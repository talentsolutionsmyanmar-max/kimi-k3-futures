"""K3 live engine — tick-level mark prices + Entry/SL/TP touch detection.

Dependency-free (stdlib only). Primary feed: Binance USDT-M futures websocket
combined stream `!markPrice@arr@1s` (every symbol, ~1s cadence, one socket).
Fallback: REST poll of /fapi/v1/premiumIndex every 2s if the socket keeps
failing; the engine keeps retrying the websocket in the background.

Outputs (under reports/):
  live_prices.json    — latest mark prices {ts, source, prices{SYM: px}}
  stream_events.jsonl — one JSON per detected touch event
  stream_alert.json   — current alert signature + events (for the alarm task)
  live_state.json     — dedupe state (which setup/event already fired)
  livefeed.log        — runtime log

Touch detection: price crossing Entry / Stop / TP1-3 of any ACTIVE or WATCH
setup from the latest scanner snapshot. ENTRY alerts are only alert-worthy
inside a non-caution kill zone; STOP/TP events always are.

Run:  python3 k3/livefeed.py        (or via the launchd agent)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from k3.killzones import session_state  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
SNAPSHOTS = REPORTS / "live_snapshots.jsonl"
PRICES_OUT = REPORTS / "live_prices.json"
EVENTS_OUT = REPORTS / "stream_events.jsonl"
ALERT_OUT = REPORTS / "stream_alert.json"
STATE_FILE = REPORTS / "live_state.json"
LOG_FILE = REPORTS / "livefeed.log"

# NOTE: fstream.binance.com completes the handshake from this network but never
# delivers frames; fstream.binancefuture.com streams correctly (verified live).
WS_HOST = "fstream.binancefuture.com"
WS_PATH = "/stream?streams=!markPrice@arr@1s"
REST_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

HEARTBEAT_SEC = 30          # reconnect if no message this long
REST_FALLBACK_AFTER = 3     # consecutive ws failures before REST mode
WS_RETRY_SEC = 120          # while in REST mode, retry ws this often
PRICE_WRITE_MIN_SEC = 1.0   # throttle live_prices.json writes


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- websocket

class WsError(Exception):
    pass


class MarkPriceWs:
    """Minimal RFC6455 client for Binance futures combined streams."""

    def __init__(self, host: str = WS_HOST, path: str = WS_PATH, timeout: int = 15):
        self.host, self.path, self.timeout = host, path, timeout
        self.sock = None

    def connect(self) -> None:
        raw = socket.create_connection((self.host, 443), timeout=self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {self.path} HTTP/1.1\r\nHost: {self.host}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WsError("handshake: connection closed")
            resp += chunk
        if b" 101" not in resp.split(b"\r\n", 1)[0]:
            raise WsError(f"handshake rejected: {resp.split(chr(13).encode())[0][:80]}")

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise WsError("socket closed")
            buf += chunk
        return buf

    def _send_pong(self, payload: bytes) -> None:
        mask = os.urandom(4)
        n = len(payload)
        header = bytearray([0x8A])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_text(self) -> str:
        """Return one complete text message; answers pings; raises on close."""
        data = b""
        while True:
            b1, b2 = self._read_exact(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(n) if n else b""
            if opcode == 0x9:                      # ping
                self._send_pong(payload)
                continue
            if opcode == 0x8:                      # close
                raise WsError("server closed connection")
            if opcode in (0x1, 0x0):               # text / continuation
                data += payload
                if fin:
                    return data.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None


# ------------------------------------------------------------------ engine

def rest_prices() -> dict:
    with urllib.request.urlopen(REST_URL, timeout=10) as r:
        rows = json.loads(r.read().decode())
    return {row["s"]: float(row["markPrice"]) for row in rows if "markPrice" in row}


def latest_setups() -> tuple:
    """(mtime, setups) from the newest scanner snapshot."""
    try:
        mtime = SNAPSHOTS.stat().st_mtime
        with SNAPSHOTS.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-3:]
        snap = None
        for line in reversed(lines):
            line = line.strip()
            if line:
                snap = json.loads(line)
                break
    except Exception:
        return 0.0, []
    if not snap:
        return 0.0, []
    setups = []
    for profile, rows in (snap.get("profiles") or {}).items():
        for t in rows or []:
            if t.get("status") in ("ACTIVE", "WATCH") and t.get("entry") and t.get("stop"):
                setups.append({
                    "key": f"{profile}|{t.get('symbol')}|{t.get('direction')}|{t.get('entry')}|{t.get('signal_bar_time')}",
                    "profile": profile,
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "status": t.get("status"),
                    "timeframe": t.get("timeframe"),
                    "k3_score": t.get("k3_score"),
                    "entry": t.get("entry"),
                    "stop": t.get("stop"),
                    "tps": [tp.get("price") for tp in (t.get("tp_ladder") or [])],
                    "risk_usd": t.get("risk_usd"),
                    "quantity": t.get("quantity"),
                })
    return mtime, setups


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"fired": {}}


def detect_touches(setups, prices, prev, state):
    """Return list of new touch events; update state['fired']."""
    events = []
    fired = state.setdefault("fired", {})
    live_keys = {s["key"] for s in setups}
    for k in list(fired):                      # forget setups no longer live
        if k not in live_keys:
            del fired[k]
    ss = session_state()
    in_zone = ss["in_kill_zone"] and not ss["caution"]
    zone = "+".join(ss["active"]) or None

    for s in setups:
        sym = s["symbol"]
        cur = prices.get(sym)
        old = prev.get(sym)
        if cur is None:
            continue
        levels = [("ENTRY", s["entry"], in_zone), ("STOP", s["stop"], True)]
        for i, tp in enumerate(s["tps"], 1):
            if tp:
                levels.append((f"TP{i}", tp, True))
        seen = fired.setdefault(s["key"], [])
        for name, level, alertworthy in levels:
            if name in seen or not level:
                continue
            touched = (old is not None and (old - level) * (cur - level) <= 0) \
                      or abs(cur - level) / level < 0.0002
            if touched:
                seen.append(name)
                events.append({
                    "utc": datetime.now(timezone.utc).isoformat(),
                    "event": f"{name}_{'HIT' if name != 'ENTRY' else 'TOUCH'}",
                    "symbol": sym,
                    "direction": s["direction"],
                    "profile": s["profile"],
                    "status": s["status"],
                    "timeframe": s["timeframe"],
                    "level_price": level,
                    "mark_price": cur,
                    "k3_score": s["k3_score"],
                    "risk_usd": s["risk_usd"],
                    "quantity": s["quantity"],
                    "kill_zone": zone,
                    "in_kill_zone": bool(zone),
                    "alert": bool(alertworthy),
                })
    return events


def publish_alert(events) -> None:
    worthy = [e for e in events if e["alert"]]
    if not worthy:
        return
    sig = hashlib.sha256(
        "\n".join(f"{e['symbol']}|{e['event']}|{e['level_price']}" for e in worthy).encode()
    ).hexdigest()[:16]
    _atomic_write_json(ALERT_OUT, {
        "signature": sig,
        "at": datetime.now(timezone.utc).isoformat(),
        "events": worthy,
    })


def record_events(events) -> None:
    if not events:
        return
    with EVENTS_OUT.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    publish_alert(events)


def run() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    log("K3 live engine starting")
    state = load_state()
    prices: dict = {}
    snap_mtime, setups = 0.0, []
    last_write, last_msg = 0.0, time.time()
    ws_fails, mode, last_ws_try = 0, "ws", 0.0
    ws = None

    while True:
        try:
            # refresh setup list when the scanner writes a new snapshot
            m, new_setups = latest_setups()
            if m != snap_mtime:
                snap_mtime, setups = m, new_setups
                log(f"setups loaded: {len(setups)} from snapshot")

            if mode == "rest":
                prices = rest_prices()
                time.sleep(2.0)
                if time.time() - last_ws_try > WS_RETRY_SEC:
                    mode, last_ws_try = "ws", time.time()
                    log("retrying websocket")
                    continue
            else:
                if ws is None:
                    ws = MarkPriceWs()
                    ws.connect()
                    ws.sock.settimeout(HEARTBEAT_SEC)
                    last_msg = time.time()
                    log("websocket connected (!markPrice@arr@1s)")
                msg = ws.recv_text()
                last_msg = time.time()
                payload = json.loads(msg).get("data") or []
                # the arr stream alternates full-crypto and stock-index chunks;
                # merge so one chunk never wipes the other's symbols
                prices.update({row["s"]: float(row["p"]) for row in payload if "p" in row})
                ws_fails = 0

            if not prices:
                continue

            now = time.time()
            if now - last_write >= PRICE_WRITE_MIN_SEC:
                _atomic_write_json(PRICES_OUT, {
                    "ts": now,
                    "utc": datetime.now(timezone.utc).isoformat(),
                    "source": mode,
                    "prices": prices,
                })
                last_write = now

            prev = state.setdefault("prev", {})
            events = detect_touches(setups, prices, prev, state)
            prev.update({s: p for s, p in prices.items() if s in {x["symbol"] for x in setups}})
            if events:
                record_events(events)
                for e in events:
                    log(f"EVENT {e['event']} {e['symbol']} {e['direction']} @ {e['mark_price']} "
                        f"(level {e['level_price']}) zone={e['kill_zone']} alert={e['alert']}")
            if events or now - state.get("_saved", 0) > 60:
                state["_saved"] = now
                state["prev"] = {k: v for k, v in prev.items()}
                _atomic_write_json(STATE_FILE, state)

        except (WsError, socket.timeout, TimeoutError, OSError) as e:
            log(f"feed error: {e}")
            ws_fails += 1
            if ws:
                ws.close()
                ws = None
            if ws_fails >= REST_FALLBACK_AFTER and mode == "ws":
                mode = "rest"
                log("switching to REST fallback (2s poll)")
            time.sleep(min(5 * ws_fails, 30))
        except Exception as e:  # never die
            log(f"unexpected: {e!r}")
            time.sleep(5)


if __name__ == "__main__":
    run()

"""K3 universe screener — find game-changer pairs beyond the volume top-10.

High 24h quote volume is necessary (you must be able to get in and out) but it
is NOT the opportunity. A scalping/day-trading "game changer" pair has:

  range_pct      24h high-low range / vwap   — actual tradable volatility
  tape activity  trade count                 — a living tape, not a ghost book
  drift          |last/vwap - 1|             — intraday displacement quality
  chg24          |24h price change|          — regime movement
  funding        current funding rate        — crowding (extreme = penalty)

Scores are z-scored across the whole USDT-M perp market and combined:
  0.35·range + 0.20·tape + 0.20·liquidity(log) + 0.15·drift + 0.10·chg24
with a hard liquidity floor ($20M quote volume) and a crowding penalty for
|funding| > 0.10%.

Output: ranked candidates, each flagged IN_UNIVERSE (already traded by K3) or
CANDIDATE (game changer the volume top-10 misses). Research before adding —
every CANDIDATE should pass `backtest` + `leaktest` before promotion.
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

from .config import STABLE_LIKE

TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

MIN_QUOTE_VOL = 20_000_000.0      # $20M 24h — executable floor
FUNDING_CROWDED = 0.001           # 0.10% — crowding penalty threshold


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "k3-screener/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _z(xs: List[float]) -> List[float]:
    n = len(xs)
    if n < 2:
        return [0.0] * n
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / n) or 1.0
    return [(x - mu) / sd for x in xs]


def screen(top_n: int = 25) -> Dict[str, Any]:
    tickers = _get(TICKER_URL)
    premium = {p["symbol"]: float(p.get("lastFundingRate", 0) or 0) for p in _get(PREMIUM_URL)}

    rows = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym.replace("USDT", "") in STABLE_LIKE:
            continue
        qv = float(t.get("quoteVolume", 0) or 0)
        if qv < MIN_QUOTE_VOL:
            continue
        last = float(t.get("lastPrice", 0) or 0)
        vwap = float(t.get("weightedAvgPrice", 0) or 0)
        high = float(t.get("highPrice", 0) or 0)
        low = float(t.get("lowPrice", 0) or 0)
        if not (last and vwap and high and low):
            continue
        rows.append({
            "symbol": sym,
            "quote_vol_24h": qv,
            "range_pct": (high - low) / vwap * 100.0,
            "chg24_pct": abs(float(t.get("priceChangePercent", 0) or 0)),
            "drift_pct": abs(last / vwap - 1.0) * 100.0,
            "trades_24h": int(t.get("count", 0) or 0),
            "funding": premium.get(sym),
        })

    z_vol = _z([math.log10(r["quote_vol_24h"]) for r in rows])
    z_rng = _z([r["range_pct"] for r in rows])
    z_tape = _z([math.log10(max(r["trades_24h"], 1)) for r in rows])
    z_drf = _z([r["drift_pct"] for r in rows])
    z_chg = _z([r["chg24_pct"] for r in rows])

    for i, r in enumerate(rows):
        score = (0.20 * z_vol[i] + 0.35 * z_rng[i] + 0.20 * z_tape[i]
                 + 0.15 * z_drf[i] + 0.10 * z_chg[i])
        f = r["funding"]
        r["crowded"] = bool(f is not None and abs(f) >= FUNDING_CROWDED)
        if r["crowded"]:
            score -= 0.75
        r["score"] = round(score, 3)

    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[:top_n]
    for r in top:
        r["quote_vol_24h"] = round(r["quote_vol_24h"])
        r["range_pct"] = round(r["range_pct"], 2)
        r["chg24_pct"] = round(r["chg24_pct"], 2)
        r["drift_pct"] = round(r["drift_pct"], 3)
        if r["funding"] is not None:
            r["funding_pct"] = round(r["funding"] * 100, 4)
        del r["funding"]

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "perps_scanned": len(rows),
        "liquidity_floor_usd": MIN_QUOTE_VOL,
        "candidates": top,
    }


def print_report(res: Dict[str, Any], universe: List[str]) -> None:
    uni = set(universe)
    print(f"\nK3 UNIVERSE SCREENER — {res['perps_scanned']} USDT-M perps above "
          f"${res['liquidity_floor_usd'] / 1e6:.0f}M 24h quote volume")
    print(f"{'#':>2} {'symbol':<15} {'score':>6} {'rng%':>6} {'chg24%':>7} {'tape':>9} "
          f"{'qvol$M':>8} {'fund%':>7}  flag")
    for i, r in enumerate(res["candidates"], 1):
        flag = "IN_UNIVERSE" if r["symbol"] in uni else ("CANDIDATE ★" if not r["crowded"] else "crowded")
        print(f"{i:>2} {r['symbol']:<15} {r['score']:>6.2f} {r['range_pct']:>6.2f} "
              f"{r['chg24_pct']:>7.2f} {r['trades_24h']:>9,} {r['quote_vol_24h'] / 1e6:>8.0f} "
              f"{r.get('funding_pct', 0):>7.4f}  {flag}")
    game = [r["symbol"] for r in res["candidates"] if r["symbol"] not in uni and not r["crowded"]]
    print(f"\ngame changers outside current top-10: {', '.join(game) if game else 'none right now'}")
    print("doctrine: research before adding — a CANDIDATE joins the universe only after "
          "backtest + leaktest pass on it.")

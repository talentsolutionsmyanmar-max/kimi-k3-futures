"""K3 scalp2 — SCALP resurrection via structural entry mechanics (Phase 5).

Fable5 Phase 5 spec (2026-07): the market-entry SCALP baseline is dead
(signal-bar direction accuracy < 50%, costs eat the mean payoff). Do NOT tune
thresholds. Change the MECHANICS:

  1. HARD GATES (binary, not fusion points):
       - liquidity sweep within the last K bars (sweep_low for longs)
       - displacement candle in the setup direction within the last K bars
       - context-timeframe (15m) struct_state ALIGNED with the trade direction
       - inside a non-caution kill zone (live engine parity)
       - not in a dead volatility regime (ATR percentile >= 12)
  2. LIMIT ENTRY at the OTE pocket (default 70.5% retracement of the impulse
     leg). The order rests up to `cancel_bars`; filled only if a later bar
     trades through it. No fill -> no trade. Fill price = limit (never better).
  3. STRUCTURAL STOP beyond the impulse origin (impulse_low - 0.3*ATR for
     longs), not an arbitrary ATR multiple from a market entry.
  4. FEES: maker 0.02% on limit entries and TP limit exits; taker 0.075%
     (commission+slippage) with 0.1*ATR gap-through on stops; taker on time
     exits. Funding drag charged as in the baseline backtester.

Comparison harness runs this side-by-side with the market-entry baseline on
the same bars. Whatever the outcome, it is reported.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from . import data
from .backtest import STOP_GAP_ATR, _entry_session, _tradable_now, backtest_symbol
from .config import Profile, TF_MINUTES
from .signals import score_dataframe
from .structure import build_structure

MAKER_FEE = 0.0002          # 0.02% limit/maker
FUNDING_INTERVAL_MIN = 480
SETUP_LOOKBACK = 6          # sweep & displacement must occur within last 6 bars
DEFAULT_CANCEL_BARS = 12    # 5m: order rests max 1h
DEAD_ATR_PCTILE = 12.0

MAJORS5 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def _context_struct_state(df: pd.DataFrame, p: Profile, symbol: str) -> pd.Series:
    """Causal context-TF struct_state mapped onto base bars.

    A context bar opened at T is knowable only at T + tf_minutes; base bars
    strictly before that timestamp must not see it.
    """
    ctx_tf = p.context_tf
    ctx_min = TF_MINUTES.get(ctx_tf, 15)
    base_min = TF_MINUTES.get(p.timeframe, 5)
    need = min(1500, len(df) * base_min // ctx_min + 120)
    sym_ctx = data.klines(symbol, ctx_tf, need)
    if len(sym_ctx) < 60:
        return pd.Series(np.nan, index=df.index)
    ctx = build_structure(sym_ctx, p)
    avail = (ctx["timestamp"] + pd.Timedelta(minutes=ctx_min)).astype("datetime64[ms, UTC]")
    m = pd.merge_asof(
        pd.DataFrame({"ts": df["timestamp"].astype("datetime64[ms, UTC]")}),
        pd.DataFrame({"avail": avail, "ctx_state": ctx["struct_state"].values}),
        left_on="ts", right_on="avail", direction="backward",
    )
    return m["ctx_state"].fillna(0.0).astype(float).set_axis(df.index)


def backtest_scalp2(symbol: str, p: Profile, limit: int = 1500,
                    df: Optional[Any] = None, ote_level: float = 0.705,
                    cancel_bars: int = DEFAULT_CANCEL_BARS) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    r = p.risk
    if df is None:
        df = data.klines(sym, p.timeframe, limit)
    if len(df) < 200:
        return {"symbol": sym, "error": f"insufficient bars ({len(df)})"}
    df = score_dataframe(build_structure(df, p), p)
    df = df.copy()
    df["ctx_state"] = _context_struct_state(df, p, sym).values

    from .data import atr_percentile  # local import to keep header lean
    atr_pct = atr_percentile(df, r.atr_period, p.atr_pctile_window).values

    capital = r.initial_capital
    equity: List[float] = []
    trades: List[Dict[str, Any]] = []
    pos = None          # open position
    order = None        # resting limit order
    tf_min = TF_MINUTES.get(p.timeframe, 5)
    bars_per_funding = max(1, FUNDING_INTERVAL_MIN // tf_min)

    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    atr = df["atr"].values
    sweep_lo = df["sweep_low"].values; sweep_hi = df["sweep_high"].values
    disp = df["displacement"].values
    ctx = df["ctx_state"].values
    ih = df["impulse_high"].values; il = df["impulse_low"].values
    dts = pd.to_datetime(df["timestamp"], utc=True).values
    times = df["timestamp"].astype(str).values

    def taker(x: float) -> float:
        return abs(x) * (r.commission + r.slippage)

    def maker(x: float) -> float:
        return abs(x) * MAKER_FEE

    def try_cancel_order(i: int) -> None:
        nonlocal order
        if order is not None and i - order["placed_at"] > cancel_bars:
            order = None

    for i in range(80, len(df) - 1):
        # ---------- manage open position ----------
        if pos is not None:
            pos["bars"] += 1
            side, entry, stop = pos["side"], pos["entry"], pos["stop"]
            sd = pos["stop_dist"]
            a = atr[i] if atr[i] > 0 else entry * 0.002
            exit_price, exit_reason, exit_maker = None, None, False

            if pos["bars"] % bars_per_funding == 0:
                fcost = pos["qty_left"] * c[i] * r.funding_cost_per_8h
                capital -= fcost
                pos["realized"] -= fcost
                pos["funding_paid"] += fcost

            stopped = (side == 1 and l[i] <= stop) or (side == -1 and h[i] >= stop)
            if stopped:
                exit_price, exit_reason = stop - side * STOP_GAP_ATR * a, "STOP"
            else:
                for k, (rr, pct) in enumerate(zip(r.tp_r, r.tp_pct)):
                    if pos["tps"][k]:
                        continue
                    tp = entry + side * rr * sd
                    if (side == 1 and h[i] >= tp) or (side == -1 and l[i] <= tp):
                        pos["tps"][k] = True
                        part = pos["qty_left"] if k == 2 else min(pos["qty0"] * pct, pos["qty_left"])
                        pnl = side * (tp - entry) * part - maker(tp * part)   # TP limit = maker
                        capital += pnl
                        pos["realized"] += pnl
                        pos["qty_left"] -= part
                        if k == 0 and r.trail_after_tp1:
                            pos["trail"] = True
                        if pos["qty_left"] <= 1e-12:
                            exit_price, exit_reason, exit_maker = tp, "TP_LADDER_DONE", True
                            break
                if exit_price is None and pos["trail"]:
                    ns = c[i] - side * r.trail_atr_mult * a
                    pos["stop"] = max(pos["stop"], ns) if side == 1 else min(pos["stop"], ns)
                if exit_price is None and pos["bars"] >= r.max_hold_bars:
                    exit_price, exit_reason = c[i], "TIME_EXIT"

            if exit_price is not None and pos["qty_left"] > 1e-12:
                fee_fn = maker if exit_maker else taker
                pnl = side * (exit_price - entry) * pos["qty_left"] - fee_fn(exit_price * pos["qty_left"])
                capital += pnl
                pos["realized"] += pnl
                pos["qty_left"] = 0.0

            if pos["qty_left"] <= 1e-12:
                trades.append({
                    "symbol": sym, "side": "LONG" if side == 1 else "SHORT",
                    "entry_time": pos["entry_time"], "exit_time": times[i],
                    "entry": round(entry, 8), "exit_reason": exit_reason,
                    "pnl": round(pos["realized"], 2), "tps_hit": sum(pos["tps"]),
                    "funding_paid": round(pos["funding_paid"], 2),
                    "bars_held": pos["bars"], "session": pos.get("session", "NONE"),
                })
                pos = None

        # ---------- manage resting limit order ----------
        if order is not None and pos is None:
            side = order["side"]
            filled = (side == 1 and l[i] <= order["limit"]) or (side == -1 and h[i] >= order["limit"])
            if filled:
                entry = order["limit"]               # never assume better than the limit
                sd = order["stop_dist"]
                qty = min((capital * r.risk_per_trade) / sd, (capital * r.max_leverage) / entry)
                capital -= maker(entry * qty)
                pos = {
                    "side": side, "entry": entry, "stop_dist": sd, "entry_time": times[i],
                    "qty0": qty, "qty_left": qty, "stop": order["stop"],
                    "tps": [False, False, False], "bars": 0, "trail": False,
                    "realized": -maker(entry * qty), "funding_paid": 0.0,
                    "session": order["session"],
                }
                order = None
            else:
                try_cancel_order(i)

        # ---------- detect new setup (hard gates) ----------
        if pos is None and order is None and capital > 0:
            if not _tradable_now(dts[i]):
                continue
            if atr_pct[i] < DEAD_ATR_PCTILE:
                continue
            lb = slice(max(0, i - SETUP_LOOKBACK + 1), i + 1)
            bull_body = c[i] > o[i]
            for side in (1, -1):
                swept = bool(sweep_lo[lb].any()) if side == 1 else bool(sweep_hi[lb].any())
                disp_ok = bool(disp[lb].any()) and (bull_body if side == 1 else not bull_body)
                ctx_ok = (ctx[i] > 0) if side == 1 else (ctx[i] < 0)
                if not (swept and disp_ok and ctx_ok):
                    continue
                a = atr[i] if atr[i] > 0 else c[i] * 0.002
                rng = ih[i] - il[i]
                if not np.isfinite(rng) or rng <= 0:
                    continue
                if side == 1:
                    limit = ih[i] - rng * ote_level
                    stop = il[i] - 0.3 * a
                else:
                    limit = il[i] + rng * ote_level
                    stop = ih[i] + 0.3 * a
                sd = (limit - stop) * side
                if sd < 0.5 * a:          # degenerate pocket — skip
                    continue
                # the limit must be BELOW current price for a long (retracement entry)
                if (side == 1 and limit >= c[i]) or (side == -1 and limit <= c[i]):
                    continue
                order = {"side": side, "limit": float(limit), "stop": float(stop),
                         "stop_dist": float(sd), "placed_at": i,
                         "session": _entry_session(dts[i])}
                break

        mtm = 0.0 if pos is None else pos["side"] * (c[i] - pos["entry"]) * pos["qty_left"]
        equity.append(capital + mtm)

    if not trades:
        return {"symbol": sym, "trades": 0, "note": "no completed trades (setups may be rare — that is the point)"}

    pnls = np.array([t["pnl"] for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    eq = np.array(equity) if equity else np.array([r.initial_capital])
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / np.maximum(peak, 1e-9)).max())
    by_session: Dict[str, List[float]] = {}
    for t in trades:
        by_session.setdefault(t.get("session", "NONE"), []).append(t["pnl"])

    return {
        "symbol": sym, "profile": f"{p.name}2-OTE", "timeframe": p.timeframe, "bars": len(df),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "net_pnl_usd": round(float(pnls.sum()), 2),
        "return_pct": round((capital / r.initial_capital - 1) * 100, 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf"), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "funding_paid_total": round(sum(t["funding_paid"] for t in trades), 2),
        "pnl_by_session": {k: round(float(np.sum(v)), 2) for k, v in sorted(by_session.items())},
        "trades_by_session": {k: len(v) for k, v in sorted(by_session.items())},
        "final_capital": round(capital, 2),
        "trade_log": trades[-30:],
    }


def compare(symbols: List[str], p: Profile, limit: int = 1500,
            ote_level: float = 0.705, cancel_bars: int = DEFAULT_CANCEL_BARS) -> Dict[str, Any]:
    """Side-by-side: market-entry baseline vs OTE limit-entry scalp2, same bars."""
    rows: List[Dict[str, Any]] = []
    for s in symbols:
        sym = s.upper().replace("/", "")
        try:
            raw = data.klines(sym, p.timeframe, limit)
            base = backtest_symbol(sym, p, df=raw)
            new = backtest_scalp2(sym, p, df=raw, ote_level=ote_level, cancel_bars=cancel_bars)
            rows.append({"symbol": sym, "baseline": base, "scalp2": new})
        except Exception as e:  # noqa: BLE001
            rows.append({"symbol": sym, "error": str(e)})
    def _tot(key: str, field: str) -> float:
        return float(sum(r[key].get(field, 0) for r in rows if key in r and r[key].get("trades", 0) > 0))
    summary = {
        "baseline": {"trades": int(_tot("baseline", "trades")), "net_pnl_usd": round(_tot("baseline", "net_pnl_usd"), 2)},
        "scalp2": {"trades": int(_tot("scalp2", "trades")), "net_pnl_usd": round(_tot("scalp2", "net_pnl_usd"), 2)},
    }
    return {
        "profile": p.name, "timeframe": p.timeframe, "ote_level": ote_level,
        "cancel_bars": cancel_bars, "maker_fee": MAKER_FEE,
        "summary": summary, "per_symbol": rows,
    }


def print_compare(res: Dict[str, Any]) -> None:
    print(f"\n=== K3 SCALP2 vs BASELINE | {res['profile']} {res['timeframe']} "
          f"OTE={res['ote_level']} cancel={res['cancel_bars']}b maker={res['maker_fee']:.03%} ===")
    print(f"{'symbol':<12}{'base n':>7}{'base $':>11}{'base PF':>9}"
          f"{'s2 n':>6}{'s2 $':>11}{'s2 PF':>9}{'s2 win%':>9}")
    for r in res["per_symbol"]:
        if "baseline" not in r:
            print(f"{r['symbol']:<12} {r.get('error')}")
            continue
        b, s = r["baseline"], r["scalp2"]
        print(f"{r['symbol']:<12}{b.get('trades', 0):>7}{b.get('net_pnl_usd', 0):>11,.2f}"
              f"{str(b.get('profit_factor', '-')):>9}{s.get('trades', 0):>6}"
              f"{s.get('net_pnl_usd', 0):>11,.2f}{str(s.get('profit_factor', '-')):>9}"
              f"{str(s.get('win_rate', '-')):>9}")
    sm = res["summary"]
    print(f"\n{'TOTAL':<12}{sm['baseline']['trades']:>7}{sm['baseline']['net_pnl_usd']:>11,.2f}"
          f"{'':>9}{sm['scalp2']['trades']:>6}{sm['scalp2']['net_pnl_usd']:>11,.2f}")

"""K3 backtester — event-driven, funding-aware.

Improvements over the lineage backtester:
  - entries sized by conviction (score risk multiplier)
  - funding cost charged on open notional every 8h of holding (perp reality)
  - WATCH-tier entries allowed at reduced risk (matches live engine)
  - per-trade K3 score logging so research mode can correlate score <-> outcome
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from . import data
from .config import Profile, TF_MINUTES
from .risk import score_risk_multiplier
from .signals import score_dataframe
from .structure import build_structure

FUNDING_INTERVAL_MIN = 480  # 8h


def backtest_symbol(symbol: str, p: Profile, limit: int = 1500,
                    df: Optional[Any] = None, enter_tiers=("ACTIVE", "WATCH")) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    r = p.risk
    if df is None:
        df = data.klines(sym, p.timeframe, limit)
    if len(df) < 150:
        return {"symbol": sym, "error": f"insufficient bars ({len(df)})"}
    df = score_dataframe(build_structure(df, p), p)

    capital = r.initial_capital
    equity: List[float] = []
    trades: List[Dict[str, Any]] = []
    pos = None
    tf_min = TF_MINUTES.get(p.timeframe, 15)
    bars_per_funding = max(1, FUNDING_INTERVAL_MIN // tf_min)

    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    atr, dirs, scores, tiers = df["atr"].values, df["k3_dir"].values, df["k3_score"].values, df["k3_tier"].values
    times = df["timestamp"].astype(str).values

    def fee(x: float) -> float:
        return abs(x) * (r.commission + r.slippage)

    for i in range(80, len(df) - 1):
        if pos is not None:
            pos["bars"] += 1
            side = pos["side"]
            entry, stop = pos["entry"], pos["stop"]
            sd = pos["stop_dist"]
            a = atr[i] if atr[i] > 0 else entry * 0.002
            exit_price, exit_reason = None, None

            # funding drag on open notional
            if pos["bars"] % bars_per_funding == 0:
                fcost = pos["qty_left"] * c[i] * r.funding_cost_per_8h
                capital -= fcost
                pos["realized"] -= fcost
                pos["funding_paid"] += fcost

            stopped = (side == 1 and l[i] <= stop) or (side == -1 and h[i] >= stop)
            if stopped:
                exit_price, exit_reason = stop, "STOP"
            else:
                for k, (rr, pct) in enumerate(zip(r.tp_r, r.tp_pct)):
                    if pos["tps"][k]:
                        continue
                    tp = entry + side * rr * sd
                    if (side == 1 and h[i] >= tp) or (side == -1 and l[i] <= tp):
                        pos["tps"][k] = True
                        part = pos["qty_left"] if k == 2 else min(pos["qty0"] * pct, pos["qty_left"])
                        pnl = side * (tp - entry) * part - fee(tp * part)
                        capital += pnl
                        pos["realized"] += pnl
                        pos["qty_left"] -= part
                        if k == 0 and r.trail_after_tp1:
                            pos["trail"] = True
                        if pos["qty_left"] <= 1e-12:
                            exit_price, exit_reason = tp, "TP_LADDER_DONE"
                            break
                if exit_price is None and pos["trail"]:
                    ns = c[i] - side * r.trail_atr_mult * a
                    pos["stop"] = max(pos["stop"], ns) if side == 1 else min(pos["stop"], ns)
                if exit_price is None and pos["bars"] >= r.max_hold_bars:
                    exit_price, exit_reason = c[i], "TIME_EXIT"
                # K3: bail early if fusion flips hard against us
                if exit_price is None and pos["bars"] >= 3 and int(dirs[i]) == -side and scores[i] >= p.tier_active:
                    exit_price, exit_reason = c[i], "SIGNAL_FLIP"

            if exit_price is not None and pos["qty_left"] > 1e-12:
                pnl = side * (exit_price - entry) * pos["qty_left"] - fee(exit_price * pos["qty_left"])
                capital += pnl
                pos["realized"] += pnl
                pos["qty_left"] = 0.0

            if pos["qty_left"] <= 1e-12:
                trades.append({
                    "symbol": sym, "side": "LONG" if side == 1 else "SHORT",
                    "entry_time": pos["entry_time"], "exit_time": times[i],
                    "entry": round(entry, 8), "exit_reason": exit_reason,
                    "k3_score": pos["score"], "tier": pos["tier"],
                    "pnl": round(pos["realized"], 2), "tps_hit": sum(pos["tps"]),
                    "funding_paid": round(pos["funding_paid"], 2),
                    "bars_held": pos["bars"],
                })
                pos = None

        if pos is None and int(dirs[i]) != 0 and str(tiers[i]) in enter_tiers and capital > 0:
            side = int(dirs[i])
            a = atr[i] if atr[i] > 0 else c[i] * 0.002
            sd = r.atr_stop_mult * a
            entry = o[i + 1] * (1 + side * r.slippage)
            mult = score_risk_multiplier(float(scores[i]), p)
            qty = (capital * r.risk_per_trade * mult) / sd
            qty = min(qty, (capital * r.max_leverage) / entry)
            capital -= fee(entry * qty)
            pos = {
                "side": side, "entry": entry, "stop_dist": sd, "entry_time": times[i + 1],
                "qty0": qty, "qty_left": qty, "stop": entry - side * sd,
                "tps": [False, False, False], "bars": 0, "trail": False,
                "realized": -fee(entry * qty), "funding_paid": 0.0,
                "score": float(scores[i]), "tier": str(tiers[i]),
            }

        mtm = 0.0 if pos is None else pos["side"] * (c[i] - pos["entry"]) * pos["qty_left"]
        equity.append(capital + mtm)

    if not trades:
        return {"symbol": sym, "trades": 0, "note": "no completed trades"}

    pnls = np.array([t["pnl"] for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    eq = np.array(equity) if equity else np.array([r.initial_capital])
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / np.maximum(peak, 1e-9)).max())
    by_tier: Dict[str, List[float]] = {}
    for t in trades:
        by_tier.setdefault(t["tier"], []).append(t["pnl"])

    return {
        "symbol": sym, "profile": p.name, "timeframe": p.timeframe, "bars": len(df),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "net_pnl_usd": round(float(pnls.sum()), 2),
        "return_pct": round((capital / r.initial_capital - 1) * 100, 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf"), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "funding_paid_total": round(sum(t["funding_paid"] for t in trades), 2),
        "pnl_by_tier": {k: round(float(np.sum(v)), 2) for k, v in by_tier.items()},
        "final_capital": round(capital, 2),
        "trade_log": trades[-30:],
    }


def backtest_universe(symbols: List[str], p: Profile, limit: int = 1500) -> Dict[str, Any]:
    per = [backtest_symbol(s, p, limit) for s in symbols]
    ok = [x for x in per if x.get("trades", 0) > 0]
    return {
        "profile": p.name, "timeframe": p.timeframe,
        "symbols_tested": len(per), "symbols_with_trades": len(ok),
        "total_trades": sum(x["trades"] for x in ok),
        "avg_win_rate": round(float(np.mean([x["win_rate"] for x in ok])), 1) if ok else 0.0,
        "total_net_pnl_usd": round(sum(x["net_pnl_usd"] for x in ok), 2),
        "avg_return_pct": round(float(np.mean([x["return_pct"] for x in ok])), 2) if ok else 0.0,
        "per_symbol": per,
    }

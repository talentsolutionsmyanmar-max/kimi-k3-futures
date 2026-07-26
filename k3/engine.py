"""K3 setup engine: market structure + fusion + gates + trade plan, per symbol/profile."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import data
from .config import Profile, TF_MINUTES
from .killzones import apply_kill_zone_overlay, session_state
from .risk import build_trade_plan
from .signals import apply_positioning_overlay, score_dataframe
from .structure import build_structure


def _htf_bias(symbol: str, context_tf: str) -> int:
    try:
        df = data.klines(symbol, context_tf, 120)
        if len(df) < 60:
            return 0
        f = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        s = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        return 1 if f > s else (-1 if f < s else 0)
    except Exception:
        return 0


def _market_gates(symbol: str, p: Profile) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True, "reasons": []}
    try:
        qv = data.quote_volume_24h(symbol)
        out["quote_volume_24h"] = qv
        if qv < p.min_quote_vol_24h:
            out["ok"] = False
            out["reasons"].append(f"liquidity {qv:,.0f} < {p.min_quote_vol_24h:,.0f}")
    except Exception as e:
        out["reasons"].append(f"liquidity_warn:{type(e).__name__}")
    try:
        fr = data.funding_now(symbol)
        out["funding_rate"] = fr
        if fr is not None and abs(fr) > p.max_abs_funding:
            out["ok"] = False
            out["reasons"].append(f"|funding|={abs(fr):.5f} > {p.max_abs_funding:.5f}")
    except Exception as e:
        out["reasons"].append(f"funding_warn:{type(e).__name__}")
    if not out["reasons"]:
        out["reasons"].append("gates_pass")
    return out


def build_setup(symbol: str, p: Profile, capital: float, klines_limit: int = 500,
                lookback_bars: int = 6) -> Dict[str, Any]:
    sym = symbol.upper().replace("/", "")
    out: Dict[str, Any] = {"symbol": sym, "profile": p.name, "timeframe": p.timeframe}

    df = data.klines(sym, p.timeframe, klines_limit)
    if len(df) < 120:
        out.update(status="NO_DATA", reason=f"only {len(df)} bars")
        return out

    df = build_structure(df, p)
    df = score_dataframe(df, p)

    gates = _market_gates(sym, p)
    out["market_gates"] = gates

    # most recent bar with any directional interest within lookback (closed bars only)
    end = len(df) - 2
    idx: Optional[int] = None
    for i in range(end, max(end - lookback_bars, -1), -1):
        if i >= 0 and int(df["k3_dir"].iloc[i]) != 0:
            idx = i
            break
    if idx is None:
        # report the strongest sub-threshold lean for the watchlist
        tail = df.iloc[max(end - 24, 0):end + 1]
        best_side = "LONG" if tail["k3_long"].max() >= tail["k3_short"].max() else "SHORT"
        best_score = float(max(tail["k3_long"].max(), tail["k3_short"].max()))
        out.update(status="STANDBY", reason="no directional signal in lookback",
                   watch={"side": best_side, "best_subthreshold_score": round(best_score, 1)})
        return out

    row = df.iloc[idx]
    direction = int(row["k3_dir"])
    score = float(row["k3_score"])
    tier = str(row["k3_tier"])
    entry = float(row["close"])
    age_bars = end - idx
    age_min = age_bars * TF_MINUTES.get(p.timeframe, 15)

    # HTF alignment: counter-trend entries are demoted one tier
    htf = _htf_bias(sym, p.context_tf)
    htf_conflict = htf != 0 and htf != direction
    if htf_conflict and tier == "ACTIVE":
        tier = "WATCH"

    # live positioning overlay (funding z + OI delta)
    fz = data.funding_zscore(sym)
    oi_d = data.oi_delta_pct(sym, "1h")
    price_up = float(df["close"].iloc[end]) >= float(df["close"].iloc[max(end - 12, 0)])
    overlay = apply_positioning_overlay(direction, score, funding_z=fz, oi_delta=oi_d,
                                        price_up=price_up, p=p)
    score = min(100.0, score + overlay["score_adj"])
    if overlay["blocked"]:
        tier = "STANDBY"

    # kill-zone session overlay (ICT discipline)
    kz = apply_kill_zone_overlay(direction, score, tier, p.name)
    score = kz["score"]
    tier = kz["tier"]

    # market gates failure -> standby (Fable5 provenance doctrine)
    if not gates["ok"]:
        tier = "STANDBY"

    plan = build_trade_plan(direction=direction, entry=entry, atr=float(row["atr"]),
                            score=score, capital=capital, p=p)

    group_read = {g: float(row[f"g_{g}"]) for g in
                  ["structure", "liquidity", "momentum", "volatility", "positioning"]}

    out.update(
        status=tier,
        direction="LONG" if direction == 1 else "SHORT",
        k3_score=score,
        k3_score_raw=float(row["k3_score"]),
        group_scores=group_read,
        groups_agreeing=int(row["agree_long"] if direction == 1 else row["agree_short"]),
        signal_bar_time=str(row["timestamp"]),
        signal_age_bars=age_bars,
        signal_age_minutes=age_min,
        regime_adx=round(float(row["adx"]), 1),
        struct_state={1: "BULL", -1: "BEAR", 0: "NEUTRAL"}[int(row["struct_state"])],
        pd_position=round(float(row["pd_position"]) if row["pd_position"] == row["pd_position"] else 0.5, 2),
        htf_bias={1: "BULL", -1: "BEAR", 0: "NEUTRAL"}[htf],
        htf_conflict=htf_conflict,
        funding_z=round(fz, 2) if fz is not None else None,
        oi_delta_1h_pct=round(oi_d, 2) if oi_d is not None else None,
        overlay_notes=overlay["notes"] + kz["kz_notes"],
        session=kz["session"],
        trade_plan=plan,
    )
    return out


def scan_universe(symbols: List[str], p: Profile, capital: float) -> List[Dict[str, Any]]:
    results = [build_setup(s, p, capital) for s in symbols]
    rank = {"ACTIVE": 0, "WATCH": 1, "STANDBY": 2, "NO_DATA": 3}
    results.sort(key=lambda x: (rank.get(x.get("status", "NO_DATA"), 9), -x.get("k3_score", 0.0)))
    return results

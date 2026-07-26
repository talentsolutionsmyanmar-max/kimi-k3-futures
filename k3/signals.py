"""K3 signal fusion — the original core.

Five factor groups, each scored SIGNED in [-100, +100] per bar
(+ = bullish evidence, - = bearish evidence):

  G1 STRUCTURE    BOS / CHoCH / displacement / structure-state alignment
  G2 LIQUIDITY    sweeps, FVG, premium/discount position, OTE pocket, order blocks
  G3 MOMENTUM     RSI regime, EMA 20/50 alignment & slope, MACD histogram
  G4 VOLATILITY   ATR percentile regime (expansion good, dead zone & blowoff bad)
  G5 POSITIONING  taker buy ratio (per-bar flow) + funding z + OI delta (live overlay)

Composite LONG/SHORT scores = weight x positive-aligned group evidence, capped 100.
Decision tiers: ACTIVE / WATCH / STANDBY with a minimum group-agreement rule.
Hard blocks (funding extreme with direction, dead volatility) zero the score.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .config import Profile
from .data import adx, atr_percentile, rsi, wilder_atr


def _clip100(x):
    return np.clip(x, -100.0, 100.0)


def g1_structure(df: pd.DataFrame) -> np.ndarray:
    s = np.zeros(len(df))
    s += np.where(df["bos_up"], 55, 0) - np.where(df["bos_dn"], 55, 0)
    s += np.where(df["choch_up"], 75, 0) - np.where(df["choch_dn"], 75, 0)
    disp_bonus = np.where(df["displacement"], 20, 0)
    s += np.where(df["bos_up"] | df["choch_up"], disp_bonus, 0)
    s -= np.where(df["bos_dn"] | df["choch_dn"], disp_bonus, 0)
    s += df["struct_state"].values * 25            # persistent alignment tailwind
    return _clip100(s)


def g2_liquidity(df: pd.DataFrame) -> np.ndarray:
    s = np.zeros(len(df))
    s += np.where(df["sweep_low"], 65, 0) - np.where(df["sweep_high"], 65, 0)
    s += np.where(df["fvg_bull"], 35, 0) - np.where(df["fvg_bear"], 35, 0)
    pd_pos = df["pd_position"].fillna(0.5).values   # 0 discount .. 1 premium
    s += (0.5 - pd_pos) * 60                        # deep discount -> +30, deep premium -> -30
    s += np.where(df["in_ote_long"].fillna(False), 40, 0) - np.where(df["in_ote_short"].fillna(False), 40, 0)
    s += np.where(df["near_bull_ob"].fillna(False), 25, 0) - np.where(df["near_bear_ob"].fillna(False), 25, 0)
    return _clip100(s)


def g3_momentum(df: pd.DataFrame) -> np.ndarray:
    close = df["close"].astype(float)
    r = rsi(close, 14).values
    ema_f = close.ewm(span=20, adjust=False).mean()
    ema_s = close.ewm(span=50, adjust=False).mean()
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    s = np.zeros(len(df))
    s += np.clip((r - 50.0) * 2.4, -48, 48)                       # RSI 70 -> +48, RSI 30 -> -48
    align = np.sign((ema_f - ema_s).fillna(0).values)
    slope = np.sign(ema_f.diff().fillna(0).values)
    s += align * 22 + slope * 12
    s += np.sign(hist.fillna(0).values) * np.where(hist.diff().fillna(0).values * np.sign(hist.fillna(0).values) > 0, 18, 8)
    return _clip100(s)


def g4_volatility(df: pd.DataFrame, p: Profile) -> np.ndarray:
    pct = atr_percentile(df, p.risk.atr_period, p.atr_pctile_window).values
    adx_v = adx(df, p.adx_period).values
    # expansion regime (pct 30-85) + trend fuel (ADX) is direction-agnostic ENERGY;
    # sign comes from short-term drift so dead/blowoff regimes suppress both sides.
    drift = np.sign(df["close"].diff(5).fillna(0).values)
    energy = np.where((pct >= 30) & (pct <= 85), 55,
             np.where(pct < 15, -60,                            # dead market: suppress
             np.where(pct > 92, -40, 20)))                      # blowoff: suppress fresh entries
    adx_boost = np.clip((adx_v - p.adx_trend_min) * 2.0, -10, 25)
    return _clip100((energy + adx_boost) * np.where(drift == 0, 1, drift))


def g5_positioning(df: pd.DataFrame) -> np.ndarray:
    """Per-bar taker flow. Funding z / OI delta are live-only overlays (engine adds them)."""
    vol = df["volume"].replace(0.0, np.nan)
    taker_ratio = (df["taker_buy"] / vol).fillna(0.5)
    flow = taker_ratio.rolling(10, min_periods=3).mean().fillna(0.5).values
    s = np.clip((flow - 0.5) * 400, -70, 70)      # 55% taker buy over 10 bars -> +20
    return _clip100(s)


GROUP_FUNCS = {
    "structure": g1_structure,
    "liquidity": g2_liquidity,
    "momentum": g3_momentum,
    "volatility": None,      # needs profile
    "positioning": g5_positioning,
}


def score_dataframe(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    df = df.copy()
    groups: Dict[str, np.ndarray] = {
        "structure": g1_structure(df),
        "liquidity": g2_liquidity(df),
        "momentum": g3_momentum(df),
        "volatility": g4_volatility(df, p),
        "positioning": g5_positioning(df),
    }
    w = p.weights
    weights = {"structure": w.structure, "liquidity": w.liquidity,
               "momentum": w.momentum, "volatility": w.volatility, "positioning": w.positioning}

    long_score = np.zeros(len(df))
    short_score = np.zeros(len(df))
    agree_long = np.zeros(len(df), dtype=int)
    agree_short = np.zeros(len(df), dtype=int)
    for name, g in groups.items():
        long_score += weights[name] * np.clip(g, 0, None)
        short_score += weights[name] * np.clip(-g, 0, None)
        agree_long += (g > 10).astype(int)
        agree_short += (g < -10).astype(int)
        df[f"g_{name}"] = np.round(g, 1)

    # normalize: max possible = sum(weights)*100 -> rescale to 0..100
    long_score = long_score / max(1e-9, sum(weights.values()))
    short_score = short_score / max(1e-9, sum(weights.values()))

    # volatility dead-zone hard block applies to BOTH directions
    pct = atr_percentile(df, p.risk.atr_period, p.atr_pctile_window).values
    dead = pct < 12
    long_score[dead] = 0.0
    short_score[dead] = 0.0

    df["k3_long"] = np.round(np.clip(long_score, 0, 100), 1)
    df["k3_short"] = np.round(np.clip(short_score, 0, 100), 1)
    df["agree_long"] = agree_long
    df["agree_short"] = agree_short

    direction = np.where(
        (df["k3_long"] >= df["k3_short"]) & (df["k3_long"] >= p.tier_watch) & (agree_long >= p.min_groups_agree), 1,
        np.where((df["k3_short"] > df["k3_long"]) & (df["k3_short"] >= p.tier_watch) & (agree_short >= p.min_groups_agree), -1, 0),
    )
    score = np.where(direction == 1, df["k3_long"], np.where(direction == -1, df["k3_short"], 0.0))
    df["k3_dir"] = direction.astype(int)
    df["k3_score"] = np.round(score, 1)
    df["k3_tier"] = np.where(
        (direction != 0) & (score >= p.tier_active), "ACTIVE",
        np.where(direction != 0, "WATCH", "STANDBY"),
    )
    df["atr"] = wilder_atr(df, p.risk.atr_period)
    df["adx"] = adx(df, p.adx_period)
    return df


def apply_positioning_overlay(
    direction: int,
    score: float,
    *,
    funding_z: Optional[float],
    oi_delta: Optional[float],
    price_up: bool,
    p: Profile,
) -> Dict[str, Any]:
    """Live-only adjustments on the bar-score:
       - funding z extreme WITH direction -> hard block (crowded trade)
       - funding z extreme AGAINST direction -> boost (contrarian fuel)
       - OI expanding with price -> confirm; OI expanding against -> penalize
    """
    note = []
    blocked = False
    adj = 0.0
    if funding_z is not None:
        if direction == 1 and funding_z >= p.funding_z_block:
            blocked, note = True, note + [f"funding_z={funding_z:.2f} crowded-long block"]
        elif direction == -1 and funding_z <= -p.funding_z_block:
            blocked, note = True, note + [f"funding_z={funding_z:.2f} crowded-short block"]
        elif direction == 1 and funding_z <= -1.5:
            adj += 4; note.append("funding contrarian boost (shorts paying)")
        elif direction == -1 and funding_z >= 1.5:
            adj += 4; note.append("funding contrarian boost (longs paying)")
    if oi_delta is not None:
        oi_up = oi_delta > 0.3
        if oi_up and ((direction == 1) == price_up):
            adj += 3; note.append(f"OI+{oi_delta:.1f}% confirms")
        elif oi_up:
            adj -= 5; note.append(f"OI+{oi_delta:.1f}% against direction")
    return {"blocked": blocked, "score_adj": adj, "notes": note}

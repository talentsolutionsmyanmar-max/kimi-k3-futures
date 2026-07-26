"""K3 market structure engine.

Quantrex lineage gave us: swings, FVG, premium/discount, OTE, sweeps.
K3 adds what it lacked: explicit MARKET STRUCTURE STATE —
  - BOS  (break of structure, continuation)
  - CHoCH (change of character, first reversal break)
  - structure trend state machine (bull / bear / neutral)
  - displacement detection (impulsive body + range expansion validating a break)
  - order block tagging (last opposite candle before a BOS)

Everything vectorized; per-bar outputs feed the fusion scorer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Profile
from .data import wilder_atr


def _swings(df: pd.DataFrame, left: int, right: int) -> pd.DataFrame:
    """Swing highs/lows with confirmation delay.

    A swing at bar i needs `right` future bars to confirm — so the LEVEL only
    becomes knowable at bar i+right. We therefore ffill from the swing bar and
    then shift by `right`: no level is ever visible before its confirmation.
    (Fable5 audit Leak 2: previously levels were live from the swing bar itself,
    i.e. 2 bars early — look-ahead.)
    """
    df = df.copy()
    h, l = df["high"], df["low"]
    sh = pd.Series(True, index=df.index)
    sl = pd.Series(True, index=df.index)
    for k in range(1, left + 1):
        sh &= h > h.shift(k)
        sl &= l < l.shift(k)
    for k in range(1, right + 1):
        sh &= h > h.shift(-k)
        sl &= l < l.shift(-k)
    df["swing_high"] = sh.fillna(False)
    df["swing_low"] = sl.fillna(False)
    df["last_swing_high"] = pd.Series(np.where(df["swing_high"], h, np.nan), index=df.index).ffill().shift(right)
    df["last_swing_low"] = pd.Series(np.where(df["swing_low"], l, np.nan), index=df.index).ffill().shift(right)
    return df


def _structure_state(df: pd.DataFrame) -> pd.DataFrame:
    """BOS / CHoCH state machine (loop — inherently sequential)."""
    n = len(df)
    state = np.zeros(n, dtype=int)          # +1 bull, -1 bear, 0 neutral
    bos_up = np.zeros(n, dtype=bool)
    bos_dn = np.zeros(n, dtype=bool)
    choch_up = np.zeros(n, dtype=bool)
    choch_dn = np.zeros(n, dtype=bool)

    highs = df["last_swing_high"].values
    lows = df["last_swing_low"].values
    close = df["close"].values
    cur = 0
    for i in range(n):
        hi, lo, c = highs[i], lows[i], close[i]
        broke_up = not np.isnan(hi) and c > hi
        broke_dn = not np.isnan(lo) and c < lo
        if broke_up:
            if cur == -1:
                choch_up[i] = True
            elif cur == 1:
                bos_up[i] = True
            cur = 1
        elif broke_dn:
            if cur == 1:
                choch_dn[i] = True
            elif cur == -1:
                bos_dn[i] = True
            cur = -1
        state[i] = cur
    df["struct_state"] = state
    df["bos_up"], df["bos_dn"] = bos_up, bos_dn
    df["choch_up"], df["choch_dn"] = choch_up, choch_dn
    return df


def _displacement(df: pd.DataFrame) -> pd.DataFrame:
    """Displacement candle: body > 1.2x avg body AND range > 1.5x ATR — validates breaks."""
    body = (df["close"] - df["open"]).abs()
    avg_body = body.rolling(20, min_periods=5).mean()
    atr = wilder_atr(df, 14).replace(0.0, np.nan)
    rng = df["high"] - df["low"]
    df["displacement"] = ((body > 1.2 * avg_body) & (rng > 1.5 * atr)).fillna(False)
    return df


def _fvg(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    """Fair value gaps — ICT 3-candle convention, flagged at candle 3 close.

    Bull FVG: low[t] > high[t-2] — the gap between candle t-2's high and
    candle t's low is knowable only when candle t CLOSES. Flagging at t with
    shift(+past) is causal; the previous version flagged at t-2 using
    shift(-2), i.e. two bars into the future (Fable5 audit Leak 1).
    """
    df = df.copy()
    gap_up = df["low"] - df["high"].shift(2)        # bull FVG, confirmed at t
    gap_dn = df["low"].shift(2) - df["high"]        # bear FVG, confirmed at t
    if p.fvg_method == "adaptive":
        min_gap = wilder_atr(df, 14) * float(p.fvg_min_atr)
    else:
        min_gap = df["close"] * float(p.fvg_min_pct)
    df["fvg_bull"] = (gap_up > min_gap).fillna(False)
    df["fvg_bear"] = (gap_dn > min_gap).fillna(False)
    # zone bounds: bull zone sits between high[t-2] (bottom) and low[t] (top)
    df["fvg_bull_zone_bot"] = np.where(df["fvg_bull"], df["high"].shift(2), np.nan)
    df["fvg_bear_zone_top"] = np.where(df["fvg_bear"], df["low"].shift(2), np.nan)
    return df


def _premium_discount(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    df = df.copy()
    w = max(2, int(p.range_bars))
    rh = df["high"].rolling(w, min_periods=w).max()
    rl = df["low"].rolling(w, min_periods=w).min()
    eq = (rh + rl) / 2
    df["dealing_high"], df["dealing_low"], df["equilibrium"] = rh, rl, eq
    span = (rh - rl).replace(0.0, np.nan)
    df["pd_position"] = ((df["close"] - rl) / span).clip(0, 1)   # 0=deep discount, 1=deep premium
    df["discount"] = df["close"] < eq
    df["premium"] = df["close"] > eq
    return df


def _ote(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    df = df.copy()
    w = max(2, int(p.impulse_bars))
    ih = df["high"].rolling(w, min_periods=w).max()
    il = df["low"].rolling(w, min_periods=w).min()
    rng = ih - il
    df["impulse_high"], df["impulse_low"] = ih, il
    df["ote_long_62"] = ih - rng * 0.62
    df["ote_long_79"] = ih - rng * 0.79
    df["ote_short_62"] = il + rng * 0.62
    df["ote_short_79"] = il + rng * 0.79
    # inside OTE pocket (62-79 retrace) — the ICT "sweet spot"
    df["in_ote_long"] = (df["close"] <= df["ote_long_62"]) & (df["close"] >= df["ote_long_79"])
    df["in_ote_short"] = (df["close"] >= df["ote_short_62"]) & (df["close"] <= df["ote_short_79"])
    return df


def _sweeps(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    df = df.copy()
    if p.sweep_vol_factor > 0:
        vol = df["volume"].astype(float)
        vma = vol.rolling(20, min_periods=1).mean()
        vol_ok = (vol >= p.sweep_vol_factor * vma.replace(0.0, np.nan)).fillna(False)
    else:
        vol_ok = pd.Series(True, index=df.index)
    # sweep = take out swing level intrabar, close back inside (stop hunt), w/ vol if configured
    df["sweep_low"] = (
        df["last_swing_low"].notna()
        & (df["low"] < df["last_swing_low"])
        & (df["close"] > df["last_swing_low"])
        & vol_ok
    )
    df["sweep_high"] = (
        df["last_swing_high"].notna()
        & (df["high"] > df["last_swing_high"])
        & (df["close"] < df["last_swing_high"])
        & vol_ok
    )
    return df


def _order_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """Order block: last opposite-color candle before a displacement BOS. Tag proximity."""
    df = df.copy()
    bull_ob_top = np.full(len(df), np.nan)
    bear_ob_bot = np.full(len(df), np.nan)
    last_bull_ob = np.nan   # top of last down-candle before bull BOS
    last_bear_ob = np.nan   # bottom of last up-candle before bear BOS
    o, c = df["open"].values, df["close"].values
    bos_up, bos_dn = df["bos_up"].values, df["bos_dn"].values
    for i in range(len(df)):
        if bos_up[i]:
            for j in range(i, max(i - 5, -1), -1):
                if c[j] < o[j]:
                    last_bull_ob = max(o[j], c[j])
                    break
        if bos_dn[i]:
            for j in range(i, max(i - 5, -1), -1):
                if c[j] > o[j]:
                    last_bear_ob = min(o[j], c[j])
                    break
        bull_ob_top[i] = last_bull_ob
        bear_ob_bot[i] = last_bear_ob
    df["bull_ob"] = bull_ob_top
    df["bear_ob"] = bear_ob_bot
    atr = wilder_atr(df, 14).replace(0.0, np.nan)
    df["near_bull_ob"] = (df["bull_ob"].notna()) & ((df["close"] - df["bull_ob"]).abs() <= 0.8 * atr)
    df["near_bear_ob"] = (df["bear_ob"].notna()) & ((df["close"] - df["bear_ob"]).abs() <= 0.8 * atr)
    return df


def build_structure(df: pd.DataFrame, p: Profile) -> pd.DataFrame:
    df = _swings(df, p.swing_left, p.swing_right)
    df = _structure_state(df)
    df = _displacement(df)
    df = _fvg(df, p)
    df = _premium_discount(df, p)
    df = _ote(df, p)
    df = _sweeps(df, p)
    df = _order_blocks(df)
    return df

"""K3 configuration: universe, risk kernel, and the two trading profiles.

Design notes
------------
One shared RISK KERNEL (fixed-fractional 1% risk, ATR stop, 3-step scale-out,
trail-after-TP1, time exit) — inherited from the Quantrex lineage.
Two PROFILES differ only in geometry (timeframes, windows, thresholds).
Fusion weights are declared here so research mode can sweep them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List

FAPI = "https://fapi.binance.com/fapi/v1"

FALLBACK_TOP10 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
]
STABLE_LIKE = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "EUR", "GBP", "AEUR", "XUSD", "USD1"}

TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}


@dataclass
class RiskKernel:
    initial_capital: float = 10_000.0
    risk_per_trade: float = 0.01
    atr_period: int = 14
    atr_stop_mult: float = 1.8
    commission: float = 0.00055        # honest taker (Fable5 audit: real is 0.05–0.055%)
    slippage: float = 0.0002
    max_leverage: float = 20.0
    # scale-out ladder
    tp_r: List[float] = field(default_factory=lambda: [1.0, 2.0, 3.0])
    tp_pct: List[float] = field(default_factory=lambda: [0.50, 0.30, 0.20])
    trail_after_tp1: bool = True
    trail_atr_mult: float = 1.0
    max_hold_bars: int = 48
    # portfolio caps
    max_concurrent: int = 4
    max_daily_loss: float = 0.03
    funding_cost_per_8h: float = 0.0001   # applied to held notional each funding tick in backtest


@dataclass
class FusionWeights:
    """K3 five-group fusion weights (sum ~1.0)."""
    structure: float = 0.30     # BOS/CHoCH, sweeps, market structure
    liquidity: float = 0.20     # FVG, premium/discount, OTE
    momentum: float = 0.20      # RSI, EMA slope, MACD histogram
    volatility: float = 0.15    # ATR percentile, squeeze/expansion
    positioning: float = 0.15   # funding z, OI delta, taker flow


@dataclass
class Profile:
    name: str
    timeframe: str
    context_tf: str
    swing_left: int = 2                 # swing detection geometry
    swing_right: int = 2
    range_bars: int = 20                # premium/discount window
    impulse_bars: int = 20              # OTE impulse window
    fvg_method: str = "static"          # static | adaptive
    fvg_min_pct: float = 0.001
    fvg_min_atr: float = 0.25
    sweep_vol_factor: float = 0.0       # 0 = off
    adx_period: int = 14
    adx_trend_min: float = 18.0
    atr_pctile_window: int = 200
    # decision tiers
    tier_active: float = 72.0
    tier_watch: float = 58.0
    min_groups_agree: int = 3           # of 5 groups must lean same direction
    # gates
    min_quote_vol_24h: float = 50_000_000.0
    max_abs_funding: float = 0.0010
    funding_z_block: float = 2.5        # block entries when funding z extreme WITH direction
    weights: FusionWeights = field(default_factory=FusionWeights)
    risk: RiskKernel = field(default_factory=RiskKernel)


SCALP = Profile(
    name="SCALP",
    timeframe="5m",
    context_tf="15m",
    range_bars=24,                      # ~2h dealing range
    impulse_bars=16,
    fvg_method="adaptive",
    fvg_min_atr=0.20,
    sweep_vol_factor=1.15,
    adx_trend_min=16.0,
    # calibrated on top-5 majors: q95 ~ 52, q99 ~ 63 (2026-07 sample)
    tier_active=64.0,
    tier_watch=52.0,
    min_groups_agree=3,
    max_abs_funding=0.0008,
    risk=RiskKernel(
        atr_stop_mult=1.3,
        tp_r=[0.8, 1.6, 2.6],
        tp_pct=[0.50, 0.30, 0.20],
        trail_atr_mult=0.8,
        max_hold_bars=24,
        commission=0.00055,
        max_leverage=25.0,
        max_concurrent=3,
    ),
)

DAY = Profile(
    name="DAY",
    timeframe="15m",
    context_tf="1h",
    range_bars=20,
    impulse_bars=20,
    fvg_method="static",
    fvg_min_pct=0.001,
    sweep_vol_factor=0.0,
    adx_trend_min=18.0,
    # calibrated on top-5 majors: q95 ~ 50, q99 ~ 61 (2026-07 sample)
    tier_active=62.0,
    tier_watch=50.0,
    min_groups_agree=3,
    max_abs_funding=0.0010,
    risk=RiskKernel(),
)

PROFILES: Dict[str, Profile] = {"scalp": SCALP, "day": DAY}


def get_profile(name: str) -> Profile:
    key = str(name).strip().lower()
    if key not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; choose {list(PROFILES)}")
    return PROFILES[key]


def clone_profile(p: Profile, **risk_overrides) -> Profile:
    out = replace(p, risk=replace(p.risk), weights=replace(p.weights))
    for k, v in risk_overrides.items():
        if hasattr(out.risk, k):
            setattr(out.risk, k, v)
    return out

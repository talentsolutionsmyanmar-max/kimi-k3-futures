"""K3 data layer — Binance USDT-M futures public API only.

Adds positioning data the Quantrex lineage didn't use:
  - funding history (for z-score)
  - open-interest history
  - taker buy/sell volume ratio (order-flow proxy)
TTL-cached; fail-open everywhere (never brick a scan on an API blip).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from .config import FAPI, FALLBACK_TOP10, STABLE_LIKE

_cache: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, ttl: float, fetch):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    val = fetch()
    with _lock:
        _cache[key] = (now + max(5.0, ttl), val)
    return val


def _get(path: str, params: Optional[dict] = None, timeout: int = 20, base: str = FAPI):
    r = requests.get(f"{base.rstrip('/')}{path}", params=params or {}, timeout=timeout,
                     headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def discover_top10(ttl: float = 300.0) -> List[str]:
    def _fetch() -> List[str]:
        info = _get("/exchangeInfo")
        tradable = {
            s["symbol"] for s in info.get("symbols", [])
            if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT" and s.get("baseAsset") not in STABLE_LIKE
        }
        ticks = _get("/ticker/24hr")
        rows = [(t["symbol"], float(t.get("quoteVolume") or 0.0))
                for t in ticks if isinstance(t, dict) and t.get("symbol") in tradable]
        rows.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in rows[:10]]
    try:
        out = _cached("k3top10", ttl, _fetch)
        if out:
            return out
    except Exception as e:
        print(f"[k3.data] top10 discovery failed ({type(e).__name__}); fallback list")
    return list(FALLBACK_TOP10)


def klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    rows = _get("/klines", {"symbol": symbol.upper(), "interval": interval, "limit": int(min(limit, 1500))})
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "taker_buy"])
    return pd.DataFrame({
        "timestamp": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
        "open": [float(r[1]) for r in rows],
        "high": [float(r[2]) for r in rows],
        "low": [float(r[3]) for r in rows],
        "close": [float(r[4]) for r in rows],
        "volume": [float(r[5]) for r in rows],
        "taker_buy": [float(r[9]) for r in rows],       # taker buy base volume
    })


def quote_volume_24h(symbol: str, ttl: float = 60.0) -> float:
    return float(_cached(f"qv|{symbol}", ttl,
                 lambda: float(_get("/ticker/24hr", {"symbol": symbol.upper()}, 15).get("quoteVolume") or 0.0)))


def funding_now(symbol: str, ttl: float = 60.0) -> Optional[float]:
    def _f() -> Optional[float]:
        try:
            j = _get("/premiumIndex", {"symbol": symbol.upper()}, 15)
            fr = j.get("lastFundingRate")
            return None if fr is None else float(fr)
        except Exception:
            return None
    return _cached(f"fn|{symbol}", ttl, _f)


def fetch_mark_price(symbol: str, ttl: float = 20.0) -> Optional[float]:
    """Live mark price for a USDT-M perpetual."""
    def _f() -> Optional[float]:
        try:
            j = _get("/premiumIndex", {"symbol": symbol.upper()}, 15)
            mp = j.get("markPrice")
            return None if mp is None else float(mp)
        except Exception:
            return None
    return _cached(f"mp|{symbol}", ttl, _f)


def funding_history(symbol: str, limit: int = 90) -> pd.Series:
    """~30 days of 8h funding prints -> Series for z-score."""
    try:
        rows = _get("/fundingRate", {"symbol": symbol.upper(), "limit": int(limit)}, 15)
        vals = [float(r["fundingRate"]) for r in rows]
        return pd.Series(vals, dtype=float)
    except Exception:
        return pd.Series(dtype=float)


def funding_zscore(symbol: str, ttl: float = 300.0) -> Optional[float]:
    def _f() -> Optional[float]:
        h = funding_history(symbol)
        if len(h) < 20:
            return None
        mu, sd = float(h.mean()), float(h.std(ddof=0))
        if sd <= 0:
            return 0.0
        cur = funding_now(symbol)
        if cur is None:
            return None
        return (cur - mu) / sd
    return _cached(f"fz|{symbol}", ttl, _f)


def oi_now(symbol: str, ttl: float = 60.0) -> Optional[float]:
    def _f() -> Optional[float]:
        try:
            return float(_get("/openInterest", {"symbol": symbol.upper()}, 15).get("openInterest"))
        except Exception:
            return None
    return _cached(f"oi|{symbol}", ttl, _f)


def oi_delta_pct(symbol: str, period: str = "1h", ttl: float = 300.0) -> Optional[float]:
    """% change in open interest over the last period (5m/15m/1h/4h/1d)."""
    def _f() -> Optional[float]:
        try:
            rows = _get("/futures/data/openInterestHist",
                        {"symbol": symbol.upper(), "period": period, "limit": 2}, 15)
            if not isinstance(rows, list) or len(rows) < 2:
                return None
            prev, cur = float(rows[-2]["sumOpenInterest"]), float(rows[-1]["sumOpenInterest"])
            if prev <= 0:
                return None
            return (cur / prev - 1.0) * 100.0
        except Exception:
            return None
    return _cached(f"oid|{symbol}|{period}", ttl, _f)


def btc_correlation(symbol: str, interval: str, limit: int = 200, ttl: float = 120.0) -> Optional[float]:
    sym = symbol.upper()
    if sym == "BTCUSDT":
        return 0.0
    def _f() -> Optional[float]:
        try:
            a, b = klines(sym, interval, limit)["close"], klines("BTCUSDT", interval, limit)["close"]
            n = min(len(a), len(b))
            if n < 30:
                return None
            ret = pd.DataFrame({"a": a.iloc[-n:].values, "b": b.iloc[-n:].values}).pct_change().dropna()
            return float(ret["a"].corr(ret["b"])) if len(ret) >= 20 else None
        except Exception:
            return None
    return _cached(f"corr|{sym}|{interval}", ttl, _f)


# ---------------- indicators (shared) ----------------

def wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(1, int(period)), adjust=False).mean().fillna(0.0)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l = df["high"].astype(float), df["low"].astype(float)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr = wilder_atr(df, period).replace(0.0, np.nan)
    pdi = 100 * pdm.ewm(alpha=1 / period, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.astype(float).diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def atr_percentile(df: pd.DataFrame, period: int = 14, window: int = 200) -> pd.Series:
    """Percentile rank of current ATR% within trailing window (vol regime)."""
    atr_pct = wilder_atr(df, period) / df["close"].replace(0.0, np.nan) * 100.0
    return atr_pct.rolling(window, min_periods=max(20, window // 4)).apply(
        lambda x: float((x <= x[-1]).mean() * 100.0), raw=True
    ).fillna(50.0)

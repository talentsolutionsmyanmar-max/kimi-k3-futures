"""K3 order flow — cumulative volume delta (CVD) + book imbalance.

Consumes Binance USDT-M futures streams (fed by k3/livefeed.py):
  <sym>@aggTrade        — every executed trade; m=True means the buyer is the
                          maker, i.e. the aggressor SOLD. Delta = +q buy, -q sell.
  <sym>@depth10@100ms   — top-10 bid/ask snapshots; imbalance =
                          (bidQty - askQty) / (bidQty + askQty).

Maintains rolling windows and emits per-symbol snapshots:
  cvd_1m / cvd_5m   net aggressive volume (quote USDT) over 1 / 5 minutes
  delta_z           z-score of 1m delta vs its own recent history (per symbol)
  imbalance         latest top-10 book imbalance, smoothed (EMA)
  trade_count_1m    activity gauge
  updated           unix ts of last event

Everything is in-memory; state is published to reports/orderflow.json by the
live engine and consumed by the scanner as a live-only score overlay.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Deque, Dict, Optional


class SymbolFlow:
    __slots__ = ("trades", "delta_hist", "imb_ema", "last_ts")

    def __init__(self) -> None:
        self.trades: Deque = deque()          # (ts, signed_quote_usdt)
        self.delta_hist: Deque = deque()      # (ts, cvd_1m_value) sampled ~1/s
        self.imb_ema: Optional[float] = None
        self.last_ts: float = 0.0

    def on_trade(self, ts: float, qty: float, price: float, buyer_maker: bool) -> None:
        signed = qty * price * (-1.0 if buyer_maker else 1.0)
        self.trades.append((ts, signed))
        self.last_ts = ts
        self._trim(ts)

    def on_depth(self, ts: float, bids, asks) -> None:
        bq = sum(float(q) for _, q in bids)
        aq = sum(float(q) for _, q in asks)
        if bq + aq <= 0:
            return
        imb = (bq - aq) / (bq + aq)
        self.imb_ema = imb if self.imb_ema is None else 0.3 * imb + 0.7 * self.imb_ema
        self.last_ts = max(self.last_ts, ts)

    def _trim(self, now: float) -> None:
        cutoff = now - 600.0                     # keep 10 minutes
        while self.trades and self.trades[0][0] < cutoff:
            self.trades.popleft()
        while self.delta_hist and self.delta_hist[0][0] < cutoff:
            self.delta_hist.popleft()

    def cvd(self, now: float, window: float) -> float:
        cutoff = now - window
        total = 0.0
        for ts, v in reversed(self.trades):
            if ts < cutoff:
                break
            total += v
        return total

    def snapshot(self, now: float) -> Dict[str, Any]:
        self._trim(now)
        cvd_1m = self.cvd(now, 60.0)
        cvd_5m = self.cvd(now, 300.0)

        # sample 1m delta once per second into history for the z-score base
        if not self.delta_hist or now - self.delta_hist[-1][0] >= 1.0:
            self.delta_hist.append((now, cvd_1m))

        vals = [v for _, v in self.delta_hist]
        delta_z = None
        if len(vals) >= 30:
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            sd = math.sqrt(var)
            if sd > 0:
                delta_z = round((cvd_1m - mu) / sd, 2)

        n1 = sum(1 for ts, _ in self.trades if ts >= now - 60.0)
        return {
            "cvd_1m": round(cvd_1m, 0),
            "cvd_5m": round(cvd_5m, 0),
            "delta_z": delta_z,
            "imbalance": round(self.imb_ema, 4) if self.imb_ema is not None else None,
            "trade_count_1m": n1,
            "updated": round(self.last_ts, 1),
        }


class OrderflowTracker:
    """Multi-symbol tracker. Feed events; call snapshot() periodically."""

    def __init__(self) -> None:
        self.symbols: Dict[str, SymbolFlow] = {}

    def _get(self, sym: str) -> SymbolFlow:
        sf = self.symbols.get(sym)
        if sf is None:
            sf = self.symbols[sym] = SymbolFlow()
        return sf

    def on_agg_trade(self, sym: str, data: Dict[str, Any]) -> None:
        # {"e":"aggTrade","E":..,"s":..,"p":"..","q":"..","m":bool,"T":..}
        try:
            ts = float(data.get("T") or data.get("E") or 0) / 1000.0 or time.time()
            self._get(sym).on_trade(ts, float(data["q"]), float(data["p"]), bool(data["m"]))
        except (KeyError, ValueError, TypeError):
            pass

    def on_depth(self, sym: str, data: Dict[str, Any]) -> None:
        # partial book depth: {"e":"depthUpdate"|..., "b":[[p,q]..], "a":[[p,q]..]}
        try:
            ts = float(data.get("E") or 0) / 1000.0 or time.time()
            bids = data.get("b") or data.get("bids") or []
            asks = data.get("a") or data.get("asks") or []
            self._get(sym).on_depth(ts, bids, asks)
        except (ValueError, TypeError):
            pass

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        return {sym: sf.snapshot(now) for sym, sf in self.symbols.items()}

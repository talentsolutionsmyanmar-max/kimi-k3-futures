# K3 vs True Real-Time — Honest Gap Analysis

What exists today, what the dashboard + live engine close, and what remains open. No marketing.

## Gap 1 — REST polling, not tick streaming  (CLOSED — live engine)
K3 reads Binance REST klines for signals (closed-bar doctrine: no signal on a closed bar
is ever missed). Intra-bar level tracking is now handled by **`k3/livefeed.py`, the K3
live engine**: a dependency-free websocket consumer on
`fstream.binancefuture.com/stream?streams=!markPrice@arr@1s` (1s ticks, all symbols,
with REST `premiumIndex` fallback). It runs 24/7 as a launchd service
(`launchd/com.kimi.k3.livefeed.plist`), writes `reports/live_prices.json` every second,
and detects Entry / Stop / TP1-3 touches against the latest scanner setups —
ENTRY alerts only inside non-caution kill zones, STOP/TP always. The scanner prefers
these tick prices (≤45s fresh) over REST, and the alarm task fires within ~1 minute
of any touch.
- *Network note:* `fstream.binance.com` accepts the handshake from some networks but
  never delivers frames; `fstream.binancefuture.com` streams correctly (verified live).
- *Remaining:* kline streams for intra-bar signal regeneration (structure still forms
  on closed bars only — by design).

## Gap 2 — No order book / footprint  (CLOSED — order-flow overlay)
`k3/orderflow.py` consumes `<sym>@aggTrade` and `<sym>@depth10@100ms` streams (21
streams on the live engine's single socket) for every universe symbol and maintains:
rolling **CVD** (1m/5m, quote USDT), a per-symbol **delta z-score** (1m delta vs its
own 10-min history), and an EMA-smoothed **top-10 book imbalance**. Published to
`reports/orderflow.json` every 5s. The scanner applies it as a **live-only overlay**
(±5 max on the K3 score: delta-z ×1.5 + imbalance ×4, direction-signed), notes it on
the ticket, and the board renders an ORDER FLOW chip row (adj / Δz / book / CVD / prints).
Backtests are deliberately untouched — there is no order-flow history to replay.
- *Remaining:* true level-2 footprint / cumulative-delta charting; absorption detection.

## Gap 3 — OI delta endpoint intermittent  (OPEN, fail-open)
`/futures/data/openInterestHist` returns nothing from some networks/regions, so
`oi_delta_1h_pct` is often `None`. The fusion degrades gracefully (no OI confirm/boost),
but the positioning group is then funding-z + taker flow only.
- *To close:* run from a region where the endpoint is served, or proxy.

## Gap 4 — Positioning history absent in backtests  (OPEN)
Funding history and OI history are available "recent-only" from the API. Backtests score
the positioning group from taker flow only; live scans use the full overlay. So backtest
P&L *understates* what the live engine sees — the live system is strictly smarter.
- *To close:* persist funding/OI snapshots to SQLite on every scheduled run;
  after 4–8 weeks, backtests replay real positioning history. The dashboard job does this.

## Gap 5 — No execution layer  (BY DESIGN)
K3 emits setups, not orders. Slippage/fees are modeled (0.04–0.05% + 0.02%), funding drag
is charged, but live fills, partial fills, and liquidation mechanics are not simulated.
- *To close:* testnet API keys + the `risk.portfolio_check` admission layer, behind the
  Fable5 provenance gate (`live` provenance only after paper track record).

## Gap 6 — Scheduler granularity  (CLOSED — 1-minute alarm path)
Blueprint schedules are cron-based; the scanner stays at 15 min (matches the DAY profile
natively and catches every closed 5m bar). Level-touch alerting no longer waits for the
scanner: the live engine publishes `reports/stream_alert.json` and the alarm task's
condition runs every 1 minute, so an Entry/SL/TP touch reaches the desktop within
~1 minute, any hour, kill zone or not (ENTRY alerts remain kill-zone-gated).
- *Remaining:* sub-minute push would need OS-level notifications from the daemon itself.

## Summary

| Layer | Status |
|---|---|
| Signal quality on closed bars | Real-time-capable now (15-min cadence, zero missed closed bars) |
| Tick-level mark prices | Live now — websocket engine, 1s cadence, launchd-persistent |
| Entry / SL / TP touch alerts | Live now — ~1 min to desktop via alarm task |
| Kill zones / session discipline | Live now |
| Order flow (CVD, delta-z, book imbalance) | Live now — 21-stream socket, ±5 score overlay |
| Intra-bar signal regeneration | Closed bars only (by design) |
| Order book depth | Not built |
| Historical positioning in research | Accrues automatically from the dashboard job |
| Live order execution | Deliberately out of scope (signal/paper doctrine) |

# K3 vs True Real-Time — Honest Gap Analysis

What exists today, what the dashboard closes, and what remains open. No marketing.

## Gap 1 — REST polling, not tick streaming  (PARTIALLY CLOSED)
K3 reads Binance REST klines. The dashboard refreshes every 15 min at
`:03/:18/:33/:48` — i.e. 2–3 min after each 15m bar close. Every closed 5m/15m bar is
captured, so **no signal on a closed bar is ever missed**. What is missed: intra-bar
information (a sweep that happens and reverts inside the current bar).
- *To fully close:* persistent websocket consumer (`fstream.binance.com/ws`, kline streams
  per symbol) with a small event loop. Blueprint runs are time-bounded, so this belongs
  on a VPS or a `launchd`/`systemd` service, not in the scheduled job.

## Gap 2 — No order book / footprint  (OPEN)
Scalpers live on depth, spread, and delta. K3's order-flow read is the per-bar
`taker_buy/volume` ratio only — aggregated, no level-2.
- *To close:* subscribe `depth20@100ms` + `aggTrade` websockets; add a real
  cumulative-delta group to the fusion. Public, no keys needed, but requires Gap 1 first.

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

## Gap 6 — Scheduler granularity  (CLOSED ENOUGH)
Blueprint schedules are cron-based; minimum sensible cadence for this workload is 15 min.
That matches the DAY profile natively. For SCALP (5m), the job still catches every closed
5m bar, but alerts arrive up to ~17 min after a 5m bar closes — fine for WATCH/ACTIVE
setups that persist, not fine for 2-minute fade entries.
- *To close:* interval trigger at 5–7 min once websocket consumer exists (Gap 1).

## Summary

| Layer | Status |
|---|---|
| Signal quality on closed bars | Real-time-capable now (15-min cadence, zero missed closed bars) |
| Kill zones / session discipline | Live now |
| Intra-bar scalping edge | Needs websockets — the one real gap for scalpers |
| Order book depth | Not built |
| Historical positioning in research | Accrues automatically from the dashboard job |
| Live order execution | Deliberately out of scope (signal/paper doctrine) |

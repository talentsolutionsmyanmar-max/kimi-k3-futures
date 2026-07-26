# K3 Live Dashboard (Kimi Work Blueprint)

K3 ships with a live command-board built on Kimi Work Blueprint assets. All
three pieces are recreated here in code form so the pipeline is reproducible.

## Components

| Asset | Role | Cadence |
|---|---|---|
| **K3 Futures Scanner** (code Automation) | Scans the top-10 futures universe with `k3.py scan --live`, enriches every setup with live mark price, distance-to-entry, R-now, quantity/notional and kill-zone state, and delivers the artifact to the Widget. | Cron `8,23,38,53 * * * *` UTC (every 15 min) |
| **K3 Live Futures Board** (Widget) | World-class dark command UI: kill-zone hero with session progress, tradeable-now banner, trade tickets with Entry / SL / TP ladder / live mark / R-now / timeframe badges, score rings, price ladder. | Refreshes on every scanner delivery |
| **K3 Kill-Zone Alarm** (condition Automation) | Checks the latest snapshot every 15 min; fires once per *new* tradeable setup signature (ACTIVE + gates pass + inside a kill zone, not caution). Appends to `reports/alarms.jsonl` and pushes a desktop notification that opens the board. | Condition, 15-min checks, fires only on new setups |

## Data files produced

- `reports/live_snapshots.jsonl` — one full scanner artifact per run (history).
- `reports/alarms.jsonl` — one alarm record per fired kill-zone alert.
- `reports/alarmed.json` — dedupe signature for the alarm condition.

## Kill zones (UTC)

| Zone | Window | Notes |
|---|---|---|
| ASIA | 00:00–04:00 | Boost active |
| LONDON | 06:00–09:00 | Boost active |
| NEW_YORK | 11:00–14:00 | Boost active |
| LONDON_CLOSE | 14:00–16:00 | Caution — no new entries |
| NY_PM | 17:30–20:00 | Boost active |

Outside kill zones, SCALP setups are demoted ACTIVE → WATCH and the
tradeable-now list stays empty.

## Honest cadence note

This stack refreshes on a 15-minute schedule, not tick-by-tick. Entry/SL/TP are
computed from the signal bar; mark price is fetched live (20 s cache) at scan
time. For true tick-level scalping see the websocket streamer roadmap in
`REALTIME_GAPS.md`.

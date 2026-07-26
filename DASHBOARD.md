# K3 Live Dashboard (Kimi Work Blueprint)

K3 ships with a live command-board built on Kimi Work Blueprint assets. All
three pieces are recreated here in code form so the pipeline is reproducible.

## Components

| Asset | Role | Cadence |
|---|---|---|
| **K3 Live Engine** (`k3/livefeed.py`, launchd service) | Dependency-free websocket consumer (`fstream.binancefuture.com`, `!markPrice@arr@1s`) streaming tick mark prices for all symbols; detects Entry / Stop / TP1-3 touches against the latest scanner setups. ENTRY alerts fire only inside non-caution kill zones; STOP/TP always. | 1 s ticks, 24/7 |
| **K3 Futures Scanner** (code Automation) | Scans the top-10 futures universe with `k3.py scan --live`; mark prices come from the live engine's tick file when ≤45 s fresh (REST fallback); enriches every setup with distance-to-entry, R-now, quantity/notional, kill-zone state and recent touch events; delivers the artifact to the Widget. | Cron `8,23,38,53 * * * *` UTC (every 15 min) |
| **K3 Live Futures Board** (Widget) | World-class dark command UI: kill-zone hero with session progress, tradeable-now banner, trade tickets with Entry / SL / TP ladder / live mark / R-now / timeframe badges, score rings, price ladder. | Refreshes on every scanner delivery |
| **K3 Kill-Zone Alarm** (condition Automation) | Checks every 1 min; fires once per *new* alert signature — either a live-engine touch (Entry in kill zone, or any Stop/TP hit) or a new tradeable setup (ACTIVE + gates pass + in kill zone). Appends to `reports/alarms.jsonl` and pushes a desktop notification that opens the board. | Condition, 1-min checks, fires only on new alerts |

## Data files produced

- `reports/live_prices.json` — latest tick mark prices from the live engine (1 s).
- `reports/stream_events.jsonl` — every detected Entry/SL/TP touch event.
- `reports/stream_alert.json` — current alert signature + events (alarm input).
- `reports/live_snapshots.jsonl` — one full scanner artifact per run (history).
- `reports/alarms.jsonl` — one alarm record per fired kill-zone alert.
- `reports/alarmed.json`, `reports/live_state.json` — dedupe state.

## Live engine service (macOS launchd)

```bash
# install / start
cp launchd/com.kimi.k3.livefeed.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kimi.k3.livefeed.plist
# stop / remove
launchctl bootout gui/$(id -u)/com.kimi.k3.livefeed
rm ~/Library/LaunchAgents/com.kimi.k3.livefeed.plist
```

Note: from some networks `fstream.binance.com` completes the websocket handshake
but never delivers frames; the engine targets `fstream.binancefuture.com`, which
streams correctly, and falls back to REST polling if the socket keeps failing.

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

Signals are computed from closed bars on a 15-minute schedule (closed-bar
doctrine — no missed closed-bar signals). Level *tracking* is tick-level: the
live engine streams mark prices every second and the alarm task pushes an
Entry/SL/TP touch to the desktop within ~1 minute. The remaining gap is
intra-bar signal regeneration and order-book depth — see `REALTIME_GAPS.md`.

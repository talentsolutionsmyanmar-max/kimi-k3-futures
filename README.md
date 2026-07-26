# KIMI K3 — Autonomous Crypto Futures Trading System

**K3** is an original trading system for Binance USDT-M perpetual **scalping and day trading**
on the top-10 crypto futures by volume. Signal/paper only — it never places orders.

Lineage: it absorbs the DNA of
[ict-quantrex-cursor](https://github.com/talentsolutionsmyanmar-max/ict-quantrex-cursor)
(ICT liquidity concepts, fixed-fractional risk kernel, scale-out ladder, market gates) and
[quantrex-Fable5](https://github.com/talentsolutionsmyanmar-max/quantrex-Fable5)
(ensemble fusion gating, provenance doctrine) — then goes further with its own architecture.

## What K3 adds on top of the lineage

| K3 original | Why it matters |
|---|---|
| **Structure state machine** — BOS / CHoCH / displacement / order blocks | The lineage detected levels; K3 tracks *market structure itself* |
| **5-group signed factor fusion** (Structure .30 / Liquidity .20 / Momentum .20 / Volatility .15 / Positioning .15) | Every bar gets a calibrated 0–100 K3 score per direction, not a binary signal |
| **Positioning intelligence** — funding z-score (30d history), OI delta, taker buy/sell flow | Knows when a trade is *crowded* — blocks or fades it |
| **Tiered decisions** — ACTIVE / WATCH / STANDBY + conviction-scaled risk (0.75x / 1.0x / 1.25x) | Position size follows evidence, not hope |
| **Funding-aware backtester** — 8h funding drag, signal-flip early exit, per-tier P&L attribution | Backtests that behave like real perp trading |
| **Walk-forward research mode** — train 60% / OOS 40% with a train-gate | Kills parameter combos that only look good in-sample |
| **Look-ahead regression harness** — `leaktest` must lose on random walks | Any backtest number that can't survive this is not shipped |
| **Universe screener** — 75+ perps ranked by range / tape / drift / funding, not just volume | Finds game-changer pairs the volume top-10 misses; candidates are backtested before promotion |

## Run it

```bash
pip install -r requirements.txt

python k3.py top10                              # live top-10 futures universe
python k3.py universe                           # game-changer screener (all USDT-M perps)
python k3.py scan --profile both                # live setups, both profiles
python k3.py backtest --profile day --limit 1500
python k3.py research --profile scalp           # walk-forward validation
python k3.py leaktest                           # random-walk look-ahead regression (must lose)
python k3.py causaltest                         # causal truncation test: output at t must not change when the future is cut
python k3.py groupstudy --profile both          # per-group rank IC vs forward returns — does the fusion have edge at all?
python k3.py tiercal --profile both             # tier recalibration: train 60% thresholds, OOS 40% verdict
python k3.py scalp2                             # Phase 5: OTE limit-entry mechanics vs market-entry baseline
python k3.py replay                             # order-flow overlay validation (accruing)
python k3.py scan --symbols BTCUSDT SOLUSDT --capital 25000 --profile day
```

## The two profiles

| | SCALP (experimental ⚠) | DAY (validated ✓) |
|---|---|---|
| TF / context | 5m / 15m | 15m / 1h |
| Stop | 1.3 × ATR | 1.8 × ATR |
| TP ladder | 0.8/1.6/2.6 R — 50/30/20 | 1/2/3 R — 50/30/20 |
| Max hold | 24 bars (2h) | 48 bars (12h) |
| Sweep filter | volume ≥ 1.15× | off |
| Tiers (ACTIVE/WATCH) | 64 / 52 | 62 / 50 |

Tiers are calibrated on the majors' composite distribution (q95 ≈ 50–52, q99 ≈ 61–63)
so ACTIVE fires on roughly the top 1% of bars — selective by construction. The 2026-07-27
OOS recalibration (`tiercal`) found **no threshold that beats them out-of-sample**, so
they ship as-is but are labeled *un-validated*, not "empirical".

## Validation results — the honest baseline (2026-07-26, post Fable5 audit)

**⚠ The earlier DAY claim (+$2,942, 65.9% win) was retracted.** A Fable5 audit found two
look-ahead leaks in `structure.py` (FVG flagged 2 bars into the future via `shift(-2)`;
swing levels visible before their 2-bar confirmation). The audit's random-walk test proved
the old engine profited on coin flips (+$1,578 on 8 seeds) — the classic signature of
look-ahead bias. Both leaks are now fixed (causal 3-candle FVG, confirmation-delayed
swings), and the random-walk regression test (`python3 k3.py leaktest`) is permanent:
**post-fix the engine loses on all random-walk seeds, as a correct backtester must.**

**True DAY baseline (leak-free, honest costs 0.055% taker + ATR stop-gap slippage,
1500 bars × 10 symbols, $10k, funding):** 508 trades, 51.3% win, **−$7,056 net**.
ACTIVE-tier-only variant: 126 trades, 49.1% win, −$3,253. On this 15-day single-regime
sample the leak-free DAY stack does **not** beat costs — that is the true starting point,
and every future improvement is measured against it. Signal quality concentrates in the
ACTIVE tier and per-session attribution (`pnl_by_session`) now shows where.

**SCALP profile — honest failure, still documented on purpose.** Raw backtest: −$3,650.
Walk-forward research: **no combo survived out-of-sample**. Additionally, SCALP entries
are now kill-zone-gated in the backtester for live-engine parity. Ships as experimental.

**Doctrine:** K3 numbers are believable only because they are now *mechanically*
verifiable — `leaktest` must pass, walk-forward gates research, and any claim that
can't survive both is not shipped. That is the Fable5 provenance doctrine applied
to K3 itself, not just its failures.

## Fable5 audit round 2 (2026-07-27) — four directives + Phase 5

**1. Causal truncation test adopted (`k3/causaltest.py`, verbatim from Fable5).**
Truncate the series at bar *t*; every computed value at *t* must be bitwise-identical
to the full-series run. `python3 k3.py causaltest --profile both` → **PASS, 0
violations**, both profiles, exit-gated in CI fashion (exit 1 on any violation).
Economic (leaktest) + causal (causaltest) = the complete gate.

**2. Tier recalibration done the honest way (`python3 k3.py tiercal`).** The shipped
tiers were calibrated in-sample on the *leaked* engine — meaningless. Redone:
candidate thresholds from train-60% score quantiles only, verdict on the untouched
OOS 40%. With a breadth gate (a candidate must trade on ≥ half the universe — a
threshold "validated" on one symbol is multiple-comparisons noise): **no candidate
cleared the adoption gate on either profile. Shipped tiers kept (64/52, 62/50),
now labeled un-validated rather than falsely "empirical".**

**3. KAITO-class single-symbol PFs are noise.** No single-symbol result is ever
promoted; only universe-breadth results count. Standing discipline, no exception.

**4. Group-level IC study (`python3 k3.py groupstudy`) — the verdict is blunt.**
Per-group Spearman rank IC vs forward returns (5m fwd 12 bars; 15m fwd 8 bars),
10 symbols, no fitting:

| Group | SCALP mean IC | DAY mean IC | Verdict |
|---|---|---|---|
| Structure | n/a (too discrete) | n/a (too discrete) | can't measure — event-sparse |
| Liquidity | −0.002 | **+0.036 (90% of symbols positive)** | the only non-negative group |
| Momentum | −0.025 | −0.071 | **inverted — trend-following is contrarian at these horizons** |
| Volatility | −0.055 (inverted) | −0.035 (inverted) | expansion energy predicts reversal |
| Positioning | +0.011 | −0.032 | none |
| **Composite** | **−0.041** | **−0.047** | **mildly inverted — no edge as constructed** |

Signal-bar directional accuracy: **44.9% SCALP / 42.9% DAY — below a coin flip.**
Mean payoff per signal bar (+0.11% / +0.14%) barely covers the taker round trip
(~0.11%) even before the losing-side skew. **The 5-group fusion does not currently
have edge. Any future K3 signal work must start from this fact, not from parameter
sweeps.**

**5. Phase 5 — SCALP resurrection via mechanics, not tuning (`python3 k3.py scalp2`).**
New `k3/scalp2.py`: hard gates (sweep + displacement + 15m struct_state alignment +
kill zone + volatility regime), **limit entries at the 70.5% OTE level** (order rests
≤12 bars, fill-or-cancel, never assume better than limit), structural stops beyond the
impulse origin, **maker fees 0.02%** on limit entries and TP exits (taker 0.075% on
stops with gap-through). Result on 5 majors, same 1500 bars:

| | trades | net P&L |
|---|---|---|
| Market-entry baseline | 217 | **−$18,478** |
| scalp2 OTE limit-entry | 21 | **−$1,793** |

The mechanics work as designed — 10× selectivity, 90% less bleeding — but scalp2 is
**still net negative and 21 trades is too thin for significance**. Verdict: the entry
mechanics are validated as *cost control*, not as an edge. SCALP remains experimental
and the dashboard continues to demote it outside kill zones.


## Architecture

```
k3/
  config.py     # risk kernel + SCALP/DAY profiles + fusion weights
  data.py       # Binance futures API: top10, klines(+taker flow), funding hist/z, OI, indicators
  structure.py  # swings (confirmation-delayed), BOS/CHoCH, displacement, causal FVG, PD, OTE, sweeps, OBs
  signals.py    # 5-group signed scorers + composite K3 score + tiers + positioning overlay
  risk.py       # conviction-scaled sizing, TP ladder, portfolio caps
  engine.py     # per-symbol setup builder (structure → fusion → gates → trade plan)
  backtest.py   # leak-free event-driven backtester, KZ-gated SCALP, per-session P&L, honest costs
  research.py   # walk-forward grid validation with OOS honesty gate
  killzones.py  # ICT kill-zone session clock (UTC)
  livefeed.py   # 24/7 websocket engine: 1s marks, Entry/SL/TP touches, 21 streams
  orderflow.py  # CVD, delta z-score, book imbalance from aggTrade + depth10
  replay.py     # order-flow overlay validation against accrued history
  leaktest.py   # random-walk look-ahead regression test (must lose on coin flips)
  causaltest.py # causal truncation test (output at t invariant to cutting the future)
  groupstudy.py # per-group rank IC vs forward returns — edge measurement, not fitting
  tiercal.py    # train-only tier thresholds with breadth-gated OOS adoption verdict
  scalp2.py     # Phase 5: OTE limit-entry / maker-fee mechanics + baseline comparison
  screener.py   # all-perp universe screener (range / tape / drift / funding ranks)
k3.py           # CLI: top10 | universe | scan | backtest | research | leaktest | causaltest | groupstudy | tiercal | scalp2 | replay
reports/        # JSON artifacts of every run
```

## Safety

K3 outputs **setups, not orders**. STANDBY means a gate failed (funding, liquidity,
crowding, HTF conflict) — the system watches, it doesn't force trades. Futures with
leverage can liquidate you; nothing here is financial advice.

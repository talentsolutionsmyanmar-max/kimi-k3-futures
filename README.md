# KIMI K3 — Autonomous Crypto Futures Trading System

> **STATUS: ALL TRACKS CLOSED (2026-07-27).** The five-group fusion was falsified
> under a pre-registered protocol at 5m/15m (Phase 8), and the horizon pivot was
> tested and closed at 1h (Phase 9): reversion persists (raw momentum KZ IC −0.019,
> no flip to momentum) but pays 2.2bp against a 10bp MEXC clearing bar.
> **Nothing validated at any tested horizon — systematic trading is closed, with no
> further horizons, venues, or conditionings to be tested.**
> This repository is now a **measurement instrument and a doctrine**, not a signal
> generator. Read [OBITUARY.md](OBITUARY.md) — the one-page answer to "what did K3
> find?" — then [DOCTRINE.md](DOCTRINE.md); both are worth more than the code.

**Three findings that outlive the project:**

1. **Maker execution costs more than taker — measured at two horizons.**
   39.1 bps effective vs 15 bps taker at 15m; re-derived at 1h (fill 28.5%,
   adverse selection again, maker 13.8 vs market 60.9 bp/signal). "Just use limit
   orders to cut fees" is *backwards* at every horizon tested. Counterintuitive,
   transferable, and the most valuable thing K3 produced.
2. **The composite scored worse than its own best component.** 0/32 FDR cells for
   the fusion vs 17–20 for momentum alone — weighted-sum fusion over correlated,
   oppositely-signed components destroys information. Validate components
   individually; combine only what validates.
3. **The measured market fact, now at two timescales.** Crypto 5m/15m returns
   mean-revert weakly (sign-stable, killzone-amplified, OOS-consistent) worth
   2.5–4.5 bps vs a 16.5 bps floor; at 1h the reversion persists but shrinks
   (IC −0.019 → 2.2 bps vs a 10 bps bar). The signal is real at every horizon
   tested, and everywhere too small to pay its costs. That is a complete answer.

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
python k3.py ledger --profile both              # Phase 7: exit-event ledger — MFE/MAE, conversions, dumb baseline, conditional-MFE test
python k3.py validity --profile both            # Phase 6: pre-registered IC protocol (5k+ bars, bootstrap null, BH-FDR, OOS, regimes)
python k3.py fillmodel --profile both           # Phase 8b: limit-fill validation (strict fills, adverse selection, leak check)
python k3.py condvalid --profile both           # Phase 8c: conditional validity — power check first, one pass, closes the track
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

## Phase 6 — signal validity study (2026-07-27, pre-registered protocol)

`python3 k3.py validity` — the rigorous prior question: **do any of the five fusion
groups predict forward returns at all?** 8 symbols × 6,000 bars × horizons 1/4/8/24,
non-overlapping Spearman IC (primary), Newey-West t (secondary), circular block
bootstrap null (1,000 iters), Benjamini-Hochberg FDR q=0.10 across the 160-cell grid,
chronological 60/40 OOS, regime breakdown. Pre-registered rule: VALIDATED needs
sign stability + FDR survival + OOS consistency + **economic materiality** (median
quintile spread ≥ 1.5× the 11 bps cost floor).

**Headline: the composite is FALSIFIED on both profiles. No group is VALIDATED.**

| Group | DAY mean IC | DAY verdict | SCALP mean IC | SCALP verdict |
|---|---|---|---|---|
| Structure | −0.028 | CONDITIONAL | −0.054 | CONDITIONAL |
| Liquidity | **+0.034** (94% symbols positive) | CONDITIONAL | +0.030 | CONDITIONAL |
| Momentum | −0.065 (**inverted**, 17/32 FDR cells) | CONDITIONAL | −0.068 (inverted) | CONDITIONAL |
| Volatility | −0.049 | CONDITIONAL | −0.044 | CONDITIONAL |
| Positioning | −0.023 | CONDITIONAL | −0.026 | CONDITIONAL |
| **Composite** | +0.016, 0/32 FDR, OOS flips | **FALSIFIED** | −0.004, 0/32 FDR | **FALSIFIED** |

The binding constraint is economic, exactly as the brief predicted — *"an IC of 0.02
is real and worthless"*: momentum's inversion is statistically robust (sign-stable on
8/8 symbols, FDR-surviving) yet its median quintile spread is **5.0 bps DAY / 1.4 bps
SCALP against an 11 bps cost floor**. Detectable, but practically dead. Regime read:
liquidity is positive in all three DAY regimes (strongest in bear, +0.082); momentum's
inversion deepens in bear regimes (−0.175). Per the protocol, **strategy-layer work
stays frozen**: no reweighting, tier changes, or ladder redesign until a group
validates. The live open hypotheses are structural — execution (maker fills at OTE/OB)
and session conditioning (killzone-restricted samples) — not the fusion score.

## Phase 7 — exit-event ledger (2026-07-27, measurement only)

`python3 k3.py ledger` — `backtest.py` now emits a row at every position transition
(TP1/TP2/TP3/STOP/TIME_EXIT/SIGNAL_FLIP) with the separated group scores, tier, bias,
killzone, ATR, stop bps, funding rate/z, and causal MFE/MAE in R (entry bar forward,
stop-first convention on spanning bars — documented in `k3/ledger.py`). Findings:

- **A. MFE vs ladder:** DAY median MFE **1.02R** (p75 1.57R, p90 2.56R) vs ladder
  1/2/3R — TP2/TP3 sit beyond what the median trade ever reaches; SCALP median 0.86R.
- **B. MAE on winners:** winners' median dip only −0.36R; 11% threaten −0.8R —
  **stop width is not the binding issue** on either profile.
- **C. TP conversion:** DAY TP1→TP2 **28.5%** (below the ~30% dead-zone line — the
  runner pays volatility for nothing); SCALP 51%.
- **D. Dumb baseline:** flat 1R target on the same entries: DAY −$7,136 vs ladder
  −$7,104 (**statistically indistinguishable — the ladder adds nothing on DAY**);
  SCALP −$26,496 vs ladder −$17,020 (ladder genuinely helps on SCALP).
- **E. Conditional MFE (1,000-iter bootstrap null):** DAY ACTIVE entries sit at the
  **100th percentile** of matched random entries (median 1.06R vs null 0.50R);
  SCALP 70th — no separation. Caveat honored: MFE is direction-agnostic and can
  reflect regime conditioning rather than directional skill — which is exactly what
  the Phase 6 composite falsification suggests is happening.

No parameter was changed as a result of any of this. Measurement only.

## Phase 8 — fill-model validation + conditional economics (2026-07-27)

**8a — MAE control: the Phase 7 DAY conditional-MFE result is RETRACTED.** The
matched-random bootstrap (1,000 iters, same construction) run on the adverse side
shows ACTIVE trades' median MAE at the **100th percentile for depth** (−0.92R vs
null −0.49R) alongside the 100th-percentile MFE, with an MFE/MAE ratio at only the
71st percentile. Both sides of the excursion are extreme = **volatility/regime
conditioning, not directional path edge**. The "path-level evidence" reading is
withdrawn; the retraction stands in `k3/ledger.py` output (`mae_control_verdict`).

**8b — Fill-model validation (`python3 k3.py fillmodel`).** Honest limit-fill
simulation at the OTE pocket: strict trade-through fills only, non-fills counted,
market-entry returns computed for every unfilled signal (the adverse-selection
measurement), 8-bar window, plus a random-walk phantom-profit check.

| | fill rate | filled ret | unfilled ret | effective maker RT | verdict |
|---|---|---|---|---|---|
| SCALP 5m | 56% | +11.6 bp | +21.4 bp | 20.6 bp | **ADVERSE_SELECTION + leak-check FAIL** — model invalid |
| DAY 15m | 50% | +14.3 bp | +13.9 bp | **39.1 bp** | model defensible, but maker costs MORE than taker |

The maker-cost claim does not survive measurement: on SCALP the fill model selects
for losers and prints phantom profit on random walks (both pre-registered failure
modes hit); on DAY it is structurally sound but its effective round-trip cost
(39.1 bps including missed-winner opportunity cost) is **worse than the 15 bps
taker RT**. Maker execution at OTE, as constructed, lowers no cost floor.

**8c — Conditional validity, one pass (`python3 k3.py condvalid`).** Grid
{liquidity, momentum-inverted} × {all bars, killzone} × {1,4,8,24} × 8 symbols,
BH-FDR across the entire expanded grid, standing power doctrine applied in advance
(DAY h=24 excluded as underpowered: detectable IC 0.36 > required 0.15).

| group | profile | KZ mean IC | all-bars IC | FDR cells | OOS | KZ spread | floors | verdict |
|---|---|---|---|---|---|---|---|---|
| liquidity | DAY | +0.035 | +0.037 | 6/24 | 19/24 | 2.7 bp | 16.5 / 58.7 bp | NOT VALIDATED |
| liquidity | SCALP | +0.020 | +0.010 | 1/32 | 19/24 | 2.5 bp | 16.5 / n/a | NOT VALIDATED |
| momentum-inv | DAY | +0.075 | +0.066 | 20/24 | 24/24 | 4.5 bp | 16.5 / 58.7 bp | NOT VALIDATED |
| momentum-inv | SCALP | +0.108 | +0.073 | 20/32 | 24/24 | 3.2 bp | 16.5 / n/a | NOT VALIDATED |

The structural hypothesis behaved as hypothesized — killzone conditioning DOES
raise momentum-inversion IC (SCALP 0.073 → 0.108, DAY 0.066 → 0.075), and the
statistical signal is robust (FDR-surviving, OOS-consistent). It dies at the
economic translation every time: 2.5–4.5 bps of quintile spread against a 16.5 bps
floor. **STUDY VERDICT, both profiles: NO GROUP CONDITIONAL-VALIDATED — K3's
systematic track closes under this protocol.** Published as plainly as the SCALP
failure, per the doctrine that negative results carry equal prominence. The fusion
score has no demonstrated, economically-viable predictive power at any tested
horizon, conditioning, or execution model. What remains is infrastructure (live
dashboard, alarms, ledger, harnesses) and one measured fact: crypto 5m/15m returns
mean-revert weakly (momentum inversion) — statistically detectable, but too weak to
pay for its own trading costs.



## Architecture

```
k3/
  config.py     # risk kernel + SCALP/DAY profiles + fusion weights
  data.py       # Binance futures API: top10, klines(+taker flow), klines_history (paginated 5k+ bars), funding hist/z, OI, indicators
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
  ledger.py     # Phase 7: exit-event ledger — MFE/MAE, TP conversion, dumb baseline, conditional-MFE test (8a: MAE control)
  validity.py   # Phase 6: pre-registered IC protocol (bootstrap null, BH-FDR, OOS, regimes)
  fillmodel.py  # Phase 8b: honest limit-fill simulation (strict trade-through, adverse selection, leak check)
  condvalid.py  # Phase 8c: conditional validity grid — power doctrine first, one shot, closes the track
  screener.py   # all-perp universe screener (range / tape / drift / funding ranks)
k3.py           # CLI: top10 | universe | scan | backtest | research | leaktest | causaltest | groupstudy | tiercal | scalp2 | ledger | validity | fillmodel | condvalid | replay
reports/        # JSON artifacts of every run
```

## Safety

K3 outputs **setups, not orders**. STANDBY means a gate failed (funding, liquidity,
crowding, HTF conflict) — the system watches, it doesn't force trades. Futures with
leverage can liquidate you; nothing here is financial advice.

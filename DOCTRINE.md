# K3 Close-Out Doctrine — What Was Tested, What Was Measured, Why the Track Closed

*Written 2026-07-27, at close, while fresh. This document is worth more than the code.*

---

## 1. The question and the rule

K3 set out to build a systematic edge in crypto perpetual futures at the 5m/15m
timescale — scalping and day trading the top-10 USDT-M pairs on Binance, with ICT/SMC
structure concepts fused into a five-group composite score.

The rule was written before the data existed, and it is the entire value of the
exercise:

> A group is **VALIDATED** only if its information coefficient is sign-stable across
> the majority of symbols, survives Benjamini-Hochberg FDR at q=0.10, is confirmed
> out-of-sample in a chronological holdout, **and is economically meaningful** — its
> quintile spread must clear the measured round-trip cost floor with margin.
> Breakeven is not validation. If nothing validates, the track closes and the result
> is published with the same prominence as a success.

The data came back negative. The track is closed. It is not being reopened, hedged,
or re-varianted.

## 2. What was tested

Eight phases, each pre-registered before it ran:

| Phase | Test | Harness |
|---|---|---|
| 1 | Look-ahead audit | Causal 3-candle FVG, confirmation-delayed swings (two leaks found and killed) |
| 2 | Economic + causal leakage | `leaktest` (random-walk P&L must be negative) + `causaltest` (truncation invariance) — both green, permanent |
| 3 | True baseline | 508 trades, 51.3% win, **−$7,056** DAY / SCALP dead out-of-sample |
| 4 | Tier recalibration | Train-60% thresholds, breadth-gated OOS adoption — no candidate cleared; shipped tiers kept, labeled un-validated |
| 5 | Execution mechanics | OTE limit entries, maker fees, structural stops — 90% less bleeding, still negative |
| 6 | Signal validity | 8 symbols × 6,000 bars × 4 horizons, non-overlapping Spearman IC, block-bootstrap null, BH-FDR, chronological OOS, regime breakdown |
| 7 | Exit-event ledger | MFE/MAE in R per transition, TP conversion, dumb-baseline ladder test, conditional-MFE bootstrap |
| 8 | Fill model + conditional economics | Strict trade-through fills, adverse selection, phantom-profit check; killzone-conditioned validity, power doctrine first |

Total search: 8 symbols × 6,000 bars × 4 horizons × 2 execution models × 1 registered
conditioning, every gate pre-registered, every null bootstrapped, every multiple-
comparison correction applied across the whole grid.

## 3. What was measured

**The composite is falsified.** Zero of 32 FDR-significant cells on either profile;
sign flips out-of-sample. The five-group fusion, as constructed, has no predictive
power at the 5m/15m scale.

**No group validated under any conditioning.** The strongest statistical signal —
momentum *inversion* — is sign-stable on 8/8 symbols, FDR-surviving (20/32 cells),
OOS-consistent 24/24, and *amplified* by killzone conditioning (SCALP IC 0.073 →
0.108). It is worth **2.5–4.5 bps of quintile spread against a 16.5 bps cost floor**.
The signal exists and is roughly a quarter of the size needed to pay for itself.

**Maker execution costs more than taker — 39.1 bps effective versus 15 bps.** The
most valuable thing K3 produced. Measured honestly — strict trade-through fills,
non-fills counted, missed-winner opportunity cost included — "just use limit orders
to cut fees" is *backwards* at this horizon. On the 5m profile it is worse than
backwards: the fill model adversely selects (unfilled signals +21.4 bps vs filled
+11.6 bps) and prints phantom profit on random walks. This finding is transferable
far beyond K3.

**The composite scored worse than its own best component.** Zero FDR cells for the
fusion; 17–20 for momentum alone. Weighted-sum fusion over correlated, oppositely-
signed components destroys information. Validate components individually; combine
only what validates.

**Why the 4.5 bps cannot be salvaged:** surviving with margin needs total round-trip
friction under ~2 bps. That requires being *paid* to provide liquidity — maker
rebates, negative fee tiers, colocation. That is market making: a different business,
different infrastructure, different capital. It is not a tuning gap; it is a
different industry.

## 4. What the discipline caught

The point of a falsification protocol is not the answer it gives; it is the losses
it prevents:

- A `shift(-2)` look-ahead that made the engine profit on coin flips (+$1,578 on
  random walks). Caught by `leaktest` before it took live capital. The retracted
  +$2,942 backtest was this bug.
- A fill-model fantasy — maker execution that would have "fixed" the economics on
  paper while selecting for losers and leaking on noise. Caught by 8b.
- A volatility artifact at the 100th percentile — the single best number in the
  project, the one most worth believing. Caught by its own MAE control and retracted
  in module output, not buried in prose.

## 5. What remains

- **Infrastructure that tells the truth**: live telemetry, killzone clock, funding/
  positioning feeds, the ledger, and the harnesses (`leaktest`, `causaltest`,
  `fillmodel`, `validity`, `condvalid`) — reusable by any future system at any
  timeframe.
- **A measurement most practitioners never obtain**: the size of the available
  signal at this timescale, in bps, against its cost floor. Many traders are live
  right now believing the +$2,942 version of their own backtest. This project closed
  with capital intact and the number measured.
- **The direction the arithmetic points**: horizon. At daily timeframes moves are
  2–5% while costs stay ~0.11% — friction falls from a quarter of the available move
  to a few percent of it, and a weak signal becomes viable. Any future work starts
  there, under this same protocol, pre-registered from bar one.

## 6. The doctrine, for reuse

1. Write the decision rule before the data exists. Honor it after.
2. Economic + causal gates are both necessary; neither is sufficient.
3. Every non-fill counts; every unfilled signal gets its market return computed.
4. Controls kill findings. Run them anyway. Retract in the module, not the prose.
5. Multiple comparisons: correct across the *entire* grid, never per-slice.
6. Power checks before the test, not after the null.
7. A statistically robust signal that cannot pay its costs is a market fact,
   not a trading strategy.
8. Negative results get equal prominence. They are the expensive kind of knowledge.

*— K3, closed 2026-07-27. Protocol by Fable5/Quantrex CTO doctrine. Harnesses and
data in this repository; every number reproducible from the CLI.*

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
- ~~**The direction the arithmetic points**: horizon.~~ *Superseded by Phase 9
  (below): the 1h horizon was tested under this protocol and failed; the
  pre-registered rule then closed all systematic trading — no further horizons,
  venues, or conditionings. The arithmetic's pointer is recorded here for honesty,
  but the rule outranks the pointer.*

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

## 7. Phase 9 — the horizon pivot, tested and closed (2026-07-27)

The doctrine's own pointer said longer horizons. Phase 9 tested that pointer under
the identical protocol, in two stages with a hard stop between them.

**Stage 0(a) — OI integrity audit: no retraction.** `g5_positioning` in every study
feature frame (Phase 5, 8c, ledger) is built from per-bar **taker flow** in the
klines (`taker_buy`, verified 0% null). Funding-z and OI-delta are *live-only
engine overlays* by design (`apply_positioning_overlay`) — they never entered any
historical study, so the OI endpoint bug (wrong base URL, 404 swallowed by a
fail-open `except`) could not have nulled anything in a study frame. The ledger's
`oi_delta: null` is documented design (no OI history at scale), and its funding
map verified 93.7%+ populated. Fail-open audit: study loops record symbol errors
explicitly (0 dropped symbols in 8c); the one dangerous class was `data.py` live
positioning endpoints — fixed for OI. New rule: a fail-open `except` that returns
`None` must log or count; silence is how the OI bug hid for a full phase.

**Stage 0(b/c) — gate arithmetic (`python3 k3.py hzgate`).** Spread-per-IC slope
c = 3.66 per unit σ, calibrated from 47 cells of the 8c DAY artifact. Typical
moves: 1h 31bp, 4h 64–70bp, 24h 171bp. Required IC to clear floors with 2×
margin: MEXC (5bp all-in) needs 0.088 at 1h, 0.039 at 4h; Binance (16.5bp) needs
0.29 at 1h — 4–8× anything ever measured, dead on arrival. Detectable IC at 80%
power (KZ slice, OOS): 0.061 at 1h×h=1 → **the only MEXC-powered cell in the
grid**. Gate: PASS on that cell alone. Caveats recorded: the KZ mask labels
zone-close bars in-zone, inflating KZ share at 1h (66.7% vs the intended ~52%)
and making 4h KZ conditioning meaningless (83.3% of bars "in zone").

**Stage 0(d) — maker economics re-derived, not inherited (`fillmodel --tf 1h`).**
The 58.7bp maker floor was declared void at this horizon, then measured: 151
setups, fill rate 28.5% (below the 60% sanity bound), unfilled signals +92.2bp
vs filled +72.0bp → **ADVERSE_SELECTION at 1h too**, maker 13.8 vs market 60.9
bp/signal, leak check PASS. The brief's hypothesis that longer working time
rescues maker fills is falsified: the OTE level deepens with 1h ATR faster than
the 8h window compensates. Maker is dead at both tested horizons.

**Stage 1 — the study (`python3 k3.py hzstudy`), one shot, 32 cells.**
Momentum tested **raw** per pre-registration: KZ mean IC **−0.019** (all-bars
−0.030) — **reversion persists at 1h; it does not flip to momentum**. Weaker
than at 15m (−0.075 raw) but sign-stable (7/8 OOS-consistent) with 2/8
FDR-significant cells. Median |KZ quintile spread|: **2.2bp vs the 10bp MEXC
clearing bar** → NOT VALIDATED. Liquidity: KZ IC −0.001, 0/8 FDR — the 15m
liquidity effect does not exist at 1h → NOT VALIDATED.

**Pre-registered decision, executed:** nothing validated at 1h, and the gate had
already excluded 4h on power. **K3 systematic trading is closed on all tested
horizons — 5m, 15m, and 1h — with no further horizons, venues, or conditionings
to be tested.** The final market fact: the reversion signal is real, persistent
across timescales, and everywhere too small to pay its costs. That is a complete
answer.

*— K3, closed 2026-07-27 on all tested horizons (5m/15m Phase 8; 1h Phase 9).
Protocol by Fable5/Quantrex CTO doctrine. Harnesses and data in this repository;
every number reproducible from the CLI.*

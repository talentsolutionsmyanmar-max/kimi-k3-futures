# K3 — Executive Obituary

*A research record that happens to end in a negative result. One page; every
number traceable to a committed artifact in this repository.*

K3 asked whether a five-group ICT-style signal system could make money
systematically on crypto perpetuals. It was run under a pre-registered
falsification protocol — decision rules written before the data existed — across
nine phases, three agents, and zero capital deployed. The answer, measured to the
basis point: **the signal is real, persistent across timescales, and too small to
pay its costs at every horizon tested.** The program closed itself on schedule, by
its own rule. That is a complete answer, and these are the things worth keeping
from it.

---

## 1. Three transferable findings

**Maker execution costs more than taker — measured, not theorised.** At 15m, an
honest limit-fill model (strict trade-through fills, every non-fill counted,
missed-winner opportunity cost included) priced maker execution at **39.1 bps
effective round-trip against ~15 bps taker** — and leaked phantom profit on
random walks until the model was fixed. Re-derived at 1h rather than inherited:
fill rate 28.5%, unfilled signals +92.2 bp vs filled +72.0 bp — adverse selection
again. The mechanism: the retracement level deepens with ATR faster than a longer
working window compensates. "Just use limit orders to cut fees" is backwards at
every horizon tested. This contradicts standard retail advice and generalises.

**The composite scored worse than its own best component.** The five-group
weighted-sum fusion scored **0/32 FDR-significant cells in both profiles**
(IC +0.016 DAY / −0.004 SCALP) while a single component — momentum, signed —
hit **16–20/32 depending on study and slice**. Weighted-sum fusion over
correlated, oppositely-signed inputs destroys information. Validate components
individually; combine only what validates. This generalises well beyond trading.

**The reversion signal is real, persistent, and sized to its timescale — the
shortfall is structural.** Raw momentum IC, all-bars slice: **−0.066 at 15m →
−0.030 at 1h** (−55% for a 4× horizon increase; killzone slice −0.075 → −0.019,
−75%). Sign-stable throughout — 8/8 symbols and 24/24 OOS-consistent cells at
15m; 7/8 OOS-consistent at 1h. But scaled by each horizon's cost, the
signal-to-friction ratio was approximately **invariant**: achieved/required IC
0.32 at 15m and 0.34 at 1h — roughly 3× short of the clearing bar at both. (The
killzone slice suggests degradation, 0.36 → 0.22, but carries the mask caveat in
§3 and is the less reliable of the two.) The mechanistic reading: a
microstructure effect proportionate to the timescale it is measured at. Horizon
change did not help and did not meaningfully hurt — the shortfall is structural,
not something a longer holding period trades away at the horizons measured.

## 2. The arithmetic that closed it

Friction as a share of the typical move (Binance taker ≈ 11 bps round-trip;
measured typical moves from `hzgate`):

| Horizon | Typical move | Friction share | Required IC to clear MEXC floor ×2 | Signal measured |
|---|---|---|---|---|
| 15m | 13.2 bp | ~83% | — (16.5 bp taker floor: spread 2.5–4.5 bp) | IC −0.066 |
| 1h | 31 bp | ~35% | 0.088 | IC −0.030 → 2.2 bp spread vs 10 bp bar |
| 4h | 64–70 bp | ~17% | 0.039 | excluded at gate — underpowered (7.5–315 yrs) |
| 24h | 171 bp | ~6% | 0.016 | excluded at gate — underpowered |

One line carries the whole argument: **across the two horizons actually
measured, the signal-to-friction ratio was invariant — roughly 3× short of the
clearing bar at both 15m and 1h.** The gate passed only the 1h × 1h cell; the
study ran that cell, one shot, 32 cells, and the spread came back 2.2 bp against
a 10 bp clearing bar. Not validated. Binance taker was never close: required IC
0.29 at 1h — 4–8× anything ever measured.

## 3. The boundary — what was NOT tested

What was tested: **time-series directional strategies at 5m/15m/1h across 8–10
symbols.** Recorded as untested, not falsified:

- **Cross-sectional strategies.** Every study measured time-series conditional
  quintile spread — bars sorted by signal strength within a symbol. Ranking all
  symbols against each other at each timestamp and trading the spread between
  them is a different quantity with different power characteristics. Never run.
- **Positioning data.** `g5_positioning` was built from taker flow in the
  klines; OI and funding were live-only engine overlays that never entered a
  historical study frame. The established finding is "*taker flow* does not
  predict" (IC ≈ −0.02, 2–3/32 FDR), not "positioning does not predict."
- **Daily and multi-day horizons.** 24h was excluded at the Stage 0 gate as
  underpowered — not tested and rejected. The honest extrapolation: if the
  measured ratio invariance held, a daily strategy would still be ~3× short of
  the clearing bar; if a different phenomenon dominates at that timescale, it is
  unknown either way. Recorded as untested.
- **Killzone conditioning is caveated.** The mask labelled zone-close bars
  in-zone: 66.7% coverage at 1h against an intended ~52%, and 83.3% at 4h where
  conditioning is meaningless. All 8c killzone results carry this caveat.

## 4. The rules — and what each one cost

A rule that never costs anything was never a rule. Each of these was honored
against interest:

- **The retracted +$2,942 DAY baseline.** The headline backtest result was a
  look-ahead bug; `causaltest` caught it, the true baseline was −$7,056, and the
  +$2,942 was retracted in the record, not the footnotes.
- **The retracted 100th-percentile conditional MFE.** The most exciting number
  the program produced — killed by its own MAE control (8a): both tails were
  extreme, so it was volatility conditioning, not edge. Retracted in the module
  that published it.
- **The maker-cost hypothesis, falsified twice.** Once at 15m (39.1 bps), once
  at 1h (adverse selection) — the second time after the protocol explicitly
  predicted the opposite.
- **The closure itself.** Executed on schedule, on the pre-registered rule,
  rather than argued around. The pointer toward longer horizons was the
  program's own doctrine; the rule outranked the pointer.

## 5. The ledger

Eight phases across nine. Three agents. Zero capital deployed. One look-ahead
caught, one fill-model fantasy caught, one volatility artifact caught. The
systematic track closed at 5m/15m in Phase 8 and at 1h in Phase 9; this document
is Phase 10 and the last artifact.

## 6. The naming-defect pattern — doctrine, added at close

Three separate substantive confusions traced to naming or silent failure:
`aggtrade_volumes` (cost a multi-day investigation and a wrong CTO hypothesis),
`oi_delta` (hidden behind a fail-open `except` for a full phase — a 404
misdiagnosed as regional blocking), and `g5_positioning` (contained no
positioning data). Recorded as doctrine:

> **A feature's name is part of its contract. A fail-open handler must log or
> count — silence is indistinguishable from absence of signal.**

---

*K3, closed 2026-07-27 on all tested horizons. Protocol by Fable5/Quantrex CTO
doctrine; measurement, harnesses, and this record by Kimi. Every figure
reproducible from the CLI (`validity`, `condvalid`, `fillmodel`, `hzgate`,
`hzstudy`) and the committed artifacts under `reports/`.*

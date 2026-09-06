# V38 Canonical Early1 Validation — 2026-09-06

## Verdict

**Research canonical: PASS / Early1 remains the strongest directly comparable candidate.**

This is not a production-CAGR claim and does not change main. The validation uses the pinned research source, frozen Reset and Stage56 artifacts, next-open causal replication, security-level turnover costs, a fresh Yahoo OHLCV data-vintage rerun, and a separate Gross100 funding-state invariant audit.

## Canonical rule tested

- Core DDV: 20M, applied after adopted Top12 construction; DDV failure leaves vacancy.
- Total capacity: ATTACK 12, SELECTIVE 4.
- Early reservation: ATTACK Core11 + Early1; SELECTIVE Core3 + Early1. No 13th slot.
- Early score: `RS21_HIGH_ACCEL`.
- Early gate: `NOT_RED` plus existing Breadth capacity (>=50 for fills).
- Early max age: 10 trading days.
- Direct Early -> Core promotion retained.
- Core ranking and V38 exit mechanics unchanged.
- Frozen strict Reset.
- Frozen Stage56 `M30_TOUCH30_F80_D10` TQQQ target.
- Gross <=100%.
- Decision/execution research standard: prior information -> next open/open-to-open.
- Primary cost: per-security 5bp; 0/10/20bp also tested.

## Fresh data-vintage rerun

GitHub Actions run: **33972198145, attempt 2**.

Pinned research source: `898a684142239fa77ce6dd28b2c35b43e3b188ec`.

Frozen Reset artifact digest: `sha256:6db59e07c5eb3c248de0748b9d7f8c43183f96fc80f739faee8250246b10d59d`.

Frozen Stage56 artifact digest: `sha256:b6df441dae8be5bb6f6f5ceb7771472545e20b270c7016c1a7936915f8f7482d`.

Fresh output artifact: ID **9989377963**, digest `sha256:90ebc6b87b0e442f2cf364630afa80c617886ef7f2d1a524cf342f1ee07cdc81`.

The computation and artifact upload succeeded. The overall attempt is marked failure only because its final research-branch push was rejected as non-fast-forward after the branch had advanced; this does not affect the completed calculation or uploaded artifact.

### Causal 5bp full-period result

Period: 2016-01-04 through 2026-03-20, 2,567 open intervals.

| Variant | CAGR | MDD | Sharpe | Sortino | Calmar |
|---|---:|---:|---:|---:|---:|
| **EARLY1** | **50.0234058%** | **-28.1000485%** | **1.379952** | **2.020740** | **1.780189** |
| EARLY0 | 48.6535506% | -28.7669935% | 1.354820 | 1.975141 | 1.691298 |
| CORE_DDV50 | 49.1763702% | -33.1766867% | 1.344902 | 1.964630 | 1.482257 |
| EARLY2 | 48.0682671% | -27.0277224% | 1.346821 | 1.973524 | 1.778480 |
| EARLY1_CURRENT_LIQ | 48.9674597% | -29.5866005% | 1.364159 | 1.990741 | 1.655055 |
| EARLY1_LEGACY_LIQ | 48.0414264% | -29.7247423% | 1.343175 | 1.956183 | 1.616210 |
| CORE_DDV20_REFILL | 46.9075259% | -29.6078202% | 1.321380 | 1.920351 | 1.584295 |
| CORE_DDV10 | 45.7845772% | -27.5840201% | 1.295675 | 1.885884 | 1.659822 |

EARLY1 - EARLY0 observed CAGR delta: approximately **+1.37 percentage points**.

### Data-vintage stability

Attempt-1 EARLY1 5bp CAGR was 50.0234002%; fresh attempt-2 is 50.0234058%. Difference is approximately **+0.0000056 percentage point**.

Attempt-1 EARLY0 5bp CAGR was 48.6535475%; fresh attempt-2 is 48.6535506%. Difference is approximately **+0.0000030 percentage point**.

The ranking and practical result are unchanged despite a fresh OHLCV download. The failed-history symbol set remains consistent with the known current static-universe data-quality limitations.

## Cost and subperiod robustness

Previously frozen same-engine sensitivity remains applicable to the same source/rule definition:

- EARLY1 0bp: ~51.91% CAGR.
- EARLY1 5bp: ~50.02%.
- EARLY1 10bp: ~48.16%.
- EARLY1 20bp: ~44.50%.

EARLY1 remains ahead of EARLY0 at 0/5/10/20bp.

Broad 5bp periods also favor EARLY1:

- 2016-2020: ~55.12% vs ~52.94%.
- 2021-2025: ~47.43% vs ~46.53%.
- 2022-2025: ~50.18% vs ~49.34%.
- 2022-2026 available: ~47.33% vs ~46.81%.

However calendar-year leadership is not uniform; aggregate advantage is concentrated in several strong periods rather than winning every year.

## Statistical uncertainty

Paired causal 5bp block bootstrap, 5,000 simulations:

- 20-day blocks: median EARLY1-EARLY0 CAGR delta +1.22pt; 90% interval **[-2.01,+4.76]pt**; positive share 73.0%.
- 60-day blocks: median +1.38pt; 90% interval **[-1.65,+4.57]pt**; positive share 76.4%.
- Year-cluster resampling: 90% interval **[-1.51,+4.89]pt**; positive share 77.3%.

Intervals cross zero. The observed advantage is directionally consistent but not statistically decisive.

## Funding-state invariant audit

GitHub Actions run: **34033745858**.

Artifact: **9989469270**, `astra-v38-canonical-funding-invariant`.

Allocation tested exactly as research Gross100 priority:

`Reset -> protected TQQQ (<=80%) -> Ordinary (<=70%) -> TQQQ extra`, with selective fill only where native TQQQ >0.

### EARLY1

- Dates: 2,568.
- Days with ordinary positions: 1,804.
- Days with Reset positions: 1,246.
- Ordinary zero-funded days while virtual holdings existed: **0**.
- Reset zero-funded days: **0**.
- Positive virtual Core/Early holdings reduced to zero actual weight: **0**.
- Gross >100% violations: **0**.
- Minimum ordinary proportional funding scale: **0.06539**.
- 1st percentile: 0.13279.
- 5th percentile: 0.16936.
- Median: 0.71989.
- Reset funding scale minimum/median: **1.0 / 1.0**.
- Maximum total gross: 1.0000000000000002 (floating-point tolerance).
- Funding-state invariant: **PASS**.

### Meaning

Within the current fractional-share research model, Gross100 funding priority never deletes a virtual Core/Early or Reset holding. Core/Early state transitions are price-, age-, sleeve-, slot-, partial-flag- and promotion-based rather than dollar-NAV based. Therefore proportional funding compression does not change the held-symbol state sequence under these assumptions.

This materially reduces the concern that the causal portfolio result is using a symbol-state path that would disappear solely because of Gross100 cash competition.

It does **not** validate whole-share rounding, broker minimums, actual fill microstructure, taxes, or a delisting-complete point-in-time universe.

## Additional stress findings

- One extra day delay applied to all targets: CAGR ~40.39%, MDD ~-30.36%; still positive but materially weaker.
- Worst historical drawdown in the causal series: ~-28.10%; longest major underwater episode was roughly 614 calendar days.
- Synthetic block-path reorderings can produce much deeper drawdowns (roughly -46% to -50% in adverse tails); these are stress scenarios, not forecasts.
- TQQQ is the largest return contributor. Removing TQQQ from the frozen decision overlay drops CAGR to ~13.86%.
- Early is incremental rather than the primary engine; removing Early from the Early1 composite drops CAGR from ~50.02% to ~48.10% in the fixed-decision ablation.
- Early-origin trades remain right-tail dependent: removing the largest few winners materially reduces trade-level PF/mean.
- Direct Early->Core promotion remains weakly identified (only 9 promoted trades in the trade audit). Keep it as the current research setting, but do not claim its standalone edge is proven.
- QQQ 30-week hard gating materially worsened the composite and remains rejected.

## Final classification

| Item | Classification |
|---|---|
| Canonical DDV20 + Early1 RS21_HIGH_ACCEL composite | **Research PASS / current research best** |
| Early1 vs Early0 superiority | **Directionally supported, not statistically decisive** |
| Fresh data-vintage reproducibility | **PASS** |
| Gross100 funding-state continuity | **PASS** |
| Early2 | **Reject as replacement** |
| LIQ_ACCEL replacement | **Reject as replacement** |
| DDV refill beyond Top12 | **Reject** |
| QQQ W30 hard gate | **Reject** |
| Direct promotion standalone edge | **Unproven / retain provisionally** |
| Production main adoption | **Not automatic; requires explicit decision and production implementation audit** |

## Production safety

All new code/workflows in this validation are confined to `research/astra-v38-full-audit-20260905`. No main, Dashboard UI, V38 live state, production workflow, public page or production rule has been changed.

# V38 Astra Audit Addendum — 2026-09-06

This addendum supersedes the MC15/MC57 interpretation in `V38_ASTRA_AUDIT_20260906.md` where the earlier report treated the current MC15 transform as a possible unvalidated scale substitution for Stage56. That blocker is withdrawn after commit/run-level verification.

## 1. MC57 / MC15 correction

- `57` is the fixed Market Conditions ETF universe size, not a score lookback.
- Current `build_dashboard.py` keeps the confirmed Raw construction at **57 ETFs × 12 equal-weight metrics → EMA2 Raw**.
- `MC15` means the final Raw score is normalized against the **previous 3780 trading sessions (15 years)** and mapped symmetrically to 0–100.
- The MC15 migration explicitly preserved the 57-ETF/12-metric Raw and changed the post-Raw normalization layer.
- Stage56 fixed audit run **33080590798** executed on 2026-08-27, after the MC15 migration on 2026-08-25/26. Its research data path calls `bd.MC_MARKET_TICKERS` and then `bd.mri_frame(...)`.
- Therefore Stage56's MC thresholds (including 20/25/35/40/65 used in inherited hierarchy logic) were evaluated on the MC15-style series in that fixed run. The remaining names `mc57` / `compute_mc57()` are legacy naming debt, not evidence that Stage56 used a different 57-point scale.

**Corrected verdict:** MC15/MC57 naming is not a production-change blocker. Do not split or recalibrate Stage56 merely because the variable is named `mc57`.

## 2. Old Early1 53.636620% provenance

Historical result is verified as a real successful GitHub Actions result:

- Run: **33877667359**
- Head commit: **6f5105cd9d5fa143b47e1babdf5a4e44a555b7c4**
- Period: **2016-01-04 through 2026-03-20**
- Early1 Promote: **53.636620% CAGR**
- Early0: **51.763499% CAGR**
- Early1 No-Promote: **53.046031% CAGR**
- Fixed Reset input artifact digest: `sha256:6db59e07c5eb3c248de0748b9d7f8c43183f96fc80f739faee8250246b10d59d`
- Fixed Stage56 TQQQ artifact digest: `sha256:b6df441dae8be5bb6f6f5ceb7771472545e20b270c7016c1a7936915f8f7482d`
- Output artifact: `gross100-early1-promotion-audit`, artifact 9938829101, digest `sha256:454cdcf22d557df465ba065553aa7c61af5304ce97ba6010f7629ac1f1718107`.

The old run downloaded the 3,595-stock OHLCV universe live from Yahoo during the run. The full ordinary-stock OHLCV snapshot was not frozen into the output artifact. Consequently the later reproducible value **53.217238% / 53.217241%** cannot be reconciled to 53.636620% at the individual-price-bar level.

No source-function or universe-file change was found that explains the approximately **0.41938 percentage-point** gap. Small differences in failed Yahoo symbols/history exist, but the audit cannot uniquely attribute the gap to Yahoo, corporate-action corrections, delisted history, or another data-vintage change.

**Disposition:** 53.636620% is **historically verified but not reproducible**. Preserve it in the genealogy, but retire it as the operative benchmark. The reproducible legacy benchmark is 53.21724%, and even that remains a legacy SAME_DAY_GROSS research result rather than an executable expected CAGR.

## 3. Final same-engine causal comparison: Early1 vs Early0

Simulator: `CAUSAL_OPEN_REPLICATION`, same static universe/Core rules/frozen Reset/frozen Stage56, next-open timing, per-security turnover with 5bp cost, gross ≤100%, 2016-01-04 through 2026-03-20.

| Variant | CAGR | MDD | Sharpe | Calmar |
|---|---:|---:|---:|---:|
| Early1 | **50.0234%** | **-28.1000%** | **1.3800** | **1.7802** |
| Early0 | 48.6535% | -28.7670% | 1.3548 | 1.6913 |

Observed Early1 advantage: **+1.3699 percentage points CAGR**, with slightly better historical MDD, Sharpe and Calmar in this simulator.

Broad-period CAGR comparison also favors Early1:

| Period | Early1 | Early0 | Delta |
|---|---:|---:|---:|
| 2016–2020 | 55.12% | 52.94% | +2.18pt |
| 2021–2025 | 47.43% | 46.53% | +0.89pt |
| 2022–2025 | 50.18% | 49.34% | +0.84pt |
| 2022–2026 available | 47.33% | 46.81% | +0.52pt |

Cost sensitivity does not reverse the direction: at 20bp, Early1 is about **44.50%** versus Early0 about **43.53%**.

However robustness intervals still cross zero:

- 20-day block bootstrap, 5,000 sims: median delta +1.22pt; 90% interval **[-2.01, +4.76]pt**; positive-return-delta share 73.0%.
- 60-day block bootstrap: median +1.38pt; 90% interval **[-1.65, +4.57]pt**; positive share 76.4%.
- Year-cluster resampling: 90% interval **[-1.51, +4.89]pt**; positive share 77.3%.

These are resampling frequencies, not probabilities that Early1 is truly superior.

## 4. Trade-level qualification

Under the 5bp ordinary-stock virtual sleeve:

- Early-origin trades: 223, 193 symbols, mean +1.14%, win 48.88%, PF 1.296.
- Symbol-cluster 90% interval for mean Early return: **[-0.32%, +2.78%]**; PF interval **[0.925, 1.811]**.
- Direct Early→Core promotions: only 9 trades / 8 symbols; mean -3.81%, PF 0.606. This is too small to conclude promotion should be removed.
- No-Promote versus Promote portfolio differences also include slot reuse and downstream trade changes; they are not the same thing as the P/L of the nine promoted trades.

The separate early-leader capture objective is still unmet: historical capture work showed that future major leaders were usually entered after very large prior run-up; adding slots mechanically did not solve that problem.

## 5. Updated audit verdict

### Production
**UNCHANGED / insufficient evidence for a production strategy change.**

Do not change main merely because Early1 has the best observed causal result. The directional evidence is meaningful, but the uncertainty interval crosses zero, no pristine untouched OOS remains, and the static present-day universe/taxonomy is not a delisting-complete point-in-time database.

### Research best
**Early1 remains the research-best Early design** among the directly comparable variants:

- one reserved Early slot inside total capacity (Attack Core11+Early1; Selective Core3+Early1), not a 13th slot;
- `RS21_HIGH_ACCEL`;
- NOT_RED plus the existing Breadth-capacity requirement;
- max 10 trading days;
- DDV20 / Vacancy-Top12 context;
- direct Core promotion retained as a research setting, but promotion edge itself remains unproven.

### 53.64 handling
Keep 53.636620% only as a historical genealogy record. Do not use it in current rankings or expected-return claims. Use the causal simulator for decision comparisons, not SAME_DAY_GROSS headline CAGR.

### MC handling
Keep the current 57-ETF Market Conditions construction and Stage56 logic unchanged on the basis of this audit. Optionally rename legacy `mc57` identifiers in a future non-functional cleanup only if separately tested; no strategy recalibration is justified by the name alone.

## 6. Production safety

This addendum modifies only `research/astra-v38-full-audit-20260905`. No main, Dashboard UI, V38 live output, production workflow, public page, or production state is changed.
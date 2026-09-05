# Options nested attribution — 2026-09-05

Research only. This is the final attribution pass for the current 11-session sample; no production files were changed.

## Nested out-of-date deltas versus baseline+depth

The reference model already contains technical/sector controls plus OI and strike depth. Positive spread/IC deltas are better; negative MSE deltas are better.

|Added structure|Metric|Dates|Delta|95% date CI|Improved dates|
|---|---|---:|---:|---:|---:|
|base+depth+flip minus base+depth|ic|6|-0.0001|-0.0045 to 0.0041|33.33%|
|base+depth+flip minus base+depth|spread|6|-0.43%|-1.92% to 0.59%|33.33%|
|base+depth+flip minus base+depth|mse|6|0.0000|-0.0000 to 0.0000|16.67%|
|base+depth+gex minus base+depth|ic|6|0.0005|-0.0169 to 0.0142|66.67%|
|base+depth+gex minus base+depth|spread|6|-0.40%|-1.28% to 0.14%|50.00%|
|base+depth+gex minus base+depth|mse|6|0.0000|-0.0000 to 0.0000|50.00%|
|base+depth+wall_rr minus base+depth|ic|6|0.0021|-0.0039 to 0.0088|83.33%|
|base+depth+wall_rr minus base+depth|spread|6|-0.04%|-0.20% to 0.12%|33.33%|
|base+depth+wall_rr minus base+depth|mse|6|0.0000|0.0000 to 0.0000|16.67%|
|base+depth+flip+gex minus base+depth|ic|6|-0.0014|-0.0189 to 0.0108|66.67%|
|base+depth+flip+gex minus base+depth|spread|6|-0.43%|-1.29% to 0.10%|33.33%|
|base+depth+flip+gex minus base+depth|mse|6|0.0000|0.0000 to 0.0000|16.67%|
|base+depth+flip+wall_rr minus base+depth|ic|6|0.0035|-0.0065 to 0.0166|66.67%|
|base+depth+flip+wall_rr minus base+depth|spread|6|0.17%|-0.18% to 0.65%|33.33%|
|base+depth+flip+wall_rr minus base+depth|mse|6|0.0000|0.0000 to 0.0000|16.67%|
|base+all_rr minus base+depth|ic|6|-0.0030|-0.0193 to 0.0148|50.00%|
|base+all_rr minus base+depth|spread|6|0.11%|-0.06% to 0.29%|50.00%|
|base+all_rr minus base+depth|mse|6|0.0000|0.0000 to 0.0000|0.00%|
|base+all_dist minus base+depth|ic|6|-0.0329|-0.0819 to 0.0049|33.33%|
|base+all_dist minus base+depth|spread|6|-0.59%|-1.42% to 0.04%|33.33%|
|base+all_dist minus base+depth|mse|6|0.0000|-0.0000 to 0.0001|50.00%|

## Date-by-date partial coefficients

Each date is a separate standardized cross-sectional ridge regression. These coefficients ask whether each feature has residual association after the named controls.

|Test|Dates|Mean standardized coefficient|95% date CI|Positive dates|
|---|---:|---:|---:|---:|
|flip | base+depth|5|-0.09%|-0.40% to 0.20%|40.00%|
|flip | base+depth+wall+gex|4|0.14%|0.02% to 0.34%|100.00%|
|gex | base+depth|6|-0.05%|-0.24% to 0.14%|66.67%|
|log_oi | base+strikes|6|0.47%|0.34% to 0.63%|100.00%|
|log_strikes | base+oi|6|-0.06%|-0.42% to 0.26%|50.00%|
|wall_rr | base+depth|6|-0.23%|-0.50% to 0.03%|33.33%|

## Historical DDV control for OI

Eligible DDV-controlled independent dates: 0; summed cross-sectional observations: 0.
OI standardized coefficient after technical/sector/price/DDV/strike controls: — (— to —); positive dates —.

## Consolidated interpretation

- After OI/strike depth is already known, adding Flip changes the out-of-date top-bottom spread by -0.43%. Thus the strong univariate Flip ranking is not yet proven to be independent of depth/other controls.
- Adding Wall RR on top of depth changes spread by -0.04%. Do not reverse or increase its directional weight from this short sample.
- Adding GEX on top of depth changes spread by -0.40%. Dealer-side ambiguity remains unresolved.
- OI depth is the most persistent quality-associated feature in the current sample, but it may proxy liquidity, company size, institutional attention, or provider coverage. It should not be called bullish positioning.
- Historical DDV coverage is too sparse for a credible liquidity-controlled conclusion. This is a key reason to keep collecting all-liquid daily snapshots before production reweighting.

## Decision for this sample

No production weight/threshold change is justified yet. The useful research hypotheses are: downside score asymmetry, Options-market depth as a quality variable, Gamma Flip as a conditional structure variable, and Wall as a path/level variable rather than a standalone directional predictor. Freeze these hypotheses and retest at ~40 and ~120 independent sessions.

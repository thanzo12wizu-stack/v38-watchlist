# Options incremental-value reconciliation — 2026-09-05

Research only. No production logic or upstream artifact was changed.

Purpose: reconcile why Gamma Flip looked strong in univariate ranks while OI/strike depth explained more of the out-of-date model improvement.

## Coverage

- Rows: 4,062
- Tickers: 1,734
- Independent dates: 11
- Strict complete-case rows/dates/tickers: 1,567 / 6 / 757
- Historical DDV availability: 1,674/4,062 (41.2%). It is not used as a historical control when missing.

## Pairwise leave-one-date-out tests

Each candidate model is compared with the same baseline on exactly the same rows. This avoids attributing a sample-composition change to the feature itself.

|Sample|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|
|---|---|---|---:|---:|---:|---:|---:|
|pair:base+all_dist|base+all_dist|ic|6|0.0826|0.0277|-0.0098 to 0.0652|83.33%|
|pair:base+all_dist|base+all_dist|spread|6|1.42%|0.91%|0.10% to 1.61%|83.33%|
|pair:base+all_dist|base+all_dist|mse|6|0.0024|-0.0001|-0.0003 to 0.0001|66.67%|
|pair:base+all_rr|base+all_rr|ic|6|0.1125|0.0576|0.0207 to 0.0913|83.33%|
|pair:base+all_rr|base+all_rr|spread|6|2.12%|1.61%|1.08% to 2.15%|100.00%|
|pair:base+all_rr|base+all_rr|mse|6|0.0024|-0.0001|-0.0003 to 0.0000|83.33%|
|pair:base+depth|base+depth|ic|6|0.1531|-0.0085|-0.0353 to 0.0217|33.33%|
|pair:base+depth|base+depth|spread|6|2.40%|0.16%|-1.05% to 1.31%|66.67%|
|pair:base+depth|base+depth|mse|6|0.0031|-0.0002|-0.0003 to -0.0000|83.33%|
|pair:base+depth+flip|base+depth+flip|ic|6|0.1523|0.0070|-0.0398 to 0.0520|50.00%|
|pair:base+depth+flip|base+depth+flip|spread|6|2.27%|0.53%|-0.57% to 1.59%|66.67%|
|pair:base+depth+flip|base+depth+flip|mse|6|0.0031|-0.0002|-0.0003 to 0.0000|66.67%|
|pair:base+depth+flip+gex|base+depth+flip+gex|ic|6|0.1442|-0.0012|-0.0323 to 0.0333|33.33%|
|pair:base+depth+flip+gex|base+depth+flip+gex|spread|6|2.36%|0.61%|-0.48% to 1.43%|83.33%|
|pair:base+depth+flip+gex|base+depth+flip+gex|mse|6|0.0031|-0.0002|-0.0003 to 0.0000|66.67%|
|pair:base+depth+flip+wall_dist|base+depth+flip+wall_dist|ic|6|0.0841|0.0292|-0.0153 to 0.0742|66.67%|
|pair:base+depth+flip+wall_dist|base+depth+flip+wall_dist|spread|6|1.44%|0.92%|0.31% to 1.62%|83.33%|
|pair:base+depth+flip+wall_dist|base+depth+flip+wall_dist|mse|6|0.0024|-0.0001|-0.0003 to 0.0001|66.67%|
|pair:base+depth+flip+wall_rr|base+depth+flip+wall_rr|ic|6|0.1190|0.0641|0.0182 to 0.1159|83.33%|
|pair:base+depth+flip+wall_rr|base+depth+flip+wall_rr|spread|6|2.18%|1.67%|1.00% to 2.49%|100.00%|
|pair:base+depth+flip+wall_rr|base+depth+flip+wall_rr|mse|6|0.0023|-0.0001|-0.0003 to 0.0000|66.67%|
|pair:base+depth+gex|base+depth+gex|ic|6|0.1517|-0.0100|-0.0390 to 0.0199|50.00%|
|pair:base+depth+gex|base+depth+gex|spread|6|2.46%|0.23%|-0.82% to 1.11%|66.67%|
|pair:base+depth+gex|base+depth+gex|mse|6|0.0031|-0.0002|-0.0003 to -0.0000|83.33%|
|pair:base+depth+wall_rr|base+depth+wall_rr|ic|6|0.0969|0.0452|0.0106 to 0.0832|66.67%|
|pair:base+depth+wall_rr|base+depth+wall_rr|spread|6|1.74%|0.88%|-0.77% to 2.41%|66.67%|
|pair:base+depth+wall_rr|base+depth+wall_rr|mse|6|0.0023|-0.0001|-0.0003 to -0.0000|83.33%|
|pair:base+flip|base+flip|ic|6|0.1372|-0.0082|-0.0142 to -0.0021|33.33%|
|pair:base+flip|base+flip|spread|6|1.71%|-0.04%|-0.23% to 0.14%|50.00%|
|pair:base+flip|base+flip|mse|6|0.0033|-0.0000|-0.0000 to 0.0000|66.67%|
|pair:base+oi|base+oi|ic|6|0.1548|-0.0069|-0.0321 to 0.0214|50.00%|
|pair:base+oi|base+oi|spread|6|2.40%|0.17%|-0.97% to 1.30%|66.67%|
|pair:base+oi|base+oi|mse|6|0.0031|-0.0002|-0.0003 to -0.0000|83.33%|
|pair:base+strikes|base+strikes|ic|6|0.1314|-0.0302|-0.0642 to 0.0007|16.67%|
|pair:base+strikes|base+strikes|spread|6|2.26%|0.02%|-0.57% to 0.65%|33.33%|
|pair:base+strikes|base+strikes|mse|6|0.0032|-0.0000|-0.0001 to 0.0000|66.67%|

## Strict common-sample model comparison

All variants below use the identical complete-case rows.

|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|
|---|---|---:|---:|---:|---:|---:|
|base+all_dist|ic|6|0.0826|0.0277|-0.0103 to 0.0658|83.33%|
|base+all_dist|spread|6|1.42%|0.91%|0.10% to 1.61%|83.33%|
|base+all_dist|mse|6|0.0024|-0.0001|-0.0003 to 0.0001|66.67%|
|base+all_rr|ic|6|0.1125|0.0576|0.0213 to 0.0913|83.33%|
|base+all_rr|spread|6|2.12%|1.61%|1.08% to 2.15%|100.00%|
|base+all_rr|mse|6|0.0024|-0.0001|-0.0003 to 0.0000|83.33%|
|base+depth|ic|6|0.1155|0.0606|0.0180 to 0.1037|83.33%|
|base+depth|spread|6|2.01%|1.50%|1.07% to 1.96%|100.00%|
|base+depth|mse|6|0.0023|-0.0002|-0.0003 to 0.0000|83.33%|
|base+depth+flip|ic|6|0.1154|0.0605|0.0136 to 0.1060|83.33%|
|base+depth+flip|spread|6|1.58%|1.07%|-0.31% to 2.34%|83.33%|
|base+depth+flip|mse|6|0.0023|-0.0002|-0.0003 to 0.0000|83.33%|
|base+depth+flip+gex|ic|6|0.1141|0.0593|0.0188 to 0.0936|83.33%|
|base+depth+flip+gex|spread|6|1.59%|1.07%|0.36% to 1.80%|83.33%|
|base+depth+flip+gex|mse|6|0.0023|-0.0001|-0.0003 to 0.0000|83.33%|
|base+depth+flip+wall_dist|ic|6|0.0841|0.0292|-0.0144 to 0.0767|66.67%|
|base+depth+flip+wall_dist|spread|6|1.44%|0.92%|0.31% to 1.62%|83.33%|
|base+depth+flip+wall_dist|mse|6|0.0024|-0.0001|-0.0003 to 0.0001|66.67%|
|base+depth+flip+wall_rr|ic|6|0.1190|0.0641|0.0182 to 0.1167|83.33%|
|base+depth+flip+wall_rr|spread|6|2.18%|1.67%|1.00% to 2.55%|100.00%|
|base+depth+flip+wall_rr|mse|6|0.0023|-0.0001|-0.0003 to 0.0000|66.67%|
|base+depth+gex|ic|6|0.1160|0.0611|0.0216 to 0.0942|83.33%|
|base+depth+gex|spread|6|1.62%|1.11%|0.40% to 1.84%|83.33%|
|base+depth+gex|mse|6|0.0023|-0.0002|-0.0003 to 0.0000|83.33%|
|base+depth+wall_rr|ic|6|0.1176|0.0628|0.0190 to 0.1029|83.33%|
|base+depth+wall_rr|spread|6|1.97%|1.46%|1.00% to 2.00%|100.00%|
|base+depth+wall_rr|mse|6|0.0023|-0.0001|-0.0003 to 0.0000|83.33%|
|base+flip|ic|6|0.0560|0.0012|-0.0092 to 0.0144|50.00%|
|base+flip|spread|6|0.63%|0.12%|-0.12% to 0.37%|66.67%|
|base+flip|mse|6|0.0025|-0.0000|-0.0000 to 0.0000|50.00%|
|base+oi|ic|6|0.1181|0.0632|0.0188 to 0.1118|83.33%|
|base+oi|spread|6|1.99%|1.48%|1.02% to 1.96%|100.00%|
|base+oi|mse|6|0.0023|-0.0002|-0.0003 to -0.0000|83.33%|
|base+strikes|ic|6|0.0798|0.0249|0.0032 to 0.0482|66.67%|
|base+strikes|spread|6|1.54%|1.03%|0.54% to 1.61%|100.00%|
|base+strikes|mse|6|0.0025|-0.0000|-0.0001 to 0.0000|83.33%|

## Univariate cross-sectional spreads

Top 20% minus bottom 20% 5d ex-QQQ. Sector-neutral rows first rank within sector/date and then equal-weight sectors by date.

|Feature|Sector neutral|Dates|Spread|95% date CI|Positive dates|
|---|---|---:|---:|---:|---:|
|log_oi|no|6|1.43%|0.54% to 2.39%|100.00%|
|log_oi|yes|3|1.73%|0.46% to 3.58%|100.00%|
|log_strikes|no|6|-1.14%|-2.61% to 0.38%|16.67%|
|log_strikes|yes|3|0.33%|-0.16% to 0.76%|66.67%|
|flip_cap|no|6|0.99%|0.36% to 1.56%|83.33%|
|flip_cap|yes|3|0.88%|0.16% to 1.61%|100.00%|
|log_wall_rr|no|6|-0.93%|-1.63% to -0.20%|16.67%|
|log_wall_rr|yes|3|0.48%|-0.47% to 1.44%|66.67%|
|signed_log_gex_per_oi|no|6|0.55%|-0.20% to 1.44%|50.00%|
|signed_log_gex_per_oi|yes|3|0.35%|0.13% to 0.50%|100.00%|

## Price-bucket check for depth

Within each date, stocks are split into four price buckets. This does not replace market-cap/DDV controls, but checks whether depth is only a share-price proxy.

|Feature|Dates|Spread|95% date CI|Positive dates|
|---|---:|---:|---:|---:|
|log_oi | priceQ1|3|2.87%|-0.13% to 8.71%|66.67%|
|log_strikes | priceQ1|3|1.03%|-0.03% to 2.48%|66.67%|
|log_oi | priceQ2|3|2.11%|1.42% to 3.11%|100.00%|
|log_strikes | priceQ2|3|1.28%|-0.54% to 2.48%|66.67%|
|log_oi | priceQ3|3|0.52%|-0.73% to 2.77%|33.33%|
|log_strikes | priceQ3|3|0.13%|-1.59% to 3.48%|33.33%|
|log_oi | priceQ4|3|1.17%|-0.54% to 2.75%|66.67%|
|log_strikes | priceQ4|3|0.30%|-2.33% to 3.74%|33.33%|

## Strict-sample univariate check

This tells us whether Flip's earlier univariate effect disappeared merely because the multivariate model required more complete fields.

|Feature|Dates|Spread|95% date CI|Positive dates|
|---|---:|---:|---:|---:|
|flip_cap|6|1.00%|0.34% to 1.58%|83.33%|
|log_oi|6|1.76%|0.88% to 2.73%|100.00%|
|log_strikes|6|-0.95%|-2.79% to 0.80%|33.33%|
|log_wall_rr|6|-0.88%|-1.62% to -0.11%|16.67%|
|signed_log_gex_per_oi|6|0.57%|-0.36% to 1.61%|66.67%|

## Interpretation

- Largest pairwise out-of-date spread improvement: base+depth+flip+wall_rr, 1.67% across 6 dates.
- Depth and Flip appear complementary on matched samples: the combined model improves more than either addition alone. This is still exploratory because the independent-date count is small.
- OI/strike depth may represent option tradability, institutional attention, company size, or data quality rather than directional positioning. Without reliable historical DDV/market-cap controls, label it a quality/coverage feature, not a bullish signal.
- Wall and GEX remain diagnostic unless they show stable incremental improvement on longer independent history.

## Evidence threshold

Freeze these diagnostics and repeat after ~40 and ~120 independent sessions. Do not optimize production weights from the present 11-session sample.

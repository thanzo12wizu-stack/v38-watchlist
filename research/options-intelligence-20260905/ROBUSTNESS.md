# Options Intelligence robustness validation — 2026-09-05

Research only. No production file or upstream V38 / Dashboard / Rotation / Leadership artifact was changed.

## Data / methodological guardrail

- Event rows: 4,062
- Tickers: 1,734
- Independent option-snapshot sessions: 11
- Thresholds are compared for stability, not optimized to the best in-sample number.
- Cross-sectional spreads are calculated within each date; confidence intervals resample independent dates.
- Exact production-score reconstruction uses the production Gamma Flip rule: spot must be >2% above/below Flip for ±10.

## 1. Exact current score: asymmetric threshold sweep (5d ex-QQQ)

|Variant|Side|Threshold|N|Dates|Equal-date mean|95% date CI|Event hit|Date hit|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|score_exact_current|UP|60|1036|7|-0.03%|-1.64% to 1.77%|44.11%|42.86%|
|score_exact_current|UP|64|697|7|0.40%|-1.71% to 2.88%|47.78%|42.86%|
|score_exact_current|UP|68|650|7|0.53%|-1.53% to 2.87%|48.92%|42.86%|
|score_exact_current|UP|72|477|7|0.51%|-1.59% to 3.06%|50.10%|42.86%|
|score_exact_current|UP|76|244|6|-1.29%|-3.90% to 1.01%|48.36%|50.00%|
|score_exact_current|UP|80|155|6|-0.07%|-1.39% to 1.18%|43.23%|50.00%|
|score_exact_current|DOWN|40|443|7|-1.61%|-2.33% to -0.90%|63.66%|100.00%|
|score_exact_current|DOWN|36|277|7|-1.08%|-1.63% to -0.66%|62.82%|100.00%|
|score_exact_current|DOWN|32|266|6|-1.10%|-1.72% to -0.62%|62.03%|100.00%|
|score_exact_current|DOWN|28|156|6|-1.06%|-2.16% to -0.16%|63.46%|83.33%|
|score_exact_current|DOWN|24|79|4|-1.11%|-2.80% to 0.33%|68.35%|75.00%|
|score_exact_current|DOWN|20|39|3|-1.63%|-4.25% to -0.24%|66.67%|100.00%|
|score_no_wall|UP|60|1067|7|0.05%|-1.48% to 1.75%|44.05%|42.86%|
|score_no_wall|UP|64|859|7|0.64%|-1.38% to 2.96%|45.40%|42.86%|
|score_no_wall|UP|68|859|7|0.64%|-1.34% to 2.96%|45.40%|42.86%|
|score_no_wall|UP|72|734|7|0.61%|-1.60% to 3.25%|45.50%|57.14%|
|score_no_wall|UP|76|184|6|-2.82%|-5.59% to 0.04%|53.80%|33.33%|
|score_no_wall|DOWN|40|501|7|-1.82%|-2.68% to -0.93%|60.88%|85.71%|
|score_no_wall|DOWN|36|310|7|-1.08%|-1.77% to -0.46%|61.61%|85.71%|
|score_no_wall|DOWN|32|310|7|-1.08%|-1.76% to -0.46%|61.61%|85.71%|
|score_no_wall|DOWN|28|238|7|-1.15%|-1.85% to -0.51%|62.61%|85.71%|
|score_no_wall|DOWN|24|114|4|-0.55%|-2.72% to 2.33%|61.40%|75.00%|
|score_tech_only|UP|60|1014|7|-0.30%|-1.57% to 0.86%|43.69%|42.86%|
|score_tech_only|UP|64|234|6|-2.20%|-4.94% to 0.39%|51.28%|33.33%|
|score_tech_only|UP|68|234|6|-2.20%|-4.76% to 0.34%|51.28%|33.33%|
|score_tech_only|DOWN|40|644|7|-1.35%|-2.13% to -0.60%|63.66%|85.71%|
|score_tech_only|DOWN|36|220|4|-2.82%|-5.71% to -1.00%|63.64%|100.00%|
|score_tech_only|DOWN|32|220|4|-2.82%|-5.71% to -1.00%|63.64%|100.00%|

## 2. Score component ablation: within-date top-bottom spread

|Variant|Horizon|Dates|Top-bottom ex-QQQ|95% date CI|Positive dates|
|---|---:|---:|---:|---:|---:|
|score_exact_current|1d|9|-0.33%|-0.96% to 0.31%|33.33%|
|score_exact_current|3d|7|-0.08%|-1.32% to 1.19%|28.57%|
|score_exact_current|5d|6|0.98%|0.36% to 1.71%|100.00%|
|score_exact_current|10d|3|2.12%|0.02% to 3.92%|100.00%|
|score_no_wall|1d|9|-0.54%|-1.46% to 0.37%|33.33%|
|score_no_wall|3d|7|-0.06%|-1.60% to 1.39%|57.14%|
|score_no_wall|5d|6|1.32%|0.45% to 2.05%|83.33%|
|score_no_wall|10d|3|2.90%|1.45% to 3.88%|100.00%|
|score_tech_only|1d|8|-0.57%|-1.73% to 0.70%|37.50%|
|score_tech_only|3d|6|-1.23%|-3.87% to 1.38%|33.33%|
|score_tech_only|5d|5|0.37%|-1.75% to 2.38%|60.00%|
|score_tech_only|10d|3|1.50%|-4.38% to 5.99%|66.67%|

## 3. Gamma Flip robustness (5d ex-QQQ)

Within each stratum/date, rank by Flip distance in ATR; report top 20% minus bottom 20%.

|Stratum|Dates|Groups|Spread|95% date CI|Positive dates|
|---|---:|---:|---:|---:|---:|
|ALL|6|6|0.95%|0.28% to 1.55%|83.33%|
|QQQ above EMA21|3|3|1.62%|1.33% to 1.99%|100.00%|
|QQQ below EMA21|3|3|0.28%|-0.33% to 1.11%|66.67%|
|Sector momentum >=0|4|4|0.74%|0.13% to 1.21%|75.00%|
|Sector momentum <0|3|3|0.35%|-0.93% to 2.03%|33.33%|
|OI>=5k & strikes>=20|3|3|0.52%|-1.44% to 2.31%|66.67%|
|OI<5k or strikes<20|6|6|0.97%|0.34% to 1.62%|100.00%|
|SCAN source|6|6|0.95%|0.28% to 1.58%|83.33%|
|Within sector/date|3|26|0.93%|0.16% to 1.61%|100.00%|

## 4. Wall diagnostics

Distance-bin rows show 5-session path behavior. Directional-quintile rows use Mean 5d ex-QQQ as the top-minus-bottom spread; MFE/MAE columns then contain its bootstrap CI bounds.

|Kind|Side/feature|Bucket|N|Dates|Touch|Break|Hold if touched|5d ex-QQQ / spread|MFE or CI-lo|MAE or CI-hi|
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|distance_bin|call|0-0.5ATR|706|10|75.37%|52.21%|30.73%|0.03%|3.43%|-3.59%|
|distance_bin|call|0.5-1ATR|697|10|49.00%|29.93%|38.91%|-0.00%|3.45%|-3.43%|
|distance_bin|call|1-2ATR|1076|10|22.69%|11.69%|48.46%|-0.82%|3.14%|-3.33%|
|distance_bin|call|2ATR+|1205|10|2.37%|1.38%|41.67%|-1.51%|2.72%|-3.31%|
|distance_bin|put|0-0.5ATR|799|10|83.24%|62.04%|25.46%|-0.11%|3.44%|-3.74%|
|distance_bin|put|0.5-1ATR|734|10|55.63%|38.85%|30.17%|-0.28%|3.18%|-3.25%|
|distance_bin|put|1-2ATR|1010|10|29.67%|17.48%|41.10%|-0.65%|3.18%|-3.23%|
|distance_bin|put|2ATR+|1130|10|5.06%|3.44%|32.14%|-1.45%|2.61%|-3.33%|
|directional_quintile|call_dist_atr|call_dist_atr|1843|6|—|—|—|-0.14%|-1.20%|0.76%|
|directional_quintile|put_dist_atr|put_dist_atr|1836|6|—|—|—|1.56%|0.18%|2.95%|
|directional_quintile|wall_rr|wall_rr|1693|6|—|—|—|-0.93%|-1.65%|-0.22%|

## 5. Out-of-date feature-group ablation (5d ex-QQQ)

All models use the same complete-case observations. Baseline is technical + sector context. Each Options group is added separately, then all are added together.

|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|
|---|---|---:|---:|---:|---:|---:|
|baseline|ic|6|0.058|0.000|0.000 to 0.000|0.00%|
|baseline|spread|6|0.98%|0.00%|0.00% to 0.00%|0.00%|
|baseline|mse|6|0.002|0.000|0.000 to 0.000|0.00%|
|baseline+flip|ic|6|0.046|-0.012|-0.023 to -0.003|16.67%|
|baseline+flip|spread|6|0.52%|-0.46%|-1.15% to 0.03%|16.67%|
|baseline+flip|mse|6|0.002|0.000|-0.000 to 0.000|66.67%|
|baseline+wall|ic|6|0.014|-0.045|-0.137 to 0.016|50.00%|
|baseline+wall|spread|6|0.12%|-0.86%|-2.47% to 0.11%|50.00%|
|baseline+wall|mse|6|0.003|0.000|-0.000 to 0.000|50.00%|
|baseline+gex|ic|6|0.044|-0.014|-0.034 to 0.005|50.00%|
|baseline+gex|spread|6|1.09%|0.11%|-0.15% to 0.35%|83.33%|
|baseline+gex|mse|6|0.002|0.000|-0.000 to 0.000|16.67%|
|baseline+depth|ic|6|0.118|0.060|0.018 to 0.096|83.33%|
|baseline+depth|spread|6|2.08%|1.10%|0.63% to 1.73%|100.00%|
|baseline+depth|mse|6|0.002|-0.000|-0.000 to 0.000|83.33%|
|baseline+all_options|ic|6|0.083|0.025|-0.012 to 0.061|66.67%|
|baseline+all_options|spread|6|1.01%|0.03%|-1.16% to 0.93%|66.67%|
|baseline+all_options|mse|6|0.002|-0.000|-0.000 to 0.000|83.33%|

## Research interpretation

- The exact current score remains more stable on the DOWN side than the UP side across nearby thresholds. This supports asymmetric treatment as a research hypothesis, not an automatic threshold change.
- Gamma Flip cross-sectional spread is 0.95% over 6 dates in the all-sample test.
- Sector/date-neutral Gamma Flip spread is 0.93% over 3 dates. If its sign survives, Flip is less likely to be only a sector-selection artifact.
- Wall RR top-minus-bottom spread is -0.93%. Its sign should be interpreted diagnostically; reversing the production weight from this short sample would be overfit.
- Best feature-group addition by out-of-date spread in this sample: baseline+depth, delta 1.10% across 6 left-out dates. This identifies where the incremental signal came from; it is not an adoption rule.

## Evidence threshold

Do not tune production thresholds from 11 sessions. Continue daily all-liquid snapshots and repeat the same frozen tests at ~40 and ~120 independent sessions. A production change should require sign stability across time, sector-neutral confirmation, and out-of-date improvement.

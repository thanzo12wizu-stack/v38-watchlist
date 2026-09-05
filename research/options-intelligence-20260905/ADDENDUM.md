# Incremental Options value addendum

Question: after controlling for ordinary underlying trend / sector / market context, do Flip / Wall / GEX add useful cross-sectional information?

All results remain research-only; the option snapshot history contains only 11 independent sessions.

## Within-date quintile spreads

Top 20% minus bottom 20% future return, measured relative to QQQ. Ranking is recalculated independently inside each observation date, which removes most day-level market selection effects.

|Feature|Dates|Top-bottom 5d ex-QQQ|95% date-bootstrap CI|Positive dates|Note|
|---|---:|---:|---:|---:|---|
|tech_score|5|0.37%|-1.75% to 2.38%|60.00%|higher=bullish|
|options_score|6|-0.31%|-1.24% to 0.55%|50.00%|higher=bullish|
|combined_score_rebuilt|6|0.31%|-0.52% to 1.31%|33.33%|higher=bullish|
|flip_dist_atr|6|0.95%|0.28% to 1.58%|83.33%|higher=bullish|
|log_wall_rr|6|-0.93%|-1.65% to -0.22%|16.67%|higher=bullish|
|signed_log_gex_per_oi|6|0.55%|-0.20% to 1.46%|50.00%|higher test only; dealer side unknown|
|options_score|3|0.96%|-0.44% to 2.10%|66.67%|quality-gated|

## Leave-one-date-out prediction, 5-day ex-QQQ

Baseline = underlying 1d/20d momentum, distance from 20d high, sector 20d momentum, HV20, EMA21 and 63d VWAP state. Enhanced = baseline + Flip distance, Wall asymmetry, GEX-per-OI transform, OI depth and strike count. Historical C/P OI balance is excluded because older snapshots do not contain it consistently.

- base_ic: 0.0582 (-0.0296 to 0.1605) across 6 left-out dates
- enhanced_ic: 0.1148 (0.0480 to 0.1870) across 6 left-out dates
- delta_ic: 0.0566 (0.0184 to 0.0890) across 6 left-out dates
- base_spread: 0.0098 (-0.0039 to 0.0244) across 6 left-out dates
- enhanced_spread: 0.0182 (0.0044 to 0.0328) across 6 left-out dates
- delta_spread: 0.0084 (0.0054 to 0.0118) across 6 left-out dates
- base_mse: 0.002489 (0.002017 to 0.003040) across 6 left-out dates
- enhanced_mse: 0.002345 (0.001983 to 0.002811) across 6 left-out dates
- delta_mse: -0.000144 (-0.000281 to 0.000013) across 6 left-out dates

## Date-by-date multivariate coefficients (Fama-MacBeth style, 5-day ex-QQQ)

Each date is regressed cross-sectionally after z-scoring features. The table averages coefficients across dates; t-stat is across independent dates, not across tickers.

|Feature|Dates|Mean standardized coefficient|t across dates|Positive dates|
|---|---:|---:|---:|---:|
|above_ema21|4|-0.29%|-3.91|0.00%|
|sector_ret20|4|0.52%|2.69|100.00%|
|log_oi|4|0.56%|2.54|100.00%|
|flip_dist_atr|4|0.19%|1.76|100.00%|
|n_strikes|4|0.19%|1.73|100.00%|
|above_vwap63|4|0.43%|1.27|75.00%|
|hv20|4|-0.40%|-1.12|25.00%|
|ret1_today|4|0.31%|1.01|50.00%|
|log_wall_rr|4|-0.22%|-0.70|50.00%|
|dist20hi|4|-0.30%|-0.67|50.00%|
|ret20|4|-0.22%|-0.40|50.00%|
|signed_log_gex_per_oi|4|0.00%|0.01|50.00%|

## Interpretation guardrail

- In this short sample, adding Options features improves all three out-of-date metrics (rank IC, top-bottom spread, and MSE). That is evidence of incremental information, but not enough independent dates for production adoption.
- GEX sign remains a statistical proxy only. It cannot be interpreted as dealer bullish/bearish positioning because trade side is unobserved.
- Expected Move still cannot be validated historically: the new Expected Move fields exist mainly on the latest all-liquid snapshot, which has no completed forward expiry yet.

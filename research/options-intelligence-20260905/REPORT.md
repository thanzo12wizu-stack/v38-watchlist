# Options Intelligence structure backtest — 2026-09-05

## Scope / guardrails

Research only. No production V38 / Dashboard / Rotation / Options ranking code was changed.
Historical option-chain snapshots are not reconstructed: only snapshots already stored in `options_scan_history.csv` / `options_history.csv` are used. Historical OHLCV is fetched only to calculate contemporaneous technical context and subsequent underlying returns.

## Data audit

- Raw option event rows after same ticker/day collapse: 4,335
- Events matched to underlying daily OHLCV: 4,062
- Unique tickers: 1,734
- Option snapshot dates: 2026-08-18 to 2026-09-04 (11 sessions)
- Price-download failures after retries: 0
- Forward-return availability: 1d=2,360, 3d=2,233, 5d=2,141, 10d=1,276

> Limitation: the snapshot history is short. Cross-sectional N can be large, but independent time clusters are few. Therefore the results below are exploratory and are **not sufficient by themselves for production rule adoption**. Confidence intervals use moving-block resampling by observation date; multiple tests use Benjamini-Hochberg q-values.

## Current broad Direction score

|Bucket|Horizon|N|Dates|Mean ex-QQQ|95% block CI|Directional hit|
|---|---:|---:|---:|---:|---:|---:|
|UP >=68|1d|679|9|0.42%|-0.80% to 1.25%|48.31%|
|UP >=68|3d|656|7|0.69%|-2.47% to 2.10%|55.03%|
|UP >=68|5d|644|6|0.49%|-2.76% to 2.27%|48.91%|
|UP >=68|10d|452|3|0.28%|-0.79% to 1.03%|52.65%|
|DOWN <=32|1d|292|8|-0.33%|-0.47% to 0.15%|60.62%|
|DOWN <=32|3d|284|6|-0.67%|-0.99% to -0.14%|61.62%|
|DOWN <=32|5d|269|5|-1.41%|-2.49% to -0.78%|63.20%|
|DOWN <=32|10d|175|3|-4.05%|-4.21% to -3.89%|76.57%|
|MID 33-67|1d|1389|10|-0.05%|-0.38% to 0.28%|—|
|MID 33-67|3d|1293|8|-0.38%|-1.60% to 0.82%|—|
|MID 33-67|5d|1228|7|-0.80%|-2.35% to 0.66%|—|
|MID 33-67|10d|649|4|-0.70%|-1.19% to -0.65%|—|

## Strongest exploratory effects (5-day ex-QQQ)

|Condition|N|Dates|Mean ex-QQQ|95% block CI|Win|q(BH)|
|---|---:|---:|---:|---:|---:|---:|
|Broad Direction score <=32|269|5|-1.41%|-2.49% to -0.73%|36.80%|0.015|
|Sector 20d momentum <0|476|7|-1.78%|-2.85% to -0.62%|28.15%|0.015|
|QQQ < EMA21|876|4|-2.40%|-2.53% to -0.81%|20.21%|0.015|
|QQQ > EMA21|1265|3|0.84%|0.27% to 1.19%|55.97%|0.224|
|Negative gamma regime|253|7|-1.47%|-2.69% to 0.14%|33.99%|0.300|
|Bear combo Flip-/EMA/VWAP/RR|57|4|-1.77%|-3.77% to -0.41%|28.07%|0.370|
|Net GEX <0|662|7|-1.05%|-2.58% to -0.02%|38.97%|0.413|
|Price < 63d VWAP|759|7|-1.12%|-2.56% to -0.03%|35.84%|0.415|
|GEX- & Flip below|391|6|-0.97%|-2.57% to 0.22%|38.11%|0.749|
|Flip < -0.35ATR|395|6|-0.96%|-2.59% to 0.21%|37.97%|0.836|
|OI >=20k|536|6|0.95%|-2.22% to 2.33%|53.92%|0.915|
|Price < EMA21|939|7|-0.84%|-2.39% to 0.31%|39.30%|0.915|
|20d return <0|788|7|-0.99%|-2.76% to 0.35%|36.68%|0.954|
|Broad Direction score >=68|644|6|0.49%|-2.76% to 2.24%|48.91%|0.971|
|OI >=5k|1216|6|0.34%|-1.92% to 1.40%|49.34%|0.971|

## Wall behavior within next 5 sessions

|Side|Distance|N|Touch|Close-break|Hold given touch|Mean 5d ex-QQQ|
|---|---:|---:|---:|---:|---:|---:|
|Call|0-0.5ATR|706|75.37%|52.21%|30.73%|0.03%|
|Call|0.5-1ATR|697|49.00%|29.93%|38.91%|-0.00%|
|Call|1-2ATR|1076|22.69%|11.69%|48.46%|-0.82%|
|Call|2ATR+|1205|2.37%|1.38%|41.67%|-1.51%|
|Put|0-0.5ATR|799|83.24%|62.04%|25.46%|-0.11%|
|Put|0.5-1ATR|734|55.63%|38.85%|30.17%|-0.28%|
|Put|1-2ATR|1010|29.67%|17.48%|41.10%|-0.65%|
|Put|2ATR+|1130|5.06%|3.44%|32.14%|-1.45%|

## Expected Move calibration to expiry

|Implied/HV bucket|N|Inside expected range|Median realized / expected|
|---|---:|---:|---:|

## Research conclusions

- Sector 20d momentum <0, 3d: ex-QQQ -1.10% (N=523, dates=8, q=0.015). Candidate for a longer validation, not automatic adoption.
- Broad Direction score <=32, 5d: ex-QQQ -1.41% (N=269, dates=5, q=0.015). Candidate for a longer validation, not automatic adoption.
- Sector 20d momentum <0, 5d: ex-QQQ -1.78% (N=476, dates=7, q=0.015). Candidate for a longer validation, not automatic adoption.
- QQQ < EMA21, 5d: ex-QQQ -2.40% (N=876, dates=4, q=0.015). Candidate for a longer validation, not automatic adoption.
- Sector 20d momentum <0, 10d: ex-QQQ -3.59% (N=233, dates=4, q=0.015). Candidate for a longer validation, not automatic adoption.
- 20d return <0, 10d: ex-QQQ -1.42% (N=447, dates=4, q=0.050). Candidate for a longer validation, not automatic adoption.
- Price < EMA21, 10d: ex-QQQ -1.77% (N=550, dates=4, q=0.050). Candidate for a longer validation, not automatic adoption.
- Price < 63d VWAP, 10d: ex-QQQ -2.09% (N=434, dates=4, q=0.050). Candidate for a longer validation, not automatic adoption.
- Current broad UP score 5d mean ex-QQQ: 0.49% (N=644, dates=6).
- Current broad DOWN score 5d mean ex-QQQ: -1.41%; directional hit 63.20% (N=269, dates=5).
- Net GEX sign is evaluated as an empirical feature only. Because free OI does not identify dealer long/short side, even a statistical association would not justify interpreting positive Net GEX as inherently bullish.
- Historical earnings calendars are not reliably recoverable from the free provider in this run. A |daily return|>=5% event-proxy is tested instead; this must not be relabeled as an earnings test.

## Next evidence threshold

Accumulate daily all-liquid snapshots. Re-run after at least ~40 independent market sessions, and again after ~120 sessions. Production changes should require effect-sign stability across time splits plus date-clustered confidence intervals, not only a large cross-sectional ticker count.

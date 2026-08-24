# Methodology

## What is exact

The market-score component weights and color thresholds are frozen to V38 market policy v1.0.0:

- index trend: 30%
- short breadth: 15%
- medium breadth: 20%
- long breadth: 10%
- relative-strength breadth: 15%
- sector participation: 10%
- BLUE >= 0.72, GREEN >= 0.55, YELLOW >= 0.38, otherwise RED

The QQQ index-trend tests also follow the original policy: price versus 20/50/200-day averages plus rising 20-day and 50-day averages.

## What is a historical proxy

The original Command Center uses a stock cross-section that is not available point-in-time back to 2011 in this repository. Reusing the current universe in 2011 would create survivorship bias, so the backtest deliberately does not do that.

For 2011-2025 the cross-sectional breadth inputs are reconstructed from a fixed panel of long-lived broad, sector and industry ETFs. Each ETF only participates after its own required lookback exists. Sector rotation is likewise based only on data available on that historical date.

Therefore the first pass is a test of the V38 *market-regime and portfolio-allocation architecture*, not a claim that the exact current stock-ranking engine existed historically.

## Execution timing

All features are computed from close t or earlier. A signal from close t is first tradable at open t+1. Portfolio returns are measured from open t+1 to open t+2. This intentionally avoids same-close execution and look-ahead.

## Taxes and contributions

The default tax model assumes positive calendar-year strategy P&L is realized and taxed at 20.315%. Losses can offset later gains for up to three years in the model. JPY 1,000,000 is contributed after year-end tax in every calendar year, so 2011-2025 contains 15 contributions. This is conservative versus investing savings earlier during each year.

## VIX / FTD overlay

The VIX/FTD variant is reported separately from the core regime strategies. The current first-pass proxy arms after an extreme VIX event or sustained RED regime, detects a higher-volume QQQ follow-through day 4-12 sessions after a fresh 20-day low, and stages risk back in. These thresholds are not optimized on 2011-2025 and must not be treated as production settings without sensitivity testing.

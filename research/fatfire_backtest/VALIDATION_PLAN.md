# Validation plan

Before any production use or merge:

1. CI must pass unit tests and complete the 2011-2025 market-data run.
2. Inspect 2018 Q4, 2020 Feb-Apr and 2022 for regime timing and drawdown behavior.
3. Compare regime counts and transitions against known broad-market episodes; do not tune thresholds to improve returns.
4. Run sensitivity around portfolio sleeve weights separately from market-score thresholds.
5. Treat the VIX/FTD overlay as experimental until it improves drawdown/return trade-offs across multiple stress periods rather than a single crash.
6. Do not claim historical individual-stock alpha until a point-in-time universe including delisted/failed names is available.

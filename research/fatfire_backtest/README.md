# V38 FAT FIRE backtest

Research-only backtest harness for reconstructing V38-style market regimes and testing portfolio policies from 2011 onward without changing the production Command Center.

## Fixed life-plan inputs

- start capital: JPY 9,000,000
- annual contribution: JPY 1,000,000
- default evaluation: 2011-2025 (15 full calendar years)
- after-tax reporting

## Strategies reported

1. QQQ buy and hold benchmark
2. TQQQ buy and hold benchmark
3. V38 regime-gated QQQ
4. V38 regime-gated TQQQ + QQQ
5. V38 beta + sector-rotation proxy
6. Same allocation with experimental VIX/FTD staged re-entry

The market score preserves the historical V38 policy weights and BLUE/GREEN/YELLOW/RED thresholds. Because the repository does not contain a genuine point-in-time stock universe back to 2011, stock breadth and leader alpha are **not** backfilled with today's surviving stocks. The first pass uses a dynamically available ETF cross-section and reports that limitation explicitly.

See `METHODOLOGY.md` for execution timing, tax treatment and proxy definitions.

## Run

```bash
pip install -r research/fatfire_backtest/requirements.txt
pytest -q research/fatfire_backtest/test_backtest.py
python research/fatfire_backtest/backtest.py --out research/fatfire_backtest/output
```

Generated outputs are `summary.json`, `yearly.csv`, `equity.csv` and `regimes.csv`.

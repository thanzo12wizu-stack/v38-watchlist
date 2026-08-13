from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .journal import analyse_journal, write_report_data
from .renderer import render_dashboard
from .loader import _demo_input


DEMO_POSITIONS = [
    ("SNDK", 203.0, "Technology", "Memory", "2nd Pivot"),
    ("MU", 178.0, "Technology", "Memory", "21EMA Pullback"),
    ("NVDA", 188.0, "Technology", "AI Compute", "Breakout"),
    ("AVGO", 402.0, "Technology", "AI Networking", "21EMA Pullback"),
    ("CRDO", 146.0, "Technology", "AI Networking", "2nd Pivot"),
    ("VRT", 142.0, "Industrials", "Data Center Power", "Breakout"),
    ("APP", 512.0, "Communication Services", "AdTech", "Pocket Pivot"),
    ("PLTR", 168.0, "Technology", "AI Software", "21EMA Pullback"),
    ("HOOD", 119.0, "Financials", "Digital Brokerage", "Pocket Pivot"),
    ("FCX", 57.0, "Materials", "Copper", "21EMA Pullback"),
    ("STLD", 167.0, "Materials", "Steel", "Breakout"),
    ("WDC", 124.0, "Technology", "Storage", "2nd Pivot"),
    ("CEG", 362.0, "Utilities", "Nuclear Power", "Breakout"),
    ("ETN", 418.0, "Industrials", "Grid Equipment", "21EMA Pullback"),
    ("UBER", 108.0, "Industrials", "Mobility", "Pocket Pivot"),
]


def build_demo15(starting_equity_jpy: float, output_dir: Path) -> dict[str, object]:
    data = _demo_input(starting_equity_jpy)
    as_of = pd.Timestamp(data.equity["date"].max())
    invested_jpy = float(data.account_equity_jpy or starting_equity_jpy) * 0.72
    weights = np.array([8.0, 7.5, 7.0, 6.5, 6.0, 5.8, 5.5, 5.2, 4.8, 4.5, 4.2, 3.9, 3.7, 3.0, 2.4], dtype=float)
    weights = weights / weights.sum()
    rows: list[dict[str, object]] = []

    for index, ((ticker, price, sector, theme, setup), weight) in enumerate(zip(DEMO_POSITIONS, weights, strict=True)):
        market_value = invested_jpy * float(weight)
        quantity = max(1, round(market_value / (price * 150.0), 4))
        return_pct = 0.13 - index * 0.017
        entry_price = price / (1.0 + return_pct)
        stop_price = max(entry_price * 0.965, price * 0.94)
        rows.append({
            "ticker": ticker,
            "quantity": quantity,
            "entry_price": entry_price,
            "current_price": price,
            "fx_to_jpy": 150.0,
            "sector": sector,
            "industry": theme,
            "theme": theme,
            "stop_price": stop_price,
            "stop_method": "10MA" if index % 3 == 0 else "21EMA_LOW",
            "stop_ema21_low": stop_price * .995,
            "stop_sma10": stop_price,
            "adr_pct": 2.8 + (index % 6) * .45,
            "entry_stage": 1 if index in {5, 12} else 2,
            "entry_price_1": entry_price * .985,
            "entry_price_2": entry_price * 1.015,
            "shares_1": quantity / 2,
            "shares_2": 0 if index in {5, 12} else quantity / 2,
            "partial_taken": index in {0, 2},
            "capitulation_status": "WAITING" if index in {7, 13} else ("DONE" if index in {1, 9} else "NONE"),
            "entry_date": as_of - pd.offsets.BDay(5 + index * 2),
            "setup": setup,
            "nq_color": "GREEN",
            "event_risk": "EARNINGS+2" if index in {4, 10} else "",
        })

    data.holdings = pd.DataFrame(rows)
    rng = np.random.default_rng(3815)
    common = rng.normal(0.0006, 0.012, 90)
    data.price_returns = pd.DataFrame({
        ticker: common * (0.35 + (index % 4) * 0.10) + rng.normal(0.0004, 0.017, 90)
        for index, (ticker, *_rest) in enumerate(DEMO_POSITIONS)
    })
    data.source_notes = ["Almanac分離実装の15銘柄ストレステスト（実データではない）"]

    report = analyse_journal(data, starting_equity_jpy=starting_equity_jpy)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report_data(report, output_dir)
    render_dashboard(report, output_dir / "index.html")

    summary = report.to_summary_dict()
    summary["variant"] = "almanac-sidecar"
    summary["holdings"] = int(len(report.holdings))
    summary["output_dir"] = str(output_dir)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the standalone Almanac 15-position demo")
    parser.add_argument("--output", default="kaview/artifacts")
    parser.add_argument("--starting-equity-jpy", type=float, default=7_300_000)
    args = parser.parse_args()
    result = build_demo15(args.starting_equity_jpy, Path(args.output))
    print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

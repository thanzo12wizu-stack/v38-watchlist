from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .trade_journal import analyse_journal, write_report_data
from .trade_journal_almanac_final import render_dashboard
from .trade_journal_cards import render_daily_card, render_portfolio_card, write_social_copy
from .trade_journal_run import load_input, write_templates


def run(
    *,
    input_dir: Path,
    output_dir: Path,
    starting_equity_jpy: float,
    portfolio_path: Path | None = None,
    rules_path: Path | None = None,
    research_root: Path | None = None,
    prices_path: Path | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    """Build the Almanac as an independent sidecar artifact.

    The caller controls ``output_dir``. This module never writes to the existing
    Command Center or the existing Trade Journal output directory implicitly.
    """
    data = load_input(
        input_dir=input_dir,
        portfolio_path=portfolio_path,
        rules_path=rules_path,
        research_root=research_root,
        prices_path=prices_path,
        starting_equity_jpy=starting_equity_jpy,
        demo=demo,
    )
    report = analyse_journal(data, starting_equity_jpy=starting_equity_jpy)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report_data(report, output_dir)
    render_dashboard(report, output_dir / "index.html")
    render_daily_card(report, output_dir / "daily_card.png")
    render_portfolio_card(report, output_dir / "portfolio_card.png")
    write_social_copy(report, output_dir / "social_post_ja.txt")
    summary = report.to_summary_dict()
    summary["variant"] = "almanac-sidecar"
    summary["holdings"] = int(len(report.holdings))
    summary["output_dir"] = str(output_dir)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="V38 Trade Journal Almanac sidecar")
    parser.add_argument("--input", default="data/trade_journal")
    parser.add_argument("--output", default="artifacts/trade-journal-almanac")
    parser.add_argument("--starting-equity-jpy", type=float, default=7_300_000)
    parser.add_argument("--portfolio")
    parser.add_argument("--rules", default="config/trade_journal.example.json")
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--init-templates", action="store_true")
    args = parser.parse_args()

    if args.init_templates:
        write_templates(Path(args.input))
        print(json.dumps({"status": "PASS", "templates": str(Path(args.input))}, ensure_ascii=False))
        return

    result = run(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        starting_equity_jpy=args.starting_equity_jpy,
        portfolio_path=Path(args.portfolio) if args.portfolio else None,
        rules_path=Path(args.rules) if args.rules and Path(args.rules).exists() else None,
        research_root=Path(args.research_root) if args.research_root and Path(args.research_root).exists() else None,
        prices_path=Path(args.prices) if args.prices and Path(args.prices).exists() else None,
        demo=args.demo,
    )
    print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

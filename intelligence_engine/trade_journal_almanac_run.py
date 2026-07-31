from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .trade_journal import analyse_journal, write_report_data
from .trade_journal_almanac_final import render_dashboard
from .trade_journal_run import load_input, write_templates


def _live_readiness(data: Any) -> dict[str, Any]:
    account = data.account_equity_jpy
    account_value = float(account) if account is not None else 0.0
    if account_value <= 0 and not data.equity.empty and "equity_jpy" in data.equity:
        values = pd.to_numeric(data.equity["equity_jpy"], errors="coerce").dropna()
        account_value = float(values.iloc[-1]) if len(values) else 0.0
    missing: list[str] = []
    if account_value <= 0:
        missing.append("実口座総資産（V38_ACCOUNT_EQUITY_JPY または equity.csv）")
    connected = {
        "trades": int(len(data.trades)),
        "holdings": int(len(data.holdings)),
        "equity_rows": int(len(data.equity)),
        "candidates": int(len(data.candidates)),
    }
    equity_as_of = None
    equity_age_days = None
    if not data.equity.empty and "date" in data.equity:
        equity_dates = pd.to_datetime(data.equity["date"], errors="coerce").dropna()
        if len(equity_dates):
            latest = pd.Timestamp(equity_dates.max()).normalize()
            today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
            equity_as_of = latest.date().isoformat()
            equity_age_days = max(0, int((today - latest).days))
    stale_equity = equity_age_days is not None and equity_age_days > 7
    status = "SETUP_REQUIRED" if missing else (
        "READY"
        if connected["trades"] and connected["equity_rows"] and not stale_equity
        else "PARTIAL"
    )
    return {
        "status": status,
        "account_equity_jpy": account_value if account_value > 0 else None,
        "missing": missing,
        "connected_rows": connected,
        "equity_as_of": equity_as_of,
        "equity_age_days": equity_age_days,
        "stale_equity": stale_equity,
    }


def _render_setup_required(path: Path, readiness: dict[str, Any]) -> None:
    missing = "".join(f"<li>{html.escape(str(item))}</li>" for item in readiness["missing"])
    counts = readiness["connected_rows"]
    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>V38 Trade Journal Almanac — Setup</title>
<style>:root{{--bg:#f5f2ea;--panel:#fffdf8;--line:#dfd6bf;--text:#211d14;--muted:#726a58;--accent:#1f4fa8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}}
main{{max-width:680px;margin:auto;padding:28px 16px}}h1{{font-family:Georgia,"Noto Serif JP",serif;font-size:25px;margin:0}}.eyebrow{{font-size:10px;color:var(--accent);font-weight:800;letter-spacing:.12em}}
.card{{margin-top:18px;padding:17px;background:var(--panel);border:1px solid var(--line);border-radius:10px}}p,li{{font-size:13px;line-height:1.7}}.muted{{color:var(--muted)}}
.counts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}}.counts div{{padding:10px;border:1px solid var(--line);border-radius:8px}}.counts b{{display:block;font-size:20px}}</style>
</head><body><main><div class="eyebrow">V38 COMMAND CENTER</div><h1>Trade Journal Almanac</h1>
<div class="card"><h2>実データ接続待ち</h2><p>架空の資産・約定を表示しないため、次の入力が入るまで実績画面を生成しません。</p><ul>{missing}</ul>
<p class="muted">約定履歴・保有・入出金は任意です。まず総資産を接続すれば、Command Centerの保有診断と候補履歴を同期した部分運用を開始できます。</p></div>
<div class="counts"><div>取引履歴<b>{counts['trades']}</b></div><div>保有<b>{counts['holdings']}</b></div><div>資産履歴<b>{counts['equity_rows']}</b></div><div>候補履歴<b>{counts['candidates']}</b></div></div>
</main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


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
    require_live_data: bool = False,
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
    readiness = _live_readiness(data)
    if readiness["equity_as_of"]:
        freshness = f"Equity as of: {readiness['equity_as_of']}"
        if readiness["stale_equity"]:
            freshness += f"（{readiness['equity_age_days']}日経過・要更新）"
        data.source_notes.append(freshness)
    if require_live_data and readiness["status"] == "SETUP_REQUIRED":
        output_dir.mkdir(parents=True, exist_ok=True)
        _render_setup_required(output_dir / "index.html", readiness)
        summary = {
            "variant": "almanac-sidecar",
            "data_status": readiness["status"],
            "holdings": readiness["connected_rows"]["holdings"],
            "output_dir": str(output_dir),
            "readiness": readiness,
        }
        (output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        return summary
    report = analyse_journal(data, starting_equity_jpy=starting_equity_jpy)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_report_data(report, output_dir)
    render_dashboard(report, output_dir / "index.html")
    summary = report.to_summary_dict()
    summary["variant"] = "almanac-sidecar"
    summary["data_status"] = readiness["status"]
    summary["readiness"] = readiness
    summary["holdings"] = int(len(report.holdings))
    summary["output_dir"] = str(output_dir)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="V38 Trade Journal Almanac sidecar")
    parser.add_argument("--input", default="data/trade_journal")
    parser.add_argument("--output", default="artifacts/trade-journal-almanac")
    parser.add_argument("--starting-equity-jpy", type=float, default=0)
    parser.add_argument("--portfolio")
    parser.add_argument("--rules", default="config/trade_journal.example.json")
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--require-live-data", action="store_true")
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
        require_live_data=args.require_live_data,
    )
    print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()

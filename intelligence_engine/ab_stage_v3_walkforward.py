from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .ab_stage_data import ExperimentConfig
from .ab_stage_v2_data import prepare_dataset
from .ab_stage_v3_exposure import POLICY_VERSION, SPEC_NAMES, aggregate, run_walk_forward


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%" if math.isfinite(number) else "—"


def numfmt(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.{digits}f}" if math.isfinite(number) else "—"


def report(summary: pd.DataFrame, metadata: dict[str, Any]) -> str:
    lines = [
        "# A/B × Stage Walk-Forward 第3弾 — エクスポージャー検証",
        "",
        f"- Policy version: `{POLICY_VERSION}`",
        "- 比較対象は同一のA+B2ランキング・3R/1R出口。違いはロット制御のみ。",
        "- NORMALIZEDは学習期間の上位10%候補から平均ステージ倍率を算出し、テスト年へ固定適用。",
        "- テスト年の成績やステージ分布を見て倍率を調整しない。",
        "- DDは完全日次時価評価、QQQはポートフォリオ実稼働期間へ一致。",
        "",
        "## 集計",
        "",
        "|仕様|平均収益|PF|最悪DD|平均Gross|最大Gross平均|収益/Gross|DD/Gross|QQQ超過年|正の年|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"|{int(row['spec'])}. {row['spec_name']}|{pct(row['mean_portfolio_return'])}|"
            f"{numfmt(row['mean_profit_factor'])}|{pct(row['worst_max_drawdown'])}|"
            f"{pct(row['mean_average_gross_exposure'])}|{pct(row['mean_max_gross_exposure'])}|"
            f"{numfmt(row['mean_return_per_exposure'])}|{numfmt(row['mean_drawdown_per_exposure'])}|"
            f"{int(row['qqq_excess_years'])}/{int(row['folds'])}|{int(row['positive_years'])}/{int(row['folds'])}|"
        )
    lookup = {int(row["spec"]): row for _, row in summary.iterrows()}
    base, raw, normalized = lookup[14], lookup[18], lookup[20]
    lines.extend(["", "## 判定", ""])
    raw_exposure_ratio = float(raw["mean_average_gross_exposure"] / base["mean_average_gross_exposure"])
    norm_exposure_ratio = float(normalized["mean_average_gross_exposure"] / base["mean_average_gross_exposure"])
    lines.append(f"- 生ステージ配分の平均Grossは基準の **{raw_exposure_ratio:.1%}**。")
    lines.append(f"- 学習期正規化後の平均Grossは基準の **{norm_exposure_ratio:.1%}**。")
    raw_dd_improvement = float(raw["worst_max_drawdown"] - base["worst_max_drawdown"])
    norm_dd_improvement = float(normalized["worst_max_drawdown"] - base["worst_max_drawdown"])
    lines.append(f"- 生ステージ配分の最悪DD改善幅: **{raw_dd_improvement:+.2%}**。")
    lines.append(f"- 正規化ステージ配分の最悪DD改善幅: **{norm_dd_improvement:+.2%}**。")
    robust = (
        normalized["mean_profit_factor"] >= base["mean_profit_factor"] - 0.05
        and normalized["mean_portfolio_return"] >= base["mean_portfolio_return"] - 0.02
        and normalized["worst_max_drawdown"] >= base["worst_max_drawdown"] + 0.02
    )
    lines.append(
        "- **最終判定: " + ("ステージ配分のリスク選別効果あり" if robust else "DD改善の主因は低エクスポージャー") + "**。"
    )
    lines.extend(["", "## メタデータ", "", "```json", json.dumps(sanitize(metadata), ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def run(config: ExperimentConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    dataset, prices, metadata = prepare_dataset(config)
    by_year, fold_metadata = run_walk_forward(dataset, prices, config)
    if by_year.empty:
        raise RuntimeError("all V3 folds were empty")
    summary = aggregate(by_year)
    metadata.update(fold_metadata)
    metadata.update({
        "policy_version": POLICY_VERSION,
        "spec_names": SPEC_NAMES,
        "stage_scale_source": "training-period OOF top-decile mean stage multiplier",
        "stage_scale_cap": 3.0,
        "drawdown_method": "daily_mark_to_market",
    })
    by_year.to_csv(config.output_dir / "walk_forward_v3_by_year.csv", index=False)
    summary.to_csv(config.output_dir / "walk_forward_v3_summary.csv", index=False)
    payload = {"policy_version": POLICY_VERSION, "metadata": metadata, "summary": summary.to_dict(orient="records"), "fold_results": by_year.to_dict(orient="records")}
    write_json(config.output_dir / "results_v3.json", payload)
    (config.output_dir / "REPORT_V3_JA.md").write_text(report(summary, metadata), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--output", default="artifacts/ab-stage-v3-walkforward")
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--cooldown", type=int, default=5)
    args = parser.parse_args()
    result = run(ExperimentConfig(
        research_root=Path(args.research_root), prices_path=Path(args.prices),
        output_dir=Path(args.output), start_year=max(2017, args.start_year),
        cooldown_sessions=max(1, args.cooldown),
    ))
    print(json.dumps({"status": "PASS", "summary_rows": len(result["summary"]), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()

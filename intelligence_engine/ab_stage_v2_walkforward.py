from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .ab_stage_data import ExperimentConfig, prepare_dataset
from .ab_stage_v2_models import POLICY_VERSION, SPEC_NAMES, aggregate, run_walk_forward
from .ab_stage_v2_policy import incremental_verdicts


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


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
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize(payload), ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + "\n",
        encoding="utf-8",
    )


def pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%" if math.isfinite(number) else "—"


def number(value: Any, digits: int = 3) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{value:.{digits}f}" if math.isfinite(value) else "—"


def build_report(summary: pd.DataFrame, verdicts: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    lines = [
        "# A/B × Stage Walk-Forward 第2弾", "",
        f"- Policy version: `{POLICY_VERSION}`",
        "- B2: +3R先着・-1R先着・時間切れの競合リスク＋5日Early Failureを分離",
        "- A+B2固定比率: 日次順位で A 70% / B2 30%（事前固定、最適化なし）",
        "- 約定: シグナル翌営業日始値",
        "- 同日上下到達: ストップ先着",
        "- ポートフォリオ: 最大12、1取引0.6%リスク、建玉8%上限、往復コスト0.20%",
        "- DD: 日次時価評価。エントリー当日から退出日まで日々の終値で評価",
        "- スロット: 当日退出予定ポジションを寄付き前に空き扱いしない",
        "- QQQ比較: 各仕様の最初のエントリー日から最後の退出日まで完全一致",
        "", "## 集計", "",
        "|仕様|出口|IC|上位10%超過|+3R|Early Fail|時間切れ|Brier Skill|PF|最悪MTM DD|QQQ超過年|取引数|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"|{int(row['spec'])}. {row['spec_name']}|{row['portfolio_mode']}|{number(row['mean_daily_spearman_ic'], 4)}|"
            f"{pct(row['mean_top10_excess_return'])}|{pct(row['mean_hit_3r_rate'])}|{pct(row['mean_early_failure_rate'])}|"
            f"{pct(row['mean_neither_rate'])}|{pct(row['mean_brier_skill'])}|{number(row['mean_profit_factor'], 2)}|"
            f"{pct(row['worst_max_drawdown'])}|{int(row['qqq_excess_years'])}/{int(row['folds'])}|{int(row['total_trades'])}|"
        )
    lines.extend(["", "## 増分採否", ""])
    for verdict in verdicts:
        improvements = "、".join(verdict["material_improvements"]) or "明確な改善なし"
        violations = "、".join(verdict["guardrail_violations"]) or "なし"
        lines.append(
            f"- **{verdict['increment']}**: {verdict['verdict']} — 改善: {improvements}。"
            f"非劣化違反: {violations}。取引数変化 {verdict['trade_count_change']:+d}。"
        )
    lines.extend([
        "", "## 解釈上の固定ルール", "",
        "- 固定10日出口と3R/1R出口は同じランキングでも別仕様として扱う。",
        "- ステージは加点せず、モデル交互作用またはロット倍率にだけ使用する。",
        "- DD改善だけでなく、PF・収益・上位群の期待値の非劣化を要求する。",
        "- 取引数減少だけでは採用しない。",
        "", "## メタデータ", "", "```json",
        json.dumps(sanitize(metadata), ensure_ascii=False, indent=2, default=json_default), "```", "",
    ])
    return "\n".join(lines)


def run(config: ExperimentConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    dataset, prices, metadata = prepare_dataset(config)
    fold_results, fold_metadata = run_walk_forward(dataset, prices, config)
    if fold_results.empty:
        raise RuntimeError("all v2 walk-forward folds were empty")
    summary = aggregate(fold_results)
    verdicts = incremental_verdicts(summary)
    metadata.update(fold_metadata)
    metadata.update({
        "policy_version": POLICY_VERSION,
        "spec_names": SPEC_NAMES,
        "b2_score_contract": "3*p_upper - p_lower + median_none_payoff_R*p_none - 0.5*p_early",
        "ab2_blend": {"A_daily_rank": 0.70, "B2_daily_rank": 0.30},
        "drawdown_method": "daily_mark_to_market",
        "qqq_alignment": "first_entry_open_to_last_exit_close_per_spec",
    })
    fold_results.to_csv(config.output_dir / "walk_forward_v2_by_year.csv", index=False)
    summary.to_csv(config.output_dir / "walk_forward_v2_summary.csv", index=False)
    payload = {
        "policy_version": POLICY_VERSION, "metadata": metadata,
        "summary": summary.to_dict(orient="records"),
        "incremental_verdicts": verdicts,
        "fold_results": fold_results.to_dict(orient="records"),
    }
    write_json(config.output_dir / "results_v2.json", payload)
    (config.output_dir / "REPORT_V2_JA.md").write_text(build_report(summary, verdicts, metadata), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--output", default="artifacts/ab-stage-v2-walkforward")
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

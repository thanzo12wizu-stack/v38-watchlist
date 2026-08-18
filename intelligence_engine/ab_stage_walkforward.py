from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import ab_stage_data
from .ab_stage_data import ExperimentConfig, POLICY_VERSION
from .ab_stage_models import SPEC_NAMES, aggregate, incremental_verdicts, run_walk_forward


def sanitize(value: Any) -> Any:
    """Recursively convert pandas/numpy values to strict finite JSON values."""
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and missing:
        return None
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def normalize_dimension_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Prevent real-universe blank/NaN dimension keys from becoming mixed merge dtypes."""
    out = frame.copy()
    for column in ("sector", "industry"):
        if column not in out:
            out[column] = "Unclassified"
            continue
        values = out[column].astype("string").str.strip()
        out[column] = values.mask(values.eq(""), pd.NA).fillna("Unclassified")
    return out


def prepare_dataset(config: ExperimentConfig):
    original = ab_stage_data.attach_group_features

    def normalized_attach(frame: pd.DataFrame, market_stage: pd.DataFrame) -> pd.DataFrame:
        return original(normalize_dimension_columns(frame), market_stage)

    ab_stage_data.attach_group_features = normalized_attach
    try:
        return ab_stage_data.prepare_dataset(config)
    finally:
        ab_stage_data.attach_group_features = original


def pct(value: Any) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{value * 100:.2f}%" if math.isfinite(value) else "—"


def finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def report(summary: pd.DataFrame, verdicts: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    lines = [
        "# A/B × Stage Walk-Forward 検証結果", "",
        f"- Policy version: `{POLICY_VERSION}`",
        "- 約定: シグナル翌営業日始値",
        "- 上下同日到達: ストップ先着扱い（保守的）",
        "- 売買: 上位10%、最大12ポジション、1トレード0.6%リスク、建玉上限8%、往復コスト0.20%",
        "- 学習/検証: 3年学習→翌年検証、最大20営業日ラベルが検証年へ跨ぐ学習行は除外",
        "", "## 集計", "",
        "|仕様|IC|上位10%超過|+3R先着|Early Fail|Brier|PF|最悪DD|QQQ超過年|取引数|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"|{int(row['spec'])}. {row['spec_name']}|{finite_or_zero(row['mean_daily_spearman_ic']):.4f}|"
            f"{pct(row['mean_top10_excess_return'])}|{pct(row['mean_hit_3r_rate'])}|"
            f"{pct(row['mean_early_failure_rate'])}|{finite_or_zero(row['mean_brier_score']):.4f}|"
            f"{finite_or_zero(row['mean_profit_factor']):.2f}|{pct(row['worst_max_drawdown'])}|"
            f"{int(row['qqq_excess_years'])}/{int(row['folds'])}|{int(row['total_trades'])}|"
        )
    lines.extend(["", "## 増分採否", ""])
    for verdict in verdicts:
        reasons = "、".join(verdict["material_improvements"]) or "明確な改善なし"
        lines.append(f"- **{verdict['increment']}**: {verdict['verdict']} — {reasons}。取引数変化 {verdict['trade_count_change']:+d}。")
    lines.extend([
        "", "## 注意事項", "",
        "- 最大DDは完全な日次時価評価ではなく、各トレードの実現損益を退出日に反映した比較用DD。",
        "- 現在の研究母集団は既存リサーチ・シグナルプール。全上場銘柄の無条件日次母集団ではない。",
        "- 最高リターンだけでは採用せず、増分改善・年別安定性・QQQ超過年数を併用する。",
        "", "## 実行メタデータ", "", "```json",
        json.dumps(sanitize(metadata), ensure_ascii=False, indent=2, allow_nan=False), "```", "",
    ])
    return "\n".join(lines)


def run(config: ExperimentConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    dataset, prices, metadata = prepare_dataset(config)
    fold_results, fold_metadata = run_walk_forward(dataset, prices, config)
    if fold_results.empty:
        raise RuntimeError("all walk-forward folds were empty")
    summary = aggregate(fold_results)
    verdicts = incremental_verdicts(summary)
    metadata.update(fold_metadata)
    metadata.update({"policy_version": POLICY_VERSION, "spec_names": SPEC_NAMES})
    fold_results.to_csv(config.output_dir / "walk_forward_by_year.csv", index=False)
    summary.to_csv(config.output_dir / "walk_forward_summary.csv", index=False)
    audit_columns = [column for column in (
        "ticker", "date", "sector", "industry", "individual_stage", "market_stage",
        "excess_10", "hit_3r_before_1r_15", "early_failure_5", "mfe_15", "mae_15",
        "trade_return_gross", "risk_fraction", "label_end_date",
    ) if column in dataset]
    dataset[audit_columns].to_csv(config.output_dir / "label_audit_sample.csv", index=False)
    payload = {
        "policy_version": POLICY_VERSION, "metadata": metadata,
        "summary": summary.to_dict(orient="records"), "incremental_verdicts": verdicts,
        "fold_results": fold_results.to_dict(orient="records"),
    }
    write_json(config.output_dir / "results.json", payload)
    (config.output_dir / "REPORT_JA.md").write_text(report(summary, verdicts, metadata), encoding="utf-8")
    return sanitize(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--output", default="artifacts/ab-stage-walkforward")
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

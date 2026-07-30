from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .ab_stage_data import num


def incremental_verdicts(summary: pd.DataFrame) -> list[dict[str, Any]]:
    lookup = {int(row["spec"]): row for _, row in summary.iterrows()}
    pairs = (
        (12, 11, "Aの固定10日出口"),
        (14, 11, "AへのB2追加"),
        (15, 14, "A+B2の固定10日出口"),
        (16, 12, "Aへのステージ交互作用"),
        (17, 14, "A+B2へのステージ交互作用"),
        (18, 14, "A+B2のステージ別ロット"),
        (19, 17, "交互作用モデルのステージ別ロット"),
    )
    improvements = (
        ("mean_top10_excess_return", 0.001, 1, "上位10%超過収益"),
        ("mean_hit_3r_rate", 0.01, 1, "+3R先着率"),
        ("mean_early_failure_rate", 0.01, -1, "Early Failure率"),
        ("mean_brier_skill", 0.01, 1, "Brier Skill"),
        ("mean_profit_factor", 0.10, 1, "PF"),
        ("worst_max_drawdown", 0.02, 1, "完全MTM最大DD"),
        ("mean_portfolio_return", 0.03, 1, "平均運用収益"),
    )
    guardrails = (
        ("mean_top10_excess_return", -0.001, 1),
        ("mean_hit_3r_rate", -0.01, 1),
        ("mean_early_failure_rate", -0.01, -1),
        ("mean_profit_factor", -0.05, 1),
        ("worst_max_drawdown", -0.01, 1),
        ("mean_portfolio_return", -0.02, 1),
    )
    output = []
    for new_spec, old_spec, label in pairs:
        if new_spec not in lookup or old_spec not in lookup:
            continue
        new, old = lookup[new_spec], lookup[old_spec]
        reasons = []
        for column, threshold, direction, name in improvements:
            new_value, old_value = num(new.get(column)), num(old.get(column))
            if (
                np.isfinite(new_value)
                and np.isfinite(old_value)
                and (new_value - old_value) * direction >= threshold
            ):
                reasons.append(name)
        violations = []
        for column, tolerance, direction in guardrails:
            new_value, old_value = num(new.get(column)), num(old.get(column))
            if not np.isfinite(new_value) or not np.isfinite(old_value):
                continue
            if (new_value - old_value) * direction < tolerance:
                violations.append(column)
        output.append(
            {
                "increment": label,
                "from_spec": old_spec,
                "to_spec": new_spec,
                "verdict": "ADOPT" if reasons and not violations else "REJECT",
                "material_improvements": reasons,
                "guardrail_violations": violations,
                "trade_count_change": int(new.get("total_trades") or 0)
                - int(old.get("total_trades") or 0),
                "note": "取引数減少だけでは採用しない。改善と非劣化を同時要求。",
            }
        )
    return output

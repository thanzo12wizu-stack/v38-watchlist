from __future__ import annotations

import pandas as pd

from .utils import percentile_rank, weighted_available

ENTRY_POLICY_VERSION = "1.1.1"


def add_entry_intelligence(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in ("trend_alignment", "contraction_score_raw", "pivot_quality_raw", "participation_score_raw", "reward_risk_raw"):
        if col in out:
            out[f"pct_{col}"] = percentile_rank(out[col])
    for col in ("extension_atr", "stop_risk_pct", "supply_risk_raw"):
        if col in out:
            out[f"pct_{col}_quality"] = percentile_rank(-pd.to_numeric(out[col], errors="coerce"))

    def score_row(row: pd.Series) -> pd.Series:
        technical, _ = weighted_available(
            {"trend": row.get("pct_trend_alignment"), "contraction": row.get("pct_contraction_score_raw"), "pivot": row.get("pct_pivot_quality_raw"), "participation": row.get("pct_participation_score_raw")},
            {"trend": .30, "contraction": .25, "pivot": .30, "participation": .15},
        )
        risk, _ = weighted_available(
            {"stop": row.get("pct_stop_risk_pct_quality"), "rr": row.get("pct_reward_risk_raw"), "extension": row.get("pct_extension_atr_quality"), "supply": row.get("pct_supply_risk_raw_quality")},
            {"stop": .30, "rr": .30, "extension": .25, "supply": .15},
        )
        entry, confidence = weighted_available(
            {"technical": technical, "risk": risk, "leader": row.get("score_leader"), "candidate": row.get("score_candidate")},
            {"technical": .45, "risk": .25, "leader": .20, "candidate": .10},
        )
        return pd.Series({"score_entry": entry, "score_entry_technical": technical, "score_entry_risk": risk, "score_entry_confidence": confidence})

    if out.empty:
        for column in ("score_entry", "score_entry_technical", "score_entry_risk", "score_entry_confidence", "entry_rank_pct"):
            out[column] = pd.Series(dtype="float64")
        out["setup"] = pd.Series(dtype="object")
        return out
    out = pd.concat([out, out.apply(score_row, axis=1)], axis=1)
    out["entry_rank_pct"] = percentile_rank(out["score_entry"])
    out["setup"] = out.apply(classify_setup, axis=1)
    return out


def classify_setup(row: pd.Series) -> str:
    if bool(row.get("hard_block", False)):
        return "AVOID"
    extension = pd.to_numeric(row.get("extension_atr"), errors="coerce")
    distance_pivot = pd.to_numeric(row.get("distance_pivot_pct"), errors="coerce")
    contraction = pd.to_numeric(row.get("contraction_score_raw"), errors="coerce")
    volume = pd.to_numeric(row.get("volume_ratio_20d"), errors="coerce")
    if pd.notna(extension) and extension >= 3.0:
        return "EXTENDED"
    if bool(row.get("above_pivot", False)) and pd.notna(volume) and volume >= 1.25:
        return "BREAKOUT"
    if pd.notna(distance_pivot) and -3.0 <= distance_pivot <= 0.5 and (pd.isna(contraction) or contraction >= 0.5):
        return "PRE_BREAKOUT"
    if bool(row.get("near_ema21_low", False)):
        return "PULLBACK"
    if pd.notna(volume) and volume >= 1.5:
        return "VOLUME_SURGE"
    distance_high = pd.to_numeric(row.get("distance_52w_high_pct"), errors="coerce")
    if pd.notna(distance_high) and distance_high <= -20:
        return "DEEP_PULLBACK"
    return "WATCH"


def build_entry_candidates(frame: pd.DataFrame, limit: int = 20) -> list[dict]:
    if frame.empty or limit <= 0:
        return []
    ordered = frame.sort_values(
        ["score_entry", "score_leader", "ticker"],
        ascending=[False, False, True],
        na_position="last",
    )
    avoid_mask = ordered["setup"].isin(["AVOID", "EXTENDED"])
    trade_limit = max(1, int(round(limit * .75)))
    avoid_limit = max(0, limit - trade_limit)
    selected = pd.concat(
        [ordered.loc[~avoid_mask].head(trade_limit), ordered.loc[avoid_mask].head(avoid_limit)],
        axis=0,
    )
    if len(selected) < limit:
        remaining = ordered.loc[~ordered.index.isin(selected.index)].head(limit - len(selected))
        selected = pd.concat([selected, remaining], axis=0)

    records = []
    for _, row in selected.iterrows():
        warnings = []
        if pd.notna(row.get("supply_risk_raw")) and row.get("supply_risk_raw") >= .5:
            warnings.append("supply")
        warnings.append("earnings_unknown")
        records.append(
            {
                "ticker": str(row["ticker"]),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "setup": row["setup"],
                "score_entry": row.get("score_entry"),
                "score_candidate": row.get("score_candidate"),
                "score_leader": row.get("score_leader"),
                "leader_confidence": row.get("score_leader_confidence"),
                "entry_confidence": row.get("score_entry_confidence"),
                "price": row.get("price"),
                "adr_pct": row.get("adr_pct"),
                "pivot": row.get("pivot_20d"),
                "distance_pivot_pct": row.get("distance_pivot_pct"),
                "distance_52w_high_pct": row.get("distance_52w_high_pct"),
                "stop_ema21_low": row.get("stop_ema21_low"),
                "stop_sma10": row.get("stop_sma10"),
                "stop_risk_pct": row.get("stop_risk_pct"),
                "reward_risk_raw": row.get("reward_risk_raw"),
                "extension_atr": row.get("extension_atr"),
                "hard_block": bool(row.get("hard_block", False)),
                "volume_ratio_20d": row.get("volume_ratio_20d"),
                "contraction_score_raw": row.get("contraction_score_raw"),
                "warnings": warnings,
            }
        )
    return records

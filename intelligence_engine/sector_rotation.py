from __future__ import annotations

import pandas as pd

from .utils import percentile_rank, weighted_available

SECTOR_ROTATION_POLICY_VERSION = "1.1.0"


def _numeric(group: pd.DataFrame, column: str) -> pd.Series:
    if column not in group.columns:
        return pd.Series(dtype="float64")
    value = group.loc[:, column]
    if isinstance(value, pd.DataFrame):
        value = value.apply(pd.to_numeric, errors="coerce").bfill(axis=1).iloc[:, 0]
    return pd.to_numeric(value, errors="coerce")


def _phase(strength: float | None, acceleration: float | None, breadth: float | None) -> str:
    s = 0.0 if strength is None else strength
    a = 0.0 if acceleration is None else acceleration
    b = 0.0 if breadth is None else breadth
    if s >= 75 and a >= 60 and b >= .60:
        return "LEADING"
    if a >= 70 and b >= .48:
        return "ACCELERATING"
    if a >= 58 and s < 65:
        return "EMERGING"
    if s >= 65 and a < 45:
        return "MATURE"
    if s < 35 and a < 40 and b < .35:
        return "BROKEN"
    if a < 40 and b < .45:
        return "WEAKENING"
    return "IMPROVING"


def build_sector_rotation(frame: pd.DataFrame, top_leaders: int = 5) -> list[dict]:
    """Aggregate stock evidence into established strength, acceleration and breadth."""
    if frame.empty or "sector" not in frame:
        return []
    work = frame.copy()
    work = work[work["sector"].notna() & work["sector"].astype(str).str.strip().ne("")]
    if work.empty:
        return []

    rows: list[dict] = []
    for sector, group in work.groupby("sector", sort=True):
        rs63 = _numeric(group, "rs_raw_63")
        rs126 = _numeric(group, "rs_raw_126")
        rs189 = _numeric(group, "rs_raw_189")
        change63 = _numeric(group, "rs_change_raw_63")
        change126 = _numeric(group, "rs_change_raw_126")
        leaders_rank = _numeric(group, "leader_rank_pct")
        strength_inputs = {
            "rs63": None if rs63.dropna().empty else float(rs63.median()),
            "rs126": None if rs126.dropna().empty else float(rs126.median()),
            "rs189": None if rs189.dropna().empty else float(rs189.median()),
        }
        acceleration_inputs = {
            "rs63": None if change63.dropna().empty else float(change63.median()),
            "rs126": None if change126.dropna().empty else float(change126.median()),
        }
        valid_breadth = rs63.dropna()
        breadth = float((valid_breadth > 0).mean()) if not valid_breadth.empty else None
        valid_leaders = leaders_rank.dropna()
        leader_share = float((valid_leaders >= 80.0).mean()) if not valid_leaders.empty else None
        leaders = group.sort_values(["score_leader", "ticker"], ascending=[False, True]).head(top_leaders) if "score_leader" in group else group.head(0)
        rows.append(
            {
                "sector": str(sector),
                "stock_count": int(len(group)),
                "strength_raw": strength_inputs,
                "acceleration_raw": acceleration_inputs,
                "breadth_positive_63d": breadth,
                "leader_share_top20pct": leader_share,
                "leaders": [str(t) for t in leaders.get("ticker", pd.Series(dtype=str)).tolist()],
            }
        )

    result = pd.DataFrame(rows)
    for key in ("rs63", "rs126", "rs189"):
        result[f"pct_strength_{key}"] = percentile_rank(result["strength_raw"].map(lambda x: x.get(key)))
    for key in ("rs63", "rs126"):
        result[f"pct_acceleration_{key}"] = percentile_rank(result["acceleration_raw"].map(lambda x: x.get(key)))
    result["pct_breadth"] = percentile_rank(result["breadth_positive_63d"])
    result["pct_leader_share"] = percentile_rank(result["leader_share_top20pct"])

    scores = []
    for _, row in result.iterrows():
        strength, _ = weighted_available(
            {"r63": row.get("pct_strength_rs63"), "r126": row.get("pct_strength_rs126"), "r189": row.get("pct_strength_rs189")},
            {"r63": 0.25, "r126": 0.35, "r189": 0.40},
        )
        acceleration, _ = weighted_available(
            {"r63": row.get("pct_acceleration_rs63"), "r126": row.get("pct_acceleration_rs126")},
            {"r63": 0.60, "r126": 0.40},
        )
        rotation, confidence = weighted_available(
            {"strength": strength, "acceleration": acceleration, "breadth": row.get("pct_breadth"), "leaders": row.get("pct_leader_share")},
            {"strength": 0.40, "acceleration": 0.30, "breadth": 0.20, "leaders": 0.10},
        )
        scores.append((strength, acceleration, rotation, confidence))
    result[["score_strength", "score_acceleration", "score_rotation", "score_confidence"]] = pd.DataFrame(scores, index=result.index)
    result = result.sort_values(["score_rotation", "score_strength", "sector"], ascending=[False, False, True])

    output: list[dict] = []
    for _, row in result.iterrows():
        strength = None if pd.isna(row["score_strength"]) else float(row["score_strength"])
        acceleration = None if pd.isna(row["score_acceleration"]) else float(row["score_acceleration"])
        breadth = None if pd.isna(row["breadth_positive_63d"]) else float(row["breadth_positive_63d"])
        output.append(
            {
                "sector": row["sector"],
                "stock_count": int(row["stock_count"]),
                "score_rotation": None if pd.isna(row["score_rotation"]) else float(row["score_rotation"]),
                "score_strength": strength,
                "score_acceleration": acceleration,
                "score_confidence": None if pd.isna(row["score_confidence"]) else float(row["score_confidence"]),
                "phase": _phase(strength, acceleration, breadth),
                "breadth_positive_63d": breadth,
                "leader_share_top20pct": None if pd.isna(row["leader_share_top20pct"]) else float(row["leader_share_top20pct"]),
                "leaders": row["leaders"],
            }
        )
    return output

from __future__ import annotations

import pandas as pd

from .utils import percentile_rank, weighted_available


SECTOR_ROTATION_POLICY_VERSION = "1.0.0"


def build_sector_rotation(frame: pd.DataFrame, top_leaders: int = 5) -> list[dict]:
    """Aggregate stock evidence into a sector rotation table.

    The score separates established strength from acceleration so consumers can
    distinguish strong sectors from sectors whose internal leadership is improving.
    """
    if frame.empty or "sector" not in frame:
        return []
    work = frame.copy()
    work = work[work["sector"].notna() & work["sector"].astype(str).str.strip().ne("")]
    if work.empty:
        return []

    rows: list[dict] = []
    for sector, group in work.groupby("sector", sort=True):
        strength_inputs = {
            "rs63": pd.to_numeric(group.get("rs_raw_63"), errors="coerce").median(),
            "rs126": pd.to_numeric(group.get("rs_raw_126"), errors="coerce").median(),
            "rs189": pd.to_numeric(group.get("rs_raw_189"), errors="coerce").median(),
        }
        acceleration_inputs = {
            "rs63": pd.to_numeric(group.get("rs_change_raw_63"), errors="coerce").median(),
            "rs126": pd.to_numeric(group.get("rs_change_raw_126"), errors="coerce").median(),
        }
        breadth = float((pd.to_numeric(group.get("rs_raw_63"), errors="coerce") > 0).mean()) if "rs_raw_63" in group else None
        leader_share = float((pd.to_numeric(group.get("leader_rank_pct"), errors="coerce") >= 0.80).mean()) if "leader_rank_pct" in group else None
        leaders = group.sort_values(["score_leader", "ticker"], ascending=[False, True]).head(top_leaders) if "score_leader" in group else group.head(0)
        rows.append({
            "sector": str(sector),
            "stock_count": int(len(group)),
            "strength_raw": strength_inputs,
            "acceleration_raw": acceleration_inputs,
            "breadth_positive_63d": breadth,
            "leader_share_top20pct": leader_share,
            "leaders": [str(t) for t in leaders.get("ticker", pd.Series(dtype=str)).tolist()],
        })

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
        output.append({
            "sector": row["sector"],
            "stock_count": int(row["stock_count"]),
            "score_rotation": None if pd.isna(row["score_rotation"]) else float(row["score_rotation"]),
            "score_strength": None if pd.isna(row["score_strength"]) else float(row["score_strength"]),
            "score_acceleration": None if pd.isna(row["score_acceleration"]) else float(row["score_acceleration"]),
            "score_confidence": None if pd.isna(row["score_confidence"]) else float(row["score_confidence"]),
            "breadth_positive_63d": row["breadth_positive_63d"],
            "leader_share_top20pct": row["leader_share_top20pct"],
            "leaders": row["leaders"],
        })
    return output

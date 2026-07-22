from __future__ import annotations

import numpy as np
import pandas as pd

from .utils import percentile_rank, weighted_available


LEADER_POLICY_VERSION = "1.0.1"


def add_leader_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Add a leader score that rewards persistent relative strength, improving RS,
    proximity to highs, liquidity and peer leadership.
    """
    out = frame.copy()
    for col in ("rs_raw_63", "rs_raw_126", "rs_raw_189", "rs_change_raw_63", "rs_change_raw_126", "distance_52w_high_pct", "dollar_volume_20d"):
        if col in out and f"pct_{col}" not in out:
            out[f"pct_{col}"] = percentile_rank(out[col])

    def row_score(row: pd.Series) -> pd.Series:
        persistence, _ = weighted_available(
            {"r63": row.get("pct_rs_raw_63"), "r126": row.get("pct_rs_raw_126"), "r189": row.get("pct_rs_raw_189")},
            {"r63": 0.25, "r126": 0.35, "r189": 0.40},
        )
        acceleration, _ = weighted_available(
            {"r63": row.get("pct_rs_change_raw_63"), "r126": row.get("pct_rs_change_raw_126")},
            {"r63": 0.60, "r126": 0.40},
        )
        tradability, _ = weighted_available(
            {"liquidity": row.get("pct_dollar_volume_20d"), "near_high": row.get("pct_distance_52w_high_pct")},
            {"liquidity": 0.45, "near_high": 0.55},
        )
        peer, _ = weighted_available(
            {"sector": row.get("sector_rank_pct"), "industry": row.get("industry_rank_pct")},
            {"sector": 0.40, "industry": 0.60},
        )
        leader, confidence = weighted_available(
            {"persistence": persistence, "acceleration": acceleration, "tradability": tradability, "peer": peer},
            {"persistence": 0.45, "acceleration": 0.20, "tradability": 0.20, "peer": 0.15},
        )
        return pd.Series({"score_leader": leader, "score_leader_confidence": confidence})

    if out.empty:
        out["score_leader"] = pd.Series(dtype="float64")
        out["score_leader_confidence"] = pd.Series(dtype="float64")
        out["leader_rank_pct"] = pd.Series(dtype="float64")
        return out
    scored = out.apply(row_score, axis=1)
    out = pd.concat([out, scored], axis=1)
    out["leader_rank_pct"] = percentile_rank(out["score_leader"]) if "score_leader" in out else np.nan
    return out

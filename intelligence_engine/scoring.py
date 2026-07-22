from __future__ import annotations

import numpy as np
import pandas as pd

from .score_policy import SCORE_WEIGHTS
from .utils import percentile_rank, weighted_available


def add_percentile_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in [
        "rs_raw_21","rs_raw_63","rs_raw_126","rs_raw_189","rs_raw_252",
        "rs_change_raw_63","rs_change_raw_126","rs_change_raw_189",
        "eps_yoy","eps_acceleration","revenue_yoy","revenue_acceleration",
        "gross_margin_delta","operating_margin_delta","free_cash_flow_yoy",
        "volume_ratio_20d","distance_52w_high_pct",
    ]:
        if col in out:
            out[f"pct_{col}"] = percentile_rank(out[col])
    if "shares_yoy" in out:
        out["pct_share_quality"] = percentile_rank(-pd.to_numeric(out["shares_yoy"], errors="coerce"))
    return out


def _row_score(row: pd.Series) -> pd.Series:
    momentum, _ = weighted_available(
        {"r63":row.get("pct_rs_raw_63"),"r126":row.get("pct_rs_raw_126"),"r189":row.get("pct_rs_raw_189"),"r252":row.get("pct_rs_raw_252"),"high":row.get("pct_distance_52w_high_pct")},
        SCORE_WEIGHTS["momentum"],
    )
    fundamental, _ = weighted_available(
        {"eps":row.get("pct_eps_yoy"),"epsa":row.get("pct_eps_acceleration"),"rev":row.get("pct_revenue_yoy"),"reva":row.get("pct_revenue_acceleration"),"opm":row.get("pct_operating_margin_delta"),"fcf":row.get("pct_free_cash_flow_yoy")},
        SCORE_WEIGHTS["fundamental"],
    )
    improvement, _ = weighted_available(
        {"r63":row.get("pct_rs_change_raw_63"),"r126":row.get("pct_rs_change_raw_126"),"r189":row.get("pct_rs_change_raw_189"),"epsa":row.get("pct_eps_acceleration"),"reva":row.get("pct_revenue_acceleration")},
        SCORE_WEIGHTS["improvement"],
    )
    leadership, _ = weighted_available(
        {"sector":row.get("sector_rank_pct"),"industry":row.get("industry_rank_pct")},
        SCORE_WEIGHTS["leadership"],
    )
    quality, _ = weighted_available(
        {"gross":row.get("pct_gross_margin_delta"),"op":row.get("pct_operating_margin_delta"),"fcf":row.get("pct_free_cash_flow_yoy"),"shares":row.get("pct_share_quality")},
        SCORE_WEIGHTS["quality"],
    )
    candidate, confidence = weighted_available(
        {"momentum":momentum,"fundamental":fundamental,"improvement":improvement,"leadership":leadership,"quality":quality},
        SCORE_WEIGHTS["candidate"],
    )
    emerging, _ = weighted_available(
        {"improvement":improvement,"fundamental":fundamental,"momentum":momentum},
        SCORE_WEIGHTS["emerging"],
    )
    compounder, _ = weighted_available(
        {"fundamental":fundamental,"quality":quality,"momentum":momentum},
        SCORE_WEIGHTS["compounder"],
    )
    breakout, _ = weighted_available(
        {"momentum":momentum,"volume":row.get("pct_volume_ratio_20d"),"high":row.get("pct_distance_52w_high_pct")},
        SCORE_WEIGHTS["breakout"],
    )
    turnaround, _ = weighted_available(
        {"improvement":improvement,"fundamental":fundamental,"momentum":momentum},
        SCORE_WEIGHTS["turnaround"],
    )
    return pd.Series({
        "score_momentum":momentum,"score_fundamental":fundamental,"score_improvement":improvement,
        "score_leadership":leadership,"score_quality":quality,"score_candidate":candidate,
        "score_emerging":emerging,"score_compounder":compounder,"score_breakout":breakout,
        "score_turnaround":turnaround,"score_confidence":confidence,
    })


def score_universe(frame: pd.DataFrame) -> pd.DataFrame:
    out = add_percentile_features(frame)
    out["sector_rank_pct"] = percentile_rank(out.groupby("sector")["rs_raw_126"].transform("mean")) if "sector" in out and "rs_raw_126" in out else np.nan
    out["industry_rank_pct"] = percentile_rank(out.groupby("industry")["rs_raw_126"].transform("mean")) if "industry" in out and "rs_raw_126" in out else np.nan
    return pd.concat([out, out.apply(_row_score, axis=1)], axis=1)

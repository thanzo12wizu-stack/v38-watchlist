from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .utils import percentile_rank, weighted_available

STORY_POLICY_VERSION = "1.1.0"


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric Series aligned to frame.index for missing/scalar/duplicate inputs."""
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64", name=column)
    value: Any = frame.loc[:, column]
    if isinstance(value, pd.DataFrame):
        value = value.apply(pd.to_numeric, errors="coerce").bfill(axis=1).iloc[:, 0]
    elif not isinstance(value, pd.Series):
        value = pd.Series(value, index=frame.index, name=column)
    return pd.to_numeric(value, errors="coerce").reindex(frame.index)


def _mean_available(series: list[pd.Series], index: pd.Index) -> pd.Series:
    return pd.concat([s.reindex(index) for s in series], axis=1).mean(axis=1, skipna=True)


def _phase(row: pd.Series) -> str:
    evidence = pd.to_numeric(row.get("story_evidence_count"), errors="coerce")
    confidence = pd.to_numeric(row.get("score_story_confidence"), errors="coerce")
    if pd.isna(evidence) or evidence < 2 or pd.isna(confidence) or confidence < .25:
        return "DATA_INSUFFICIENT"
    growth = pd.to_numeric(row.get("story_growth_raw"), errors="coerce")
    acceleration = pd.to_numeric(row.get("story_acceleration_raw"), errors="coerce")
    quality = pd.to_numeric(row.get("story_quality_raw"), errors="coerce")
    dilution = pd.to_numeric(row.get("shares_yoy"), errors="coerce")
    if pd.notna(dilution) and dilution > .08:
        return "DILUTING"
    if pd.notna(growth) and growth > .20 and pd.notna(acceleration) and acceleration > 0 and pd.notna(quality) and quality >= 0:
        return "ACCELERATING"
    if pd.notna(growth) and growth > .10 and (pd.isna(quality) or quality >= 0):
        return "COMPOUNDING"
    if pd.notna(acceleration) and acceleration > 0 and (pd.isna(growth) or growth <= .10):
        return "INFLECTING"
    if pd.notna(growth) and growth < 0 and pd.notna(acceleration) and acceleration < 0:
        return "DETERIORATING"
    if pd.notna(quality) and quality < 0:
        return "MARGIN_PRESSURE"
    return "MIXED"


def add_story_intelligence(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    eps_yoy = _numeric_series(out, "eps_yoy")
    revenue_yoy = _numeric_series(out, "revenue_yoy")
    eps_acc = _numeric_series(out, "eps_acceleration")
    revenue_acc = _numeric_series(out, "revenue_acceleration")
    gross_delta = _numeric_series(out, "gross_margin_delta")
    operating_delta = _numeric_series(out, "operating_margin_delta")
    fcf_yoy = _numeric_series(out, "free_cash_flow_yoy")
    shares_yoy = _numeric_series(out, "shares_yoy")
    evidence_frame = pd.concat(
        [eps_yoy, revenue_yoy, eps_acc, revenue_acc, gross_delta, operating_delta, fcf_yoy, shares_yoy],
        axis=1,
    )
    out["story_evidence_count"] = evidence_frame.notna().sum(axis=1)
    out["story_growth_raw"] = _mean_available([eps_yoy, revenue_yoy], out.index)
    out["story_acceleration_raw"] = _mean_available([eps_acc, revenue_acc], out.index)
    out["story_quality_raw"] = _mean_available([gross_delta, operating_delta, fcf_yoy], out.index)
    out["story_dilution_quality_raw"] = -shares_yoy
    if "shares_yoy" not in out.columns:
        out["shares_yoy"] = shares_yoy
    for col in ("story_growth_raw", "story_acceleration_raw", "story_quality_raw", "story_dilution_quality_raw"):
        out[f"pct_{col}"] = percentile_rank(out[col])

    def score(row: pd.Series) -> pd.Series:
        value, confidence = weighted_available(
            {
                "growth": row.get("pct_story_growth_raw"),
                "acceleration": row.get("pct_story_acceleration_raw"),
                "quality": row.get("pct_story_quality_raw"),
                "dilution": row.get("pct_story_dilution_quality_raw"),
            },
            {"growth": .35, "acceleration": .30, "quality": .25, "dilution": .10},
        )
        return pd.Series({"score_story": value, "score_story_confidence": confidence})

    if out.empty:
        out["score_story"] = pd.Series(dtype="float64")
        out["score_story_confidence"] = pd.Series(dtype="float64")
        out["story_rank_pct"] = pd.Series(dtype="float64")
        out["story_phase"] = pd.Series(dtype="object")
        return out
    out = pd.concat([out, out.apply(score, axis=1)], axis=1)
    out["story_rank_pct"] = percentile_rank(out["score_story"])
    out["story_phase"] = out.apply(_phase, axis=1)
    return out


def build_story_records(frame: pd.DataFrame, limit: int = 100) -> list[dict]:
    if frame.empty:
        return []
    work = frame.sort_values(
        ["score_story", "score_story_confidence", "ticker"],
        ascending=[False, False, True],
        na_position="last",
    ).head(limit)
    records = []
    for _, row in work.iterrows():
        risks = []
        if row.get("story_phase") in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}:
            risks.append(str(row.get("story_phase")).lower())
        if row.get("story_phase") == "DATA_INSUFFICIENT":
            risks.append("data_insufficient")
        records.append(
            {
                "ticker": str(row["ticker"]),
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "score_story": row.get("score_story"),
                "story_confidence": row.get("score_story_confidence"),
                "story_evidence_count": row.get("story_evidence_count"),
                "story_phase": row.get("story_phase"),
                "growth": row.get("story_growth_raw"),
                "acceleration": row.get("story_acceleration_raw"),
                "quality": row.get("story_quality_raw"),
                "shares_yoy": row.get("shares_yoy"),
                "latest_filing_date": row.get("latest_filing_date"),
                "risks": risks,
            }
        )
    return records


def apply_story_context(candidates: list[dict], frame: pd.DataFrame) -> list[dict]:
    lookup = frame.set_index("ticker") if not frame.empty else pd.DataFrame()
    result = []
    for item in candidates:
        enriched = dict(item)
        ticker = str(item.get("ticker"))
        if not lookup.empty and ticker in lookup.index:
            row = lookup.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            enriched.update(
                {
                    "story_score": row.get("score_story"),
                    "story_phase": row.get("story_phase"),
                    "story_confidence": row.get("score_story_confidence"),
                    "story_evidence_count": row.get("story_evidence_count"),
                }
            )
            warnings = list(enriched.get("warnings") or [])
            if row.get("story_phase") in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}:
                warnings.append(f"story_{str(row.get('story_phase')).lower()}")
            if row.get("story_phase") == "DATA_INSUFFICIENT":
                warnings.append("story_data_insufficient")
            enriched["warnings"] = sorted(set(warnings))
        else:
            enriched["story_phase"] = "DATA_INSUFFICIENT"
            enriched["story_confidence"] = 0.0
            warnings = list(enriched.get("warnings") or [])
            warnings.append("story_data_insufficient")
            enriched["warnings"] = sorted(set(warnings))
        result.append(enriched)
    return result

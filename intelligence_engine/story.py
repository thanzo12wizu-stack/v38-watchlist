from __future__ import annotations

import pandas as pd

from .utils import percentile_rank, weighted_available

STORY_POLICY_VERSION = "1.0.0"


def _phase(row: pd.Series) -> str:
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
    eps_yoy = pd.to_numeric(out.get("eps_yoy"), errors="coerce")
    revenue_yoy = pd.to_numeric(out.get("revenue_yoy"), errors="coerce")
    eps_acc = pd.to_numeric(out.get("eps_acceleration"), errors="coerce")
    revenue_acc = pd.to_numeric(out.get("revenue_acceleration"), errors="coerce")
    gross_delta = pd.to_numeric(out.get("gross_margin_delta"), errors="coerce")
    operating_delta = pd.to_numeric(out.get("operating_margin_delta"), errors="coerce")
    fcf_yoy = pd.to_numeric(out.get("free_cash_flow_yoy"), errors="coerce")
    shares_yoy = pd.to_numeric(out.get("shares_yoy"), errors="coerce")

    out["story_growth_raw"] = pd.concat([eps_yoy, revenue_yoy], axis=1).mean(axis=1, skipna=True)
    out["story_acceleration_raw"] = pd.concat([eps_acc, revenue_acc], axis=1).mean(axis=1, skipna=True)
    out["story_quality_raw"] = pd.concat([gross_delta, operating_delta, fcf_yoy], axis=1).mean(axis=1, skipna=True)
    out["story_dilution_quality_raw"] = -shares_yoy

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

    out = pd.concat([out, out.apply(score, axis=1)], axis=1)
    out["story_rank_pct"] = percentile_rank(out["score_story"])
    out["story_phase"] = out.apply(_phase, axis=1)
    return out


def build_story_records(frame: pd.DataFrame, limit: int = 100) -> list[dict]:
    if frame.empty:
        return []
    work = frame.sort_values(["score_story", "score_story_confidence", "ticker"], ascending=[False, False, True]).head(limit)
    records = []
    for _, row in work.iterrows():
        risks = []
        if row.get("story_phase") in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}:
            risks.append(str(row.get("story_phase")).lower())
        records.append({
            "ticker": str(row["ticker"]),
            "sector": row.get("sector"),
            "industry": row.get("industry"),
            "score_story": row.get("score_story"),
            "story_confidence": row.get("score_story_confidence"),
            "story_phase": row.get("story_phase"),
            "growth": row.get("story_growth_raw"),
            "acceleration": row.get("story_acceleration_raw"),
            "quality": row.get("story_quality_raw"),
            "shares_yoy": row.get("shares_yoy"),
            "latest_filing_date": row.get("latest_filing_date"),
            "risks": risks,
        })
    return records


def apply_story_context(candidates: list[dict], frame: pd.DataFrame) -> list[dict]:
    lookup = frame.set_index("ticker") if not frame.empty else pd.DataFrame()
    result = []
    for item in candidates:
        enriched = dict(item)
        ticker = str(item.get("ticker"))
        if not lookup.empty and ticker in lookup.index:
            row = lookup.loc[ticker]
            enriched.update({
                "story_score": row.get("score_story"),
                "story_phase": row.get("story_phase"),
                "story_confidence": row.get("score_story_confidence"),
            })
            if row.get("story_phase") in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}:
                warnings = list(enriched.get("warnings") or [])
                warnings.append(f"story_{str(row.get('story_phase')).lower()}")
                enriched["warnings"] = sorted(set(warnings))
        result.append(enriched)
    return result

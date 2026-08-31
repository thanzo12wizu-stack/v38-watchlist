from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import requests

import rotation_live_snapshot as base
import rotation_macro_direct_official_qa as direct
import rotation_macro_why_qa as macroqa

_ORIGINAL_FETCH_EXACT_FLOWS = base.fetch_exact_flows
_ORIGINAL_BUILD_OBSERVATIONS = base.build_observations


def series_payload(df: pd.DataFrame | None, error: str | None, source: str) -> dict[str, Any]:
    if df is None or error is not None or df.empty:
        return {"quality": "DATA_REQUIRED", "source": source, "error": error}
    return {
        "quality": "EXACT_OFFICIAL",
        "source": source,
        "asof": str(df.date.iloc[-1].date()),
        "value": float(df.value.iloc[-1]),
        "change_20obs": None if len(df) < 21 else float(df.value.iloc[-1] - df.value.iloc[-21]),
        "high_252": float(df.value.tail(252).max()),
        "low_252": float(df.value.tail(252).min()),
    }


def fetch_exact_flows_latest_valid(session: requests.Session, close: pd.DataFrame):
    """Select the latest valid official 20D Flow observation; never forward-fill."""
    flows, diag = _ORIGINAL_FETCH_EXACT_FLOWS(session, close)
    valid = flows[flows["flow_20d"].notna() & flows["flow_20d_pct_aum"].notna()].copy()
    for d in diag:
        ticker = d.get("ticker")
        x = valid[valid["ticker"] == ticker]
        d["live_latest_valid_flow_date"] = None if x.empty else str(pd.Timestamp(x["date"].max()).date())
        d["live_selection_policy"] = "LATEST_VALID_OFFICIAL_20D_FLOW_NO_FORWARD_FILL"
    return valid, diag


def direct_macro_snapshot(session: requests.Session, ohlcv: dict[str, pd.DataFrame]) -> dict[str, Any]:
    year = pd.Timestamp(date.today()).year
    nominal, nerr, nurl = direct.fetch_treasury(session, "daily_treasury_yield_curve", "BC_10YEAR", year)
    real, rerr, rurl = direct.fetch_treasury(session, "daily_treasury_real_yield_curve", "TC_10YEAR", year)
    broad, berr = direct.fetch_fed_broad(session)

    cnn, cerr = macroqa.fetch_json(session, macroqa.CNN_CURRENT)
    ctab = macroqa.current_cnn_table(cnn)
    components = []
    if not ctab.empty:
        for row in ctab.to_dict("records"):
            components.append({"component": row["component"], "score": base.num(row["score"]), "rating": row.get("rating")})
    fearish = [x for x in components if x["component"] != "fear_and_greed" and str(x.get("rating") or "").lower() in {"fear", "extreme fear"}]
    greedish = [x for x in components if x["component"] != "fear_and_greed" and str(x.get("rating") or "").lower() in {"greed", "extreme greed"}]
    headline = next((x for x in components if x["component"] == "fear_and_greed"), None)
    vix = base.latest_scalar(ohlcv["close"]["^VIX"]) if "^VIX" in ohlcv["close"].columns else None

    return {
        "rates": {
            "us10y": series_payload(nominal, nerr, nurl),
            "real10y": series_payload(real, rerr, rurl),
        },
        "broad_usd": series_payload(broad, berr, direct.FED_BROAD_DAILY),
        "credit": {
            "ig_oas": {"quality": "DATA_REQUIRED", "reason": "FRED timeout from GitHub Actions; no proxy substituted"},
            "hy_oas": {"quality": "DATA_REQUIRED", "reason": "FRED timeout from GitHub Actions; CNN Junk Bond Demand is kept as a separate exact component"},
        },
        "vix": {"quality": "MARKET_PRICE_SERIES" if vix is not None else "DATA_REQUIRED", "value": vix},
        "fear_greed": {
            "quality": "EXACT_CNN_COMPONENTS" if cerr is None and len(components) == 8 else "DATA_REQUIRED",
            "headline": headline,
            "components": components,
            "split": bool(fearish and greedish),
            "fear_components": [x["component"] for x in fearish],
            "greed_components": [x["component"] for x in greedish],
        },
        "dxy": {"quality": "DATA_REQUIRED", "note": "DXY source contract is unproven. FRB Broad Dollar is not relabeled DXY."},
        "guardrail": "Macro WHY is explanatory only and never a V38 trading Gate.",
    }


def classify_state_v2(row: dict[str, Any], *, validated_sector: bool) -> tuple[str, str]:
    p = row.get("validated_price_score") if validated_sector else row.get("matrix_price_score")
    i = row.get("validated_internal_score") if validated_sector else row.get("matrix_internal_score")
    d = row.get("validated_internal_delta20") if validated_sector else row.get("matrix_internal_delta20")
    f = row.get("flow_20d_pct_aum")
    if any(x is None for x in (p, i, f)):
        return "DATA_REQUIRED", "price/internal/flowのいずれかが不足"

    # Predictive/context labels are restricted to the PIT-tested 11-Sector cross-section.
    if validated_sector and p >= 70 and i < 50 and f <= 0:
        return "DISTRIBUTION_WARNING", "PIT検証済み厳格条件: Price>=70・Internal<50・20D Flow<=0。Contextのみ"
    if validated_sector and p >= 70 and d is not None and d <= -20 and f <= 0:
        return "DISTRIBUTION_DETERIORATION_WARNING", "PIT delta型: Price>=70・Internal20D変化<=-20pt・Flow<=0。2024+ 40D支持、20D block CIは0跨ぎ。早期警戒Contextのみ"

    # Purely descriptive states below do not claim future alpha.
    if p < 45 and i < 45:
        return "WEAK_BREAKDOWN", "価格・内部がともに弱い"
    if i < 50 and f < 0:
        return "INTERNAL_WEAK_FLOW_OUT", "内部弱＋ETF Flow流出。Industryでは未PIT検証の診断表示のみ"
    if i < 50 and f > 0:
        return "FLOW_INTERNAL_DIVERGENCE_WATCH", "ETF Flow流入に内部参加が追随していない。WATCHのみ"
    if p >= 60 and i >= 60 and f < 0:
        return "REDEMPTION_DIVERGENCE", "価格・内部は強いがETF Flowは流出。売り抜けと断定しない"
    if p >= 70 and i >= 60:
        return "CURRENT_STRENGTH", "価格・内部が同時に強い現在状態。PIT研究では将来Alphaを確認できず、買いシグナルではない"
    if p < 60 and i >= 50 and d is not None and d >= 10 and f >= 0:
        return "EARLY_ROTATION_WATCH", "内部改善＋Flow流入が価格に先行。PIT研究では買いシグナル不採用、WATCHのみ"
    if p < 60 and i >= 60:
        return "INTERNAL_LEAD_WATCH", "価格より内部参加が強い。観測用で将来Alphaは主張しない"
    return "MIXED_HOLD", "方向不一致または閾値未達"


def build_observations_v2(matrix: list[dict[str, Any]], macro: dict[str, Any]) -> list[dict[str, str]]:
    obs = _ORIGINAL_BUILD_OBSERVATIONS(matrix, macro)

    strict = [r for r in matrix if r.get("state") == "DISTRIBUTION_WARNING"]
    deterioration = [r for r in matrix if r.get("state") == "DISTRIBUTION_DETERIORATION_WARNING"]
    flow_internal = [r for r in matrix if r.get("state") == "FLOW_INTERNAL_DIVERGENCE_WATCH"]
    weak_out = [r for r in matrix if r.get("state") == "INTERNAL_WEAK_FLOW_OUT"]
    internal_lead = [r for r in matrix if r.get("state") == "INTERNAL_LEAD_WATCH"]

    extra: list[dict[str, str]] = []
    if strict:
        extra.append({"type": "STRICT_DISTRIBUTION", "text": "厳格PIT分配警戒: " + " / ".join(r["ticker"] for r in strict)})
    if deterioration:
        extra.append({"type": "DISTRIBUTION_DETERIORATION", "text": "内部急落型の早期分配警戒（40D支持）: " + " / ".join(r["ticker"] for r in deterioration)})
    if flow_internal:
        extra.append({"type": "FLOW_INTERNAL_DIVERGENCE", "text": "Flow流入だが内部弱・昇格待ち: " + " / ".join(r["ticker"] for r in flow_internal)})
    if weak_out:
        extra.append({"type": "INTERNAL_WEAK_FLOW_OUT", "text": "内部弱＋Flow流出: " + " / ".join(r["ticker"] for r in weak_out)})
    if internal_lead:
        extra.append({"type": "INTERNAL_LEAD", "text": "価格より内部が先行（観測のみ）: " + " / ".join(r["ticker"] for r in internal_lead)})

    rate = (macro.get("rates") or {}).get("us10y") or {}
    if rate.get("quality") == "EXACT_OFFICIAL" and rate.get("value") is not None and rate.get("high_252") is not None:
        value = float(rate["value"])
        high = float(rate["high_252"])
        sensitive = [r for r in matrix if r.get("ticker") in {"XLU", "XLRE"} and (r.get("validated_internal_score") is not None and float(r["validated_internal_score"]) < 30)]
        if high - value <= 0.10 and sensitive:
            extra.append({"type": "RATE_SENSITIVE_PRESSURE", "text": f"米10年 {value:.2f}% は52週高値 {high:.2f}%近辺。内部弱の金利感応: " + " / ".join(r["ticker"] for r in sensitive)})

    # Preserve deterministic original observations but replace stale state-specific duplicates.
    drop_types = {"DISTRIBUTION", "WATCH"}
    kept = [x for x in obs if x.get("type") not in drop_types]
    return kept + extra


base.fetch_exact_flows = fetch_exact_flows_latest_valid
base.macro_snapshot = direct_macro_snapshot
base.classify_state = classify_state_v2
base.build_observations = build_observations_v2

if __name__ == "__main__":
    base.main()

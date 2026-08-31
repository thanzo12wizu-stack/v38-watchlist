from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import requests

import rotation_live_snapshot as base
import rotation_macro_direct_official_qa as direct
import rotation_macro_why_qa as macroqa

_ORIGINAL_FETCH_EXACT_FLOWS = base.fetch_exact_flows


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
    """Keep only rows with a valid 20D exact flow before base.main selects ticker tail rows.

    Provider histories do not always end on the latest ETF price date. The original live
    table deliberately aligns official flow records to the ETF trading calendar, leaving
    trailing NaN rows when the provider's latest record is older than the price as-of.
    Dropping only those invalid 20D rows ensures base.main selects the latest *officially
    observed* flow date instead of a trailing calendar NaN. No value is forward-filled.
    """
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


base.fetch_exact_flows = fetch_exact_flows_latest_valid
base.macro_snapshot = direct_macro_snapshot

if __name__ == "__main__":
    base.main()

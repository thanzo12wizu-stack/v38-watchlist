from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def classify(row: dict[str, Any]) -> tuple[str, str]:
    p = num(row.get("price_score_56"))
    i = num(row.get("internal_score_56"))
    d = num(row.get("internal_delta20_56"))
    f = num(row.get("flow_20d_pct_aum"))
    if p is None:
        return "DATA_REQUIRED", "ETF価格履歴が不足。状態判定を行わない。"
    if i is None:
        return "PRICE_ONLY", "Price/RSのみ取得。正確な構成銘柄Internalsが未取得またはcoverage不足。"

    if f is not None:
        if p >= 60 and i >= 60 and f < 0:
            return "REDEMPTION_DIVERGENCE", "Price/Internalは強いが、公式ETF Flowは20日流出。"
        if p >= 70 and i >= 60:
            return "CURRENT_STRENGTH", "Priceと構成銘柄InternalsがともにTheme56上位。"
        if p < 60 and i >= 50 and d is not None and d >= 10 and f >= 0:
            return "EARLY_ROTATION_WATCH", "Internals改善と公式Flow流入がPriceに先行している観測状態。"
        if p < 45 and i < 45:
            return "WEAK_BREAKDOWN", "Priceと構成銘柄InternalsがともにTheme56下位。"
        if i < 50 and f < 0:
            return "INTERNAL_WEAK_FLOW_OUT", "Internalsが弱く、公式ETF Flowも流出。"
        if p < 55 and i >= 60:
            return "INTERNAL_LEAD_WATCH", "InternalsがPriceより先行。公式Flowは決定条件に使わない観測状態。"
        return "MIXED_HOLD", "Price/Internal/公式Flowの方向が揃っていない。"

    # Exact Flow is unavailable. Price/Internal can still describe the current cross-section,
    # but flow-dependent labels are deliberately not assigned.
    if p >= 70 and i >= 60:
        return "CURRENT_STRENGTH", "Priceと構成銘柄InternalsがともにTheme56上位。Exact Flowは未取得。"
    if p < 45 and i < 45:
        return "WEAK_BREAKDOWN", "Priceと構成銘柄InternalsがともにTheme56下位。Exact Flowは未取得。"
    if p < 60 and i >= 60 and d is not None and d >= 10:
        return "INTERNAL_LEAD_WATCH", "Internals改善がPriceに先行。Exact Flow未取得のため流入判定はしない。"
    return "MIXED_HOLD", "PriceとInternalsの方向が揃わない、または中位。Exact Flowは未取得。"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the public-compatible Theme56 Rotation brief while preserving current V38/Macro context")
    ap.add_argument("--base-brief", type=Path, required=True)
    ap.add_argument("--fullstack", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    base = load_json(args.base_brief)
    fs = load_json(args.fullstack)
    rows = fs.get("rows") if isinstance(fs.get("rows"), list) else []
    if len(rows) != 56:
        raise RuntimeError(f"expected 56 Theme56 rows, got {len(rows)}")

    out = copy.deepcopy(base)
    theme_rows: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        state, reason = classify(raw)
        theme_rows.append({
            "ticker": raw.get("ticker"),
            "label": raw.get("label"),
            "level": "THEME",
            "state": state,
            "state_evidence": "THEME56_DESCRIPTIVE_NOT_TRADING_SIGNAL",
            "state_reason": reason,
            "price_score": raw.get("price_score_56"),
            "internal_score": raw.get("internal_score_56"),
            "internal_delta20": raw.get("internal_delta20_56"),
            "ret_1d_pct": raw.get("ret_1d_pct"),
            "ret_5d_pct": raw.get("ret_5d_pct"),
            "ret_20d_pct": raw.get("ret_20d_pct"),
            "flow_1d_usd": raw.get("flow_1d_usd"),
            "flow_5d_usd": raw.get("flow_5d_usd"),
            "flow_20d_usd": raw.get("flow_20d_usd"),
            "flow_20d_pct_aum": raw.get("flow_20d_pct_aum"),
            "flow_provider": raw.get("flow_provider"),
            "source_member_coverage": raw.get("source_member_coverage"),
            "quality": raw.get("quality"),
            "exact_flow": raw.get("exact_flow_adapter") == "PASS",
            "exact_holdings": raw.get("holdings_adapter") == "PASS",
        })

    observations = out.get("observations") if isinstance(out.get("observations"), dict) else {}
    observations["rotation_buckets"] = {"themes": theme_rows}
    observations["state_transitions"] = []
    exact_flow_rows = [x for x in theme_rows if num(x.get("flow_20d_pct_aum")) is not None]
    flow_sorted = sorted(exact_flow_rows, key=lambda x: num(x.get("flow_20d_pct_aum")) or 0.0, reverse=True)
    observations["flow"] = {
        "scope": "EXACT_FLOW_ONLY",
        "leaders": flow_sorted[:5],
        "laggards": list(reversed(flow_sorted[-5:])),
        "coverage": len(exact_flow_rows),
        "universe": 56,
        "note": "Flow ranking uses only ETFs with official NAV + Shares Outstanding. Missing Flow is never proxied.",
    }
    out["observations"] = observations

    theme_asof = fs.get("asof")
    base_asof = base.get("asof")
    out["schema"] = 3
    out["research_only"] = True
    out["deterministic_formatter"] = True
    out["asof"] = theme_asof or base_asof
    same = bool(theme_asof and base_asof and str(theme_asof) == str(base_asof))
    out["input_alignment"] = {
        "status": "OK" if same else "PARTIAL",
        "rotation_asof": theme_asof,
        "v38_asof": base_asof,
        "same_asof": same,
        "note": None if same else "Theme56 Rotationと既存V38/Macroの基準日が異なるため、それぞれの基準日を維持して表示。",
    }
    out["theme56_data_status"] = {
        "universe_count": 56,
        "price_ready_count": fs.get("price_ready_count"),
        "exact_holdings_count": fs.get("exact_holdings_count"),
        "internal_measured_count": fs.get("internal_measured_count"),
        "exact_flow_count": fs.get("exact_flow_count"),
        "measured_full_stack_count": fs.get("measured_full_stack_count"),
        "classification_contract": "DESCRIPTIVE_ONLY_NOT_TRADING_SIGNAL",
    }
    limits = out.get("limitations") if isinstance(out.get("limitations"), list) else []
    theme_limits = [
        "Theme56 state labels are descriptive current observations, not validated trading signals.",
        "Exact Flow is shown only where official NAV + Shares Outstanding is available; no price/volume proxy is substituted.",
        "Theme56 leading-stock membership uses exact current ETF holdings and is not historical PIT membership.",
        "Distribution Warning is deliberately not assigned at Theme56 level until separate PIT validation is complete.",
    ]
    out["limitations"] = limits + [x for x in theme_limits if x not in limits]

    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "rotation_theme56_public_brief.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for x in theme_rows:
        counts[str(x.get("state"))] = counts.get(str(x.get("state")), 0) + 1
    print(json.dumps({"asof": out["asof"], "alignment": out["input_alignment"], "states": counts, "flow_coverage": len(exact_flow_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

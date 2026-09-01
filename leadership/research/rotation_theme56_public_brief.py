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
    if str(row.get("ticker") or "").upper() == "DRAM" and (
        row.get("rs189_pending") is True
        or row.get("price_quality") == "MARKET_PRICE_SERIES_RS189_PENDING"
    ):
        return "RS189_PENDING", "2026-04-02設定。短期価格・補助Internals・1M実Fund Flowは表示し、RS189と総合Price Scoreのみ履歴待ち。"

    p = num(row.get("price_score_56"))
    i = num(row.get("internal_score_56"))
    d = num(row.get("internal_delta20_56"))
    f = num(row.get("flow_20d_pct_aum"))
    if p is None:
        return "DATA_REQUIRED", "ETF価格履歴が不足。状態判定を行わない。"
    if i is None:
        return "PRICE_ONLY", "Price/RSのみ取得。構成銘柄Internalsが未取得またはcoverage不足。"

    if f is not None:
        if p >= 60 and i >= 60 and f < 0:
            return "REDEMPTION_DIVERGENCE", "Price/Internalは強いが、ETF Fund Flowは20日流出。"
        if p >= 70 and i >= 60:
            return "CURRENT_STRENGTH", "Priceと構成銘柄InternalsがともにTheme56上位。"
        if p < 60 and i >= 50 and d is not None and d >= 10 and f >= 0:
            return "EARLY_ROTATION_WATCH", "Internals改善とFund Flow流入がPriceに先行している観測状態。"
        if p < 45 and i < 45:
            return "WEAK_BREAKDOWN", "Priceと構成銘柄InternalsがともにTheme56下位。"
        if i < 50 and f < 0:
            return "INTERNAL_WEAK_FLOW_OUT", "Internalsが弱く、ETF Fund Flowも流出。"
        if p < 55 and i >= 60:
            return "INTERNAL_LEAD_WATCH", "InternalsがPriceより先行。Fund Flowは決定条件に使わない観測状態。"
        return "MIXED_HOLD", "Price/Internal/Fund Flowの方向が揃っていない。"

    if p >= 70 and i >= 60:
        return "CURRENT_STRENGTH", "Priceと構成銘柄InternalsがともにTheme56上位。Fund Flowは未取得。"
    if p < 45 and i < 45:
        return "WEAK_BREAKDOWN", "Priceと構成銘柄InternalsがともにTheme56下位。Fund Flowは未取得。"
    if p < 60 and i >= 60 and d is not None and d >= 10:
        return "INTERNAL_LEAD_WATCH", "Internals改善がPriceに先行。Fund Flow未取得のため流入判定はしない。"
    return "MIXED_HOLD", "PriceとInternalsの方向が揃わない、または中位。Fund Flowは未取得。"


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
        holdings_quality = str(raw.get("holdings_quality") or "")
        flow_quality = str(raw.get("flow_quality") or "")
        internal_display = raw.get("internal_score_56")
        internal_display_quality = "THEME56_STANDARD"
        if num(internal_display) is None and num(raw.get("internal_supplemental_score_55ref")) is not None:
            internal_display = raw.get("internal_supplemental_score_55ref")
            internal_display_quality = str(raw.get("internal_supplemental_quality") or "DRAM_SUPPLEMENTAL")
        theme_rows.append({
            "ticker": raw.get("ticker"),
            "label": raw.get("label"),
            "level": "THEME",
            "state": state,
            "state_evidence": "THEME56_DESCRIPTIVE_NOT_TRADING_SIGNAL",
            "state_reason": reason,
            "price_score": raw.get("price_score_56"),
            "price_quality": raw.get("price_quality"),
            "inception_date": raw.get("inception_date"),
            "rs189_pending": raw.get("rs189_pending") is True,
            "rs63_vs_spy": raw.get("rs63_vs_spy"),
            "internal_score": internal_display,
            "internal_display_quality": internal_display_quality,
            "internal_delta20": raw.get("internal_delta20_56"),
            "internal_supplemental_members": raw.get("internal_supplemental_members"),
            "internal_supplemental_downloaded_members": raw.get("internal_supplemental_downloaded_members"),
            "internal_supplemental_coverage": raw.get("internal_supplemental_coverage"),
            "internal_supplemental_membership_asof": raw.get("internal_supplemental_membership_asof"),
            "ret_1d_pct": raw.get("ret_1d_pct"),
            "ret_5d_pct": raw.get("ret_5d_pct"),
            "ret_20d_pct": raw.get("ret_20d_pct"),
            "flow_1d_usd": raw.get("flow_1d_usd"),
            "flow_5d_usd": raw.get("flow_5d_usd"),
            "flow_20d_usd": raw.get("flow_20d_usd"),
            "flow_20d_pct_aum": raw.get("flow_20d_pct_aum"),
            "flow_provider": raw.get("flow_provider"),
            "flow_quality": flow_quality or None,
            "flow_1m_usd": raw.get("flow_1m_usd"),
            "flow_1m_pct_aum": raw.get("flow_1m_pct_aum"),
            "flow_1m_provider": raw.get("flow_1m_provider"),
            "flow_1m_quality": raw.get("flow_1m_quality"),
            "holdings_quality": holdings_quality or None,
            "source_member_coverage": raw.get("source_member_coverage"),
            "quality": raw.get("quality"),
            "flow_ready": raw.get("actual_flow_adapter") == "PASS",
            "exact_flow": raw.get("exact_flow_adapter") == "PASS",
            "holdings_ready": raw.get("holdings_adapter") == "PASS",
            "exact_holdings": holdings_quality == "ISSUER_EXACT_CURRENT",
        })

    observations = out.get("observations") if isinstance(out.get("observations"), dict) else {}
    observations["rotation_buckets"] = {"themes": theme_rows}
    observations["state_transitions"] = []
    flow_rows = [x for x in theme_rows if x.get("flow_ready") and num(x.get("flow_20d_pct_aum")) is not None]
    flow_sorted = sorted(flow_rows, key=lambda x: num(x.get("flow_20d_pct_aum")) or 0.0, reverse=True)
    observations["flow"] = {
        "scope": "VALIDATED_ACTUAL_FUND_FLOW",
        "leaders": flow_sorted[:5],
        "laggards": list(reversed(flow_sorted[-5:])),
        "coverage": len(flow_rows),
        "universe": 56,
        "source_counts": fs.get("flow_source_counts") or {},
        "note": "Issuer-derived Exact Flowを優先し、残りは発行会社データとの照合を通過したETF.com actual fund flowを使用。価格・出来高proxyは不使用。DRAM補助1M Flowはこの20日ランキングには混ぜない。",
    }
    out["observations"] = observations

    theme_asof = fs.get("asof")
    base_asof = base.get("asof")
    out["schema"] = 5
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
        "holdings_ready_count": fs.get("holdings_ready_count"),
        "issuer_exact_holdings_count": fs.get("issuer_exact_holdings_count"),
        "validated_fallback_holdings_count": fs.get("validated_fallback_holdings_count"),
        "internal_measured_count": fs.get("internal_measured_count"),
        "flow_ready_count": fs.get("flow_ready_count"),
        "issuer_exact_flow_count": fs.get("issuer_exact_flow_count"),
        "validated_actual_flow_count": fs.get("validated_actual_flow_count"),
        "measured_full_stack_count": fs.get("measured_full_stack_count"),
        "dram_supplemental": fs.get("dram_supplemental"),
        "formal_exception": "DRAM: 2026-04-02設定。短期価格・補助Internals・1M実Fund Flowは表示し、RS189と総合Price Scoreのみ履歴待ち。",
        "classification_contract": "DESCRIPTIVE_ONLY_NOT_TRADING_SIGNAL",
    }
    limits = out.get("limitations") if isinstance(out.get("limitations"), list) else []
    theme_limits = [
        "Theme56 state labels are descriptive current observations, not validated trading signals.",
        "Fund Flow uses issuer-derived Exact Flow where clean and ETF.com validated actual fund flow otherwise; no price/volume proxy is substituted.",
        "Theme56 constituent membership prefers issuer-exact current holdings; validated fallback membership is separately labeled and must meet the >=80% validation contract.",
        "Theme56 leading-stock membership is current membership and is not historical PIT membership.",
        "DRAM launched on 2026-04-02, so RS189 and the established composite Price Score remain pending; short returns and RS63 remain visible.",
        "DRAM supplemental Internal uses current direct listed equities only and a frozen 55-theme reference percentile; it does not alter the existing 55-theme Internal ranks.",
        "DRAM supplemental TradingView fund_flows.1M is displayed only as 1M context and is not substituted into the validated 20-trading-day Flow ranking or state rules.",
        "Distribution Warning is deliberately not assigned at Theme56 level until separate PIT validation is complete.",
    ]
    out["limitations"] = limits + [x for x in theme_limits if x not in limits]

    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / "rotation_theme56_public_brief.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for x in theme_rows:
        counts[str(x.get("state"))] = counts.get(str(x.get("state")), 0) + 1
    print(json.dumps({"asof": out["asof"], "alignment": out["input_alignment"], "states": counts, "flow_coverage": len(flow_rows), "data_status": out["theme56_data_status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

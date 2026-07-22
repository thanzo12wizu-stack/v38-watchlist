from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd

PRESENTATION_POLICY_VERSION = "1.0.1"

WARNING_JA = {
    "market_gate": "地合いゲートにより新規発注停止",
    "earnings_unknown": "決算日を確認できていない",
    "earnings_window": "決算前後3営業日のため新規回避",
    "supply": "下落日の出来高比率が高い",
    "hard_block": "長期トレンド条件を満たしていない",
    "extended": "50日線からの乖離が大きい",
    "theme_weakening": "テーマの内部モメンタムが弱化",
    "story_deteriorating": "業績成長と加速が悪化",
    "story_margin_pressure": "利益率またはキャッシュ創出が悪化",
    "story_diluting": "株式希薄化が大きい",
    "story_data_insufficient": "財務データが不足",
    "stop_risk_high": "想定損切り幅が大きい",
    "reward_risk_low": "上値余地に対して損切り幅が大きい",
    "data_stale": "データが古い",
    "external_data_missing": "決算・材料データの取得範囲が不足",
    "eps_revisions_down": "EPS予想が下方修正",
    "guidance_cut": "会社ガイダンスが引き下げ",
    "large_insider_sale": "大口インサイダー売却",
}

STATUS_JA = {
    "ACTIONABLE": "発注可能",
    "READY": "準備候補",
    "AVOID": "回避",
}

SETUP_JA = {
    "PULLBACK": "21EMA付近の押し目",
    "PRE_BREAKOUT": "ピボット直前の収縮",
    "BREAKOUT": "出来高を伴うブレイク",
    "VOLUME_SURGE": "出来高急増",
    "DEEP_PULLBACK": "深い押し目",
    "WATCH": "形待ち",
    "EXTENDED": "過熱",
    "AVOID": "長期条件未達",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bounded(value: float | None, low: float = 0.0, high: float = 100.0) -> float | None:
    if value is None:
        return None
    return min(max(value, low), high)


def _theme_score(candidate: dict[str, Any]) -> float | None:
    raw = _number(candidate.get("theme_score"))
    if raw is None:
        return None
    return raw * 100.0 if raw <= 1.0 else raw


def _expectancy_component(candidate: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    exp = candidate.get("expectancy") or {}
    ten = exp.get("10") or {}
    base = ten.get("setup") or {}
    calibration = ten.get("score_calibration") or {}
    mean = _number(base.get("mean_excess_return"))
    if mean is None:
        mean = _number(calibration.get("expected_excess_return"))
    samples = int(base.get("samples") or calibration.get("samples") or 0)
    p10 = _number(base.get("downside_tail_p10"))
    if p10 is None:
        p10 = _number(calibration.get("p10"))
    qualified = bool(base.get("usable") or base.get("qualified") or samples >= 50)
    if not qualified or mean is None:
        return None, {"samples": samples, "qualified": False, "mean_excess": mean, "p10": p10}
    score = 50.0 + mean * 1000.0
    if p10 is not None and p10 < -0.08:
        score -= min(20.0, abs(p10 + 0.08) * 250.0)
    return _bounded(score), {"samples": samples, "qualified": True, "mean_excess": mean, "p10": p10}


def _entry_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    price = _number(candidate.get("price"))
    pivot = _number(candidate.get("pivot"))
    ema = _number(candidate.get("stop_ema21_low"))
    sma10 = _number(candidate.get("stop_sma10"))
    adr = _number(candidate.get("adr_pct")) or 0.0
    setup = str(candidate.get("setup") or "WATCH")

    entry_low = entry_high = entry_1 = entry_2 = None
    if price is not None:
        adr_fraction = max(adr, 1.0) / 100.0
        if setup == "PRE_BREAKOUT" and pivot is not None:
            entry_low = pivot * 0.985
            entry_high = pivot * 1.005
            entry_1 = entry_low
            entry_2 = pivot
        elif setup == "BREAKOUT" and pivot is not None:
            entry_low = pivot
            entry_high = max(pivot, min(price, pivot * (1.0 + min(adr_fraction * 0.5, 0.025))))
            entry_1 = pivot
            entry_2 = entry_high
        elif setup == "PULLBACK":
            reference = price * (1.0 - min(adr_fraction * 0.75, 0.05))
            entry_low = max(reference, (ema or reference) * 1.002)
            entry_low = min(entry_low, price)
            entry_high = price
            entry_1 = entry_low
            entry_2 = price if pivot is None else min(max(price, entry_low), pivot)
        else:
            entry_low = price * (1.0 - min(adr_fraction, 0.06))
            entry_high = min(pivot, price) if pivot is not None and pivot > 0 else price
            if entry_high < entry_low:
                entry_high = price
            entry_1 = entry_low
            entry_2 = pivot if pivot is not None and pivot >= price else price

    stops = [value for value in (ema, sma10) if value is not None and value > 0]
    valid_stops = [value for value in stops if entry_1 is not None and value < entry_1 * 0.998]
    stop = max(valid_stops) if valid_stops else None
    source_risk = _number(candidate.get("stop_risk_pct"))
    if stop is None and entry_1 is not None and source_risk is not None and 0 < source_risk < 50:
        stop = entry_1 * (1.0 - source_risk / 100.0)

    risk_pct = None
    if entry_1 is not None and stop is not None and entry_1 > 0:
        risk_pct = (entry_1 - stop) / entry_1 * 100.0
    if risk_pct is None:
        risk_pct = source_risk

    distance_high = _number(candidate.get("distance_52w_high_pct"))
    target = None
    if price is not None and distance_high is not None and distance_high < 0 and 1.0 + distance_high / 100.0 > 0:
        target = price / (1.0 + distance_high / 100.0)
    upside_pct = (target / entry_1 - 1.0) * 100.0 if target is not None and entry_1 else None
    rr = upside_pct / risk_pct if upside_pct is not None and risk_pct is not None and risk_pct > 0 else _number(candidate.get("reward_risk_raw"))

    return {
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_1": entry_1,
        "entry_2": entry_2,
        "stop_effective": stop,
        "stop_distance_pct": risk_pct,
        "target_reference": target,
        "upside_reference_pct": upside_pct,
        "reward_risk": rr,
    }


def _reason_codes(candidate: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    warnings = list(candidate.get("warnings") or [])
    codes.extend(str(code) for code in warnings)
    setup = str(candidate.get("setup") or "WATCH")
    gate = str(candidate.get("market_gate") or "NO_NEW")
    story = str(candidate.get("story_phase") or "DATA_INSUFFICIENT")
    theme = str(candidate.get("theme_phase") or "")

    if gate not in {"ALLOW", "SELECTIVE"} and "market_gate" not in codes:
        codes.append("market_gate")
    if bool(candidate.get("hard_block")) and "hard_block" not in codes:
        codes.append("hard_block")
    if setup == "EXTENDED" and "extended" not in codes:
        codes.append("extended")
    if story == "DATA_INSUFFICIENT" and "story_data_insufficient" not in codes:
        codes.append("story_data_insufficient")
    if story in {"DETERIORATING", "MARGIN_PRESSURE", "DILUTING"}:
        code = f"story_{story.lower()}"
        if code not in codes:
            codes.append(code)
    if theme in {"WEAKENING", "BROKEN"} and "theme_weakening" not in codes:
        codes.append("theme_weakening")
    stop_distance = _number(plan.get("stop_distance_pct"))
    rr = _number(plan.get("reward_risk"))
    if stop_distance is not None and stop_distance > 10.0 and "stop_risk_high" not in codes:
        codes.append("stop_risk_high")
    if rr is not None and rr < 1.5 and "reward_risk_low" not in codes:
        codes.append("reward_risk_low")
    return list(dict.fromkeys(codes))


def _status(candidate: dict[str, Any], codes: list[str]) -> str:
    setup = str(candidate.get("setup") or "WATCH")
    gate = str(candidate.get("market_gate") or "NO_NEW")
    hard = {
        "earnings_window",
        "hard_block",
        "extended",
        "story_deteriorating",
        "story_margin_pressure",
        "story_diluting",
        "stop_risk_high",
        "reward_risk_low",
    }
    if hard.intersection(codes) or setup in {"AVOID", "EXTENDED"}:
        return "AVOID"
    tradeable = setup in {"PULLBACK", "PRE_BREAKOUT", "BREAKOUT"}
    if gate in {"ALLOW", "SELECTIVE"} and tradeable:
        return "ACTIONABLE"
    return "READY"


def _rank_components(candidate: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    leader = _number(candidate.get("score_leader"))
    base_candidate = _number(candidate.get("score_candidate"))
    theme = _theme_score(candidate)
    story = _number(candidate.get("story_score"))
    entry = _number(candidate.get("score_entry"))
    rr = _number(plan.get("reward_risk"))
    risk = _number(plan.get("stop_distance_pct"))
    expectancy, exp_meta = _expectancy_component(candidate)

    quality_parts = [(leader, .35), (base_candidate, .25), (theme, .20), (story, .20)]
    quality_available = [(value, weight) for value, weight in quality_parts if value is not None]
    quality = sum(value * weight for value, weight in quality_available) / sum(weight for _, weight in quality_available) if quality_available else None

    setup_bonus = {
        "BREAKOUT": 95.0,
        "PRE_BREAKOUT": 92.0,
        "PULLBACK": 90.0,
        "VOLUME_SURGE": 65.0,
        "WATCH": 50.0,
        "DEEP_PULLBACK": 35.0,
        "EXTENDED": 10.0,
        "AVOID": 0.0,
    }.get(str(candidate.get("setup") or "WATCH"), 50.0)
    rr_quality = _bounded((rr or 0.0) / 4.0 * 100.0) if rr is not None else None
    risk_quality = _bounded((1.0 - (risk or 0.0) / 12.0) * 100.0) if risk is not None else None
    trade_parts = [(entry, .50), (rr_quality, .20), (risk_quality, .15), (setup_bonus, .15)]
    trade_available = [(value, weight) for value, weight in trade_parts if value is not None]
    trade = sum(value * weight for value, weight in trade_available) / sum(weight for _, weight in trade_available) if trade_available else None

    final_parts = [(quality, .45), (trade, .35), (expectancy, .20)]
    final_available = [(value, weight) for value, weight in final_parts if value is not None]
    final = sum(value * weight for value, weight in final_available) / sum(weight for _, weight in final_available) if final_available else 0.0
    confidence_values = [
        _number(candidate.get("entry_confidence")),
        _number(candidate.get("story_confidence")),
        _number(candidate.get("leader_confidence")),
    ]
    confidence_values = [value / 100.0 if value > 1 else value for value in confidence_values if value is not None]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.5
    final *= 0.85 + 0.15 * min(max(confidence, 0.0), 1.0)
    return {
        "base_quality": quality,
        "trade_quality": trade,
        "expectancy_quality": expectancy,
        "expectancy_meta": exp_meta,
        "data_confidence": confidence,
        "final_rank_score": round(final, 2),
    }


def enrich_candidates(
    candidates: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
    price_asof: str | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        plan = _entry_plan(item)
        item.update(plan)
        codes = _reason_codes(item, plan)
        status = _status(item, codes)
        components = _rank_components(item, plan)
        item.update(components)
        item["decision_status"] = status
        item["decision_status_ja"] = STATUS_JA[status]
        item["setup_ja"] = SETUP_JA.get(str(item.get("setup")), str(item.get("setup") or "—"))
        item["reason_codes"] = codes
        item["warning_labels_ja"] = [WARNING_JA.get(code, code) for code in codes]

        positives: list[str] = []
        if item.get("theme_confirmed"):
            positives.append("強いテーマ内の候補")
        if str(item.get("setup")) in {"PULLBACK", "PRE_BREAKOUT", "BREAKOUT"}:
            positives.append(SETUP_JA.get(str(item.get("setup")), str(item.get("setup"))))
        rr = _number(item.get("reward_risk"))
        if rr is not None and rr >= 3.0:
            positives.append(f"参考R/R {rr:.1f}")
        item["positive_reasons_ja"] = positives[:3]
        item["reasons_ja"] = item["warning_labels_ja"][:3] or positives[:3] or ["監視条件は満たすが、明確な発注条件待ち"]

        external = item.get("external_data") or {}
        item["earnings_date"] = external.get("next_earnings_date") or external.get("earnings_date")
        item["days_to_earnings"] = external.get("days_to_earnings")
        item["data_freshness"] = {
            "generated_at": generated_at,
            "price_asof": price_asof,
            "external_fetched_at": external.get("fetched_at"),
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        output.append(item)

    status_order = {"ACTIONABLE": 0, "READY": 1, "AVOID": 2}
    output.sort(
        key=lambda item: (
            status_order.get(str(item.get("decision_status")), 9),
            -float(item.get("final_rank_score") or 0.0),
            str(item.get("ticker") or ""),
        )
    )
    for rank, item in enumerate(output, 1):
        item["decision_rank"] = rank
    return output


def partition_candidates(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        status: [item for item in candidates if item.get("decision_status") == status]
        for status in ("ACTIONABLE", "READY", "AVOID")
    }

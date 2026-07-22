from __future__ import annotations

from copy import deepcopy
from typing import Any

PORTFOLIO_REASON_JA = {
    "stop_or_hard_block": "損切り水準到達、または長期トレンド条件が崩れた",
    "second_pivot_missing_10d": "1st Pivot後10営業日以内に2nd Pivotが成立していない",
    "second_pivot_late_5d": "1st Pivot後5営業日を過ぎても2nd Pivotが成立していない",
    "second_pivot_watch_3d": "1st Pivot後3営業日。2nd Pivotへの進展を確認",
    "stop_near": "現在値が撤退水準に接近している",
    "fundamental_or_theme_weakness": "業績またはテーマの勢いが弱化している",
    "second_half_candidate": "2nd Entryの追加条件候補",
    "take_25pct_partial": "+25%到達。部分利確を検討",
    "trail_maintained": "トレーリング条件を維持",
}

PORTFOLIO_WARNING_JA = {
    "portfolio_input_missing": "Portfolio入力が未設定",
    "max_position_count_exceeded": "最大保有銘柄数を超過",
    "market_exposure_cap_exceeded": "地合い別の推奨露出上限を超過",
    "single_position_above_rule": "1銘柄の建玉が基準ロットを超過",
    "single_position_concentration": "単一銘柄への集中が大きい",
    "sector_concentration": "セクター集中が大きい",
    "theme_concentration": "テーマ集中が大きい",
    "portfolio_classification_missing": "セクター・テーマ未分類の保有が多い",
    "correlation_concentration": "保有銘柄間の相関が高い",
}

EXTERNAL_WARNING_JA = {
    "earnings_window": "決算前後3日以内",
    "eps_revisions_down": "EPS予想が下方修正",
    "guidance_cut": "会社ガイダンスが引き下げ",
    "large_insider_sale": "大口インサイダー売却",
}

QUALITY_WARNING_JA = {
    "qqq_missing": "QQQ価格データがない",
    "qqq_stale": "QQQ価格データが古い",
    "price_coverage_low": "価格データの銘柄カバレッジが低い",
    "candidate_count_zero": "候補銘柄が0件",
    "candidate_count_anomaly": "候補数が前回から大きく変化",
}

ACTION_JA = {
    "EXIT": "撤退",
    "REDUCE": "縮小",
    "ADD": "追加",
    "HOLD": "保有継続",
}


def _translate(code: Any, mapping: dict[str, str]) -> str:
    text = str(code or "")
    if text.startswith("external_stale:"):
        return f"外部データが古い：{text.split(':', 1)[1]}"
    return mapping.get(text, text)


def _translated_list(values: Any, mapping: dict[str, str]) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return [] if values in (None, "") else [_translate(values, mapping)]
    return [_translate(value, mapping) for value in values]


def _date_label(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else (text or "未確認")


def candidates_with_freshness(
    candidates: list[dict[str, Any]],
    *,
    generated_at: Any,
    price_asof: Any,
) -> list[dict[str, Any]]:
    """Reserve one visible reason line for price/build freshness."""
    result = deepcopy(candidates)
    label = f"データ鮮度：価格 {_date_label(price_asof)} / 生成 {_date_label(generated_at)}"
    for candidate in result:
        reasons = [
            str(reason)
            for reason in (candidate.get("reasons_ja") or [])
            if not str(reason).startswith("データ鮮度：")
        ]
        candidate["data_freshness_ja"] = label
        candidate["reasons_ja"] = reasons[:2] + [label]
    return result


def portfolio_for_display(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    raw_warnings = list(result.get("warnings") or [])
    result["warning_codes"] = raw_warnings
    result["warnings"] = _translated_list(raw_warnings, PORTFOLIO_WARNING_JA)
    for position in result.get("positions") or []:
        raw_reasons = list(position.get("reasons") or [])
        position["reason_codes"] = raw_reasons
        position["reasons"] = _translated_list(raw_reasons, PORTFOLIO_REASON_JA)
        action = str(position.get("action") or "")
        position["action_code"] = action
        position["action"] = ACTION_JA.get(action, action)
    return result


def external_for_display(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(records)
    for record in result:
        raw_warnings = list(record.get("warnings") or [])
        record["warning_codes"] = raw_warnings
        record["warnings"] = _translated_list(raw_warnings, EXTERNAL_WARNING_JA)
    return result


def quality_for_display(payload: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(payload)
    raw_warnings = list(result.get("warnings") or [])
    result["warning_codes"] = raw_warnings
    result["warnings"] = _translated_list(raw_warnings, QUALITY_WARNING_JA)
    return result

from __future__ import annotations

from typing import Any

MORNING_BRIEF_POLICY_VERSION = "1.0.0"


def _top(items: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (-(x.get(key) or 0), str(x.get("sector") or x.get("theme") or x.get("ticker") or "")))[:limit]


def build_morning_brief(
    market_state: dict[str, Any],
    sector_rotation: list[dict[str, Any]],
    theme_intelligence: list[dict[str, Any]],
    entry_candidates: list[dict[str, Any]],
    portfolio_doctor: dict[str, Any],
) -> dict[str, Any]:
    actionable = [x for x in entry_candidates if x.get("actionable")]
    avoid = [x for x in entry_candidates if not x.get("actionable") or x.get("warnings")]
    strong_sectors = _top(sector_rotation, "score_rotation")
    strong_themes = [x for x in _top(theme_intelligence, "score_theme", 8) if x.get("phase") in {"LEADING", "EMERGING", "IMPROVING"}][:5]
    leader_changes = []
    for theme in strong_themes:
        leaders = theme.get("leaders") or []
        if leaders:
            leader_changes.append({"theme": theme.get("theme"), "phase": theme.get("phase"), "leader": leaders[0]})
    regime = market_state.get("regime", "UNKNOWN")
    gate = market_state.get("entry_gate", "UNKNOWN")
    exposure = market_state.get("recommended_exposure_pct")
    headline = f"地合い {regime} / 新規 {gate}"
    if exposure is not None:
        headline += f" / 推奨露出 {exposure}%"
    market_comment = {
        "BLUE": "指数と内部の両方が強い。強いテーマの押し目・ブレイク前を優先。",
        "GREEN": "地合いは買えるが選別が必要。テーマ確認済みの高品質セットアップに限定。",
        "YELLOW": "内部悪化を警戒。新規を止め、既存ポジションのストップと集中を点検。",
        "RED": "防御優先。新規を避け、撤退・縮小候補から処理。",
    }.get(regime, "データ不足。無理に判断せず入力状態を確認。")
    portfolio_actions = {
        "exit": [x for x in portfolio_doctor.get("positions", []) if x.get("action") == "EXIT"],
        "reduce": [x for x in portfolio_doctor.get("positions", []) if x.get("action") == "REDUCE"],
        "add": [x for x in portfolio_doctor.get("positions", []) if x.get("action") == "ADD"],
    }
    jp_lines = [
        f"【AI分析】今日の米株：{headline}",
        market_comment,
    ]
    if strong_themes:
        jp_lines.append("強いテーマ：" + "、".join(str(x.get("theme")) for x in strong_themes[:4]))
    if actionable:
        jp_lines.append("発注候補：" + " ".join(str(x.get("ticker")) for x in actionable[:8]))
    if avoid:
        jp_lines.append("警戒候補：" + " ".join(str(x.get("ticker")) for x in avoid[:6]))
    x_post_ja = "\n".join(jp_lines)
    en_lines = [f"US Market AI Brief: {regime} / New entries {gate}", market_comment]
    if strong_themes:
        en_lines.append("Leading themes: " + ", ".join(str(x.get("theme")) for x in strong_themes[:4]))
    if actionable:
        en_lines.append("Actionable: " + " ".join(str(x.get("ticker")) for x in actionable[:8]))
    return {
        "headline": headline,
        "market_comment": market_comment,
        "market": market_state,
        "strong_sectors": strong_sectors,
        "strong_themes": strong_themes,
        "leader_changes": leader_changes,
        "actionable_candidates": actionable[:10],
        "avoid_candidates": avoid[:10],
        "portfolio_actions": portfolio_actions,
        "x_post_ja": x_post_ja,
        "x_post_en": "\n".join(en_lines),
    }

from __future__ import annotations

from typing import Any

MORNING_BRIEF_POLICY_VERSION = "1.0.0"


def build_morning_brief(market_state: dict[str, Any], sector_rotation: list[dict[str, Any]], themes: list[dict[str, Any]], entries: list[dict[str, Any]], portfolio: dict[str, Any]) -> dict[str, Any]:
    strong_sectors = sorted(sector_rotation, key=lambda x: (-(x.get("score_rotation") or 0), str(x.get("sector") or "")))[:5]
    strong_themes = [x for x in sorted(themes, key=lambda x: (-(x.get("score_theme") or 0), str(x.get("theme") or ""))) if x.get("phase") in {"LEADING", "EMERGING", "IMPROVING"}][:5]
    actionable = [x for x in entries if x.get("actionable")][:10]
    avoid = [x for x in entries if not x.get("actionable") or x.get("warnings")][:10]
    regime = market_state.get("regime", "UNKNOWN")
    gate = market_state.get("entry_gate", "UNKNOWN")
    exposure = market_state.get("recommended_exposure_pct")
    comment = {"BLUE": "指数と内部の両方が強い。強いテーマの押し目・ブレイク前を優先。", "GREEN": "買える地合いだが選別が必要。テーマ確認済みの高品質セットアップに限定。", "YELLOW": "内部悪化を警戒。新規を止め、既存ポジションのストップと集中を点検。", "RED": "防御優先。新規を避け、撤退・縮小候補から処理。"}.get(regime, "データ不足。無理に判断せず入力状態を確認。")
    headline = f"地合い {regime} / 新規 {gate}" + (f" / 推奨露出 {exposure}%" if exposure is not None else "")
    jp = [f"【AI分析】今日の米株：{headline}", comment]
    if strong_themes: jp.append("強いテーマ：" + "、".join(str(x.get("theme")) for x in strong_themes[:4]))
    if actionable: jp.append("発注候補：" + " ".join(str(x.get("ticker")) for x in actionable[:8]))
    if avoid: jp.append("警戒候補：" + " ".join(str(x.get("ticker")) for x in avoid[:6]))
    en = [f"US Market AI Brief: {regime} / New entries {gate}", comment]
    if strong_themes: en.append("Leading themes: " + ", ".join(str(x.get("theme")) for x in strong_themes[:4]))
    if actionable: en.append("Actionable: " + " ".join(str(x.get("ticker")) for x in actionable[:8]))
    return {"headline": headline, "market_comment": comment, "strong_sectors": strong_sectors, "strong_themes": strong_themes, "leader_changes": [{"theme": x.get("theme"), "phase": x.get("phase"), "leader": (x.get("leaders") or [None])[0]} for x in strong_themes], "actionable_candidates": actionable, "avoid_candidates": avoid, "portfolio_actions": {k.lower(): [x for x in portfolio.get("positions", []) if x.get("action") == k] for k in ("EXIT", "REDUCE", "ADD")}, "x_post_ja": "\n".join(jp), "x_post_en": "\n".join(en)}

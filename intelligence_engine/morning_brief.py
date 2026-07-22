from __future__ import annotations

from typing import Any

MORNING_BRIEF_POLICY_VERSION = "1.2.0"


def _top(items: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (-(item.get(key) or 0), str(item.get("theme") or item.get("sector") or "")))[:limit]


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.0f}%"


def _decision_status(item: dict[str, Any]) -> str:
    status = str(item.get("decision_status") or "").upper()
    if status in {"ACTIONABLE", "READY", "AVOID"}:
        return status
    if item.get("actionable"):
        return "ACTIONABLE"
    return "AVOID" if str(item.get("setup") or "").upper() in {"AVOID", "EXTENDED"} else "READY"


def build_morning_brief(
    market_state: dict[str, Any],
    sector_rotation: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    portfolio: dict[str, Any],
    *,
    leader_transitions: dict[str, Any] | None = None,
    expectancy: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    leader_transitions = leader_transitions or {}
    expectancy = expectancy or {}
    quality = quality or {}
    strong_sectors = _top(sector_rotation, "score_rotation")
    strong_themes = [
        item for item in _top(themes, "score_theme", 12)
        if item.get("phase") in {"LEADING", "ACCELERATING", "EMERGING", "IMPROVING"}
    ][:5]

    partitioned = {"ACTIONABLE": [], "READY": [], "AVOID": []}
    for item in entries:
        partitioned[_decision_status(item)].append(item)
    actionable = partitioned["ACTIONABLE"][:10]
    ready = partitioned["READY"][:12]
    avoid = partitioned["AVOID"][:10]

    regime = market_state.get("regime", "UNKNOWN")
    gate = market_state.get("entry_gate", "UNKNOWN")
    exposure = market_state.get("recommended_exposure_pct")
    breadth = market_state.get("breadth") or {}
    components = market_state.get("components") or {}
    qqq = market_state.get("qqq") or {}

    comments_ja = {
        "BLUE": "指数・内部Breadth・相対強度が揃う攻撃局面。強いテーマ内の押し目とブレイク前を優先。",
        "GREEN": "買える地合いだが選別が必要。テーマ確認済みで損切り幅の狭い候補に限定。",
        "YELLOW": "指数より市場内部が弱い。新規発注は止めるが、次の押し目・Pivot候補の準備は継続。",
        "RED": "防御優先。新規を避け、既存ポジションの撤退・縮小と集中解消から処理。",
    }
    comments_en = {
        "BLUE": "Index trend, breadth and relative strength are aligned. Prioritize pullbacks and pre-breakouts inside leading themes.",
        "GREEN": "The market is investable but selective. Focus on theme-confirmed names with tight, well-defined risk.",
        "YELLOW": "Market internals lag the indexes. Pause new orders while preparing the next pullback and pivot candidates.",
        "RED": "Defense first. Avoid new positions and address exits, reductions and concentration risk in current holdings.",
    }
    comment_ja = comments_ja.get(regime, "データ不足。無理に方向を決めず、入力状態と更新時刻を確認。")
    comment_en = comments_en.get(regime, "Data is insufficient. Avoid forcing a directional view and verify input freshness.")
    headline = f"地合い {regime} / 新規 {gate}" + (f" / 推奨露出 {exposure}%" if exposure is not None else "")

    pillars = [
        {"name": "指数トレンド", "value": components.get("index_trend"), "read": "QQQの移動平均と傾き"},
        {"name": "短期Breadth", "value": components.get("short_breadth"), "read": "10日線上の銘柄比率"},
        {"name": "中期Breadth", "value": components.get("medium_breadth"), "read": "50日線上の銘柄比率"},
        {"name": "相対強度", "value": components.get("relative_strength_breadth"), "read": "QQQを上回る銘柄の広がり"},
        {"name": "セクター参加", "value": components.get("sector_participation"), "read": "上位セクター内部の参加率"},
    ]
    pillar_text = " / ".join(f"{item['name']} {_pct(item['value'])}" for item in pillars)

    changes = leader_transitions.get("changes") or {}
    leader_new = []
    leader_drop = []
    for window in (63, 126, 189):
        section = changes.get(f"rs{window}") or {}
        leader_new.extend(section.get("new_top10") or [])
        leader_drop.extend(section.get("dropped_top10") or [])
    leader_new = list(dict.fromkeys(leader_new))[:8]
    leader_drop = list(dict.fromkeys(leader_drop))[:8]

    summary_lines = [
        comment_ja,
        pillar_text,
        f"発注可能 {len(actionable)} / 準備 {len(ready)} / 回避 {len(avoid)}",
    ]
    if strong_themes:
        summary_lines.append("主力テーマ：" + "、".join(str(item.get("theme_ja") or item.get("theme")) for item in strong_themes[:4]))
    if leader_new:
        summary_lines.append("RS上位へ新規：" + " ".join(leader_new))
    if leader_drop:
        summary_lines.append("RS上位から脱落：" + " ".join(leader_drop))
    if quality.get("status") not in {None, "PASS"}:
        summary_lines.append("データ品質警告あり：Dataタブを確認")

    jp = [f"【V38】今日の米株：{headline}", comment_ja]
    if strong_themes:
        jp.append("強いテーマ：" + "、".join(str(item.get("theme_ja") or item.get("theme")) for item in strong_themes[:4]))
    if actionable:
        jp.append("発注候補：" + " ".join(str(item.get("ticker")) for item in actionable[:8]))
    elif ready:
        jp.append("準備候補：" + " ".join(str(item.get("ticker")) for item in ready[:8]))
    if avoid:
        jp.append("回避候補：" + " ".join(str(item.get("ticker")) for item in avoid[:6]))

    exposure_en = f" / Suggested exposure {exposure}%" if exposure is not None else ""
    en = [f"V38 US Market Brief: {regime} / New entries {gate}{exposure_en}", comment_en]
    if strong_themes:
        en.append("Leading themes: " + ", ".join(str(item.get("theme")) for item in strong_themes[:4]))
    if actionable:
        en.append("Actionable: " + " ".join(str(item.get("ticker")) for item in actionable[:8]))
    elif ready:
        en.append("Ready: " + " ".join(str(item.get("ticker")) for item in ready[:8]))
    if avoid:
        en.append("Avoid: " + " ".join(str(item.get("ticker")) for item in avoid[:6]))

    return {
        "policy_version": MORNING_BRIEF_POLICY_VERSION,
        "headline": headline,
        "market_comment": comment_ja,
        "market_comment_en": comment_en,
        "summary_20s": "\n".join(summary_lines),
        "pillars": pillars,
        "qqq": qqq,
        "breadth": breadth,
        "strong_sectors": strong_sectors,
        "strong_themes": strong_themes,
        "leader_changes": [
            {"theme": item.get("theme"), "phase": item.get("phase"), "leader": (item.get("leaders") or [None])[0]}
            for item in strong_themes
        ],
        "leader_new_top10": leader_new,
        "leader_dropped_top10": leader_drop,
        "actionable_candidates": actionable,
        "ready_candidates": ready,
        "avoid_candidates": avoid,
        "expectancy_status": expectancy.get("status"),
        "expectancy_sample_count": expectancy.get("sample_count", 0),
        "portfolio_actions": {
            key.lower(): [item for item in portfolio.get("positions", []) if item.get("action") == key]
            for key in ("EXIT", "REDUCE", "ADD")
        },
        "x_post_ja": "\n".join(jp),
        "x_post_en": "\n".join(en),
    }

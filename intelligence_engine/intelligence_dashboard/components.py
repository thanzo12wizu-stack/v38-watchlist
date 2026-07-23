from __future__ import annotations

from typing import Any

from .formatting import esc, fmt, money, num, pct, present, status_ja


def value_tile(label: str, value: str, *, tone: str = "") -> str:
    return f'<div class="value-tile {tone}"><small>{esc(label)}</small><strong>{value}</strong></div>'


def candidate_card(item: dict, *, open_card: bool = False) -> str:
    status = str(item.get("decision_status") or ("ACTIONABLE" if item.get("actionable") else "READY"))
    reasons = item.get("reasons_ja") or item.get("warning_labels_ja") or item.get("warnings") or ["発注条件待ち"]
    reasons = [str(reason) for reason in reasons if present(reason)]
    reason_head = reasons[0] if reasons else "発注条件待ち"
    reasons_html = "".join(f"<li>{esc(reason)}</li>" for reason in reasons[:3])
    theme = item.get("theme_ja") or item.get("theme") or item.get("sector")
    setup = item.get("setup_ja") or item.get("setup") or "形待ち"
    earnings = item.get("earnings_date") or item.get("next_earnings_date")
    days = item.get("days_to_earnings")
    earnings_text = "未取得" if not earnings else f"{earnings}" + (f"（{days}日）" if days is not None else "")

    entry_low = money(item.get("entry_low"))
    entry_high = money(item.get("entry_high"))
    entry_range = "算出不可" if entry_low == "—" and entry_high == "—" else f"{entry_low}–{entry_high}"
    stop_text = money(item.get("stop_effective"))
    stop_distance = pct(item.get("stop_distance_pct"))
    if stop_text != "—" and stop_distance != "—":
        stop_text = f"{stop_text} / {stop_distance}"
    elif stop_text == "—":
        stop_text = "算出不可"
    rr_text = num(item.get("reward_risk"), 1)
    if rr_text == "—":
        rr_text = "未算出"
    score = num(item.get("final_rank_score") or item.get("score_entry"), 1)

    details = [
        ("現在値", item.get("price"), "money"),
        ("1st / 2nd", f"{money(item.get('entry_1'))} / {money(item.get('entry_2'))}", "html"),
        ("決算", earnings_text, "text"),
        ("Story", item.get("story_phase") or "DATA_INSUFFICIENT", "text"),
        ("ADR", item.get("adr_pct"), "pct_raw"),
        ("価格日", item.get("price_asof"), "text"),
    ]
    detail_rows = []
    for label, value, kind in details:
        if kind == "html":
            text = str(value)
            if text == "— / —":
                continue
        elif not present(value):
            continue
        else:
            text = fmt(value, kind)
        detail_rows.append(f"<span>{esc(label)}</span><b>{text}</b>")

    open_attr = " open" if open_card else ""
    return f"""
    <details class="candidate {status.lower()}" data-status="{status}" data-setup="{esc(item.get('setup'))}" data-theme="{esc(theme)}"{open_attr}>
      <summary>
        <div class="candidate-title"><div><b class="ticker">{esc(item.get('ticker'))}</b><span class="rank">#{esc(item.get('decision_rank'))}</span></div><span class="badge {status.lower()}">{esc(item.get('decision_status_ja') or status_ja(status))}</span></div>
        <div class="candidate-sub"><span>{esc(setup)}</span><span>{esc(theme)}</span><span>Score {score}</span></div>
        <div class="decision-grid">
          {value_tile('Entry', entry_range)}
          {value_tile('Stop', stop_text, tone='risk')}
          {value_tile('R/R', rr_text)}
        </div>
        <p class="reason-head">{esc(reason_head)}</p>
      </summary>
      <div class="candidate-detail">
        <div class="kv compact">{"".join(detail_rows) if detail_rows else '<span>補助データ</span><b>未取得</b>'}</div>
        <ul class="reasons">{reasons_html}</ul>
      </div>
    </details>"""


def candidate_section(title: str, items: list[dict], empty: str, limit: int, status: str) -> str:
    visible = items[:limit]
    content = "".join(
        candidate_card(item, open_card=index == 0 and status == "ACTIONABLE")
        for index, item in enumerate(visible)
    )
    if not content:
        content = f'<div class="empty-state"><b>{esc(empty)}</b><span>候補タブでは全銘柄を確認できます。</span></div>'
    more = ""
    if len(items) > limit:
        more = f'<button class="text-button" onclick="openCandidates(\'{status}\')">残り{len(items)-limit}件を見る →</button>'
    return f'<section class="section"><div class="section-head"><h2>{esc(title)}</h2><span>{len(items)}件</span></div><div class="candidate-list">{content}</div>{more}</section>'


def standard_cards(
    items: list[dict],
    title_key: str,
    fields: list[tuple[str, str, str]],
    limit: int = 20,
    *,
    hide_empty_items: bool = True,
) -> str:
    cards = []
    for item in items[:limit]:
        rows = []
        for key, label, kind in fields:
            value = item.get(key)
            if not present(value):
                continue
            text = fmt(value, kind)
            if text == "—":
                continue
            rows.append(f"<span>{esc(label)}</span><b>{text}</b>")
        if not rows and hide_empty_items:
            continue
        cards.append(
            f'<article class="item"><h3>{esc(item.get(title_key) or "Item")}</h3>'
            f'<div class="kv compact">{"".join(rows) if rows else "<span>状態</span><b>未取得</b>"}</div></article>'
        )
    return "".join(cards) or '<div class="empty-state"><b>表示できるデータなし</b><span>未取得項目はカード単位で非表示にしています。</span></div>'


def compact_table(headers: list[str], rows: list[list[str]], *, empty: str = "データなし") -> str:
    if not rows:
        return f'<div class="empty-state"><b>{esc(empty)}</b></div>'
    head = "".join(f"<th>{esc(value)}</th>" for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def phase_class(phase: Any) -> str:
    text = str(phase or "").upper()
    if text in {"LEADING", "ACCELERATING", "EMERGING"}:
        return "good"
    if text in {"WEAKENING", "BROKEN"}:
        return "bad"
    return "neutral"


def sector_rows(items: list[dict]) -> list[list[str]]:
    rows = []
    for item in items:
        leaders = item.get("leaders") or []
        leader_text = " ".join(str(value) for value in leaders[:4]) if isinstance(leaders, list) else str(leaders or "")
        phase = str(item.get("phase") or "—")
        rows.append([
            f'<b>{esc(item.get("sector"))}</b><small class="subline">{esc(leader_text)}</small>',
            f'<span class="phase {phase_class(phase)}">{esc(phase)}</span>',
            num(item.get("score_rotation"), 0),
            num(item.get("score_acceleration"), 0),
            pct(item.get("breadth_positive_63d"), decimal=True),
        ])
    return rows


def theme_rows(items: list[dict]) -> list[list[str]]:
    rows = []
    for item in items:
        leaders = item.get("leaders") or []
        leader_text = " ".join(str(value) for value in leaders[:4]) if isinstance(leaders, list) else str(leaders or "")
        phase = str(item.get("phase") or "—")
        rows.append([
            f'<b>{esc(item.get("theme_ja") or item.get("theme"))}</b><small class="subline">{esc(leader_text)}</small>',
            f'<span class="phase {phase_class(phase)}">{esc(phase)}</span>',
            num(item.get("score_theme"), 0),
            pct(item.get("breadth_positive"), decimal=True),
        ])
    return rows


def meaningful_external(record: dict) -> bool:
    keys = (
        "next_earnings_date",
        "earnings_date",
        "days_to_earnings",
        "eps_revision_30d_pct",
        "guidance_direction",
        "event_type",
        "warnings",
    )
    return any(present(record.get(key)) for key in keys)

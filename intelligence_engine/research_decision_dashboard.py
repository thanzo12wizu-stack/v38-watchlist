from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .research_storage import load_dataset

STATUS_JA = {"ACTIONABLE": "買える", "READY": "待つ", "AVOID": "避ける"}
ACTION_JA = {"ADD": "追加", "HOLD": "保有", "REDUCE": "縮小", "EXIT": "撤退"}
SEVERITY_JA = {"CRITICAL": "重要", "HIGH": "高", "MEDIUM": "中", "LOW": "低"}
CONSISTENCY_JA = {
    "CONFIRMED": "8年・5年一致",
    "MIXED": "3年のみ不一致",
    "CONFLICT": "8年・5年逆方向",
    "PRIMARY_ONLY": "8年のみ",
    "RECENT_ONLY": "最近のみ",
    "UNAVAILABLE": "未確定",
}
BLOCK_JA = {
    "LONG_TREND_BROKEN": "長期トレンド崩れ",
    "STOP_TOO_WIDE": "損切り幅過大",
    "REWARD_RISK_LOW": "上値余地不足",
    "FUNDAMENTAL_DETERIORATION": "財務悪化",
    "LEADERSHIP_RISK": "RS失速",
    "EARNINGS_WINDOW": "決算前後3日",
}
REASON_JA = {
    "research_hard_exit": "研究Hard Block",
    "research_deterioration": "財務またはRS悪化",
    "second_entry_supported": "2nd Entryを複合条件が支持",
    "research_thesis_intact": "研究上の保有根拠を維持",
    "expectancy_window_conflict": "8年と5年の期待値が不一致",
    "partial_profit_due": "+25%部分利確候補",
    "research_candidate_not_available": "研究候補外。価格ルールを優先",
}


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _esc(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, list):
        return html.escape(" / ".join(str(item) for item in value)) if value else "—"
    return html.escape(str(value))


def _num(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
        if pd.isna(number):
            return "—"
        return f"{number:,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any, *, decimal: bool = False, signed: bool = False, digits: int = 1) -> str:
    try:
        number = float(value)
        if pd.isna(number):
            return "—"
        if decimal:
            number *= 100
        prefix = "+" if signed and number > 0 else ""
        return f"{prefix}{number:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _money(value: Any) -> str:
    try:
        number = float(value)
        return "—" if pd.isna(number) else f"${number:,.2f}"
    except (TypeError, ValueError):
        return "—"


def _kv(rows: list[tuple[str, str]]) -> str:
    return '<div class="kv">' + "".join(
        f"<span>{_esc(label)}</span><b>{value}</b>" for label, value in rows
    ) + "</div>"


def _bar(label: str, value: Any) -> str:
    try:
        score = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        score = 0.0
    return (
        f'<div class="bar"><span>{_esc(label)}</span><i><b style="width:{score:.1f}%"></b></i>'
        f'<em>{_num(value,0)}</em></div>'
    )


def _latest(rankings: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if rankings.empty or "date" not in rankings:
        return pd.DataFrame(), "—"
    work = rankings.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    latest_date = work["date"].max()
    if pd.isna(latest_date):
        return pd.DataFrame(), "—"
    current = work[work["date"] == latest_date].copy()
    if "research_rank" in current:
        current = current.sort_values(["research_rank", "ticker"])
    return current, pd.Timestamp(latest_date).date().isoformat()


def _candidate_reasons(row: pd.Series) -> list[str]:
    blocks = row.get("hard_blocks") if isinstance(row.get("hard_blocks"), list) else []
    if blocks:
        return [BLOCK_JA.get(str(code), str(code)) for code in blocks[:3]]
    reasons: list[str] = []
    phase = str(row.get("financial_phase") or "")
    rs = str(row.get("rs_archetype") or "")
    entry = str(row.get("entry_state") or "")
    consistency = str(row.get("expectancy_consistency") or "UNAVAILABLE")
    if phase in {"ACCELERATING", "COMPOUNDING", "INFLECTING"}:
        reasons.append(f"財務 {phase}")
    if rs in {"NEW_LEADER", "ACCELERATING_LEADER", "ESTABLISHED_LEADER", "REACCELERATING"}:
        reasons.append(f"RS {rs}")
    if entry in {"READY", "TRIGGERED"}:
        reasons.append(f"Entry {entry}")
    if consistency == "CONFIRMED":
        reasons.append("期待値は8年・5年で同方向")
    elif consistency in {"CONFLICT", "MIXED"}:
        reasons.append(CONSISTENCY_JA[consistency])
    return (reasons or ["候補条件は満たすが追加根拠待ち"])[:3]


def _candidate_card(row: pd.Series) -> str:
    ticker = str(row.get("ticker") or "")
    status = str(row.get("decision_status") or "READY")
    reasons = "".join(f"<li>{_esc(item)}</li>" for item in _candidate_reasons(row))
    blocks = row.get("hard_blocks") if isinstance(row.get("hard_blocks"), list) else []
    bars = "".join(
        _bar(label, row.get(field))
        for label, field in (
            ("財務", "fundamental_quality"),
            ("変化", "fundamental_change"),
            ("RS", "leadership_quality"),
            ("Entry", "entry_quality"),
            ("Risk", "risk_fit"),
        )
    )
    quick = _kv(
        [
            ("現在値", _money(row.get("price"))),
            ("Pivot", _money(row.get("pivot_20d"))),
            ("Stop幅", _pct(row.get("stop_risk_pct"))),
            ("R/R", _num(row.get("reward_risk_raw"), 1)),
            ("10日期待値 8年", _pct(row.get("expected_edge_10d_8y"), decimal=True, signed=True)),
            ("標本", _num(row.get("expectancy_samples"), 0)),
        ]
    )
    details = _kv(
        [
            ("EPS YoY", _pct(row.get("eps_yoy"), decimal=True, signed=True)),
            ("売上 YoY", _pct(row.get("revenue_yoy"), decimal=True, signed=True)),
            ("EPS加速", _pct(row.get("eps_acceleration"), decimal=True, signed=True)),
            ("営業利益率変化", _pct(row.get("operating_margin_delta"), decimal=True, signed=True)),
            ("FCF YoY", _pct(row.get("free_cash_flow_yoy"), decimal=True, signed=True)),
            ("株式数 YoY", _pct(row.get("shares_yoy"), decimal=True, signed=True)),
            ("RS63", _num(row.get("pct_rs_raw_63"), 0)),
            ("RS126", _num(row.get("pct_rs_raw_126"), 0)),
            ("RS189", _num(row.get("pct_rs_raw_189"), 0)),
            ("10年期待値", _pct(row.get("expected_edge_10d_10y"), decimal=True, signed=True)),
            ("5年期待値", _pct(row.get("expected_edge_10d_5y"), decimal=True, signed=True)),
            ("3年期待値", _pct(row.get("expected_edge_10d_3y"), decimal=True, signed=True)),
            ("期待値判定", _esc(row.get("expectancy_status"))),
            ("期間一貫性", _esc(CONSISTENCY_JA.get(str(row.get("expectancy_consistency")), row.get("expectancy_consistency")))),
            ("Confidence", _pct(row.get("research_confidence"), decimal=True)),
            ("Hard Block", _esc([BLOCK_JA.get(str(code), str(code)) for code in blocks] or ["なし"])),
        ]
    )
    tag_values = (
        row.get("candidate_archetype"),
        row.get("financial_phase"),
        row.get("rs_archetype"),
        row.get("setup"),
    )
    tags = "".join(
        f"<span>{_esc(value)}</span>" for value in tag_values if value
    )
    search_text = " ".join(str(value or "") for value in (ticker, *tag_values))
    return f"""
    <article class="candidate {status.lower()}" data-status="{_esc(status)}"
      data-archetype="{_esc(row.get('candidate_archetype'))}" data-search="{_esc(search_text)}">
      <div class="head"><div><b class="ticker">{_esc(ticker)}</b><span class="rank">#{_num(row.get('research_rank'),0)}</span></div>
      <span class="badge {status.lower()}">{_esc(STATUS_JA.get(status,status))}</span></div>
      <div class="tags">{tags}</div><div class="score"><strong>{_num(row.get('composite_rank_score'),1)}</strong><small>総合</small>
      <button onclick="copyTicker('{_esc(ticker)}')">コピー</button></div><ul>{reasons}</ul>{quick}<div class="bars">{bars}</div>
      <details><summary>根拠を展開</summary>{details}</details>
    </article>"""


def _event_cards(changes: dict[str, Any]) -> str:
    events = changes.get("events") or []
    if not events:
        return '<div class="empty">比較可能な前回データを蓄積中</div>'
    return "".join(
        f'''<article class="event {str(item.get('severity') or 'LOW').lower()}">
        <div class="head"><b>{_esc(item.get('ticker'))}</b><span class="sev">{_esc(SEVERITY_JA.get(str(item.get('severity')),item.get('severity')))}</span></div>
        <h3>{_esc(item.get('title'))}</h3><p>{_esc(item.get('detail'))}</p>
        <small>#{_num(item.get('research_rank'),0)} / {_esc(item.get('candidate_archetype'))} / {_esc(item.get('financial_phase'))} / {_esc(item.get('rs_archetype'))}</small>
        </article>'''
        for item in events[:60]
    )


def _portfolio_cards(overlay: dict[str, Any]) -> str:
    rows = overlay.get("positions") or []
    if not rows:
        return '<div class="empty">Portfolio入力なし</div>'
    cards: list[str] = []
    for row in rows:
        action = str(row.get("action") or "HOLD")
        reasons = "".join(
            f"<li>{_esc(REASON_JA.get(str(reason),reason))}</li>"
            for reason in row.get("reasons") or []
        )
        cards.append(
            f'''<article class="portfolio {action.lower()}"><div class="head"><b class="ticker">{_esc(row.get('ticker'))}</b>
            <span class="badge {action.lower()}">{_esc(ACTION_JA.get(action,action))}</span></div>
            <div class="tags"><span>Research {_esc(row.get('research_status'))}</span><span>#{_num(row.get('research_rank'),0)}</span>
            <span>{_esc(row.get('candidate_archetype'))}</span></div>{_kv([('現在値',_money(row.get('price'))),('建値',_money(row.get('cost_basis'))),('損益',_pct(row.get('gain_pct'))),('Stop幅',_pct(row.get('stop_risk_pct'))),('8年期待値',_pct(row.get('expected_edge_10d_8y'),decimal=True,signed=True)),('Entry段階',_num(row.get('entry_stage'),0))])}
            <ul>{reasons}</ul></article>'''
        )
    return "".join(cards)


def _window_rows(expectancy: dict[str, Any], years: int) -> list[dict[str, Any]]:
    window = next(
        (
            item
            for item in expectancy.get("windows") or []
            if int(item.get("window_years") or 0) == years
        ),
        {},
    )
    rows = [
        row
        for row in window.get("groups") or []
        if row.get("group_type") == "archetype_setup"
        and int(row.get("horizon") or 0) == 10
    ]
    return sorted(
        rows,
        key=lambda row: (
            -(row.get("mean_excess_return") or -999),
            -int(row.get("samples") or 0),
        ),
    )


def _expectancy_table(expectancy: dict[str, Any]) -> str:
    by_window = {years: _window_rows(expectancy, years) for years in (8, 5, 3)}
    keys: list[tuple[str, str]] = []
    for rows in by_window.values():
        for row in rows:
            key = (str(row.get("candidate_archetype")), str(row.get("setup")))
            if key not in keys:
                keys.append(key)
    body: list[str] = []
    for archetype, setup in keys[:50]:
        cells: list[str] = []
        for years in (8, 5, 3):
            match = next(
                (
                    row
                    for row in by_window[years]
                    if str(row.get("candidate_archetype")) == archetype
                    and str(row.get("setup")) == setup
                ),
                None,
            )
            cells.append(
                f'<td><b>{_pct(match.get("mean_excess_return"),decimal=True,signed=True)}</b><small>n={_num(match.get("samples"),0)} / {_esc(match.get("qualification"))}</small></td>'
                if match
                else "<td>—</td>"
            )
        body.append(
            f'<tr><th>{_esc(archetype)}<small>{_esc(setup)}</small></th>{"".join(cells)}</tr>'
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>型 × Setup</th><th>8年</th><th>5年</th><th>3年</th></tr></thead><tbody>'
        + "".join(body)
        + "</tbody></table></div>"
    )


def _health_view(
    health: dict[str, Any], manifest: dict[str, Any], expectancy: dict[str, Any]
) -> str:
    status = str(health.get("status") or "NO_DATA")
    warnings = (
        "".join(f"<li>{_esc(item)}</li>" for item in health.get("warnings") or [])
        or "<li>重大警告なし</li>"
    )
    rows = health.get("groups") or []
    conflict_rows = "".join(
        f'<tr><th>{_esc(row.get("candidate_archetype"))}<small>{_esc(row.get("setup"))}</small></th><td>{_pct(row.get("edge_8y"),decimal=True,signed=True)}</td><td>{_pct(row.get("edge_5y"),decimal=True,signed=True)}</td><td>{"不一致" if row.get("conflict") else "一致"}</td><td>{_num(row.get("samples_8y"),0)}</td></tr>'
        for row in rows[:40]
    )
    metrics = _kv(
        [
            ("Model Health", _esc(status)),
            ("保持年", _esc(health.get("retained_years"))),
            ("標本", _num(health.get("retained_sample_count"), 0)),
            ("QUALIFIED", _num(health.get("qualified_groups"), 0)),
            ("PROMISING", _num(health.get("promising_groups"), 0)),
            ("期間不一致率", _pct(health.get("conflict_rate"), decimal=True)),
            ("WFプラス率", _pct(health.get("walk_forward_positive_rate"), decimal=True)),
            ("生成", _esc(manifest.get("generated_at"))),
            ("比較窓", _esc(expectancy.get("comparison_windows_years") or [10, 8, 5, 3])),
        ]
    )
    return (
        f'<div class="health {status.lower()}">{metrics}<h3>警告</h3><ul>{warnings}</ul></div>'
        f'<div class="table-wrap"><table><thead><tr><th>型 × Setup</th><th>8年</th><th>5年</th><th>判定</th><th>n</th></tr></thead><tbody>{conflict_rows}</tbody></table></div>'
    )


def build_html(root: Path) -> str:
    manifest = _read(root / "manifest.json", {})
    expectancy = _read(root / "expectancy.json", {})
    changes = _read(root / "changes.json", {})
    health = _read(root / "model_health.json", {})
    overlay = _read(root / "portfolio_overlay.json", {})
    current, latest_date = _latest(load_dataset(root, "rankings"))
    counts = (
        current.get("decision_status", pd.Series(dtype=str)).value_counts()
        if not current.empty
        else pd.Series(dtype=int)
    )
    candidate_cards = (
        "".join(_candidate_card(row) for _, row in current.head(100).iterrows())
        or '<div class="empty">研究候補を生成中</div>'
    )
    archetypes = sorted(
        str(item)
        for item in current.get("candidate_archetype", pd.Series(dtype=str))
        .dropna()
        .unique()
    )
    options = "".join(
        f'<option value="{_esc(item)}">{_esc(item)}</option>' for item in archetypes
    )
    today = f'''<div class="hero"><div><small>研究日</small><strong>{_esc(latest_date)}</strong></div><div><small>買える</small><strong>{int(counts.get('ACTIONABLE',0))}</strong></div><div><small>待つ</small><strong>{int(counts.get('READY',0))}</strong></div><div><small>避ける</small><strong>{int(counts.get('AVOID',0))}</strong></div><div><small>Model</small><strong>{_esc(health.get('status') or '—')}</strong></div></div><section><div class="filters"><select id="statusFilter"><option value="ALL">全判断</option><option value="ACTIONABLE">買える</option><option value="READY">待つ</option><option value="AVOID">避ける</option></select><select id="archetypeFilter"><option value="ALL">全タイプ</option>{options}</select><input id="search" placeholder="Ticker検索"><button onclick="resetFilters()">解除</button></div><div class="grid">{candidate_cards}</div></section>'''
    change_view = f'<section><div class="section-title"><h2>前回からの変化</h2><small>{_esc(changes.get("prior_date"))} → {_esc(changes.get("current_date"))} / {int(changes.get("event_count") or 0)}件</small></div><div class="event-grid">{_event_cards(changes)}</div></section>'
    portfolio_view = f'<section><div class="section-title"><h2>Portfolio Research Overlay</h2><small>価格ルールを主、研究を補助判定として使用</small></div><div class="portfolio-grid">{_portfolio_cards(overlay)}</div></section>'
    expectancy_view = (
        '<section><div class="section-title"><h2>型別10日期待値</h2><small>8年を標準、5年を最近、3年を現在レジーム確認</small></div>'
        + _expectancy_table(expectancy)
        + "</section>"
    )
    health_view = (
        '<section><div class="section-title"><h2>Model Health</h2><small>標本・期間不一致・Walk-forward・集中を監視</small></div>'
        + _health_view(health, manifest, expectancy)
        + "</section>"
    )
    tabs = [
        ("today", "候補"),
        ("changes", "変化"),
        ("portfolio", "保有"),
        ("expectancy", "期待値"),
        ("health", "Health"),
    ]
    buttons = "".join(
        f'<button data-tab="{key}" class="{"active" if index == 0 else ""}">{label}</button>'
        for index, (key, label) in enumerate(tabs)
    )
    views = {
        "today": today,
        "changes": change_view,
        "portfolio": portfolio_view,
        "expectancy": expectancy_view,
        "health": health_view,
    }
    view_html = "".join(
        f'<main id="{key}" class="view {"active" if index == 0 else ""}">{views[key]}</main>'
        for index, (key, _) in enumerate(tabs)
    )
    css = ":root{color-scheme:dark;--bg:#080b10;--panel:#111720;--panel2:#0c1118;--line:#263243;--text:#f2f5f9;--muted:#8d9aad;--blue:#75aaff;--green:#50d38a;--red:#ff7474;--yellow:#efc15a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.35}.wrap{max-width:1320px;margin:auto;padding:11px}.top{display:flex;justify-content:space-between;align-items:flex-end;gap:8px}.top h1{margin:0;font-size:21px}.muted,small{color:var(--muted)}.back{color:var(--blue);text-decoration:none;font-size:12px}.tabs{display:flex;gap:5px;overflow:auto;position:sticky;top:0;z-index:5;background:rgba(8,11,16,.97);padding:8px 0}.tabs button,.filters button,.filters select,.filters input{min-height:38px;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:999px;padding:7px 12px;white-space:nowrap}.tabs button.active{color:var(--blue);border-color:var(--blue)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:7px}.hero>div,section{background:var(--panel);border:1px solid var(--line);border-radius:12px}.hero>div{padding:9px}.hero strong{display:block;font-size:18px}section{padding:9px;margin-bottom:8px}.section-title{display:flex;justify-content:space-between;gap:8px;align-items:end;margin-bottom:8px}.section-title h2{font-size:15px;margin:0}.filters{display:flex;gap:5px;overflow:auto;margin-bottom:8px}.filters input{border-radius:8px;min-width:130px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.candidate,.event,.portfolio,.health{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:9px}.candidate.actionable{border-color:rgba(80,211,138,.55)}.candidate.avoid{opacity:.8}.head,.score{display:flex;align-items:center;justify-content:space-between;gap:6px}.ticker{font-size:18px;color:var(--blue)}.rank{font-size:10px;color:var(--muted);margin-left:5px}.badge,.sev{font-size:10px;font-weight:800;padding:3px 7px;border-radius:99px}.badge.actionable,.badge.add{color:var(--green);background:rgba(80,211,138,.14)}.badge.ready,.badge.hold{color:var(--blue);background:rgba(117,170,255,.14)}.badge.avoid,.badge.exit{color:var(--red);background:rgba(255,116,116,.14)}.badge.reduce{color:var(--yellow);background:rgba(239,193,90,.14)}.tags{display:flex;flex-wrap:wrap;gap:3px;margin:4px 0}.tags span{font-size:9px;color:var(--muted);border:1px solid var(--line);border-radius:99px;padding:2px 5px}.score{justify-content:flex-start}.score strong{font-size:22px}.score button{margin-left:auto;border:0;background:none;color:var(--blue)}ul{padding-left:17px;margin:6px 0;font-size:10.5px}.kv{display:grid;grid-template-columns:minmax(90px,.9fr) minmax(0,1.1fr);gap:4px 7px;font-size:10.5px}.kv span{color:var(--muted)}.kv b{text-align:right;overflow-wrap:anywhere}.bars{margin-top:7px}.bar{display:grid;grid-template-columns:42px 1fr 25px;gap:5px;align-items:center;font-size:9px;margin:3px 0}.bar span,.bar em{color:var(--muted);font-style:normal}.bar i{height:4px;background:#1d2734;border-radius:99px;overflow:hidden}.bar i b{display:block;height:100%;background:var(--blue)}details{border-top:1px solid var(--line);margin-top:7px;padding-top:6px}summary{color:var(--blue);font-size:10px;cursor:pointer}.event-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.event h3{font-size:12px;margin:5px 0}.event p{font-size:10.5px;margin:4px 0}.event.critical{border-color:var(--red)}.event.high{border-color:rgba(255,116,116,.45)}.portfolio-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:10.5px}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child{text-align:left}th small,td small{display:block}.health{max-width:520px;margin-bottom:8px}.health.fail{border-color:var(--red)}.health.warn{border-color:var(--yellow)}.health.pass{border-color:var(--green)}.empty{color:var(--muted);padding:16px}@media(max-width:900px){.grid,.portfolio-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.event-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.hero{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:580px){.wrap{padding:8px}.top{align-items:flex-start;flex-direction:column}.tabs{margin:0 -8px;padding:8px}.grid,.portfolio-grid,.event-grid{grid-template-columns:1fr}.hero{grid-template-columns:1fr 1fr}.section-title{align-items:flex-start;flex-direction:column}.candidate,.portfolio{padding:9px}}"
    script = "document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});function filterCards(){const s=document.getElementById('statusFilter').value,a=document.getElementById('archetypeFilter').value,q=document.getElementById('search').value.toUpperCase();document.querySelectorAll('.candidate').forEach(c=>{c.style.display=(s==='ALL'||c.dataset.status===s)&&(a==='ALL'||c.dataset.archetype===a)&&(!q||c.dataset.search.toUpperCase().includes(q))?'':'none'})}['statusFilter','archetypeFilter','search'].forEach(id=>document.getElementById(id)?.addEventListener(id==='search'?'input':'change',filterCards));function resetFilters(){document.getElementById('statusFilter').value='ALL';document.getElementById('archetypeFilter').value='ALL';document.getElementById('search').value='';filterCards()}function copyTicker(t){navigator.clipboard.writeText(t)}"
    generated = manifest.get("generated_at") or "—"
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>V38 Research Decision</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>Research Decision</h1><div class="muted">財務 × RS × Entry × 実測期待値 / {_esc(generated)}</div></div><a class="back" href="intelligence-dashboard.html">← Intelligence</a></header><nav class="tabs">{buttons}</nav>{view_html}</div><script>{script}</script></body></html>'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence/research")
    parser.add_argument("--output", default="research-dashboard.html")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(Path(args.root)), encoding="utf-8")


if __name__ == "__main__":
    main()

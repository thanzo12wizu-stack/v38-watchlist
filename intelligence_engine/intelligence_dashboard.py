from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (list, tuple, set)):
        return html.escape(" / ".join(str(item) for item in value)) if value else "—"
    if isinstance(value, dict):
        return html.escape(" / ".join(f"{key}:{item}" for key, item in value.items())) if value else "—"
    return html.escape(str(value))


def _num(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any, digits: int = 1, *, decimal: bool = False, signed: bool = False) -> str:
    try:
        number = float(value)
        if decimal:
            number *= 100
        sign = "+" if signed and number > 0 else ""
        return f"{sign}{number:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _unwrap(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return value
    wrappers = {
        "sector_rotation": ("sectors",),
        "theme_intelligence": ("themes",),
        "entry_candidates": ("candidates",),
        "external_data": ("records",),
        "leader_board": ("boards",),
    }
    for candidate in wrappers.get(key, ()):
        if candidate in value:
            return value.get(candidate) or []
    return value


def load_payload(input_path: Path) -> dict:
    combined = _read_json(input_path)
    if isinstance(combined, dict):
        combined.setdefault("dashboard_input_status", "INDEX")
        return combined
    root = input_path.parent
    payload: dict[str, Any] = {
        "dashboard_input_status": "BOOTSTRAP_NO_INDEX",
        "manifest": {"dashboard_input_status": "BOOTSTRAP_NO_INDEX"},
    }
    file_map = {
        "market_state": "market_state.json",
        "sector_rotation": "sector_rotation.json",
        "theme_intelligence": "theme_intelligence.json",
        "portfolio_doctor": "portfolio_doctor.json",
        "morning_brief": "morning_brief.json",
        "expectancy_rankings": "expectancy_rankings.json",
        "robust_expectancy": "robust_expectancy.json",
        "leader_transitions": "leader_transitions.json",
        "leader_board": "leader_board.json",
        "data_quality": "data_quality.json",
        "entry_candidates": "entry_candidates.json",
        "external_data": "external_data.json",
    }
    for key, filename in file_map.items():
        value = _read_json(root / filename)
        if value is not None:
            payload[key] = _unwrap(value, key)
            if isinstance(value, dict) and not payload.get("generated_at"):
                payload["generated_at"] = value.get("generated_at")
    payload["manifest"]["bootstrap_sections"] = [
        key for key in payload if key not in {"dashboard_input_status", "manifest", "generated_at"}
    ]
    return payload


def _as_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _partition(candidates: list[dict]) -> dict[str, list[dict]]:
    output = {"ACTIONABLE": [], "READY": [], "AVOID": []}
    for item in candidates:
        status = item.get("decision_status")
        if status not in output:
            status = "ACTIONABLE" if item.get("actionable") else "READY"
        output[status].append(item)
    for status in output:
        output[status].sort(key=lambda item: (-float(item.get("final_rank_score") or item.get("score_entry") or 0), str(item.get("ticker") or "")))
    return output


def _candidate_card(item: dict) -> str:
    status = str(item.get("decision_status") or ("ACTIONABLE" if item.get("actionable") else "READY"))
    reasons = item.get("reasons_ja") or item.get("warning_labels_ja") or item.get("warnings") or ["発注条件待ち"]
    reasons_html = "".join(f"<li>{_esc(reason)}</li>" for reason in reasons[:3])
    theme = item.get("theme_ja") or item.get("theme")
    earnings = item.get("earnings_date")
    days = item.get("days_to_earnings")
    earnings_text = "未確認" if not earnings else f"{earnings}" + (f"（{days}日）" if days is not None else "")
    entry_range = f"{_money(item.get('entry_low'))}–{_money(item.get('entry_high'))}"
    return f"""
    <article class="candidate {status.lower()}" data-status="{status}" data-setup="{_esc(item.get('setup'))}" data-theme="{_esc(theme)}">
      <div class="candidate-head"><div><b class="ticker">{_esc(item.get('ticker'))}</b><span class="rank">#{_esc(item.get('decision_rank'))}</span></div><span class="badge {status.lower()}">{_esc(item.get('decision_status_ja') or status)}</span></div>
      <div class="candidate-sub"><span>{_esc(item.get('setup_ja') or item.get('setup'))}</span><span>{_esc(theme)}</span><span>Score {_num(item.get('final_rank_score'),1)}</span></div>
      <div class="kv"><span>現在値</span><b>{_money(item.get('price'))}</b><span>Entry帯</span><b>{entry_range}</b><span>1st / 2nd</span><b>{_money(item.get('entry_1'))} / {_money(item.get('entry_2'))}</b><span>Stop</span><b>{_money(item.get('stop_effective'))}（{_pct(item.get('stop_distance_pct'))}）</b><span>参考R/R</span><b>{_num(item.get('reward_risk'),1)}</b><span>決算</span><b>{_esc(earnings_text)}</b><span>Story</span><b>{_esc(item.get('story_phase') or 'DATA_INSUFFICIENT')}</b></div>
      <ul class="reasons">{reasons_html}</ul>
    </article>"""


def _candidate_section(title: str, items: list[dict], empty: str, limit: int = 12) -> str:
    content = "".join(_candidate_card(item) for item in items[:limit]) or f'<div class="empty">{_esc(empty)}</div>'
    return f'<section class="section"><div class="section-head"><h2>{_esc(title)}</h2><span>{len(items)}件</span></div><div class="candidate-grid">{content}</div></section>'


def _standard_cards(items: list[dict], title_key: str, fields: list[tuple[str, str, str]], limit: int = 20) -> str:
    if not items:
        return '<div class="empty">データなし</div>'
    cards = []
    for item in items[:limit]:
        rows = []
        for key, label, kind in fields:
            value = item.get(key)
            if kind == "pct": text = _pct(value, decimal=True)
            elif kind == "pct_raw": text = _pct(value)
            elif kind == "money": text = _money(value)
            elif kind == "num": text = _num(value)
            else: text = _esc(value)
            rows.append(f"<span>{_esc(label)}</span><b>{text}</b>")
        cards.append(f'<article class="item"><h3>{_esc(item.get(title_key) or "Item")}</h3><div class="kv">{"".join(rows)}</div></article>')
    return "".join(cards)


def _friendly_status(status: Any) -> str:
    mapping = {
        "NO_SETTLED_OBSERVATIONS": "実運用の5・10・21日後結果を蓄積中。履歴バックテストは上段に表示済み。",
        "NO_PRIOR_HISTORY": "前日Snapshot未蓄積。価格履歴ベースの交代判定を使用。",
        "PRICE_HISTORY": "価格履歴5営業日比較",
        "OK": "稼働中",
        "PASS": "正常",
        "WARN": "警告あり",
    }
    return mapping.get(str(status), str(status or "—"))


def build_html(payload: dict) -> str:
    market = payload.get("market_state") or {}
    brief = payload.get("morning_brief") or {}
    candidates = _as_list(payload.get("entry_candidates"))
    partitions = _partition(candidates)
    themes = _as_list(payload.get("theme_intelligence"))
    sectors = _as_list(payload.get("sector_rotation"))
    portfolio = payload.get("portfolio_doctor") or {}
    positions = _as_list(portfolio.get("positions"))
    transitions = payload.get("leader_transitions") or {}
    boards = payload.get("leader_board") or transitions.get("leader_board") or {}
    quality = payload.get("data_quality") or {}
    expectancy = payload.get("expectancy_rankings") or {}
    robust = payload.get("robust_expectancy") or {}
    external = _as_list(payload.get("external_data"))
    manifest = payload.get("manifest") or {}
    generated = payload.get("generated_at") or manifest.get("generated_at") or "—"
    input_status = payload.get("dashboard_input_status") or manifest.get("dashboard_input_status") or "INDEX"

    summary = brief.get("summary_20s") or brief.get("market_comment") or "データを確認中"
    pillars = _as_list(brief.get("pillars"))
    pillar_cards = _standard_cards(pillars, "name", [("value", "状態", "pct"), ("read", "意味", "text")], 8)
    qqq = market.get("qqq") or {}
    breadth = market.get("breadth") or {}

    daily = f"""
      <div class="hero">
        <div class="metric"><small>Market Regime</small><strong>{_esc(market.get('regime'))}</strong></div>
        <div class="metric"><small>Entry Gate</small><strong>{_esc(market.get('entry_gate'))}</strong></div>
        <div class="metric"><small>推奨Exposure</small><strong>{_pct(market.get('recommended_exposure_pct'))}</strong></div>
        <div class="metric"><small>Quality</small><strong>{_esc(quality.get('status'))}</strong></div>
      </div>
      <section class="section summary"><h2>20秒要約</h2><pre>{_esc(summary)}</pre></section>
      {_candidate_section('発注可能', partitions['ACTIONABLE'], '地合いまたは個別条件により本日の発注候補なし', 8)}
      {_candidate_section('準備候補', partitions['READY'], '準備候補なし', 12)}
      {_candidate_section('回避', partitions['AVOID'], '明確な回避候補なし', 8)}
    """

    filters = """
      <div class="filters"><select id="statusFilter"><option value="ALL">全状態</option><option value="ACTIONABLE">発注可能</option><option value="READY">準備</option><option value="AVOID">回避</option></select><input id="tickerSearch" placeholder="ティッカー検索"><button onclick="resetFilters()">解除</button></div>
    """
    candidate_all = "".join(_candidate_card(item) for item in candidates) or '<div class="empty">候補なし</div>'
    candidate_view = f'<section class="section"><div class="section-head"><h2>候補ランキング</h2><span>理由・価格帯・リスク順</span></div>{filters}<div id="candidateList" class="candidate-grid">{candidate_all}</div></section>'

    market_view = f"""
      <section class="section"><h2>市場の柱</h2><div class="grid">{pillar_cards}</div></section>
      <section class="section"><h2>QQQ</h2><div class="grid">{_standard_cards([qqq], 'label', [('price','価格','money'),('return_5d','5日','pct'),('return_21d','21日','pct'),('distance_52w_high_pct','高値距離','pct_raw')],1)}</div></section>
      <section class="section"><h2>Breadth</h2><div class="grid">{_standard_cards([{'label':'Market Breadth',**breadth}], 'label', [('above_sma10','10日線上','pct'),('above_sma50','50日線上','pct'),('above_sma200','200日線上','pct'),('positive_rs63','RS63プラス','pct'),('positive_rs126','RS126プラス','pct')],1)}</div></section>
      <section class="section"><h2>Sector加速</h2><div class="grid">{_standard_cards(sectors,'sector',[('phase','Phase','text'),('score_rotation','Rotation','num'),('score_strength','Strength','num'),('score_acceleration','Acceleration','num'),('breadth_positive_63d','Breadth','pct'),('leaders','Leaders','text')],20)}</div></section>
    """

    theme_view = f'<section class="section"><h2>Theme Taxonomy</h2><div class="grid">{_standard_cards(themes,"theme_ja",[("theme","English","text"),("phase","Phase","text"),("score_theme","Score","pct"),("rs_acceleration_raw","RS加速","pct"),("breadth_positive","Breadth","pct"),("leaders","Leaders","text")],30)}</div></section>'

    board_sections = []
    for key, label in (("rs63", "RS63"), ("rs126", "RS126"), ("rs189", "RS189")):
        rows = _as_list(boards.get(key))
        board_sections.append(f'<section class="section"><h2>{label} Top10</h2><div class="leader-table">' + "".join(f'<div><b>#{_esc(item.get("rank"))} {_esc(item.get("ticker"))}</b><span>変化 {_esc(item.get("rank_change"))} / RS {_num(item.get("rs_raw") or item.get("rs_percentile"),2)}</span></div>' for item in rows) + ('' if rows else '<div class="empty">データなし</div>') + '</div></section>')
    changes = transitions.get("changes") or {}
    change_cards = []
    for key in ("rs63", "rs126", "rs189"):
        section = changes.get(key) or {}
        change_cards.append({"label": key.upper(), "new": section.get("new_top10"), "dropped": section.get("dropped_top10")})
    leader_view = "".join(board_sections) + f'<section class="section"><h2>リーダー交代</h2><p class="note">{_esc(_friendly_status(transitions.get("status")))}</p><div class="grid">{_standard_cards(change_cards,"label",[("new","Top10新規","text"),("dropped","Top10脱落","text")],3)}</div></section>'

    rankings = _as_list(expectancy.get("rankings") or expectancy.get("setup_stats"))
    rankings = [item for item in rankings if item.get("usable") or item.get("qualified")][:40]
    walk = _as_list(expectancy.get("walk_forward"))
    exp_view = f"""
      <div class="hero"><div class="metric"><small>履歴標本</small><strong>{_num(expectancy.get('sample_count'),0)}</strong></div><div class="metric"><small>対象銘柄</small><strong>{_num(expectancy.get('ticker_count'),0)}</strong></div><div class="metric"><small>履歴期間</small><strong>{_esc(expectancy.get('years'))}</strong></div><div class="metric"><small>実運用検証</small><strong>{_esc(_friendly_status(robust.get('status')))}</strong></div></div>
      <section class="section"><h2>実測期待値ランキング</h2><div class="grid">{_standard_cards(rankings,'setup',[('horizon','期間','text'),('samples','標本','num'),('win_rate','勝率','pct'),('mean_excess_return','平均超過','pct'),('median_excess_return','中央値超過','pct'),('downside_tail_p10','下方P10','pct')],40)}</div></section>
      <section class="section"><h2>Walk-forward</h2><div class="grid">{_standard_cards(walk,'selected_setup',[('test_year','検証年','text'),('horizon','期間','text'),('train_samples','学習標本','num'),('test_samples','検証標本','num'),('mean_excess','平均超過','pct'),('win_rate','勝率','pct')],30)}</div></section>
      <section class="section"><h2>実運用Forward検証</h2><p class="note">{_esc(_friendly_status(robust.get('status')))}</p></section>
    """

    portfolio_view = f"""
      <div class="hero"><div class="metric"><small>Gross Exposure</small><strong>{_pct(portfolio.get('gross_exposure'),decimal=True)}</strong></div><div class="metric"><small>Exposure Cap</small><strong>{_pct(portfolio.get('market_exposure_cap'),decimal=True)}</strong></div><div class="metric"><small>Portfolio ADR</small><strong>{_pct(portfolio.get('portfolio_adr_pct'))}</strong></div><div class="metric"><small>Stop Risk</small><strong>{_pct(portfolio.get('portfolio_stop_risk_pct'))}</strong></div></div>
      <section class="section"><div class="section-head"><h2>保有診断</h2><button class="smallbtn" onclick="copyText('{_esc(portfolio.get('positions_copy'))}')">全銘柄コピー</button></div><div class="grid">{_standard_cards(positions,'ticker',[('action','Action','text'),('weight','Weight','pct'),('gain_pct','損益','pct_raw'),('held_days','保有日数','text'),('stop','Stop','money'),('stop_distance_pct','Stop距離','pct_raw'),('risk_contribution_pct','Risk寄与','pct_raw'),('reasons','理由','text')],30)}</div></section>
      <section class="section"><h2>集中警告</h2><p class="note">{_esc(portfolio.get('warnings') or ['重大警告なし'])}</p><div class="grid">{_standard_cards([{'label':'Sector', 'weights':portfolio.get('sector_weights')},{'label':'Theme','weights':portfolio.get('theme_weights')},{'label':'Correlation','weights':(portfolio.get('correlation') or {}).get('high_correlation_pairs')}],'label',[('weights','内容','text')],3)}</div></section>
    """

    external_cards = _standard_cards(external, "ticker", [("next_earnings_date","決算","text"),("days_to_earnings","日数","text"),("eps_revision_30d_pct","EPS修正","pct_raw"),("guidance_direction","Guidance","text"),("event_type","材料","text"),("warnings","警告","text")],30)
    data_view = f'<section class="section"><h2>データ品質</h2><div class="hero"><div class="metric"><small>Status</small><strong>{_esc(quality.get("status"))}</strong></div><div class="metric"><small>Price coverage</small><strong>{_pct((quality.get("metrics") or {}).get("price_coverage_ratio"),decimal=True)}</strong></div><div class="metric"><small>Price as of</small><strong>{_esc(manifest.get("price_asof") or (quality.get("metrics") or {}).get("qqq_last_date"))}</strong></div><div class="metric"><small>Warnings</small><strong>{len(quality.get("warnings") or [])}</strong></div></div><p class="note">{_esc(quality.get("warnings") or ["重大警告なし"])}</p></section><section class="section"><h2>外部材料</h2><div class="grid">{external_cards}</div></section>'

    post_ja = brief.get("x_post_ja") or brief.get("market_comment") or ""
    post_en = brief.get("x_post_en") or ""
    x_view = f'<section class="section"><h2>X投稿用 日本語</h2><textarea id="xpostja" class="copy">{_esc(post_ja)}</textarea><button class="copybtn" onclick="copyArea(\'xpostja\')">コピー</button></section><section class="section"><h2>X post English</h2><textarea id="xposten" class="copy">{_esc(post_en)}</textarea><button class="copybtn" onclick="copyArea(\'xposten\')">Copy</button></section>'

    tabs = [("daily","日次"),("market","市場"),("candidates","候補"),("themes","テーマ"),("leaders","リーダー"),("expectancy","期待値"),("portfolio","Portfolio"),("data","Data"),("x","X投稿")]
    buttons = "".join(f'<button data-tab="{key}" class="{"active" if index == 0 else ""}">{label}</button>' for index,(key,label) in enumerate(tabs))
    views = {"daily":daily,"market":market_view,"candidates":candidate_view,"themes":theme_view,"leaders":leader_view,"expectancy":exp_view,"portfolio":portfolio_view,"data":data_view,"x":x_view}
    view_html = "".join(f'<div id="{key}" class="view {"active" if index == 0 else ""}">{views[key]}</div>' for index,(key,_) in enumerate(tabs))
    bootstrap_banner = "" if input_status == "INDEX" else '<div class="banner">統合JSON未生成。取得済みセクションのみ表示中。</div>'

    css = """
    :root{color-scheme:dark;--bg:#080c11;--panel:#111821;--panel2:#0d131b;--line:#273343;--muted:#91a0b4;--text:#f2f6fb;--accent:#78afff;--good:#54d68a;--warn:#f3c45b;--bad:#ff7373}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.35}.wrap{max-width:1380px;margin:auto;padding:14px}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-end}.top h1{font-size:24px;margin:0}.muted,.note{color:var(--muted);font-size:12px}.hub{color:var(--accent);text-decoration:none;font-size:12px}.banner{margin:10px 0;padding:10px;border:1px solid var(--warn);border-radius:10px;color:var(--warn)}.tabs{display:flex;gap:7px;overflow:auto;position:sticky;top:0;z-index:10;background:rgba(8,12,17,.96);padding:10px 0}.tabs button,.filters button,.filters select,.filters input,.smallbtn{min-height:42px;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:999px;padding:8px 13px;white-space:nowrap}.tabs button.active{border-color:var(--accent);color:var(--accent)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:8px 0 10px}.metric,.section{background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric{padding:12px}.metric small{color:var(--muted)}.metric strong{display:block;font-size:20px;margin-top:3px}.section{padding:12px;margin-bottom:10px}.section h2{font-size:16px;margin:0}.section-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:9px}.section-head span{color:var(--muted);font-size:11px}.summary pre{margin:8px 0 0;white-space:pre-wrap;font:inherit;line-height:1.55}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.item,.candidate{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:10px;min-width:0}.item h3{font-size:14px;color:var(--accent);margin:0 0 8px}.kv{display:grid;grid-template-columns:minmax(90px,.8fr) minmax(0,1.2fr);gap:5px 8px;font-size:11px}.kv span{color:var(--muted)}.kv b{text-align:right;overflow-wrap:anywhere}.candidate-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.candidate-head,.candidate-sub{display:flex;justify-content:space-between;gap:7px;align-items:center}.ticker{font-size:17px;color:var(--accent)}.rank{font-size:10px;color:var(--muted);margin-left:5px}.candidate-sub{font-size:10px;color:var(--muted);margin:5px 0 9px;flex-wrap:wrap}.badge{font-size:10px;font-weight:800;padding:3px 7px;border-radius:99px}.badge.actionable{background:rgba(84,214,138,.15);color:var(--good)}.badge.ready{background:rgba(120,175,255,.14);color:var(--accent)}.badge.avoid{background:rgba(255,115,115,.14);color:var(--bad)}.candidate.actionable{border-color:rgba(84,214,138,.45)}.candidate.avoid{opacity:.82}.reasons{margin:9px 0 0;padding-left:18px;font-size:10.5px;color:var(--muted)}.reasons li{margin:2px 0}.filters{display:flex;gap:7px;margin:8px 0;overflow:auto}.filters input{border-radius:10px;min-width:130px}.empty{color:var(--muted);padding:18px}.leader-table{display:grid;gap:5px}.leader-table>div{display:flex;justify-content:space-between;gap:8px;padding:8px;border-radius:8px;background:var(--panel2);font-size:12px}.leader-table span{color:var(--muted)}.copy{width:100%;min-height:170px;background:#080c11;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px;font:inherit}.copybtn{margin-top:8px;border:0;border-radius:9px;padding:10px 16px;background:var(--accent);color:#08111e;font-weight:800}.smallbtn{min-height:34px;padding:5px 10px}@media(max-width:960px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.candidate-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:580px){.wrap{padding:10px}.top{align-items:flex-start;flex-direction:column}.top h1{font-size:22px}.hero{grid-template-columns:1fr 1fr}.grid,.candidate-grid{grid-template-columns:1fr}.section{padding:10px}.kv{grid-template-columns:minmax(92px,.8fr) minmax(0,1.2fr)}.candidate{padding:10px}.tabs{margin:0 -10px;padding:9px 10px}.tabs button{min-height:40px;padding:7px 12px}}@media print{.tabs,.filters,.copybtn,.smallbtn{display:none}.view{display:block!important}.section{break-inside:avoid}}
    """
    script = """
    document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(item=>item.classList.remove('active'));document.querySelectorAll('.view').forEach(item=>item.classList.remove('active'));button.classList.add('active');document.getElementById(button.dataset.tab).classList.add('active')});
    function applyFilters(){const status=document.getElementById('statusFilter').value;const query=document.getElementById('tickerSearch').value.toUpperCase();document.querySelectorAll('#candidateList .candidate').forEach(card=>{const okStatus=status==='ALL'||card.dataset.status===status;const okTicker=!query||card.textContent.toUpperCase().includes(query);card.style.display=okStatus&&okTicker?'':'none'})}
    document.getElementById('statusFilter')?.addEventListener('change',applyFilters);document.getElementById('tickerSearch')?.addEventListener('input',applyFilters);function resetFilters(){document.getElementById('statusFilter').value='ALL';document.getElementById('tickerSearch').value='';applyFilters()}function copyArea(id){navigator.clipboard.writeText(document.getElementById(id).value)}function copyText(text){navigator.clipboard.writeText(text)}
    """
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>V38 Intelligence Dashboard</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>V38 Intelligence Dashboard</h1><div class="muted">個人用詳細分析 / generated {_esc(generated)}</div></div><div><a class="hub" href="index.html">← Command Hub</a><div class="muted">{_esc(brief.get("headline"))}</div></div></header>{bootstrap_banner}<nav class="tabs">{buttons}</nav><main>{view_html}</main></div><script>{script}</script></body></html>'


def generate(input_path: Path, output_path: Path) -> None:
    payload = load_payload(input_path)
    output_path.write_text(build_html(payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/intelligence/index.json")
    parser.add_argument("--output", default="intelligence-dashboard.html")
    args = parser.parse_args()
    generate(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()

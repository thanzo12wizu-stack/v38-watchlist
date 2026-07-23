from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .research_storage import load_dataset


BLOCK_JA = {
    "LONG_TREND_BROKEN": "長期トレンド崩れ",
    "STOP_TOO_WIDE": "損切り幅が広すぎる",
    "REWARD_RISK_LOW": "上値余地が不足",
    "FUNDAMENTAL_DETERIORATION": "財務モメンタム悪化",
    "LEADERSHIP_RISK": "RSリーダー失速",
    "EARNINGS_WINDOW": "決算前後3日",
}
STATUS_JA = {"ACTIONABLE": "買える", "READY": "待つ", "AVOID": "避ける"}
CONSISTENCY_JA = {
    "CONFIRMED": "8年・5年で一致",
    "MIXED": "3年だけ不一致",
    "CONFLICT": "8年・5年が逆方向",
    "PRIMARY_ONLY": "8年のみ有効",
    "RECENT_ONLY": "最近だけ標本あり",
    "UNAVAILABLE": "期待値未確定",
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


def _pct(value: Any, digits: int = 1, *, decimal: bool = False, signed: bool = False) -> str:
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
        if pd.isna(number):
            return "—"
        return f"${number:,.2f}"
    except (TypeError, ValueError):
        return "—"


def _score(value: Any) -> float:
    try:
        number = float(value)
        return max(0.0, min(100.0, number)) if pd.notna(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _bar(label: str, value: Any) -> str:
    score = _score(value)
    return f'<div class="bar"><span>{_esc(label)}</span><i><b style="width:{score:.1f}%"></b></i><em>{_num(value,0)}</em></div>'


def _blocks(row: pd.Series) -> list[str]:
    value = row.get("hard_blocks")
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _reasons(row: pd.Series) -> list[str]:
    blocks = _blocks(row)
    if blocks:
        return [BLOCK_JA.get(code, code) for code in blocks[:3]]
    reasons: list[str] = []
    phase = str(row.get("financial_phase") or "")
    rs = str(row.get("rs_archetype") or "")
    state = str(row.get("entry_state") or "")
    consistency = str(row.get("expectancy_consistency") or "UNAVAILABLE")
    if phase in {"ACCELERATING", "COMPOUNDING", "INFLECTING"}:
        reasons.append(f"財務フェーズ: {phase}")
    if rs in {"NEW_LEADER", "ACCELERATING_LEADER", "ESTABLISHED_LEADER", "REACCELERATING"}:
        reasons.append(f"RS状態: {rs}")
    if state in {"READY", "TRIGGERED"}:
        reasons.append(f"Entry位置: {state}")
    if consistency == "CONFIRMED":
        reasons.append("8年と5年の期待値が同方向")
    elif consistency in {"CONFLICT", "MIXED"}:
        reasons.append(CONSISTENCY_JA[consistency])
    if not reasons:
        reasons.append("候補条件は満たすが、強い根拠の重なり待ち")
    return reasons[:3]


def _kv(rows: list[tuple[str, str]]) -> str:
    return '<div class="kv">' + "".join(f"<span>{_esc(label)}</span><b>{value}</b>" for label, value in rows) + "</div>"


def _candidate_card(row: pd.Series) -> str:
    status = str(row.get("decision_status") or "READY")
    status_ja = STATUS_JA.get(status, status)
    reasons = "".join(f"<li>{_esc(reason)}</li>" for reason in _reasons(row))
    ticker = str(row.get("ticker") or "")
    archetype = str(row.get("candidate_archetype") or "NONE")
    setup = str(row.get("setup") or "WATCH")
    consistency = str(row.get("expectancy_consistency") or "UNAVAILABLE")
    blocks = _blocks(row)
    component_bars = "".join(
        [
            _bar("財務力", row.get("fundamental_quality")),
            _bar("財務変化", row.get("fundamental_change")),
            _bar("RS", row.get("leadership_quality")),
            _bar("Entry", row.get("entry_quality")),
            _bar("Risk", row.get("risk_fit")),
        ]
    )
    quick = _kv(
        [
            ("現在値", _money(row.get("price"))),
            ("Pivot", _money(row.get("pivot_20d"))),
            ("Stop幅", _pct(row.get("stop_risk_pct"))),
            ("R/R", _num(row.get("reward_risk_raw"), 1)),
            ("期待値 8年", _pct(row.get("expected_edge_10d_8y"), decimal=True, signed=True)),
            ("標本", _num(row.get("expectancy_samples"), 0)),
        ]
    )
    financial = _kv(
        [
            ("EPS YoY", _pct(row.get("eps_yoy"), decimal=True, signed=True)),
            ("売上 YoY", _pct(row.get("revenue_yoy"), decimal=True, signed=True)),
            ("EPS加速", _pct(row.get("eps_acceleration"), decimal=True, signed=True)),
            ("売上加速", _pct(row.get("revenue_acceleration"), decimal=True, signed=True)),
            ("粗利率変化", _pct(row.get("gross_margin_delta"), decimal=True, signed=True)),
            ("営業利益率変化", _pct(row.get("operating_margin_delta"), decimal=True, signed=True)),
            ("FCF YoY", _pct(row.get("free_cash_flow_yoy"), decimal=True, signed=True)),
            ("株式数 YoY", _pct(row.get("shares_yoy"), decimal=True, signed=True)),
        ]
    )
    relative = _kv(
        [
            ("RS63", _num(row.get("pct_rs_raw_63"), 0)),
            ("RS126", _num(row.get("pct_rs_raw_126"), 0)),
            ("RS189", _num(row.get("pct_rs_raw_189"), 0)),
            ("RS63順位変化", _num(row.get("rs63_rank_change_21d"), 0)),
            ("RS126順位変化", _num(row.get("rs126_rank_change_21d"), 0)),
            ("Top20持続率", _pct(row.get("rs126_top20_persistence_63d"), decimal=True)),
        ]
    )
    entry = _kv(
        [
            ("Setup", _esc(setup)),
            ("Entry状態", _esc(row.get("entry_state"))),
            ("EMA21 Low", _money(row.get("stop_ema21_low"))),
            ("10MA", _money(row.get("stop_sma10"))),
            ("出来高比", _num(row.get("volume_ratio_20d"), 2)),
            ("50MA乖離 ATR", _num(row.get("extension_atr"), 2)),
        ]
    )
    expectancy = _kv(
        [
            ("10年", _pct(row.get("expected_edge_10d_10y"), decimal=True, signed=True)),
            ("8年・標準", _pct(row.get("expected_edge_10d_8y"), decimal=True, signed=True)),
            ("5年", _pct(row.get("expected_edge_10d_5y"), decimal=True, signed=True)),
            ("3年", _pct(row.get("expected_edge_10d_3y"), decimal=True, signed=True)),
            ("判定", _esc(row.get("expectancy_status"))),
            ("一貫性", _esc(CONSISTENCY_JA.get(consistency, consistency))),
            ("順位補正", _num(row.get("expectancy_adjustment"), 2)),
            ("Confidence", _pct(row.get("research_confidence"), decimal=True)),
        ]
    )
    block_text = " / ".join(BLOCK_JA.get(code, code) for code in blocks) if blocks else "なし"
    return f'''
    <article class="candidate {status.lower()}" data-status="{_esc(status)}" data-archetype="{_esc(archetype)}" data-search="{_esc(ticker)} {_esc(archetype)} {_esc(setup)}">
      <div class="head"><div><b class="ticker">{_esc(ticker)}</b><span class="rank">#{_num(row.get('research_rank'),0)}</span></div><span class="badge {status.lower()}">{_esc(status_ja)}</span></div>
      <div class="sub"><span>{_esc(archetype)}</span><span>{_esc(row.get('financial_phase'))}</span><span>{_esc(row.get('rs_archetype'))}</span><span>{_esc(setup)}</span></div>
      <div class="scoreline"><strong>{_num(row.get('composite_rank_score'),1)}</strong><small>総合</small><button onclick="copyTicker('{_esc(ticker)}')">コピー</button></div>
      <ul class="reasons">{reasons}</ul>
      {quick}
      <div class="bars">{component_bars}</div>
      <details><summary>財務・RS・Entry・期待値を確認</summary><div class="detail-grid"><section><h4>財務</h4>{financial}</section><section><h4>RS</h4>{relative}</section><section><h4>Entry</h4>{entry}</section><section><h4>期待値</h4>{expectancy}</section></div><p class="block">Hard block: {_esc(block_text)}</p></details>
    </article>'''


def _window_lookup(expectancy: dict) -> dict[int, dict]:
    result = {}
    for window in expectancy.get("windows") or []:
        try:
            result[int(window.get("window_years"))] = window
        except (TypeError, ValueError):
            continue
    return result


def _expectancy_rows(expectancy: dict, window_years: int) -> list[dict]:
    window = _window_lookup(expectancy).get(window_years) or {}
    rows = [
        row
        for row in window.get("groups") or []
        if row.get("group_type") == "archetype_setup" and int(row.get("horizon") or 0) == 10
    ]
    rows.sort(key=lambda row: (-(row.get("mean_excess_return") or -999), -int(row.get("samples") or 0)))
    return rows[:30]


def _expectancy_table(expectancy: dict) -> str:
    lookups = {years: _expectancy_rows(expectancy, years) for years in (8, 5, 3)}
    keys = []
    for rows in lookups.values():
        for row in rows:
            key = (str(row.get("candidate_archetype")), str(row.get("setup")))
            if key not in keys:
                keys.append(key)
    body = []
    for archetype, setup in keys[:40]:
        cells = []
        for years in (8, 5, 3):
            match = next((row for row in lookups[years] if str(row.get("candidate_archetype")) == archetype and str(row.get("setup")) == setup), None)
            if match:
                cells.append(f'<td><b>{_pct(match.get("mean_excess_return"),decimal=True,signed=True)}</b><small>n={_num(match.get("samples"),0)} / {_esc(match.get("qualification"))}</small></td>')
            else:
                cells.append('<td>—</td>')
        body.append(f'<tr><th>{_esc(archetype)}<small>{_esc(setup)}</small></th>{"".join(cells)}</tr>')
    return '<div class="table-wrap"><table><thead><tr><th>型 × Setup</th><th>8年・標準</th><th>5年</th><th>3年</th></tr></thead><tbody>' + "".join(body) + '</tbody></table></div>'


def _validation_cards(expectancy: dict) -> str:
    walk = [row for row in expectancy.get("walk_forward") or [] if int(row.get("horizon") or 0) == 10]
    walk.sort(key=lambda row: int(row.get("test_year") or 0), reverse=True)
    loyo = [row for row in expectancy.get("leave_one_year_out") or [] if int(row.get("horizon") or 0) == 10]
    loyo.sort(key=lambda row: int(row.get("omitted_year") or 0), reverse=True)
    cards = []
    for row in walk[:12]:
        cards.append(f'<article class="mini"><h3>{_esc(row.get("test_year"))} Walk-forward</h3>{_kv([("採用型",_esc(row.get("selected_archetype"))),("学習n",_num(row.get("train_samples"),0)),("検証n",_num(row.get("test_samples"),0)),("検証超過",_pct(row.get("test_mean_excess"),decimal=True,signed=True)),("勝率",_pct(row.get("test_win_rate"),decimal=True))])}</article>')
    for row in loyo[:8]:
        cards.append(f'<article class="mini"><h3>{_esc(row.get("omitted_year"))}除外</h3>{_kv([("標本",_num(row.get("samples"),0)),("平均超過",_pct(row.get("mean_excess_return"),decimal=True,signed=True)),("勝率",_pct(row.get("win_rate"),decimal=True))])}</article>')
    return "".join(cards) or '<div class="empty">検証結果を蓄積中</div>'


def build_html(root: Path) -> str:
    manifest = _read(root / "manifest.json", {})
    expectancy = _read(root / "expectancy.json", {})
    rankings = load_dataset(root, "rankings")
    if not rankings.empty and "date" in rankings:
        rankings["date"] = pd.to_datetime(rankings["date"], errors="coerce")
        latest_date = rankings["date"].max()
        latest = rankings[rankings["date"] == latest_date].copy()
    else:
        latest_date = pd.NaT
        latest = pd.DataFrame()
    if not latest.empty:
        latest = latest.sort_values(["research_rank", "ticker"], ascending=[True, True])
    cards = "".join(_candidate_card(row) for _, row in latest.head(100).iterrows()) or '<div class="empty">研究候補を生成中</div>'
    counts = latest.get("decision_status", pd.Series(dtype=str)).value_counts() if not latest.empty else pd.Series(dtype=int)
    generated = manifest.get("generated_at") or "—"
    latest_text = latest_date.date().isoformat() if pd.notna(latest_date) else "—"
    css = '''
    :root{color-scheme:dark;--bg:#080b10;--panel:#111720;--panel2:#0c1118;--line:#253142;--text:#f2f5f9;--muted:#8e9bad;--blue:#75aaff;--green:#50d38a;--yellow:#efc15a;--red:#ff7474}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.35}.wrap{max-width:1320px;margin:auto;padding:12px}.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-end}.top h1{font-size:22px;margin:0}.muted{color:var(--muted);font-size:11px}.back{color:var(--blue);text-decoration:none;font-size:12px}.tabs{display:flex;gap:6px;overflow:auto;position:sticky;top:0;z-index:5;background:rgba(8,11,16,.97);padding:9px 0}.tabs button,.filters button,.filters select,.filters input{min-height:39px;border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:999px;padding:7px 12px;white-space:nowrap}.tabs button.active{color:var(--blue);border-color:var(--blue)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;margin:7px 0}.metric,.section{background:var(--panel);border:1px solid var(--line);border-radius:13px}.metric{padding:10px}.metric small{color:var(--muted);font-size:10px}.metric strong{display:block;font-size:18px;margin-top:2px}.section{padding:10px;margin-bottom:8px}.section h2{font-size:15px;margin:0 0 7px}.filters{display:flex;gap:6px;overflow:auto;margin-bottom:8px}.filters input{border-radius:9px;min-width:140px}.candidate-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.candidate{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:10px;min-width:0}.candidate.actionable{border-color:rgba(80,211,138,.55)}.candidate.avoid{opacity:.8}.head,.sub,.scoreline{display:flex;align-items:center;justify-content:space-between;gap:6px}.ticker{font-size:18px;color:var(--blue)}.rank{font-size:10px;color:var(--muted);margin-left:5px}.badge{font-size:10px;font-weight:800;padding:3px 7px;border-radius:99px}.badge.actionable{color:var(--green);background:rgba(80,211,138,.14)}.badge.ready{color:var(--blue);background:rgba(117,170,255,.14)}.badge.avoid{color:var(--red);background:rgba(255,116,116,.14)}.sub{justify-content:flex-start;flex-wrap:wrap;color:var(--muted);font-size:9.5px;margin:4px 0 6px}.sub span{border:1px solid var(--line);border-radius:99px;padding:2px 5px}.scoreline{justify-content:flex-start;margin-bottom:5px}.scoreline strong{font-size:23px}.scoreline small{color:var(--muted)}.scoreline button{margin-left:auto;border:0;background:none;color:var(--blue)}.reasons{margin:5px 0 8px;padding-left:17px;font-size:10.5px}.reasons li{margin:2px 0}.kv{display:grid;grid-template-columns:minmax(90px,.9fr) minmax(0,1.1fr);gap:4px 7px;font-size:10.5px}.kv span{color:var(--muted)}.kv b{text-align:right;overflow-wrap:anywhere}.bars{margin-top:8px}.bar{display:grid;grid-template-columns:52px 1fr 25px;gap:5px;align-items:center;font-size:9px;margin:3px 0}.bar span,.bar em{color:var(--muted);font-style:normal}.bar i{height:4px;background:#1d2734;border-radius:99px;overflow:hidden}.bar i b{display:block;height:100%;background:var(--blue)}details{margin-top:8px;border-top:1px solid var(--line);padding-top:7px}summary{color:var(--blue);font-size:10.5px;cursor:pointer}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}.detail-grid section{background:#090e15;border-radius:8px;padding:7px}.detail-grid h4{font-size:11px;margin:0 0 5px}.block{font-size:10px;color:var(--muted);margin:7px 0 0}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:11px}th,td{border-bottom:1px solid var(--line);padding:7px;text-align:right;white-space:nowrap}th:first-child{text-align:left}th small,td small{display:block;color:var(--muted);font-weight:400}.mini-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.mini{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:9px}.mini h3{font-size:12px;color:var(--blue);margin:0 0 6px}.empty{color:var(--muted);padding:18px}@media(max-width:900px){.candidate-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.mini-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:580px){.wrap{padding:9px}.top{align-items:flex-start;flex-direction:column}.candidate-grid,.mini-grid{grid-template-columns:1fr}.hero{grid-template-columns:1fr 1fr}.detail-grid{grid-template-columns:1fr}.tabs{margin:0 -9px;padding:8px 9px}.section{padding:9px}}
    '''
    script = '''
    document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));button.classList.add('active');document.getElementById(button.dataset.tab).classList.add('active')});
    function filterCards(){const status=document.getElementById('statusFilter').value;const archetype=document.getElementById('archetypeFilter').value;const query=document.getElementById('search').value.toUpperCase();document.querySelectorAll('.candidate').forEach(card=>{const ok1=status==='ALL'||card.dataset.status===status;const ok2=archetype==='ALL'||card.dataset.archetype===archetype;const ok3=!query||card.dataset.search.toUpperCase().includes(query);card.style.display=ok1&&ok2&&ok3?'':'none'})}
    ['statusFilter','archetypeFilter','search'].forEach(id=>document.getElementById(id)?.addEventListener(id==='search'?'input':'change',filterCards));function resetFilters(){document.getElementById('statusFilter').value='ALL';document.getElementById('archetypeFilter').value='ALL';document.getElementById('search').value='';filterCards()}function copyTicker(ticker){navigator.clipboard.writeText(ticker)}
    '''
    archetypes = sorted(str(value) for value in latest.get("candidate_archetype", pd.Series(dtype=str)).dropna().unique())
    archetype_options = "".join(f'<option value="{_esc(value)}">{_esc(value)}</option>' for value in archetypes)
    today = f'''
      <div class="hero"><div class="metric"><small>研究日</small><strong>{_esc(latest_text)}</strong></div><div class="metric"><small>買える</small><strong>{int(counts.get('ACTIONABLE',0))}</strong></div><div class="metric"><small>待つ</small><strong>{int(counts.get('READY',0))}</strong></div><div class="metric"><small>避ける</small><strong>{int(counts.get('AVOID',0))}</strong></div><div class="metric"><small>保存期間</small><strong>{_esc(manifest.get('years_retained') or 10)}年</strong></div></div>
      <section class="section"><h2>今日の複合候補</h2><div class="filters"><select id="statusFilter"><option value="ALL">全判断</option><option value="ACTIONABLE">買える</option><option value="READY">待つ</option><option value="AVOID">避ける</option></select><select id="archetypeFilter"><option value="ALL">全タイプ</option>{archetype_options}</select><input id="search" placeholder="Ticker検索"><button onclick="resetFilters()">解除</button></div><div class="candidate-grid">{cards}</div></section>
    '''
    expectation = f'<section class="section"><h2>型別10日期待値</h2><p class="muted">8年を標準判断、5年を最近相場、3年を現在レジームの確認に使用。3年だけ良くても順位補正しません。</p>{_expectancy_table(expectancy)}</section>'
    validation = f'<section class="section"><h2>Walk-forward / 年除外</h2><div class="mini-grid">{_validation_cards(expectancy)}</div></section>'
    data = f'<section class="section"><h2>研究データ</h2>{_kv([("生成",_esc(generated)),("期間",f"{_esc(manifest.get("start_date"))} → {_esc(manifest.get("end_date"))}"),("銘柄",_num(manifest.get("tickers"),0)),("Signals",_num(manifest.get("signal_rows"),0)),("Outcomes",_num(manifest.get("outcome_rows"),0)),("Rankings",_num(manifest.get("ranking_rows"),0)),("標準窓",f"{_esc(expectancy.get("primary_window_years") or 8)}年"),("比較窓",_esc(expectancy.get("comparison_windows_years") or [10,8,5,3])),("警告",_esc(manifest.get("warnings") or ["なし"]))])}</section>'
    tabs = [("today","候補"),("expectancy","期待値"),("validation","検証"),("data","Data")]
    buttons = "".join(f'<button data-tab="{key}" class="{"active" if index==0 else ""}">{label}</button>' for index,(key,label) in enumerate(tabs))
    views = {"today":today,"expectancy":expectation,"validation":validation,"data":data}
    view_html = "".join(f'<main id="{key}" class="view {"active" if index==0 else ""}">{views[key]}</main>' for index,(key,_) in enumerate(tabs))
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>V38 Research Decision</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>Research Decision</h1><div class="muted">財務 × RS × Entry × 実測期待値 / generated {_esc(generated)}</div></div><a class="back" href="intelligence-dashboard.html">← Intelligence</a></header><nav class="tabs">{buttons}</nav>{view_html}</div><script>{script}</script></body></html>'


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

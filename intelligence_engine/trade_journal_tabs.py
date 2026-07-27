from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from .trade_journal import JournalReport
from .trade_journal_html import (
    _esc,
    _line_chart_svg,
    _metric,
    _monthly_heatmap,
    _num,
    _pct,
    _sector_bars,
    _table,
    _tone,
    _treemap_svg,
    _yen,
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _nq_state(color: str) -> tuple[str, str, str]:
    states = {
        "BLUE": ("青", "新規可", "市場ゲートは攻められる状態。個別の位置とHeatを優先。"),
        "GREEN": ("緑", "新規可", "通常運用。過熱・集中・決算接近は個別に遮断。"),
        "YELLOW": ("黄", "新規停止", "既存ルールに従い、新規発注はせず候補監視に限定。"),
        "RED": ("赤", "リスクオフ", "新規禁止。既存ポジションの縮小・撤退を優先。"),
    }
    return states.get(str(color).upper(), ("不明", "判定停止", "NQ色が取得できないため発注判断は停止。"))


def _review_html(markdown: str) -> str:
    parts: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts.append(f"<h3>{_esc(line.lstrip('# ').strip())}</h3>")
        else:
            parts.append(f"<p>{_esc(line)}</p>")
    return "".join(parts) or '<div class="empty">レビューなし</div>'


def _journal_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="empty">取引履歴なし</div>'
    work = frame.sort_values(["exit_date", "entry_date"], ascending=False, na_position="last")
    rows = [
        '<div class="journal-toolbar">',
        '<label class="search"><span>検索</span><input id="trade-search" type="search" placeholder="Ticker / Setup / Exit"></label>',
        '<label><span>Setup</span><select id="trade-setup"><option value="">すべて</option>',
    ]
    setups = sorted({str(v) for v in work.get("setup", pd.Series(dtype=str)).dropna() if str(v)})
    rows.extend(f'<option value="{_esc(v.lower())}">{_esc(v)}</option>' for v in setups)
    rows.append('</select></label><label><span>NQ</span><select id="trade-nq"><option value="">すべて</option>')
    nq_values = [v for v in ("BLUE", "GREEN", "YELLOW", "RED", "UNKNOWN") if v in set(work.get("nq_color", pd.Series(dtype=str)).astype(str))]
    rows.extend(f'<option value="{v.lower()}">{v}</option>' for v in nq_values)
    rows.append('</select></label><label><span>結果</span><select id="trade-result"><option value="">すべて</option><option value="win">勝ち</option><option value="loss">負け</option><option value="flat">引分</option></select></label>')
    rows.append('<button class="ghost" type="button" id="trade-reset">リセット</button><strong id="trade-count"></strong></div>')
    rows.append('<div class="table-wrap tall"><table id="trade-table"><thead><tr>')
    headers = ["Entry", "Exit", "Ticker", "Setup", "NQ", "損益率", "R", "損益", "日数", "Exit理由", "規律"]
    rows.extend(f"<th>{h}</th>" for h in headers)
    rows.append("</tr></thead><tbody>")
    for _, row in work.iterrows():
        pnl = _finite(row.get("net_pnl_jpy"))
        result = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
        setup = str(row.get("setup") or "UNKNOWN")
        nq = str(row.get("nq_color") or "UNKNOWN")
        searchable = " ".join(str(row.get(c) or "") for c in ("ticker", "setup", "exit_reason", "sector", "theme")).lower()
        followed = bool(row.get("rule_followed"))
        discipline = "遵守" if followed else "逸脱"
        rows.append(
            f'<tr data-search="{_esc(searchable)}" data-setup="{_esc(setup.lower())}" data-nq="{_esc(nq.lower())}" data-result="{result}">'
            f'<td>{pd.Timestamp(row["entry_date"]).date().isoformat() if pd.notna(row.get("entry_date")) else "—"}</td>'
            f'<td>{pd.Timestamp(row["exit_date"]).date().isoformat() if pd.notna(row.get("exit_date")) else "OPEN"}</td>'
            f'<td class="ticker">{_esc(row.get("ticker", "—"))}</td><td>{_esc(setup)}</td><td><span class="nq-dot nq-{_esc(nq.lower())}"></span>{_esc(nq)}</td>'
            f'<td class="{_tone(row.get("return_pct"))}">{_pct(row.get("return_pct"), signed=True)}</td>'
            f'<td>{_num(row.get("r_multiple"))}</td><td class="{_tone(pnl)}">{_yen(pnl)}</td>'
            f'<td>{int(row.get("hold_days")) if pd.notna(row.get("hold_days")) else "—"}</td><td>{_esc(row.get("exit_reason", "—"))}</td>'
            f'<td><span class="pill {"ok" if followed else "bad"}">{discipline}</span></td></tr>'
        )
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _candidate_table(frame: pd.DataFrame) -> str:
    columns = [
        ("date", "Date", "date"), ("ticker", "Ticker", "text"), ("traded", "売買", "text"),
        ("setup", "Setup", "text"), ("nq_color", "NQ", "text"), ("forward_10d_return", "10日後", "spct"),
        ("qqq_excess_10d", "QQQ超過", "spct"), ("realized_return", "実現", "spct"), ("capture_gap", "Capture差", "spct"),
    ]
    return _table(frame.sort_values(["date", "ticker"], ascending=[False, True]) if not frame.empty else frame, columns, 100)


def _risk_summary(report: JournalReport) -> str:
    risk = report.portfolio_risk
    heat = _finite(risk.get("correlation_adjusted_heat"))
    nominal = _finite(risk.get("nominal_heat"))
    gross = _finite(risk.get("gross_exposure"))
    cluster = risk.get("largest_cluster") or "—"
    tone = "critical" if heat > 0.024 else "warning" if heat > 0.018 else "good"
    return (
        f'<div class="risk-strip {tone}"><div><span>相関調整Heat</span><strong>{_pct(heat)}</strong></div>'
        f'<div><span>名目Heat</span><strong>{_pct(nominal)}</strong></div>'
        f'<div><span>Gross Exposure</span><strong>{_pct(gross)}</strong></div>'
        f'<div><span>最大クラスター</span><strong>{_esc(cluster)}</strong></div></div>'
    )


def _today_checklist(report: JournalReport) -> str:
    _, action, explanation = _nq_state(report.nq_color)
    violations = len(report.rule_violations)
    holdings = len(report.holdings)
    cash_fraction = _finite(report.kpis.get("cash_fraction"))
    items = [
        ("市場ゲート", action, explanation, "critical" if report.nq_color in {"RED", "UNKNOWN"} else "warning" if report.nq_color == "YELLOW" else "good"),
        ("ポートフォリオ", f"{holdings}銘柄 / 現金 {_pct(cash_fraction)}", "建玉・Heat・同一テーマ集中を保有一覧で確認。", "good"),
        ("規律", f"逸脱検出 {violations}件", "重大違反は振り返りタブで原因と再発防止を確認。", "critical" if violations else "good"),
    ]
    return "".join(
        f'<div class="check-row"><i class="state {tone}"></i><div><span>{_esc(label)}</span><strong>{_esc(value)}</strong><small>{_esc(detail)}</small></div></div>'
        for label, value, detail, tone in items
    )


def _share_copy(report: JournalReport) -> str:
    k = report.kpis
    risk = report.portfolio_risk
    return (
        f"運用実績 {report.as_of.date().isoformat()}\n"
        f"総資産 {_yen(report.account_equity_jpy)}｜本日 {_pct(k.get('daily_return'), signed=True)}｜月初来 {_pct(k.get('mtd_return'), signed=True)}｜年初来 {_pct(k.get('ytd_return'), signed=True)}\n"
        f"PF {_num(k.get('profit_factor'))}｜勝率 {_pct(k.get('win_rate'))}｜最大DD {_pct(k.get('max_drawdown'))}\n"
        f"NQ {report.nq_color}｜Gross {_pct(risk.get('gross_exposure'))}｜相関調整Heat {_pct(risk.get('correlation_adjusted_heat'))}"
    )


def render_dashboard(report: JournalReport, path: Path) -> None:
    k = report.kpis
    risk = report.portfolio_risk
    nq_jp, nq_action, _ = _nq_state(report.nq_color)

    overview_metrics = "".join([
        _metric("本日", _pct(k.get("daily_return"), signed=True), _tone(k.get("daily_return")), "資産ベース"),
        _metric("月初来", _pct(k.get("mtd_return"), signed=True), _tone(k.get("mtd_return")), "MTD"),
        _metric("年初来", _pct(k.get("ytd_return"), signed=True), _tone(k.get("ytd_return")), "YTD"),
        _metric("総損益", _yen(k.get("net_pnl_jpy")), _tone(k.get("net_pnl_jpy")), f"含み {_yen(k.get('unrealized_pnl_jpy'))}"),
        _metric("PF", _num(k.get("profit_factor")), "positive" if _finite(k.get("profit_factor")) > 1 else "negative", f"平均R {_num(k.get('average_r'))}"),
        _metric("最大DD", _pct(k.get("max_drawdown")), "negative", f"回復係数 {_num(k.get('recovery_factor'))}"),
    ])
    performance_metrics = "".join([
        _metric("勝率", _pct(k.get("win_rate")), "neutral", f"{int(k.get('wins', 0))}勝 / {int(k.get('losses', 0))}敗"),
        _metric("平均利益", _yen(k.get("average_win_jpy")), "positive", "勝ちトレード"),
        _metric("平均損失", _yen(k.get("average_loss_jpy")), "negative", "負けトレード"),
        _metric("Payoff", _num(k.get("payoff_ratio")), "neutral", "平均利益÷平均損失"),
        _metric("期待値", _yen(k.get("expectancy_jpy")), _tone(k.get("expectancy_jpy")), "1トレード"),
        _metric("平均保有", f"{_num(k.get('average_hold_days'), 1)}日", "neutral", "決済済み"),
        _metric("CAGR", _pct(k.get("cagr")), _tone(k.get("cagr")), "年率換算"),
        _metric("Sharpe", _num(k.get("sharpe")), "neutral", "日次ベース"),
        _metric("規律遵守率", _pct(k.get("rule_adherence")), "positive" if _finite(k.get("rule_adherence")) >= .9 else "negative", f"逸脱 {int(k.get('rule_break_trades', 0))}件"),
    ])

    holdings_table = _table(report.holdings, [
        ("ticker", "Ticker", "text"), ("market_value_jpy", "評価額", "yen"), ("allocation", "比率", "pct"),
        ("unrealized_pct", "含み", "spct"), ("unrealized_pnl_jpy", "含み損益", "yen"), ("heat_fraction", "Heat", "pct"),
        ("hold_days", "保有日数", "int"), ("stop_price", "Stop", "num"), ("sector", "Sector", "text"),
        ("theme", "Theme", "text"), ("setup", "Setup", "text"),
    ], 100)
    setup_table = _table(report.setup_analysis, [
        ("setup", "Setup", "text"), ("trades", "件数", "int"), ("win_rate", "勝率", "pct"),
        ("profit_factor", "PF", "num"), ("avg_r", "平均R", "num"), ("avg_return", "平均騰落", "spct"),
        ("avg_hold_days", "平均日数", "num"), ("net_pnl_jpy", "損益", "yen"),
    ], 50)
    regime_table = _table(report.regime_analysis, [
        ("nq_color", "NQ色", "text"), ("trades", "件数", "int"), ("win_rate", "勝率", "pct"),
        ("profit_factor", "PF", "num"), ("avg_r", "平均R", "num"), ("avg_return", "平均騰落", "spct"),
        ("avg_hold_days", "平均日数", "num"), ("net_pnl_jpy", "損益", "yen"),
    ], 20)
    missed_table = _table(report.missed_analysis, [
        ("bucket", "区分", "text"), ("candidates", "候補数", "int"), ("avg_forward_10d", "10日後", "spct"),
        ("avg_qqq_excess_10d", "QQQ超過", "spct"), ("positive_rate", "上昇率", "pct"),
    ], 20)
    violation_table = _table(report.rule_violations, [
        ("entry_date", "Entry", "date"), ("ticker", "Ticker", "text"), ("severity", "重要度", "text"),
        ("violation", "違反", "text"), ("detail", "内容", "text"),
    ], 100)
    notes = "".join(f"<li>{_esc(note)}</li>" for note in report.source_notes) or "<li>入力ソースの注記なし</li>"
    share_copy = _share_copy(report)

    css = r'''
:root{--bg:#070a11;--surface:#0d1320;--surface2:#121a2a;--surface3:#182237;--text:#f4f7fb;--muted:#8d99ad;--line:#263149;--accent:#7f9dff;--accent2:#a37aff;--pos:#31d39c;--neg:#ff647c;--warn:#f5c65e;--radius:18px}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 12% 0,#182441 0,#070a11 34%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans JP","Hiragino Sans",sans-serif}.app{max-width:1320px;margin:auto;padding:20px 24px 48px}.topbar{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center;margin-bottom:14px}.brand small{display:block;color:var(--accent);font-size:11px;font-weight:900;letter-spacing:.17em}.brand h1{font-size:30px;line-height:1.15;margin:6px 0}.brand p{margin:0;color:var(--muted);font-size:13px}.account-head{display:flex;gap:10px;align-items:stretch}.head-card{min-width:142px;padding:12px 14px;border:1px solid var(--line);border-radius:15px;background:#101726}.head-card span{display:block;color:var(--muted);font-size:10px}.head-card strong{display:block;font-size:18px;margin-top:4px}.nq-card{border-color:#4562a4}.nq-card small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.tabs{position:sticky;top:0;z-index:50;display:flex;gap:6px;overflow-x:auto;padding:8px;margin:0 -8px 18px;background:#070a11e8;backdrop-filter:blur(14px);border-bottom:1px solid #1d2638;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{flex:0 0 auto;border:1px solid transparent;background:transparent;color:var(--muted);padding:10px 13px;border-radius:11px;font-weight:800;font-size:13px;cursor:pointer}.tab:hover{background:#151d2c;color:var(--text)}.tab[aria-selected="true"]{background:linear-gradient(135deg,#253454,#242b48);border-color:#3b4b70;color:#fff}.tab em{font-style:normal;margin-left:5px;padding:2px 6px;border-radius:999px;background:#222c40;font-size:10px}.tab-panel{display:none}.tab-panel.active{display:block;animation:fade .18s ease}@keyframes fade{from{opacity:.3;transform:translateY(4px)}to{opacity:1;transform:none}}.section-head{display:flex;justify-content:space-between;gap:16px;align-items:end;margin:4px 0 14px}.section-head h2{font-size:25px;margin:0}.section-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.section-head .context{color:var(--muted);font-size:12px;text-align:right}.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.metrics.compact{grid-template-columns:repeat(3,minmax(0,1fr))}.metric,.panel,.decision-card{background:linear-gradient(145deg,var(--surface2),var(--surface));border:1px solid var(--line);box-shadow:0 18px 48px #0004}.metric{padding:14px;border-radius:15px;min-width:0}.metric span,.metric small{display:block;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric strong{display:block;font-size:22px;margin:7px 0}.grid{display:grid;grid-template-columns:1.45fr 1fr;gap:14px;margin-top:14px}.grid.equal{grid-template-columns:1fr 1fr}.panel{padding:17px;border-radius:var(--radius);overflow:hidden}.panel.full{grid-column:1/-1}.panel h3{font-size:17px;margin:0 0 3px}.panel .sub{color:var(--muted);font-size:11px;margin-bottom:13px}.risk-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin-top:14px;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--line)}.risk-strip>div{padding:15px;background:var(--surface)}.risk-strip span{display:block;color:var(--muted);font-size:10px}.risk-strip strong{display:block;font-size:18px;margin-top:5px}.risk-strip.warning{border-color:#725c2e}.risk-strip.critical{border-color:#733447}.checklist{display:grid;gap:9px}.check-row{display:grid;grid-template-columns:10px 1fr;gap:11px;padding:11px 0;border-bottom:1px solid var(--line)}.check-row:last-child{border-bottom:0}.check-row .state{width:9px;height:9px;margin-top:5px;border-radius:50%;background:var(--muted)}.state.good{background:var(--pos);box-shadow:0 0 14px #31d39c66}.state.warning{background:var(--warn)}.state.critical{background:var(--neg)}.check-row span,.check-row small{display:block;color:var(--muted);font-size:10px}.check-row strong{display:block;margin:2px 0;font-size:14px}.chart,.treemap{width:100%;height:auto}.axis,.zero{stroke:#34415b;stroke-width:1}.zero{stroke-dasharray:5 5}.line{fill:none;stroke:var(--accent);stroke-width:3}.area{fill:#7f9dff22}.chart-label{fill:var(--muted);font-size:11px}.heatmap{width:100%;border-collapse:separate;border-spacing:4px}.heatmap th{font-size:10px;color:var(--muted)}.heatmap td{padding:8px 5px;border-radius:6px;text-align:center;font-size:10px;font-weight:800}.heatmap .positive{background:#20c99733;color:#78efc6}.heatmap .negative{background:#ff5c7333;color:#ff95a5}.heatmap .neutral,.heatmap .na{background:#20293a;color:#718096}.heatmap .s4,.heatmap .s5{outline:1px solid #ffffff22}.table-wrap{overflow:auto}.table-wrap.tall{max-height:68vh}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:10px 11px;border-bottom:1px solid var(--line);font-size:11px;text-align:right}th:first-child,td:first-child{text-align:left}thead th{position:sticky;top:0;background:#111827;color:var(--muted);z-index:2}.ticker{font-weight:900;color:#fff}.positive{color:var(--pos)}.negative{color:var(--neg)}.neutral{color:var(--text)}.bars{display:grid;gap:11px}.bar-row{display:grid;grid-template-columns:115px 1fr 56px;gap:9px;align-items:center;font-size:11px}.bar-track{height:8px;background:#222b3d;border-radius:99px;overflow:hidden}.bar-track i{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:99px}.tm-pos{fill:#153f36;stroke:#2ed49b55}.tm-neg{fill:#4d1d2b;stroke:#ff667d55}.tm-flat{fill:#283249;stroke:#66708555}.tm-label{fill:white;font-size:16px;font-weight:800}.tm-sub{fill:#cbd5e1;font-size:11px}.journal-toolbar{display:flex;gap:9px;align-items:end;flex-wrap:wrap;margin-bottom:11px}.journal-toolbar label{display:grid;gap:4px}.journal-toolbar label span{font-size:9px;color:var(--muted);font-weight:800}.journal-toolbar input,.journal-toolbar select{height:36px;border:1px solid var(--line);border-radius:9px;background:#0d1422;color:var(--text);padding:0 10px}.journal-toolbar .search{min-width:240px;flex:1}.ghost,.copy-button{height:36px;border:1px solid var(--line);border-radius:9px;background:#172033;color:var(--text);font-weight:800;padding:0 12px;cursor:pointer}.ghost:hover,.copy-button:hover{border-color:var(--accent)}#trade-count{font-size:11px;color:var(--muted);padding:10px}.pill{display:inline-block;padding:3px 7px;border-radius:999px;font-size:9px;font-weight:900}.pill.ok{background:#193f36;color:#7aebc5}.pill.bad{background:#51202d;color:#ff9aad}.nq-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:#718096}.nq-blue{background:#5f8cff}.nq-green{background:#31d39c}.nq-yellow{background:#f5c65e}.nq-red{background:#ff647c}.review{line-height:1.72;color:#dbe4f3}.review h3{font-size:16px;margin:18px 0 4px}.review p{margin:7px 0}.source-list{color:var(--muted);font-size:11px;line-height:1.7}.share-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.share-card img{display:block;width:100%;border-radius:13px;border:1px solid var(--line);background:#05070c}.share-card .actions{display:flex;gap:8px;margin-top:10px}.share-card a{display:inline-grid;place-items:center;height:36px;padding:0 12px;border-radius:9px;background:#1a2437;color:#fff;text-decoration:none;font-size:11px;font-weight:800}.copy-box{width:100%;min-height:150px;resize:vertical;background:#090f1a;border:1px solid var(--line);border-radius:12px;color:#e7edf7;padding:13px;font:12px/1.7 ui-monospace,SFMono-Regular,Menlo,monospace}.empty{padding:32px;text-align:center;color:var(--muted)}.fineprint{color:var(--muted);font-size:10px;line-height:1.6;margin-top:11px}@media(max-width:1000px){.metrics{grid-template-columns:repeat(3,1fr)}.grid,.grid.equal{grid-template-columns:1fr}.panel.full{grid-column:auto}.share-grid{grid-template-columns:1fr}.risk-strip{grid-template-columns:repeat(2,1fr)}}@media(max-width:680px){.app{padding:12px 12px 32px}.topbar{grid-template-columns:1fr}.brand h1{font-size:24px}.account-head{display:grid;grid-template-columns:1fr 1fr}.head-card{min-width:0}.tabs{margin:0 -12px 12px;padding:8px 12px}.tab{padding:9px 11px}.section-head{display:block}.section-head .context{text-align:left;margin-top:7px}.metrics,.metrics.compact{grid-template-columns:repeat(2,1fr)}.metric strong{font-size:19px}.panel{padding:13px}.risk-strip{grid-template-columns:1fr 1fr}.journal-toolbar{display:grid;grid-template-columns:1fr 1fr}.journal-toolbar .search{grid-column:1/-1;min-width:0}.journal-toolbar .ghost{align-self:end}.heatmap{min-width:760px}.bar-row{grid-template-columns:90px 1fr 50px}.table-wrap.tall{max-height:62vh}}
'''

    js = r'''
(() => {
  const tabs = [...document.querySelectorAll('.tab')];
  const panels = [...document.querySelectorAll('.tab-panel')];
  function activate(id, push = true) {
    if (!panels.some(p => p.id === id)) id = 'today';
    tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === id)));
    panels.forEach(p => p.classList.toggle('active', p.id === id));
    if (push) history.replaceState(null, '', '#' + id);
    window.scrollTo({top: 0, behavior: 'instant'});
  }
  tabs.forEach(t => t.addEventListener('click', () => activate(t.dataset.tab)));
  activate(location.hash.slice(1) || 'today', false);
  const rows = [...document.querySelectorAll('#trade-table tbody tr')];
  const search = document.getElementById('trade-search');
  const setup = document.getElementById('trade-setup');
  const nq = document.getElementById('trade-nq');
  const result = document.getElementById('trade-result');
  const count = document.getElementById('trade-count');
  function filterTrades() {
    if (!rows.length) return;
    const q = (search?.value || '').trim().toLowerCase();
    let visible = 0;
    rows.forEach(row => {
      const show = (!q || row.dataset.search.includes(q)) && (!setup.value || row.dataset.setup === setup.value) && (!nq.value || row.dataset.nq === nq.value) && (!result.value || row.dataset.result === result.value);
      row.hidden = !show;
      if (show) visible++;
    });
    count.textContent = `${visible} / ${rows.length}件`;
  }
  [search, setup, nq, result].filter(Boolean).forEach(el => el.addEventListener('input', filterTrades));
  document.getElementById('trade-reset')?.addEventListener('click', () => { search.value=''; setup.value=''; nq.value=''; result.value=''; filterTrades(); });
  filterTrades();
  document.querySelectorAll('[data-copy-target]').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;
    try { await navigator.clipboard.writeText(target.value || target.textContent); button.textContent = 'コピー済み'; }
    catch { target.select?.(); document.execCommand('copy'); button.textContent = 'コピー済み'; }
    setTimeout(() => button.textContent = 'コピー', 1400);
  }));
})();
'''

    document = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V38 Performance OS</title><style>{css}</style></head><body><main class="app">
<header class="topbar"><div class="brand"><small>V38 PERFORMANCE OS</small><h1>運用実績・ポートフォリオ管理</h1><p>{report.as_of.date().isoformat()}更新｜候補選定・実売買・資産・規律を同じ正本で照合</p></div><div class="account-head"><div class="head-card"><span>総資産</span><strong>{_yen(report.account_equity_jpy)}</strong></div><div class="head-card nq-card"><span>NQゲート</span><strong>{nq_jp} / {nq_action}</strong><small>{_esc(report.nq_color)}</small></div></div></header>
<nav class="tabs" role="tablist" aria-label="Trade Journal navigation"><button class="tab" data-tab="today" role="tab" aria-selected="true">今日</button><button class="tab" data-tab="performance" role="tab" aria-selected="false">資産</button><button class="tab" data-tab="portfolio" role="tab" aria-selected="false">ポートフォリオ <em>{len(report.holdings)}</em></button><button class="tab" data-tab="journal" role="tab" aria-selected="false">取引履歴 <em>{len(report.trades)}</em></button><button class="tab" data-tab="edge" role="tab" aria-selected="false">エッジ分析</button><button class="tab" data-tab="review" role="tab" aria-selected="false">振り返り <em>{len(report.rule_violations)}</em></button><button class="tab" data-tab="share" role="tab" aria-selected="false">共有</button></nav>
<section class="tab-panel active" id="today" role="tabpanel"><div class="section-head"><div><h2>今日の運用</h2><p>朝晩の確認をこの画面だけで完結</p></div><div class="context">現金 {_yen(report.cash_jpy)}｜Gross {_pct(risk.get('gross_exposure'))}</div></div><div class="metrics">{overview_metrics}</div>{_risk_summary(report)}<div class="grid"><div class="panel"><h3>資産推移</h3><div class="sub">入出金調整後</div>{_line_chart_svg(report.equity,'adjusted_equity_jpy')}</div><div class="panel"><h3>今日の確認</h3><div class="sub">市場・建玉・規律</div><div class="checklist">{_today_checklist(report)}</div></div><div class="panel full"><h3>現在保有</h3><div class="sub">日次確認用。詳細はポートフォリオタブ</div>{_table(report.holdings, [('ticker','Ticker','text'),('allocation','比率','pct'),('unrealized_pct','含み','spct'),('heat_fraction','Heat','pct'),('hold_days','日数','int'),('setup','Setup','text'),('sector','Sector','text')], 12)}</div></div></section>
<section class="tab-panel" id="performance" role="tabpanel"><div class="section-head"><div><h2>資産・パフォーマンス</h2><p>結果の見栄えではなく、再現性と下方リスクを確認</p></div><div class="context">取引 {int(k.get('trades',0))}件｜総リターン {_pct(k.get('total_return'), signed=True)}</div></div><div class="metrics compact">{performance_metrics}</div><div class="grid"><div class="panel"><h3>資産曲線</h3><div class="sub">入出金調整後</div>{_line_chart_svg(report.equity,'adjusted_equity_jpy')}</div><div class="panel"><h3>ドローダウン</h3><div class="sub">ピークからの下落率</div>{_line_chart_svg(report.equity,'drawdown',zero_line=True)}</div><div class="panel full"><h3>月次ヒートマップ</h3><div class="sub">月末ベースの入出金調整後リターン</div><div class="table-wrap">{_monthly_heatmap(report.monthly_returns)}</div></div></div></section>
<section class="tab-panel" id="portfolio" role="tabpanel"><div class="section-head"><div><h2>ポートフォリオ</h2><p>評価額・集中・同時破裂リスクを一体で確認</p></div><div class="context">{len(report.holdings)}銘柄｜現金 {_pct(k.get('cash_fraction'))}</div></div>{_risk_summary(report)}<div class="grid"><div class="panel full"><h3>Treemap</h3><div class="sub">面積＝評価額 / 色＝含み損益</div>{_treemap_svg(report.holdings)}</div><div class="panel"><h3>セクター配分</h3><div class="sub">現在評価額ベース</div>{_sector_bars(report.sector_allocation)}</div><div class="panel"><h3>テーマ配分</h3><div class="sub">テーマ集中を確認</div>{_sector_bars(report.theme_allocation)}</div><div class="panel full"><h3>保有一覧</h3><div class="sub">Stop・Heat・保有日数まで表示</div>{holdings_table}</div></div></section>
<section class="tab-panel" id="journal" role="tabpanel"><div class="section-head"><div><h2>Trade Journal</h2><p>検索・Setup・NQ色・勝敗で即座に絞り込み</p></div><div class="context">損益は手数料・FX・Point Value反映後</div></div><div class="panel">{_journal_table(report.trades)}</div></section>
<section class="tab-panel" id="edge" role="tabpanel"><div class="section-head"><div><h2>エッジ分析</h2><p>何を買うかより、どの条件で期待値が残るかを確認</p></div><div class="context">PF・平均R・QQQ超過を優先</div></div><div class="grid equal"><div class="panel"><h3>セットアップ別</h3><div class="sub">勝率だけで判断しない</div>{setup_table}</div><div class="panel"><h3>地合い別</h3><div class="sub">NQ色別の実績</div>{regime_table}</div><div class="panel"><h3>Missed Trade集計</h3><div class="sub">買った候補と見送った候補</div>{missed_table}</div><div class="panel"><h3>候補と実売買の照合</h3><div class="sub">選定・売買・10日後結果・Capture差</div>{_candidate_table(report.candidate_comparison)}</div></div></section>
<section class="tab-panel" id="review" role="tabpanel"><div class="section-head"><div><h2>振り返り・規律</h2><p>負けを正当化せず、再発可能なミスを先に潰す</p></div><div class="context">規律遵守率 {_pct(k.get('rule_adherence'))}</div></div><div class="grid"><div class="panel"><h3>ルール逸脱</h3><div class="sub">重大度・種類・具体的内容</div>{violation_table}</div><div class="panel review"><h3>AI週次レビュー</h3><div class="sub">保存済み数値だけから生成</div>{_review_html(report.weekly_review)}</div><div class="panel full"><h3>データソース・品質</h3><div class="sub">取得元とフォールバックを明示</div><ul class="source-list">{notes}</ul><p class="fineprint">重要入力が欠ける場合は推測値で埋めず、該当指標を不明として扱います。</p></div></div></section>
<section class="tab-panel" id="share" role="tabpanel"><div class="section-head"><div><h2>投稿・共有</h2><p>分析画面とは分離した16:9カードをそのまま使用</p></div><div class="context">1200×675 PNG</div></div><div class="share-grid"><div class="panel share-card"><h3>日次成績カード</h3><div class="sub">本日・MTD・YTD・資産曲線</div><img src="daily_card.png" alt="日次成績カード"><div class="actions"><a href="daily_card.png" download>画像を保存</a></div></div><div class="panel share-card"><h3>ポートフォリオカード</h3><div class="sub">Treemap・配分・Heat</div><img src="portfolio_card.png" alt="ポートフォリオカード"><div class="actions"><a href="portfolio_card.png" download>画像を保存</a></div></div><div class="panel full"><h3>投稿文</h3><div class="sub">$ティッカーを過剰に使わない実績投稿用</div><textarea id="share-copy" class="copy-box" readonly>{_esc(share_copy)}</textarea><div class="actions"><button class="copy-button" type="button" data-copy-target="share-copy">コピー</button><a class="copy-button" href="social_post_ja.txt" download>生成済み投稿文</a></div></div></div></section>
</main><script>{js}</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")

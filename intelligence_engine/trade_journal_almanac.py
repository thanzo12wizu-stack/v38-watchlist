from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .trade_journal import JournalReport


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _yen(value: Any) -> str:
    number = _finite(value)
    sign = "-" if number < 0 else ""
    return f"{sign}¥{abs(number):,.0f}"


def _pct(value: Any, *, signed: bool = False, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{number * 100:.{digits}f}%"


def _num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "∞" if number > 0 else "—"
    return f"{number:,.{digits}f}"


def _adr(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.1f}%" if math.isfinite(number) else "—"


def _safe_value(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        {str(key): _safe_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _monthly_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        year = int(_finite(row.get("year")))
        if not year:
            continue
        for month in range(1, 13):
            value = row.get(month, row.get(str(month)))
            if value is None or pd.isna(value):
                continue
            records.append({"month": f"{year:04d}-{month:02d}", "return": _finite(value)})
    return records


def _script_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _review_html(markdown: str) -> str:
    out: list[str] = []
    list_tag: str | None = None

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line.startswith("###"):
            close_list()
            out.append(f"<h4>{html.escape(line.lstrip('# ').strip())}</h4>")
        elif line.startswith("##") or line.startswith("#"):
            close_list()
            out.append(f"<h3>{html.escape(line.lstrip('# ').strip())}</h3>")
        elif line.startswith(("- ", "* ")):
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{html.escape(line[2:].strip())}</li>")
        elif ". " in line and line.split(". ", 1)[0].isdigit():
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{html.escape(line.split('. ', 1)[1].strip())}</li>")
        else:
            close_list()
            out.append(f"<p>{html.escape(line)}</p>")
    close_list()
    return "".join(out) or '<div class="stub"><b>レビューなし</b>データが蓄積されると週次レビューを表示します。</div>'


def _decision(report: JournalReport) -> dict[str, Any]:
    holdings = report.holdings
    risk = report.portfolio_risk
    nq = str(report.nq_color or "UNKNOWN").upper()
    corr_heat = _finite(risk.get("correlation_adjusted_heat"))
    nominal_heat = _finite(risk.get("nominal_heat"))
    equity_age = report.kpis.get("equity_age_days")
    stale_equity = equity_age is not None and _finite(equity_age) > 7
    event_count = 0
    stop_near = 0
    if not holdings.empty:
        if "event_risk" in holdings:
            event_text = holdings["event_risk"].fillna("").astype(str).str.strip().str.lower()
            event_count = int(
                (~event_text.isin({"", "0", "false", "none", "nan", "unknown", "なし"})).sum()
            )
        if {"current_price", "stop_price"}.issubset(holdings.columns):
            current = pd.to_numeric(holdings["current_price"], errors="coerce")
            stop = pd.to_numeric(holdings["stop_price"], errors="coerce")
            distance = (current - stop) / current.replace(0, np.nan)
            stop_near = int(((distance >= 0) & (distance <= 0.02)).fillna(False).sum())

    if stale_equity:
        level, title, tone = "STOP", "資産データ要更新", "bad"
        reason = f"最終口座評価から{int(_finite(equity_age))}日経過"
    elif nq in {"RED", "UNKNOWN"}:
        level, title, tone = "STOP", "新規発注停止", "bad"
        reason = "市場ゲートが赤または取得不能"
    elif nq == "YELLOW":
        level, title, tone = "STOP", "新規発注停止", "warn"
        reason = "市場ゲートが黄"
    elif corr_heat >= 0.024:
        level, title, tone = "STOP", "新規発注停止", "bad"
        reason = "相関調整Heatが上限帯"
    elif corr_heat >= 0.018 or stop_near >= 2 or event_count >= 2:
        level, title, tone = "CAUTION", "条件付きで発注可", "warn"
        reasons = []
        if corr_heat >= 0.018:
            reasons.append("相関Heat高め")
        if stop_near:
            reasons.append(f"Stop接近{stop_near}銘柄")
        if event_count:
            reasons.append(f"イベント接近{event_count}銘柄")
        reason = "・".join(reasons)
    else:
        level, title, tone = "OPEN", "新規発注可能", "good"
        reason = "市場・Heat・保有リスクは許容範囲"

    return {
        "level": level,
        "title": title,
        "tone": tone,
        "reason": reason,
        "corr_heat": corr_heat,
        "nominal_heat": nominal_heat,
        "event_count": event_count,
        "stop_near": stop_near,
    }


CSS = r'''
:root{--bg:#f5f2ea;--bg-alt:#eee8da;--panel:#fffdf8;--panel2:#faf6ec;--line:#dfd6bf;--line-strong:#c9bc9c;--text:#211d14;--muted:#726a58;--accent:#1f4fa8;--accent-soft:#e6ecf9;--good:#0f6b3f;--good-soft:#e4f2e8;--bad:#a3311a;--bad-soft:#f7e6e1;--warn:#8a5a06;--warn-soft:#f6ecd9;--radius:10px;color-scheme:light}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;max-width:100%;overflow-x:hidden}body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;-webkit-font-smoothing:antialiased}.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}.app{max-width:760px;margin:0 auto;padding:0 0 44px}.topbar{padding:14px 14px 10px;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.brand .mark{font-family:Georgia,"Iowan Old Style","Noto Serif JP",serif;font-size:20px;font-weight:700}.brand .mark small{display:block;margin-top:1px;font-family:inherit;font-size:9px;font-weight:700;letter-spacing:.16em;color:var(--accent);text-transform:uppercase}.asof{font-size:9px;color:var(--muted);text-align:right;line-height:1.5}.acct-line{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid var(--line);font-size:9px;color:var(--muted)}.acct-line span{text-align:center}.acct-line strong{display:block;color:var(--text);font-size:11px;margin-top:2px}
.tabs{position:sticky;top:0;z-index:30;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line-strong);border-bottom:1px solid var(--line-strong)}.tab{display:grid;place-items:center;min-width:0;min-height:39px;padding:7px 3px;font-size:10px;font-weight:800;color:var(--muted);background:var(--bg);border:0;border-bottom:2px solid transparent;white-space:normal;text-align:center;text-decoration:none}.tab[aria-selected="true"]{color:var(--text);border-bottom-color:var(--accent);background:var(--panel)}.tab:active{opacity:.65}.panel-wrap{padding:13px 14px 0}.tab-panel{display:none}.tab-panel.active,.tab-panel:target{display:block}.sec-head{margin:3px 0 10px}.sec-head h2{margin:0;font-family:Georgia,"Iowan Old Style","Noto Serif JP",serif;font-size:19px}.sec-head p{margin:2px 0 0;font-size:10px;color:var(--muted)}.rule{height:1px;margin-top:7px;background:linear-gradient(to right,var(--line-strong) 0 70%,transparent 70%);background-size:6px 1px;background-repeat:repeat-x}
.status-line{display:grid;grid-template-columns:8px minmax(0,1fr) auto;align-items:center;gap:8px;padding:11px 12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--good-soft);margin-bottom:10px;font-size:11px}.status-line.warn{background:var(--warn-soft)}.status-line.bad{background:var(--bad-soft)}.status-dot{width:8px;height:8px;border-radius:50%;background:var(--good)}.status-line.warn .status-dot{background:var(--warn)}.status-line.bad .status-dot{background:var(--bad)}.status-line b{display:block;font-size:12px}.status-line small{display:block;margin-top:2px;color:var(--muted);font-size:9px}.detail-link{color:var(--accent);font-size:9px;font-weight:800;text-decoration:none}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-bottom:10px}.metric{padding:9px 10px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);min-width:0}.metric span{display:block;font-size:8px;color:var(--muted);font-weight:800}.metric strong{display:block;margin-top:4px;font-size:18px;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric small{display:block;margin-top:2px;font-size:8px;color:var(--muted)}.pos{color:var(--good)}.neg{color:var(--bad)}.warn-text{color:var(--warn)}.panel{padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:9px;overflow:hidden}.panel h3{margin:0;font-size:12px}.panel .sub{margin:2px 0 9px;font-size:9px;color:var(--muted)}.fineprint{font-size:9px;color:var(--muted);line-height:1.6;margin-top:4px}.stub{padding:22px 12px;text-align:center;color:var(--muted);font-size:10px;border:1px dashed var(--line-strong);border-radius:var(--radius)}.stub b{display:block;color:var(--text);font-size:11px;margin-bottom:4px}
.bar-row{display:grid;grid-template-columns:92px minmax(0,1fr) 42px;align-items:center;gap:7px;font-size:10px;padding:5px 0}.bar-row+.bar-row{border-top:1px solid var(--line)}.bar-track{height:6px;background:var(--bg-alt);border-radius:99px;overflow:hidden}.bar-track i{display:block;height:100%;background:var(--accent);border-radius:99px}.bar-row b{text-align:right}.conc-row{display:grid;grid-template-columns:18px 48px minmax(0,1fr) 40px 45px;align-items:center;gap:6px;padding:6px 0}.conc-row+.conc-row{border-top:1px solid var(--line)}.conc-rank{font-size:9px;color:var(--muted)}.conc-ticker{font-weight:850;font-size:11px}.conc-track{height:15px;border-radius:5px;background:var(--bg-alt);overflow:hidden}.conc-track i{display:block;height:100%;border-radius:5px}.conc-track.up i{background:#bfe0cc}.conc-track.down i{background:#ecc7bd}.conc-pct,.conc-pnl{text-align:right;font-size:9px;font-weight:800}
.holding-card{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel2);margin-bottom:7px;overflow:hidden}.holding-card summary{list-style:none;cursor:pointer;padding:9px 10px}.holding-card summary::-webkit-details-marker{display:none}.holding-main{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:start}.holding-title{font-size:13px;font-weight:850}.holding-title small{display:block;margin-top:2px;font-size:8px;color:var(--muted)}.holding-pnl{text-align:right;font-size:12px;font-weight:850}.holding-quick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:7px;padding-top:7px;border-top:1px solid var(--line)}.holding-quick div,.holding-detail div{min-width:0}.holding-quick span,.holding-detail span{display:block;color:var(--muted);font-size:7px;font-weight:800}.holding-quick b,.holding-detail b{display:block;margin-top:1px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.holding-detail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 10px;padding:9px 10px 10px;border-top:1px solid var(--line);background:var(--panel)}.holding-card[open] summary{background:#f7f1e5}.risk-badge{display:inline-block;margin-left:5px;padding:1px 5px;border-radius:99px;background:var(--warn-soft);color:var(--warn);font-size:7px;font-weight:800}
.period-bar{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}.period-btn{padding:6px 9px;font-size:9px;font-weight:800;border:1px solid var(--line);border-radius:99px;background:var(--panel);color:var(--muted);cursor:pointer}.period-btn[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}.custom-range{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:6px;margin-bottom:9px;font-size:10px;color:var(--muted)}.custom-range input,.j-toolbar input,.j-toolbar select,.edge-controls select,.edge-controls input{height:34px;min-width:0;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);padding:0 8px;font-size:10px;width:100%;font-family:inherit}.equity-svg{width:100%;height:auto;display:block}.equity-svg .area{fill:#1f4fa81a}.equity-svg .line{fill:none;stroke:var(--accent);stroke-width:2.2}.equity-svg .axis{stroke:var(--line-strong);stroke-width:1}.month-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.month-cell{padding:8px 4px;border-radius:8px;text-align:center;border:1px solid var(--line)}.month-cell .m{display:block;font-size:8px;color:var(--muted);font-weight:800}.month-cell .v{display:block;margin-top:3px;font-size:11px;font-weight:850}.month-cell.up{background:var(--good-soft)}.month-cell.down{background:var(--bad-soft)}
.j-toolbar{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-bottom:8px}.j-toolbar .search{grid-column:1/-1}.j-count{display:flex;justify-content:space-between;align-items:center;font-size:9px;color:var(--muted);margin-bottom:7px}.trade-card{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel2);padding:9px 10px;margin-bottom:6px}.trade-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}.trade-top .tk{font-weight:850;font-size:11px}.trade-top .tk small{margin-left:5px;font-size:8px;color:var(--muted)}.trade-top .pnl{font-weight:850;font-size:11px}.trade-meta{display:flex;flex-wrap:wrap;gap:5px 9px;margin-top:5px;font-size:8px;color:var(--muted)}.nq-dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:3px}.nq-GREEN{background:#0f6b3f}.nq-BLUE{background:#1f4fa8}.nq-YELLOW{background:#8a5a06}.nq-RED{background:#a3311a}.rule-flag{color:var(--bad);font-weight:800}.more-btn,.copy-btn{width:100%;height:36px;border:1px solid var(--line-strong);border-radius:8px;background:var(--panel);color:var(--text);font-weight:800;font-size:10px;cursor:pointer}
.edge-controls{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 70px;gap:6px;margin-bottom:9px}.edge-controls label{display:grid;gap:3px}.edge-controls span{font-size:7px;color:var(--muted);font-weight:800}.rank-head,.rank-row{display:grid;grid-template-columns:minmax(0,1fr) 30px 38px 33px 38px;gap:5px;align-items:center}.rank-head{padding-bottom:4px;border-bottom:1px solid var(--line-strong)}.rank-head span{font-size:7px;color:var(--muted);font-weight:800;text-align:right}.rank-head span:first-child{text-align:left}.rank-row{padding:7px 0;font-size:9px;cursor:pointer}.rank-row+.rank-row{border-top:1px solid var(--line)}.rank-row .lbl{font-weight:800;overflow-wrap:anywhere}.rank-row b{text-align:right}.low-n{opacity:.48}.tag-low{font-size:6px;background:var(--bg-alt);color:var(--muted);border-radius:99px;padding:1px 4px;margin-left:3px}.callout{padding:10px 11px;border-radius:var(--radius);background:var(--accent-soft);border:1px solid #c3d3f0;font-size:10px;margin-bottom:9px}.callout b{display:block;font-size:11px;margin-bottom:2px}.review{font-size:11px;line-height:1.7}.review h3{font-family:Georgia,"Noto Serif JP",serif;font-size:15px;margin:13px 0 4px}.review h4{font-size:9px;margin:13px 0 3px;color:var(--muted);text-transform:uppercase}.review p{margin:0 0 8px}.review li{margin:3px 0}.review ul,.review ol{padding-left:18px}.share-preview{border-radius:14px;background:linear-gradient(160deg,#fdf9ee,#e8dfc9);border:1px solid var(--line-strong);padding:18px 15px;margin-bottom:10px}.share-preview .eyebrow{font-size:8px;letter-spacing:.15em;text-transform:uppercase;color:var(--accent);font-weight:800}.share-preview .headline{font-family:Georgia,"Noto Serif JP",serif;font-size:22px;font-weight:700;margin:7px 0 12px}.share-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.share-stats div{border-top:1px solid var(--line-strong);padding-top:6px}.share-stats span{display:block;font-size:8px;color:var(--muted)}.share-stats strong{display:block;margin-top:2px;font-size:14px}.share-images{display:grid;gap:8px}.share-images img{display:block;width:100%;border:1px solid var(--line);border-radius:9px}.copy-box{width:100%;min-height:110px;background:var(--panel2);border:1px solid var(--line);border-radius:9px;color:var(--text);padding:10px;font:10px/1.6 -apple-system,sans-serif;resize:vertical}.noscript{margin:10px 14px;padding:9px;border:1px solid var(--warn);border-radius:8px;background:var(--warn-soft);font-size:9px}
.portfolio-tools{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px;margin-bottom:8px}.portfolio-tools .sub{margin:0}.compact-btn{min-height:34px;padding:6px 10px;border:1px solid var(--line-strong);border-radius:8px;background:var(--panel);color:var(--text);font-size:9px;font-weight:800;cursor:pointer}.sizer>summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:8px}.sizer>summary::-webkit-details-marker{display:none}.sizer>summary::after{content:'＋';color:var(--accent);font-size:16px}.sizer[open]>summary::after{content:'−'}.sizer-body{padding-top:10px}.sizer-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.sizer-grid label{display:grid;gap:3px;min-width:0}.sizer-grid label.wide{grid-column:1/-1}.sizer-grid span,.sizer-output span{font-size:7px;color:var(--muted);font-weight:800}.sizer-grid input,.sizer-grid select{height:36px;min-width:0;width:100%;padding:0 8px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--text);font:10px -apple-system,sans-serif}.sizer-output{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:9px}.sizer-output div{padding:8px 9px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);min-width:0}.sizer-output b{display:block;margin-top:2px;font-size:11px;white-space:normal;overflow-wrap:anywhere}.sizer-message{margin:8px 0 0;padding:7px 8px;border-radius:7px;background:var(--accent-soft);font-size:8px;line-height:1.5}.sizer-message.bad{background:var(--bad-soft);color:var(--bad)}.risk-badge.good-badge{background:var(--good-soft);color:var(--good)}.risk-badge.badge-neutral{background:var(--bg-alt);color:var(--muted)}
@media(min-width:520px){.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.holding-detail{grid-template-columns:repeat(4,minmax(0,1fr))}.month-grid{grid-template-columns:repeat(6,minmax(0,1fr))}.share-images{grid-template-columns:1fr 1fr}.acct-line{font-size:10px}.acct-line strong{font-size:12px}}
@media(max-width:390px){.portfolio-tools{grid-template-columns:1fr}.compact-btn{width:100%}.sizer-grid,.sizer-output{grid-template-columns:repeat(2,minmax(0,1fr))}.panel-wrap{padding-left:10px;padding-right:10px}}
'''

JS = r'''
(() => {
  const data = window.V38_DATA;
  const tabs = [...document.querySelectorAll('.tab')];
  const panels = [...document.querySelectorAll('.tab-panel')];
  function activate(id) {
    if (!panels.some(p => p.id === id)) id = 'today';
    tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === id)));
    panels.forEach(p => p.classList.toggle('active', p.id === id));
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', () => activate(location.hash.slice(1) || 'today'));
  activate(location.hash.slice(1) || 'today');

  const validNum = v => v !== null && v !== '' && Number.isFinite(Number(v));
  const fmtPct = (v, signed=false, digits=1) => validNum(v) ? `${signed && Number(v)>0?'+':''}${(Number(v)*100).toFixed(digits)}%` : '—';
  const fmtNum = (v, digits=2) => Number(v) === Infinity ? '∞' : validNum(v) ? Number(v).toFixed(digits) : '—';
  const fmtYen = v => validNum(v) ? `${Number(v)<0?'-':''}¥${Math.abs(Math.round(Number(v))).toLocaleString('ja-JP')}` : '—';
  const fmtAdr = v => validNum(v) ? `${Number(v).toFixed(1)}%` : '—';
  const tone = v => validNum(v) ? (Number(v)>0?'pos':Number(v)<0?'neg':'') : '';
  const dateOnly = v => v ? String(v).slice(0,10) : '—';
  const esc = v => String(v??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function renderBars(rows, target, limit=99) {
    const list = rows.slice(0,limit), max = Math.max(0.0001, ...list.map(r => Number(r.allocation||r.value||0)));
    document.getElementById(target).innerHTML = list.map(r => {
      const name = r.sector || r.theme || r.name || 'UNKNOWN';
      const value = Number(r.allocation||r.value||0);
      return `<div class="bar-row"><span>${esc(name)}</span><div class="bar-track"><i style="width:${Math.min(100,value/max*100).toFixed(0)}%"></i></div><b class="num">${fmtPct(value)}</b></div>`;
    }).join('') || '<div class="stub">配分データなし</div>';
  }
  renderBars(data.sectorAllocation,'sector-bars');
  renderBars(data.themeAllocation,'theme-bars',8);

  const holdings = [...data.holdings].sort((a,b)=>Number(b.allocation||0)-Number(a.allocation||0));
  const maxAlloc = Math.max(0.0001,...holdings.map(h=>Number(h.allocation||0)));
  document.getElementById('conc-list').innerHTML = holdings.map((h,i)=>`<div class="conc-row"><span class="conc-rank">${i+1}</span><span class="conc-ticker">${esc(h.ticker)}</span><span class="conc-track ${Number(h.unrealized_pct||0)>=0?'up':'down'}"><i style="width:${(Number(h.allocation||0)/maxAlloc*100).toFixed(0)}%"></i></span><span class="conc-pct num">${fmtPct(h.allocation)}</span><span class="conc-pnl num ${tone(h.unrealized_pct)}">${fmtPct(h.unrealized_pct,true)}</span></div>`).join('') || '<div class="stub">保有なし</div>';

  function stopDistance(h){ const c=Number(h.current_price||0), s=Number(h.stop_price||0); return c ? (c-s)/c : 0; }
  const capBadge = h => h.capitulation_status === 'WAITING'
    ? '<span class="risk-badge">セリクラ待ち</span>'
    : h.capitulation_status === 'DONE'
      ? '<span class="risk-badge good-badge">セリクラ済</span>'
      : '';
  const partialBadge = h => h.partial_take_due
    ? '<span class="risk-badge">+25% 利確待ち</span>'
    : h.partial_taken
      ? '<span class="risk-badge good-badge">25% 利確済</span>'
      : '';
  const trancheLabel = h => Number(h.entry_stage||1) >= 2 ? '2nd組入済' : '1stのみ';
  document.getElementById('holdings-cards').innerHTML = holdings.map(h=>`<details class="holding-card"><summary><div class="holding-main"><div><div class="holding-title">${esc(h.ticker)}${h.event_risk?'<span class="risk-badge">EVENT</span>':''}${capBadge(h)}${partialBadge(h)}<small>${esc(h.setup||'UNKNOWN')}｜${esc(h.sector||'UNKNOWN')}</small></div><div class="holding-quick"><div><span>配分</span><b class="num">${fmtPct(h.allocation)}</b></div><div><span>保有</span><b class="num">${Number(h.hold_days||0)}日</b></div><div><span>Stop距離</span><b class="num ${stopDistance(h)<=.02?'neg':''}">${fmtPct(stopDistance(h),true)}</b></div></div></div><div class="holding-pnl num ${tone(h.unrealized_pct)}">${fmtPct(h.unrealized_pct,true)}<small style="display:block;color:var(--muted);font-size:7px;margin-top:2px">${fmtYen(h.unrealized_pnl_jpy)}</small></div></div></summary><div class="holding-detail"><div><span>現在値</span><b class="num">${fmtNum(h.current_price)}</b></div><div><span>平均Entry</span><b class="num">${fmtNum(h.entry_price)}</b></div><div><span>撤退線</span><b class="num">${fmtNum(h.stop_price)}</b></div><div><span>撤退方法</span><b>${esc(h.stop_method==='10MA'?'10MA':'21EMA Low')}</b></div><div><span>ADR%</span><b class="num">${fmtAdr(h.adr_pct)}</b></div><div><span>Heat</span><b class="num">${fmtPct(h.heat_fraction)}</b></div><div><span>評価額</span><b class="num">${fmtYen(h.market_value_jpy)}</b></div><div><span>Theme</span><b>${esc(h.theme||'UNKNOWN')}</b></div><div><span>Entry日</span><b class="num">${dateOnly(h.entry_date)}</b></div><div><span>2分割Entry</span><b>${trancheLabel(h)}</b></div><div><span>1st / 2nd</span><b class="num">${fmtNum(h.entry_price_1)} / ${fmtNum(h.entry_price_2)}</b></div><div><span>+25%ルール</span><b>${h.partial_take_due?'25%利確候補':h.partial_taken?'利確済・残りをトレール':'未到達'}</b></div><div><span>セリクラ</span><b>${h.capitulation_status==='WAITING'?'待ち':h.capitulation_status==='DONE'?'済':'設定なし'}</b></div><div><span>Event</span><b>${esc(h.event_risk_label||'なし')}</b></div></div></details>`).join('') || '<div class="stub">保有なし</div>';

  async function copyText(value, button) {
    try { await navigator.clipboard.writeText(value); }
    catch {
      const area=document.createElement('textarea');area.value=value;area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();document.execCommand('copy');area.remove();
    }
    const old=button.textContent;button.textContent='コピー済み';setTimeout(()=>button.textContent=old,1200);
  }
  const copyHoldings=document.getElementById('copy-holdings');
  copyHoldings?.addEventListener('click',()=>copyText(holdings.map(h=>h.ticker).filter(Boolean).join(' '),copyHoldings));

  const sizerIds=['sz-equity','sz-risk','sz-cap','sz-fx','sz-entry1','sz-entry2','sz-split1','sz-stop-method','sz-stop21','sz-stop10'];
  const sz=id=>document.getElementById(id);
  function renderSizer(){
    const equity=Number(sz('sz-equity').value),riskPct=Number(sz('sz-risk').value),capPct=Number(sz('sz-cap').value),fx=Number(sz('sz-fx').value),entry1=Number(sz('sz-entry1').value),entry2=Number(sz('sz-entry2').value),split=Math.max(0,Math.min(1,Number(sz('sz-split1').value)/100)),method=sz('sz-stop-method').value,stop=Number(sz(method==='10MA'?'sz-stop10':'sz-stop21').value),message=sz('sz-message');
    const second=entry2>0?entry2:entry1,estimated=entry1*split+second*(1-split);
    if(!(equity>0&&riskPct>0&&capPct>0&&fx>0&&entry1>0&&estimated>stop&&stop>0)){
      ['sz-avg','sz-qty','sz-tranches','sz-value','sz-loss','sz-partial','sz-runner','sz-trail'].forEach(id=>sz(id).textContent='—');message.className='sizer-message bad';message.textContent='口座、リスク、FX、Entry、選択した撤退線を入力。撤退線は平均Entryより下に設定してください。';return;
    }
    const riskBudget=equity*riskPct/100,capBudget=equity*capPct/100,byRisk=Math.floor(riskBudget/((estimated-stop)*fx)),byCap=Math.floor(capBudget/(estimated*fx));let qty=Math.max(0,Math.min(byRisk,byCap)),q1=0,q2=0,avg=estimated,value=0,loss=0;while(qty>0){q1=qty===1?1:Math.max(1,Math.min(qty-1,Math.round(qty*split)));q2=qty-q1;avg=(entry1*q1+second*q2)/qty;value=qty*avg*fx;loss=qty*(avg-stop)*fx;if(value<=capBudget+.01&&loss<=riskBudget+.01)break;qty-=1}if(qty===0){q1=0;q2=0;avg=estimated;value=0;loss=0}const partial=qty?Math.max(1,Math.round(qty*.25)):0,runner=Math.max(0,qty-partial),target=avg*1.25,binding=byRisk<=byCap?`リスク${riskPct}%側`:`建率${capPct}%上限側`;
    sz('sz-avg').textContent=fmtNum(avg);sz('sz-qty').textContent=`${qty.toLocaleString('ja-JP')}株`;sz('sz-tranches').textContent=`${q1}株 / ${q2}株`;sz('sz-value').textContent=`${fmtYen(value)} (${fmtPct(value/equity)})`;sz('sz-loss').textContent=fmtYen(loss);sz('sz-partial').textContent=`${fmtNum(target)} で ${partial}株`;sz('sz-runner').textContent=`${runner}株`;sz('sz-trail').textContent=method==='10MA'?'10MA':'21EMA Low';message.className='sizer-message';message.textContent=`${binding}がボトルネック。+25%で25%を利確し、残り75%は選択線を終値で割れたら翌日撤退。`;
  }
  sizerIds.forEach(id=>sz(id)?.addEventListener('input',renderSizer));renderSizer();

  document.getElementById('corr-pairs').innerHTML = (data.correlationPairs||[]).slice(0,10).map(pair=>{
    const corr=Number(pair.correlation||0), width=Math.max(0,Math.min(100,(corr+1)*50));
    return `<div class="pair-row"><span><b>${esc(pair.ticker_a)}</b> × <b>${esc(pair.ticker_b)}</b></span><span class="pair-track"><i style="width:${width.toFixed(0)}%"></i></span><strong class="num ${corr>=.7?'warn-text':''}">${corr.toFixed(2)}</strong></div>`;
  }).join('') || '<div class="stub">相関計算に必要な価格履歴なし</div>';

  document.getElementById('dd-list').innerHTML = (data.drawdowns||[]).slice(0,8).map(dd=>`<div class="dd-row"><div><b class="num neg">${fmtPct(dd.depth)}</b><small>${dateOnly(dd.start_date)} → ${dd.status==='ACTIVE'?'継続中':dateOnly(dd.recovery_date)}</small></div><div><span>谷まで</span><b class="num">${Number(dd.days_to_trough||0)}日</b></div><div><span>全期間</span><b class="num">${Number(dd.total_days||0)}日</b></div><em class="${dd.status==='ACTIVE'?'active-dd':''}">${dd.status==='ACTIVE'?'ACTIVE':'回復'}</em></div>`).join('') || '<div class="stub">Drawdownなし</div>';

  const selectionRows=data.missedAnalysis||[];
  document.getElementById('candidate-selection').innerHTML = selectionRows.map(row=>`<div class="selection-row"><div><b>${esc(row.bucket)}</b><small>n=${Number(row.candidates||0)}</small></div><div><span>10日</span><b class="num ${tone(row.avg_forward_10d)}">${fmtPct(row.avg_forward_10d,true)}</b></div><div><span>QQQ超過</span><b class="num ${tone(row.avg_qqq_excess_10d)}">${fmtPct(row.avg_qqq_excess_10d,true)}</b></div><div><span>勝率</span><b class="num">${fmtPct(row.positive_rate)}</b></div></div>`).join('') || '<div class="stub">候補のフォワード結果が蓄積されると比較します</div>';

  const trades = [...data.trades].sort((a,b)=>String(b.exit_date||'').localeCompare(String(a.exit_date||'')));
  let shown = 20;
  const search=document.getElementById('j-search'), setup=document.getElementById('j-setup'), nq=document.getElementById('j-nq'), result=document.getElementById('j-result');
  const setups=[...new Set(trades.map(t=>t.setup).filter(Boolean))].sort(); setup.innerHTML='<option value="">Setup すべて</option>'+setups.map(x=>`<option>${x}</option>`).join('');
  function filteredTrades(){ const q=(search.value||'').trim().toLowerCase(); return trades.filter(t=>(!q||[t.ticker,t.sector,t.theme,t.exit_reason].join(' ').toLowerCase().includes(q))&&(!setup.value||t.setup===setup.value)&&(!nq.value||t.nq_color===nq.value)&&(!result.value||(result.value==='win'?Number(t.net_pnl_jpy)>0:Number(t.net_pnl_jpy)<=0))); }
  function renderTrades(reset=false){ if(reset) shown=20; const list=filteredTrades(); const visible=list.slice(0,shown); document.getElementById('j-count').innerHTML=`<span>${visible.length} / ${list.length}件</span><span>全${trades.length}件</span>`; document.getElementById('j-list').innerHTML=visible.map(t=>`<div class="trade-card"><div class="trade-top"><span class="tk">${esc(t.ticker)}<small>${esc(t.setup||'UNKNOWN')}</small></span><span class="pnl num ${tone(t.net_pnl_jpy)}">${fmtPct(t.return_pct,true)}｜${fmtNum(t.r_multiple)}R</span></div><div class="trade-meta"><span>${dateOnly(t.entry_date)} → ${dateOnly(t.exit_date)}</span><span><i class="nq-dot nq-${esc(t.nq_color)}"></i>${esc(t.nq_color)}</span><span>${Number(t.hold_days||0)}日</span><span>${esc(t.exit_reason||'—')}</span>${t.partial_exit?'<span>分割利確</span>':''}${t.rule_followed===false?'<span class="rule-flag">規律逸脱</span>':''}<span class="num ${tone(t.net_pnl_jpy)}">${fmtYen(t.net_pnl_jpy)}</span></div></div>`).join('')||'<div class="stub">該当トレードなし</div>'; document.getElementById('j-more').hidden=shown>=list.length; }
  [search,setup,nq,result].forEach(el=>el.addEventListener('input',()=>renderTrades(true))); document.getElementById('j-more').addEventListener('click',()=>{shown+=20;renderTrades();}); renderTrades();

  const PERIODS=[['1m','1ヶ月',1],['3m','3ヶ月',3],['6m','6ヶ月',6],['ytd','YTD',0],['1y','1年',12],['all','全期間',999],['custom','指定',-1]];
  const refDate=new Date(`${data.asOf}T00:00:00`);
  function iso(d){return d.toISOString().slice(0,10)} function fromFor(key){if(key==='all')return'1900-01-01';if(key==='ytd')return `${refDate.getFullYear()}-01-01`;const p=PERIODS.find(x=>x[0]===key);const d=new Date(refDate);d.setMonth(d.getMonth()-p[2]);return iso(d)}
  function mountPeriod(barId,customId,fromId,toId,onChange,initial){const bar=document.getElementById(barId),box=document.getElementById(customId);bar.innerHTML=PERIODS.map(p=>`<button class="period-btn" data-key="${p[0]}" aria-pressed="${p[0]===initial}">${p[1]}</button>`).join('');function set(k){bar.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.key===k)));box.hidden=k!=='custom'}bar.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const k=b.dataset.key;set(k);if(k==='custom'){onChange(document.getElementById(fromId).value||fromFor('1m'),document.getElementById(toId).value||data.asOf,k)}else onChange(fromFor(k),data.asOf,k)});[fromId,toId].forEach(id=>document.getElementById(id).addEventListener('change',()=>{set('custom');onChange(document.getElementById(fromId).value,document.getElementById(toId).value,'custom')}));onChange(fromFor(initial),data.asOf,initial)}
  function tradesRange(from,to){return trades.filter(t=>t.exit_date&&t.exit_date>=from&&t.exit_date<=to)}
  function stats(list){const wins=list.filter(t=>Number(t.net_pnl_jpy)>0),losses=list.filter(t=>Number(t.net_pnl_jpy)<=0),gp=wins.reduce((s,t)=>s+Number(t.net_pnl_jpy||0),0),gl=-losses.reduce((s,t)=>s+Number(t.net_pnl_jpy||0),0);return{n:list.length,wr:list.length?wins.length/list.length:null,pf:list.length?(gl?gp/gl:(gp?Infinity:0)):null,r:list.length?list.reduce((s,t)=>s+Number(t.r_multiple||0),0)/list.length:null,pnl:list.reduce((s,t)=>s+Number(t.net_pnl_jpy||0),0)}}
  function equityRange(from,to){return data.equity.filter(x=>x.date>=from&&x.date<=to)}
  function renderCurve(rows){const values=rows.map(x=>Number(x.adjusted_equity_jpy||x.equity_jpy||0));const svg=document.getElementById('equity-svg');if(!values.length){svg.innerHTML='';return}const w=600,h=190,p=8,min=Math.min(...values),max=Math.max(...values),xs=values.map((_,i)=>p+(values.length===1?0:i/(values.length-1))*(w-2*p)),ys=values.map(v=>h-p-(v-min)/((max-min)||1)*(h-2*p)),pts=xs.map((x,i)=>`${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' '),area=`${p},${h-p} ${pts} ${w-p},${h-p}`;svg.innerHTML=`<polygon class="area" points="${area}"></polygon><polyline class="line" points="${pts}"></polyline><line class="axis" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"></line>`}
  function renderMonths(rows){const out={};rows.forEach(x=>{const key=String(x.month);out[key]=x});document.getElementById('month-grid').innerHTML=Object.entries(out).sort().map(([k,x])=>`<div class="month-cell ${Number(x.return||0)>=0?'up':'down'}"><span class="m">${k}</span><span class="v num ${tone(x.return)}">${fmtPct(x.return,true)}</span></div>`).join('')||'<div class="stub" style="grid-column:1/-1">月次データなし</div>'}
  function updateAssets(from,to){const e=equityRange(from,to),t=tradesRange(from,to),s=stats(t);let ret=null,dd=null;if(e.length){const first=Number(e[0].adjusted_equity_jpy||e[0].equity_jpy||0),last=Number(e[e.length-1].adjusted_equity_jpy||e[e.length-1].equity_jpy||0),gapDays=(new Date(`${e[0].date}T00:00:00`)-new Date(`${from}T00:00:00`))/86400000;if((from==='1900-01-01'||gapDays<=7)&&first)ret=last/first-1;dd=Math.min(...e.map(x=>Number(x.drawdown||0)))}document.getElementById('a-ret').textContent=fmtPct(ret,true);document.getElementById('a-ret').className=`num ${tone(ret)}`;document.getElementById('a-pf').textContent=fmtNum(s.pf);document.getElementById('a-wr').textContent=fmtPct(s.wr);document.getElementById('a-r').textContent=fmtNum(s.r);document.getElementById('a-dd').textContent=fmtPct(dd);document.getElementById('a-n').textContent=s.n;renderCurve(e);renderMonths(data.monthlyReturns.filter(x=>x.month>=from.slice(0,7)&&x.month<=to.slice(0,7)))}
  mountPeriod('assets-period','assets-custom','assets-from','assets-to',updateAssets,'ytd');

  const HOLD_BUCKETS=[[0,7,'0-7日'],[8,14,'8-14日'],[15,21,'15-21日'],[22,30,'22-30日'],[31,9999,'31日+']],R_BUCKETS=[[-999,-1,'< -1R'],[-1,0,'-1〜0R'],[0,1,'0〜1R'],[1,2,'1〜2R'],[2,3,'2〜3R'],[3,999,'3R+']];
  const bucket=(v,b)=>{for(const [lo,hi,l] of b)if(v>=lo&&v<hi)return l;return b[b.length-1][2]};
  const axisFn={setup:t=>t.setup||'UNKNOWN',nq:t=>t.nq_color||'UNKNOWN',sector:t=>t.sector||'UNKNOWN',theme:t=>t.theme||'UNKNOWN',weekday:t=>new Date(`${t.entry_date}T00:00:00`).toLocaleDateString('ja-JP',{weekday:'short'}),holdBucket:t=>bucket(Number(t.hold_days||0),HOLD_BUCKETS),rBucket:t=>bucket(Number(t.r_multiple||0),R_BUCKETS),setupNq:t=>`${t.setup||'UNKNOWN'} × ${t.nq_color||'UNKNOWN'}`};
  let edgeRange=[fromFor('all'),data.asOf];
  function renderEdge(){const list=tradesRange(...edgeRange),axis=document.getElementById('edge-axis').value,sort=document.getElementById('edge-sort').value,minn=Number(document.getElementById('edge-minn').value||1),groups=new Map();list.forEach(t=>{const k=axisFn[axis](t);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(t)});let rows=[...groups].map(([k,v])=>({k,...stats(v)}));rows.sort((a,b)=>Number(b[sort]||0)-Number(a[sort]||0));const valid=rows.filter(r=>r.n>=minn),best=valid[0];document.getElementById('edge-callout').innerHTML=best?`<b>現時点の上位条件：${esc(best.k)}</b>n=${best.n}｜PF ${fmtNum(best.pf)}｜平均R ${fmtNum(best.r)}。サンプル数を優先して解釈してください。`:'<b>十分なサンプルなし</b>期間または最小件数を調整してください。';document.getElementById('rank-body').innerHTML=rows.map(r=>`<div class="rank-row ${r.n<minn?'low-n':''}" data-key="${esc(r.k)}"><span class="lbl">${esc(r.k)}${r.n<minn?'<span class="tag-low">n少</span>':''}</span><b>${r.n}</b><b>${fmtPct(r.wr)}</b><b>${fmtNum(r.pf)}</b><b>${fmtNum(r.r)}</b></div>`).join('')||'<div class="stub">該当データなし</div>';document.querySelectorAll('.rank-row').forEach(row=>row.addEventListener('click',()=>{const key=row.dataset.key.split(' × ')[0];search.value='';setup.value='';nq.value='';if(axis==='setup'||axis==='setupNq')setup.value=key;else if(axis==='nq')nq.value=key;else search.value=key;location.hash='#journal';renderTrades(true)}));const violations=(data.ruleViolations||[]).filter(v=>v.entry_date&&v.entry_date>=edgeRange[0]&&v.entry_date<=edgeRange[1]);document.getElementById('rule-violations').innerHTML=violations.slice(0,12).map(v=>`<div class="trade-card"><div class="trade-top"><span class="tk">${esc(v.ticker)}<small>${dateOnly(v.entry_date)}</small></span><span class="pnl neg">${esc(v.violation)}</span></div><div class="trade-meta"><span>${esc(v.severity||'')}</span><span>${esc(v.detail||'')}</span></div></div>`).join('')||'<div class="stub">規律違反なし</div>'}
  mountPeriod('edge-period','edge-custom','edge-from','edge-to',(f,t)=>{edgeRange=[f,t];renderEdge()},'all');['edge-axis','edge-sort','edge-minn'].forEach(id=>document.getElementById(id).addEventListener('input',renderEdge));

  document.querySelectorAll('[data-copy-target]').forEach(btn=>btn.addEventListener('click',async()=>{const target=document.getElementById(btn.dataset.copyTarget);try{await navigator.clipboard.writeText(target.value||target.textContent)}catch{target.select?.();document.execCommand('copy')}const old=btn.textContent;btn.textContent='コピー済み';setTimeout(()=>btn.textContent=old,1200)}));
})();
'''


def render_dashboard(report: JournalReport, path: Path) -> None:
    decision = _decision(report)
    k = report.kpis
    risk = report.portfolio_risk
    holdings = _records(report.holdings)
    trades = _records(report.trades)
    equity = _records(report.equity)
    monthly = _monthly_records(report.monthly_returns)
    sectors = _records(report.sector_allocation)
    themes = _records(report.theme_allocation)
    violations = _records(report.rule_violations)
    drawdowns = _records(report.drawdown_episodes)
    correlation_pairs = _records(report.correlation_pairs)
    missed_analysis = _records(report.missed_analysis)
    candidate_comparison = _records(report.candidate_comparison)
    share_copy = (
        f"運用実績 {report.as_of.date().isoformat()}\n"
        f"総資産 {_yen(report.account_equity_jpy)}｜本日 {_pct(k.get('daily_return'), signed=True)}｜月初来 {_pct(k.get('mtd_return'), signed=True)}｜年初来 {_pct(k.get('ytd_return'), signed=True)}\n"
        f"PF {_num(k.get('profit_factor'))}｜勝率 {_pct(k.get('win_rate'))}｜平均R {_num(k.get('average_r'))}｜最大DD {_pct(k.get('max_drawdown'))}"
    )
    payload = {
        "asOf": report.as_of.date().isoformat(),
        "accountEquityJpy": report.account_equity_jpy,
        "holdings": holdings,
        "trades": trades,
        "equity": equity,
        "monthlyReturns": monthly,
        "sectorAllocation": sectors,
        "themeAllocation": themes,
        "ruleViolations": violations,
        "drawdowns": drawdowns,
        "correlationPairs": correlation_pairs,
        "missedAnalysis": missed_analysis,
        "candidateComparison": candidate_comparison,
    }
    top_watch: list[dict[str, Any]] = []
    for row in holdings:
        current = _finite(row.get("current_price"))
        stop = _finite(row.get("stop_price"))
        row = dict(row)
        row["stop_distance"] = (current - stop) / current if current else 0.0
        top_watch.append(row)
    top_watch.sort(key=lambda x: x["stop_distance"])
    watch_html = "".join(
        f'''<details class="holding-card"><summary><div class="holding-main"><div><div class="holding-title">{html.escape(str(row.get('ticker') or '—'))}<small>{html.escape(str(row.get('setup') or 'UNKNOWN'))}</small></div><div class="holding-quick"><div><span>Stop</span><b class="num">{_num(row.get('stop_price'))}</b></div><div><span>Stop距離</span><b class="num {'neg' if row['stop_distance'] <= .02 else ''}">{_pct(row['stop_distance'], signed=True)}</b></div><div><span>保有</span><b class="num">{int(_finite(row.get('hold_days')))}日</b></div></div></div><div class="holding-pnl num {'pos' if _finite(row.get('unrealized_pct')) >= 0 else 'neg'}">{_pct(row.get('unrealized_pct'), signed=True)}</div></div></summary></details>'''
        for row in top_watch[:3]
    ) or '<div class="stub">保有なし</div>'
    review = _review_html(report.weekly_review)
    source_notes = "".join(f"<li>{html.escape(str(note))}</li>" for note in report.source_notes) or "<li>注記なし</li>"
    document = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V38 Trade Journal — Almanac</title><style>{CSS}</style></head><body><main class="app"><header class="topbar"><div class="brand"><div class="mark"><small>V38 Command Center</small>Trade Journal Almanac</div><div class="asof">{report.as_of.date().isoformat()}<br>集計基準日</div></div><div class="acct-line"><span>現金<strong class="num">{_yen(report.cash_jpy)}</strong></span><span>総資産<strong class="num">{_yen(report.account_equity_jpy)}</strong></span><span>Gross<strong class="num">{_pct(risk.get('gross_exposure'))}</strong></span></div></header>
<nav class="tabs" role="tablist" aria-label="Trade Journal navigation"><a class="tab" href="#today" data-tab="today" role="tab" aria-controls="today" aria-selected="true">今日</a><a class="tab" href="#assets" data-tab="assets" role="tab" aria-controls="assets" aria-selected="false">資産</a><a class="tab" href="#portfolio" data-tab="portfolio" role="tab" aria-controls="portfolio" aria-selected="false">保有</a><a class="tab" href="#journal" data-tab="journal" role="tab" aria-controls="journal" aria-selected="false">履歴</a><a class="tab" href="#edge" data-tab="edge" role="tab" aria-controls="edge" aria-selected="false">エッジ</a><a class="tab" href="#review" data-tab="review" role="tab" aria-controls="review" aria-selected="false">振り返り</a><a class="tab" href="#share" data-tab="share" role="tab" aria-controls="share" aria-selected="false">共有</a></nav><noscript><div class="noscript">JavaScriptなしでもタブリンクから各画面へ移動できます。分析・絞り込みにはJavaScriptが必要です。</div></noscript><div class="panel-wrap">
<section class="tab-panel active" id="today"><div class="sec-head"><h2>今日の運用</h2><p>意思決定に必要な数字だけを集約</p><div class="rule"></div></div><div class="status-line {decision['tone']}"><span class="status-dot"></span><span><b>{html.escape(decision['title'])}</b><small>{html.escape(decision['reason'])}</small></span><a class="detail-link" href="#portfolio">内訳 →</a></div><div class="metrics"><div class="metric"><span>本日</span><strong class="num {'pos' if _finite(k.get('daily_return')) >= 0 else 'neg'}">{_pct(k.get('daily_return'),signed=True)}</strong><small>資産ベース</small></div><div class="metric"><span>月初来</span><strong class="num {'pos' if _finite(k.get('mtd_return')) >= 0 else 'neg'}">{_pct(k.get('mtd_return'),signed=True)}</strong><small>MTD</small></div><div class="metric"><span>年初来</span><strong class="num {'pos' if _finite(k.get('ytd_return')) >= 0 else 'neg'}">{_pct(k.get('ytd_return'),signed=True)}</strong><small>YTD</small></div><div class="metric"><span>最大DD</span><strong class="num neg">{_pct(k.get('max_drawdown'))}</strong><small>全期間</small></div></div><div class="panel"><h3>今日見る銘柄</h3><div class="sub">Stopまでの距離が近い順。タップで最小情報だけ確認</div>{watch_html}</div><div class="metrics"><div class="metric"><span>相関調整Heat</span><strong class="num">{_pct(risk.get('correlation_adjusted_heat'))}</strong></div><div class="metric"><span>名目Heat</span><strong class="num">{_pct(risk.get('nominal_heat'))}</strong></div><div class="metric"><span>Stop接近</span><strong class="num">{decision['stop_near']}銘柄</strong></div><div class="metric"><span>イベント接近</span><strong class="num">{decision['event_count']}銘柄</strong></div></div><p class="fineprint">候補銘柄は約定扱いにしません。実際の保有・約定・入出金だけを実績へ反映します。</p></section>
<section class="tab-panel" id="assets"><div class="sec-head"><h2>資産推移</h2><p>期間を変えると実口座評価額ベースで再計算</p><div class="rule"></div></div><div class="period-bar" id="assets-period"></div><div class="custom-range" id="assets-custom" hidden><input type="date" id="assets-from"><span>〜</span><input type="date" id="assets-to"></div><div class="metrics"><div class="metric"><span>リターン</span><strong class="num" id="a-ret">—</strong></div><div class="metric"><span>PF</span><strong class="num" id="a-pf">—</strong></div><div class="metric"><span>勝率</span><strong class="num" id="a-wr">—</strong></div><div class="metric"><span>平均R</span><strong class="num" id="a-r">—</strong></div><div class="metric"><span>最大DD</span><strong class="num neg" id="a-dd">—</strong></div><div class="metric"><span>取引数</span><strong class="num" id="a-n">—</strong></div></div><div class="panel"><h3>Equity Curve</h3><div class="sub">入出金調整後の日次口座評価額</div><svg class="equity-svg" viewBox="0 0 600 190" id="equity-svg"></svg></div><div class="panel"><h3>月次リターン</h3><div class="sub">選択期間に含まれる月をすべて表示</div><div class="month-grid" id="month-grid"></div></div><div class="panel"><h3>Drawdown Episodes</h3><div class="sub">深さ順。回復済みと継続中を分離</div><div id="dd-list"></div></div></section>
<section class="tab-panel" id="portfolio"><div class="sec-head"><h2>ポートフォリオ</h2><p>{len(report.holdings)}銘柄｜サイズ計算・撤退・部分利確まで一画面</p><div class="rule"></div></div><div class="metrics"><div class="metric"><span>相関調整Heat</span><strong class="num">{_pct(risk.get('correlation_adjusted_heat'))}</strong></div><div class="metric"><span>名目Heat</span><strong class="num">{_pct(risk.get('nominal_heat'))}</strong></div><div class="metric"><span>Gross</span><strong class="num">{_pct(risk.get('gross_exposure'))}</strong></div><div class="metric"><span>ポートフォリオADR%</span><strong class="num">{_adr(risk.get('portfolio_adr_pct'))}</strong><small>評価額加重・カバー率 {_pct(risk.get('adr_coverage'))}</small></div><div class="metric"><span>最大クラスター</span><strong>{html.escape(str(risk.get('largest_cluster') or '—'))}</strong></div><div class="metric"><span>保有数</span><strong class="num">{len(report.holdings)}銘柄</strong></div></div>
<details class="panel sizer" id="sizing-calculator"><summary><span><h3>自由サイジング</h3><span class="sub">2分割Entry × 21EMA Low / 10MA × +25%で25%利確</span></span></summary><div class="sizer-body"><div class="sizer-grid"><label><span>口座総資産（円）</span><input id="sz-equity" type="number" inputmode="decimal" min="0" value="{_finite(report.account_equity_jpy):.0f}"></label><label><span>1トレードリスク%</span><input id="sz-risk" type="number" inputmode="decimal" min="0.01" step="0.1" value="0.6"></label><label><span>建率上限%</span><input id="sz-cap" type="number" inputmode="decimal" min="0.1" step="0.5" value="8"></label><label><span>FX→円（日本株は1）</span><input id="sz-fx" type="number" inputmode="decimal" min="0.0001" step="0.01" value="1"></label><label><span>1st Entry</span><input id="sz-entry1" type="number" inputmode="decimal" min="0" step="0.01" placeholder="100"></label><label><span>2nd Entry</span><input id="sz-entry2" type="number" inputmode="decimal" min="0" step="0.01" placeholder="未定なら1stと同値"></label><label><span>1stの配分%</span><input id="sz-split1" type="number" inputmode="decimal" min="1" max="99" step="1" value="50"></label><label><span>撤退方法</span><select id="sz-stop-method"><option value="21EMA_LOW">21EMA Low</option><option value="10MA">10MA</option></select></label><label><span>21EMA Low</span><input id="sz-stop21" type="number" inputmode="decimal" min="0" step="0.01" placeholder="95"></label><label><span>10MA</span><input id="sz-stop10" type="number" inputmode="decimal" min="0" step="0.01" placeholder="96"></label></div><div class="sizer-output"><div><span>平均Entry</span><b class="num" id="sz-avg">—</b></div><div><span>総数量</span><b class="num" id="sz-qty">—</b></div><div><span>1st / 2nd</span><b class="num" id="sz-tranches">—</b></div><div><span>建率</span><b class="num" id="sz-value">—</b></div><div><span>Stop時損失</span><b class="num" id="sz-loss">—</b></div><div><span>+25%部分利確</span><b class="num" id="sz-partial">—</b></div><div><span>残す数量</span><b class="num" id="sz-runner">—</b></div><div><span>残玉トレール</span><b id="sz-trail">—</b></div></div><p class="sizer-message bad" id="sz-message">必要数値を入力すると計算します。</p></div></details>
<div class="panel"><h3>集中度</h3><div class="sub">配分順。色は含み損益。Treemapより15〜30銘柄を比較しやすい表示</div><div id="conc-list"></div></div><div class="panel"><h3>セクター配分</h3><div id="sector-bars"></div></div><div class="panel"><h3>テーマ配分</h3><div id="theme-bars"></div></div><div class="panel"><div class="portfolio-tools"><div><h3>保有一覧</h3><div class="sub">必要な銘柄だけ詳細を展開</div></div><button class="compact-btn" id="copy-holdings" type="button">全銘柄をコピー</button></div><div id="holdings-cards"></div></div><div class="panel"><h3>相関上位ペア</h3><div class="sub">{html.escape(str(risk.get('method') or '相関計算なし'))}</div><div id="corr-pairs"></div></div></section>
<section class="tab-panel" id="journal"><div class="sec-head"><h2>取引履歴</h2><p>検索・Setup・NQ・勝敗で絞り込み</p><div class="rule"></div></div><div class="j-toolbar"><input class="search" id="j-search" type="search" placeholder="Ticker / Sector / Theme / Exit"><select id="j-setup"></select><select id="j-nq"><option value="">NQ すべて</option><option>GREEN</option><option>BLUE</option><option>YELLOW</option><option>RED</option></select><select id="j-result"><option value="">結果 すべて</option><option value="win">勝ち</option><option value="loss">負け</option></select></div><div class="j-count" id="j-count"></div><div id="j-list"></div><button class="more-btn" id="j-more">さらに20件表示</button></section>
<section class="tab-panel" id="edge"><div class="sec-head"><h2>エッジ分析</h2><p>期間・軸・並び順・最小件数を組み替えて検証</p><div class="rule"></div></div><div class="period-bar" id="edge-period"></div><div class="custom-range" id="edge-custom" hidden><input type="date" id="edge-from"><span>〜</span><input type="date" id="edge-to"></div><div class="callout" id="edge-callout"></div><div class="edge-controls"><label><span>軸</span><select id="edge-axis"><option value="setup">Setup別</option><option value="nq">NQ環境別</option><option value="sector">Sector別</option><option value="theme">Theme別</option><option value="weekday">曜日別</option><option value="holdBucket">保有日数帯</option><option value="rBucket">R倍数帯</option><option value="setupNq">Setup × NQ</option></select></label><label><span>並び替え</span><select id="edge-sort"><option value="pf">PF</option><option value="wr">勝率</option><option value="r">平均R</option><option value="n">件数</option></select></label><label><span>最小件数</span><input type="number" id="edge-minn" value="5" min="1" max="100"></label></div><div class="panel"><h3>条件別ランキング</h3><div class="sub">行タップで取引履歴へ移動</div><div class="rank-head"><span>条件</span><span>件数</span><span>勝率</span><span>PF</span><span>平均R</span></div><div id="rank-body"></div></div><div class="panel"><h3>規律違反</h3><div class="sub">選択期間内</div><div id="rule-violations"></div></div><p class="fineprint">サンプル不足は薄色表示します。PFや勝率だけでは採用せず、件数・平均R・市場環境を同時に確認してください。</p></section>
<section class="tab-panel" id="review"><div class="sec-head"><h2>振り返り</h2><p>数値から再発可能な問題だけを抽出</p><div class="rule"></div></div><div class="panel review">{review}</div><div class="panel"><h3>候補選択の検証</h3><div class="sub">買った候補と見送った候補を同じ10日窓で比較</div><div id="candidate-selection"></div></div><div class="panel"><h3>データ品質</h3><ul class="fineprint">{source_notes}</ul></div></section>
<section class="tab-panel" id="share"><div class="sec-head"><h2>共有</h2><p>個別銘柄・Setup詳細を出さない集計カード</p><div class="rule"></div></div><div class="share-preview"><div class="eyebrow">V38 Trade Journal — {report.as_of.strftime('%Y-%m')}</div><div class="headline">期待値を残し、損失を管理する。</div><div class="share-stats"><div><span>勝率</span><strong>{_pct(k.get('win_rate'))}</strong></div><div><span>Profit Factor</span><strong>{_num(k.get('profit_factor'))}</strong></div><div><span>平均R</span><strong>{_num(k.get('average_r'))}</strong></div><div><span>最大DD</span><strong>{_pct(k.get('max_drawdown'))}</strong></div></div></div><div class="panel"><h3>投稿文</h3><textarea class="copy-box" id="share-text" readonly>{html.escape(share_copy)}</textarea><button class="copy-btn" data-copy-target="share-text">コピー</button></div><div class="share-images"><div class="panel"><h3>日次カード</h3><img src="daily_card.png" alt="日次成績カード"></div><div class="panel"><h3>ポートフォリオカード</h3><img src="portfolio_card.png" alt="ポートフォリオカード"></div></div></section>
</div></main><script>window.V38_DATA={_script_json(payload)};</script><script>{JS}</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


__all__ = ["render_dashboard"]

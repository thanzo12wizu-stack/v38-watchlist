from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .trade_journal import JournalReport
from .trade_journal_almanac import render_dashboard as _render_base


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pct(value: Any) -> str:
    return f"{_finite(value) * 100:.1f}%"


def _risk_counts(report: JournalReport) -> tuple[int, int, int]:
    holdings = report.holdings
    if holdings.empty:
        return 0, 0, 0
    event_count = 0
    if "event_risk" in holdings:
        event_text = holdings["event_risk"].fillna("").astype(str).str.strip().str.lower()
        event_count = int((~event_text.isin({"", "0", "false", "none", "nan", "unknown", "なし"})).sum())
    breached = near = 0
    if {"current_price", "stop_price"}.issubset(holdings.columns):
        current = pd.to_numeric(holdings["current_price"], errors="coerce")
        stop = pd.to_numeric(holdings["stop_price"], errors="coerce")
        distance = (current - stop) / current.replace(0, np.nan)
        breached = int((distance < 0).fillna(False).sum())
        near = int(((distance >= 0) & (distance <= 0.02)).fillna(False).sum())
    return event_count, breached, near


def _decision(report: JournalReport, breached: int, near: int, events: int) -> tuple[str, str, str]:
    nq = str(report.nq_color or "UNKNOWN").upper()
    corr_heat = _finite(report.portfolio_risk.get("correlation_adjusted_heat"))
    if breached:
        return "bad", "撤退確認を優先", f"Stop逸脱{breached}銘柄。新規発注より既存ポジションを処理"
    if nq in {"RED", "UNKNOWN"}:
        return "bad", "新規発注停止", "市場ゲートが赤または取得不能"
    if nq == "YELLOW":
        return "warn", "新規発注停止", "市場ゲートが黄"
    if corr_heat >= 0.024:
        return "bad", "新規発注停止", "相関調整Heatが上限帯"
    if corr_heat >= 0.018 or near >= 2 or events >= 2:
        reasons: list[str] = []
        if corr_heat >= 0.018:
            reasons.append("相関Heat高め")
        if near:
            reasons.append(f"Stop接近{near}銘柄")
        if events:
            reasons.append(f"イベント接近{events}銘柄")
        return "warn", "条件付きで発注可", "・".join(reasons)
    return "good", "新規発注可能", "市場・Heat・保有リスクは許容範囲"


_ENHANCEMENT_CSS = r'''
.tabs{grid-template-columns:repeat(12,minmax(0,1fr))}
.tab:nth-child(-n+4){grid-column:span 3}
.tab:nth-child(n+5){grid-column:span 4}
#holdings-more[hidden]{display:none}
'''

_ENHANCEMENT_JS = r'''
(() => {
  const root = document.getElementById('holdings-cards');
  const more = document.getElementById('holdings-more');
  if (!root || !more || !window.V38_DATA) return;
  const distances = new Map((window.V38_DATA.holdings || []).map(h => {
    const current = Number(h.current_price || 0), stop = Number(h.stop_price || 0);
    return [String(h.ticker), current ? (current - stop) / current : 0];
  }));
  const cards = [...root.querySelectorAll('.holding-card')];
  cards.sort((a, b) => {
    const at = a.querySelector('.holding-title')?.textContent.trim().split(/\s/)[0] || '';
    const bt = b.querySelector('.holding-title')?.textContent.trim().split(/\s/)[0] || '';
    return Number(distances.get(at) || 0) - Number(distances.get(bt) || 0);
  }).forEach(card => root.appendChild(card));
  cards.forEach(card => {
    const title = card.querySelector('.holding-title');
    const ticker = title?.textContent.trim().split(/\s/)[0] || '';
    if (Number(distances.get(ticker) || 0) < 0 && title && !title.querySelector('.stop-breach')) {
      const badge = document.createElement('span');
      badge.className = 'risk-badge stop-breach';
      badge.style.background = 'var(--bad-soft)';
      badge.style.color = 'var(--bad)';
      badge.textContent = 'STOP逸脱';
      title.appendChild(badge);
    }
  });
  let expanded = false;
  function update() {
    cards.forEach((card, index) => { card.hidden = !expanded && index >= 8; });
    const remaining = Math.max(0, cards.length - 8);
    more.hidden = expanded || remaining === 0;
    more.textContent = `残り${remaining}銘柄を表示`;
  }
  more.addEventListener('click', () => { expanded = true; update(); });
  update();
})();
'''


def _enhance(document: str, report: JournalReport) -> str:
    events, breached, near = _risk_counts(report)
    tone, title, reason = _decision(report, breached, near, events)
    status = (
        f'<div class="status-line {tone}"><span class="status-dot"></span><span>'
        f'<b>{html.escape(title)}</b><small>{html.escape(reason)}</small></span>'
        '<a class="detail-link" href="#portfolio">内訳 →</a></div><div class="metrics">'
    )
    document, count = re.subn(
        r'<div class="status-line [^"]+">.*?</div><div class="metrics">',
        status,
        document,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Almanac decision banner was not found")

    risk = report.portfolio_risk
    metrics = (
        '<div class="metrics">'
        f'<div class="metric"><span>相関調整Heat</span><strong class="num">{_pct(risk.get("correlation_adjusted_heat"))}</strong></div>'
        f'<div class="metric"><span>名目Heat</span><strong class="num">{_pct(risk.get("nominal_heat"))}</strong></div>'
        f'<div class="metric"><span>Stop逸脱</span><strong class="num {"neg" if breached else ""}">{breached}銘柄</strong></div>'
        f'<div class="metric"><span>Stop接近</span><strong class="num">{near}銘柄</strong></div>'
        f'<div class="metric"><span>イベント接近</span><strong class="num">{events}銘柄</strong></div>'
        f'<div class="metric"><span>保有数</span><strong class="num">{len(report.holdings)}銘柄</strong></div>'
        '</div><p class="fineprint">'
    )
    document, count = re.subn(
        r'<div class="metrics"><div class="metric"><span>相関調整Heat</span>.*?</div></div><p class="fineprint">',
        metrics,
        document,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Almanac risk metrics were not found")

    marker = '<div id="holdings-cards"></div></div></section>'
    replacement = '<div id="holdings-cards"></div><button class="more-btn" id="holdings-more">残りを表示</button></div></section>'
    if marker not in document:
        raise ValueError("Almanac holdings container was not found")
    document = document.replace(marker, replacement, 1)
    document = document.replace('</style>', _ENHANCEMENT_CSS + '</style>', 1)
    document = document.replace('</body>', f'<script>{_ENHANCEMENT_JS}</script></body>', 1)
    return document


def render_dashboard(report: JournalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / ".trade_journal_almanac_base.html"
    _render_base(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)
    path.write_text(_enhance(document, report), encoding="utf-8")


__all__ = ["render_dashboard"]

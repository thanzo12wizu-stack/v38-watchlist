from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

DASHBOARD_BRIDGE_VERSION = "1.0.0"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def build_intelligence_panel(index_payload: dict[str, Any]) -> str:
    market = index_payload.get("market_state") or {}
    brief = index_payload.get("morning_brief") or {}
    portfolio = index_payload.get("portfolio_doctor") or {}
    candidates = brief.get("actionable_candidates") or []
    themes = brief.get("strong_themes") or []
    actions = portfolio.get("positions") or []
    candidate_cards = "".join(
        f'<div class="cc-ai-card"><b>{_esc(x.get("ticker"))}</b><span>{_esc(x.get("setup"))}</span><small>{_esc(x.get("theme"))} / {_esc(x.get("story_phase"))}</small></div>'
        for x in candidates[:8]
    ) or '<div class="cc-ai-empty">発注可能候補なし</div>'
    theme_cards = "".join(
        f'<div class="cc-ai-row"><b>{_esc(x.get("theme"))}</b><span>{_esc(x.get("phase"))}</span><em>{round(float(x.get("score_theme") or 0)*100)}</em></div>'
        for x in themes[:6]
    ) or '<div class="cc-ai-empty">テーマデータなし</div>'
    position_rows = "".join(
        f'<div class="cc-ai-row"><b>{_esc(x.get("ticker"))}</b><span>{_esc(x.get("action"))}</span><em>{_esc(x.get("stop_distance_pct"))}%</em></div>'
        for x in actions[:8]
    ) or '<div class="cc-ai-empty">portfolio.csv未設定</div>'
    x_text = _esc(brief.get("x_post_ja") or "")
    payload = json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''<!-- COMMAND_CENTER_INTELLIGENCE_START -->
<section id="command-center-intelligence" class="cc-ai-shell">
  <style>
    .cc-ai-shell{{font-family:inherit;margin:12px 0;padding:14px;border:1px solid rgba(127,127,127,.22);border-radius:18px;background:rgba(127,127,127,.06)}}
    .cc-ai-head{{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}}
    .cc-ai-head h2{{margin:0;font-size:18px}} .cc-ai-regime{{font-weight:800;padding:6px 10px;border-radius:999px;background:rgba(127,127,127,.12)}}
    .cc-ai-tabs{{display:flex;gap:8px;overflow-x:auto;margin:12px 0;scrollbar-width:none}} .cc-ai-tabs button{{white-space:nowrap;border:0;border-radius:999px;padding:8px 12px;font-weight:700;cursor:pointer}}
    .cc-ai-pane{{display:none}} .cc-ai-pane.active{{display:block}} .cc-ai-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
    .cc-ai-card,.cc-ai-row{{border:1px solid rgba(127,127,127,.18);border-radius:12px;padding:10px;background:rgba(127,127,127,.05)}}
    .cc-ai-card{{display:flex;flex-direction:column;gap:3px}} .cc-ai-row{{display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;margin-bottom:6px}}
    .cc-ai-card small,.cc-ai-row span,.cc-ai-row em{{opacity:.72;font-style:normal}} .cc-ai-copy{{width:100%;min-height:150px;border-radius:12px;padding:10px;box-sizing:border-box}}
    .cc-ai-copy-btn{{margin-top:8px;border:0;border-radius:10px;padding:9px 12px;font-weight:800;cursor:pointer}}
    @media(max-width:680px){{.cc-ai-shell{{margin:8px -2px;padding:12px;border-radius:14px}}.cc-ai-grid{{grid-template-columns:1fr}}.cc-ai-head h2{{font-size:16px}}}}
    @media print{{.cc-ai-tabs,.cc-ai-copy-btn{{display:none}}.cc-ai-pane{{display:block!important;break-inside:avoid}}}}
  </style>
  <div class="cc-ai-head"><h2>AI Command Layer</h2><div class="cc-ai-regime">{_esc(market.get("regime"))} · {_esc(market.get("entry_gate"))}</div></div>
  <p>{_esc(brief.get("market_comment"))}</p>
  <div class="cc-ai-tabs"><button data-ai-tab="daily">日次</button><button data-ai-tab="weekend">週末</button><button data-ai-tab="portfolio">Portfolio</button><button data-ai-tab="post">X投稿</button></div>
  <div class="cc-ai-pane active" data-ai-pane="daily"><div class="cc-ai-grid">{candidate_cards}</div></div>
  <div class="cc-ai-pane" data-ai-pane="weekend">{theme_cards}</div>
  <div class="cc-ai-pane" data-ai-pane="portfolio">{position_rows}</div>
  <div class="cc-ai-pane" data-ai-pane="post"><textarea class="cc-ai-copy" readonly>{x_text}</textarea><button class="cc-ai-copy-btn">コピー</button></div>
  <script type="application/json" id="cc-intelligence-json">{payload}</script>
  <script>(function(){{var root=document.getElementById('command-center-intelligence');if(!root)return;root.querySelectorAll('[data-ai-tab]').forEach(function(b){{b.onclick=function(){{root.querySelectorAll('[data-ai-pane]').forEach(function(p){{p.classList.toggle('active',p.dataset.aiPane===b.dataset.aiTab)}})}}}});var copy=root.querySelector('.cc-ai-copy-btn');if(copy)copy.onclick=function(){{var t=root.querySelector('.cc-ai-copy');navigator.clipboard.writeText(t.value);copy.textContent='コピー済み'}}}})();</script>
</section>
<!-- COMMAND_CENTER_INTELLIGENCE_END -->'''


def inject_panel(html_path: Path, index_payload: dict[str, Any]) -> bool:
    if not html_path.exists():
        return False
    text = html_path.read_text(encoding="utf-8")
    start = "<!-- COMMAND_CENTER_INTELLIGENCE_START -->"
    end = "<!-- COMMAND_CENTER_INTELLIGENCE_END -->"
    if start in text and end in text:
        before = text.split(start, 1)[0]
        after = text.split(end, 1)[1]
        text = before + after
    panel = build_intelligence_panel(index_payload)
    marker = "</body>"
    text = text.replace(marker, panel + "\n" + marker, 1) if marker in text else text + "\n" + panel
    html_path.write_text(text, encoding="utf-8")
    return True

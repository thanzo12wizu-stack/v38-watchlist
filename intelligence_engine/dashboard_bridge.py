from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

DASHBOARD_BRIDGE_VERSION = "1.0.0"


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def build_panel(payload: dict[str, Any]) -> str:
    market, brief, portfolio = payload.get("market_state", {}), payload.get("morning_brief", {}), payload.get("portfolio_doctor", {})
    candidates = "".join(f'<article class="ccai-card"><b>{_e(x.get("ticker"))}</b><span>{_e(x.get("setup"))}</span><small>{_e(x.get("theme"))} / {_e(x.get("story_phase"))}</small></article>' for x in brief.get("actionable_candidates", [])[:8]) or '<div class="ccai-empty">発注可能候補なし</div>'
    themes = "".join(f'<div class="ccai-row"><b>{_e(x.get("theme"))}</b><span>{_e(x.get("phase"))}</span><em>{round(float(x.get("score_theme") or 0)*100)}</em></div>' for x in brief.get("strong_themes", [])[:6]) or '<div class="ccai-empty">テーマデータなし</div>'
    positions = "".join(f'<div class="ccai-row"><b>{_e(x.get("ticker"))}</b><span>{_e(x.get("action"))}</span><em>{_e(x.get("stop_distance_pct"))}%</em></div>' for x in portfolio.get("positions", [])[:8]) or '<div class="ccai-empty">portfolio.csv未設定</div>'
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''<!-- COMMAND_CENTER_INTELLIGENCE_START --><section id="cc-intelligence" class="ccai"><style>.ccai{{margin:12px 0;padding:14px;border:1px solid #8884;border-radius:18px;background:#8881;font-family:inherit}}.ccai-head{{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}}.ccai-head h2{{font-size:18px;margin:0}}.ccai-pill{{font-weight:800;padding:6px 10px;border-radius:999px;background:#8882}}.ccai-tabs{{display:flex;gap:7px;overflow:auto;margin:12px 0}}.ccai-tabs button,.ccai-copybtn{{border:0;border-radius:999px;padding:8px 12px;font-weight:800}}.ccai-pane{{display:none}}.ccai-pane.on{{display:block}}.ccai-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.ccai-card,.ccai-row{{border:1px solid #8883;border-radius:12px;padding:10px;background:#8881}}.ccai-card{{display:flex;flex-direction:column;gap:3px}}.ccai-row{{display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-bottom:6px}}.ccai-row em{{font-style:normal}}.ccai-copy{{width:100%;min-height:160px;box-sizing:border-box;border-radius:12px;padding:10px}}@media(max-width:680px){{.ccai{{padding:11px;border-radius:14px}}.ccai-grid{{grid-template-columns:1fr}}}}@media print{{.ccai-tabs,.ccai-copybtn{{display:none}}.ccai-pane{{display:block!important}}}}</style><div class="ccai-head"><h2>AI Command Layer</h2><span class="ccai-pill">{_e(market.get("regime"))} · {_e(market.get("entry_gate"))}</span></div><p>{_e(brief.get("market_comment"))}</p><nav class="ccai-tabs"><button data-tab="daily">日次</button><button data-tab="weekend">週末</button><button data-tab="portfolio">Portfolio</button><button data-tab="post">X投稿</button></nav><div class="ccai-pane on" data-pane="daily"><div class="ccai-grid">{candidates}</div></div><div class="ccai-pane" data-pane="weekend">{themes}</div><div class="ccai-pane" data-pane="portfolio">{positions}</div><div class="ccai-pane" data-pane="post"><textarea class="ccai-copy" readonly>{_e(brief.get("x_post_ja"))}</textarea><button class="ccai-copybtn">コピー</button></div><script type="application/json" id="cc-intelligence-json">{raw}</script><script>(function(){{var r=document.getElementById('cc-intelligence');if(!r)return;r.querySelectorAll('[data-tab]').forEach(function(b){{b.onclick=function(){{r.querySelectorAll('[data-pane]').forEach(function(p){{p.classList.toggle('on',p.dataset.pane===b.dataset.tab)}})}}}});var c=r.querySelector('.ccai-copybtn');if(c)c.onclick=function(){{var t=r.querySelector('.ccai-copy');navigator.clipboard.writeText(t.value);c.textContent='コピー済み'}}}})();</script></section><!-- COMMAND_CENTER_INTELLIGENCE_END -->'''


def inject_panel(path: Path, payload: dict[str, Any]) -> bool:
    if not path.exists(): return False
    text = path.read_text(encoding="utf-8")
    start, end = "<!-- COMMAND_CENTER_INTELLIGENCE_START -->", "<!-- COMMAND_CENTER_INTELLIGENCE_END -->"
    if start in text and end in text: text = text.split(start, 1)[0] + text.split(end, 1)[1]
    panel = build_panel(payload)
    text = text.replace("</body>", panel + "\n</body>", 1) if "</body>" in text else text + panel
    path.write_text(text, encoding="utf-8")
    return True

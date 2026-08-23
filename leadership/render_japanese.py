from __future__ import annotations

import html
import json
from typing import Any


PHASE_JA = {
    "EMERGING": "新興",
    "LEADING": "主導",
    "MATURE": "成熟",
    "LOSING": "失速",
}

ROLE_JA = {
    "PIONEER": "先導株",
    "LEADER": "主導株",
    "FOLLOWER": "追随",
    "NO_DATA": "データ不足",
}

ENTRY_JA = {
    "ENTRY": "エントリー候補",
    "WATCH": "監視",
    "WAIT": "待機",
    "AVOID": "見送り",
    "NO_DATA": "データ不足",
}

MARKET_JA = {
    "GO": "攻める",
    "SELECTIVE": "選別",
    "STOP": "停止",
}

GATE_JA = {
    "Green": "緑",
    "Blue": "青",
    "Yellow": "黄",
    "Red": "赤",
    "Black": "黒",
}

FTD_JA = {
    "FTD_ACTIVE": "FTD有効",
    "RALLY_ATTEMPT": "ラリー試行",
    "CORRECTION": "調整",
}


def esc(value: Any) -> str:
    return html.escape(str("—" if value is None else value))


def phase_label(row: dict[str, Any]) -> str:
    phase = str(row.get("phase") or "")
    return PHASE_JA.get(phase, phase or "—")


def role_label(value: Any) -> str:
    key = str(value or "")
    return ROLE_JA.get(key, key or "—")


def entry_label(value: Any) -> str:
    key = str(value or "")
    return ENTRY_JA.get(key, key or "—")


def render_cards(rows: list[dict[str, Any]], *, clickable: bool = False) -> str:
    cards: list[str] = []
    for row in rows:
        attr = f' data-group="{esc(row.get("name"))}"' if clickable else ""
        cards.append(
            f'<button class="card phase-{esc(str(row.get("phase") or "").lower())}"{attr}>'
            f'<span class="phase">{esc(phase_label(row))}</span>'
            f'<strong>{esc(row.get("name"))}</strong>'
            f'<span class="score">{esc(row.get("score"))}<small>/100</small></span>'
            f'<span class="meta">主導株密度 {esc(row.get("leader_density"))} · RS加速 {esc(row.get("acceleration"))}</span>'
            '</button>'
        )
    return "".join(cards) or '<div class="empty">有効なデータがありません</div>'


def render_chips(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">該当なし。強いだけの株を無理に追いません。</div>'
    return "".join(
        f'<div class="chip"><b>{esc(x.get("symbol"))}</b>'
        f'<span>{esc(role_label(x.get("role")))} · {esc(x.get("group"))}</span>'
        f'<em>{esc(x.get("reason"))}</em></div>'
        for x in rows
    )


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model["market"]
    cov = model["coverage"]
    market_status = str(market.get("status") or "")
    market_label = MARKET_JA.get(market_status, market_status or "—")
    gate = GATE_JA.get(str(market.get("gate") or ""), str(market.get("gate") or "—"))
    ftd = FTD_JA.get(str(market.get("ftd") or ""), str(market.get("ftd") or "—"))
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f17"><title>Leadership Command</title>
<style>
:root{{--bg:#0b0f17;--panel:rgba(255,255,255,.03);--panel-strong:#111827;--line:rgba(255,255,255,.07);--text:#e6edf3;--muted:#8b9bb0;--blue:#9ecbff;--green:#16a34a;--yellow:#ca8a04;--red:#dc2626;--soft-blue:#16243e}}*{{box-sizing:border-box}}body{{margin:0;min-height:100svh;background:radial-gradient(1200px 520px at 80% -10%,rgba(22,163,74,.10),transparent 54%),var(--bg);color:var(--text);font-family:'Hiragino Sans','Noto Sans JP',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;line-height:1.5}}button{{font:inherit}}.wrap{{max-width:1380px;margin:auto;padding:max(22px,env(safe-area-inset-top)) 16px max(30px,env(safe-area-inset-bottom))}}header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;padding:12px 4px 20px}}.eyebrow{{font-size:10px;font-weight:800;letter-spacing:.13em;color:#64748b}}h1{{margin:3px 0 5px;font-size:28px;letter-spacing:-.03em;color:var(--blue)}}.sub,.muted{{color:var(--muted)}}.sub{{font-size:13px}}.asof{{text-align:right;color:#7d8da1;font-size:11px;line-height:1.65}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}}.permission{{display:grid;grid-template-columns:1.05fr 1.7fr;gap:12px;margin-bottom:12px}}.market{{display:flex;gap:18px;align-items:center}}.status{{font-size:34px;font-weight:900;line-height:1.05;margin:4px 0}}.status-GO{{color:#fff;background:var(--green);border-radius:12px;padding:6px 14px;display:inline-block;box-shadow:0 0 26px rgba(22,163,74,.34)}}.status-SELECTIVE{{color:#fff;background:var(--yellow);border-radius:12px;padding:6px 14px;display:inline-block}}.status-STOP{{color:#fff;background:var(--red);border-radius:12px;padding:6px 14px;display:inline-block}}.mri{{margin-left:auto;text-align:right;color:var(--muted)}}.mri b{{font-size:34px;color:#fff}}.flow{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}.flow span{{padding:6px 9px;background:rgba(255,255,255,.03);border:1px solid var(--line);border-radius:8px;color:#cbd5e1}}.flow i{{color:#5f6b7e;font-style:normal}}h2{{font-size:12px;letter-spacing:.05em;color:#cbd5e1;margin:0 0 10px}}.section{{margin-bottom:12px}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}}.card{{color:inherit;text-align:left;background:rgba(255,255,255,.03);border:1px solid var(--line);border-left:3px solid #334155;border-radius:10px;padding:10px 11px;min-height:108px;display:grid;grid-template-columns:1fr auto;gap:6px;cursor:pointer;transition:background .14s ease,border-color .14s ease,transform .14s ease}}.card:hover{{background:rgba(255,255,255,.045);border-color:rgba(255,255,255,.12)}}.card:active{{transform:scale(.99)}}.phase-emerging{{border-left-color:var(--green)}}.phase-leading{{border-left-color:var(--blue)}}.phase-mature{{border-left-color:var(--yellow)}}.phase-losing{{border-left-color:#475569}}.card .phase{{grid-column:1/3;color:#94a3b8;font-size:10px;font-weight:700}}.card strong{{grid-column:1/3;font-size:13px;color:#e6edf3}}.score{{font-size:24px;font-weight:800;color:#fff}}.score small{{font-size:9px;color:#64748b}}.meta{{text-align:right;color:#7d8da1;font-size:10px;align-self:end}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}.chips{{display:flex;gap:8px;flex-wrap:wrap}}.chip{{min-width:168px;padding:9px 10px;border:1px solid var(--line);background:rgba(255,255,255,.03);border-radius:9px}}.chip b{{display:block;color:var(--blue);font-size:17px}}.chip span,.chip em{{display:block;font-style:normal;color:var(--muted);font-size:10px;margin-top:2px}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:10px}}table{{width:100%;border-collapse:collapse;min-width:1120px}}th,td{{padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.055);text-align:right;white-space:nowrap}}th{{font-size:10px;letter-spacing:.03em;color:#7d8da1;background:#0b0f17;position:sticky;top:0}}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}tbody tr:hover{{background:rgba(255,255,255,.025)}}.role-PIONEER{{color:#86efac;font-weight:800}}.role-LEADER{{color:var(--blue);font-weight:800}}.role-NO_DATA{{color:#64748b}}.entry-ENTRY{{color:#86efac;font-weight:800}}.entry-WAIT,.entry-WATCH{{color:#fbbf24}}.entry-AVOID{{color:#f87171}}.entry-NO_DATA{{color:#64748b}}.empty{{color:var(--muted);padding:9px 2px}}.footer{{color:#5f6b7e;font-size:10px;margin-top:8px;line-height:1.5}}@media(max-width:900px){{header{{flex-direction:column;align-items:flex-start}}.asof{{text-align:left}}.permission,.actions{{grid-template-columns:1fr}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:520px){{.wrap{{padding-left:10px;padding-right:10px}}.grid{{grid-template-columns:1fr}}.market{{align-items:flex-start}}.mri b{{font-size:28px}}h1{{font-size:25px}}}}
</style></head><body><main class="wrap"><header><div><div class="eyebrow">V38 WATCHLIST</div><h1>Leadership Command</h1><div class="sub">市場が良いときに、主導セクター → 主導グループ → 先導株 → 今入れるか、の順で見る。</div></div><div class="asof">基準日 {esc(cov.get("market_asof") or market.get("asof"))}<br>RS63取得 {esc(cov.get("rs63"))}銘柄 · データ信頼度 <b>{esc(cov.get("confidence"))}</b></div></header><section class="permission"><div class="panel market"><div><div class="muted">市場判断</div><div class="status status-{esc(market_status)}">{esc(market_label)}</div><div>{esc(market.get("label"))}</div></div><div class="mri"><span>地合いスコア MRI</span><br><b>{esc(market.get("mri"))}</b><br><span>{esc(gate)} · {esc(ftd)}</span></div></div><div class="panel"><h2>判断フロー</h2><div class="flow"><span>地合い</span><i>→</i><span>セクター</span><i>→</i><span>グループ</span><i>→</i><span>先導株 / 主導株</span><i>→</i><span>エントリー</span></div><div class="footer">RSはQQQ超過の21 / 63 / 189日順位。強い株と、今買える株を分けて表示します。</div></div></section><section class="panel section"><h2>主導セクター</h2><div class="grid">{render_cards(model.get("sectors", [])[:8])}</div></section><section class="panel section"><h2>グループ・ローテーション</h2><div class="grid">{render_cards(model.get("groups", [])[:12], clickable=True)}</div></section><section class="actions"><div class="panel"><h2>🎯 今、入れる候補</h2><div class="chips">{render_chips(model.get("actionable", []))}</div></div><div class="panel"><h2>⏳ 強いが、今は待つ</h2><div class="chips">{render_chips(model.get("waiting", [])[:6])}</div></div></section><section class="panel"><h2 id="boardTitle">主導株ボード</h2><div class="table-wrap"><table><thead><tr><th>銘柄</th><th>役割</th><th>主導度</th><th>RS189</th><th>RS63</th><th>RS21</th><th>RS加速</th><th>52週高値差</th><th>RVOL</th><th>EPS</th><th>判断</th><th>理由</th></tr></thead><tbody id="board"></tbody></table></div><div class="footer" id="coverage"></div></section></main><script id="payload" type="application/json">{payload}</script><script>const data=JSON.parse(document.getElementById('payload').textContent);const board=document.getElementById('board');const roleJa={{PIONEER:'先導株',LEADER:'主導株',FOLLOWER:'追随',NO_DATA:'データ不足'}};const entryJa={{ENTRY:'エントリー候補',WATCH:'監視',WAIT:'待機',AVOID:'見送り',NO_DATA:'データ不足'}};const phaseJa={{EMERGING:'新興',LEADING:'主導',MATURE:'成熟',LOSING:'失速'}};function v(x){{return x===null||x===undefined?'—':x}}function render(name){{const g=data.groups.find(x=>x.name===name)||data.groups[0];if(!g)return;document.getElementById('boardTitle').textContent=`主導株ボード — ${{g.name}} · ${{phaseJa[g.phase]||g.phase}} · ${{g.score}}/100`;board.innerHTML=g.stocks.map(s=>`<tr><td><b>${{s.symbol}}</b><div class="muted">${{s.name||''}}</div></td><td class="role-${{s.role}}">${{roleJa[s.role]||s.role}}</td><td><b>${{v(s.strength)}}</b></td><td>${{v(s.rs189)}}</td><td>${{v(s.rs63)}}</td><td>${{v(s.rs21)}}</td><td>${{v(s.acceleration)}}</td><td>${{v(s.near_high)}}</td><td>${{v(s.volume_ratio)}}</td><td>${{s.eps_label||'—'}}</td><td class="entry-${{s.entry.status}}">${{entryJa[s.entry.status]||s.entry.status}}</td><td>${{s.entry.reason}}</td></tr>`).join('')}}document.querySelectorAll('[data-group]').forEach(el=>el.addEventListener('click',()=>render(el.dataset.group)));render(data.groups[0]?.name);const c=data.coverage;document.getElementById('coverage').textContent=`データ: ${{c.metric_source}} · 対象 ${{c.stocks}}銘柄 · セクター ${{c.sectors}} · グループ ${{c.groups}} · RS63 ${{c.rs63}} · エントリー判定 ${{c.entry_inputs}}`;</script></body></html>'''

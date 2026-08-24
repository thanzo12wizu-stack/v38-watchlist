from __future__ import annotations

import html
import json
from typing import Any


ROTATION_META = {
    "RISING": ("急浮上", "RISING"),
    "LEADING": ("主導中", "LEADING"),
    "TOPPING": ("ピークアウト警戒", "TOPPING"),
    "FADING": ("失速", "FADING"),
}
ROLE_JA = {"PIONEER": "先導株", "LEADER": "主導株", "FOLLOWER": "追随", "NO_DATA": "データ不足"}
PRE_JA = {
    "READY": ("発火目前", "READY"),
    "COILED": ("あと一歩", "COILED"),
    "WATCH": ("監視", "WATCH"),
    "NOT_READY": ("形成中", "BUILDING"),
    "ALREADY_BROKE": ("発火済み", "TRIGGERED"),
    "NO_DATA": ("判定不能", "NO DATA"),
}
MARKET_JA = {"GO": "攻める", "SELECTIVE": "選別", "STOP": "見送る"}
GATE_JA = {"Green": "緑", "Blue": "青", "Yellow": "黄", "Red": "赤", "Black": "黒"}
FTD_JA = {"FTD_ACTIVE": "FTD有効", "RALLY_ATTEMPT": "ラリー試行", "CORRECTION": "調整"}


def esc(value: Any) -> str:
    return html.escape(str("—" if value is None else value))


def _names(rows: list[dict[str, Any]], limit: int = 3) -> str:
    values = [str(x.get("name") or "").strip() for x in rows if str(x.get("name") or "").strip()]
    return " / ".join(values[:limit]) if values else "—"


def _leader_text(group: dict[str, Any], limit: int = 3) -> str:
    leaders = list(group.get("rotation_leaders") or [])
    if not leaders:
        return "主導株データなし"
    parts = []
    for row in leaders[:limit]:
        symbol = str(row.get("symbol") or "")
        status = str(row.get("status") or "")
        parts.append(f"{symbol} {status}" if status else symbol)
    return " · ".join(parts)


def render_group_rows(rows: list[dict[str, Any]], *, limit: int | None = None) -> str:
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        return '<div class="empty">該当なし</div>'
    out: list[str] = []
    for group in rows:
        state = str(group.get("rotation_state") or "FADING")
        jp, en = ROTATION_META.get(state, (state or "—", state or ""))
        out.append(
            f'<button class="rotrow state-{esc(state.lower())}" data-group="{esc(group.get("name"))}">'
            f'<span class="statepill"><b>{esc(jp)}</b><small>{esc(en)}</small></span>'
            f'<span class="rotmain"><strong>{esc(group.get("name"))}</strong>'
            f'<span class="rotwhy">{esc(group.get("rotation_reason"))}</span>'
            f'<span class="leadersline">主導株：{esc(_leader_text(group))}</span></span>'
            '<span class="chev">›</span></button>'
        )
    return "".join(out)


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model.get("market") or {}
    coverage = model.get("coverage") or {}
    rotation = model.get("rotation") or {}
    rising = list(rotation.get("rising") or [])
    leading = list(rotation.get("leading") or [])
    topping = list(rotation.get("topping") or [])
    fading = list(rotation.get("fading") or [])
    status = str(market.get("status") or "")
    gate = str(market.get("gate") or "")
    gate_cls = gate.lower() if gate.lower() in {"green", "blue", "yellow", "red"} else "gray"
    ftd = FTD_JA.get(str(market.get("ftd") or ""), str(market.get("ftd") or "—"))
    asof = coverage.get("market_asof") or market.get("asof")

    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f17"><meta name="color-scheme" content="dark"><title>Sector Rotation</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}html{{background:#0b0f17;color-scheme:dark}}body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','Hiragino Sans','Noto Sans JP',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}}button{{font:inherit}}.wrap{{max-width:720px;margin:0 auto;padding:0 12px calc(42px + env(safe-area-inset-bottom))}}header{{padding:14px 4px 9px}}h1{{font-size:18px;font-weight:850;letter-spacing:.01em}}.asof{{font-size:10px;color:#718197;margin-top:2px}}
.market{{border:1px solid #243044;border-left:4px solid #64748b;border-radius:11px;background:#121a26;padding:9px 11px;margin-bottom:10px}}.market.green{{border-left-color:#34d399}}.market.blue{{border-left-color:#60a5fa}}.market.yellow{{border-left-color:#fbbf24}}.market.red{{border-left-color:#f87171}}.markettop{{display:flex;align-items:center;gap:8px}}.markettop span{{font-size:9.5px;color:#7f8da3;font-weight:750;letter-spacing:.08em}}.markettop b{{font-size:15px}}.markettop em{{margin-left:auto;font-style:normal;color:#9fb0c5;font-size:10px}}.marketfoot{{font-size:10px;color:#718197;margin-top:4px}}
.card{{background:#0f1623;border:1px solid #1c2533;border-radius:13px;padding:12px 13px;margin-bottom:11px}}.card h2{{font-size:14.5px;font-weight:850;margin-bottom:4px}}.sub{{font-size:10.5px;color:#8090a5;line-height:1.55;margin-bottom:9px}}.flow{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}.flowcell{{background:#101824;border:1px solid #243044;border-radius:9px;padding:8px 9px}}.flowcell span{{display:block;font-size:9px;color:#718197}}.flowcell b{{display:block;font-size:12.5px;margin-top:2px;line-height:1.35}}.flowwide{{grid-column:1/-1}}
.rotlist{{display:grid;gap:6px}}.rotrow{{width:100%;border:1px solid #243044;border-left:3px solid #475569;background:#101824;color:inherit;border-radius:10px;padding:8px 9px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:center;text-align:left;cursor:pointer}}.state-rising{{border-left-color:#34d399}}.state-leading{{border-left-color:#60a5fa}}.state-topping{{border-left-color:#fbbf24}}.state-fading{{border-left-color:#64748b}}.statepill{{min-width:58px;text-align:center;border:1px solid #26364a;border-radius:7px;padding:4px 5px;background:#121b28}}.statepill b{{display:block;font-size:9.5px}}.statepill small{{display:block;font-size:6.5px;color:#64748b;letter-spacing:.08em;margin-top:1px}}.rotmain{{min-width:0}}.rotmain strong{{display:block;font-size:12.8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.rotwhy{{display:block;font-size:9.5px;color:#8393a9;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.leadersline{{display:block;font-size:9.5px;color:#aab7c7;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.chev{{font-size:20px;color:#5f7188}}
.groupdetail{{margin:-1px 0 7px;padding:10px;background:#0b111b;border:1px solid #26344a;border-radius:10px}}.ghead{{display:flex;justify-content:space-between;gap:8px;align-items:flex-start;margin-bottom:7px}}.ghead b{{font-size:13px;color:#dbeafe}}.ghead small{{display:block;font-size:9px;color:#718197;margin-top:1px}}.gsummary{{font-size:10px;color:#9fb0c5;line-height:1.5;margin-bottom:7px}}.leadercard{{border-top:1px solid #182131;padding:8px 0;cursor:pointer}}.leadercard:first-of-type{{border-top:0}}.leadtop{{display:flex;align-items:center;gap:6px}}.leadtop b{{font-size:14px;color:#9ecbff}}.role{{font-size:8px;color:#8fa4bc;border:1px solid #26364a;border-radius:5px;padding:1px 4px}}.setup{{margin-left:auto;text-align:right;font-size:9.5px;font-weight:800}}.setup small{{display:block;font-size:6.5px;color:#64748b;letter-spacing:.08em}}.setup-ready{{color:#43c98a}}.setup-coiled{{color:#8fb3ff}}.setup-watch{{color:#e3aa3c}}.leadwhy{{font-size:9.5px;color:#8190a4;margin-top:3px}}.tapdetail{{margin-top:7px;padding:9px;background:#101824;border:1px solid #26344a;border-radius:9px}}.detailgrid{{display:grid;grid-template-columns:1fr 1fr;gap:5px}}.detailcell{{background:#0d1520;border:1px solid #1d2a3a;border-radius:7px;padding:6px 7px}}.detailcell span{{display:block;font-size:8px;color:#718197}}.detailcell b{{display:block;font-size:10.5px;margin-top:1px}}.detailwhy{{font-size:10px;line-height:1.5;color:#aebdce;margin-top:7px}}.tvbtn{{display:flex;justify-content:center;align-items:center;margin-top:8px;text-decoration:none;border:1px solid #2f81f7;background:rgba(47,129,247,.08);color:#9ecbff;border-radius:8px;padding:8px;font-size:11px;font-weight:800}}details.fold{{margin-top:8px;border-top:1px solid #182131;padding-top:8px}}details>summary{{cursor:pointer;list-style:none;color:#718197;font-size:10.5px;font-weight:750}}details>summary::-webkit-details-marker{{display:none}}details>summary:before{{content:'▸ ';font-size:8px}}details[open]>summary:before{{content:'▾ '}}.empty{{font-size:11px;color:#718197;padding:3px 0}}.method{{font-size:9.5px;color:#718197;line-height:1.55}}
@media(min-width:760px){{.wrap{{max-width:900px;padding-left:20px;padding-right:20px}}.flow{{grid-template-columns:repeat(3,1fr)}}.flowwide{{grid-column:auto}}.detailgrid{{grid-template-columns:repeat(4,1fr)}}}}
</style></head><body><main class="wrap">
<header><h1>セクターローテーション</h1><div class="asof">{esc(asof)} · 細分類 {esc(coverage.get("groups"))}グループ · {esc(coverage.get("stocks"))}銘柄</div></header>
<section class="market {esc(gate_cls)}"><div class="markettop"><span>今日の地合い</span><b>{esc(MARKET_JA.get(status, status or "—"))}</b><em>MRI {esc(market.get("mri"))}</em></div><div class="marketfoot">{esc(GATE_JA.get(gate, gate or "—"))} · {esc(ftd)}　— 地合いは入口。主役は下の資金移動です。</div></section>
<section class="card"><h2>今の資金移動</h2><div class="sub">まず細分類の流れを見る。そのあと、その中の主導株を見る。</div><div class="flow"><div class="flowcell"><span>急浮上</span><b>{esc(_names(rising))}</b></div><div class="flowcell"><span>主導中</span><b>{esc(_names(leading))}</b></div><div class="flowcell flowwide"><span>ピークアウト警戒</span><b>{esc(_names(topping))}</b></div></div></section>
<section class="card"><h2>急浮上</h2><div class="sub">先導株が先に走り、強さが広がり始めた細分類。最初に見る。</div><div class="rotlist">{render_group_rows(rising, limit=8)}</div></section>
<section class="card"><h2>主導中</h2><div class="sub">先導株だけでなく、グループ全体にも強さが広がっている。</div><div class="rotlist">{render_group_rows(leading, limit=10)}</div></section>
<section class="card"><h2>ピークアウト警戒</h2><div class="sub">まだ強いが、加速が鈍り始めた細分類。新規は主導株の形を厳選。</div><div class="rotlist">{render_group_rows(topping, limit=8)}</div></section>
<section class="card"><details class="fold"><summary>失速グループを見る（{len(fading)}）</summary><div class="rotlist" style="margin-top:7px">{render_group_rows(fading)}</div></details></section>
<section class="card"><details><summary>判定方法</summary><div class="method">細分類Industry Groupごとに、先導株の強さ、グループ内の広がり、RS加速、上値抵抗・下値支持、発火前の主導株数を統合して「急浮上 / 主導中 / ピークアウト警戒 / 失速」に整理しています。点数は裏側の判定に使い、トップ画面では状態と主導株を優先して表示します。</div></details></section>
<script id="payload" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('payload').textContent);
const roleJa={{PIONEER:'先導株',LEADER:'主導株',FOLLOWER:'追随',NO_DATA:'データ不足'}};
const preJa={{READY:['発火目前','READY'],COILED:['あと一歩','COILED'],WATCH:['監視','WATCH'],NOT_READY:['形成中','BUILDING'],ALREADY_BROKE:['発火済み','TRIGGERED'],NO_DATA:['判定不能','NO DATA']}};
const h=x=>String(x===null||x===undefined?'—':x).replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
const val=(x,s='')=>x===null||x===undefined?'—':h(x)+s;const pct=(x,p='')=>x===null||x===undefined?'—':p+Number(x).toFixed(1)+'%';
function tvUrl(s){{const ex=String(s.exchange||'').trim().toUpperCase();const sym=String(s.symbol||'').trim().toUpperCase();return 'https://www.tradingview.com/chart/?symbol='+encodeURIComponent(ex?`${{ex}}:${{sym}}`:sym)}}
function setupInfo(s){{const p=s.prebreakout||{{}};return preJa[p.status]||['形成中','BUILDING']}}
function stockDetail(s,g){{const p=s.prebreakout||{{}};const st=s.structure||{{}};const state=setupInfo(s);const why=p.reason||s.entry?.reason||'—';return `<div class="tapdetail"><div class="detailgrid"><div class="detailcell"><span>現在値</span><b>${{val(s.price)}}</b></div><div class="detailcell"><span>発火準備度</span><b>${{val(p.score,' / 100')}}</b></div><div class="detailcell"><span>Pivotまで</span><b>${{pct(p.pivot_gap_pct)}}</b></div><div class="detailcell"><span>主導度</span><b>${{val(s.strength,' / 100')}}</b></div><div class="detailcell"><span>RS 189 / 63 / 21</span><b>${{val(s.rs189)}} / ${{val(s.rs63)}} / ${{val(s.rs21)}}</b></div><div class="detailcell"><span>RS加速</span><b>${{val(s.acceleration)}}</b></div><div class="detailcell"><span>上値抵抗まで</span><b>${{pct(st.supply_distance_pct,'+')}}</b></div><div class="detailcell"><span>下値支持まで</span><b>${{pct(st.demand_distance_pct,'−')}}</b></div><div class="detailcell"><span>RVOL</span><b>${{val(s.volume_ratio,'x')}}</b></div><div class="detailcell"><span>52週高値差</span><b>${{pct(s.near_high)}}</b></div><div class="detailcell"><span>EPS</span><b>${{h(s.eps_label||'—')}}</b></div><div class="detailcell"><span>状態</span><b>${{h(state[0])}}</b></div></div><div class="detailwhy">${{h(why)}}</div><a class="tvbtn" href="${{tvUrl(s)}}" target="_blank" rel="noopener noreferrer">TradingViewで開く ↗</a></div>`}}
function leaderCard(s,g){{const state=setupInfo(s);const cls=state[1]==='READY'?'setup-ready':state[1]==='COILED'?'setup-coiled':state[1]==='WATCH'?'setup-watch':'';const p=s.prebreakout||{{}};let why=[];if(p.pivot_gap_pct!==null&&p.pivot_gap_pct!==undefined)why.push(`Pivotまで ${{Number(p.pivot_gap_pct).toFixed(1)}}%`);if(s.rs63!==null&&s.rs63!==undefined)why.push(`RS63 ${{s.rs63}}`);if(s.acceleration!==null&&s.acceleration!==undefined)why.push(`加速 ${{Number(s.acceleration)>=0?'+':''}}${{s.acceleration}}`);return `<div class="leadercard" data-stock="${{h(s.symbol)}}"><div class="leadtop"><b>${{h(s.symbol)}}</b><span class="role">${{h(roleJa[s.role]||s.role||'')}}</span><span class="setup ${{cls}}">${{h(state[0])}}<small>${{h(state[1])}}</small></span></div><div class="leadwhy">${{h(why.join(' · ')||'詳細を確認')}}</div></div>`}}
function groupDetail(g){{const leaders=(g.stocks||[]).filter(s=>['PIONEER','LEADER'].includes(s.role)).slice(0,6);return `<div class="groupdetail" data-open-group="${{h(g.name)}}"><div class="ghead"><div><b>${{h(g.name)}}</b><small>${{h(g.rotation_label)}} · ${{h(g.rotation_arrow)}} ${{h(g.rotation_direction)}} · ${{h(g.rotation_breadth_label)}}</small></div></div><div class="gsummary">${{h(g.rotation_structure_label)}}。先導株 ${{g.pioneers||0}} / 主導株 ${{g.leaders||0}} / 発火目前 ${{g.prebreakout_ready||0}} / あと一歩 ${{g.prebreakout_coiled||0}}</div>${{leaders.length?leaders.map(s=>leaderCard(s,g)).join(''):'<div class="empty">主導株データなし</div>'}}<details class="fold"><summary>分析値を見る</summary><div class="method">Pioneer ${{val(g.pioneer_score)}} · Breadth ${{val(g.breadth_score)}} · Structure ${{val(g.structure_score)}} · Rotation ${{val(g.rotation_score)}} · 上位RS加速 ${{val(g.top_acceleration)}}</div></details></div>`}}
function findGroup(name){{return (data.groups||[]).find(g=>g.name===name)}}
document.addEventListener('click',ev=>{{if(ev.target.closest('a.tvbtn,summary,details'))return;const stockRow=ev.target.closest('.leadercard');if(stockRow){{const current=stockRow.querySelector(':scope > .tapdetail');if(current){{current.remove();return}}document.querySelectorAll('.tapdetail').forEach(x=>x.remove());const groupBox=stockRow.closest('.groupdetail');const g=findGroup(groupBox?.dataset.openGroup);const s=(g?.stocks||[]).find(x=>String(x.symbol)===String(stockRow.dataset.stock));if(s)stockRow.insertAdjacentHTML('beforeend',stockDetail(s,g));return}}const row=ev.target.closest('.rotrow');if(!row)return;const name=row.dataset.group;const next=row.nextElementSibling;if(next?.classList.contains('groupdetail')&&next.dataset.openGroup===name){{next.remove();return}}document.querySelectorAll('.groupdetail').forEach(x=>x.remove());const g=findGroup(name);if(g)row.insertAdjacentHTML('afterend',groupDetail(g))}});
</script></main></body></html>'''

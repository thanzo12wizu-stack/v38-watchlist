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
    "ENTRY": "ENTRY",
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


def phase_label(value: Any) -> str:
    key = str(value or "")
    return PHASE_JA.get(key, key or "—")


def role_label(value: Any) -> str:
    key = str(value or "")
    return ROLE_JA.get(key, key or "—")


def entry_label(value: Any) -> str:
    key = str(value or "")
    return ENTRY_JA.get(key, key or "—")


def _phase_class(value: Any) -> str:
    key = str(value or "").lower()
    return key if key in {"emerging", "leading", "mature", "losing"} else "losing"


def _market_action(status: str) -> str:
    if status == "GO":
        return "主導株を探す。追いかけず、ENTRYだけ。"
    if status == "SELECTIVE":
        return "上位グループだけ。ENTRY以外は待つ。"
    return "新規は見送る。"


def _top_groups(model: dict[str, Any]) -> list[dict[str, Any]]:
    groups = list(model.get("groups") or [])
    preferred = [g for g in groups if str(g.get("phase")) in {"EMERGING", "LEADING"}]
    return (preferred or groups)[:8]


def _summary_names(rows: list[dict[str, Any]], limit: int = 3) -> str:
    names = [str(x.get("name") or "").strip() for x in rows if str(x.get("name") or "").strip()]
    return " / ".join(names[:limit]) if names else "—"


def render_action_rows(rows: list[dict[str, Any]], empty_text: str) -> str:
    if not rows:
        return f'<div class="empty">{esc(empty_text)}</div>'
    out: list[str] = []
    for x in rows:
        status = str(x.get("status") or x.get("entry_status") or "")
        out.append(
            f'<div class="pickrow">'
            f'<div class="picktop"><b class="ticker">{esc(x.get("symbol"))}</b>'
            f'<span class="role role-{esc(str(x.get("role") or ""))}">{esc(role_label(x.get("role")))}</span>'
            f'<span class="entry entry-{esc(status)}">{esc(entry_label(status))}</span></div>'
            f'<div class="pickmeta">{esc(x.get("group"))}</div>'
            f'<div class="pickwhy">{esc(x.get("reason"))}</div>'
            f'</div>'
        )
    return "".join(out)


def render_group_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">有効なデータがありません</div>'
    out: list[str] = []
    for row in rows:
        out.append(
            f'<button class="leadrow phase-{esc(_phase_class(row.get("phase")))}" data-group="{esc(row.get("name"))}">'
            f'<span class="phasebadge">{esc(phase_label(row.get("phase")))}</span>'
            f'<span class="leadname">{esc(row.get("name"))}</span>'
            f'<span class="leadscore">{esc(row.get("score"))}</span>'
            f'<span class="leaddetail">主導密度 {esc(row.get("leader_density"))} · RS加速 {esc(row.get("acceleration"))}</span>'
            f'</button>'
        )
    return "".join(out)


def render_sector_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">有効なデータがありません</div>'
    out: list[str] = []
    for row in rows:
        out.append(
            f'<div class="leadrow static phase-{esc(_phase_class(row.get("phase")))}">'
            f'<span class="phasebadge">{esc(phase_label(row.get("phase")))}</span>'
            f'<span class="leadname">{esc(row.get("name"))}</span>'
            f'<span class="leadscore">{esc(row.get("score"))}</span>'
            f'<span class="leaddetail">主導密度 {esc(row.get("leader_density"))} · RS加速 {esc(row.get("acceleration"))}</span>'
            f'</div>'
        )
    return "".join(out)


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model["market"]
    cov = model["coverage"]
    market_status = str(market.get("status") or "")
    market_label = MARKET_JA.get(market_status, market_status or "—")
    gate_key = str(market.get("gate") or "")
    gate = GATE_JA.get(gate_key, gate_key or "—")
    gate_cls = gate_key.lower() if gate_key.lower() in {"blue", "green", "yellow", "red"} else "gray"
    ftd = FTD_JA.get(str(market.get("ftd") or ""), str(market.get("ftd") or "—"))
    groups = _top_groups(model)
    actionable = list(model.get("actionable") or [])
    waiting = list(model.get("waiting") or [])
    top_group_text = _summary_names(groups)
    focus_tickers = " ".join(str(x.get("symbol") or "") for x in (actionable or waiting)[:6]) or "—"

    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f17"><meta name="color-scheme" content="dark"><title>Leadership</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html{{background:#0b0f17;color-scheme:dark}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','Hiragino Sans','Noto Sans JP',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}}
button{{font:inherit}}
.wrap{{max-width:680px;margin:0 auto;padding:0 12px calc(42px + env(safe-area-inset-bottom))}}
header{{padding:14px 4px 8px}}
h1{{font-size:18px;font-weight:800;letter-spacing:.01em}}
.asof{{color:#7d8da1;font-size:11px;margin-top:2px}}
.mut{{color:#7d8da1}}
.todayact{{border:1px solid #243044;border-left:4px solid #6b7280;border-radius:11px;background:#121a26;padding:9px 12px;margin:0 0 10px}}
.todayact.ta-blue{{border-left-color:#4d9fff}}.todayact.ta-green{{border-left-color:#34d39c}}.todayact.ta-yellow{{border-left-color:#fbbf24}}.todayact.ta-red{{border-left-color:#f87171}}
.ta-top{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
.ta-h{{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:#7f8da3;font-weight:700}}
.ta-col{{font-weight:800;font-size:14px}}
.ta-mri{{margin-left:auto;font-size:11px;color:#9fb0c5}}.ta-mri b{{font-size:16px;color:#fff}}
.ta-act{{font-size:13px;font-weight:700;line-height:1.5;margin-top:5px;color:#dbe4ef}}
.ta-foot{{font-size:10px;color:#718197;margin-top:4px}}
.card{{background:#0f1623;border:1px solid #1c2533;border-radius:13px;padding:12px 14px;margin-bottom:12px}}
.card.hot-card{{border-color:#2f81f7}}
.card h2{{font-size:14.5px;font-weight:800;margin-bottom:7px;color:#eef3fa}}
.card .sub{{font-size:11px;color:#8494ab;line-height:1.55;margin:-3px 0 9px}}
.summary{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
.sumcell{{background:#101824;border:1px solid #243044;border-radius:9px;padding:8px 10px}}
.sumcell span{{display:block;font-size:9.5px;color:#718197}}
.sumcell b{{display:block;font-size:14px;color:#e6edf3;margin-top:2px;line-height:1.35}}
.sumwide{{grid-column:1/-1}}
.pickrow{{border-top:1px solid #182131;padding:8px 0}}
.pickrow:first-child{{border-top:0}}
.picktop{{display:flex;align-items:center;gap:6px}}
.ticker{{font-size:15px;color:#9ecbff}}
.role,.entry,.phasebadge{{display:inline-block;font-size:8.5px;font-weight:800;border-radius:5px;padding:1px 5px}}
.role-PIONEER{{background:rgba(67,201,138,.14);color:#43c98a;border:1px solid rgba(67,201,138,.35)}}
.role-LEADER{{background:rgba(88,166,255,.16);color:#8fb3ff;border:1px solid rgba(88,166,255,.45)}}
.role-FOLLOWER,.role-NO_DATA{{background:#0f1622;color:#6f8198;border:1px solid #1c2533}}
.entry{{margin-left:auto}}
.entry-ENTRY{{background:rgba(67,201,138,.14);color:#43c98a;border:1px solid rgba(67,201,138,.35)}}
.entry-WAIT,.entry-WATCH{{background:rgba(227,170,60,.15);color:#e3aa3c;border:1px solid rgba(227,170,60,.4)}}
.entry-AVOID{{background:rgba(229,100,94,.16);color:#e5645e;border:1px solid rgba(229,100,94,.45)}}
.entry-NO_DATA{{background:#0f1622;color:#6f8198;border:1px solid #1c2533}}
.pickmeta{{font-size:10.5px;color:#7e8ea3;margin-top:2px}}
.pickwhy{{font-size:11.5px;color:#cbd5e1;margin-top:2px}}
.leadlist{{display:grid;gap:5px}}
.leadrow{{width:100%;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 7px;align-items:center;text-align:left;background:#101824;border:1px solid #243044;border-left:3px solid #475569;border-radius:9px;padding:8px 9px;color:inherit;cursor:pointer}}
.leadrow.static{{cursor:default}}
.leadrow.phase-emerging{{border-left-color:#34d39c}}.leadrow.phase-leading{{border-left-color:#4d9fff}}.leadrow.phase-mature{{border-left-color:#fbbf24}}.leadrow.phase-losing{{border-left-color:#475569}}
.phasebadge{{color:#9fb0c5;background:#141b29;border:1px solid #243044}}
.phase-emerging .phasebadge{{color:#43c98a}}.phase-leading .phasebadge{{color:#8fb3ff}}.phase-mature .phasebadge{{color:#e3aa3c}}
.leadname{{font-size:12.5px;font-weight:700;color:#e6edf3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.leadscore{{font-size:15px;font-weight:800;color:#fff;font-variant-numeric:tabular-nums}}
.leaddetail{{grid-column:2/4;font-size:9.5px;color:#718197;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.board-title{{display:flex;align-items:baseline;justify-content:space-between;gap:8px}}
.board-title small{{font-size:9.5px;color:#718197;font-weight:600}}
.stockrow{{border-top:1px solid #182131;padding:8px 0}}
.stockrow:first-child{{border-top:0}}
.stocktop{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}}
.stockname{{min-width:0}}
.stockname b{{font-size:14px;color:#9ecbff}}
.stockname small{{display:block;color:#718197;font-size:9.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}}
.stockscore{{text-align:right}}.stockscore b{{font-size:17px}}.stockscore small{{display:block;font-size:8.5px;color:#718197}}
.stocktags{{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:5px}}
.metricline{{font-size:10.5px;color:#9fb0c5;margin-top:4px;line-height:1.45}}
.reason{{font-size:11.5px;color:#cbd5e1;margin-top:3px}}
details.more{{margin-top:5px}}
details.more>summary{{cursor:pointer;list-style:none;font-size:10px;color:#6f8198;font-weight:700}}
details.more>summary::-webkit-details-marker{{display:none}}
details.more>summary:before{{content:"▸ ";font-size:8px}}details.more[open]>summary:before{{content:"▾ "}}
.morebody{{font-size:10px;color:#7e8ea3;line-height:1.55;margin-top:4px}}
.empty{{font-size:11.5px;color:#7d8da1;padding:4px 0}}
.datafold{{margin-top:2px}}
.datafold>summary{{cursor:pointer;list-style:none;font-size:10.5px;color:#7d8da1;font-weight:700}}
.datafold>summary::-webkit-details-marker{{display:none}}
.datafold>summary:before{{content:"▸ ";font-size:8px}}.datafold[open]>summary:before{{content:"▾ "}}
.datafold p{{font-size:10px;color:#64748b;line-height:1.55;margin-top:5px}}
@media(min-width:760px){{.wrap{{max-width:920px;padding-left:20px;padding-right:20px}}body{{font-size:15px}}h1{{font-size:21px}}.card{{padding:14px 18px;border-radius:15px;margin-bottom:14px}}.card h2{{font-size:16px}}.card .sub{{font-size:12px}}.summary{{grid-template-columns:repeat(4,1fr)}}.sumwide{{grid-column:span 2}}}}
@media(min-width:1080px){{.wrap{{max-width:1060px}}}}
</style></head><body><main class="wrap">
<header><h1>Leadership</h1><div class="asof">{esc(cov.get("market_asof") or market.get("asof"))} · 対象 {esc(cov.get("stocks"))}銘柄</div></header>

<section class="todayact ta-{esc(gate_cls)}">
  <div class="ta-top"><span class="ta-h">今日の主導株判断</span><span class="ta-col">{esc(market_label)}</span><span class="ta-mri">MRI <b>{esc(market.get("mri"))}</b></span></div>
  <div class="ta-act">{esc(_market_action(market_status))}</div>
  <div class="ta-foot">{esc(gate)} · {esc(ftd)} · RS63 {esc(cov.get("rs63"))}銘柄</div>
</section>

<section class="card">
  <h2>本日の結論</h2>
  <div class="summary">
    <div class="sumcell sumwide"><span>主役</span><b>{esc(top_group_text)}</b></div>
    <div class="sumcell"><span>今入れる</span><b>{len(actionable)}銘柄</b></div>
    <div class="sumcell"><span>待機</span><b>{len(waiting)}銘柄</b></div>
    <div class="sumcell sumwide"><span>監視優先</span><b>{esc(focus_tickers)}</b></div>
  </div>
</section>

<section class="card hot-card">
  <h2>今、入れる</h2>
  <div class="sub">主導グループ × 先導/主導株 × ENTRY。ここだけ新規候補。</div>
  {render_action_rows(actionable, "該当なし。強いだけの株は追わない。")}
</section>

<section class="card">
  <h2>強いが、まだ待つ</h2>
  <div class="sub">主導性はある。押し目・初動条件まで待つ。</div>
  {render_action_rows(waiting[:8], "該当なし。")}
</section>

<section class="card">
  <h2>主導グループ</h2>
  <div class="sub">上から優先。タップで下の主導株を切り替え。</div>
  <div class="leadlist">{render_group_rows(groups)}</div>
</section>

<section class="card">
  <h2>主導セクター</h2>
  <div class="sub">セクターは背景確認。銘柄選びはグループを優先。</div>
  <div class="leadlist">{render_sector_rows(list(model.get("sectors") or [])[:8])}</div>
</section>

<section class="card">
  <div class="board-title"><h2 id="boardTitle">主導株</h2><small id="boardMeta"></small></div>
  <div id="board"></div>
</section>

<section class="card">
  <details class="datafold"><summary>データ状況</summary><p id="coverage"></p></details>
</section>

<script id="payload" type="application/json">{payload}</script>
<script>
const data=JSON.parse(document.getElementById('payload').textContent);
const roleJa={{PIONEER:'先導株',LEADER:'主導株',FOLLOWER:'追随',NO_DATA:'データ不足'}};
const entryJa={{ENTRY:'ENTRY',WATCH:'監視',WAIT:'待機',AVOID:'見送り',NO_DATA:'データ不足'}};
const phaseJa={{EMERGING:'新興',LEADING:'主導',MATURE:'成熟',LOSING:'失速'}};
const board=document.getElementById('board');
function v(x){{return x===null||x===undefined?'—':x}}
function escJs(x){{return String(x===null||x===undefined?'—':x).replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]))}}
function render(name){{
  const g=data.groups.find(x=>x.name===name)||data.groups[0];
  if(!g)return;
  document.getElementById('boardTitle').textContent=g.name;
  document.getElementById('boardMeta').textContent=`${{phaseJa[g.phase]||g.phase}} · ${{g.score}}/100`;
  board.innerHTML=(g.stocks||[]).map(s=>`
    <div class="stockrow">
      <div class="stocktop">
        <div class="stockname"><b>${{escJs(s.symbol)}}</b><small>${{escJs(s.name||'')}}</small></div>
        <div class="stockscore"><b>${{v(s.strength)}}</b><small>主導度</small></div>
      </div>
      <div class="stocktags">
        <span class="role role-${{s.role}}">${{roleJa[s.role]||s.role}}</span>
        <span class="entry entry-${{s.entry.status}}">${{entryJa[s.entry.status]||s.entry.status}}</span>
      </div>
      <div class="metricline">RS 189/63/21：${{v(s.rs189)}} / ${{v(s.rs63)}} / ${{v(s.rs21)}}　·　加速 ${{v(s.acceleration)}}</div>
      <div class="reason">${{escJs(s.entry.reason)}}</div>
      <details class="more"><summary>詳細</summary><div class="morebody">52週高値差 ${{v(s.near_high)}} · RVOL ${{v(s.volume_ratio)}} · EPS ${{escJs(s.eps_label||'—')}}</div></details>
    </div>`).join('');
}}
document.querySelectorAll('[data-group]').forEach(el=>el.addEventListener('click',()=>render(el.dataset.group)));
render(data.groups[0]?.name);
const c=data.coverage;
document.getElementById('coverage').textContent=`${{c.metric_source}} · 対象 ${{c.stocks}}銘柄 · RS63 ${{c.rs63}} · Entry判定 ${{c.entry_inputs}} · 信頼度 ${{c.confidence}}`;
</script></main></body></html>'''

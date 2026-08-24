from __future__ import annotations

import html
import json
from typing import Any


PHASE_JA = {"EMERGING": "新興", "LEADING": "主導", "MATURE": "成熟", "LOSING": "失速"}
ROLE_JA = {"PIONEER": "先導株", "LEADER": "主導株", "FOLLOWER": "追随", "NO_DATA": "データ不足"}
ENTRY_JA = {"ENTRY": "ENTRY", "WATCH": "監視", "WAIT": "待機", "AVOID": "見送り", "NO_DATA": "データ不足"}
MARKET_JA = {"GO": "攻める", "SELECTIVE": "選別", "STOP": "停止"}
GATE_JA = {"Green": "緑", "Blue": "青", "Yellow": "黄", "Red": "赤", "Black": "黒"}
FTD_JA = {"FTD_ACTIVE": "FTD有効", "RALLY_ATTEMPT": "ラリー試行", "CORRECTION": "調整"}
BREAKOUT_JA = {
    "BREAKOUT_NOW": "本日ブレイク",
    "BREAKOUT_RECENT": "突破直後",
    "BREAKOUT_WATCH": "ブレイク直前",
    "EXTENDED": "伸びすぎ",
    "NONE": "初動待ち",
    "NO_DATA": "BOデータ不足",
}


def esc(value: Any) -> str:
    return html.escape(str("—" if value is None else value))


def _phase(value: Any) -> str:
    key = str(value or "")
    return PHASE_JA.get(key, key or "—")


def _role(value: Any) -> str:
    key = str(value or "")
    return ROLE_JA.get(key, key or "—")


def _entry(value: Any) -> str:
    key = str(value or "")
    return ENTRY_JA.get(key, key or "—")


def _phase_class(value: Any) -> str:
    key = str(value or "").lower()
    return key if key in {"emerging", "leading", "mature", "losing"} else "losing"


def _market_action(status: str) -> str:
    if status == "GO":
        return "主導グループの初動と主導株ブレイクを優先。伸びた株は追わない。"
    if status == "SELECTIVE":
        return "上位グループだけ。構造が悪いSupply直下は突破待ち。"
    return "新規は見送る。"


def _top_groups(model: dict[str, Any]) -> list[dict[str, Any]]:
    groups = list(model.get("groups") or [])
    preferred = [g for g in groups if str(g.get("phase")) in {"EMERGING", "LEADING"}]
    return (preferred or groups)[:8]


def _summary_names(rows: list[dict[str, Any]], limit: int = 3) -> str:
    names = [str(x.get("name") or "").strip() for x in rows if str(x.get("name") or "").strip()]
    return " / ".join(names[:limit]) if names else "—"


def _distance(value: Any, *, prefix: str) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{prefix}{x:.1f}%"


def render_action_rows(rows: list[dict[str, Any]], empty_text: str) -> str:
    if not rows:
        return f'<div class="empty">{esc(empty_text)}</div>'
    out: list[str] = []
    for row in rows:
        status = str(row.get("status") or "")
        bo = str(row.get("breakout_status") or "")
        out.append(
            '<div class="pickrow">'
            f'<div class="picktop"><b class="ticker">{esc(row.get("symbol"))}</b>'
            f'<span class="role role-{esc(str(row.get("role") or ""))}">{esc(_role(row.get("role")))}</span>'
            f'<span class="bo bo-{esc(bo)}">{esc(BREAKOUT_JA.get(bo, bo or "—"))}</span>'
            f'<span class="entry entry-{esc(status)}">{esc(_entry(status))}</span></div>'
            f'<div class="pickmeta">{esc(row.get("group"))} · 総合 {esc(row.get("priority_score"))} · 構造 {esc(row.get("structure_score"))} · {esc(row.get("structure_label"))}</div>'
            f'<div class="pickwhy">{esc(row.get("reason"))}</div>'
            '</div>'
        )
    return "".join(out)


def render_group_rows(rows: list[dict[str, Any]], *, compact: bool = False) -> str:
    if not rows:
        return '<div class="empty">有効なデータがありません</div>'
    out: list[str] = []
    for row in rows:
        supply = _distance(row.get("supply_distance_pct"), prefix="+")
        demand = _distance(row.get("demand_distance_pct"), prefix="−")
        detail = (
            f'主導 {esc(row.get("leadership_score"))} · 構造 {esc(row.get("structure_score"))} · '
            f'{esc(row.get("structure_label"))} · BO {esc(row.get("leader_breakouts"))}'
        )
        if not compact:
            detail += f' · Supply {supply} · Demand {demand}'
        out.append(
            f'<button class="leadrow phase-{esc(_phase_class(row.get("phase")))}" data-group="{esc(row.get("name"))}">'
            f'<span class="phasebadge">{esc(_phase(row.get("phase")))}</span>'
            f'<span class="leadname">{esc(row.get("name"))}</span>'
            f'<span class="leadscore">{esc(row.get("priority_score"))}</span>'
            f'<span class="leaddetail">{detail}</span>'
            '</button>'
        )
    return "".join(out)


def render_sector_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">有効なデータがありません</div>'
    out: list[str] = []
    for row in rows:
        out.append(
            f'<div class="leadrow static phase-{esc(_phase_class(row.get("phase")))}">'
            f'<span class="phasebadge">{esc(_phase(row.get("phase")))}</span>'
            f'<span class="leadname">{esc(row.get("name"))}</span>'
            f'<span class="leadscore">{esc(row.get("priority_score") or row.get("score"))}</span>'
            f'<span class="leaddetail">主導 {esc(row.get("leadership_score") or row.get("score"))} · 構造 {esc(row.get("structure_score"))} · {esc(row.get("structure_label"))}</span>'
            '</div>'
        )
    return "".join(out)


def render_html(model: dict[str, Any]) -> str:
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    market = model.get("market") or {}
    coverage = model.get("coverage") or {}
    market_status = str(market.get("status") or "")
    market_label = MARKET_JA.get(market_status, market_status or "—")
    gate_key = str(market.get("gate") or "")
    gate = GATE_JA.get(gate_key, gate_key or "—")
    gate_cls = gate_key.lower() if gate_key.lower() in {"blue", "green", "yellow", "red"} else "gray"
    ftd = FTD_JA.get(str(market.get("ftd") or ""), str(market.get("ftd") or "—"))
    groups = _top_groups(model)
    all_groups = list(model.get("groups") or [])
    active_groups = [g for g in all_groups if str(g.get("phase")) in {"EMERGING", "LEADING"}]
    actionable = list(model.get("actionable") or [])
    waiting = list(model.get("waiting") or [])
    top_group_text = _summary_names(groups)
    focus_tickers = " ".join(str(x.get("symbol") or "") for x in (actionable or waiting)[:6]) or "—"

    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b0f17"><meta name="color-scheme" content="dark"><title>Leadership</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}html{{background:#0b0f17;color-scheme:dark}}body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue','Hiragino Sans','Noto Sans JP',sans-serif;background:#0b0f17;color:#e6edf3;font-size:14px;-webkit-text-size-adjust:100%}}button{{font:inherit}}
.wrap{{max-width:680px;margin:0 auto;padding:0 12px calc(42px + env(safe-area-inset-bottom))}}header{{padding:14px 4px 8px}}h1{{font-size:18px;font-weight:800}}.asof{{color:#7d8da1;font-size:11px;margin-top:2px}}
.todayact{{border:1px solid #243044;border-left:4px solid #6b7280;border-radius:11px;background:#121a26;padding:9px 12px;margin-bottom:10px}}.todayact.ta-blue{{border-left-color:#4d9fff}}.todayact.ta-green{{border-left-color:#34d39c}}.todayact.ta-yellow{{border-left-color:#fbbf24}}.todayact.ta-red{{border-left-color:#f87171}}.ta-top{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}.ta-h{{font-size:9.5px;letter-spacing:.1em;color:#7f8da3;font-weight:700}}.ta-col{{font-weight:800;font-size:14px}}.ta-mri{{margin-left:auto;font-size:11px;color:#9fb0c5}}.ta-mri b{{font-size:16px;color:#fff}}.ta-act{{font-size:13px;font-weight:700;line-height:1.5;margin-top:5px}}.ta-foot{{font-size:10px;color:#718197;margin-top:4px}}
.card{{background:#0f1623;border:1px solid #1c2533;border-radius:13px;padding:12px 14px;margin-bottom:12px}}.card.hot{{border-color:#2f81f7}}.card h2{{font-size:14.5px;font-weight:800;margin-bottom:7px;color:#eef3fa}}.sub{{font-size:11px;color:#8494ab;line-height:1.55;margin:-3px 0 9px}}.summary{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}.sumcell{{background:#101824;border:1px solid #243044;border-radius:9px;padding:8px 10px}}.sumcell span{{display:block;font-size:9.5px;color:#718197}}.sumcell b{{display:block;font-size:14px;margin-top:2px}}.sumwide{{grid-column:1/-1}}
.pickrow{{border-top:1px solid #182131;padding:8px 0}}.pickrow:first-child{{border-top:0}}.picktop{{display:flex;align-items:center;gap:5px;flex-wrap:wrap}}.ticker{{font-size:15px;color:#9ecbff}}.role,.entry,.bo,.phasebadge{{display:inline-block;font-size:8.5px;font-weight:800;border-radius:5px;padding:1px 5px;border:1px solid #243044}}.role-PIONEER{{color:#43c98a;border-color:rgba(67,201,138,.35)}}.role-LEADER{{color:#8fb3ff;border-color:rgba(88,166,255,.45)}}.entry{{margin-left:auto}}.entry-ENTRY{{color:#43c98a;border-color:rgba(67,201,138,.35)}}.entry-WAIT,.entry-WATCH{{color:#e3aa3c;border-color:rgba(227,170,60,.4)}}.entry-AVOID{{color:#e5645e;border-color:rgba(229,100,94,.45)}}.bo-BREAKOUT_NOW{{color:#43c98a}}.bo-BREAKOUT_RECENT{{color:#8fb3ff}}.bo-BREAKOUT_WATCH{{color:#e3aa3c}}.bo-EXTENDED{{color:#e5645e}}.pickmeta{{font-size:10.5px;color:#7e8ea3;margin-top:3px}}.pickwhy{{font-size:11.5px;color:#cbd5e1;margin-top:2px}}
.leadlist{{display:grid;gap:5px}}.leadrow{{width:100%;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 7px;align-items:center;text-align:left;background:#101824;border:1px solid #243044;border-left:3px solid #475569;border-radius:9px;padding:8px 9px;color:inherit;cursor:pointer}}.leadrow.static{{cursor:default}}.phase-emerging{{border-left-color:#34d39c}}.phase-leading{{border-left-color:#4d9fff}}.phase-mature{{border-left-color:#fbbf24}}.phasebadge{{color:#9fb0c5;background:#141b29}}.phase-emerging .phasebadge{{color:#43c98a}}.phase-leading .phasebadge{{color:#8fb3ff}}.phase-mature .phasebadge{{color:#e3aa3c}}.leadname{{font-size:12.5px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.leadscore{{font-size:15px;font-weight:800}}.leaddetail{{grid-column:2/4;font-size:9.5px;color:#718197;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.board-title{{display:flex;align-items:baseline;justify-content:space-between;gap:8px}}.board-title small{{font-size:9.5px;color:#718197}}.stockrow{{border-top:1px solid #182131;padding:8px 0}}.stockrow:first-child{{border-top:0}}.stocktop{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}}.stockname b{{font-size:14px;color:#9ecbff}}.stockname small{{display:block;color:#718197;font-size:9.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.stockscore{{text-align:right}}.stockscore b{{font-size:17px}}.stockscore small{{display:block;font-size:8.5px;color:#718197}}.stocktags{{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:5px}}.metricline{{font-size:10.5px;color:#9fb0c5;margin-top:4px;line-height:1.45}}.reason{{font-size:11.5px;color:#cbd5e1;margin-top:3px}}details.more{{margin-top:5px}}details>summary{{cursor:pointer;list-style:none;color:#6f8198;font-size:10.5px;font-weight:700}}details>summary::-webkit-details-marker{{display:none}}details>summary:before{{content:"▸ ";font-size:8px}}details[open]>summary:before{{content:"▾ "}}.morebody{{font-size:10px;color:#7e8ea3;line-height:1.55;margin-top:4px}}.fold{{margin-top:8px;padding-top:8px;border-top:1px solid #182131}}.empty{{font-size:11.5px;color:#7d8da1;padding:4px 0}}
@media(min-width:760px){{.wrap{{max-width:920px;padding-left:20px;padding-right:20px}}body{{font-size:15px}}h1{{font-size:21px}}.card{{padding:14px 18px;border-radius:15px}}.summary{{grid-template-columns:repeat(4,1fr)}}.sumwide{{grid-column:span 2}}}}@media(min-width:1080px){{.wrap{{max-width:1060px}}}}
</style></head><body><main class="wrap">
<header><h1>Leadership</h1><div class="asof">{esc(coverage.get("market_asof") or market.get("asof"))} · 対象 {esc(coverage.get("stocks"))}銘柄 · 細分類 {esc(coverage.get("groups"))}</div></header>
<section class="todayact ta-{esc(gate_cls)}"><div class="ta-top"><span class="ta-h">今日の主導株判断</span><span class="ta-col">{esc(market_label)}</span><span class="ta-mri">MRI <b>{esc(market.get("mri"))}</b></span></div><div class="ta-act">{esc(_market_action(market_status))}</div><div class="ta-foot">{esc(gate)} · {esc(ftd)} · RS63 {esc(coverage.get("rs63"))}銘柄</div></section>
<section class="card"><h2>本日の結論</h2><div class="summary"><div class="sumcell sumwide"><span>主役</span><b>{esc(top_group_text)}</b></div><div class="sumcell"><span>今入れる</span><b>{len(actionable)}銘柄</b></div><div class="sumcell"><span>待機</span><b>{len(waiting)}銘柄</b></div><div class="sumcell sumwide"><span>監視優先</span><b>{esc(focus_tickers)}</b></div></div></section>
<section class="card hot"><h2>今、入れる</h2><div class="sub">主導性 × 構造 × 主導株ブレイク。Supply直下は原則ここから外す。</div>{render_action_rows(actionable, "該当なし。強いだけの株は追わない。")}</section>
<section class="card"><h2>強いが、まだ待つ</h2><div class="sub">主導性はあるが、Supply突破・押し目・初動条件を待つ。</div>{render_action_rows(waiting[:10], "該当なし。")}</section>
<section class="card"><h2>主導グループ</h2><div class="sub">総合 = 主導 60% + 構造 40%。構造は上値Supply・下値Demand・吸収・出来高乾きを評価。</div><div class="leadlist">{render_group_rows(groups, compact=True)}</div><details class="fold"><summary>新興・主導をすべて見る（{len(active_groups)}）</summary><div class="leadlist" style="margin-top:7px">{render_group_rows(active_groups)}</div></details><details class="fold"><summary>全Industry Groupを見る（{len(all_groups)}）</summary><div class="leadlist" style="margin-top:7px">{render_group_rows(all_groups)}</div></details></section>
<section class="card"><h2>大分類セクター</h2><div class="sub">背景確認用。銘柄選びは上の細分類Industry Groupを優先。</div><div class="leadlist">{render_sector_rows(list(model.get("sectors") or [])[:10])}</div></section>
<section class="card"><div class="board-title"><h2 id="boardTitle">主導株</h2><small id="boardMeta"></small></div><div id="board"></div></section>
<section class="card"><details><summary>判定方法・データ状況</summary><div class="morebody">Supply＝未突破20/50日Pivot。Demand＝21EMA・50SMA・63VWAP・突破済Pivotのうち直下の支持。Supply直前でRS加速・低出来高テスト、またはブレイク成立を吸収として評価。<br>{esc(coverage.get("metric_source"))} · 対象 {esc(coverage.get("stocks"))} · Structure {esc(coverage.get("structure_groups"))}グループ · 信頼度 {esc(coverage.get("confidence"))}</div></details></section>
<script id="payload" type="application/json">{payload}</script><script>
const data=JSON.parse(document.getElementById('payload').textContent);const roleJa={{PIONEER:'先導株',LEADER:'主導株',FOLLOWER:'追随',NO_DATA:'データ不足'}};const entryJa={{ENTRY:'ENTRY',WATCH:'監視',WAIT:'待機',AVOID:'見送り',NO_DATA:'データ不足'}};const phaseJa={{EMERGING:'新興',LEADING:'主導',MATURE:'成熟',LOSING:'失速'}};const boJa={{BREAKOUT_NOW:'本日ブレイク',BREAKOUT_RECENT:'突破直後',BREAKOUT_WATCH:'ブレイク直前',EXTENDED:'伸びすぎ',NONE:'初動待ち',NO_DATA:'BOデータ不足'}};const board=document.getElementById('board');function v(x){{return x===null||x===undefined?'—':x}}function e(x){{return String(x===null||x===undefined?'—':x).replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]))}}function pct(x,p){{return x===null||x===undefined?'—':p+Number(x).toFixed(1)+'%'}}
function render(name){{const g=data.groups.find(x=>x.name===name)||data.groups[0];if(!g)return;document.getElementById('boardTitle').textContent=g.name;document.getElementById('boardMeta').textContent=`${{phaseJa[g.phase]||g.phase}} · 総合 ${{v(g.priority_score)}} · 構造 ${{v(g.structure_score)}}`;board.innerHTML=(g.stocks||[]).map(s=>{{const st=s.structure||{{}};const bo=(s.breakout||{{}}).status||'';return `<div class="stockrow"><div class="stocktop"><div class="stockname"><b>${{e(s.symbol)}}</b><small>${{e(s.name||'')}}</small></div><div class="stockscore"><b>${{v(s.strength)}}</b><small>主導度</small></div></div><div class="stocktags"><span class="role role-${{s.role}}">${{roleJa[s.role]||s.role}}</span><span class="bo bo-${{bo}}">${{boJa[bo]||bo}}</span><span class="entry entry-${{s.entry.status}}">${{entryJa[s.entry.status]||s.entry.status}}</span></div><div class="metricline">RS189/63/21 ${{v(s.rs189)}} / ${{v(s.rs63)}} / ${{v(s.rs21)}} · 加速 ${{v(s.acceleration)}} · 構造 ${{v(st.score)}}</div><div class="metricline">Supply ${{pct(st.supply_distance_pct,'+')}} · Demand ${{pct(st.demand_distance_pct,'−')}} · ${{e(st.label||'')}}</div><div class="reason">${{e(s.entry.reason)}}</div><details class="more"><summary>詳細</summary><div class="morebody">RVOL ${{v(s.volume_ratio)}} · 52週高値差 ${{v(s.near_high)}} · EPS ${{e(s.eps_label||'—')}} · Supply吸収 ${{v(st.absorption_score)}}</div></details></div>`}}).join('')}}document.querySelectorAll('[data-group]').forEach(el=>el.addEventListener('click',()=>render(el.dataset.group)));render(data.groups[0]?.name);
</script></main></body></html>'''

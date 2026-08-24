from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from leadership.prebreakout_overlay import apply_prebreakout_overlay
    from leadership.render_structured import render_html
    from leadership.structure_overlay import apply_structure_overlay
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from prebreakout_overlay import apply_prebreakout_overlay
    from render_structured import render_html
    from structure_overlay import apply_structure_overlay


PREBREAKOUT_PRESENTATION = {
    "READY": ("発火目前", "READY"),
    "COILED": ("発火準備", "COILED"),
    "WATCH": ("監視", "WATCH"),
    "NOT_READY": ("形成待ち", "BUILDING"),
    "ALREADY_BROKE": ("発火済み", "TRIGGERED"),
    "NO_DATA": ("判定不能", "NO DATA"),
}


def _load_exchange_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            exchange = str(row.get("取引所") or row.get("exchange") or row.get("Exchange") or "").strip().upper()
            if symbol and exchange:
                out[symbol] = exchange
    return out


def _attach_exchange(model: dict[str, Any], exchange_map: dict[str, str] | None) -> dict[str, Any]:
    out = deepcopy(model)
    if not exchange_map:
        return out
    for group in list(out.get("groups") or []):
        for stock in list(group.get("stocks") or []):
            symbol = str(stock.get("symbol") or "").upper()
            if symbol in exchange_map:
                stock["exchange"] = exchange_map[symbol]
    return out


def _polish_model(model: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(model)
    for group in list(out.get("groups") or []):
        for stock in list(group.get("stocks") or []):
            pre = stock.get("prebreakout") if isinstance(stock.get("prebreakout"), dict) else None
            if pre:
                key = str(pre.get("status") or "")
                if key in PREBREAKOUT_PRESENTATION:
                    pre["label"] = PREBREAKOUT_PRESENTATION[key][0]

    for bucket_name in ("actionable", "waiting"):
        for item in list(out.get(bucket_name) or []):
            key = str(item.get("prebreakout_status") or "")
            if key not in PREBREAKOUT_PRESENTATION:
                continue
            jp, _ = PREBREAKOUT_PRESENTATION[key]
            item["prebreakout_label"] = jp
            score = item.get("prebreakout_score")
            old_reason = str(item.get("reason") or "")
            tail = old_reason.split(" / ", 1)[1] if " / " in old_reason else old_reason
            item["reason"] = f"{jp} · 準備度 {score} / {tail}" if score is not None else f"{jp} / {tail}"
            # Candidate cards use the pre-breakout state itself as the visible badge.
            item["status"] = key
    return out


def _prebreakout_copy(page: str) -> str:
    replacements = {
        "主導グループの初動と主導株ブレイクを優先。伸びた株は追わない。": "主導株の発火前を優先。Pivot直下で締まった銘柄を先に見る。発火済みは追わない。",
        "上位グループだけ。構造が悪いSupply直下は突破待ち。": "上位グループだけ。発火目前・発火準備を優先し、発火済みは追わない。",
        "<span>今入れる</span>": "<span>発火目前</span>",
        "<span>待機</span>": "<span>次点候補</span>",
        "<h2>今、入れる</h2>": "<h2>発火前・最優先</h2>",
        "主導性 × 構造 × 主導株ブレイク。Supply直下は原則ここから外す。": "主導株 × Pivotまで0〜4% × RS高位/加速 × Supply吸収 × Demand支持。ブレイクする前だけを表示。",
        "<h2>強いが、まだ待つ</h2>": "<h2>発火前・次点</h2>",
        "主導性はあるが、Supply突破・押し目・初動条件を待つ。": "発火準備・監視。Pivotまでの距離や吸収がもう一段整えば最優先へ。",
        "Supply＝未突破20/50日Pivot。Demand＝21EMA・50SMA・63VWAP・突破済Pivotのうち直下の支持。Supply直前でRS加速・低出来高テスト、またはブレイク成立を吸収として評価。": "発火前候補＝未突破20/50日Pivotまでの距離、主導度、RS63/21、RS加速、Supply吸収、Demand支持、出来高乾きを統合。発火済みは候補リストから除外。",
        '<span class="entry entry-READY">READY</span>': '<span class="entry entry-READY">発火目前 <small class="engmini">READY</small></span>',
        '<span class="entry entry-COILED">COILED</span>': '<span class="entry entry-COILED">発火準備 <small class="engmini">COILED</small></span>',
    }
    for old, new in replacements.items():
        page = page.replace(old, new)
    return page


def _interactive_shell(page: str) -> str:
    css = r'''
.engmini{font-size:7px;letter-spacing:.06em;opacity:.58;margin-left:2px;font-weight:700}
.entry-READY{color:#43c98a;border-color:rgba(67,201,138,.48);background:rgba(67,201,138,.06)}
.entry-COILED{color:#8fb3ff;border-color:rgba(88,166,255,.46);background:rgba(88,166,255,.05)}
.pickrow,.stockrow{cursor:pointer}
.pickrow:hover,.stockrow:hover{background:rgba(255,255,255,.015)}
.taphelp{font-size:9.5px;color:#65758a;margin:5px 0 1px}
.tapdetail{margin-top:9px;padding:11px;background:#0b111b;border:1px solid #26344a;border-radius:10px;cursor:default}
.detailhead{display:flex;gap:8px;align-items:flex-start;justify-content:space-between;margin-bottom:8px}
.detailtitle b{font-size:15px;color:#dbeafe}.detailtitle small{display:block;font-size:9.5px;color:#718197;margin-top:1px}
.detailstate{text-align:right;font-size:11px;font-weight:800;color:#e6edf3}.detailstate small{display:block;font-size:7px;color:#718197;letter-spacing:.08em;margin-top:1px}
.detailgrid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:6px}
.detailcell{background:#101824;border:1px solid #1c293a;border-radius:8px;padding:7px 8px;min-width:0}
.detailcell span{display:block;font-size:8.5px;color:#718197}.detailcell b{display:block;font-size:11.5px;color:#dbe4ef;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.detailwhy{font-size:10.5px;color:#aebdce;line-height:1.55;margin:8px 1px 0}
.tvbtn{display:flex;align-items:center;justify-content:center;text-decoration:none;margin-top:9px;padding:9px 10px;border-radius:9px;border:1px solid #2f81f7;background:rgba(47,129,247,.08);color:#9ecbff;font-size:11.5px;font-weight:800}
.tvbtn:active{transform:translateY(1px)}
@media(min-width:760px){.detailgrid{grid-template-columns:repeat(4,1fr)}}
'''
    page = page.replace("</style>", css + "\n</style>", 1)
    page = page.replace(
        '<div class="sub">主導株 × Pivotまで0〜4% × RS高位/加速 × Supply吸収 × Demand支持。ブレイクする前だけを表示。</div>',
        '<div class="sub">主導株 × Pivotまで0〜4% × RS高位/加速 × Supply吸収 × Demand支持。ブレイクする前だけを表示。</div><div class="taphelp">銘柄をタップすると詳細とTradingViewを開けます。</div>',
        1,
    )
    page = page.replace(
        '<div class="sub">発火準備・監視。Pivotまでの距離や吸収がもう一段整えば最優先へ。</div>',
        '<div class="sub">発火準備・監視。Pivotまでの距離や吸収がもう一段整えば最優先へ。</div><div class="taphelp">銘柄をタップで詳細。</div>',
        1,
    )

    script = r'''
<script>
(()=>{
  const detailData=JSON.parse(document.getElementById('payload').textContent);
  const preNames={READY:['発火目前','READY'],COILED:['発火準備','COILED'],WATCH:['監視','WATCH'],NOT_READY:['形成待ち','BUILDING'],ALREADY_BROKE:['発火済み','TRIGGERED'],NO_DATA:['判定不能','NO DATA']};
  const roleNames={PIONEER:'先導株',LEADER:'主導株',FOLLOWER:'追随',NO_DATA:'データ不足'};
  const boNames={BREAKOUT_NOW:'本日ブレイク',BREAKOUT_RECENT:'突破直後',BREAKOUT_WATCH:'ブレイク直前',EXTENDED:'伸びすぎ',NONE:'初動待ち',NO_DATA:'データ不足'};
  const h=x=>String(x===null||x===undefined?'—':x).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const val=(x,suffix='')=>x===null||x===undefined?'—':h(x)+suffix;
  const pct=(x,prefix='')=>x===null||x===undefined?'—':prefix+Number(x).toFixed(1)+'%';
  function findStock(symbol){
    for(const g of (detailData.groups||[])){
      const s=(g.stocks||[]).find(x=>String(x.symbol||'').toUpperCase()===String(symbol||'').toUpperCase());
      if(s)return {stock:s,group:g};
    }
    return null;
  }
  function tvUrl(s){
    const ex=String(s.exchange||'').trim().toUpperCase();
    const sym=String(s.symbol||'').trim().toUpperCase();
    const q=ex?`${ex}:${sym}`:sym;
    return 'https://www.tradingview.com/chart/?symbol='+encodeURIComponent(q);
  }
  function detailHtml(s,g){
    const pre=s.prebreakout||{};
    const st=s.structure||{};
    const state=preNames[pre.status]||['状況確認',''];
    const reason=pre.reason||s.entry?.reason||'—';
    return `<div class="tapdetail" data-symbol="${h(s.symbol)}">
      <div class="detailhead">
        <div class="detailtitle"><b>${h(s.symbol)} ${h(s.name||'')}</b><small>${h(s.exchange||'')} · ${h(g?.name||s.group||'')} · ${h(roleNames[s.role]||s.role||'')}</small></div>
        <div class="detailstate">${h(state[0])}<small>${h(state[1])}</small></div>
      </div>
      <div class="detailgrid">
        <div class="detailcell"><span>現在値</span><b>${val(s.price)}</b></div>
        <div class="detailcell"><span>準備度</span><b>${val(pre.score,' / 100')}</b></div>
        <div class="detailcell"><span>Pivotまで</span><b>${pct(pre.pivot_gap_pct,'')}</b></div>
        <div class="detailcell"><span>主導度</span><b>${val(s.strength,' / 100')}</b></div>
        <div class="detailcell"><span>RS 189 / 63 / 21</span><b>${val(s.rs189)} / ${val(s.rs63)} / ${val(s.rs21)}</b></div>
        <div class="detailcell"><span>RS加速</span><b>${val(s.acceleration)}</b></div>
        <div class="detailcell"><span>Supply</span><b>${pct(st.supply_distance_pct,'+')}</b></div>
        <div class="detailcell"><span>Demand</span><b>${pct(st.demand_distance_pct,'−')}</b></div>
        <div class="detailcell"><span>構造</span><b>${val(st.score,' / 100')} · ${h(st.label||'')}</b></div>
        <div class="detailcell"><span>RVOL</span><b>${val(s.volume_ratio,'x')}</b></div>
        <div class="detailcell"><span>52週高値差</span><b>${pct(s.near_high,'')}</b></div>
        <div class="detailcell"><span>発火状態</span><b>${h(boNames[(s.breakout||{}).status]||(s.breakout||{}).status||'—')}</b></div>
      </div>
      <div class="detailwhy">${h(reason)}${s.eps_label?`<br>EPS：${h(s.eps_label)}`:''}</div>
      <a class="tvbtn" href="${tvUrl(s)}" target="_blank" rel="noopener noreferrer">TradingViewで開く ↗</a>
    </div>`;
  }
  function toggle(row,symbol){
    if(!row||!symbol)return;
    const current=row.querySelector(':scope > .tapdetail');
    if(current){current.remove();return;}
    document.querySelectorAll('.tapdetail').forEach(x=>x.remove());
    const found=findStock(symbol);
    if(!found)return;
    row.insertAdjacentHTML('beforeend',detailHtml(found.stock,found.group));
  }
  document.addEventListener('click',ev=>{
    if(ev.target.closest('a.tvbtn'))return;
    if(ev.target.closest('summary,details'))return;
    const row=ev.target.closest('.pickrow,.stockrow');
    if(!row)return;
    const symbol=row.querySelector('.ticker,.stockname b')?.textContent?.trim();
    toggle(row,symbol);
  });
})();
</script>
'''
    return page.replace("</body>", script + "\n</body>", 1)


def _build_public_model(model: dict[str, Any], exchange_map: dict[str, str] | None = None) -> dict[str, Any]:
    with_exchange = _attach_exchange(model, exchange_map)
    structured = apply_structure_overlay(with_exchange)
    enriched = apply_prebreakout_overlay(structured)
    return _polish_model(enriched)


def render_public_html(model: dict, exchange_map: dict[str, str] | None = None) -> str:
    enriched = _build_public_model(model, exchange_map)
    return _interactive_shell(_prebreakout_copy(render_html(enriched)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render V38-style Leadership with polished pre-breakout labels and stock drilldown")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    enriched = _build_public_model(model, _load_exchange_map(args.universe))
    args.model.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_interactive_shell(_prebreakout_copy(render_html(enriched))), encoding="utf-8")


if __name__ == "__main__":
    main()

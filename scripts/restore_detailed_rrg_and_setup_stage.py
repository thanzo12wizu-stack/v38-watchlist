from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "build_dashboard.py"
s = p.read_text(encoding="utf-8")

# 1) Restore the detailed-sector drilldown on the theme-ETF RRG.
# Historical implementation passed etf_hier as sub_data; a later refactor
# replaced it with None, leaving the UI copy promising a drilldown that no
# longer existed.
old_rrg = '_rrg_card(mkt.get("rrg_etf"), None, None, 100, "テーマETFの温度計（重複あり）", _RRG_ETF_DESC)'
new_rrg = '_rrg_card(mkt.get("rrg_etf"), None, mkt.get("etf_hier"), 100, "テーマETFの温度計（重複あり）", _RRG_ETF_DESC)'
if s.count(old_rrg) != 1:
    raise SystemExit(f"RRG anchor mismatch: expected 1, found {s.count(old_rrg)}")
s = s.replace(old_rrg, new_rrg, 1)

# 2) Add display-only Weinstein stage badges to every ticker-bearing element in
# the Setups tab. This intentionally does NOT change selection/filter/ranking.
js_anchor = 'JS = r"""\nfunction escHtml(v){'
if s.count(js_anchor) != 1:
    raise SystemExit(f"JS anchor mismatch: expected 1, found {s.count(js_anchor)}")

stage_js = r'''JS = r"""
/* SETUP_STAGE_BADGE_V1: display only; no setup eligibility/ranking changes. */
function setupStageBadges(){
  try{
    if(!document.getElementById('setupStageBadgeStyle')){
      var st=document.createElement('style'); st.id='setupStageBadgeStyle';
      st.textContent='.setup-stage-badge{display:inline-flex;align-items:center;justify-content:center;margin-left:5px;padding:1px 5px;border-radius:999px;font-size:9px;font-weight:800;line-height:1.45;vertical-align:1px;white-space:nowrap;border:1px solid currentColor}.setup-stage-badge.s1{color:#60a5fa;background:rgba(96,165,250,.10)}.setup-stage-badge.s2{color:#4ade80;background:rgba(74,222,128,.10)}.setup-stage-badge.s3{color:#fbbf24;background:rgba(251,191,36,.10)}.setup-stage-badge.s4{color:#f87171;background:rgba(248,113,113,.10)}.setup-stage-badge.s0{color:#94a3b8;background:rgba(148,163,184,.08)}';
      document.head.appendChild(st);
    }
    var names={1:'ステージ1：底固め・移行期',2:'ステージ2：上昇トレンド',3:'ステージ3：天井圏',4:'ステージ4：下降トレンド'};
    document.querySelectorAll('#t-today [data-tkone]').forEach(function(el){
      if(el.getAttribute('data-stage-decorated')==='1') return;
      var tk=(el.getAttribute('data-tkone')||'').toUpperCase();
      var d=(window.DET||{})[tk]||{}; var n=Number(d.wst); var ok=(n>=1&&n<=4);
      var tgt=(el.matches&&el.matches('.tk,.pretk,.tbtk,.cft'))?el:el.querySelector('.tk,.pretk,.tbtk,.cft');
      if(!tgt) tgt=el.querySelector('b')||el.firstElementChild||el;
      if(!tgt) return;
      var b=document.createElement('span'); b.className='setup-stage-badge '+(ok?('s'+n):'s0');
      b.textContent=ok?('S'+n):'S—'; b.title=ok?names[n]:'ステージ判定データなし';
      tgt.appendChild(b); el.setAttribute('data-stage-decorated','1');
    });
  }catch(e){}
}
if(document.readyState!=='loading'){setupStageBadges();}
else{document.addEventListener('DOMContentLoaded',setupStageBadges);}
function escHtml(v){'''

s = s.replace(js_anchor, stage_js, 1)

# Regression guards for recently-fixed behavior and the restored industry hierarchy.
required = [
    'INCEPTION_VWAP_BYPASS_PRESENTATION_CAP_V1',
    'mkt["etf_hier"] = _scard("etf_hier", build_etf_hier, m, s2t, ind_map=_indmap)',
    'window.HIER=',
    'wst=wsx.get("wst")',
    'SETUP_STAGE_BADGE_V1',
    new_rrg,
]
for needle in required:
    if needle not in s:
        raise SystemExit(f"required invariant missing: {needle}")

opt = (ROOT / "tools" / "build_options_positioning.py").read_text(encoding="utf-8")
for needle in [
    'sub = sub[sub.index > spot] if kind == "C" else sub[sub.index < spot]',
    'cw = top_walls(g, "C", spot=spot); pw = top_walls(g, "P", spot=spot)',
]:
    if needle not in opt:
        raise SystemExit(f"option direction regression guard failed: {needle}")

ind = ROOT / "industry_map.json"
if not ind.exists() or ind.stat().st_size < 1000:
    raise SystemExit("industry_map.json missing or unexpectedly small")

p.write_text(s, encoding="utf-8")
print("RESTORED_DETAILED_SECTOR_RRG=1")
print("ADDED_SETUP_STAGE_BADGES=1")
print("PRESERVED_INCEPTION_VWAP_FIX=1")
print("PRESERVED_DIRECTIONAL_OPTION_WALLS=1")

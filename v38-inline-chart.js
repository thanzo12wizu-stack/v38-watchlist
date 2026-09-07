(() => {
'use strict';

const PRIMARY='./v38_chart_data', ROT='./rotation/data/stock-chart', OPT='./options_chart_data.json';
const shards=new Map();
let optPromise=null, deps=null, activeChart=null, activeSlot=null, activeTicker=null, scheduled=false;

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bucket=t=>/^[A-Z]$/.test(String(t||'').trim().toUpperCase()[0]||'')?String(t).trim().toUpperCase()[0]:'OTHER';

function addCss(){
  if(![...document.styleSheets].some(s=>String(s.href||'').includes('options-chart.css'))){
    const l=document.createElement('link');l.rel='stylesheet';l.href='./options-chart.css?v=20260907-v38inline2';document.head.appendChild(l);
  }
  if(document.getElementById('v38InlineChartStyle'))return;
  const s=document.createElement('style');s.id='v38InlineChartStyle';s.textContent=`
[data-v38-chart-symbol]{cursor:pointer}.pick[data-v38-chart-symbol]{transition:transform .15s ease}.pick[data-v38-chart-symbol]:active{transform:scale(.995)}
.pick[data-v38-chart-symbol]::after{content:"チャート";position:absolute;right:10px;top:10px;font-size:9px;font-weight:800;color:#9ecbff;border:1px solid rgba(158,203,255,.22);background:rgba(22,36,62,.8);border-radius:999px;padding:3px 6px}
td[data-v38-chart-symbol] b,.poshead [data-v38-chart-symbol]{text-decoration:underline;text-decoration-color:rgba(140,183,255,.45);text-underline-offset:3px}
.v38InlineChartRow td{padding:0!important;border-bottom:1px solid #20334a}.v38InlineChartSlot{grid-column:1/-1;min-width:0;width:100%}
.v38InlineChartClose{appearance:none;border:1px solid rgba(255,255,255,.12);background:#172334;color:#d8e6f8;border-radius:999px;padding:6px 10px;font-size:11px;font-weight:800;cursor:pointer}
.v38InlineChartHint{font-size:10px;color:#89919d}.v38InlineChartMissing{padding:26px 16px;text-align:center;color:#9caec4;font-size:12px;line-height:1.6}
@media(max-width:680px){.pick[data-v38-chart-symbol]::after{right:8px;top:8px}.v38InlineChartClose{padding:6px 9px}}`;document.head.appendChild(s);
}

function loadScript(src,test){
  if(test?.())return Promise.resolve();
  const needle=src.replace(/^\.\//,'').split('?')[0];
  return new Promise((resolve,reject)=>{
    const old=[...document.scripts].find(s=>String(s.src||'').includes(needle));
    if(old){
      const started=Date.now(), timer=setInterval(()=>{if(test?.()){clearInterval(timer);resolve()}else if(Date.now()-started>8000){clearInterval(timer);reject(new Error(`script not ready: ${needle}`))}},40);
      return;
    }
    const s=document.createElement('script');s.src=src;s.onload=resolve;s.onerror=()=>reject(new Error(`script load failed: ${src}`));document.body.appendChild(s);
  });
}

function ensureDeps(){
  if(deps)return deps;addCss();
  deps=(async()=>{
    await loadScript('https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js',()=>!!window.LightweightCharts);
    await loadScript('./options-chart.js?v=20260907-v38inline2',()=>!!window.V38Chart?.mount);
  })();
  return deps;
}

async function json(url){const r=await fetch(`${url}${url.includes('?')?'&':'?'}v=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(`${url}:${r.status}`);return r.json()}

async function shardRecord(ticker){
  const key=bucket(ticker);
  if(!shards.has(key))shards.set(key,(async()=>{
    try{return{a:await json(`${PRIMARY}/${key}.json`),b:null}}catch(_){}
    try{return{a:null,b:await json(`${ROT}/${key}.json`)}}catch(_){return{a:null,b:null}}
  })());
  const p=await shards.get(key);return p.a?.tickers?.[ticker]||p.b?.tickers?.[ticker]||null;
}

async function record(ticker){
  const r=await shardRecord(ticker);if(r?.bars?.length)return r;
  if(!optPromise)optPromise=json(OPT).catch(()=>({tickers:{}}));
  const o=await optPromise;return o?.tickers?.[ticker]?.bars?.length?o.tickers[ticker]:null;
}

function mark(el,ticker){
  if(!el||!ticker)return;el.dataset.v38ChartSymbol=String(ticker).trim().toUpperCase();el.setAttribute('role',el.getAttribute('role')||'button');
  if(!el.hasAttribute('tabindex'))el.tabIndex=0;el.setAttribute('aria-label',`${ticker} のチャートを開く`);
}
function cellTicker(row,i){const m=row?.cells?.[i]?.textContent?.trim()?.toUpperCase()?.match(/[A-Z][A-Z0-9.-]{0,9}/);return m?.[0]||null}

function annotate(){
  scheduled=false;
  document.querySelectorAll('.pick').forEach(x=>{const t=x.querySelector('.ticker')?.textContent?.trim()?.toUpperCase();if(t)mark(x,t)});
  for(const [sel,i] of [['#candidateRows tr',1],['#resetHoldingRows tr',0],['#resetSignalRows tr',0],['#resetWatchRows tr',1]]){
    document.querySelectorAll(sel).forEach(row=>{const t=cellTicker(row,i),c=row.cells?.[i];if(t&&c)mark(c,t)});
  }
  document.querySelectorAll('#positionList .pos').forEach(p=>{const e=p.querySelector('.poshead b:first-child'),t=e?.textContent?.trim()?.toUpperCase();if(t)mark(e,t)});
}
function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(annotate)}

function closeChart(){
  if(activeChart){try{activeChart.destroy()}catch(_){}activeChart=null}
  const row=activeSlot?.closest?.('tr.v38InlineChartRow');
  if(row)row.remove();else activeSlot?.remove();
  activeSlot=null;activeTicker=null;
}

function makeSlot(trigger){
  const row=trigger.closest('tr');
  if(row){
    const wrap=document.createElement('tr');wrap.className='v38InlineChartRow';
    const td=document.createElement('td');td.colSpan=Math.max(1,row.cells?.length||1);
    const slot=document.createElement('div');slot.className='v38InlineChartSlot';td.appendChild(slot);wrap.appendChild(td);row.insertAdjacentElement('afterend',wrap);return slot;
  }
  const pick=trigger.closest('.pick'), slot=document.createElement('div');slot.className='v38InlineChartSlot';
  if(pick){const grid=pick.closest('.picks');(grid||pick).insertAdjacentElement('afterend',slot);return slot}
  const pos=trigger.closest('.pos');(pos||trigger).insertAdjacentElement('afterend',slot);return slot;
}

function head(ticker,sub,extra=''){return `<div class="v38ChartHead"><div class="v38ChartHeadLeft"><span class="v38ChartEyebrow">PRICE CHART</span><div class="v38ChartTitle"><b>${esc(ticker)}</b><span>${esc(sub)}</span></div></div><div class="v38ChartStatus">${extra}<button type="button" class="v38InlineChartClose">閉じる</button></div></div>`}
function loading(t){return `<section class="v38ChartPanel">${head(t,'日足を準備中')}<div class="v38ChartCanvas"><div class="v38ChartPending"><b>チャートを読み込み中</b>V38用の価格履歴を取得しています。</div></div></section>`}
function missing(t){return `<section class="v38ChartPanel">${head(t,'価格履歴なし')}<div class="v38InlineChartMissing">この銘柄のV38チャート履歴がまだ生成されていません。次回チャート更新時に自動取得対象になります。</div></section>`}
function panel(t,r){
  const d=r?.history_session_date||r?.bars?.at?.(-1)?.time||'—', status=r?.stale?'<span class="warn">前回値を表示</span>':'<span>価格履歴 OK</span>';
  return `<section class="v38ChartPanel" data-chart-ticker="${esc(t)}">${head(t,'日足 1年',`<span>最終足 ${esc(d)}</span>${status}`)}
<div class="v38ChartLegend"><span class="tech ema"><b>21EMA</b></span><span class="tech sma150"><b>150SMA</b></span><span class="tech vwap"><b>63VWAP</b></span><span><b>NQSAR背景</b></span></div>
<div class="v38ChartCanvas" data-v38-inline-canvas></div><div class="v38ChartFoot"><span>表示専用。V38順位・Market Mode・売買ルールには使用しません。</span><span class="v38InlineChartHint">ドラッグ / ピンチ / ホイールで拡大縮小</span></div></section>`;
}
function wireClose(){activeSlot?.querySelector('.v38InlineChartClose')?.addEventListener('click',closeChart,{once:true})}

async function openChart(trigger,ticker){
  if(activeTicker===ticker&&activeSlot?.isConnected){closeChart();return}
  closeChart();activeTicker=ticker;activeSlot=makeSlot(trigger);activeSlot.innerHTML=loading(ticker);wireClose();
  const token=ticker;
  try{
    await ensureDeps();const r=await record(ticker);
    if(activeTicker!==token||!activeSlot?.isConnected)return;
    if(!r?.bars?.length){activeSlot.innerHTML=missing(ticker);wireClose();return}
    activeSlot.innerHTML=panel(ticker,r);wireClose();
    activeChart=window.V38Chart.mount({element:activeSlot.querySelector('[data-v38-inline-canvas]'),bars:r.bars||[],ticker,levels:{},wallHistory:[],stale:!!r.stale});
  }catch(e){console.error('V38_INLINE_CHART',e);if(activeTicker===token&&activeSlot?.isConnected){activeSlot.innerHTML=missing(ticker);wireClose()}}
}

function activate(trigger){const t=String(trigger?.dataset?.v38ChartSymbol||'').trim().toUpperCase();if(t)openChart(trigger,t)}
function click(e){
  const x=e.target.closest?.('[data-v38-chart-symbol]');if(!x)return;
  const a=e.target.closest('a');if(a&&/tradingview\.com\/chart/i.test(a.href||'')){e.preventDefault();e.stopPropagation()}
  activate(x);
}
function key(e){if(!['Enter',' '].includes(e.key))return;const x=e.target.closest?.('[data-v38-chart-symbol]');if(!x)return;e.preventDefault();activate(x)}

function boot(){
  addCss();schedule();new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
  document.addEventListener('click',click,true);document.addEventListener('keydown',key,true);window.addEventListener('beforeunload',closeChart);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
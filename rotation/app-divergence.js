'use strict';

(() => {
  const rootUrl = new URL('.', window.location.href);
  const diagnosticsUrl = new URL('data/rotation-theme56-divergence.json', rootUrl).href;
  const dataUrl = new URL('data/rotation-theme56.json', rootUrl).href;
  const statusUrl = new URL('data/status.json', rootUrl).href;

  const esc = value => String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]);
  const finite = value => value !== null && value !== '' && Number.isFinite(Number(value));
  const fmt = (value, digits=1) => finite(value) ? Number(value).toFixed(digits) : '—';
  const pct = (value, digits=1) => finite(value) ? `${Number(value)>0?'+':''}${Number(value).toFixed(digits)}%` : '—';

  async function getJson(url) {
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw new Error(`${url} HTTP ${response.status}`);
    return response.json();
  }

  function allRows(data) {
    return Object.values(data?.observations?.rotation_buckets || {}).flat().filter(row => row && row.ticker);
  }

  function ensureStyles() {
    if (document.getElementById('rotationDivergenceStyles')) return;
    const style=document.createElement('style');
    style.id='rotationDivergenceStyles';
    style.textContent=`
      .divergence-card{border-color:#263545;background:linear-gradient(180deg,rgba(17,25,34,.98),rgba(13,19,26,.98))}
      .divergence-intro{font-size:10px;color:var(--muted);max-width:850px;line-height:1.55}
      .divergence-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:11px}
      .divergence-panel{border:1px solid var(--line2);border-radius:11px;background:rgba(4,8,12,.24);padding:11px;min-width:0}
      .divergence-panel-title{font-size:11px;font-weight:820;margin-bottom:4px}
      .divergence-panel-sub{font-size:9px;color:var(--faint);margin-bottom:5px;line-height:1.45}
      .divergence-list{display:grid;gap:7px}
      .divergence-item{border-top:1px solid var(--line2);padding-top:8px;min-width:0}
      .divergence-item:first-child{border-top:0;padding-top:3px}
      .divergence-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
      .divergence-name{font-size:12px;font-weight:820;min-width:0}
      .divergence-score{font-size:9px;color:var(--faint);white-space:nowrap}
      .divergence-badges{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0}
      .cause-pill,.early-pill{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:2px 6px;font-size:9px;font-weight:800;line-height:1.4}
      .cause-pill.top{color:var(--orange);border-color:rgba(231,154,98,.42);background:rgba(231,154,98,.055)}
      .cause-pill.warn{color:var(--amber);border-color:rgba(228,185,103,.4);background:rgba(228,185,103,.055)}
      .cause-pill.good{color:var(--green);border-color:rgba(119,212,158,.36);background:rgba(119,212,158,.05)}
      .cause-pill.bad{color:var(--red);border-color:rgba(223,123,123,.38);background:rgba(223,123,123,.055)}
      .cause-pill.neutral{color:var(--muted)}
      .early-pill{color:var(--accent);border-color:rgba(143,205,242,.34);background:rgba(143,205,242,.045)}
      .divergence-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin-top:5px}
      .divergence-metric{border:1px solid var(--line2);border-radius:7px;padding:5px 6px;min-width:0}
      .divergence-metric span{display:block;font-size:8px;color:var(--faint)}
      .divergence-metric b{display:block;font-size:10px;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .driver-line{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
      .driver-chip{font-size:8px;color:var(--muted);border:1px solid var(--line2);border-radius:6px;padding:2px 5px}
      .theme-diagnostic-line{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin:3px 0 2px}
      .theme-diagnostic-line small{font-size:8px;color:var(--faint)}
      .divergence-method{margin-top:9px;font-size:9px;color:var(--faint);line-height:1.5}
      @media(max-width:760px){.divergence-columns{grid-template-columns:1fr}.divergence-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function causeTone(key) {
    if (['TOP_WEIGHT_LED_NARROW','STRONG_TOP_HEAVY'].includes(key)) return 'top';
    if (['PRICE_LEAD_NARROW','PRICE_HOLD_INTERNAL_ROLLOVER','STRONG_ROLLING_OVER','MIXED_ROLLOVER'].includes(key)) return 'warn';
    if (['BROAD_INTERNAL_IGNITION','INTERNAL_LEAD','BROAD_STRENGTH','WEAK_EARLY_RECOVERY','MIXED_EARLY'].includes(key)) return 'good';
    if (['BROAD_WEAK'].includes(key)) return 'bad';
    return 'neutral';
  }

  function earlyPriority(key) {
    return ({IGNITION_5D:0,EXPANSION_10D:1,SHORT_LEAD:2,BUILDING:3,WEAK_EARLY_RECOVERY:4,CONFIRMED_20D:8,ROLLING_OVER_5D:9,ROLLING_OVER_10D:10})[key] ?? 7;
  }

  function causePriority(key) {
    return ({TOP_WEIGHT_LED_NARROW:0,PRICE_HOLD_INTERNAL_ROLLOVER:1,PRICE_LEAD_NARROW:2,STRONG_TOP_HEAVY:3,STRONG_ROLLING_OVER:4,BROAD_INTERNAL_IGNITION:5,INTERNAL_LEAD:6,WEAK_EARLY_RECOVERY:7,MIXED_EARLY:8,MIXED_ROLLOVER:9})[key] ?? 20;
  }

  function horizon(diag, h) { return diag?.horizons?.[String(h)] || {}; }

  function drivers(diag) {
    const top=diag?.concentration?.top_holdings || [];
    return top.slice(0,5).map(x => `<span class="driver-chip">${esc(x.symbol)} ${finite(x.weight_pct)?fmt(x.weight_pct,1)+'%':'—'} / 5D ${pct(x.ret_5d_pct,1)}</span>`).join('');
  }

  function itemMarkup(diag,row,kind) {
    const h5=horizon(diag,5),h10=horizon(diag,10),h20=horizon(diag,20);
    const conc=diag.concentration || {},cause=diag.divergence_cause || {},early=diag.early_phase || {};
    const top5=finite(conc.top5_weight_pct)?`${fmt(conc.top5_weight_pct,1)}%`:'—';
    const move=finite(h5.top5_abs_move_share_pct)?`${fmt(h5.top5_abs_move_share_pct,0)}%`:'—';
    const confidence=cause.confidence && cause.confidence!=='LOW'?`確度 ${cause.confidence}`:'';
    return `<div class="divergence-item">
      <div class="divergence-head"><div class="divergence-name">${esc(row?.ticker||diag.ticker)}${row?.label?`｜${esc(row.label)}`:''}</div><div class="divergence-score">価格 ${fmt(row?.price_score,0)} / 構成 ${fmt(row?.internal_score,0)}</div></div>
      <div class="divergence-badges"><span class="cause-pill ${causeTone(cause.key)}">${esc(cause.label||'原因未分類')}</span><span class="early-pill">${esc(early.label||'短期未取得')}</span>${confidence?`<span class="cause-pill neutral">${esc(confidence)}</span>`:''}</div>
      <div class="divergence-metrics">
        <div class="divergence-metric"><span>上位5構成比</span><b>${esc(top5)}</b></div>
        <div class="divergence-metric"><span>5D 上昇銘柄率</span><b>${pct(h5.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>10D 上昇銘柄率</span><b>${pct(h10.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>20D 上昇銘柄率</span><b>${pct(h20.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>5D 中央値</span><b>${pct(h5.median_return_pct,1)}</b></div>
        <div class="divergence-metric"><span>10D 中央値</span><b>${pct(h10.median_return_pct,1)}</b></div>
        <div class="divergence-metric"><span>上位5 値動き集中</span><b>${esc(move)}</b></div>
        <div class="divergence-metric"><span>実効銘柄数</span><b>${finite(conc.effective_holdings)?fmt(conc.effective_holdings,1):'—'}</b></div>
      </div>
      ${drivers(diag)?`<div class="driver-line">${drivers(diag)}</div>`:''}
    </div>`;
  }

  function ensureSection() {
    let section=document.getElementById('divergenceAnalysisCard');
    if (section) return section;
    const anchor=document.querySelector('.change-card');
    if (!anchor) return null;
    section=document.createElement('div');
    section.id='divergenceAnalysisCard';
    section.className='card s12 divergence-card';
    section.innerHTML=`<div class="section-head"><div><div class="eyebrow">DIVERGENCE / EARLY MOTION</div><h2>チグハグの原因・20日前の初動</h2><div class="divergence-intro">ETF価格と構成株がズレる理由を、ETF構成比・上位銘柄への値動き集中・5日/10日/20日の構成株の広がりで分解します。大型株かどうかを推測するのではなく、ETF価格への影響を直接表す「構成比」を優先します。</div></div></div><div class="divergence-columns"><div class="divergence-panel"><div class="divergence-panel-title good">5日 / 10日で先に動いている</div><div class="divergence-panel-sub">20日で強くなる前の広がりを表示。売買シグナルではありません。</div><div id="earlyMotionList" class="divergence-list"></div></div><div class="divergence-panel"><div class="divergence-panel-title watch">ETFと構成株のズレを分解</div><div class="divergence-panel-sub">上位構成銘柄主導、広がり不足、内部先行、直近失速などを分類。</div><div id="divergenceCauseList" class="divergence-list"></div></div></div><div class="divergence-method">「上位構成銘柄主導」は時価総額の推測ではなくETFウェイトと値動き寄与で判定。構成比データが十分でないテーマでは断定せず、原因混合/未確定として扱います。</div>`;
    anchor.insertAdjacentElement('afterend',section);
    return section;
  }

  function annotateThemeRows(diagByTicker) {
    document.querySelectorAll('#themeList .theme-row[data-ticker]').forEach(node => {
      const ticker=String(node.dataset.ticker||'').toUpperCase();
      const diag=diagByTicker.get(ticker);
      if (!diag || diag.status!=='READY') return;
      const state=node.querySelector('.theme-state');
      if (!state) return;
      let line=state.querySelector('.theme-diagnostic-line');
      if (!line) {
        line=document.createElement('div');
        line.className='theme-diagnostic-line';
        const trajectory=state.querySelector('.trajectory-line');
        if (trajectory) trajectory.insertAdjacentElement('afterend',line); else state.appendChild(line);
      }
      const cause=diag.divergence_cause||{},early=diag.early_phase||{};
      line.innerHTML=`<span class="cause-pill ${causeTone(cause.key)}">${esc(cause.label||'原因未分類')}</span><span class="early-pill">${esc(early.label||'短期未取得')}</span>`;
    });
  }

  function renderSection(diags,rowsByTicker) {
    const section=ensureSection();
    if (!section) return false;
    const ready=diags.filter(x=>x&&x.status==='READY');
    const early=ready.filter(x=>['IGNITION_5D','EXPANSION_10D','SHORT_LEAD','BUILDING'].includes(x.early_phase?.key))
      .sort((a,b)=>earlyPriority(a.early_phase?.key)-earlyPriority(b.early_phase?.key) || Number(horizon(b,5).positive_breadth_pct||0)-Number(horizon(a,5).positive_breadth_pct||0)).slice(0,7);
    const mismatch=ready.filter(x=>causePriority(x.divergence_cause?.key)<20)
      .sort((a,b)=>causePriority(a.divergence_cause?.key)-causePriority(b.divergence_cause?.key) || Math.abs(Number(rowsByTicker.get(String(b.ticker).toUpperCase())?.price_score||0)-Number(rowsByTicker.get(String(b.ticker).toUpperCase())?.internal_score||0))-Math.abs(Number(rowsByTicker.get(String(a.ticker).toUpperCase())?.price_score||0)-Number(rowsByTicker.get(String(a.ticker).toUpperCase())?.internal_score||0))).slice(0,7);
    const earlyHost=document.getElementById('earlyMotionList');
    const causeHost=document.getElementById('divergenceCauseList');
    if (earlyHost) earlyHost.innerHTML=early.length?early.map(x=>itemMarkup(x,rowsByTicker.get(String(x.ticker).toUpperCase()),'early')).join(''):'<div class="sub">5日/10日で明確に先行するテーマなし</div>';
    if (causeHost) causeHost.innerHTML=mismatch.length?mismatch.map(x=>itemMarkup(x,rowsByTicker.get(String(x.ticker).toUpperCase()),'cause')).join(''):'<div class="sub">大きなチグハグは限定的</div>';
    return true;
  }

  async function enhance() {
    const [diag,data,status]=await Promise.all([getJson(diagnosticsUrl),getJson(dataUrl),getJson(statusUrl)]);
    const asof=String(status.asof||'');
    if (diag.status!=='READY' || !asof || String(diag.asof||'')!==asof || String(data.asof||'')!==asof) return false;
    const rows=allRows(data);
    if (!rows.length || !document.querySelector('#themeList .theme-row')) return false;
    ensureStyles();
    const rowsByTicker=new Map(rows.map(x=>[String(x.ticker||'').toUpperCase(),x]));
    const diags=diag.themes||[];
    const diagByTicker=new Map(diags.map(x=>[String(x.ticker||'').toUpperCase(),x]));
    annotateThemeRows(diagByTicker);
    return renderSection(diags,rowsByTicker);
  }

  let attempts=0;
  const run=async()=>{
    attempts+=1;
    try { if (await enhance()) return; } catch (_) {}
    if (attempts<12) window.setTimeout(run,400);
  };
  window.setTimeout(run,350);
})();

'use strict';
(async function nativeUnifiedCommandCenter(){
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const isNum=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
  const num=v=>isNum(v)?Number(v):null;
  const fmt=(v,d=1)=>isNum(v)?Number(v).toFixed(d):'—';
  const pct=(v,d=1)=>isNum(v)?`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`:'—';
  const money=v=>{if(!isNum(v))return'—';const x=Number(v),sg=x>=0?'+':'−',a=Math.abs(x);if(a>=1e9)return`${sg}${(a/1e9).toFixed(2)}B`;if(a>=1e6)return`${sg}${Math.round(a/1e6)}M`;if(a>=1e3)return`${sg}${Math.round(a/1e3)}K`;return`${sg}${Math.round(a)}`};
  const toneClass=v=>Number(v)>0?'pos':Number(v)<0?'neg':'';
  const modeJa=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';
  const shortDate=s=>{const p=String(s||'').split('-');return p.length===3?`${p[0]}.${p[1]}.${p[2]}`:(s||'—')};
  const ETF={CIBR:'サイバー',IGV:'ソフトウェア',WCLD:'クラウド・SaaS',OIH:'油田サービス',DRAM:'メモリ',SKYY:'クラウド基盤',XES:'油田装置',AIQ:'AI',ARKW:'次世代ネット',BOTZ:'ロボティクス',SMH:'半導体',HYDR:'水素',XOP:'石油探査',MOO:'農業',SOXX:'半導体装置',DRIV:'EV・自動運転',XSD:'半導体EW',QTUM:'量子・次世代',SLX:'鉄鋼',BLOK:'ブロックチェーン',XME:'金属・鉱業',GRID:'スマートグリッド',IAI:'証券・取引所',URA:'ウラン',NLR:'原子力',DTCR:'データセンター',FAN:'風力',ICLN:'クリーンEN',SHLD:'防衛テック',LIT:'リチウム電池',WOOD:'林業',XBI:'バイオテック',GNOM:'ゲノム',PHO:'水関連',KBE:'銀行',TAN:'ソーラー',KRE:'地銀',IHI:'医療機器',KIE:'保険',COPX:'銅鉱',IYT:'運輸',ITA:'航空宇宙・防衛',PAVE:'インフラ',SIL:'銀鉱',IBUY:'EC',REMX:'レアアース',PPH:'製薬',PKB:'建設',BOAT:'海運',XRT:'小売',XHB:'住宅建設',XAR:'宇宙・防衛',WGMI:'BTCマイニング',JETS:'航空',GDX:'金鉱',PEJ:'レジャー'};
  const etfLabel=r=>`${r?.ticker||'—'}${(r?.label||ETF[r?.ticker])?`｜${r.label||ETF[r.ticker]}`:''}`;

  const wrap=q('.wrap')||document.body;
  const oldNav=q('nav',wrap);
  if(!oldNav)return;
  oldNav.style.display='none';
  oldNav.setAttribute('aria-hidden','true');
  const legacyToday=q('#taCard');
  if(legacyToday){legacyToday.style.display='none';legacyToday.setAttribute('aria-hidden','true')}

  const extraStyle=document.createElement('style');
  extraStyle.textContent=`
    #u-nav{display:flex!important}
    #u-nav button{cursor:pointer}
    .u-subnav{display:flex;gap:5px;overflow-x:auto;margin:0 0 10px;padding:0 0 7px;scrollbar-width:none}
    .u-subnav::-webkit-scrollbar{display:none}
    .u-subnav button{flex:0 0 auto;background:#ebeae5;color:#5a5850;border:1px solid #dfddd5;border-radius:14px;padding:6px 11px;font-size:11px;font-weight:700;cursor:pointer}
    .u-subnav button.on{background:#d8e4f5;color:#2c69c9;border-color:#9db9df}
    .u-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:7px 0 10px}
    .u-grid4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:8px 0 0}
    .u-metric{background:#f2f1ee;border:1px solid #e3e1db;border-radius:10px;padding:9px 10px;min-width:0}
    .u-metric .k{font-size:10px;color:#575242;font-weight:700}.u-metric .v{font-size:21px;font-weight:800;line-height:1.1;margin-top:2px;color:#1c1b19}.u-metric .n{font-size:9.5px;color:#575242;margin-top:3px;line-height:1.35}
    .u-call{border-radius:14px;padding:13px 15px;margin:0 0 12px;border:1px solid #e3e1db;background:linear-gradient(135deg,#ecebe7,#e5e4de)}
    .u-call .ey{font-size:10px;color:#575242;font-weight:800;letter-spacing:.04em}.u-call .main{font-size:22px;font-weight:800;line-height:1.2;margin:3px 0}.u-call .sub{font-size:11px;color:#565243;line-height:1.55}
    .u-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;padding:8px 2px;border-bottom:1px solid rgba(27,29,28,.06)}.u-row:last-child{border-bottom:0}.u-row .name{font-weight:800;color:#1c1b19;min-width:0}.u-row .meta{font-size:10.5px;color:#575242;line-height:1.4;min-width:0}.u-row .value{text-align:right;font-weight:800;white-space:nowrap}.u-row .value small{display:block;font-size:9px;color:#575242;font-weight:600}
    .u-pill{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:#e6e5df;border:1px solid #d6d4ca;color:#34322e}.u-pill.go{background:#dcecdc;color:#226738;border-color:#b8d4bd}.u-pill.warn{background:#efe5c9;color:#805f18;border-color:#d7c48b}.u-pill.bad{background:#f0d9d6;color:#8b302b;border-color:#deb6b1}.u-pill.info{background:#d8e4f5;color:#2c69c9;border-color:#9db9df}
    .u-alert{border:1px solid #d8c797;background:#f3ead2;color:#67511e;border-radius:11px;padding:9px 11px;margin:0 0 10px;font-size:10.5px;line-height:1.55}.u-alert.bad{border-color:#deb6b1;background:#f2dedb;color:#7d302b}.u-alert.info{border-color:#b9cce5;background:#e4edf8;color:#315a8b}
    .u-table-wrap{overflow-x:auto;margin-top:7px}.u-table th:first-child,.u-table td:first-child{text-align:left}.u-table td{vertical-align:middle}.u-table .tk{font-weight:800;color:#2c69c9}.u-table .mut{color:#77736a;font-size:10px}
    .u-empty{font-size:11px;color:#575242;padding:8px 0}
    .u-rot-top{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:7px 0 10px}.u-rot-col{background:#f2f1ee;border:1px solid #e3e1db;border-radius:10px;padding:8px}.u-rot-col h3{font-size:11px;margin:0 0 5px}.u-rot-line{padding:5px 0;border-top:1px solid rgba(27,29,28,.06);font-size:10.5px;line-height:1.35}.u-rot-line:first-of-type{border-top:0}.u-rot-line b{font-size:11.5px}.u-rot-line span.note{display:block;color:#575242;margin-top:1px}
    .u-map{width:100%;height:auto;display:block;margin-top:4px}.u-map text{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}
    .u-legend{display:flex;gap:9px;flex-wrap:wrap;font-size:9.5px;color:#575242;margin:5px 0}.u-legend i{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px}.u-legend .g{background:#5f9870}.u-legend .y{background:#ad8021}.u-legend .r{background:#b45a52}.u-legend .n{background:#8c887d}
    .u-model{border-left:3px solid #9c988d;padding-left:10px}.u-local{border-left:3px solid #3774d3;padding-left:10px}
    #u-detail .legacy-panel{display:none!important;padding-top:0!important}#u-detail .legacy-panel.u-on{display:block!important}
    #u-rotation .legacy-rotation{display:block!important;padding-top:0!important;margin-top:8px}
    @media(max-width:720px){.u-grid4{grid-template-columns:repeat(2,minmax(0,1fr))}.u-rot-top{grid-template-columns:1fr}}
    @media(max-width:520px){.u-grid{grid-template-columns:1fr}.u-grid4{grid-template-columns:repeat(2,minmax(0,1fr))}.u-metric .v{font-size:19px}}
  `;
  document.head.appendChild(extraStyle);

  const topSections=qa('section',wrap);
  const byId=Object.fromEntries(topSections.map(s=>[s.id,s]));
  const nav=document.createElement('nav');nav.id='u-nav';nav.setAttribute('aria-label','V38 unified tabs');
  const tabs=[['today','今日'],['market','市場'],['rotation','資金循環'],['stocks','銘柄'],['tqqq','TQQQ'],['manage','RSI / 保有'],['detail','詳細']];
  tabs.forEach(([id,label])=>{const b=document.createElement('button');b.type='button';b.dataset.u=id;b.textContent=label;nav.appendChild(b)});
  oldNav.parentNode.insertBefore(nav,oldNav.nextSibling);
  const mkSection=id=>{const s=document.createElement('section');s.id='u-'+id;nav.insertAdjacentElement('afterend',s);return s};
  const uToday=mkSection('today'),uRotation=mkSection('rotation'),uStocks=mkSection('stocks'),uTqqq=mkSection('tqqq'),uManage=mkSection('manage'),uDetail=mkSection('detail');
  const unifiedSections=[uToday,uRotation,uStocks,uTqqq,uManage,uDetail];

  const detailPanels=['t-today','t-movers','t-rs','t-weekly','t-alloc','t-port','t-post1','t-rules'];
  uDetail.innerHTML='<div class="u-subnav" id="u-detail-nav"></div><div id="u-detail-panels"></div>';
  const detailNav=q('#u-detail-nav'),detailHost=q('#u-detail-panels');
  const detailLabels={'t-today':'Setups','t-movers':'Movers','t-rs':'RS','t-weekly':'Weekly','t-alloc':'Positions詳細','t-port':'Core 12','t-post1':'Publish','t-rules':'Rules'};
  detailPanels.forEach((id,i)=>{const p=byId[id];if(!p)return;p.classList.remove('on');p.classList.add('legacy-panel');detailHost.appendChild(p);const b=document.createElement('button');b.type='button';b.dataset.panel=id;b.textContent=detailLabels[id]||id;b.classList.toggle('on',i===0);detailNav.appendChild(b)});
  const firstDetail=q('.legacy-panel',detailHost);if(firstDetail)firstDetail.classList.add('u-on');
  detailNav.addEventListener('click',e=>{const b=e.target.closest('button[data-panel]');if(!b)return;qa('button',detailNav).forEach(x=>x.classList.toggle('on',x===b));qa('.legacy-panel',detailHost).forEach(x=>x.classList.toggle('u-on',x.id===b.dataset.panel));window.scrollTo(0,nav.offsetTop)});
  if(byId['t-rotation']){byId['t-rotation'].classList.remove('on');byId['t-rotation'].classList.add('legacy-rotation')}

  function showRoute(route){
    unifiedSections.forEach(s=>s.classList.remove('on'));
    Object.values(byId).forEach(s=>s.classList.remove('on'));
    qa('#u-nav button').forEach(b=>b.classList.toggle('on',b.dataset.u===route));
    const target=route==='market'?byId['t-market']:q('#u-'+route);
    if(target)target.classList.add('on');
    const base=location.pathname+location.search;
    history.replaceState(null,'',route==='today'?base:`${base}#${route}`);
    window.scrollTo(0,nav.offsetTop);
  }
  nav.addEventListener('click',e=>{const b=e.target.closest('button[data-u]');if(b)showRoute(b.dataset.u)});

  function card(title,sub,body,cls=''){return `<div class="card ${cls}"><h2>${title}</h2>${sub?`<div class="sub">${sub}</div>`:''}${body}</div>`}
  function row(name,meta,value,small=''){return `<div class="u-row"><div><div class="name">${name}</div><div class="meta">${meta||''}</div></div><div class="value">${value}${small?`<small>${small}</small>`:''}</div></div>`}
  function v38Health(v){
    const g=v?.gross100_allocation||{},st=String(g.sleeve_refresh_status||''),stale=st.includes('LAST_READY_PRESERVED')||String(v?.source||'').includes('Sleeve更新失敗');
    return{stale,status:st||'—',last:g.sleeve_last_successful_asof||v?.asof||'—',error:g.sleeve_refresh_error||g.sleeve_live_reason||''};
  }
  function healthBanner(v){const h=v38Health(v);return h.stale?`<div class="u-alert"><b>モデルSleeve更新警告：</b> 通常株/RSI Resetのモデル追跡は前回READYを継続（最終 ${esc(h.last)}）。市場判定やTQQQとは別系統です。モデル配分・モデル保有を実保有として扱わないでください。${h.error?`<br><span>${esc(h.error)}</span>`:''}</div>`:''}
  function loadLocalHoldings(){
    try{if(typeof window.hldLoad==='function'){const a=window.hldLoad();if(Array.isArray(a))return a.filter(x=>x&&x.status!=='closed'&&(x.t||x.ticker))}}
    catch(_){ }
    try{const a=JSON.parse(localStorage.getItem('v38_holdings')||'[]');return Array.isArray(a)?a.filter(x=>x&&x.status!=='closed'&&(x.t||x.ticker)):[]}catch(_){return[]}
  }
  function loadAuditMemo(){try{const a=JSON.parse(localStorage.getItem('v38_audited_positions_v1')||'[]');return Array.isArray(a)?a:[]}catch(_){return[]}}
  function stratLabel(s){return({core:'Core 12',lev:'レバETF',swing:'裁量'})[s]||s||'未分類'}
  function localHoldingRows(){
    return loadLocalHoldings().map(h=>{const t=String(h.t||h.ticker||'').toUpperCase(),entry=num(h.entryAvg??h.avgPx??h.px),shares=num(h.remainingShares??h.filledSharesTotal??h.sh);return `<tr><td class="tk">${esc(t)}</td><td>${esc(stratLabel(h.strat))}</td><td>${esc(h.dt||'—')}</td><td>${entry===null?'—':fmt(entry,2)}</td><td>${shares===null?'—':fmt(shares,4)}</td><td>${esc(h.status||'open')}</td></tr>`}).join('')
  }

  function markLegacyMarket(v){
    const m=byId['t-market'];if(!m||q('.u-market-note',m))return;
    const n=document.createElement('div');n.className='u-alert info u-market-note';
    n.innerHTML=`<b>このタブは既存Command Centerの市場観測。</b> 通常個別株の売買許可は統合版「今日」のV38 Market Mode（${esc(modeJa(v?.market?.mode))}）を正本とします。`;
    m.insertBefore(n,m.firstChild);
  }

  function renderToday(v){
    const m=v.market||{},nrm=v.normal_tqqq||{},p=v.panic_tqqq||{},r=v.panic_reset||{},g=v.gross100_allocation||{};
    const mode=String(m.mode||'').toUpperCase(),signals=(r.monitor||[]).filter(x=>x.status==='SIGNAL_TODAY_NEXT_OPEN');
    const action=mode==='ATTACK'?`通常個別株 新規可（上限${m.new_entry_limit??12}枠）`:mode==='SELECTIVE'?`通常個別株 選別新規（上限${m.new_entry_limit??4}枠）`:mode==='DEFENSE'?'通常個別株 次回寄り退避':'通常個別株 新規0';
    const tqTarget=p.active?(p.requested_target_pct??nrm.underlying_target_pct):nrm.underlying_target_pct;
    const localCount=loadLocalHoldings().length;
    const modelReady=String(g.status||'').includes('LIVE ALLOCATION READY');
    uToday.innerHTML=healthBanner(v)+`<div class="u-call"><div class="ey">TODAY · V38 ${esc(v.asof||'—')}</div><div class="main">${esc(action)}</div><div class="sub">NQSAR ${esc(m.nqsar||'—')} / Breadth50 ${fmt(m.breadth50,1)}% / TQQQは別エンジン</div><div class="u-grid4"><div class="u-metric"><div class="k">Market Mode</div><div class="v">${esc(modeJa(mode))}</div></div><div class="u-metric"><div class="k">通常株 新規上限</div><div class="v">${m.new_entry_limit??'—'}</div><div class="n">現在の許可枠。実保有数とは別。</div></div><div class="u-metric"><div class="k">TQQQ 戦略目標</div><div class="v">${fmt(tqTarget,0)}%</div><div class="n">実口座保有率ではない</div></div><div class="u-metric"><div class="k">Reset 正式Signal</div><div class="v">${signals.length}</div><div class="n">翌寄りEntry対象</div></div></div></div>`+
      card('今日の確認順','WHEN → WHERE → WHAT。Rotationは正式順位や買付許可へ加点しません。',`${row('① WHEN｜市場','NQSAR + Breadth',`${esc(modeJa(mode))} / 新規上限 ${m.new_entry_limit??'—'}`)}${row('② WHERE｜資金循環','Theme56 Price / Internal / ETF純資金','資金循環タブ')}${row('③ WHAT｜銘柄','ATTACK / SELECTIVEの正式V38順位','銘柄タブ')}${row('この端末の保有記録','Command Centerの手入力ローカル記録。証券口座自動連携ではありません。',`${localCount}件`,'RSI / 保有で確認')}`)+
      card('参考：モデル内部の配分','これは実保有でも「今ここまで買う」指示でもありません。戦略シミュレータ/Sleeveの内部状態です。',modelReady?`<div class="u-grid4"><div class="u-metric"><div class="k">通常株モデル</div><div class="v">${fmt(g.normal_stock_allocated_pct,0)}%</div></div><div class="u-metric"><div class="k">Resetモデル</div><div class="v">${fmt(g.reset_allocated_pct,1)}%</div></div><div class="u-metric"><div class="k">TQQQモデル</div><div class="v">${fmt(g.tqqq_allocated_pct,0)}%</div></div><div class="u-metric"><div class="k">モデル合計</div><div class="v">${fmt(g.gross_allocated_pct,0)}%</div></div></div>`:'<div class="u-empty">モデル配分はDATA REQUIRED。欠損を0%として扱いません。</div>','u-model');
  }

  function stockTable(rows,mode,kind){
    const rankKey=kind==='live'?'final_rank':kind==='selective'?'selective_watch_rank':'attack_watch_rank';
    const score=x=>kind==='live'&&mode==='ATTACK'?x.attack_score:kind==='live'&&mode==='SELECTIVE'?x.rs189:kind==='selective'?x.rs189:x.attack_watch_score;
    return `<div class="u-table-wrap"><table class="u-table"><thead><tr><th>順位</th><th>銘柄</th><th>Score</th><th>RS189</th><th>RS63</th><th>Theme</th><th>Theme強度</th><th>扱い</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${x[rankKey]??'—'}</td><td class="tk">${esc(x.ticker)}</td><td>${fmt(score(x),1)}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${fmt(x.peer_theme_score,1)}</td><td>${kind==='live'?'空き枠があれば翌寄り候補':'今は買わない'}</td></tr>`).join('')||'<tr><td colspan="8">候補なし</td></tr>'}</tbody></table></div>`
  }
  function renderStocks(v){
    const m=v.market||{},ranking=v.ranking||{},mode=String(m.mode||'').toUpperCase(),all=(v.candidates||[]).filter(x=>x.eligibility==='ELIGIBLE');
    if(mode==='ATTACK'||mode==='SELECTIVE'){
      const cap=mode==='ATTACK'?12:4,ready=mode==='SELECTIVE'||ranking.strict_loo_live_status==='READY';
      const live=all.filter(x=>num(x.final_rank)!==null).sort((a,b)=>Number(a.final_rank)-Number(b.final_rank));
      uStocks.innerHTML=card(mode==='ATTACK'?'ATTACK 正式V38順位':'SELECTIVE 正式V38順位',`${modeJa(mode)} / 新規保有可能総数 最大${cap}。${mode==='SELECTIVE'?'Themeは順位に加点しません。':'Stock70 + strict LOO Theme30。'}`,ready?stockTable(live.slice(0,cap),mode,'live'):'<div class="u-empty">正式順位に必要なデータが揃っていません。</div>')+
        card('Eligibility','Price≥$5 / DDV≥$10M / 50>200 / Close>200 / RS189・RS63≥85 / 構造的小型Clinical Biotech除外。',`<div class="u-empty">Eligibility通過 ${all.length}銘柄。上限は「必ず埋める目標」ではありません。</div>`);
    }else{
      const sel=[...all].filter(x=>num(x.selective_watch_rank)!==null).sort((a,b)=>a.selective_watch_rank-b.selective_watch_rank).slice(0,4);
      const atk=[...all].filter(x=>num(x.attack_watch_rank)!==null).sort((a,b)=>a.attack_watch_rank-b.attack_watch_rank).slice(0,12);
      uStocks.innerHTML=`<div class="u-alert"><b>現在は${esc(modeJa(mode))}。</b> 下の2本は復帰した場合の監視順位で、買いシグナルではありません。</div>`+
        card('SELECTIVE復帰時 Top4','Blue/Green ＋ Breadth 50〜60%。RS189だけで順位付け。',stockTable(sel,mode,'selective'))+
        card('ATTACK復帰時 Top12','Blue/Green ＋ Breadth≥60%。Stock70 + strict LOO Theme30。',ranking.attack_watch_status==='READY'?stockTable(atk,mode,'attack'):'<div class="u-empty">ATTACK監視順位はDATA REQUIRED。</div>');
    }
  }

  function renderTqqq(v){
    const nrm=v.normal_tqqq||{},p=v.panic_tqqq||{},g=v.gross100_allocation||{};
    const tqProblem=nrm.status!=='READY'||String(p.status||'').includes('DATA REQUIRED');
    const tqBanner=tqProblem?`<div class="u-alert bad"><b>TQQQデータ不足。</b> CURRENT30 / Panicの値を実行判断に使わないでください。Normal: ${esc(nrm.status||'—')} / Panic: ${esc(p.status||'—')}</div>`:'';
    const seedAge=num(p.seed_age_sessions),seedValid=seedAge!==null&&seedAge>=0&&seedAge<=30;
    const seedV=isNum(p.vix_close)&&Number(p.vix_close)>=23,seedD=isNum(p.qqq_sma50_atr_deviation)&&Number(p.qqq_sma50_atr_deviation)<=-0.5,seedDD=isNum(p.qqq_drawdown10)&&Number(p.qqq_drawdown10)<=-0.02;
    const strategyTarget=p.active?(p.requested_target_pct??nrm.underlying_target_pct):nrm.underlying_target_pct;
    const grossReady=String(g.status||'').includes('LIVE ALLOCATION READY');
    uTqqq.innerHTML=healthBanner(v)+tqBanner+`<div class="u-call"><div class="ey">TQQQ STRATEGY · ${esc(v.asof||'—')}</div><div class="main">戦略目標 ${fmt(strategyTarget,0)}%</div><div class="sub">これは実口座の現在保有率ではありません。CURRENT30 hierarchy と Panic F80 の戦略目標です。</div></div>`+
      card('CURRENT30','30%はnormal base。risk lock等で現在Targetは変わります。',`<div class="u-grid4"><div class="u-metric"><div class="k">Normal Base</div><div class="v">${fmt(nrm.normal_exposure_pct,0)}%</div></div><div class="u-metric"><div class="k">Hierarchy Target</div><div class="v">${fmt(nrm.underlying_target_pct,0)}%</div></div><div class="u-metric"><div class="k">Risk Lock</div><div class="v">${nrm.risk_lock?'ON':'OFF'}</div><div class="n">SLOW ${nrm.slow_lock?'ON':'OFF'} / FAST ${nrm.fast_lock?'ON':'OFF'} / MC ${nrm.mc_lock?'ON':'OFF'}</div></div><div class="u-metric"><div class="k">Panic</div><div class="v">${p.active?'ACTIVE':'OFF'}</div></div></div>`)+
      card('Panic Seed / Trigger','Seed 3条件AND成立後、age≤30内のQQQ 4H RSI14 TOUCH30＋MC57≥20。',`${row('Seed状態',seedAge===null?'Seedデータなし':`age=${seedAge}`,seedValid?'<span class="u-pill go">有効</span>':'<span class="u-pill warn">なし / 期限外</span>')}${row('VIX ≥ 23',`現在 ${fmt(p.vix_close,2)}`,seedV?'<span class="u-pill go">現在成立</span>':'<span class="u-pill">現在未成立</span>')}${row('QQQ SMA50乖離 ≤ −0.5ATR',`現在 ${fmt(p.qqq_sma50_atr_deviation,2)} ATR`,seedD?'<span class="u-pill go">現在成立</span>':'<span class="u-pill">現在未成立</span>')}${row('QQQ 10日DD ≤ −2%',`現在 ${isNum(p.qqq_drawdown10)?pct(Number(p.qqq_drawdown10)*100,2):'—'}`,seedDD?'<span class="u-pill go">現在成立</span>':'<span class="u-pill">現在未成立</span>')}${row('QQQ 4H RSI14',`現在 ${fmt(p.rsi4h,1)} / 有効Seed内だけTrigger`,p.touch30_today?'<span class="u-pill go">本日TOUCH30</span>':'未TOUCH')}${row('MC57',`Entry≥20 / Active Exit<20`,fmt(p.mc57,1))}`)+
      card('Panic / 最終モデル配分','F80は固定80%ではなく max(CURRENT30 target,80%)。GROSS100は実口座保有率ではなくモデル配分です。',`<div class="u-grid4"><div class="u-metric"><div class="k">Panic Floor</div><div class="v">${fmt(p.floor_pct_when_active,0)}%</div></div><div class="u-metric"><div class="k">Requested</div><div class="v">${fmt(p.requested_target_pct,0)}%</div></div><div class="u-metric"><div class="k">モデル最終TQQQ</div><div class="v">${grossReady?fmt(g.tqqq_allocated_pct,0)+'%':'—'}</div></div><div class="u-metric"><div class="k">モデルGross</div><div class="v">${grossReady?fmt(g.gross_allocated_pct,0)+'%':'—'}</div></div></div>`,'u-model');
  }

  function resetStatusJa(s){return({ACTIVE_POSITION:'モデル保有中',SIGNAL_TODAY_NEXT_OPEN:'反発確認→翌寄り',RSI30_TOUCHED_WAIT_RISE:'30以下到達・反発待ち',APPROACHING_RSI30:'RSI30まで5pt以内',NEAR_RSI30:'RSI30まで10pt以内',WATCHING:'監視中',SIGNAL_OCCURRED:'Signal済み'}[s]||s||'—')}
  function renderManage(v){
    const r=v.panic_reset||{},ns=v.normal_stock_sleeve||{},memo=loadAuditMemo();
    const signals=(r.monitor||[]).filter(x=>x.status==='SIGNAL_TODAY_NEXT_OPEN');
    const watch=(r.monitor||[]).filter(x=>x.status!=='SIGNAL_TODAY_NEXT_OPEN'&&x.status!=='ACTIVE_POSITION').sort((a,b)=>(num(a.distance_to_30)??999)-(num(b.distance_to_30)??999));
    const sigRows=signals.map(x=>`<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td>${esc(x.signal_date||v.asof||'—')}</td><td>翌営業日寄りEntry</td></tr>`).join('');
    const watchRows=watch.slice(0,20).map(x=>`<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td>${esc(resetStatusJa(x.status))}</td><td>${x.signal_window_days_left??'—'}</td><td>${x.current_theme_rs63_top3?'Top3':'—'}</td></tr>`).join('');
    const memoRows=memo.map(x=>`<tr><td class="tk">${esc(x.ticker||'—')}</td><td>${fmt(x.entry,2)}</td><td>${fmt(x.current,2)}</td><td>${fmt(x.peak,2)}</td><td>${x.partial?'済':'未'}</td></tr>`).join('');
    const modelRows=(ns.positions||[]).map(x=>{const ret=isNum(x.close)&&isNum(x.entry_price)?(Number(x.close)/Number(x.entry_price)-1)*100:null;return `<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.entry_date||'—')}</td><td>${fmt(x.entry_price,2)}</td><td>${fmt(x.close,2)}</td><td class="${toneClass(ret)}">${pct(ret,1)}</td><td>${x.partial_done?'済':'未'}</td></tr>`}).join('');
    const resetModelRows=(r.positions||[]).map(x=>`<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.theme||'—')}</td><td>${esc(x.entry_date||'—')}</td><td>${x.held_sessions??'—'}</td></tr>`).join('');
    uManage.innerHTML=healthBanner(v)+
      card('実保有記録｜Command Center',`この端末の localStorage「v38_holdings」に手入力・記録されたものです。証券口座の自動取得ではありません。V38通常株だけに限定した一覧でもありません。`,`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>区分</th><th>Entry日</th><th>平均Entry</th><th>残数量</th><th>状態</th></tr></thead><tbody>${localHoldingRows()||'<tr><td colspan="6">この端末の保有記録なし</td></tr>'}</tbody></table></div>`,'u-local')+
      card('RSI30 Panic Reset｜正式Signal / 監視',`Signalはルールエンジンの判定です。モデルの「保有中」と実口座保有は別です。`,`${signals.length?`<div class="u-alert info"><b>正式Signal ${signals.length}銘柄。</b> 条件を満たした翌営業日寄りEntry対象。</div>`:'<div class="u-empty">現在、正式Reset Signalなし。</div>'}<div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Theme</th><th>RSI14</th><th>Signal日</th><th>行動</th></tr></thead><tbody>${sigRows||'<tr><td colspan="5">Signalなし</td></tr>'}</tbody></table></div><details style="margin-top:10px"><summary>Signal前の監視候補を見る（ここに出るだけでは買わない）</summary><div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Theme</th><th>RSI14</th><th>状態</th><th>残り</th><th>Theme内</th></tr></thead><tbody>${watchRows||'<tr><td colspan="6">監視なし</td></tr>'}</tbody></table></div></details>`)+
      card('V38通常株｜監査用手動メモ',`localStorage「v38_audited_positions_v1」。既存V38画面と同じく空き枠計算には未使用です。`,`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Entry</th><th>Current</th><th>Peak Close</th><th>Partial25</th></tr></thead><tbody>${memoRows||'<tr><td colspan="5">監査メモなし</td></tr>'}</tbody></table></div>`)+
      card('戦略モデル追跡｜実保有ではない',`normal_stock_sleeve（${esc(ns.strategy||'—')}）は研究シミュレータseedから前日終値/翌寄りルールで進めるモデル状態です。実口座とは同期しません。`,`<details><summary>通常株モデル ${ns.position_count??0}銘柄 / モデル上限 ${fmt(ns.portfolio_desired_pct,1)}%</summary><div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>モデルEntry日</th><th>モデルEntry</th><th>Close</th><th>モデル損益</th><th>+24%</th></tr></thead><tbody>${modelRows||'<tr><td colspan="6">モデル保有なし</td></tr>'}</tbody></table></div></details><details style="margin-top:8px"><summary>RSI Resetモデル追跡 ${r.position_count??0}銘柄</summary><div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Theme</th><th>モデルEntry日</th><th>保有日数</th></tr></thead><tbody>${resetModelRows||'<tr><td colspan="4">モデル保有なし</td></tr>'}</tbody></table></div></details>`,'u-model');
  }

  function rotationRows(d){
    const themes=d?.observations?.rotation_buckets?.themes;
    const raw=Array.isArray(themes)?themes:Object.values(d?.observations?.rotation_buckets||{}).flat();
    const map=new Map();raw.filter(x=>x&&x.ticker).forEach(x=>{if(!map.has(x.ticker))map.set(x.ticker,x)});return [...map.values()];
  }
  function priceBand(v){if(!isNum(v))return{key:'na',label:'未計算'};const x=Number(v);if(x>=70)return{key:'strong',label:'強い'};if(x<45)return{key:'weak',label:'弱い'};return{key:'mid',label:'中立'}}
  function internalBand(v){if(!isNum(v))return{key:'na',label:'未取得'};const x=Number(v);if(x>=60)return{key:'strong',label:'強い'};if(x<45)return{key:'weak',label:'弱い'};return{key:'mid',label:'中立'}}
  function deltaBand(v){if(!isNum(v))return{key:'na',label:'変化未取得'};const x=Number(v);if(x>=10)return{key:'up',label:'改善'};if(x<=-10)return{key:'down',label:'悪化'};return{key:'flat',label:'横ばい'}}
  function flowMetric(r){
    if(r?.flow_ready&&isNum(r.flow_20d_pct_aum))return{pct:Number(r.flow_20d_pct_aum),usd:num(r.flow_20d_usd),period:'20日',validated:true,provider:r.flow_provider||'actual Fund Flow'};
    if(r?.ticker==='DRAM'&&isNum(r.flow_1m_pct_aum))return{pct:Number(r.flow_1m_pct_aum),usd:num(r.flow_1m_usd),period:'1M',validated:false,provider:r.flow_1m_provider||'TradingView'};
    return{pct:null,usd:null,period:'—',validated:false,provider:null};
  }
  function enrichFlowMagnitude(rows){const vals=rows.map(flowMetric).filter(f=>f.validated&&isNum(f.pct)).map(f=>Math.abs(Number(f.pct))).sort((a,b)=>a-b);rows.forEach(r=>{const f=flowMetric(r);if(!f.validated||!isNum(f.pct)||!vals.length){r.__flowMagnitudePctile=null;return}const a=Math.abs(Number(f.pct));let le=0;for(const v of vals)if(v<=a)le++;r.__flowMagnitudePctile=100*le/vals.length})}
  function flowBand(r){const f=flowMetric(r);if(!isNum(f.pct))return{key:'na',label:'未取得',...f};const x=Number(f.pct),qq=isNum(r.__flowMagnitudePctile)?Number(r.__flowMagnitudePctile):null;if(Math.abs(x)<0.05)return{key:'flat',label:'ほぼ横ばい',...f};const scale=qq!==null&&qq>=75?'（大）':qq!==null&&qq<=25?'（小）':'';return x>0?{key:'in',label:`純流入${scale}`,...f}:{key:'out',label:`純流出${scale}`,...f}}
  function describeRow(r){
    if(r.ticker==='DRAM'&&(r.rs189_pending||r.state==='RS189_PENDING'))return{key:'pending',tone:'watch',title:'RS189待ち',note:'短期価格・補助構成株・1M純資金のみ表示。既存55テーマ順位には混ぜない。'};
    const p=priceBand(r.price_score),i=internalBand(r.internal_score),d=deltaBand(r.internal_delta20),f=flowBand(r),pv=num(r.price_score),iv=num(r.internal_score),dv=num(r.internal_delta20),fv=num(f.pct);
    if(pv!==null&&iv!==null&&pv>=60&&iv>=60&&fv!==null&&fv<0)return{key:'strong_outflow',tone:'watch',title:'テーマ強い・ETF純流出',note:`価格と構成株は強い。一方、ETF商品からは${f.period}で${pct(fv,2)}純流出。`};
    if(pv!==null&&iv!==null&&pv>=70&&iv>=60)return{key:'strong',tone:'good',title:'価格・構成株とも強い',note:`テーマの値動きと中の個別株がそろって強い。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv,2)}`:''}。`};
    if(dv!==null&&dv>=10&&iv!==null&&iv>=50&&fv!==null&&fv>=0)return{key:'improving_inflow',tone:'watch',title:'構成株改善＋ETF純流入',note:`構成株の強さが20日で${pct(dv,1)}改善し、ETFにも${f.period}純流入。`};
    if(pv!==null&&iv!==null&&pv<45&&iv<45)return{key:'weak',tone:'bad',title:'価格・構成株とも弱い',note:`ETF価格も中の個別株もTheme56下位。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv,2)}`:''}。`};
    if(iv!==null&&iv<45&&fv!==null&&fv<0)return{key:'weak_outflow',tone:'bad',title:'構成株弱い＋ETF純流出',note:`構成株が弱く、ETF商品からも${f.period}で${pct(fv,2)}純流出。`};
    if(pv!==null&&iv!==null&&pv<60&&iv>=60)return{key:'internal_lead',tone:'watch',title:'構成株が先行',note:`ETF価格はまだ上位ではないが、中の個別株は強い。構成株変化は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。`};
    if(pv!==null&&iv!==null&&pv>=70&&iv<50)return{key:'price_lead',tone:'watch',title:'価格先行・構成株弱め',note:`ETF価格は強いが、構成株の広がりが追いついていない。構成株は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。`};
    if(fv!==null&&fv>0&&pv!==null&&iv!==null&&pv<60&&iv<50)return{key:'flow_lead',tone:'watch',title:'ETF純流入が先行',note:`ETF商品には${f.period}で${pct(fv,2)}純流入。ただし価格・構成株はまだ上位ではない。`};
    const tone=(p.key==='weak'||i.key==='weak'||d.key==='down')?'bad':'neutral';return{key:'explicit_mix',tone,title:`価格${p.label}・構成株${i.label}`,note:`構成株は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv,2)}`:''}。`};
  }
  function pillTone(t){return t==='good'?'go':t==='watch'?'warn':t==='bad'?'bad':''}
  function flowQuality(r,f){if(!f.validated)return f.period==='1M'?'1M補助（標準20日順位外）':'未検証';if(r.flow_quality==='ISSUER_EXACT_OFFICIAL')return'発行会社Exact';if(r.flow_quality==='ETFCOM_VALIDATED_ACTUAL')return'照合済actual';return r.flow_quality||f.provider||'actual'}
  function renderRotation(rot,ctx,v38){
    if(!rot){uRotation.innerHTML=card('資金循環','Rotationデータを取得できませんでした。','<div class="u-empty">既存Command CenterのRotation詳細は下に残しています。</div>');if(byId['t-rotation'])uRotation.appendChild(byId['t-rotation']);return}
    const rows=rotationRows(rot);enrichFlowMagnitude(rows);rows.forEach(r=>r.__desc=describeRow(r));
    const aligned=String(rot.asof||'')===String(v38?.asof||'');
    const dataStatus=rot.theme56_data_status||{};
    const meta=`<div class="u-alert ${aligned?'info':''}"><b>Rotationは研究Context（売買ルール未採用）。</b> Rotation基準 ${esc(rot.asof||'—')} / V38基準 ${esc(v38?.asof||'—')} / ${aligned?'基準日一致':'基準日不一致'}。Full Stack ${dataStatus.measured_full_stack_count??'—'}/56。ETF純資金は発行会社Exactまたは照合済actualを標準20日比較に使用し、DRAM 1M補助は混ぜません。</div>`;
    const strong=rows.filter(r=>num(r.price_score)!==null&&num(r.internal_score)!==null&&Number(r.price_score)>=70&&Number(r.internal_score)>=60).sort((a,b)=>Number(b.price_score)-Number(a.price_score)).slice(0,5);
    const improving=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)>0).sort((a,b)=>Number(b.internal_delta20)-Number(a.internal_delta20)).slice(0,5);
    const deteriorating=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)<0).sort((a,b)=>Number(a.internal_delta20)-Number(b.internal_delta20)).slice(0,5);
    const one=(r,metric)=>{const d=r.__desc,f=flowMetric(r),val=metric==='delta'?pct(r.internal_delta20,1):`P${fmt(r.price_score,0)} / I${fmt(r.internal_score,0)}${f.validated?` / Flow ${pct(f.pct,1)}`:''}`;return `<div class="u-rot-line"><b>${esc(etfLabel(r))}</b><span class="u-pill ${pillTone(d.tone)}">${esc(d.title)}</span><span class="note">${esc(val)}</span></div>`};
    const validatedFlows=rows.map(r=>({r,f:flowMetric(r)})).filter(x=>x.f.validated&&isNum(x.f.pct));
    const ranked=[...[...validatedFlows].sort((a,b)=>Number(b.f.pct)-Number(a.f.pct)).slice(0,7),...[...validatedFlows].sort((a,b)=>Number(a.f.pct)-Number(b.f.pct)).slice(0,7)];
    const seen=new Set(),flowRows=ranked.filter(x=>!seen.has(x.r.ticker)&&seen.add(x.r.ticker));
    const flowTable=flowRows.map(({r,f})=>{const d=r.__desc;return `<tr><td class="tk">${esc(r.ticker)}</td><td>${esc(r.label||ETF[r.ticker]||'')}</td><td class="${toneClass(f.pct)}">${pct(f.pct,2)}</td><td>${money(f.usd)}</td><td>${esc(flowQuality(r,f))}</td><td><span class="u-pill ${pillTone(d.tone)}">${esc(d.title)}</span></td></tr>`}).join('');
    const themeTable=[...rows].sort((a,b)=>(num(b.price_score)||-999)-(num(a.price_score)||-999)).map(r=>{const f=flowMetric(r),d=r.__desc,flowLabel=f.period==='1M'?`${pct(f.pct,1)} (1M補助)`:pct(f.pct,1);return `<tr><td class="tk">${esc(r.ticker)}</td><td>${esc(r.label||ETF[r.ticker]||'')}</td><td>${fmt(r.price_score,0)}</td><td>${fmt(r.internal_score,0)}</td><td class="${toneClass(r.internal_delta20)}">${pct(r.internal_delta20,1)}</td><td class="${toneClass(f.pct)}">${flowLabel}</td><td>${esc(flowQuality(r,f))}</td><td><span class="u-pill ${pillTone(d.tone)}">${esc(d.title)}</span></td></tr>`}).join('');
    const points=rows.filter(r=>isNum(r.price_score)&&isNum(r.internal_score));
    const W=620,H=360,L=42,R=14,T=15,B=34,iw=W-L-R,ih=H-T-B,sx=x=>L+Math.max(0,Math.min(100,x))/100*iw,sy=y=>T+ih-Math.max(0,Math.min(100,y))/100*ih;
    let svg=`<svg class="u-map" viewBox="0 0 ${W} ${H}" role="img" aria-label="Theme56 Rotation Map"><rect x="${L}" y="${T}" width="${iw}" height="${ih}" rx="8" fill="#f2f1ee" stroke="#e3e1db"/><line x1="${sx(50)}" x2="${sx(50)}" y1="${T}" y2="${T+ih}" stroke="#d6d4ca"/><line x1="${L}" x2="${L+iw}" y1="${sy(50)}" y2="${sy(50)}" stroke="#d6d4ca"/>`;
    [0,25,50,75,100].forEach(v=>{svg+=`<text x="${sx(v)}" y="${H-10}" fill="#575242" font-size="9" text-anchor="middle">${v}</text><text x="${L-7}" y="${sy(v)+3}" fill="#575242" font-size="9" text-anchor="end">${v}</text>`});
    points.forEach(r=>{const d=r.__desc,c=d.tone==='good'?'#5f9870':d.tone==='bad'?'#b45a52':d.tone==='watch'?'#ad8021':'#8c887d';svg+=`<g><circle cx="${sx(r.price_score)}" cy="${sy(r.internal_score)}" r="8" fill="${c}" fill-opacity=".82"><title>${esc(etfLabel(r))} / ${esc(d.title)}</title></circle><text x="${sx(r.price_score)}" y="${sy(r.internal_score)+3}" fill="#f6f4ef" font-size="6.5" font-weight="800" text-anchor="middle">${esc(r.ticker)}</text></g>`});
    svg+=`<text x="${L+iw/2}" y="${H-1}" fill="#575242" font-size="10" text-anchor="middle">ETF価格の強さ →</text><text x="10" y="${T+ih/2}" fill="#575242" font-size="10" text-anchor="middle" transform="rotate(-90 10 ${T+ih/2})">構成株の強さ →</text></svg>`;
    let leaders='';
    const rowBy=Object.fromEntries(rows.map(r=>[r.ticker,r]));
    (ctx?.industry_context||[]).map(item=>{const full=item.existing_emerging_or_leading_leaders_in_full_intersection||[],top=item.existing_emerging_or_leading_leaders_in_top15_intersection||[],ls=full.length?full:top;return{item,ls,r:rowBy[item.etf]}}).filter(x=>x.r&&x.ls.length&&['strong','strong_outflow','improving_inflow','internal_lead','price_lead'].includes(x.r.__desc.key)).slice(0,10).forEach(({item,ls,r})=>{leaders+=`<div class="u-row"><div><div class="name">${esc(etfLabel(r))}</div><div class="meta">${ls.slice(0,6).map(s=>`${esc(s.symbol)}${s.role?` (${esc(s.role==='PIONEER'?'先導':s.role==='LEADER'?'主導':s.role)})`:''}`).join(' · ')}</div></div><div class="value">${ls.length}<small>Leadership一致</small></div></div>`});
    uRotation.innerHTML=meta+card('資金循環','WHEREの観測。価格・構成株・ETF純資金を分離し、正式V38順位やHard Gateへは使いません。',`<div class="u-rot-top"><div class="u-rot-col"><h3>現在強い</h3>${strong.map(r=>one(r,'state')).join('')||'<div class="u-empty">明確な上位なし</div>'}</div><div class="u-rot-col"><h3>構成株が改善</h3>${improving.map(r=>one(r,'delta')).join('')||'<div class="u-empty">改善確認なし</div>'}</div><div class="u-rot-col"><h3>悪化警戒</h3>${deteriorating.map(r=>one(r,'delta')).join('')||'<div class="u-empty">悪化確認なし</div>'}</div></div>`)+
      card('Rotation Map','横＝ETF価格、縦＝構成株の強さ。状態表示はRotation本体と同じ判定。',`<div class="u-legend"><span><i class="g"></i>強い</span><span><i class="y"></i>改善 / 先行</span><span><i class="r"></i>弱化</span><span><i class="n"></i>中立 / その他</span></div>${svg}`)+
      card('ETF純資金｜標準20日','ETFの設定−解約。売買代金ではありません。発行会社Exact＋照合済actualだけをランキング。DRAM 1M補助は除外。',`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>ETF</th><th>Theme</th><th>純資金/AUM</th><th>USD</th><th>品質</th><th>状態</th></tr></thead><tbody>${flowTable||'<tr><td colspan="6">データなし</td></tr>'}</tbody></table></div>`)+
      card('先導株 / 主導株','現在ETF構成 × 既存Leadership。Rotation独自の銘柄ランキングではありません。',leaders||'<div class="u-empty">対象テーマでLeadership一致なし</div>')+
      card('Theme56','DRAMの1M補助は標準20日Flowと明示的に分離。',`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>ETF</th><th>Theme</th><th>Price</th><th>Internal</th><th>20日変化</th><th>ETF純資金</th><th>品質</th><th>状態</th></tr></thead><tbody>${themeTable}</tbody></table></div>`)+
      card('データ品質 / 基準日','研究Contextのため、鮮度と品質を隠さず表示。',`<div class="u-grid"><div class="u-metric"><div class="k">Rotation基準</div><div class="v">${esc(shortDate(rot.asof))}</div></div><div class="u-metric"><div class="k">V38基準</div><div class="v">${esc(shortDate(v38?.asof))}</div></div><div class="u-metric"><div class="k">20日Flow Ready</div><div class="v">${dataStatus.flow_ready_count??'—'}/56</div><div class="n">Exact ${dataStatus.issuer_exact_flow_count??'—'} + validated actual</div></div><div class="u-metric"><div class="k">Leadership市場データ</div><div class="v">${esc(shortDate(ctx?.leadership_coverage?.market_asof))}</div></div></div>`);
    if(byId['t-rotation']){const d=document.createElement('details');d.className='card';d.innerHTML='<summary style="font-size:12px;font-weight:800;cursor:pointer">既存Command Center Rotation 詳細</summary>';d.appendChild(byId['t-rotation']);uRotation.appendChild(d)}
  }

  const V38_URL='v38-live-state.json';
  const ROT_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const CTX_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';
  let v38=null,rot=null,ctx=null;
  try{v38=await fetch(V38_URL+'?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()})}catch(e){console.error('V38 unified load',e)}
  try{[rot,ctx]=await Promise.all([fetch(ROT_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null),fetch(CTX_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null)])}catch(e){console.error('Rotation unified load',e)}

  if(v38){markLegacyMarket(v38);renderToday(v38);renderStocks(v38);renderTqqq(v38);renderManage(v38)}else{
    const msg=card('V38 live','データ取得に失敗しました。','<div class="u-empty">既存Command Centerはそのまま使用できます。</div>');uToday.innerHTML=uStocks.innerHTML=uTqqq.innerHTML=uManage.innerHTML=msg;
  }
  renderRotation(rot,ctx,v38);
  const hash=String(location.hash||'').replace('#','');
  showRoute(tabs.some(x=>x[0]===hash)?hash:'today');
})();

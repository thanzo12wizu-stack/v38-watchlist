'use strict';
(async function unifiedV2(){
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[m]));
  const isNum=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
  const n=v=>isNum(v)?Number(v):null;
  const fmt=(v,d=1)=>isNum(v)?Number(v).toFixed(d):'—';
  const pct=(v,d=1)=>isNum(v)?`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`:'—';
  const money=v=>{if(!isNum(v))return'—';const x=Number(v),sg=x>=0?'+':'−',a=Math.abs(x);if(a>=1e9)return`${sg}${(a/1e9).toFixed(2)}B`;if(a>=1e6)return`${sg}${Math.round(a/1e6)}M`;if(a>=1e3)return`${sg}${Math.round(a/1e3)}K`;return`${sg}${Math.round(a)}`};
  const tone=v=>isNum(v)?(Number(v)>0?'pos':Number(v)<0?'neg':''):'';
  const modeJa=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';
  const ETF={CIBR:'サイバー',IGV:'ソフトウェア',WCLD:'クラウド・SaaS',OIH:'油田サービス',DRAM:'メモリ',SKYY:'クラウド基盤',XES:'油田装置',AIQ:'AI',ARKW:'次世代ネット',BOTZ:'ロボティクス',SMH:'半導体',HYDR:'水素',XOP:'石油探査',MOO:'農業',SOXX:'半導体装置',DRIV:'EV・自動運転',XSD:'半導体EW',QTUM:'量子・次世代',SLX:'鉄鋼',BLOK:'ブロックチェーン',XME:'金属・鉱業',GRID:'スマートグリッド',IAI:'証券・取引所',URA:'ウラン',NLR:'原子力',DTCR:'データセンター',FAN:'風力',ICLN:'クリーンEN',SHLD:'防衛テック',LIT:'リチウム電池',WOOD:'林業',XBI:'バイオテック',GNOM:'ゲノム',PHO:'水関連',KBE:'銀行',TAN:'ソーラー',KRE:'地銀',IHI:'医療機器',KIE:'保険',COPX:'銅鉱',IYT:'運輸',ITA:'航空宇宙・防衛',PAVE:'インフラ',SIL:'銀鉱',IBUY:'EC',REMX:'レアアース',PPH:'製薬',PKB:'建設',BOAT:'海運',XRT:'小売',XHB:'住宅建設',XAR:'宇宙・防衛',WGMI:'BTCマイニング',JETS:'航空',GDX:'金鉱',PEJ:'レジャー'};
  const etf=t=>`${t}${ETF[t]?`｜${ETF[t]}`:''}`;
  const wrap=q('.wrap')||document.body, oldNav=q('nav',wrap);
  if(!oldNav)return;
  const oldToday=q('#taCard'); if(oldToday)oldToday.style.display='none';
  oldNav.style.display='none'; oldNav.setAttribute('aria-hidden','true');

  const css=document.createElement('style');
  css.textContent=`
    #u-nav{display:flex!important}#u-nav button{cursor:pointer}#u-nav button.on{background:#3774d3;color:#fff;border-color:#eef3fb}
    #u-host>section{display:none}#u-host>section.on{display:block}.u-hidden{display:none!important}
    .u-alert{padding:9px 11px;border-radius:10px;margin:0 0 9px;font-size:11px;line-height:1.45;border:1px solid #d8d5ca;background:#eceae4}.u-alert.warn{border-color:#c9a34f;background:#f3ead1}.u-alert.bad{border-color:#bb7770;background:#f3dfdc}.u-alert b{font-weight:800}
    .u-call{border-radius:14px;padding:13px 15px;margin:0 0 12px;border:1px solid #dedbd2;background:linear-gradient(135deg,#eeece7,#e7e5df)}
    .u-call .ey{font-size:10px;color:#575242;font-weight:800;letter-spacing:.05em}.u-call .main{font-size:22px;font-weight:800;line-height:1.2;margin:3px 0}.u-call .sub{font-size:11px;color:#575242;line-height:1.5}
    .u-alloc,.u-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:9px}.u-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
    .u-box{background:#f2f1ee;border:1px solid #e2dfd6;border-radius:10px;padding:8px 9px;min-width:0}.u-box span{display:block;font-size:9.5px;color:#575242}.u-box b{display:block;font-size:18px;margin-top:1px}.u-box small{display:block;color:#777268;font-size:9px;margin-top:2px;line-height:1.35}
    .u-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 10px;padding:8px 2px;border-bottom:1px solid rgba(30,28,24,.07)}.u-row:last-child{border-bottom:0}.u-row .name{font-weight:800}.u-row .meta{font-size:10px;color:#68645b;line-height:1.4}.u-row .val{text-align:right;font-weight:800;white-space:nowrap}.u-row .val small{display:block;color:#777268;font-size:9px;font-weight:600}
    .u-pill{display:inline-block;border:1px solid #d5d1c7;background:#e9e7e1;border-radius:5px;padding:1px 5px;font-size:9.5px;font-weight:800}.u-pill.good{background:#dcebdc;border-color:#93b99b;color:#20743d}.u-pill.watch{background:#efe4c7;border-color:#c7a34e;color:#8b6418}.u-pill.bad{background:#efd9d7;border-color:#c98e88;color:#9b332d}
    .u-subnav{display:flex;gap:5px;overflow-x:auto;margin:0 0 10px;padding-bottom:6px;scrollbar-width:none}.u-subnav::-webkit-scrollbar{display:none}.u-subnav button{flex:0 0 auto;background:#ebeae5;color:#5a5850;border:1px solid #dfddd5;border-radius:14px;padding:6px 11px;font-size:11px;font-weight:700;cursor:pointer}.u-subnav button.on{background:#d8e4f5;color:#2c69c9;border-color:#9db9df}
    .u-panel{display:none}.u-panel.on{display:block}.u-table-wrap{overflow-x:auto;margin-top:7px}.u-table-wrap table{min-width:680px}.u-tk{font-weight:800;color:#2c69c9}.u-note{font-size:10.5px;color:#68645b;line-height:1.5;margin-top:7px}
    .u-rot-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:8px}.u-rot-col{background:#f2f1ee;border:1px solid #e2dfd6;border-radius:10px;padding:8px}.u-rot-col h3{font-size:11px;margin:0 0 4px}.u-rot-item{padding:6px 0;border-top:1px solid rgba(30,28,24,.07);font-size:10px;line-height:1.35}.u-rot-item:first-of-type{border-top:0}.u-rot-item b{font-size:11.5px}.u-map{display:block;width:100%;height:auto;margin-top:6px}.u-health{font-size:10.5px;line-height:1.55}.u-health b{font-weight:800}
    #u-market .u-legacy-top{display:none!important}
    @media(max-width:640px){.u-alloc{grid-template-columns:repeat(2,minmax(0,1fr))}.u-rot-cols{grid-template-columns:1fr}.u-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.u-call .main{font-size:20px}}
  `; document.head.appendChild(css);

  const sections=qa(':scope > section',wrap), byId=Object.fromEntries(sections.map(s=>[s.id,s]));
  const nav=document.createElement('nav'); nav.id='u-nav'; nav.setAttribute('aria-label','V38統合ナビ');
  const tabs=[['today','今日'],['market','市場'],['rotation','資金循環'],['stocks','銘柄'],['tqqq','TQQQ'],['manage','保有 / RSI'],['detail','詳細']];
  tabs.forEach(([id,label])=>{const b=document.createElement('button');b.type='button';b.dataset.u=id;b.textContent=label;nav.appendChild(b)});
  oldNav.after(nav); const host=document.createElement('div');host.id='u-host';nav.after(host);
  const sec=id=>{const s=document.createElement('section');s.id='u-'+id;host.appendChild(s);return s};
  const uToday=sec('today'),uMarket=sec('market'),uRotation=sec('rotation'),uStocks=sec('stocks'),uTqqq=sec('tqqq'),uManage=sec('manage'),uDetail=sec('detail');
  sections.forEach(s=>s.classList.remove('on'));
  ['t-today','t-rules','t-post1','t-rotation'].forEach(id=>{if(byId[id])byId[id].classList.add('u-hidden')});

  const card=(title,sub,body)=>`<div class="card"><h2>${title}</h2>${sub?`<div class="sub">${sub}</div>`:''}${body}</div>`;
  const row=(name,meta,val,small='')=>`<div class="u-row"><div><div class="name">${name}</div><div class="meta">${meta||''}</div></div><div class="val">${val}${small?`<small>${small}</small>`:''}</div></div>`;
  const pill=(text,kind='')=>`<span class="u-pill ${kind}">${esc(text)}</span>`;
  const actualOpen=()=>{try{return typeof window.hldLoad==='function'?window.hldLoad().filter(x=>x&&x.status!=='closed'):[]}catch(_){return[]}};

  let actualHoldCard=null;
  const hld=q('#hldList');
  if(hld){
    const srcCard=hld.closest('.card'), start=srcCard&&q('.swhold-h',srcCard);
    if(srcCard&&start){
      actualHoldCard=document.createElement('div');actualHoldCard.className='card';
      actualHoldCard.innerHTML='<h2>実保有記録 <span class="h2en">Actual Holdings</span></h2><div class="sub"><b>この端末のlocalStorageに自分で記録した実保有</b>です。V38戦略モデルの仮想保有とは別です。</div><div class="u-alert"><b>注意：</b>「Core 12 / レバETF / 裁量」は既存トレードノート上の記録ラベルです。正式V38ルールの判定そのものではありません。</div>';
      let node=start; while(node){const next=node.nextSibling;actualHoldCard.appendChild(node);node=next;}
    }
  }

  const legacyMarket=byId['t-market'];
  if(legacyMarket){[...legacyMarket.children].slice(0,7).forEach(x=>x.classList.add('u-legacy-top'));uMarket.appendChild(legacyMarket)}

  const detailDefs=[['formal','V38ルール/データ',null],['t-movers','Movers',byId['t-movers']],['t-rs','RS',byId['t-rs']],['t-weekly','週次参考',byId['t-weekly']],['t-port','早期警戒',byId['t-port']],['t-alloc','裁量プラン',byId['t-alloc']]].filter(x=>x[0]==='formal'||x[2]);
  uDetail.innerHTML='<div class="u-subnav" id="u-detail-nav"></div><div id="u-detail-body"></div>';
  const dnav=q('#u-detail-nav'),dbody=q('#u-detail-body');
  detailDefs.forEach(([id,label,node],i)=>{const b=document.createElement('button');b.type='button';b.dataset.panel=id;b.textContent=label;b.classList.toggle('on',i===0);dnav.appendChild(b);const p=document.createElement('div');p.className='u-panel'+(i===0?' on':'');p.dataset.panel=id;if(node){node.classList.remove('on','u-hidden');p.appendChild(node)}dbody.appendChild(p)});
  dnav.addEventListener('click',e=>{const b=e.target.closest('button[data-panel]');if(!b)return;qa('button',dnav).forEach(x=>x.classList.toggle('on',x===b));qa('.u-panel',dbody).forEach(x=>x.classList.toggle('on',x.dataset.panel===b.dataset.panel));window.scrollTo(0,nav.offsetTop)});

  function showRoute(route){qa('#u-host>section').forEach(s=>s.classList.toggle('on',s.id==='u-'+route));qa('#u-nav button').forEach(b=>b.classList.toggle('on',b.dataset.u===route));history.replaceState(null,'',route==='today'?location.pathname:`#${route}`);window.scrollTo(0,nav.offsetTop)}
  nav.addEventListener('click',e=>{const b=e.target.closest('button[data-u]');if(b)showRoute(b.dataset.u)});

  const V38_URL='v38-live-state.json';
  const ROT_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const CTX_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';
  let v=null,rot=null,ctx=null;
  try{v=await fetch(V38_URL+'?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('V38 '+r.status);return r.json()})}catch(e){console.error(e)}
  try{[rot,ctx]=await Promise.all([fetch(ROT_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null),fetch(CTX_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null)])}catch(e){console.error(e)}

  const legacyAsof=window.CALC?.asof||window.CALC?.date||null;
  const preserved=v?!!(v.gross100_allocation?.sleeve_preserved_previous_ready||/LAST[_ ]READY|STALE|更新失敗|前回READY/i.test(`${v.source||''} ${v.gross100_allocation?.status||''} ${v.gross100_allocation?.sleeve_refresh_status||''}`)):false;
  const healthAlert=()=>{
    if(!v)return'<div class="u-alert bad"><b>V38 live取得失敗。</b>正式判断を表示できません。</div>';
    const ga=v.gross100_allocation||{};let html='';
    if(preserved)html+=`<div class="u-alert warn"><b>一部スリーブ更新失敗：</b>前回READYを継続表示しています。最終成功 ${esc(ga.sleeve_last_successful_asof||v.asof||'—')} / 試行 ${esc(ga.sleeve_refresh_attempted_asof||'—')}。モデル保有・配分は実口座ではありません。</div>`;
    if(legacyAsof&&v.asof&&legacyAsof!==v.asof)html+=`<div class="u-alert warn"><b>基準日不一致：</b>Command Center ${esc(legacyAsof)} / V38 ${esc(v.asof)}。</div>`;
    return html;
  };

  function renderToday(){
    if(!v){uToday.innerHTML=healthAlert();return}
    const m=v.market||{},ga=v.gross100_allocation||{},r=v.panic_reset||{},ns=v.normal_stock_sleeve||{},p=v.panic_tqqq||{},mode=String(m.mode||'').toUpperCase();
    const action=mode==='ATTACK'?'通常個別株：新規可':mode==='SELECTIVE'?`通常個別株：選別して補充（上限 ${m.new_entry_limit??4}）`:mode==='DEFENSE'?'通常個別株：防御・次回寄り退避':'通常個別株：新規停止';
    const cash=isNum(ga.remaining_capacity_pct)?Number(ga.remaining_capacity_pct):(isNum(ga.gross_allocated_pct)?Math.max(0,100-Number(ga.gross_allocated_pct)):null);
    const actual=actualOpen();
    uToday.innerHTML=healthAlert()+`<div class="u-call"><div class="ey">TODAY · V38 ${esc(v.asof||'—')}</div><div class="main">${esc(action)}</div><div class="sub">NQSAR ${esc(m.nqsar||'—')} / Breadth50 ${fmt(m.breadth50,1)}% / Market Mode ${pill(modeJa(mode),mode==='ATTACK'?'good':mode==='DEFENSE'?'bad':'watch')}</div><div class="u-alloc"><div class="u-box"><span>TQQQ モデル配分</span><b>${fmt(ga.tqqq_allocated_pct,0)}%</b><small>実保有ではない</small></div><div class="u-box"><span>通常株 モデル配分</span><b>${fmt(ga.normal_stock_allocated_pct,0)}%</b><small>実保有ではない</small></div><div class="u-box"><span>RSI Reset モデル配分</span><b>${fmt(ga.reset_allocated_pct,1)}%</b><small>実保有ではない</small></div><div class="u-box"><span>モデル余力</span><b>${isNum(cash)?fmt(cash,0)+'%':'—'}</b><small>GROSS100</small></div></div></div>`+
      card('実保有とモデルを分離',`実保有はこの端末のトレードノート、戦略モデルはV38 live state。混ぜて表示しません。`,`<div class="u-grid"><div class="u-box"><span>実保有記録</span><b>${actual.length}件</b><small>この端末 / localStorage</small></div><div class="u-box"><span>通常株モデル</span><b>${ns.position_count??'—'}銘柄</b><small>${esc(ns.strategy||'—')} / 仮想追跡</small></div><div class="u-box"><span>Resetモデル</span><b>${r.position_count??'—'}銘柄</b><small>仮想追跡</small></div><div class="u-box"><span>Panic TQQQ</span><b>${p.active?'ACTIVE':'inactive'}</b><small>${esc(p.status||'—')}</small></div></div>`)+
      card('見る順番','WHEN → WHERE → WHAT。',row('① WHEN｜市場','正式V38：NQSAR + Breadth',`${modeJa(mode)} / 新規 ${m.new_entry_limit??'—'}`)+row('② WHERE｜資金循環','Theme56：価格・構成株・ETF純資金','資金循環タブ')+row('③ WHAT｜銘柄','正式V38 ranking','銘柄タブ'));
  }

  function renderMarket(){
    if(!v){uMarket.insertAdjacentHTML('afterbegin',healthAlert());return}
    const m=v.market||{},p=v.panic_tqqq||{},mode=String(m.mode||'').toUpperCase();
    const formal=card('正式V38 市場判断','ここが売買許可の正本。下のMarket Conditions・F1/F2/F3・流動性等は観測情報で、通常個別株のHard Gateにはしません。',`<div class="u-grid"><div class="u-box"><span>Market Mode</span><b>${esc(modeJa(mode))}</b><small>${esc(m.reason||'')}</small></div><div class="u-box"><span>新規枠上限</span><b>${m.new_entry_limit??'—'}</b><small>通常個別株</small></div><div class="u-box"><span>Breadth50</span><b>${fmt(m.breadth50,1)}%</b><small>coverage ${fmt((n(m.coverage)||0)*100,0)}%</small></div><div class="u-box"><span>MC57</span><b>${fmt(p.mc57,1)}</b><small>通常株Hard Gateではない</small></div></div>`);
    uMarket.insertAdjacentHTML('afterbegin',healthAlert()+formal);
  }

  function renderStocks(){
    if(!v){uStocks.innerHTML=healthAlert();return}
    const m=v.market||{},mode=String(m.mode||'').toUpperCase(),all=(v.candidates||[]).filter(x=>x.eligibility==='ELIGIBLE');
    if(mode==='ATTACK'||mode==='SELECTIVE'){
      const rows=[...all].filter(x=>isNum(x.final_rank)).sort((a,b)=>Number(a.final_rank)-Number(b.final_rank));
      const body=rows.slice(0,24).map(x=>`<tr><td class="u-tk">${esc(x.ticker)}</td><td>${x.final_rank}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${fmt(x.peer_theme_score,1)}</td><td>${esc(x.entry_status==='NEXT_OPEN_WHEN_CAPACITY'?'空き枠なら次回寄り':x.entry_status||'—')}</td></tr>`).join('');
      uStocks.innerHTML=healthAlert()+card('正式V38 実行候補',`${modeJa(mode)} / 新規枠上限 ${m.new_entry_limit??'—'}。final_rankのみを実行順位として表示。`,`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>正式順位</th><th>RS189</th><th>RS63</th><th>Theme</th><th>Theme強度</th><th>扱い</th></tr></thead><tbody>${body||'<tr><td colspan="7">実行候補なし</td></tr>'}</tbody></table></div>`);
    }else{
      const rows=[...all].filter(x=>isNum(x.attack_watch_rank)||isNum(x.selective_watch_rank)).sort((a,b)=>(n(a.attack_watch_rank)||999)-(n(b.attack_watch_rank)||999));
      const body=rows.slice(0,24).map(x=>`<tr><td class="u-tk">${esc(x.ticker)}</td><td>${x.attack_watch_rank??'—'}</td><td>${x.selective_watch_rank??'—'}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${pill('新規停止中',mode==='DEFENSE'?'bad':'watch')}</td></tr>`).join('');
      uStocks.innerHTML=healthAlert()+card('再開時ウォッチ順位',`${modeJa(mode)}中なので買いシグナルではありません。Attack再開時とSelective再開時を分けて表示します。`,`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>Attack再開</th><th>Selective再開</th><th>RS189</th><th>RS63</th><th>Theme</th><th>現在</th></tr></thead><tbody>${body||'<tr><td colspan="7">ウォッチ候補なし</td></tr>'}</tbody></table></div>`)+card('正式Eligibility','価格・流動性・トレンド・RS条件を通過した母集団。',`<div class="u-grid"><div class="u-box"><span>Price</span><b>≥ $5</b></div><div class="u-box"><span>DDV</span><b>≥ $10M</b></div><div class="u-box"><span>RS189 / RS63</span><b>≥ 85</b></div><div class="u-box"><span>Trend</span><b>50&gt;200</b><small>Close&gt;200</small></div></div>`);
    }
  }

  function renderTqqq(){
    if(!v){uTqqq.innerHTML=healthAlert();return}
    const nrm=v.normal_tqqq||{},p=v.panic_tqqq||{},ga=v.gross100_allocation||{};
    const dd=n(p.qqq_drawdown10),seedAge=n(p.seed_age_sessions),seedValid=seedAge!==null&&seedAge<=30;
    uTqqq.innerHTML=healthAlert()+`<div class="u-call"><div class="ey">TQQQ MODEL · ${esc(v.asof||'—')}</div><div class="main">Portfolioモデル配分 ${fmt(ga.tqqq_allocated_pct,0)}%</div><div class="sub">実保有ではありません。CURRENT30 hierarchy target ${fmt(nrm.underlying_target_pct,0)}% / Panic F80 ${p.active?'ACTIVE':'inactive'}</div></div>`+
      card('通常TQQQ','30%は基準値。Risk lock / hierarchyで実際のモデルTargetは変わります。',`<div class="u-grid"><div class="u-box"><span>基準Exposure</span><b>${fmt(nrm.normal_exposure_pct,0)}%</b><small>CURRENT30 baseline</small></div><div class="u-box"><span>Hierarchy Target</span><b>${fmt(nrm.underlying_target_pct,0)}%</b><small>${esc(nrm.status||'—')}</small></div><div class="u-box"><span>Portfolio配分</span><b>${fmt(ga.tqqq_allocated_pct,0)}%</b><small>GROSS100後</small></div><div class="u-box"><span>Risk lock</span><b>${nrm.risk_lock?'ON':'off'}</b></div></div>`)+
      card('Panic Seed / Trigger','Seedは3条件成立で記録され、30営業日以内にQQQ 4H RSI14≤30でTrigger。現在値が3条件を同時に満たす必要はありません。',row('Seedの有効期限',`age ${seedAge??'—'} / rule ${esc(p.seed_age_rule||'age <=30')}`,seedValid?pill('有効','watch'):pill('期限外',''))+row('VIX条件','Seed条件 VIX Close ≥23',fmt(p.vix_close,2))+row('QQQ SMA50乖離','Seed条件 ≤ -0.5ATR',`${fmt(p.qqq_sma50_atr_deviation,2)} ATR`)+row('QQQ 10日DD','Seed条件 ≤ -2%',dd===null?'—':pct(dd*100,2))+row('4H RSI14','Seed後のTrigger ≤30',fmt(p.rsi4h,1),p.touch30_today?'本日Touch':'本日Touchなし')+row('MC57','Entry ≥20 / Active Exit <20',fmt(p.mc57,1)))+
      card('Panic配分','F80はPanic有効時のfloor。',`<div class="u-grid"><div class="u-box"><span>Panic status</span><b>${esc(p.active?'ACTIVE':'inactive')}</b><small>${esc(p.status||'—')}</small></div><div class="u-box"><span>F80 floor</span><b>${fmt(p.floor_pct_when_active,0)}%</b></div><div class="u-box"><span>Underlying Target</span><b>${fmt(p.underlying_target_pct,0)}%</b></div><div class="u-box"><span>Requested Target</span><b>${fmt(p.requested_target_pct,0)}%</b></div></div>`);
  }

  function renderManage(){
    if(!v){uManage.innerHTML=healthAlert();return}
    const r=v.panic_reset||{},ns=v.normal_stock_sleeve||{};
    uManage.innerHTML='<div class="u-subnav" id="u-manage-nav"><button class="on" data-m="actual">実保有</button><button data-m="reset">RSI Reset</button><button data-m="model">モデル追跡</button></div><div id="u-manage-body"></div>';
    const body=q('#u-manage-body'), actual=document.createElement('div'),reset=document.createElement('div'),model=document.createElement('div');
    actual.className='u-panel on';actual.dataset.m='actual';reset.className='u-panel';reset.dataset.m='reset';model.className='u-panel';model.dataset.m='model';body.append(actual,reset,model);
    actual.innerHTML=healthAlert()+card('実保有','この端末に自分で記録した保有だけを表示します。V38モデル保有は「モデル追跡」へ分離。',`<div class="u-grid"><div class="u-box"><span>保有中</span><b>${actualOpen().length}件</b><small>localStorage</small></div><div class="u-box"><span>保存場所</span><b>この端末</b><small>JSONバックアップ推奨</small></div></div>`);if(actualHoldCard)actual.appendChild(actualHoldCard);
    const monitors=(r.monitor||[]).slice().sort((a,b)=>(n(a.distance_to_30)??999)-(n(b.distance_to_30)??999));
    const mr=monitors.slice(0,20).map(x=>`<tr><td class="u-tk">${esc(x.symbol)}</td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td>${esc(x.status==='RSI30_TOUCHED_WAIT_RISE'?'RSI30到達・反発待ち':x.status==='APPROACHING_RSI30'?'RSI30接近':x.status||'—')}</td><td>${x.signal_window_days_left??'—'}</td><td>${x.current_theme_rs63_top3?'Top3':'—'}</td></tr>`).join('');
    reset.innerHTML=healthAlert()+card('RSI30 Panic Reset','正式スリーブの監視/シグナル。接近帯は表示用で売買ルールではありません。モデルポジションと実保有は別です。',`<div class="u-grid"><div class="u-box"><span>モデルActive</span><b>${r.position_count??'—'}</b><small>実保有ではない</small></div><div class="u-box"><span>RSI30到達待ち</span><b>${r.monitor_summary?.touched_wait_rise??0}</b></div><div class="u-box"><span>5pt以内</span><b>${r.monitor_summary?.within_5pt??0}</b><small>表示帯のみ</small></div><div class="u-box"><span>監視</span><b>${r.monitor_summary?.watch_count??0}</b></div></div><div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>Theme</th><th>RSI14</th><th>状態</th><th>残り</th><th>Theme内</th></tr></thead><tbody>${mr||'<tr><td colspan="6">監視なし</td></tr>'}</tbody></table></div>`);
    const pos=(ns.positions||[]).map(x=>{const ret=isNum(x.close)&&isNum(x.entry_price)?(Number(x.close)/Number(x.entry_price)-1)*100:null;return`<tr><td class="u-tk">${esc(x.symbol)}</td><td>${esc(x.entry_date||'—')}</td><td>${fmt(x.entry_price,2)}</td><td>${fmt(x.close,2)}</td><td class="${tone(ret)}">${pct(ret,1)}</td><td>${x.partial_done?'済':'未'}</td></tr>`}).join('');
    model.innerHTML=healthAlert()+card('V38通常個別株｜戦略モデル追跡','バックテスト/採用ルールをライブ日次で仮想追跡したモデル状態です。<b>あなたの実保有ではありません。</b>',`<div class="u-grid"><div class="u-box"><span>Strategy</span><b>${esc(ns.strategy||'—')}</b></div><div class="u-box"><span>モデル保有</span><b>${ns.position_count??'—'}銘柄</b></div><div class="u-box"><span>モデルPortfolio</span><b>${fmt(ns.portfolio_desired_pct,1)}%</b></div><div class="u-box"><span>更新状態</span><b>${preserved?'前回READY継続':'READY'}</b><small>${esc(v.asof||'—')}</small></div></div><div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>モデルEntry日</th><th>モデルEntry</th><th>Close</th><th>モデル損益</th><th>+24%利確</th></tr></thead><tbody>${pos||'<tr><td colspan="6">モデル保有なし</td></tr>'}</tbody></table></div><div class="u-note">この表は実口座の約定履歴ではありません。実際に保有している銘柄は「実保有」だけを正として扱います。</div>`);
    const mnav=q('#u-manage-nav');mnav.addEventListener('click',e=>{const b=e.target.closest('button[data-m]');if(!b)return;qa('button',mnav).forEach(x=>x.classList.toggle('on',x===b));qa('.u-panel',body).forEach(x=>x.classList.toggle('on',x.dataset.m===b.dataset.m));window.scrollTo(0,nav.offsetTop)});
  }

  const allRows=d=>Object.values(d?.observations?.rotation_buckets||{}).flat().filter(x=>x&&x.ticker);
  const priceBand=v=>!isNum(v)?{key:'na',label:'未計算'}:Number(v)>=70?{key:'strong',label:'強い'}:Number(v)<45?{key:'weak',label:'弱い'}:{key:'mid',label:'中立'};
  const internalBand=v=>!isNum(v)?{key:'na',label:'未取得'}:Number(v)>=60?{key:'strong',label:'強い'}:Number(v)<45?{key:'weak',label:'弱い'}:{key:'mid',label:'中立'};
  const deltaBand=v=>!isNum(v)?{key:'na',label:'変化未取得'}:Number(v)>=10?{key:'up',label:'改善'}:Number(v)<=-10?{key:'down',label:'悪化'}:{key:'flat',label:'横ばい'};
  function flowMetric(r){if(r.flow_ready&&isNum(r.flow_20d_pct_aum))return{pct:Number(r.flow_20d_pct_aum),usd:n(r.flow_20d_usd),period:'20日',validated:true,provider:r.flow_provider||'actual Fund Flow'};if(r.ticker==='DRAM'&&isNum(r.flow_1m_pct_aum))return{pct:Number(r.flow_1m_pct_aum),usd:n(r.flow_1m_usd),period:'1M',validated:false,provider:r.flow_1m_provider||'TradingView'};return{pct:null,usd:null,period:'—',validated:false,provider:null}}
  const flowBand=r=>{const f=flowMetric(r);if(!isNum(f.pct))return{key:'na',label:'未取得',...f};if(Math.abs(Number(f.pct))<.05)return{key:'flat',label:'ほぼ横ばい',...f};return Number(f.pct)>0?{key:'in',label:'純流入',...f}:{key:'out',label:'純流出',...f}};
  function describeRow(r){if(r.ticker==='DRAM'&&(r.rs189_pending||r.state==='RS189_PENDING'))return{key:'pending',kind:'watch',title:'RS189待ち',note:'短期価格・補助構成株・1M純資金のみ表示。既存55テーマ順位には混ぜない。'};const p=priceBand(r.price_score),i=internalBand(r.internal_score),d=deltaBand(r.internal_delta20),f=flowBand(r),pv=n(r.price_score),iv=n(r.internal_score),dv=n(r.internal_delta20),fv=n(f.pct);if(pv!==null&&iv!==null&&pv>=60&&iv>=60&&fv!==null&&fv<0)return{key:'strong_outflow',kind:'watch',title:'テーマ強い・ETF純流出',note:`価格と構成株は強い。一方ETF商品から${f.period} ${pct(fv,2)}純流出。`};if(pv!==null&&iv!==null&&pv>=70&&iv>=60)return{key:'strong',kind:'good',title:'価格・構成株とも強い',note:`ETF価格と中の個別株がそろって強い。ETF純資金は${f.label}。`};if(dv!==null&&dv>=10&&iv!==null&&iv>=50&&fv!==null&&fv>=0)return{key:'improving_inflow',kind:'watch',title:'構成株改善＋ETF純流入',note:`構成株が20日で${pct(dv,1)}改善し、ETFにも純流入。`};if(pv!==null&&iv!==null&&pv<45&&iv<45)return{key:'weak',kind:'bad',title:'価格・構成株とも弱い',note:`ETF価格も中の個別株もTheme56下位。`};if(iv!==null&&iv<45&&fv!==null&&fv<0)return{key:'weak_outflow',kind:'bad',title:'構成株弱い＋ETF純流出',note:`構成株が弱くETF商品からも純流出。`};if(pv!==null&&iv!==null&&pv<60&&iv>=60)return{key:'internal_lead',kind:'watch',title:'構成株が先行',note:`ETF価格はまだ上位ではないが中の個別株は強い。`};if(pv!==null&&iv!==null&&pv>=70&&iv<50)return{key:'price_lead',kind:'watch',title:'価格先行・構成株弱め',note:`ETF価格は強いが構成株の広がりが追いついていない。`};if(fv!==null&&fv>0&&pv!==null&&iv!==null&&pv<60&&iv<50)return{key:'flow_lead',kind:'watch',title:'ETF純流入が先行',note:`ETF商品には純流入。ただし価格・構成株はまだ上位ではない。`};return{key:'explicit_mix',kind:(p.key==='weak'||i.key==='weak'||d.key==='down')?'bad':'',title:`価格${p.label}・構成株${i.label}`,note:`構成株は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv,2)}`:''}。`}}
  function renderRotation(){
    if(!rot){uRotation.innerHTML=card('資金循環','Rotationデータ取得失敗。','<div class="u-alert bad">Theme56を表示できません。</div>');return}
    const rows=allRows(rot),strong=rows.filter(r=>n(r.price_score)!==null&&n(r.internal_score)!==null&&n(r.price_score)>=70&&n(r.internal_score)>=60).sort((a,b)=>n(b.price_score)-n(a.price_score)),up=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)>0).sort((a,b)=>Number(b.internal_delta20)-Number(a.internal_delta20)),down=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)<0).sort((a,b)=>Number(a.internal_delta20)-Number(b.internal_delta20));
    const one=(r,k)=>{const d=describeRow(r),f=flowMetric(r),value=k==='up'?pct(r.internal_delta20,1):k==='down'?pct(r.internal_delta20,1):`P${fmt(r.price_score,0)} / I${fmt(r.internal_score,0)}`;return`<div class="u-rot-item"><b>${esc(etf(r.ticker))}</b> ${pill(d.title,d.kind)}<div>${value}${isNum(f.pct)?` / Flow ${pct(f.pct,1)}`:''}</div></div>`};
    const flow=rows.map(r=>({r,f:flowMetric(r)})).filter(x=>x.f.validated&&isNum(x.f.pct)).sort((a,b)=>Number(b.f.pct)-Number(a.f.pct));
    const fbody=[...flow.slice(0,7),...flow.slice(-7).reverse()].map(x=>{const d=describeRow(x.r);return`<tr><td class="u-tk">${esc(x.r.ticker)}</td><td>${esc(ETF[x.r.ticker]||'')}</td><td class="${tone(x.f.pct)}">${pct(x.f.pct,2)}</td><td>${money(x.f.usd)}</td><td>${fmt(x.r.price_score,0)}</td><td>${fmt(x.r.internal_score,0)}</td><td>${esc(d.title)}</td></tr>`}).join('');
    const allbody=[...rows].sort((a,b)=>(n(b.price_score)||0)-(n(a.price_score)||0)).map(r=>{const d=describeRow(r),f=flowMetric(r);return`<tr><td class="u-tk">${esc(r.ticker)}</td><td>${esc(ETF[r.ticker]||r.label||'')}</td><td>${fmt(r.price_score,0)}</td><td>${fmt(r.internal_score,0)}</td><td class="${tone(r.internal_delta20)}">${pct(r.internal_delta20,1)}</td><td class="${tone(f.pct)}">${pct(f.pct,1)}</td><td>${esc(d.title)}</td></tr>`}).join('');
    const pts=rows.filter(r=>isNum(r.price_score)&&isNum(r.internal_score)),W=620,H=360,L=42,R=14,T=15,B=34,iw=W-L-R,ih=H-T-B,sx=x=>L+Math.max(0,Math.min(100,x))/100*iw,sy=y=>T+ih-Math.max(0,Math.min(100,y))/100*ih;let svg=`<svg class="u-map" viewBox="0 0 ${W} ${H}"><rect x="${L}" y="${T}" width="${iw}" height="${ih}" rx="8" fill="#f2f1ee" stroke="#e3e1db"/><line x1="${sx(50)}" x2="${sx(50)}" y1="${T}" y2="${T+ih}" stroke="#d6d4ca"/><line x1="${L}" x2="${L+iw}" y1="${sy(50)}" y2="${sy(50)}" stroke="#d6d4ca"/>`;pts.forEach(r=>{const d=describeRow(r),c=d.kind==='good'?'#25814a':d.kind==='bad'?'#a9473e':d.kind==='watch'?'#ad8021':'#77736a';svg+=`<g><circle cx="${sx(r.price_score)}" cy="${sy(r.internal_score)}" r="8" fill="${c}" fill-opacity=".8"><title>${esc(etf(r.ticker))}｜${esc(d.title)}</title></circle><text x="${sx(r.price_score)}" y="${sy(r.internal_score)+3}" fill="#fff" font-size="6.5" font-weight="800" text-anchor="middle">${esc(r.ticker)}</text></g>`});svg+=`<text x="${L+iw/2}" y="${H-4}" fill="#575242" font-size="10" text-anchor="middle">価格 →</text><text x="10" y="${T+ih/2}" fill="#575242" font-size="10" text-anchor="middle" transform="rotate(-90 10 ${T+ih/2})">構成株 →</text></svg>`;
    let leaders='';const allowed=new Set(['strong','strong_outflow','improving_inflow','internal_lead','price_lead']);(ctx?.industry_context||[]).map(x=>{const rr=rows.find(r=>r.ticker===x.etf)||{},ls=x.existing_emerging_or_leading_leaders_in_full_intersection||x.existing_emerging_or_leading_leaders_in_top15_intersection||[];return{x,rr,ls,d:describeRow(rr)}}).filter(z=>z.ls.length&&allowed.has(z.d.key)).slice(0,10).forEach(z=>{leaders+=row(etf(z.x.etf),z.ls.slice(0,6).map(s=>`${esc(s.symbol)}${s.role?` (${s.role==='PIONEER'?'先導':s.role==='LEADER'?'主導':esc(s.role)})`:''}`).join(' · '),z.ls.length,'Leadership一致')});
    const alignment=rot.input_alignment||{};const warn=rot.research_only?`<div class="u-alert warn"><b>Rotationは研究観測レイヤー：</b>基準日 ${esc(rot.asof||'—')}。正式V38順位・新規許可・強制売却には使いません。${alignment.status&&alignment.status!=='OK'?` V38との入力基準日は ${esc(alignment.status)}。`:''}</div>`:'';
    uRotation.innerHTML=warn+card('資金循環','WHEREだけを見る。状態文言はRotation app-v2と同じ判定ロジック。',`<div class="u-rot-cols"><div class="u-rot-col"><h3>現在強い</h3>${strong.slice(0,5).map(r=>one(r,'state')).join('')||'—'}</div><div class="u-rot-col"><h3>構成株が改善</h3>${up.slice(0,5).map(r=>one(r,'up')).join('')||'—'}</div><div class="u-rot-col"><h3>悪化</h3>${down.slice(0,5).map(r=>one(r,'down')).join('')||'—'}</div></div>`)+card('Rotation Map','横=ETF価格、縦=構成株の強さ。',svg)+card('ETF純資金','検証済みactual Fund Flowの20日値。売買代金ではありません。',`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">ETF</th><th>Theme</th><th>Flow/AUM</th><th>純資金</th><th>価格</th><th>構成株</th><th>状態</th></tr></thead><tbody>${fbody}</tbody></table></div>`)+card('先導株 / 主導株','現ETF構成 × 既存Leadership。Rotation独自の株ランキングは作りません。',leaders||'<div class="u-note">一致なし</div>')+card('Theme56 全体','価格・構成株・20日変化・ETF純資金を分けて表示。',`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">ETF</th><th>Theme</th><th>価格</th><th>構成株</th><th>構成株20日</th><th>Flow/AUM</th><th>状態</th></tr></thead><tbody>${allbody}</tbody></table></div>`);
  }

  function renderDetailFormal(){const p=q('.u-panel[data-panel="formal"]');if(!p)return;if(!v){p.innerHTML=healthAlert();return}const m=v.market||{},r=v.ranking||{},pt=v.panic_tqqq||{},pr=v.panic_reset||{},ga=v.gross100_allocation||{};p.innerHTML=healthAlert()+card('正式V38の役割分離','統合版で混ぜないもの。',row('WHEN','NQSAR + Breadth',modeJa(m.mode))+row('WHERE','Rotation / Theme56','観測のみ')+row('WHAT','正式V38候補',esc(r.mode||'—')))+card('現在の正式仕様ID','データから確認できる採用仕様。',row('通常株 Ranking',esc(r.attack_formula||'ATTACK 70/30'),'SELECTIVEはRS189中心')+row('TQQQ Panic',esc(pt.candidate||'—'),`F${pt.floor_pct_when_active??'—'} / D10`)+row('RSI Reset',esc(pr.strategy||'—'),`最大 ${pr.max_positions??'—'}銘柄`)+row('Gross allocation',esc(ga.adoption_status||'—'),esc(ga.status||'—')))+card('データ品質','表示上の基準日とfallback。',`<div class="u-health"><b>Command Center:</b> ${esc(legacyAsof||'—')}<br><b>V38:</b> ${esc(v.asof||'—')}<br><b>Rotation:</b> ${esc(rot?.asof||'—')} ${rot?.research_only?'（research_only）':''}<br><b>V38 source:</b> ${esc(v.source||'—')}<br><b>Sleeve refresh:</b> ${esc(ga.sleeve_refresh_status||ga.status||'—')}<br><b>Last successful sleeve:</b> ${esc(ga.sleeve_last_successful_asof||'—')}</div>`)};

  renderToday();renderMarket();renderStocks();renderTqqq();renderManage();renderRotation();renderDetailFormal();
  const hash=String(location.hash||'').replace('#','');showRoute(tabs.some(x=>x[0]===hash)?hash:'today');
})();
'use strict';
(async function nativeUnifiedCommandCenter(){
  const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const num=v=>v!==null&&v!==''&&Number.isFinite(Number(v))?Number(v):null;
  const fmt=(v,d=1)=>num(v)===null?'—':Number(v).toFixed(d);
  const pct=(v,d=1)=>num(v)===null?'—':`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`;
  const money=v=>{const x=num(v);if(x===null)return'—';const s=x<0?'−':'+';const a=Math.abs(x);if(a>=1e9)return`${s}${(a/1e9).toFixed(2)}B`;if(a>=1e6)return`${s}${(a/1e6).toFixed(0)}M`;if(a>=1e3)return`${s}${(a/1e3).toFixed(0)}K`;return`${s}${a.toFixed(0)}`};
  const toneClass=v=>Number(v)>0?'pos':Number(v)<0?'neg':'';
  const modeJa=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';
  const statusJa=s=>({NEXT_OPEN_WHEN_CAPACITY:'空き枠なら次回寄り',HOLD:'保有',EXIT_NEXT_OPEN:'次回寄り退出',RSI30_TOUCHED_WAIT_RISE:'RSI30到達・反発待ち',APPROACHING_RSI30:'RSI30接近',SIGNAL_TODAY:'本日シグナル'})[s]||s||'—';
  const ETF={CIBR:'サイバー',IGV:'ソフトウェア',WCLD:'クラウド・SaaS',OIH:'油田サービス',DRAM:'メモリ',SKYY:'クラウド基盤',XES:'油田装置',AIQ:'AI',ARKW:'次世代ネット',BOTZ:'ロボティクス',SMH:'半導体',HYDR:'水素',XOP:'石油探査',MOO:'農業',SOXX:'半導体装置',DRIV:'EV・自動運転',XSD:'半導体EW',QTUM:'量子・次世代',SLX:'鉄鋼',BLOK:'ブロックチェーン',XME:'金属・鉱業',GRID:'スマートグリッド',IAI:'証券・取引所',URA:'ウラン',NLR:'原子力',DTCR:'データセンター',FAN:'風力',ICLN:'クリーンEN',SHLD:'防衛テック',LIT:'リチウム電池',WOOD:'林業',XBI:'バイオテック',GNOM:'ゲノム',PHO:'水関連',KBE:'銀行',TAN:'ソーラー',KRE:'地銀',IHI:'医療機器',KIE:'保険',COPX:'銅鉱',IYT:'運輸',ITA:'航空宇宙・防衛',PAVE:'インフラ',SIL:'銀鉱',IBUY:'EC',REMX:'レアアース',PPH:'製薬',PKB:'建設',BOAT:'海運',XRT:'小売',XHB:'住宅建設',XAR:'宇宙・防衛',WGMI:'BTCマイニング',JETS:'航空',GDX:'金鉱',PEJ:'レジャー'};
  const etf=t=>`${t}${ETF[t]?`｜${ETF[t]}`:''}`;

  const wrap=q('.wrap')||document.body;
  const oldNav=q('nav',wrap);
  if(!oldNav) return;
  oldNav.style.display='none';
  oldNav.setAttribute('aria-hidden','true');

  const extraStyle=document.createElement('style');
  extraStyle.textContent=`
    #u-nav{display:flex!important}
    #u-nav button{cursor:pointer}
    #u-nav button.on{background:#3774d3;color:#f1f0ef;border-color:#eef3fb}
    .u-subnav{display:flex;gap:5px;overflow-x:auto;margin:0 0 10px;padding:0 0 7px;scrollbar-width:none}
    .u-subnav::-webkit-scrollbar{display:none}
    .u-subnav button{flex:0 0 auto;background:#ebeae5;color:#5a5850;border:1px solid #dfddd5;border-radius:14px;padding:6px 11px;font-size:11px;font-weight:700;cursor:pointer}
    .u-subnav button.on{background:#d8e4f5;color:#2c69c9;border-color:#9db9df}
    .u-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:7px 0 10px}
    .u-metric{background:#f2f1ee;border:1px solid #e3e1db;border-radius:10px;padding:9px 10px;min-width:0}
    .u-metric .k{font-size:10px;color:#575242;font-weight:700}.u-metric .v{font-size:21px;font-weight:800;line-height:1.1;margin-top:2px;color:#1c1b19}.u-metric .n{font-size:9.5px;color:#575242;margin-top:3px;line-height:1.35}
    .u-call{border-radius:14px;padding:13px 15px;margin:0 0 12px;border:1px solid #e3e1db;background:linear-gradient(135deg,#ecebe7,#e5e4de)}
    .u-call .ey{font-size:10px;color:#575242;font-weight:800;letter-spacing:.04em}.u-call .main{font-size:22px;font-weight:800;line-height:1.2;margin:3px 0}.u-call .sub{font-size:11px;color:#565243;line-height:1.55}
    .u-alloc{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-top:9px}.u-alloc>div{background:rgba(27,29,28,.04);border:1px solid rgba(27,29,28,.07);border-radius:8px;padding:7px 5px;text-align:center}.u-alloc span{display:block;font-size:9px;color:#575242}.u-alloc b{display:block;font-size:16px;margin-top:1px}
    .u-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;padding:8px 2px;border-bottom:1px solid rgba(27,29,28,.06)}.u-row:last-child{border-bottom:0}.u-row .name{font-weight:800;color:#1c1b19;min-width:0}.u-row .meta{font-size:10.5px;color:#575242;line-height:1.4;min-width:0}.u-row .value{text-align:right;font-weight:800;white-space:nowrap}.u-row .value small{display:block;font-size:9px;color:#575242;font-weight:600}
    .u-pill{display:inline-block;font-size:9.5px;font-weight:800;border-radius:5px;padding:1px 6px;margin-left:4px;background:#e6e5df;border:1px solid #d6d4ca;color:#34322e}.u-pill.go{background:#14532d;color:#7fe6a4;border-color:#1f6d3c}.u-pill.warn{background:#6e3f15;color:#e6d27f;border-color:#ad8021}.u-pill.bad{background:#7f1d1d;color:#ea9090;border-color:#a21f1f}
    .u-table-wrap{overflow-x:auto;margin-top:7px}.u-table th:first-child,.u-table td:first-child{text-align:left}.u-table td{vertical-align:middle}.u-table .tk{font-weight:800;color:#2c69c9}
    .u-empty{font-size:11px;color:#575242;padding:8px 0}
    .u-rot-top{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:7px 0 10px}.u-rot-col{background:#f2f1ee;border:1px solid #e3e1db;border-radius:10px;padding:8px}.u-rot-col h3{font-size:11px;margin:0 0 5px}.u-rot-line{padding:5px 0;border-top:1px solid rgba(27,29,28,.06);font-size:10.5px;line-height:1.35}.u-rot-line:first-of-type{border-top:0}.u-rot-line b{font-size:11.5px}.u-rot-line span{display:block;color:#575242;margin-top:1px}
    .u-map{width:100%;height:auto;display:block;margin-top:4px}.u-map text{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif}
    .u-legend{display:flex;gap:9px;flex-wrap:wrap;font-size:9.5px;color:#575242;margin:5px 0}.u-legend i{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px}.u-legend .g{background:#19803e}.u-legend .y{background:#ad8021}.u-legend .r{background:#a21f1f}
    #u-detail .legacy-panel{display:none!important;padding-top:0!important}#u-detail .legacy-panel.u-on{display:block!important}
    #u-rotation .legacy-rotation{display:block!important;padding-top:0!important;margin-top:8px}
    @media(max-width:520px){.u-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.u-alloc{grid-template-columns:repeat(2,1fr)}.u-rot-top{grid-template-columns:1fr}.u-metric .v{font-size:19px}}
  `;
  document.head.appendChild(extraStyle);

  const topSections=qa('section',wrap);
  const byId=Object.fromEntries(topSections.map(s=>[s.id,s]));
  const nav=document.createElement('nav');nav.id='u-nav';nav.setAttribute('aria-label','V38 unified tabs');
  const tabs=[['today','今日'],['market','市場'],['rotation','資金循環'],['stocks','銘柄'],['tqqq','TQQQ'],['manage','RSI / 保有'],['detail','詳細']];
  tabs.forEach(([id,label])=>{const b=document.createElement('button');b.type='button';b.dataset.u=id;b.textContent=label;nav.appendChild(b)});
  oldNav.parentNode.insertBefore(nav,oldNav.nextSibling);
  const mkSection=(id)=>{const s=document.createElement('section');s.id='u-'+id;nav.insertAdjacentElement('afterend',s);return s};
  const uToday=mkSection('today'),uRotation=mkSection('rotation'),uStocks=mkSection('stocks'),uTqqq=mkSection('tqqq'),uManage=mkSection('manage'),uDetail=mkSection('detail');

  const detailPanels=['t-today','t-movers','t-rs','t-weekly','t-alloc','t-port','t-rules'];
  uDetail.innerHTML='<div class="u-subnav" id="u-detail-nav"></div><div id="u-detail-panels"></div>';
  const detailNav=q('#u-detail-nav'), detailHost=q('#u-detail-panels');
  const detailLabels={'t-today':'Setups','t-movers':'Movers','t-rs':'RS','t-weekly':'Weekly','t-alloc':'配分','t-port':'Core詳細','t-rules':'Rules'};
  detailPanels.forEach((id,i)=>{const p=byId[id];if(!p)return;p.classList.remove('on');p.classList.add('legacy-panel');detailHost.appendChild(p);const b=document.createElement('button');b.type='button';b.dataset.panel=id;b.textContent=detailLabels[id]||id;b.classList.toggle('on',i===0);detailNav.appendChild(b)});
  const firstDetail=q('.legacy-panel',detailHost);if(firstDetail)firstDetail.classList.add('u-on');
  detailNav.addEventListener('click',e=>{const b=e.target.closest('button[data-panel]');if(!b)return;qa('button',detailNav).forEach(x=>x.classList.toggle('on',x===b));qa('.legacy-panel',detailHost).forEach(x=>x.classList.toggle('u-on',x.id===b.dataset.panel));try{scrollTo({top:nav.offsetTop,behavior:'smooth'})}catch(_){}});
  if(byId['t-rotation']){byId['t-rotation'].classList.remove('on');byId['t-rotation'].classList.add('legacy-rotation');}

  const rootSections=()=>qa('section',wrap).filter(s=>!s.closest('#u-detail')&&!s.closest('#u-rotation'));
  function showRoute(route){
    rootSections().forEach(s=>s.classList.remove('on'));
    qa('#u-nav button').forEach(b=>b.classList.toggle('on',b.dataset.u===route));
    const target=route==='market'?byId['t-market']:q('#u-'+route);
    if(target)target.classList.add('on');
    history.replaceState(null,'',route==='today'?location.pathname:`#${route}`);
    window.scrollTo(0,nav.offsetTop);
  }
  nav.addEventListener('click',e=>{const b=e.target.closest('button[data-u]');if(b)showRoute(b.dataset.u)});

  function card(title,sub,body,cls=''){return `<div class="card ${cls}"><h2>${title}</h2>${sub?`<div class="sub">${sub}</div>`:''}${body}</div>`}
  function row(name,meta,value,small=''){return `<div class="u-row"><div><div class="name">${name}</div><div class="meta">${meta||''}</div></div><div class="value">${value}${small?`<small>${small}</small>`:''}</div></div>`}
  function allRotationRows(d){return Object.values(d?.observations?.rotation_buckets||{}).flat().filter(x=>x&&x.ticker)}
  function flowOf(r){if(r?.flow_ready&&num(r.flow_20d_pct_aum)!==null)return{pct:Number(r.flow_20d_pct_aum),usd:num(r.flow_20d_usd)};if(r?.ticker==='DRAM'&&num(r.flow_1m_pct_aum)!==null)return{pct:Number(r.flow_1m_pct_aum),usd:num(r.flow_1m_usd)};return{pct:null,usd:null}}
  function rotState(r){const p=num(r.price_score),i=num(r.internal_score),d=num(r.internal_delta20),f=flowOf(r).pct;if(p===null||i===null)return['未計算',''];if(p>=70&&i>=60&&f!==null&&f<0)return['強い・ETF純流出','warn'];if(p>=70&&i>=60)return['価格・構成株とも強い','go'];if(d!==null&&d>=10&&i>=50&&f!==null&&f>=0)return['構成株改善＋ETF純流入','warn'];if(p<45&&i<45)return['価格・構成株とも弱い','bad'];if(i<45&&f!==null&&f<0)return['構成株弱い＋ETF純流出','bad'];if(p<60&&i>=60)return['構成株が先行','warn'];if(p>=70&&i<50)return['価格先行・構成株弱め','warn'];if(f!==null&&f>0&&p<60&&i<50)return['ETF純流入が先行','warn'];return[`価格${p>=70?'強':p<45?'弱':'中立'}・構成株${i>=60?'強':i<45?'弱':'中立'}`,'']}

  function renderToday(v){
    const m=v.market||{},a=v.gross100_allocation||{},r=v.panic_reset||{},ns=v.normal_stock_sleeve||{},p=v.panic_tqqq||{};
    const mode=String(m.mode||'').toUpperCase();
    const action=mode==='ATTACK'?'通常個別株の新規エントリー可':mode==='SELECTIVE'?`選別して新規。最大 ${m.new_entry_limit??4} 枠`:mode==='DEFENSE'?'防御。通常個別株は次回寄り退避':'通常個別株の新規エントリー停止';
    const modeTone=mode==='ATTACK'?'go':mode==='SELECTIVE'?'warn':mode==='DEFENSE'?'bad':'warn';
    const cash=Math.max(0,100-(num(a.gross_allocated_pct)??0));
    uToday.innerHTML=`<div class="u-call"><div class="ey">TODAY'S ACTION · ${esc(v.asof||'—')}</div><div class="main">${esc(action)}</div><div class="sub">NQSAR ${esc(m.nqsar||'—')} / Breadth50 ${fmt(m.breadth50,1)}% / Market Mode <span class="u-pill ${modeTone}">${esc(modeJa(mode))}</span></div><div class="u-alloc"><div><span>TQQQ</span><b>${fmt(a.tqqq_allocated_pct??v.normal_tqqq?.underlying_target_pct,0)}%</b></div><div><span>通常株</span><b>${fmt(a.normal_stock_allocated_pct??ns.portfolio_desired_pct,0)}%</b></div><div><span>RSI Reset</span><b>${fmt(a.reset_allocated_pct??r.desired_pct,1)}%</b></div><div><span>Cash</span><b>${fmt(cash,0)}%</b></div></div></div>`+
      card('今日の状態','正式V38 live。Rotationは売買許可や正式順位へ加点しません。',`<div class="u-grid"><div class="u-metric"><div class="k">Market Mode</div><div class="v">${esc(modeJa(mode))}</div><div class="n">${esc(m.reason||'')}</div></div><div class="u-metric"><div class="k">新規枠</div><div class="v">${m.new_entry_limit??'—'}</div><div class="n">通常個別株</div></div><div class="u-metric"><div class="k">TQQQ</div><div class="v">${fmt(a.tqqq_allocated_pct??p.underlying_target_pct,0)}%</div><div class="n">Panic ${p.active?'ACTIVE':'inactive'}</div></div><div class="u-metric"><div class="k">RSI Reset</div><div class="v">${r.position_count??0}</div><div class="n">監視 ${r.monitor_summary?.watch_count??0}銘柄</div></div></div>`)+
      card('次に見るもの','「WHEN → WHERE → WHAT」の順で確認。',`${row('① WHEN｜市場','NQSAR + Breadth',`${esc(modeJa(mode))} / ${m.new_entry_limit??'—'}枠`)}${row('② WHERE｜資金循環','Theme56 Price / Internal / ETF純資金','資金循環タブ')}${row('③ WHAT｜正式候補','V38 RS189 + strict LOO Theme','銘柄タブ')}`);
  }

  function renderStocks(v){
    const m=v.market||{},mode=String(m.mode||'').toUpperCase(),rows=(v.candidates||[]).filter(x=>x.eligibility==='ELIGIBLE');
    const key=mode==='ATTACK'?'attack_watch_rank':mode==='SELECTIVE'?'selective_watch_rank':'attack_watch_rank';
    const sorted=[...rows].filter(x=>num(x[key])!==null).sort((a,b)=>Number(a[key])-Number(b[key]));
    const max=mode==='ATTACK'?12:mode==='SELECTIVE'?4:12;
    const body=sorted.slice(0,Math.max(max,20)).map(x=>`<tr><td class="tk">${esc(x.ticker)}</td><td>${x[key]??'—'}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${fmt(x.peer_theme_score,1)}</td><td>${esc(statusJa(x.entry_status))}</td></tr>`).join('');
    uStocks.innerHTML=card('正式V38候補',`${modeJa(mode)} / Eligibility通過 ${rows.length}銘柄。${mode==='STOP'||mode==='DEFENSE'?'現在は買いシグナルではなく再開時の監視順位です。':''}`,`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>順位</th><th>RS189</th><th>RS63</th><th>Theme</th><th>Theme強度</th><th>扱い</th></tr></thead><tbody>${body||'<tr><td colspan="7">候補なし</td></tr>'}</tbody></table></div>`)+
      card('正式条件','通常個別株のEligibility。',`<div class="u-grid"><div class="u-metric"><div class="k">Price</div><div class="v">≥ $5</div></div><div class="u-metric"><div class="k">DDV</div><div class="v">≥ $10M</div></div><div class="u-metric"><div class="k">RS189 / RS63</div><div class="v">≥ 85</div></div><div class="u-metric"><div class="k">Trend</div><div class="v">50&gt;200</div><div class="n">Close&gt;200</div></div></div>`);
  }

  function renderTqqq(v){
    const nrm=v.normal_tqqq||{},p=v.panic_tqqq||{},a=v.gross100_allocation||{};
    const seedV=num(p.vix_close)!==null&&Number(p.vix_close)>=23, seedD=num(p.qqq_sma50_atr_deviation)!==null&&Number(p.qqq_sma50_atr_deviation)<=-0.5, seedDD=num(p.qqq_drawdown10)!==null&&Number(p.qqq_drawdown10)<=-0.02;
    uTqqq.innerHTML=`<div class="u-call"><div class="ey">TQQQ · ${esc(v.asof||'—')}</div><div class="main">現在 ${fmt(a.tqqq_allocated_pct??p.underlying_target_pct??nrm.underlying_target_pct,0)}%</div><div class="sub">通常 CURRENT30 ${fmt(nrm.underlying_target_pct,0)}% / Panic F80 ${p.active?'ACTIVE':'inactive'}</div></div>`+
      card('Panic Seed / Trigger','市場全体の恐怖を買う別エンジン。NQSARをPanic F80のHard Gateにはしません。',`${row('VIX ≥ 23',`現在 ${fmt(p.vix_close,2)}`,seedV?'<span class="u-pill go">成立</span>':'<span class="u-pill">未成立</span>')}${row('QQQ SMA50乖離 ≤ -0.5ATR',`現在 ${fmt(p.qqq_sma50_atr_deviation,2)} ATR`,seedD?'<span class="u-pill go">成立</span>':'<span class="u-pill">未成立</span>')}${row('QQQ 10日DD ≤ -2%',`現在 ${pct((num(p.qqq_drawdown10)??0)*100,2)}`,seedDD?'<span class="u-pill go">成立</span>':'<span class="u-pill">未成立</span>')}${row('4H RSI14 ≤ 30','Seed後30営業日以内',`${fmt(p.rsi4h,1)}`,p.touch30_today?'本日Touch':'未Touch')}${row('MC57','Entry ≥20 / Active Exit <20',fmt(p.mc57,1))}`)+
      card('配分ルール','GROSS100でReset・TQQQ・通常株を競合処理。',`<div class="u-grid"><div class="u-metric"><div class="k">通常TQQQ</div><div class="v">${fmt(nrm.normal_exposure_pct,0)}%</div><div class="n">CURRENT30</div></div><div class="u-metric"><div class="k">Panic Floor</div><div class="v">${fmt(p.floor_pct_when_active,0)}%</div><div class="n">最大10営業日</div></div><div class="u-metric"><div class="k">現在Target</div><div class="v">${fmt(p.underlying_target_pct,0)}%</div></div><div class="u-metric"><div class="k">MC57</div><div class="v">${fmt(p.mc57,1)}</div></div></div>`);
  }

  function renderManage(v){
    const r=v.panic_reset||{},ns=v.normal_stock_sleeve||{};
    const monitors=(r.monitor||[]).slice().sort((a,b)=>(num(a.distance_to_30)??999)-(num(b.distance_to_30)??999));
    const mrows=monitors.slice(0,18).map(x=>`<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td>${esc(statusJa(x.status))}</td><td>${x.signal_window_days_left??'—'}</td><td>${x.current_theme_rs63_top3?'Top3':'—'}</td></tr>`).join('');
    const pos=(ns.positions||[]).map(x=>{const ret=num(x.close)!==null&&num(x.entry_price)!==null?(Number(x.close)/Number(x.entry_price)-1)*100:null;return `<tr><td class="tk">${esc(x.symbol)}</td><td>${esc(x.entry_date||'—')}</td><td>${fmt(x.entry_price,2)}</td><td>${fmt(x.close,2)}</td><td class="${toneClass(ret)}">${pct(ret,1)}</td><td>${x.partial_done?'済':'未'}</td></tr>`}).join('');
    uManage.innerHTML=card('RSI30 Panic Reset',`別スリーブ ${r.strategy||''} / 1銘柄 ${fmt(r.slot_pct,1)}% / 最大 ${r.max_positions??4}銘柄。接近帯は表示用で売買ルールではありません。`,`<div class="u-grid"><div class="u-metric"><div class="k">Active</div><div class="v">${r.position_count??0}</div></div><div class="u-metric"><div class="k">RSI30到達待ち</div><div class="v">${r.monitor_summary?.touched_wait_rise??0}</div></div><div class="u-metric"><div class="k">5pt以内</div><div class="v">${r.monitor_summary?.within_5pt??0}</div></div><div class="u-metric"><div class="k">監視</div><div class="v">${r.monitor_summary?.watch_count??0}</div></div></div><div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Theme</th><th>RSI14</th><th>状態</th><th>残り</th><th>Theme内</th></tr></thead><tbody>${mrows||'<tr><td colspan="6">監視なし</td></tr>'}</tbody></table></div>`)+
      card('通常個別株 保有',`${ns.position_count??0}銘柄 / Portfolio ${fmt(ns.portfolio_desired_pct,1)}%。`,`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>銘柄</th><th>Entry日</th><th>Entry</th><th>Close</th><th>損益</th><th>+24%利確</th></tr></thead><tbody>${pos||'<tr><td colspan="6">保有なし</td></tr>'}</tbody></table></div>`);
  }

  function renderRotation(rot,ctx){
    if(!rot){uRotation.innerHTML=card('資金循環','Rotationデータを取得できませんでした。','<div class="u-empty">既存Command CenterのRotation詳細は下に残しています。</div>');if(byId['t-rotation'])uRotation.appendChild(byId['t-rotation']);return}
    const rows=allRotationRows(rot);rows.forEach(r=>r.__state=rotState(r));
    const strong=rows.filter(r=>num(r.price_score)>=70&&num(r.internal_score)>=60).sort((a,b)=>(num(b.price_score)||0)-(num(a.price_score)||0)).slice(0,5);
    const improving=rows.filter(r=>num(r.internal_delta20)!==null&&Number(r.internal_delta20)>=10).sort((a,b)=>Number(b.internal_delta20)-Number(a.internal_delta20)).slice(0,5);
    const bad=rows.filter(r=>num(r.internal_delta20)!==null&&Number(r.internal_delta20)<=-10).sort((a,b)=>Number(a.internal_delta20)-Number(b.internal_delta20)).slice(0,5);
    const one=(r,metric)=>{const f=flowOf(r),[st,t]=r.__state;const val=metric==='delta'?pct(r.internal_delta20,1):metric==='flow'?pct(f.pct,1):`P${fmt(r.price_score,0)} / I${fmt(r.internal_score,0)}`;return `<div class="u-rot-line"><b>${esc(etf(r.ticker))}</b> <span class="u-pill ${t}">${esc(st)}</span><span>${val}</span></div>`};
    const flowRows=rows.filter(r=>flowOf(r).pct!==null).sort((a,b)=>Number(flowOf(b).pct)-Number(flowOf(a).pct));
    const flowTable=[...flowRows.slice(0,7),...flowRows.slice(-7).reverse()].map(r=>{const f=flowOf(r),[st,t]=r.__state;return `<tr><td class="tk">${esc(r.ticker)}</td><td>${esc(ETF[r.ticker]||'')}</td><td class="${toneClass(f.pct)}">${pct(f.pct,2)}</td><td>${money(f.usd)}</td><td>${fmt(r.price_score,0)}</td><td>${fmt(r.internal_score,0)}</td><td><span class="u-pill ${t}">${esc(st)}</span></td></tr>`}).join('');
    const allSorted=[...rows].sort((a,b)=>(num(b.price_score)||0)-(num(a.price_score)||0));
    const themeTable=allSorted.map(r=>{const f=flowOf(r),[st,t]=r.__state;return `<tr><td class="tk">${esc(r.ticker)}</td><td>${esc(ETF[r.ticker]||r.label||'')}</td><td>${fmt(r.price_score,0)}</td><td>${fmt(r.internal_score,0)}</td><td class="${toneClass(r.internal_delta20)}">${pct(r.internal_delta20,1)}</td><td class="${toneClass(f.pct)}">${pct(f.pct,1)}</td><td><span class="u-pill ${t}">${esc(st)}</span></td></tr>`}).join('');
    const points=rows.filter(r=>num(r.price_score)!==null&&num(r.internal_score)!==null);
    const W=620,H=360,L=42,R=14,T=15,B=34,iw=W-L-R,ih=H-T-B,sx=x=>L+Math.max(0,Math.min(100,x))/100*iw,sy=y=>T+ih-Math.max(0,Math.min(100,y))/100*ih;
    let svg=`<svg class="u-map" viewBox="0 0 ${W} ${H}" role="img" aria-label="Theme56 Rotation Map"><rect x="${L}" y="${T}" width="${iw}" height="${ih}" rx="8" fill="#f2f1ee" stroke="#e3e1db"/><line x1="${sx(50)}" x2="${sx(50)}" y1="${T}" y2="${T+ih}" stroke="#d6d4ca"/><line x1="${L}" x2="${L+iw}" y1="${sy(50)}" y2="${sy(50)}" stroke="#d6d4ca"/>`;
    [0,25,50,75,100].forEach(v=>{svg+=`<text x="${sx(v)}" y="${H-10}" fill="#575242" font-size="9" text-anchor="middle">${v}</text><text x="${L-7}" y="${sy(v)+3}" fill="#575242" font-size="9" text-anchor="end">${v}</text>`});
    points.forEach(r=>{const [st,t]=r.__state,c=t==='go'?'#19803e':t==='bad'?'#a21f1f':t==='warn'?'#ad8021':'#77736a';svg+=`<g><circle cx="${sx(r.price_score)}" cy="${sy(r.internal_score)}" r="8" fill="${c}" fill-opacity=".78"><title>${esc(etf(r.ticker))} / ${esc(st)}</title></circle><text x="${sx(r.price_score)}" y="${sy(r.internal_score)+3}" fill="#f2f1ee" font-size="6.5" font-weight="800" text-anchor="middle">${esc(r.ticker)}</text></g>`});
    svg+=`<text x="${L+iw/2}" y="${H-1}" fill="#575242" font-size="10" text-anchor="middle">ETF価格の強さ →</text><text x="10" y="${T+ih/2}" fill="#575242" font-size="10" text-anchor="middle" transform="rotate(-90 10 ${T+ih/2})">構成株の強さ →</text></svg>`;
    let leaders='';
    const contexts=ctx?.industry_context||[];
    contexts.filter(x=>(x.existing_emerging_or_leading_leaders_in_full_intersection||x.existing_emerging_or_leading_leaders_in_top15_intersection||[]).length).slice(0,10).forEach(x=>{const ls=x.existing_emerging_or_leading_leaders_in_full_intersection||x.existing_emerging_or_leading_leaders_in_top15_intersection||[];leaders+=`<div class="u-row"><div><div class="name">${esc(etf(x.etf))}</div><div class="meta">${ls.slice(0,6).map(s=>`${esc(s.symbol)}${s.role?` (${esc(s.role==='PIONEER'?'先導':s.role==='LEADER'?'主導':s.role)})`:''}`).join(' · ')}</div></div><div class="value">${ls.length}<small>Leadership一致</small></div></div>`});
    uRotation.innerHTML=card('資金循環','WHEREの観測。価格・構成株・ETF純資金を分離して表示し、正式V38順位には加点しません。',`<div class="u-rot-top"><div class="u-rot-col"><h3>現在強い</h3>${strong.map(r=>one(r,'state')).join('')||'<div class="u-empty">なし</div>'}</div><div class="u-rot-col"><h3>改善中</h3>${improving.map(r=>one(r,'delta')).join('')||'<div class="u-empty">なし</div>'}</div><div class="u-rot-col"><h3>悪化中</h3>${bad.map(r=>one(r,'delta')).join('')||'<div class="u-empty">なし</div>'}</div></div>`)+
      card('Rotation Map','横＝ETF価格、縦＝構成株の強さ。',`<div class="u-legend"><span><i class="g"></i>強い</span><span><i class="y"></i>注意/先行</span><span><i class="r"></i>弱い</span></div>${svg}`)+
      card('ETF純資金','ETFの設定−解約。売買代金ではありません。上位流入＋上位流出。',`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>ETF</th><th>Theme</th><th>純資金/AUM</th><th>USD</th><th>Price</th><th>Internal</th><th>状態</th></tr></thead><tbody>${flowTable}</tbody></table></div>`)+
      card('先導株 / 主導株','現在ETF構成 × 既存Leadershipの一致。Rotation独自の銘柄ランキングではありません。',leaders||'<div class="u-empty">一致データなし</div>')+
      card('Theme56','全テーマを同じ粒度で比較。',`<div class="u-table-wrap"><table class="u-table"><thead><tr><th>ETF</th><th>Theme</th><th>Price</th><th>Internal</th><th>20日変化</th><th>ETF純資金</th><th>状態</th></tr></thead><tbody>${themeTable}</tbody></table></div>`);
    if(byId['t-rotation']){const d=document.createElement('details');d.className='card';d.innerHTML='<summary style="font-size:12px;font-weight:800;cursor:pointer">既存Command Center Rotation 詳細</summary>';d.appendChild(byId['t-rotation']);uRotation.appendChild(d)}
  }

  const V38_URL='v38-live-state.json';
  const ROT_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const CTX_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';
  let v38=null,rot=null,ctx=null;
  try{v38=await fetch(V38_URL+'?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()})}catch(e){console.error('V38 unified load',e)}
  try{[rot,ctx]=await Promise.all([fetch(ROT_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null),fetch(CTX_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null)])}catch(e){console.error('Rotation unified load',e)}

  if(v38){renderToday(v38);renderStocks(v38);renderTqqq(v38);renderManage(v38)}else{
    const msg=card('V38 live','データ取得に失敗しました。','<div class="u-empty">既存Command Centerはそのまま使用できます。</div>');uToday.innerHTML=uStocks.innerHTML=uTqqq.innerHTML=uManage.innerHTML=msg;
  }
  renderRotation(rot,ctx);
  const hash=String(location.hash||'').replace('#','');
  showRoute(tabs.some(x=>x[0]===hash)?hash:'today');
})();

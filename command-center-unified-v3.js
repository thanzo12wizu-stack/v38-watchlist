'use strict';
(async function unifiedV3(){
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const num=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
  const fmt=(v,d=1)=>num(v)?Number(v).toFixed(d):'—';
  const pct=(v,d=1)=>num(v)?`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`:'—';
  const modeJa=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';
  const stateJa=s=>({CURRENT_STRENGTH:'強い',EARLY_ROTATION_WATCH:'改善先行',INTERNAL_LEAD:'構成株先行',FLOW_INTERNAL_DIVERGENCE:'資金/内部乖離',DISTRIBUTION_WARNING:'分配警戒',INTERNAL_WEAK_FLOW_OUT:'内部弱い・流出',WEAK_FLOWOUT:'弱い・流出',WEAK_BREAKDOWN:'弱い',BREAKDOWN:'崩れ',MIXED_HOLD:'まちまち'})[String(s||'').toUpperCase()]||String(s||'—').replaceAll('_',' ');
  const pill=(t,cls='')=>`<span class="pill ${cls}">${esc(t)}</span>`;
  const card=(title,sub,body)=>`<div class="card"><h2>${title}</h2>${sub?`<div class="sub">${sub}</div>`:''}${body}</div>`;
  const table=(heads,rows)=>`<div style="overflow-x:auto"><table class="ptab"><thead><tr>${heads.map((h,i)=>`<th${i===0?' class="l"':''}>${h}</th>`).join('')}</tr></thead><tbody>${rows||`<tr><td colspan="${heads.length}">表示対象なし</td></tr>`}</tbody></table></div>`;
  const alert=(text,bad=false)=>`<div class="${bad?'todayact ta-red':'skip-note'}">${text}</div>`;

  const nav=q('nav#tabs');
  const wrap=q('.wrap')||document.body;
  if(!nav||typeof window.tab!=='function'){
    console.error('UNIFIED_V3: native Command Center navigation unavailable');
    return;
  }

  // Unified is a view-layer only. Keep all legacy sections and functions in DOM,
  // but expose only the seven native-looking top tabs.
  const legacyAnchors=qa('a.tabx',nav);
  legacyAnchors.forEach(a=>{a.dataset.v3Legacy='1';a.style.display='none';a.classList.remove('on');a.setAttribute('aria-selected','false');});

  const ids=['t-v38-today','t-market','t-v38-rotation','t-v38-stocks','t-v38-tqqq','t-v38-holdings','t-v38-detail'];
  const labels=['今日','市場','資金循環','銘柄','TQQQ','保有 / RSI','詳細'];
  const visibleTabs=[];
  ids.forEach((id,i)=>{
    const a=document.createElement('a');
    a.role='button';a.tabIndex=0;a.className='tabx';a.textContent=labels[i];a.dataset.v3='1';a.dataset.target=id;
    a.onclick=()=>window.tab(id,a);
    a.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();a.click();}};
    nav.appendChild(a);visibleTabs.push(a);
  });

  const makeSection=id=>{
    let s=q('#'+id);
    if(!s){s=document.createElement('section');s.id=id;wrap.appendChild(s);}
    s.classList.remove('on');
    return s;
  };
  const today=makeSection('t-v38-today');
  const rotation=makeSection('t-v38-rotation');
  const stocks=makeSection('t-v38-stocks');
  const tqqq=makeSection('t-v38-tqqq');
  const holdings=makeSection('t-v38-holdings');
  const detail=makeSection('t-v38-detail');

  // Move the existing actual-holdings card as-is. Do not recreate the holdings UI.
  const hldList=q('#hldList');
  const hldCard=hldList?.closest('.card')||null;
  if(hldCard)holdings.appendChild(hldCard);

  const actualHoldings=()=>{
    try{
      if(typeof window.hldLoad!=='function')return {ok:false,items:[],error:'保有記録の読込機能がありません'};
      const items=window.hldLoad().filter(x=>x&&x.status!=='closed');
      return {ok:true,items};
    }catch(e){return {ok:false,items:[],error:String(e?.message||e)}};
  };

  let v=null,rot=null;
  try{v=await fetch('v38-live-state.json?v='+Date.now(),{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('V38 '+r.status);return r.json();});}catch(e){console.error(e);}
  try{rot=await fetch('https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json',{cache:'no-store'}).then(r=>r.ok?r.json():null);}catch(e){console.error(e);}

  const market=v?.market||{};
  const mode=String(market.mode||'').toUpperCase();
  const normal=v?.normal_tqqq||{};
  const panic=v?.panic_tqqq||{};
  const reset=v?.panic_reset||{};
  const rank=v?.ranking||{};
  const candidates=(v?.candidates||[]).filter(x=>x&&x.eligibility==='ELIGIBLE');
  const byTicker=Object.fromEntries(candidates.map(x=>[String(x.ticker||''),x]));
  const normalReady=/READY/i.test(String(normal.status||''))&&!/DATA REQUIRED|ERROR|FAIL/i.test(String(normal.status||''));
  const panicReady=/READY/i.test(String(panic.status||''))&&!/DATA REQUIRED|ERROR|FAIL/i.test(String(panic.status||''));
  const resetReady=/READY/i.test(String(reset.status||''))&&!/DATA REQUIRED|ERROR|FAIL/i.test(String(reset.status||''));
  const ah=actualHoldings();

  const formalResetSignals=(reset.monitor||[]).filter(x=>x?.status==='SIGNAL_TODAY_NEXT_OPEN');
  const resetWatch=(reset.monitor||[]).filter(x=>x&&x.status!=='SIGNAL_TODAY_NEXT_OPEN'&&x.status!=='ACTIVE_POSITION')
    .sort((a,b)=>(Number(a.distance_to_30??999)-Number(b.distance_to_30??999))).slice(0,8);

  function normalAction(){
    if(!v)return ['判定不可','V38 live stateを取得できません'];
    if(mode==='DEFENSE')return ['通常株は退避','NQSAR Red。通常個別株は次回寄りで全退避。'];
    if(mode==='STOP')return ['通常株は新規買付しない',`${market.nqsar||'—'} / Breadth50 ${fmt(market.breadth50,1)}%。既存は個別Exitまで継続。`];
    if(mode==='SELECTIVE')return [`通常株は選別して最大${market.new_entry_limit??4}枠`,`Blue/Green + Breadth50 50〜60%。RS189中心。`];
    if(mode==='ATTACK')return [`通常株は新規可・最大${market.new_entry_limit??12}枠`,`Blue/Green + Breadth50 60%以上。正式V38順位を使用。`];
    return ['通常株 判定不可',market.reason||'Market Modeを確認できません'];
  }
  const [mainAction,mainReason]=normalAction();
  const tqTarget=normalReady&&num(normal.underlying_target_pct)?`${fmt(normal.underlying_target_pct,0)}%`:'判定不可';

  // Keep the native Today card DOM alive for the base dashboard scripts, but hide it in
  // the unified view. The concise audited Today section below replaces it visually.
  const ta=q('#taCard');
  if(ta)ta.style.display='none';

  function renderToday(){
    if(!v){today.innerHTML=card('今日の判断','正式V38 stateを取得できません。',alert('<b>DATA REQUIRED</b>：売買判断を表示しません。',true));return;}
    const dataWarn=!market.coverage_ok?alert('<b>Breadth coverage不足。</b> 通常株の新規判断はfail-closedです。',true):'';
    const holdWarn=ah.ok?'':alert(`<b>実保有を取得できません。</b> ${esc(ah.error||'')}。0件とは扱いません。`,true);
    const resetBody=resetReady?(formalResetSignals.length
      ?formalResetSignals.map(x=>`<div><b>${esc(x.symbol)}</b>｜${esc(x.theme||'—')}｜RSI ${fmt(x.current_rsi14,1)}｜<b>翌営業日寄りEntry</b></div>`).join('')
      :'<b>正式Reset Signalなし</b>'):'<b>Reset DATA REQUIRED</b>';
    today.innerHTML=dataWarn+holdWarn+
      card('今日やること',`分析基準日 ${esc(v.asof||'—')}`,`<div style="font-size:24px;font-weight:800;margin:5px 0 3px">${esc(mainAction)}</div><div class="sub">${esc(mainReason)}</div>`)+
      card('TQQQ',null,`<div style="font-size:22px;font-weight:800">${esc(tqTarget)}</div><div class="sub">${panicReady?(panic.active?'Panic F80 稼働中':'Panic F80 非発動'):'Panic判定 DATA REQUIRED'}。詳細はTQQQタブ。</div>`)+
      card('RSI Reset｜正式Signal',`接近候補はここに含めません。`,resetBody)+
      card('実保有',`この端末の既存Dashboard保有記録。`,ah.ok?`<b>${ah.items.length}件</b>。保有 / RSIタブで確認。`:'<b>取得エラー</b>。');
  }

  function renderStocks(){
    if(!v){stocks.innerHTML=card('銘柄','V38 live stateを取得できません。',alert('<b>DATA REQUIRED</b>',true));return;}
    if(mode==='STOP'||mode==='DEFENSE'){
      const sel=(rank.selective_reopen_top4||[]).map(String);
      const atk=(rank.attack_reopen_top12||[]).map(String);
      const srows=sel.map((tk,i)=>{const x=byTicker[tk]||{};return `<tr><td><b>${esc(tk)}</b></td><td>${x.selective_watch_rank??i+1}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td></tr>`;}).join('');
      const arows=atk.map((tk,i)=>{const x=byTicker[tk]||{};return `<tr><td><b>${esc(tk)}</b></td><td>${x.attack_watch_rank??i+1}</td><td>${fmt(x.attack_watch_score,1)}</td><td>${fmt(x.rs189,1)}</td><td>${esc(x.peer_theme||'—')}</td></tr>`;}).join('');
      stocks.innerHTML=card('今は買わない',`${modeJa(mode)}。下は復帰した場合の監視順位で、現在の買いシグナルではありません。`,'')+
        card('SELECTIVEへ復帰した場合｜TOP4','Blue/Green + Breadth50 50〜<60%。RS189順位。',table(['銘柄','順位','RS189','RS63','Theme'],srows))+
        card('ATTACKへ復帰した場合｜TOP12','Blue/Green + Breadth50 ≥60%。Stock70 + strict LOO Theme30。',table(['銘柄','順位','V38 Score','RS189','Theme'],arows));
      return;
    }
    const rows=[...candidates].filter(x=>num(x.final_rank)).sort((a,b)=>Number(a.final_rank)-Number(b.final_rank)).slice(0,15);
    const body=rows.map(x=>`<tr><td><b>${esc(x.ticker)}</b></td><td>${x.final_rank}</td><td>${fmt(x.attack_score??x.attack_watch_score,1)}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${esc(x.entry_status==='NEXT_OPEN_WHEN_CAPACITY'?'空き枠ならEntry候補':'候補')}</td></tr>`).join('');
    stocks.innerHTML=card('正式V38候補',`${modeJa(mode)} / 新規枠上限 ${market.new_entry_limit??'—'}。順位上位＝自動注文ではありません。`,table(['銘柄','順位','V38','RS189','RS63','Theme','扱い'],body));
  }

  function renderTqqq(){
    if(!v){tqqq.innerHTML=card('TQQQ','V38 live stateを取得できません。',alert('<b>DATA REQUIRED</b>',true));return;}
    const statusWarn=(!normalReady||!panicReady)?alert(`<b>TQQQ判定データ不足。</b> Normal ${esc(normal.status||'—')} / Panic ${esc(panic.status||'—')}。0%・inactiveとは扱いません。`,true):'';
    const seedValid=panicReady&&num(panic.seed_age_sessions)&&Number(panic.seed_age_sessions)<=30;
    const seedTxt=panicReady?(seedValid?'有効':'なし / 期限外'):'判定不可';
    const panicTxt=panicReady?(panic.active?'F80 ACTIVE':'非発動'):'判定不可';
    const body=table(['項目','現在'],
      `<tr><td>現在のTQQQ目標</td><td><b>${esc(tqTarget)}</b></td></tr>`+
      `<tr><td>Panic</td><td><b>${esc(panicTxt)}</b></td></tr>`+
      `<tr><td>Seed</td><td><b>${esc(seedTxt)}</b></td></tr>`+
      `<tr><td>QQQ 4H RSI14</td><td><b>${panicReady?fmt(panic.rsi4h,1):'—'}</b></td></tr>`);
    const condRows=`<tr><td>VIX Close ≥23</td><td>${panicReady?fmt(panic.vix_close,2):'—'}</td><td>${panicReady&&num(panic.vix_close)?(Number(panic.vix_close)>=23?'成立':'未成立'):'—'}</td></tr>`+
      `<tr><td>QQQ SMA50乖離 ≤−0.5ATR</td><td>${panicReady?fmt(panic.qqq_sma50_atr_deviation,2):'—'}</td><td>${panicReady&&num(panic.qqq_sma50_atr_deviation)?(Number(panic.qqq_sma50_atr_deviation)<=-0.5?'成立':'未成立'):'—'}</td></tr>`+
      `<tr><td>QQQ 10日DD ≤−2%</td><td>${panicReady&&num(panic.qqq_drawdown10)?pct(Number(panic.qqq_drawdown10)*100,2):'—'}</td><td>${panicReady&&num(panic.qqq_drawdown10)?(Number(panic.qqq_drawdown10)<=-0.02?'成立':'未成立'):'—'}</td></tr>`;
    tqqq.innerHTML=statusWarn+card('TQQQ',`通常CURRENT30とPanic F80を分けて表示。`,body)+
      card('Panic Seed｜3条件AND','Seed後30営業日以内にQQQ 4H RSI14≤30 TOUCH、MC57≥20で発動。',table(['条件','現在値','状態'],condRows))+
      card('Trigger / Exit',null,`<div class="sub">4H RSI14 ${panicReady?fmt(panic.rsi4h,1):'—'} ／ MC57 ${panicReady?fmt(panic.mc57,1):'—'} ／ Active ${panicReady?(panic.active?'YES':'NO'):'—'} ／ Held ${panicReady?(panic.held_sessions??'—'):'—'}日</div>`);
  }

  function rotRow(x){
    const flow=x?.flow_ready&&num(x.flow_20d_pct_aum)?pct(x.flow_20d_pct_aum,1):'—';
    const cls=String(x?.state||'').includes('WEAK')||String(x?.state||'').includes('BREAKDOWN')||String(x?.state||'').includes('DISTRIBUTION')?'neg':String(x?.state||'').includes('STRENGTH')?'pos':'warnc';
    return `<tr><td><b>${esc(x?.ticker||'—')}</b><div class="sub">${esc(x?.label||'')}</div></td><td class="${cls}">${esc(stateJa(x?.state))}</td><td>${fmt(x?.ret_20d_pct,1)}%</td><td>${fmt(x?.internal_score,0)}</td><td>${flow}</td></tr>`;
  }
  function renderRotation(){
    if(!rot){rotation.innerHTML=card('資金循環','Rotationデータを取得できません。',alert('<b>DATA REQUIRED</b>。V38正式順位には影響しません。',true));return;}
    const flow=rot.observations?.flow||{};
    const leaders=(flow.leaders||[]).slice(0,8);
    const laggards=(flow.laggards||[]).slice(0,8);
    const align=rot.input_alignment||{};
    const alignWarn=align.status&&align.status!=='OK'?alert(`<b>基準日が異なります。</b> Rotation ${esc(align.rotation_asof||rot.asof||'—')} / 参照V38 ${esc(align.v38_asof||'—')}。資金循環はWHERE観測のみで、正式V38順位や売買許可を上書きしません。`):'';
    rotation.innerHTML=alignWarn+
      card('強い / 流入側',`Theme56観測。売買シグナルではありません。`,table(['Theme','状態','20日騰落','構成株','20日純資金/AUM'],leaders.map(rotRow).join('')))+
      card('弱い / 流出側','悪化・流出の観測。Rotation単独では強制売却しません。',table(['Theme','状態','20日騰落','構成株','20日純資金/AUM'],laggards.map(rotRow).join('')));
  }

  function renderHoldings(){
    // Existing holdings card was moved above. Add only V38 Reset information.
    const resetCard=document.createElement('div');resetCard.className='card';
    const signalRows=formalResetSignals.map(x=>`<tr><td><b>${esc(x.symbol)}</b></td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td><b>翌営業日寄りEntry</b></td></tr>`).join('');
    const watchRows=resetWatch.map(x=>`<tr><td>${esc(x.symbol||'—')}</td><td>${esc(x.theme||'—')}</td><td>${fmt(x.current_rsi14,1)}</td><td>${num(x.distance_to_30)?fmt(x.distance_to_30,1)+'pt':'—'}</td><td>監視のみ</td></tr>`).join('');
    resetCard.innerHTML=`<h2>RSI Reset</h2><div class="sub">正式Signalと接近監視を分離。接近＝買いではありません。</div>`+
      (resetReady?table(['正式Signal','Theme','RSI14','行動'],signalRows):alert('<b>Reset DATA REQUIRED</b>',true))+
      `<div class="sub" style="margin-top:10px"><b>接近監視</b>｜RSI14≤30到達後の初回上昇＋Theme内RS63 Top3確認が正式Entry条件。</div>`+
      table(['銘柄','Theme','RSI14','30まで','状態'],watchRows);
    holdings.appendChild(resetCard);
    if(!hldCard){holdings.insertAdjacentHTML('afterbegin',card('実保有','既存Dashboardの保有カードを取得できません。',alert('<b>取得エラー</b>',true)));}
  }

  function openLegacy(id){
    const a=legacyAnchors.find(x=>(x.getAttribute('onclick')||'').includes(`'${id}'`)||(x.getAttribute('onclick')||'').includes(`\"${id}\"`));
    if(!a)return;
    window.tab(id,a);
    visibleTabs.forEach(x=>{const on=x.dataset.target==='t-v38-detail';x.classList.toggle('on',on);x.setAttribute('aria-selected',on?'true':'false');});
  }
  window.__unifiedV3OpenLegacy=openLegacy;
  function renderDetail(){
    detail.innerHTML=card('詳細','普段の運用判断には不要な観測情報。必要な時だけ開く。',
      `<div style="display:flex;flex-wrap:wrap;gap:7px;margin-top:8px">`+
      `<button class="memx" onclick="__unifiedV3OpenLegacy('t-today')">Setups｜EPS・VWAP・GEX・Patterns</button>`+
      `<button class="memx" onclick="__unifiedV3OpenLegacy('t-movers')">Movers</button>`+
      `<button class="memx" onclick="__unifiedV3OpenLegacy('t-rs')">RS</button>`+
      `<button class="memx" onclick="__unifiedV3OpenLegacy('t-weekly')">Weekly</button>`+
      `</div>`)+
      card('V38監査',`正式な計算状態・ルールを確認する場合。`,`<a href="command-center-v38.html" target="_blank" rel="noopener">監査版V38を開く →</a><div class="sub" style="margin-top:6px">戦略モデル配分や仮想保有は通常画面には出しません。</div>`);
  }

  renderToday();renderStocks();renderTqqq();renderRotation();renderHoldings();renderDetail();

  // Keep native market section untouched and visible as the 市場 tab.
  // Start on Today unless a supported hash was explicitly requested.
  const hash=location.hash.replace('#','');
  const hashMap={today:'t-v38-today',market:'t-market',rotation:'t-v38-rotation',stocks:'t-v38-stocks',tqqq:'t-v38-tqqq',holdings:'t-v38-holdings',detail:'t-v38-detail'};
  const start=hashMap[hash]||'t-v38-today';
  const a=visibleTabs.find(x=>x.dataset.target===start)||visibleTabs[0];
  window.tab(start,a);
})();

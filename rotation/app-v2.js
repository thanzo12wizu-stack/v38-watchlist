'use strict';

const DATA_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
const CONTEXT_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';
const LIVE_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/v38-live-state.json';
const SHARE_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/command-center_share.html';

const ETF={CIBR:'サイバー',IGV:'ソフトウェア',WCLD:'クラウド・SaaS',OIH:'油田サービス',DRAM:'メモリ',SKYY:'クラウド基盤',XES:'油田装置',AIQ:'AI',ARKW:'次世代ネット',BOTZ:'ロボティクス',SMH:'半導体',HYDR:'水素',XOP:'石油探査',MOO:'農業',SOXX:'半導体装置',DRIV:'EV・自動運転',XSD:'半導体EW',QTUM:'量子・次世代',SLX:'鉄鋼',BLOK:'ブロックチェーン',XME:'金属・鉱業',GRID:'スマートグリッド',IAI:'証券・取引所',URA:'ウラン',NLR:'原子力',DTCR:'データセンター',FAN:'風力',ICLN:'クリーンEN',SHLD:'防衛テック',LIT:'リチウム電池',WOOD:'林業',XBI:'バイオテック',GNOM:'ゲノム',PHO:'水関連',KBE:'銀行',TAN:'ソーラー',KRE:'地銀',IHI:'医療機器',KIE:'保険',COPX:'銅鉱',IYT:'運輸',ITA:'航空宇宙・防衛',PAVE:'インフラ',SIL:'銀鉱',IBUY:'EC',REMX:'レアアース',PPH:'製薬',PKB:'建設',BOAT:'海運',XRT:'小売',XHB:'住宅建設',XAR:'宇宙・防衛',WGMI:'BTCマイニング',JETS:'航空',GDX:'金鉱',PEJ:'レジャー'};

const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const isNum=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
const n=v=>isNum(v)?Number(v):null;
const fmt=(v,d=1)=>isNum(v)?Number(v).toFixed(d):'—';
const pct=(v,d=2)=>isNum(v)?`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`:'—';
const money=v=>{if(!isNum(v))return'—';const x=Number(v),sg=x>=0?'+':'−',a=Math.abs(x);if(a>=1e9)return`${sg}${(a/1e9).toFixed(2)}B`;if(a>=1e6)return`${sg}${Math.round(a/1e6)}M`;if(a>=1e3)return`${sg}${Math.round(a/1e3)}K`;return`${sg}${Math.round(a)}`};
const shortDate=s=>{const p=String(s||'').split('-');return p.length===3?`${p[0]}.${p[1]}.${p[2]}`:(s||'—')};
const etfName=t=>ETF[t]||'';
const etfLabel=t=>`${t}${etfName(t)?`｜${etfName(t)}`:''}`;
const modeLabel=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';

function parseShare(html){
  const asof=html.match(/class=["']asof["'][^>]*>(\d{4}-\d{2}-\d{2})</i)?.[1]||null;
  const crowd=html.match(/群衆温度計\s*<b>(\d+(?:\.\d+)?)/i)?.[1]||null;
  const label=html.match(/群衆温度計\s*<b>[^<]*（([^）]+)）/i)?.[1]||null;
  return {asof,crowd:n(crowd),label};
}

function allRows(d){return Object.values(d?.observations?.rotation_buckets||{}).flat().filter(x=>x&&x.ticker)}

function priceBand(v){if(!isNum(v))return {key:'na',label:'未計算'};const x=Number(v);if(x>=70)return{key:'strong',label:'強い'};if(x<45)return{key:'weak',label:'弱い'};return{key:'mid',label:'中立'};}
function internalBand(v){if(!isNum(v))return {key:'na',label:'未取得'};const x=Number(v);if(x>=60)return{key:'strong',label:'強い'};if(x<45)return{key:'weak',label:'弱い'};return{key:'mid',label:'中立'};}
function deltaBand(v){if(!isNum(v))return {key:'na',label:'変化未取得'};const x=Number(v);if(x>=10)return{key:'up',label:'改善'};if(x<=-10)return{key:'down',label:'悪化'};return{key:'flat',label:'横ばい'};}

function flowMetric(r){
  if(r.flow_ready&&isNum(r.flow_20d_pct_aum))return{pct:Number(r.flow_20d_pct_aum),usd:n(r.flow_20d_usd),period:'20日',validated:true,provider:r.flow_provider||'actual Fund Flow'};
  if(r.ticker==='DRAM'&&isNum(r.flow_1m_pct_aum))return{pct:Number(r.flow_1m_pct_aum),usd:n(r.flow_1m_usd),period:'1M',validated:false,provider:r.flow_1m_provider||'TradingView'};
  return{pct:null,usd:null,period:'—',validated:false,provider:null};
}
function flowBand(r){const f=flowMetric(r);if(!isNum(f.pct))return{key:'na',label:'未取得',...f};const x=Number(f.pct),q=isNum(r.__flowMagnitudePctile)?Number(r.__flowMagnitudePctile):null;if(Math.abs(x)<0.05)return{key:'flat',label:'ほぼ横ばい',...f};const scale=q!==null&&q>=75?'（大）':q!==null&&q<=25?'（小）':'';if(x>0)return{key:'in',label:`純流入${scale}`,...f};return{key:'out',label:`純流出${scale}`,...f};}
function enrichFlowMagnitude(rows){const vals=rows.map(r=>flowMetric(r)).filter(f=>f.validated&&isNum(f.pct)).map(f=>Math.abs(Number(f.pct))).sort((a,b)=>a-b);rows.forEach(r=>{const f=flowMetric(r);if(!f.validated||!isNum(f.pct)||!vals.length){r.__flowMagnitudePctile=null;return;}const a=Math.abs(Number(f.pct));let le=0;for(const v of vals)if(v<=a)le++;r.__flowMagnitudePctile=100*le/vals.length;});}

function describeRow(r){
  if(r.ticker==='DRAM'&&(r.rs189_pending||r.state==='RS189_PENDING')){
    return{key:'pending',tone:'watch',title:'RS189待ち',note:'短期価格・補助構成株・1M純資金のみ表示。既存55テーマ順位には混ぜない。'};
  }
  const p=priceBand(r.price_score),i=internalBand(r.internal_score),d=deltaBand(r.internal_delta20),f=flowBand(r);
  const pv=n(r.price_score),iv=n(r.internal_score),dv=n(r.internal_delta20),fv=n(f.pct);
  if(pv!==null&&iv!==null&&pv>=60&&iv>=60&&fv!==null&&fv<0){
    return{key:'strong_outflow',tone:'watch',title:'テーマ強い・ETF純流出',note:`価格と構成株は強い。一方、ETF商品からは${f.period}で${pct(fv)}純流出。`};
  }
  if(pv!==null&&iv!==null&&pv>=70&&iv>=60){
    return{key:'strong',tone:'good',title:'価格・構成株とも強い',note:`テーマの値動きと中の個別株がそろって強い。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv)}`:''}。`};
  }
  if(dv!==null&&dv>=10&&iv!==null&&iv>=50&&fv!==null&&fv>=0){
    return{key:'improving_inflow',tone:'watch',title:'構成株改善＋ETF純流入',note:`構成株の強さが20日で${pct(dv,1)}改善し、ETFにも${f.period}純流入。`};
  }
  if(pv!==null&&iv!==null&&pv<45&&iv<45){
    return{key:'weak',tone:'bad',title:'価格・構成株とも弱い',note:`ETF価格も中の個別株もTheme56下位。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv)}`:''}。`};
  }
  if(iv!==null&&iv<45&&fv!==null&&fv<0){
    return{key:'weak_outflow',tone:'bad',title:'構成株弱い＋ETF純流出',note:`構成株が弱く、ETF商品からも${f.period}で${pct(fv)}純流出。`};
  }
  if(pv!==null&&iv!==null&&pv<60&&iv>=60){
    return{key:'internal_lead',tone:'watch',title:'構成株が先行',note:`ETF価格はまだ上位ではないが、中の個別株は強い。構成株変化は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。`};
  }
  if(pv!==null&&iv!==null&&pv>=70&&iv<50){
    return{key:'price_lead',tone:'watch',title:'価格先行・構成株弱め',note:`ETF価格は強いが、構成株の広がりが追いついていない。構成株は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。`};
  }
  if(fv!==null&&fv>0&&pv!==null&&iv!==null&&pv<60&&iv<50){
    return{key:'flow_lead',tone:'watch',title:'ETF純流入が先行',note:`ETF商品には${f.period}で${pct(fv)}純流入。ただし価格・構成株はまだ上位ではない。`};
  }
  const tone=(p.key==='weak'||i.key==='weak'||d.key==='down')?'bad':'neutral';
  return{key:'explicit_mix',tone,title:`価格${p.label}・構成株${i.label}`,note:`構成株は${d.label}${isNum(dv)?` ${pct(dv,1)}`:''}。ETF純資金は${f.label}${isNum(fv)?` ${pct(fv)}`:''}。`};
}

function rowPriority(r){
  const k=describeRow(r).key;
  const map={strong:0,strong_outflow:1,improving_inflow:2,internal_lead:3,price_lead:4,flow_lead:5,explicit_mix:6,weak_outflow:7,weak:8,pending:9};
  return map[k]??6;
}

function helpText(key,r){
  if(key==='price')return{title:'価格の強さ',body:`Theme56内でのETF価格/RSの相対順位です。70以上を「強い」、45未満を「弱い」、その間を「中立」と表示します。${r&&isNum(r.price_score)?`このETFは ${fmt(r.price_score,1)}。20日騰落率 ${pct(r.ret_20d_pct)}。`:''}`};
  if(key==='internal')return{title:'構成株の強さ',body:`ETFを構成する個別株がどれだけ広く強いかをTheme56内で比較した値です。60以上を「強い」、45未満を「弱い」と表示します。20日変化が+10以上なら改善、-10以下なら悪化です。${r&&isNum(r.internal_score)?`このETFは ${fmt(r.internal_score,1)}、20日変化 ${pct(r.internal_delta20,1)}。`:''}`};
  if(key==='flow'){
    const f=r?flowMetric(r):null;
    return{title:'ETF純資金（Fund Flow）',body:`ETFの売買代金ではありません。ETF口数の設定（creation）から解約（redemption）を引いた純資金の動きです。ETF価格は構成株価値と裁定で連動しますが、ETF商品の純設定・純解約と構成株市場全体の売買資金は同一ではありません。${f&&isNum(f.pct)?`このETFは ${f.period} ${pct(f.pct)} / ${money(f.usd)}。Provider: ${f.provider}。${f.validated?'検証済み20日actual Flowです。':'DRAMの補助1M値で、標準20日ランキングには混ぜません。'}`:''}`};
  }
  return{title:'状態の読み方',body:'価格・構成株・ETF純資金の3つを別々に見て、具体的な組み合わせとして表示します。Rotation単独の売買シグナルではありません。'};
}

function openHelp(key,r){const h=helpText(key,r);$('helpTitle').textContent=h.title;$('helpBody').textContent=h.body;$('helpModal').hidden=false;document.body.classList.add('modal-open');}
function closeHelp(){$('helpModal').hidden=true;document.body.classList.remove('modal-open');}

function summaryItem(r,kind='state'){
  const d=describeRow(r),f=flowMetric(r);
  let value='';
  if(kind==='improve')value=isNum(r.internal_delta20)?pct(r.internal_delta20,1):'';
  if(kind==='flow')value=isNum(f.pct)?pct(f.pct):'';
  if(kind==='deteriorate')value=isNum(r.internal_delta20)?pct(r.internal_delta20,1):'';
  return `<div class="summary-line"><b class="${d.tone}">${esc(etfLabel(r.ticker))}</b>${value?` <span class="${Number(value.replace('%',''))>=0?'good':'bad'}">${esc(value)}</span>`:''}<small>${esc(d.title)}</small></div>`;
}

function renderHero(rows,live){
  const m=live?.market||{},mode=String(m.mode||'').toUpperCase(),limit=m.new_entry_limit??'—';
  const action={STOP:'通常個別株の新規エントリーは停止',DEFENSE:'防御モード：通常個別株の新規停止',SELECTIVE:'選別モード：新規候補を絞る',ATTACK:'攻撃モード：正式V38候補を実行対象へ'}[mode]||'市場モード確認待ち';
  $('heroAction').textContent=action;$('permission').textContent=String(limit);$('permissionSub').textContent=`NQSAR ${m.nqsar||'—'} / Breadth ${isNum(m.breadth50)?fmt(m.breadth50,1)+'%':'—'}`;
  const strong=rows.filter(r=>{const p=n(r.price_score),i=n(r.internal_score);return p!==null&&i!==null&&p>=70&&i>=60}).sort((a,b)=>(n(b.price_score)||0)-(n(a.price_score)||0));
  const improve=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)>0).sort((a,b)=>Number(b.internal_delta20)-Number(a.internal_delta20));
  const flows=rows.map(r=>({r,f:flowMetric(r)})).filter(x=>x.f.validated&&isNum(x.f.pct)).sort((a,b)=>Number(b.f.pct)-Number(a.f.pct));
  const deteriorate=rows.filter(r=>isNum(r.internal_delta20)&&Number(r.internal_delta20)<0).sort((a,b)=>Number(a.internal_delta20)-Number(b.internal_delta20));
  $('summaryStrong').innerHTML=strong.slice(0,4).map(r=>summaryItem(r)).join('')||'<div class="summary-empty">明確な上位なし</div>';
  $('summaryImprove').innerHTML=improve.slice(0,4).map(r=>summaryItem(r,'improve')).join('')||'<div class="summary-empty">改善確認なし</div>';
  $('summaryInflow').innerHTML=flows.slice(0,4).map(x=>summaryItem(x.r,'flow')).join('')||'<div class="summary-empty">純流入データなし</div>';
  $('summaryDeteriorate').innerHTML=deteriorate.slice(0,4).map(r=>summaryItem(r,'deteriorate')).join('')||'<div class="summary-empty">悪化確認なし</div>';
  const parts=[];
  if(strong.length)parts.push(`現在強いのは ${strong.slice(0,3).map(r=>etfLabel(r.ticker)).join(' / ')}`);
  if(improve.length)parts.push(`構成株の改善が大きいのは ${improve.slice(0,3).map(r=>etfLabel(r.ticker)).join(' / ')}`);
  $('heroSentence').textContent=(parts.join('。')||'Theme56に明確な上位は限定的です。')+'。Rotationは「どこを見るか」の観測で、買い許可は既存Dashboardに従います。';
}

function renderMarket(live,share){
  const m=live?.market||{},p=live?.panic_tqqq||{},mode=String(m.mode||'').toUpperCase();
  $('mode').innerHTML=`<span class="status ${mode.toLowerCase()}">${esc(modeLabel(mode))}</span>`;
  $('modeSub').textContent=`新規枠上限 ${m.new_entry_limit??'—'}`;
  $('breadth').textContent=isNum(m.breadth50)?fmt(m.breadth50,1)+'%':'—';
  $('nqsar').textContent=`NQSAR ${m.nqsar||'—'}`;
  $('crowd').textContent=isNum(share?.crowd)?fmt(share.crowd,0):'—';
  $('crowdSub').textContent=isNum(share?.crowd)?`${share.label||'—'} / 既存Dashboard`:'既存Dashboard';
  $('vix').textContent=isNum(p.vix_close)?fmt(p.vix_close,2):'—';
}

function renderThemeList(rows,d){
  const sorted=[...rows].sort((a,b)=>rowPriority(a)-rowPriority(b)||(n(b.price_score)||0)-(n(a.price_score)||0));
  $('themeList').innerHTML=sorted.map(r=>{
    const s=describeRow(r),f=flowMetric(r),db=deltaBand(r.internal_delta20),pb=priceBand(r.price_score),ib=internalBand(r.internal_score);
    const flowClass=isNum(f.pct)?(Number(f.pct)>=0?'good':'bad'):'';
    const flowLabel=f.period==='1M'?'1M補助':'20日';
    return `<div class="theme-row" data-ticker="${esc(r.ticker)}">
      <div class="theme-id"><span class="ticker">${esc(r.ticker)}</span><span class="etf-name">${esc(etfName(r.ticker))}</span></div>
      <div class="theme-state"><div class="state-title ${s.tone}">${esc(s.title)}</div><div class="state-note">${esc(s.note)}</div></div>
      <button class="metric-cell help-trigger" data-help-key="internal" data-ticker="${esc(r.ticker)}"><span>構成株</span><b class="${ib.key==='strong'?'good':ib.key==='weak'?'bad':''}">${fmt(r.internal_score,1)}</b><small class="${db.key==='up'?'good':db.key==='down'?'bad':''}">${db.label}${isNum(r.internal_delta20)?` ${pct(r.internal_delta20,1)}`:''}</small></button>
      <button class="metric-cell help-trigger" data-help-key="price" data-ticker="${esc(r.ticker)}"><span>価格</span><b class="${pb.key==='strong'?'good':pb.key==='weak'?'bad':''}">${r.rs189_pending?pct(r.ret_20d_pct):fmt(r.price_score,1)}</b><small>${r.rs189_pending?'20日 / RS189待ち':`20日 ${pct(r.ret_20d_pct)}`}</small></button>
      <button class="metric-cell help-trigger" data-help-key="flow" data-ticker="${esc(r.ticker)}"><span>ETF純資金</span><b class="${flowClass}">${pct(f.pct)}</b><small>${money(f.usd)} / ${flowLabel}</small></button>
    </div>`;
  }).join('');
  $('themeDataAsOf').textContent=`Price / Internal / 20日Flow 基準 ${shortDate(d.asof)}`;
}

function renderFlowPanel(rows){
  const arr=rows.map(r=>({r,f:flowMetric(r)})).filter(x=>x.f.validated&&isNum(x.f.pct));
  const inflow=[...arr].sort((a,b)=>Number(b.f.pct)-Number(a.f.pct)).slice(0,6);
  const outflow=[...arr].sort((a,b)=>Number(a.f.pct)-Number(b.f.pct)).slice(0,6);
  const one=x=>`<div class="flow-rank-row"><div><b>${esc(x.r.ticker)}</b><span>${esc(etfName(x.r.ticker))}</span></div><div class="flow-rank-value ${Number(x.f.pct)>=0?'good':'bad'}">${pct(x.f.pct)}<small>${money(x.f.usd)}</small></div></div>`;
  $('flowIn').innerHTML=inflow.map(one).join('')||'<div class="sub">データなし</div>';
  $('flowOut').innerHTML=outflow.map(one).join('')||'<div class="sub">データなし</div>';
}

function renderChanges(rows){
  const ready=rows.filter(r=>isNum(r.internal_delta20));
  const up=[...ready].sort((a,b)=>Number(b.internal_delta20)-Number(a.internal_delta20)).slice(0,8);
  const down=[...ready].sort((a,b)=>Number(a.internal_delta20)-Number(b.internal_delta20)).slice(0,8);
  const one=(r,upside)=>{const s=describeRow(r);return `<div class="change-row"><div class="change-theme"><b>${esc(etfLabel(r.ticker))}</b><span>${esc(s.title)}</span></div><div class="change-metrics"><strong class="${upside?'good':'bad'}">構成株 ${pct(r.internal_delta20,1)}</strong><small>価格20日 ${pct(r.ret_20d_pct)} / ETF純資金 ${pct(flowMetric(r).pct)}</small></div></div>`};
  $('improvingList').innerHTML=up.map(r=>one(r,true)).join('');
  $('deterioratingList').innerHTML=down.map(r=>one(r,false)).join('');
}

function groupBy(arr,key){return arr.reduce((m,x)=>{const k=x[key]||'その他';(m[k]||(m[k]=[])).push(x);return m},{})}
function renderLeaders(rows,d,ctx){
  const rowBy={};rows.forEach(r=>rowBy[r.ticker]=r);
  const formal={};(d.theme_stock?.formal_v38_context||[]).forEach(g=>(g.stocks||[]).forEach(s=>formal[`${g.etf}:${s.symbol}`]=s));
  const items=ctx?.industry_context||[];
  const cards=items.map(item=>{const r=rowBy[item.etf]||{},leaders=item.existing_emerging_or_leading_leaders_in_full_intersection||item.existing_emerging_or_leading_leaders_in_top15_intersection||[];return{...item,_row:r,_leaders:leaders,_state:describeRow(r)}})
    .filter(x=>x._leaders.length&&['strong','strong_outflow','improving_inflow','internal_lead','price_lead'].includes(x._state.key))
    .sort((a,b)=>rowPriority(a._row)-rowPriority(b._row)||(n(b._row.price_score)||0)-(n(a._row.price_score)||0));
  const fullScope=ctx?.context_scope==='THEME56_READY_CURRENT_MEMBERSHIP_X_FULL_LEADERSHIP_EXPORT';
  $('leaderScope').textContent=fullScope?'現ETF構成 × Leadership全銘柄':'照合範囲に上限あり';
  $('leaders').innerHTML=cards.length?cards.map(item=>{
    const s=item._state,groups=groupBy(item._leaders.slice(0,18),'group');
    const coverage=isNum(item.leadership_full_intersection_pct)?`${fmt(item.leadership_full_intersection_pct,0)}%`:'—';
    const q=item.membership_quality==='ISSUER_EXACT_CURRENT'?'発行会社Exact':'検証済み現構成';
    return `<div class="leader-card"><div class="leader-head"><div class="leader-title">${esc(etfLabel(item.etf))}<small>${esc(s.note)}</small></div><div class="leader-state ${s.tone}">${esc(s.title)}</div></div><div class="leader-coverage">構成 ${item.membership_rows??'—'}銘柄（${esc(q)}） / Leadership照合 ${item.leadership_full_intersections??'—'}（${coverage}）</div>${Object.entries(groups).slice(0,4).map(([g,ls])=>`<div class="theme-block"><div class="theme-name">${esc(g)} ・ ${esc(ls[0]?.group_phase==='EMERGING'?'新興':ls[0]?.group_phase==='LEADING'?'主導':ls[0]?.group_phase||'')}</div><div class="stocks-line">${ls.slice(0,6).map(x=>{const f=formal[`${item.etf}:${x.symbol}`],role=x.role==='PIONEER'?'先導':x.role==='LEADER'?'主導':x.role||'';return `<div class="stock-pill"><b>${esc(x.symbol)}</b><span>${esc(role)} / RS189 ${isNum(x.rs189)?fmt(x.rs189,0):'—'} / RS63 ${isNum(x.rs63)?fmt(x.rs63,0):'—'}${f&&f.attack_rank?` / V38 #${f.attack_rank}`:''}</span></div>`}).join('')}</div></div>`).join('')}</div>`;
  }).join(''):'<div class="sub">現在強い・改善中テーマで、既存Leadershipの先導株/主導株との一致はありません。</div>';
}

function toneColor(s){if(s.tone==='good')return'#77d49e';if(s.tone==='bad')return'#df7b7b';if(s.tone==='watch')return'#e4b967';return'#657281';}
function renderMatrix(rows){
  const svg=$('rotationMatrix');
  const W=760,H=430,L=52,R=18,T=20,B=42,iw=W-L-R,ih=H-T-B;
  const sx=x=>L+(Math.max(0,Math.min(100,x))/100)*iw,sy=y=>T+ih-(Math.max(0,Math.min(100,y))/100)*ih;
  let out=`<rect x="${L}" y="${T}" width="${iw}" height="${ih}" fill="#0b1117"/><line x1="${sx(50)}" x2="${sx(50)}" y1="${T}" y2="${T+ih}" stroke="#26313d"/><line x1="${L}" x2="${L+iw}" y1="${sy(50)}" y2="${sy(50)}" stroke="#26313d"/>`;
  [0,25,50,75,100].forEach(v=>{out+=`<text x="${sx(v)}" y="${H-14}" fill="#657281" font-size="10" text-anchor="middle">${v}</text><text x="${L-10}" y="${sy(v)+3}" fill="#657281" font-size="10" text-anchor="end">${v}</text>`});
  out+=`<text x="${L+iw/2}" y="${H-1}" fill="#93a0ae" font-size="11" text-anchor="middle">ETF価格の強さ →</text><text x="12" y="${T+ih/2}" fill="#93a0ae" font-size="11" text-anchor="middle" transform="rotate(-90 12 ${T+ih/2})">構成株の強さ →</text>`;
  rows.filter(r=>isNum(r.price_score)&&isNum(r.internal_score)).forEach(r=>{const s=describeRow(r),f=flowMetric(r),mag=isNum(f.pct)?Math.min(16,4+Math.sqrt(Math.abs(Number(f.pct)))*2):4,x=sx(Number(r.price_score)),y=sy(Number(r.internal_score)),c=toneColor(s),stroke=isNum(f.pct)?(Number(f.pct)>=0?'#77d49e':'#df7b7b'):'#657281';out+=`<g class="plot-point"><circle cx="${x}" cy="${y}" r="${mag}" fill="${c}" fill-opacity=".72" stroke="${stroke}" stroke-width="1.4"><title>${esc(etfLabel(r.ticker))} / ${esc(s.title)} / Flow ${pct(f.pct)}</title></circle><text x="${x}" y="${y+3}" fill="#0a0e13" font-size="8" font-weight="800" text-anchor="middle">${esc(r.ticker)}</text></g>`});
  svg.innerHTML=out;
}

function renderDashboardContext(live,share){
  const m=live?.market||{},p=live?.panic_tqqq||{};
  const items=[['Market Conditions',isNum(p.mc57)?fmt(p.mc57,1):'—'],['NQSAR',m.nqsar||'—'],['Breadth50',isNum(m.breadth50)?fmt(m.breadth50,2)+'%':'—'],['群衆温度計',isNum(share?.crowd)?`${fmt(share.crowd,0)}（${share.label||'—'}）`:'—'],['VIX',isNum(p.vix_close)?fmt(p.vix_close,2):'—']];
  $('dashboardContext').innerHTML=items.map(([k,v])=>`<div class="context-cell"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
}

function renderExternal(d){
  const facts=d.macro_why?.facts||[],hyp=d.macro_why?.hypotheses||[],missing=d.macro_why?.missing||[];
  $('externalAsOf').textContent=`外部参考の元データ基準：${shortDate(d.input_alignment?.v38_asof)}。既存Dashboardの市場判断には使用しません。`;
  $('macroFacts').innerHTML=facts.map(x=>`<div class="obs">${esc(String(x).replace('Fear & Greed','外部参考 Fear & Greed'))}</div>`).join('')||'<div class="sub">外部参考なし</div>';
  $('hypotheses').innerHTML=hyp.map(x=>`<div class="obs">${esc(String(x).replace('Fear & Greed','外部参考 Fear & Greed'))}</div>`).join('');
  $('missing').innerHTML=missing.map(x=>`<span>${esc(x)}</span>`).join('')||'<span>なし</span>';
}

function renderV38(d,live,rows){
  const m=live?.market||{},mode=String(m.mode||'').toUpperCase(),limit=m.new_entry_limit??'—';
  const strong=rows.filter(r=>{const p=n(r.price_score),i=n(r.internal_score);return p!==null&&i!==null&&p>=70&&i>=60}).sort((a,b)=>(n(b.price_score)||0)-(n(a.price_score)||0)).slice(0,4);
  const marketText=mode==='ATTACK'?'新規可':mode==='SELECTIVE'?'選別して新規可':'新規停止';
  $('v38Connection').innerHTML=`<div class="connection-step"><span>① 市場環境</span><b>${esc(modeLabel(mode))}</b><small>${esc(marketText)} / 新規枠 ${limit}</small></div><div class="connection-arrow">→</div><div class="connection-step"><span>② 見る場所</span><b>${strong.length?strong.map(r=>esc(r.ticker)).join(' / '):'明確な強Themeなし'}</b><small>Rotationの観測</small></div><div class="connection-arrow">→</div><div class="connection-step"><span>③ 買う銘柄</span><b>正式V38候補のみ</b><small>Rotation独自ランキングなし</small></div>`;
  if(['ATTACK','SELECTIVE'].includes(mode))$('v38Details').open=true;
  renderStocks(d.theme_stock?.formal_v38_context||[]);
}

function renderStocks(groups){
  $('stocks').innerHTML=(groups||[]).length?groups.map(g=>`<div class="stock-group"><div class="stock-head"><div class="stock-etf">${esc(etfLabel(g.etf))}</div><div class="stock-count">正式条件通過 ${g.eligible_count??0}銘柄</div></div><div class="scroll"><table><thead><tr><th>銘柄</th><th>Theme</th><th>攻撃時順位</th><th>RS189</th><th>RS63</th><th>Theme強度</th></tr></thead><tbody>${(g.stocks||[]).map(s=>`<tr><td>${esc(s.symbol)}</td><td>${esc(s.peer_theme||'—')}</td><td>${s.attack_rank??'—'}</td><td>${isNum(s.rs189)?fmt(s.rs189,1):'—'}</td><td>${isNum(s.rs63)?fmt(s.rs63,1):'—'}</td><td>${isNum(s.peer_theme_score)?fmt(s.peer_theme_score,1):'—'}</td></tr>`).join('')}</tbody></table></div></div>`).join(''):'<div class="sub">正式条件通過候補なし</div>';
}

function renderGuide(){
  const items=[
    ['価格・構成株とも強い','ETF価格と中の個別株が同時に上位。現在の強さを示すが、買いシグナルではない。'],
    ['テーマ強い・ETF純流出','価格と構成株は強い一方、ETF商品では純解約超過。構成株市場全体の売買資金とETF純設定/解約は別物。'],
    ['構成株改善＋ETF純流入','構成株の強さが改善し、ETF商品にも純流入。早期Rotationの観測候補。'],
    ['構成株が先行','中の個別株は強いが、ETF価格はまだ上位ではない。'],
    ['価格先行・構成株弱め','ETF価格は強いが、構成株の広がりが追いついていない。'],
    ['ETF純流入が先行','ETF商品への純流入はあるが、価格・構成株はまだ上位ではない。'],
    ['価格○・構成株○','上記の特殊形に当てはまらない場合も「方向不一致」とせず、実際の2軸をそのまま表示。'],
    ['価格・構成株とも弱い','ETF価格と中の個別株が同時に下位。Rotation上の弱化Context。']
  ];
  $('guide').innerHTML=items.map(([a,b])=>`<div class="obs"><b>${esc(a)}</b>　${esc(b)}</div>`).join('');
}

function renderQuality(d,ctx,live,share){
  const s=d.theme56_data_status||{},rot=shortDate(d.asof),v38=shortDate(live?.asof||share?.asof),lead=shortDate(ctx?.leadership_coverage?.market_asof);
  $('quality').innerHTML=`<div class="quality"><div><strong>Theme56：</strong>56 ETF / Price ${s.price_ready_count??'—'} / Holdings ${s.holdings_ready_count??'—'} / 構成株 ${s.internal_measured_count??'—'} / 20日ETF純資金 ${s.flow_ready_count??'—'} / Full Stack ${s.measured_full_stack_count??'—'}</div><div><strong>基準日：</strong>Price・構成株・20日Flow ${rot} / 既存Dashboard ${v38} / Leadership市場データ ${lead}</div><div><strong>構成銘柄：</strong>発行会社Exact ${s.issuer_exact_holdings_count??'—'} Theme ＋ 検証済みfallback ${s.validated_fallback_holdings_count??'—'} Theme。現在構成で、過去PIT構成ではありません。</div><div><strong>ETF純資金：</strong>発行会社Exact ${s.issuer_exact_flow_count??'—'} Themeを優先、残りは照合済みactual Fund Flow。売買代金proxyは不使用。</div><div><strong>DRAM：</strong>${esc(s.formal_exception||'上場後の履歴不足によりRS189未計算。')} 1M補助Flowは標準20日ランキング・状態判定に混ぜません。</div><div><strong>状態表示：</strong>売買シグナルではなく、価格・構成株・ETF純資金の現在観測。曖昧なMIXED/方向不一致ラベルは画面では使用しません。</div></div>`;
}

function renderMeta(d,live,s){
  $('rotationDateBadge').textContent=`Rotation ${shortDate(d.asof)}`;
  $('v38DateBadge').textContent=`V38 ${shortDate(live?.asof||s?.asof)}`;
  const ds=d.theme56_data_status||{};$('coverageBadge').textContent=`Full Stack ${ds.measured_full_stack_count??'—'}/56`;$('coverageBadge').classList.toggle('ok',Number(ds.measured_full_stack_count)>=55);
}

function bindHelp(rows){
  const by={};rows.forEach(r=>by[r.ticker]=r);
  document.addEventListener('click',e=>{
    const close=e.target.closest('[data-close-help]');if(close){closeHelp();return;}
    const el=e.target.closest('.help-trigger');if(!el)return;openHelp(el.dataset.helpKey,by[el.dataset.ticker]||null);
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('helpModal').hidden)closeHelp();});
}

function renderAll(d,ctx,live,shareHtml){
  const share=parseShare(shareHtml||''),rows=allRows(d);
  enrichFlowMagnitude(rows);
  renderMeta(d,live,share);renderHero(rows,live);renderMarket(live,share);renderThemeList(rows,d);renderFlowPanel(rows);renderChanges(rows);renderLeaders(rows,d,ctx);renderMatrix(rows);renderDashboardContext(live,share);renderExternal(d);renderV38(d,live,rows);renderGuide();renderQuality(d,ctx,live,share);bindHelp(rows);
}

Promise.all([
  fetch(DATA_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Rotation brief HTTP ${r.status}`);return r.json()}),
  fetch(CONTEXT_URL,{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null),
  fetch(LIVE_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`V38 live HTTP ${r.status}`);return r.json()}),
  fetch(SHARE_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Dashboard share HTTP ${r.status}`);return r.text()})
]).then(([d,ctx,live,share])=>renderAll(d,ctx,live,share)).catch(err=>{$('error').innerHTML=`<div class="error">最新データを読み込めませんでした。<br>${esc(err.message)}</div>`;console.error(err)});

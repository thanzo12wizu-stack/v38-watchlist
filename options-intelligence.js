(() => {
'use strict';

const SAME={
  pos:'./options_positioning.json',
  dh:'./options_history.csv',
  sh:'./options_scan_history.csv',
  uni:'./universe.csv',
  leaders:'./rotation/data/rotation-theme56-stock-context.json'
};
const RAW={
  pos:'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_positioning.json',
  dh:'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_history.csv',
  sh:'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_scan_history.csv',
  uni:'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/universe.csv',
  leaders:'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/rotation/data/rotation-theme56-stock-context.json'
};

const $=s=>document.querySelector(s);
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>{const n=num(v);if(n===null)return'—';const d=n>=100?0:2;return'$'+n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:2})};
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

let universe=[],universeMap={},optionMap={},positioning={},leaderMap={},leaderMeta={},records=[];
let activeSuggestion=-1;

async function getText(key){
  let last;
  for(const url of [SAME[key],RAW[key]]){
    try{const r=await fetch(url+'?v='+Date.now(),{cache:'no-store'});if(r.ok)return await r.text();last=new Error(`${key}:${r.status}`)}catch(e){last=e}
  }
  throw last||new Error(`${key} unavailable`);
}
async function getJson(key){return JSON.parse(await getText(key));}
function parseCsv(text){
  const rows=[];let row=[],cell='',q=false;
  for(let i=0;i<text.length;i++){
    const c=text[i],n=text[i+1];
    if(q){if(c==='"'&&n==='"'){cell+='"';i++}else if(c==='"')q=false;else cell+=c}
    else{if(c==='"')q=true;else if(c===','){row.push(cell);cell=''}else if(c==='\n'){row.push(cell);rows.push(row);row=[];cell=''}else if(c!=='\r')cell+=c}
  }
  if(cell||row.length){row.push(cell);rows.push(row)}
  if(rows.length<2)return[];
  const h=rows[0];
  return rows.slice(1).filter(r=>r.some(x=>x!=='')).map(r=>Object.fromEntries(h.map((k,i)=>[k,r[i]??''])));
}
function latestTwo(rows){
  const m={};
  for(const r of rows){const t=String(r.ticker||'').trim().toUpperCase();if(!t)continue;(m[t]??=[]).push(r)}
  for(const t of Object.keys(m)){
    const byDate={};for(const r of m[t])byDate[String(r.date||'').slice(0,10)]=r;
    const a=Object.values(byDate).sort((x,y)=>String(x.date).localeCompare(String(y.date)));
    m[t]=[a.at(-1)||null,a.length>1?a.at(-2):null];
  }
  return m;
}
function obs(r){
  if(!r)return null;
  return {date:String(r.date||'').slice(0,10),expiry:r.expiry||'',spot:num(r.spot),atr14:num(r.atr14),call_wall:num(r.call_wall),put_wall:num(r.put_wall),gamma_flip:num(r.gamma_flip),net_gex:num(r.net_gex),regime:r.regime||'UNKNOWN',confidence:String(r.confidence||'').toUpperCase(),total_oi:num(r.total_oi),n_strikes:num(r.n_strikes),detail:false,stale:false};
}
function currentObs(r,asof){
  const k=r.selected_expiry||r.nearest,e=(r.expiries||{})[k]||{};
  return {date:String(r.asof||asof||'').slice(0,10),expiry:k||'',spot:num(r.spot),atr14:num(r.atr14),call_wall:num(r.call_wall&&r.call_wall.px),put_wall:num(r.put_wall&&r.put_wall.px),gamma_flip:num(r.gamma_flip&&r.gamma_flip.px),net_gex:num(r.net_gex),regime:r.regime||'UNKNOWN',confidence:String(r.confidence||'').toUpperCase(),total_oi:num(e.total_oi),n_strikes:num(e.n_strikes),call_oi:num(e.call_oi),put_oi:num(e.put_oi),call_wall_share:num(e.call_wall_share),put_wall_share:num(e.put_wall_share),call_wall_vs_second:num(e.call_wall_vs_second),put_wall_vs_second:num(e.put_wall_vs_second),detail:true,stale:!!r.stale};
}
function ageDays(s){
  if(!s)return null;const d=new Date(s+'T00:00:00Z');if(!Number.isFinite(d.getTime()))return null;return Math.max(0,Math.floor((Date.now()-d.getTime())/86400000));
}
function regime(spot,gf,atr){if(spot===null||gf===null)return'UNKNOWN';if(atr&&Math.abs(spot-gf)/atr<=1)return'NEAR_FLIP';return spot>gf?'POSITIVE_GAMMA':'NEGATIVE_GAMMA'}
function datr(level,spot,atr){return level!==null&&spot!==null&&atr&&atr>0?(level-spot)/atr:null}
function multi(r){
  if(!r)return null;const spot=num(r.spot),atr=num(r.atr14),a=Object.values(r.expiries||{}).map(e=>regime(spot,num(e.gamma_flip),atr));if(!a.length)return null;
  const count=x=>a.filter(v=>v===x).length;return{count:a.length,positive:count('POSITIVE_GAMMA'),near:count('NEAR_FLIP'),negative:count('NEGATIVE_GAMMA')};
}
function crossed(prev,cur){return !!prev&&prev.spot!==null&&prev.call_wall!==null&&cur.spot!==null&&prev.spot<prev.call_wall&&cur.spot>prev.call_wall*1.002}
function classify(cur,prev,m,age){
  if(!cur||cur.spot===null||cur.stale||cur.confidence==='LOW'||(age!==null&&age>18))return{signal:'DATA LOW',score:0,reasons:['データ量/鮮度不足']};
  const ca=datr(cur.call_wall,cur.spot,cur.atr14),pa=datr(cur.put_wall,cur.spot,cur.atr14);let s=50,why=[];const reg=cur.regime||regime(cur.spot,cur.gamma_flip,cur.atr14);
  if(reg==='POSITIVE_GAMMA'){s+=18;why.push('Gamma Flip上')}else if(reg==='NEGATIVE_GAMMA'){s-=28;why.push('Gamma Flip下')}else if(reg==='NEAR_FLIP'){s-=4;why.push('Gamma Flip近辺')}
  if(pa!==null&&pa<0&&Math.abs(pa)<=2.2){s+=10;why.push('Put支持候補が近い')}
  if(ca!==null){if(ca>0&&ca<=1.2){s+=5;why.push('Call Wall接近')}else if(ca>1.2){s+=8;why.push('上側Wallまで余地')}}
  if(cur.net_gex!==null&&cur.net_gex>0){s+=5;why.push('Net GEXプラス')}
  if(['HIGH','OK','MEDIUM'].includes(cur.confidence))s+=4;
  if(m&&m.positive>m.negative){s+=6;why.push('複数満期も上側優勢')}
  const br=crossed(prev,cur);if(br){s+=18;why.push('前回Call Wall突破')}
  s=clamp(Math.round(s),0,100);
  let signal='NEUTRAL';if(br&&reg!=='NEGATIVE_GAMMA')signal='ACCELERATION';else if(reg==='NEGATIVE_GAMMA')signal='HEADWIND';else if(['POSITIVE_GAMMA','NEAR_FLIP'].includes(reg)&&ca!==null&&ca>0&&ca<=1.2)signal='BREAKOUT WATCH';else if(reg==='POSITIVE_GAMMA')signal='SUPPORTIVE';
  return{signal,score:s,reasons:why};
}
function plan(c,sig){
  const s=c.spot,cw=c.call_wall,pw=c.put_wall,gf=c.gamma_flip;let entry;
  if(sig==='ACCELERATION')entry='突破済みWallが支持へ変わるか確認。高値追いより初押し優先。';
  else if(sig==='BREAKOUT WATCH'&&cw!==null)entry=`Call Wall ${money(cw)} を終値突破し、次の足でも維持なら加速候補。`;
  else if(sig==='SUPPORTIVE')entry=gf!==null&&gf<s?`Gamma Flip ${money(gf)} 付近の反発確認を優先。`:pw!==null?`Put Wall ${money(pw)} 付近の反発確認を優先。`:'押し目反発を優先。';
  else if(sig==='HEADWIND')entry=gf!==null?`Gamma Flip ${money(gf)} の奪回待ち。`:'新規追随は見送り。';
  else entry='Gamma Flipから方向が離れるまで待つ。';
  let invalid='明確な無効化水準なし';
  if(gf!==null&&s!==null&&gf<s){invalid=`${money(gf)} 終値割れで構造悪化`;if(pw!==null&&pw<s)invalid+=`、${money(pw)} 割れで支持失効`}
  else if(gf!==null&&s!==null&&gf>s)invalid=`${money(gf)} 奪回まで上方向は保留`;
  else if(pw!==null&&s!==null&&pw<s)invalid=`${money(pw)} 終値割れで支持失効`;
  return{entry,invalid};
}
function signalView(r){
  if(!r)return{label:'Options未取得',cls:'bLow'};
  if(r.signal==='ACCELERATION')return{label:'加速候補',cls:'bAccel'};
  if(r.signal==='HEADWIND')return{label:'上値注意',cls:'bHead'};
  if(r.signal==='DATA LOW')return{label:'データ古い/不足',cls:'bLow'};
  if(r.signal==='BREAKOUT WATCH')return{label:'上抜け監視',cls:'bBreak'};
  if(r.score>=82)return{label:'強い上方向',cls:'bStrong'};
  if(r.score>=68)return{label:'上方向優位',cls:'bBull'};
  return{label:'中立',cls:'bNeutral'};
}
function thesis(r){
  if(!r)return'Optionsの有効観測がまだない。';
  switch(r.signal){case'ACCELERATION':return'前回Call Wallを突破。突破済み水準が支持へ変われば、次の上側水準まで加速余地。';case'BREAKOUT WATCH':return'上側Call Wallが近い。突破前は抵抗、終値突破後は加速候補。';case'SUPPORTIVE':return r.score>=82?'Flip上・下側支持・上側余地が揃った強い配置。':'Gamma Flip上で、下側支持と上側余地の位置関係が良い。';case'HEADWIND':return'Gamma Flip下の増幅側推定。追いかけ買いよりFlip奪回待ち。';case'DATA LOW':return'観測が古いかデータ量不足。売買根拠には使わない。';default:return'方向優位はまだ弱い。支持/抵抗どちらが先に機能するか待つ。'}
}
function distText(level,c){if(level===null||c.spot===null)return'';const p=(level/c.spot-1)*100,a=datr(level,c.spot,c.atr14);return`${p>=0?'+':''}${p.toFixed(1)}%${a!==null?' / '+Math.abs(a).toFixed(1)+'ATR':''}`}

function parseUniverse(rows){
  universe=[];universeMap={};
  for(const r of rows){const ticker=String(r['シンボル']||r.ticker||'').trim().toUpperCase();if(!ticker)continue;const u={ticker,name:r['名称']||'',sector:r['セクター']||'',industry:r['業種']||'',type:String(r['証券種別']||'').toLowerCase(),price:num(r['価格'])};universe.push(u);universeMap[ticker]=u;}
}
function scoreLeader(x){
  const strength=num(x.strength)??50,rs189=num(x.rs189)??50,rs63=num(x.rs63)??50,rs21=num(x.rs21)??50,acc=num(x.slow_acceleration)??num(x.acceleration)??0;
  let s=.36*strength+.25*rs189+.20*rs63+.11*rs21+.08*clamp(50+acc,0,100);
  if(String(x.role||'').toUpperCase()==='LEADER')s+=3;
  if(['LEADING','EMERGING'].includes(String(x.group_phase||'').toUpperCase()))s+=3;
  if(String(x.breakout_status||'').includes('BREAKOUT'))s+=3;
  return clamp(Math.round(s),0,100);
}
function collectLeaders(root){
  const out={};
  function walk(node,ctx={}){
    if(Array.isArray(node)){for(const v of node)walk(v,ctx);return}
    if(!node||typeof node!=='object')return;
    const next={...ctx};if(node.etf)next.etf=node.etf;if(node.label)next.theme=node.label;
    if(typeof node.symbol==='string'&&(node.role||node.strength!=null||node.rs189!=null||node.stock_rank_within_group!=null)){
      const t=node.symbol.trim().toUpperCase(),candidate={...node,ticker:t,theme:next.theme||'',etf:next.etf||'',leaderScore:scoreLeader(node)};
      const prev=out[t];if(!prev||candidate.leaderScore>prev.leaderScore)out[t]=candidate;
    }
    for(const [k,v] of Object.entries(node)){if(['symbol','name'].includes(k))continue;if(v&&typeof v==='object')walk(v,next)}
  }
  walk(root);return out;
}
function buildOptionMap(p,dhRows,shRows){
  positioning=p.tickers||{};const dh=latestTwo(dhRows),sh=latestTwo(shRows);optionMap={};records=[];
  const all=new Set([...Object.keys(positioning),...Object.keys(dh),...Object.keys(sh)]);
  for(const t of all){let cur=null,prev=null,source='';if(positioning[t]){cur=currentObs(positioning[t],p.asof);prev=obs((dh[t]||[])[1]);source='DETAIL'}else{const pair=sh[t]||dh[t];if(pair){cur=obs(pair[0]);prev=obs(pair[1]);source=sh[t]?'SCAN':'HISTORY'}}if(!cur)continue;const age=ageDays(cur.date),m=multi(positioning[t]),cl=classify(cur,prev,m,age),u=universeMap[t]||{};const rec={ticker:t,name:u.name||'',sector:u.sector||'',industry:u.industry||'',source,age_days:age,current:cur,previous:prev,multi_expiry:m,...cl,plan:plan(cur,cl.signal)};optionMap[t]=rec;records.push(rec)}
}

function buildLeaderRows(){
  const arr=[];for(const [t,l] of Object.entries(leaderMap)){const o=optionMap[t]||null;const fresh=o&&o.age_days!==null&&o.age_days<=4&&o.signal!=='DATA LOW';const combined=fresh?Math.round(.62*l.leaderScore+.38*o.score):Math.round(l.leaderScore*.78);arr.push({ticker:t,leader:l,option:o,fresh,combined})}
  const preferred=arr.filter(x=>x.fresh&&['ACCELERATION','SUPPORTIVE','BREAKOUT WATCH'].includes(x.option.signal)).sort((a,b)=>b.combined-a.combined);
  const rest=arr.filter(x=>!preferred.includes(x)).sort((a,b)=>b.leader.leaderScore-a.leader.leaderScore);
  return [...preferred,...rest].slice(0,8);
}
function buildBullishRows(){
  return records.filter(r=>r.age_days!==null&&r.age_days<=4&&r.signal!=='DATA LOW'&&r.signal!=='HEADWIND'&&r.score>=65&&String((universeMap[r.ticker]||{}).type||'stock')==='stock').sort((a,b)=>b.score-a.score).slice(0,10);
}
function leaderBadge(l){return l?`<span class="badge bLeader">主導株 ${l.leaderScore}</span>`:''}
function miniCard(ticker,o,l,combined){
  const u=universeMap[ticker]||{},sv=signalView(o),c=o&&o.current;const meta=l?`${esc(l.group||l.theme||u.industry||'')} · RS189 ${num(l.rs189)??'—'} / RS63 ${num(l.rs63)??'—'}`:`${esc(u.sector||'')} · ${esc(u.industry||'')}`;
  const levels=c?`<div class="miniLevels"><div class="miniLv"><span>現在</span><b>${money(c.spot)}</b></div><div class="miniLv"><span>支持候補</span><b>${money(c.put_wall??c.gamma_flip)}</b></div><div class="miniLv"><span>上値壁</span><b>${money(c.call_wall)}</b></div></div>`:'';
  return `<article class="miniCard" data-ticker="${esc(ticker)}"><div class="miniHead"><div class="ticker">${esc(ticker)}</div><div class="company">${esc(u.name||l?.name||'')}</div><div class="score">${combined!=null?combined:(o?o.score:'—')}</div></div><div class="badges">${leaderBadge(l)}<span class="badge ${sv.cls}">${sv.label}</span></div><div class="miniThesis">${esc(l&&o?`主導株 × ${thesis(o)}`:l?'Leadership上位。Options配置は未取得または鮮度不足。':thesis(o))}</div>${levels}<div class="miniMeta">${esc(meta)}${o?` · Options ${esc(o.current.date||'—')}`:''}</div></article>`;
}
function renderLeaders(){const rows=buildLeaderRows();$('#leaders').innerHTML=rows.length?rows.map(x=>miniCard(x.ticker,x.option,x.leader,x.combined)).join(''):'<div class="empty">Leadershipデータから対象を作れませんでした。</div>';bindCards($('#leaders'))}
function renderBullish(){const rows=buildBullishRows();$('#bullish').innerHTML=rows.length?rows.map(r=>miniCard(r.ticker,r,leaderMap[r.ticker]||null,r.score)).join(''):'<div class="empty">4日以内の観測で「上方向が強い配置」に該当する銘柄はありません。</div>';bindCards($('#bullish'))}
function renderAll(){const arr=[...records].sort((a,b)=>b.score-a.score).slice(0,120);$('#allRecords').innerHTML=arr.map(r=>{const u=universeMap[r.ticker]||{},sv=signalView(r);return`<div class="allRow" data-ticker="${esc(r.ticker)}"><strong>${esc(r.ticker)}</strong><span>${esc(u.name||'')}</span><em class="${sv.cls}">${esc(sv.label)}</em><b>${r.score}</b></div>`}).join('');bindCards($('#allRecords'))}
function bindCards(root){for(const el of root.querySelectorAll('[data-ticker]'))el.addEventListener('click',()=>selectTicker(el.dataset.ticker,true))}

function detailMetrics(o){const c=o.current,m=o.multi_expiry;return`<div class="detailGrid"><div class="detailMetric"><span>Options score</span><b>${o.score}/100</b></div><div class="detailMetric"><span>Net GEX</span><b>${c.net_gex===null?'—':(c.net_gex/1e6).toFixed(0)+'M'}</b></div><div class="detailMetric"><span>OI</span><b>${c.total_oi===null?'—':Math.round(c.total_oi).toLocaleString()}</b></div><div class="detailMetric"><span>複数満期</span><b>${m?`${m.positive}↑ / ${m.negative}↓`:'—'}</b></div></div>`}
function selectedHtml(ticker){
  const u=universeMap[ticker],o=optionMap[ticker],l=leaderMap[ticker];if(!u&&!o&&!l)return'<div class="noData"><strong>銘柄が見つかりません</strong>ユニバースに存在するTickerまたは会社名で検索してください。</div>';
  const name=u?.name||l?.name||o?.name||'',sector=u?.sector||l?.group_sector||'',industry=u?.industry||l?.group||'',leaderStats=l?`<div class="leaderStats"><span class="statPill">Leader<b>${l.leaderScore}</b></span><span class="statPill">RS189<b>${num(l.rs189)??'—'}</b></span><span class="statPill">RS63<b>${num(l.rs63)??'—'}</b></span><span class="statPill">RS21<b>${num(l.rs21)??'—'}</b></span><span class="statPill">Group<b>${esc(l.group_phase||'—')}</b></span></div>`:'';
  if(!o){return`<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(ticker)}</div><div class="selectedName">${esc(name)} · ${esc(sector)} · ${esc(industry)}</div></div><div class="selectedPrice"><b>${u?.price?money(u.price):'—'}</b><span>Universe price</span></div></div><div class="selectedBadges">${leaderBadge(l)}<span class="badge bLow">Options未取得</span></div>${leaderStats}<div class="noData"><strong>銘柄は存在します。</strong>この銘柄の有効なOptions観測はまだありません。検索失敗ではありません。次回の広域スキャンまたは詳細取得対象に入った後、支持・Flip・Call Wallを表示します。</div></article>`}
  const c=o.current,sv=signalView(o),decision=l?`Leadership上位。${thesis(o)}`:thesis(o);const reasons=(o.reasons||[]).map(x=>`<span class="reason">${esc(x)}</span>`).join('');
  return`<article class="selectedCard"><div class="selectedTop"><div><div class="selectedTicker">${esc(ticker)}</div><div class="selectedName">${esc(name)} · ${esc(sector)} · ${esc(industry)}</div></div><div class="selectedPrice"><b>${money(c.spot)}</b><span>Options観測 ${esc(c.date||'—')}</span></div></div><div class="selectedBadges">${leaderBadge(l)}<span class="badge ${sv.cls}">${sv.label} · ${o.score}</span></div><div class="decision"><label>結論</label><div>${esc(decision)}</div></div><div class="bigLevels"><div class="bigLv"><span>現在</span><b>${money(c.spot)}</b><small>Spot</small></div><div class="bigLv"><span>支持候補</span><b>${money(c.put_wall)}</b><small>${esc(distText(c.put_wall,c))}</small></div><div class="bigLv"><span>Gamma Flip</span><b>${money(c.gamma_flip)}</b><small>${esc(distText(c.gamma_flip,c))}</small></div><div class="bigLv"><span>上値壁</span><b>${money(c.call_wall)}</b><small>${esc(distText(c.call_wall,c))}</small></div></div><div class="scenario"><div class="scenarioBox"><label>上方向で見る条件</label><div>${esc(o.plan.entry)}</div></div><div class="scenarioBox"><label>強気シナリオ解除</label><div>${esc(o.plan.invalid)}</div></div></div>${leaderStats}<details class="moreInfo"><summary>詳しい根拠を見る</summary>${detailMetrics(o)}<div class="reasonRow">${reasons}</div><div class="miniMeta">Source ${esc(o.source)} · expiry ${esc(c.expiry||'—')} · confidence ${esc(c.confidence||'—')} · age ${o.age_days??'—'}日</div></details></article>`;
}
function selectTicker(ticker,scroll){
  ticker=String(ticker||'').trim().toUpperCase();if(!ticker)return;$('#selected').innerHTML=selectedHtml(ticker);$('#selectedSection').hidden=false;$('#search').value=ticker;hideSuggestions();if(scroll)$('#selectedSection').scrollIntoView({behavior:'smooth',block:'start'});
}

function matches(q){
  q=q.trim().toLowerCase();if(!q)return[];const exact=[],prefix=[],other=[];
  for(const u of universe){const t=u.ticker.toLowerCase(),hay=`${u.name} ${u.sector} ${u.industry}`.toLowerCase();if(t===q)exact.push(u);else if(t.startsWith(q))prefix.push(u);else if(hay.includes(q))other.push(u)}
  return [...exact,...prefix,...other].slice(0,10);
}
function showSuggestions(){
  const box=$('#suggestions'),rows=matches($('#search').value);activeSuggestion=-1;if(!rows.length){box.hidden=true;box.innerHTML='';return}
  box.innerHTML=rows.map((u,i)=>`<div class="suggestion" data-ticker="${esc(u.ticker)}" data-i="${i}"><strong>${esc(u.ticker)}</strong><span>${esc(u.name)}</span><small>${esc(u.sector)}</small></div>`).join('');box.hidden=false;
  for(const el of box.querySelectorAll('.suggestion'))el.addEventListener('click',()=>selectTicker(el.dataset.ticker,true));
}
function hideSuggestions(){const b=$('#suggestions');b.hidden=true;b.innerHTML='';activeSuggestion=-1}
function runSearch(){const q=$('#search').value.trim();if(!q)return;const t=q.toUpperCase();if(universeMap[t]||optionMap[t]||leaderMap[t])selectTicker(t,true);else{const m=matches(q);if(m[0])selectTicker(m[0].ticker,true);else{$('#selected').innerHTML='<div class="noData"><strong>見つかりません</strong>入力したTicker / 会社名 / Sectorはユニバースにありません。</div>';$('#selectedSection').hidden=false;hideSuggestions()}}}

async function init(){
  try{
    const [uniText,pos,dhText,shText,leaders]=await Promise.all([
      getText('uni'),getJson('pos').catch(()=>({tickers:{}})),getText('dh').catch(()=>''),getText('sh').catch(()=>''),getJson('leaders').catch(()=>null)
    ]);
    parseUniverse(parseCsv(uniText));
    buildOptionMap(pos,parseCsv(dhText),parseCsv(shText));
    leaderMap=leaders?collectLeaders(leaders):{};leaderMeta=leaders||{};
    renderLeaders();renderBullish();renderAll();
    $('#leaderAsOf').textContent=(leaders&&leaders.leadership_market&&leaders.leadership_market.asof)||String(leaders&&leaders.leadership_generated_at||'—').slice(0,10);
    $('#optionsAsOf').textContent=String(pos.asof||'—').slice(0,10);
    const lm=leaders&&leaders.leadership_market;$('#marketState').textContent=lm?`${lm.status||'—'}${lm.label?' / '+lm.label:''}`:'—';
    $('#stamp').textContent=`Universe ${universe.length.toLocaleString()} / Options観測 ${records.length.toLocaleString()} / Leaders ${Object.keys(leaderMap).length.toLocaleString()}`;
  }catch(e){console.error(e);$('#leaders').innerHTML=`<div class="noData"><strong>データ読み込み失敗</strong>${esc(e.message||e)}</div>`;$('#bullish').innerHTML='';$('#stamp').textContent='load error'}
}

$('#search').addEventListener('input',showSuggestions);
$('#search').addEventListener('keydown',e=>{
  const box=$('#suggestions'),items=[...box.querySelectorAll('.suggestion')];
  if(e.key==='ArrowDown'&&items.length){e.preventDefault();activeSuggestion=(activeSuggestion+1)%items.length;items.forEach((x,i)=>x.classList.toggle('active',i===activeSuggestion));}
  else if(e.key==='ArrowUp'&&items.length){e.preventDefault();activeSuggestion=(activeSuggestion-1+items.length)%items.length;items.forEach((x,i)=>x.classList.toggle('active',i===activeSuggestion));}
  else if(e.key==='Enter'){e.preventDefault();if(activeSuggestion>=0&&items[activeSuggestion])selectTicker(items[activeSuggestion].dataset.ticker,true);else runSearch();}
  else if(e.key==='Escape')hideSuggestions();
});
$('#searchBtn').addEventListener('click',runSearch);
$('#closeSelected').addEventListener('click',()=>{$('#selectedSection').hidden=true});
document.addEventListener('click',e=>{if(!e.target.closest('.searchBox'))hideSuggestions()});

init();
})();

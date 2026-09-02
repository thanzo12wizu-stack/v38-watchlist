'use strict';
(async function unifiedSemanticGuard(){
  const q=(s,r=document)=>r.querySelector(s);
  const qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const isNum=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
  const n=v=>isNum(v)?Number(v):null;
  const fmt=(v,d=1)=>isNum(v)?Number(v).toFixed(d):'—';
  const pct=(v,d=1)=>isNum(v)?`${Number(v)>=0?'+':''}${Number(v).toFixed(d)}%`:'—';
  const tone=v=>isNum(v)?(Number(v)>0?'pos':Number(v)<0?'neg':''):'';
  const modeJa=m=>({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m||'').toUpperCase()]||m||'—';
  const pill=(text,kind='')=>`<span class="u-pill ${kind}">${esc(text)}</span>`;
  const card=(title,sub,body)=>`<div class="card"><h2>${title}</h2>${sub?`<div class="sub">${sub}</div>`:''}${body}</div>`;
  const waitFor=async(fn,tries=120)=>{for(let i=0;i<tries;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,100));}return null};
  const heading=el=>q('h1,h2,h3',el)?.textContent?.trim()||'';

  const ready=await waitFor(()=>q('#u-nav')&&q('#u-stocks')&&q('#u-manage-body')&&q('#u-detail-body'));
  if(!ready)return;

  let v=null,rot=null;
  try{v=await fetch('v38-live-state.json?guard='+Date.now(),{cache:'no-store'}).then(r=>r.ok?r.json():null)}catch(_){ }
  try{rot=await fetch('https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json',{cache:'no-store'}).then(r=>r.ok?r.json():null)}catch(_){ }

  // 1) 実保有とモデル追跡をUI上でも完全に分離する。
  const manageTab=q('#u-nav button[data-u="manage"]');
  if(manageTab)manageTab.textContent='実保有 / RSI';
  const actualPanel=q('#u-manage-body > .u-panel[data-m="actual"]');
  if(actualPanel){
    qa(':scope > .u-alert',actualPanel).forEach(el=>el.remove());
    const h2=q('.card h2',actualPanel);
    if(h2&&!/実保有/.test(h2.textContent||''))h2.textContent='実保有';
    let hldError=null,hldItems=null;
    try{
      if(typeof window.hldLoad!=='function')throw new Error('hldLoad unavailable');
      hldItems=window.hldLoad().filter(x=>x&&x.status!=='closed');
    }catch(e){hldError=e;}
    const count=q('.card .u-grid .u-box b',actualPanel);
    if(hldError){
      if(count)count.textContent='取得エラー';
      const d=document.createElement('div');d.className='u-alert bad guard-holdings-error';d.innerHTML=`<b>実保有記録を読めません：</b>${esc(hldError.message||String(hldError))}。0件とは扱いません。`;
      actualPanel.insertBefore(d,actualPanel.firstChild);
    }else if(count&&Array.isArray(hldItems))count.textContent=`${hldItems.length}件`;
  }

  // 2) 銘柄タブは「順位」と「次回注文予定」を混同しない。
  if(v){
    const stock=q('#u-stocks');
    const m=v.market||{},mode=String(m.mode||'').toUpperCase();
    const candidates=(v.candidates||[]).filter(x=>x&&x.eligibility==='ELIGIBLE');
    const byTicker=Object.fromEntries(candidates.map(x=>[String(x.ticker||''),x]));
    const currentAlerts=stock?qa(':scope > .u-alert',stock).map(x=>x.outerHTML).join(''):'';
    if(stock&&(mode==='STOP'||mode==='DEFENSE')){
      const ranking=v.ranking||{};
      let selective=(ranking.selective_reopen_top4||[]).map(String);
      let attack=(ranking.attack_reopen_top12||[]).map(String);
      if(!selective.length)selective=[...candidates].filter(x=>isNum(x.selective_watch_rank)&&Number(x.selective_watch_rank)<=4).sort((a,b)=>Number(a.selective_watch_rank)-Number(b.selective_watch_rank)).map(x=>x.ticker);
      if(!attack.length)attack=[...candidates].filter(x=>isNum(x.attack_watch_rank)&&Number(x.attack_watch_rank)<=12).sort((a,b)=>Number(a.attack_watch_rank)-Number(b.attack_watch_rank)).map(x=>x.ticker);
      const srows=selective.map((tk,i)=>{const x=byTicker[tk]||{};return`<tr><td class="u-tk">${esc(tk)}</td><td>${x.selective_watch_rank??i+1}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${pill('再開時監視','watch')}</td></tr>`}).join('');
      const arows=attack.map((tk,i)=>{const x=byTicker[tk]||{};return`<tr><td class="u-tk">${esc(tk)}</td><td>${x.attack_watch_rank??i+1}</td><td>${fmt(x.attack_watch_score,1)}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.peer_theme_score,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${pill('再開時監視','watch')}</td></tr>`}).join('');
      stock.innerHTML=currentAlerts+`<div class="u-alert ${mode==='DEFENSE'?'bad':'warn'}"><b>現在は${esc(modeJa(mode))}：</b>以下はどちらも買いシグナルではありません。市場が復帰した場合に使う順位を、復帰先ごとに分けています。</div>`+
        card('Selective再開時 TOP4','Blue/Green + Breadth50 50〜<60%で再開した場合。RS189中心。',`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>順位</th><th>RS189</th><th>RS63</th><th>Theme</th><th>現在</th></tr></thead><tbody>${srows||'<tr><td colspan="6">候補なし</td></tr>'}</tbody></table></div>`)+
        card('Attack再開時 TOP12','Blue/Green + Breadth50 ≥60%で再開した場合。Stock70% + strict LOO Theme30%。',`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>順位</th><th>70/30 Score</th><th>RS189</th><th>Theme強度</th><th>Theme</th><th>現在</th></tr></thead><tbody>${arows||'<tr><td colspan="7">候補なし</td></tr>'}</tbody></table></div>`);
    }else if(stock&&(mode==='ATTACK'||mode==='SELECTIVE')){
      const pendingRaw=v.normal_stock_sleeve?.pending?.entries||[];
      const pending=new Set(pendingRaw.map(x=>String(typeof x==='string'?x:(x?.symbol||x?.ticker||''))).filter(Boolean));
      const held=new Set((v.normal_stock_sleeve?.positions||[]).map(x=>String(x?.symbol||'')).filter(Boolean));
      const rows=[...candidates].filter(x=>isNum(x.final_rank)).sort((a,b)=>Number(a.final_rank)-Number(b.final_rank)).slice(0,24);
      const body=rows.map(x=>{let handling=pill('監視');if(pending.has(x.ticker))handling=pill('次回寄り予定','good');else if(held.has(x.ticker))handling=pill('モデル保有中');return`<tr><td class="u-tk">${esc(x.ticker)}</td><td>${x.final_rank}</td><td>${fmt(x.rs189,1)}</td><td>${fmt(x.rs63,1)}</td><td>${esc(x.peer_theme||'—')}</td><td>${fmt(x.peer_theme_score,1)}</td><td>${handling}</td></tr>`}).join('');
      stock.innerHTML=currentAlerts+card('正式V38順位',`${modeJa(mode)} / 新規枠上限 ${m.new_entry_limit??'—'}。順位上位でも自動的に次回注文ではありません。「次回寄り予定」だけがモデル上のpending entryです。`,`<div class="u-table-wrap"><table class="ptab"><thead><tr><th class="l">銘柄</th><th>正式順位</th><th>RS189</th><th>RS63</th><th>Theme</th><th>Theme強度</th><th>扱い</th></tr></thead><tbody>${body||'<tr><td colspan="7">候補なし</td></tr>'}</tbody></table></div>`);
    }

    // Market coverageは欠損を0%と見せない。
    const market=q('#u-market');
    const breadthBox=market&&qa('.u-box',market).find(b=>/Breadth50/.test(q('span',b)?.textContent||''));
    if(breadthBox){const small=q('small',breadthBox);if(small&&!isNum(m.coverage))small.textContent='coverage —';}
    if(m.coverage_ok===false&&market&&!q('.guard-coverage',market)){
      const d=document.createElement('div');d.className='u-alert bad guard-coverage';d.innerHTML='<b>Breadth coverage不足：</b>通常個別株の新規判断はfail-closedです。';market.prepend(d);
    }

    // TQQQの取得失敗時に inactive/off と誤認させない。
    const tsec=q('#u-tqqq'),nstat=String(v.normal_tqqq?.status||''),pstat=String(v.panic_tqqq?.status||'');
    const tqqqBad=!/READY/i.test(nstat)||/DATA REQUIRED|ERROR|FAIL/i.test(nstat)||!/READY/i.test(pstat)||/DATA REQUIRED|ERROR|FAIL/i.test(pstat);
    if(tqqqBad&&tsec&&!q('.guard-tqqq-status',tsec)){
      const d=document.createElement('div');d.className='u-alert bad guard-tqqq-status';d.innerHTML=`<b>TQQQ判定データ不足：</b>Normal ${esc(nstat||'—')} / Panic ${esc(pstat||'—')}。inactive/offとは扱いません。`;tsec.prepend(d);
      const seedRow=qa('.u-row',tsec).find(r=>/Seedの有効期限/.test(q('.name',r)?.textContent||''));
      if(seedRow){const val=q('.val',seedRow);if(val)val.innerHTML=pill('判定不可','bad');}
    }
  }

  // 3) RSI Resetは監視帯と実シグナルを明示的に分ける。
  const resetPanel=q('#u-manage-body > .u-panel[data-m="reset"]');
  if(resetPanel){
    const firstCard=q('.card',resetPanel);
    if(firstCard&&!q('.u-alert.guard-reset',firstCard)){
      const note=document.createElement('div');note.className='u-alert guard-reset';note.innerHTML='<b>売買シグナルではない表示：</b>「5pt以内」「RSI30接近」は監視用です。正式Entryは RSI14≤30 を付けた後の初回上昇 + Theme内RS63 Top3確認です。';
      firstCard.insertBefore(note,firstCard.children[2]||null);
    }
  }

  // 4) Rotationの1M補助値を20日actual Flowと同列に見せない。
  if(rot){
    const rows=Object.values(rot?.observations?.rotation_buckets||{}).flat().filter(x=>x&&x.ticker);
    const rowBy=Object.fromEntries(rows.map(x=>[String(x.ticker),x]));
    const themeCard=qa('#u-rotation .card').find(c=>/Theme56 全体/.test(q('h2',c)?.textContent||''));
    if(themeCard){
      qa('tbody tr',themeCard).forEach(tr=>{
        const cells=qa('td',tr);if(cells.length<6)return;
        const tk=(cells[0].textContent||'').trim(),r=rowBy[tk];if(!r)return;
        if(!(r.flow_ready&&isNum(r.flow_20d_pct_aum))&&tk==='DRAM'&&isNum(r.flow_1m_pct_aum)){
          cells[5].textContent=`${pct(r.flow_1m_pct_aum,1)} 1M補助`;
          cells[5].className=tone(r.flow_1m_pct_aum);
          cells[5].title='標準20日actual Flowではないため、20日Flowランキングには混ぜません。';
        }
      });
    }
    const align=rot.input_alignment||{};
    const rotSec=q('#u-rotation');
    if(rotSec&&align.status&&align.status!=='OK'&&!q('.guard-alignment',rotSec)){
      const d=document.createElement('div');d.className='u-alert warn guard-alignment';
      d.innerHTML=`<b>基準日を分離：</b>Rotation ${esc(align.rotation_asof||rot.asof||'—')} / Rotation生成時のV38参照 ${esc(align.v38_asof||'—')} / 現在のV38 ${esc(v?.asof||'—')}。RotationはWHERE観測だけに使います。`;
      rotSec.insertBefore(d,rotSec.firstChild?.nextSibling||rotSec.firstChild);
    }
  }

  // 5) 旧Command Center由来の詳細を整理。有用な観測は残し、棄却済み運用は混ぜない。
  const detailNav=q('#u-detail-nav'),detailBody=q('#u-detail-body');
  if(detailNav&&detailBody){
    const labelMap={
      't-movers':'参考｜Movers','t-rs':'参考｜RS','t-weekly':'参考｜週次','t-port':'参考｜早期警戒','t-alloc':'参考｜記録'
    };
    qa('button[data-panel]',detailNav).forEach(b=>{if(labelMap[b.dataset.panel])b.textContent=labelMap[b.dataset.panel]});

    // t-port: 観測系だけ残し、旧Core12/候補36/旧Bench運用は統合版から除外。
    const port=q('.u-panel[data-panel="t-port"]',detailBody);
    if(port)qa(':scope > section > .card',port).forEach(c=>{if(/新規参入（ポート候補36位圏）|個別株スリーブ\s*Core 12|RSリーダー控え\s*Bench/i.test(heading(c)))c.classList.add('u-hidden')});

    // t-alloc: 旧Trade Planner/Position Sizing/隔週リバランスは隠し、記録系だけ残す。
    const alloc=q('.u-panel[data-panel="t-alloc"]',detailBody);
    if(alloc)qa(':scope > section > .card',alloc).forEach(c=>{if(!/エクイティ記録|エクイティカーブ/i.test(heading(c)))c.classList.add('u-hidden')});

    // 旧t-todayから有用な観測カードだけ復帰。旧Swing Focus/Playbook/Entries/Exitsは戻さない。
    const legacyToday=document.getElementById('t-today');
    if(legacyToday&&!q('button[data-panel="legacy-today"]',detailNav)){
      const allow=/銘柄検索|EPS加速|発火前|Put GEX|支えへの接触|エントリー候補ボード|Confluence|ポケットピボット|本日のピックアップ|Today's Setups|テクニカル・パターン|Chart Patterns|圧縮コイル|VCP|21EMAタッチ|VWAPタイミング|底打ち|Structure Pivot|ブレイク一覧|Signals|リーダー監視/i;
      const selected=qa(':scope > .card',legacyToday).filter(c=>allow.test(heading(c)));
      if(selected.length){
        const b=document.createElement('button');b.type='button';b.dataset.panel='legacy-today';b.textContent='参考｜個別詳細';detailNav.appendChild(b);
        const p=document.createElement('div');p.className='u-panel';p.dataset.panel='legacy-today';
        selected.forEach(c=>{c.classList.remove('u-hidden');p.appendChild(c)});detailBody.appendChild(p);
      }
    }

    qa('#u-detail-body > .u-panel').forEach(p=>{
      if(p.dataset.panel==='formal'||q(':scope > .guard-reference',p))return;
      const d=document.createElement('div');d.className='u-alert guard-reference';d.innerHTML='<b>参考表示：</b>既存Command Center由来の観測情報です。正式V38の新規許可、強制Exit、順位、TQQQ配分を上書きしません。';
      p.insertBefore(d,p.firstChild);
    });
  }

  // 6) 目視しなくても誤認・旧ルール混在を検知するruntime guard。
  const problems=[];
  const modelCard=qa('#u-manage .card h2').find(x=>/通常個別株/.test(x.textContent||''));
  if(modelCard&&!/モデル|戦略/.test(modelCard.textContent||''))problems.push('通常個別株モデル表のラベル不明確');
  if(v&&['STOP','DEFENSE'].includes(String(v.market?.mode||'').toUpperCase())&&/空き枠なら次回寄り|次回寄り予定/.test(q('#u-stocks')?.textContent||''))problems.push('新規停止中に次回寄り表示');
  const detailText=q('#u-detail-body')?.textContent||'';
  if(/隔週リバランス点検|運用ルール（確定版）\s*Playbook/i.test(detailText))problems.push('棄却済み旧運用ルールが詳細タブに残存');
  if(problems.length){
    const d=document.createElement('div');d.className='u-alert bad';d.innerHTML=`<b>統合表示監査エラー：</b>${esc(problems.join(' / '))}`;
    q('#u-today')?.prepend(d);
    console.error('UNIFIED_SEMANTIC_GUARD',problems);
  }
})();

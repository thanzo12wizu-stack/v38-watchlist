(()=>{
  const DATA_URL='https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const isNum=v=>v!==null&&v!==''&&Number.isFinite(Number(v));
  const pct=v=>{if(!isNum(v))return'—';const n=Number(v);return`${n>=0?'+':''}${n.toFixed(2)}%`};
  const money=v=>{if(!isNum(v))return'—';const n=Number(v),sg=n>=0?'+':'−',a=Math.abs(n);if(a>=1e9)return`${sg}${(a/1e9).toFixed(2)}B`;if(a>=1e6)return`${sg}${Math.round(a/1e6)}M`;return`${sg}${Math.round(a)}`};
  const findDram=d=>Object.values(d?.observations?.rotation_buckets||{}).flat().find(x=>x&&x.ticker==='DRAM');
  function patch(r){
    const rows=[...document.querySelectorAll('.market-row')];
    const row=rows.find(x=>x.querySelector('.ticker')?.textContent?.trim()==='DRAM');
    if(!row)return false;
    const state=row.querySelector('.state-text');
    if(state){state.textContent='RS189待ち';state.classList.remove('bad','good');state.classList.add('watch');state.title='2026/4/2設定。RS189と総合Price Scoreのみ履歴待ち。';}
    const price=row.querySelector('.price-col');
    if(price){price.innerHTML=`${pct(r.ret_20d_pct)}<small>20日 / RS189待ち</small>`;price.title=`設定 ${r.inception_date||'2026-04-02'} / RS63対SPY ${isNum(r.rs63_vs_spy)?pct(Number(r.rs63_vs_spy)*100):'—'}`;}
    const internal=row.querySelector('.internal-col');
    if(internal&&isNum(r.internal_score)){internal.innerHTML=`${Number(r.internal_score).toFixed(1)}<small>補助55基準</small>`;internal.title='現在の直接保有株だけで計算した補助Internal。既存55テーマの順位は再計算していません。';}
    const nums=[...row.querySelectorAll('.num')];
    const flow=nums[nums.length-1];
    if(flow&&isNum(r.flow_1m_pct_aum)){const cls=Number(r.flow_1m_pct_aum)>=0?'good':'bad';flow.innerHTML=`<span class="flowpct ${cls}">${pct(r.flow_1m_pct_aum)}</span><small>${money(r.flow_1m_usd)} / 1M実Flow</small>`;flow.title='TradingView fund_flows.1M。既存の検証済み20日Flowランキング・状態判定には混ぜていません。';}
    return true;
  }
  fetch(DATA_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}).then(d=>{
    const dram=findDram(d);if(!dram||dram.state!=='RS189_PENDING')return;
    let tries=0;const id=setInterval(()=>{tries++;if(patch(dram)||tries>=30)clearInterval(id)},200);
  }).catch(()=>{});
})();

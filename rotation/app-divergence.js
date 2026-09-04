'use strict';

(() => {
  const rootUrl = new URL('.', window.location.href);
  const diagnosticsUrl = new URL('data/rotation-theme56-divergence.json', rootUrl).href;
  const dataUrl = new URL('data/rotation-theme56.json', rootUrl).href;
  const statusUrl = new URL('data/status.json', rootUrl).href;
  const evidenceUrl = new URL('data/rotation-analysis-evidence.json', rootUrl).href;

  const esc = value => String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]);
  const finite = value => value !== null && value !== '' && Number.isFinite(Number(value));
  const num = value => finite(value) ? Number(value) : NaN;
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
      .divergence-intro{font-size:10px;color:var(--muted);max-width:920px;line-height:1.6}
      .evidence-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:10px 0 2px}
      .evidence-summary-item{border:1px solid var(--line2);border-radius:9px;padding:7px 8px;background:rgba(255,255,255,.015);min-width:0}
      .evidence-summary-item span{display:block;font-size:8px;color:var(--faint)}
      .evidence-summary-item b{display:block;font-size:10px;line-height:1.45;margin-top:2px}
      .divergence-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:11px}
      .divergence-panel{border:1px solid var(--line2);border-radius:11px;background:rgba(4,8,12,.24);padding:11px;min-width:0}
      .divergence-panel-title{font-size:11px;font-weight:820;margin-bottom:4px}
      .divergence-panel-sub{font-size:9px;color:var(--faint);margin-bottom:5px;line-height:1.5}
      .divergence-list{display:grid;gap:7px}
      .divergence-item{border-top:1px solid var(--line2);padding-top:8px;min-width:0}
      .divergence-item:first-child{border-top:0;padding-top:3px}
      .divergence-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
      .divergence-name{font-size:12px;font-weight:820;min-width:0}
      .divergence-score{font-size:9px;color:var(--faint);white-space:nowrap}
      .divergence-badges{display:flex;gap:4px;flex-wrap:wrap;margin:4px 0}
      .cause-pill,.early-pill,.evidence-pill{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:2px 6px;font-size:9px;font-weight:800;line-height:1.4}
      .cause-pill.top{color:var(--orange);border-color:rgba(231,154,98,.42);background:rgba(231,154,98,.055)}
      .cause-pill.warn{color:var(--amber);border-color:rgba(228,185,103,.4);background:rgba(228,185,103,.055)}
      .cause-pill.good{color:var(--green);border-color:rgba(119,212,158,.36);background:rgba(119,212,158,.05)}
      .cause-pill.bad{color:var(--red);border-color:rgba(223,123,123,.38);background:rgba(223,123,123,.055)}
      .cause-pill.neutral{color:var(--muted)}
      .early-pill{color:var(--accent);border-color:rgba(143,205,242,.34);background:rgba(143,205,242,.045)}
      .evidence-pill.analog-strong{color:var(--red);border-color:rgba(223,123,123,.48);background:rgba(223,123,123,.07)}
      .evidence-pill.analog-partial{color:var(--orange);border-color:rgba(231,154,98,.46);background:rgba(231,154,98,.065)}
      .evidence-pill.rejected{color:var(--faint);border-color:#3b4652;background:rgba(255,255,255,.02)}
      .evidence-pill.diagnostic{color:var(--amber);border-color:rgba(228,185,103,.34);background:rgba(228,185,103,.04)}
      .evidence-pill.descriptive{color:var(--muted)}
      .divergence-evidence-note{font-size:9px;color:var(--muted);line-height:1.55;margin:5px 0 2px}
      .divergence-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin-top:5px}
      .divergence-metric{border:1px solid var(--line2);border-radius:7px;padding:5px 6px;min-width:0}
      .divergence-metric span{display:block;font-size:8px;color:var(--faint)}
      .divergence-metric b{display:block;font-size:10px;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .driver-line{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
      .driver-chip{font-size:8px;color:var(--muted);border:1px solid var(--line2);border-radius:6px;padding:2px 5px}
      .theme-diagnostic-line{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin:3px 0 2px}
      .theme-diagnostic-line small{font-size:8px;color:var(--faint)}
      .divergence-method{margin-top:9px;font-size:9px;color:var(--faint);line-height:1.55}
      @media(max-width:760px){.divergence-columns{grid-template-columns:1fr}.divergence-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-summary{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function causeTone(key) {
    if (['TOP_WEIGHT_LED_NARROW','STRONG_TOP_HEAVY'].includes(key)) return 'top';
    if (['PRICE_LEAD_NARROW','PRICE_HOLD_INTERNAL_ROLLOVER','STRONG_ROLLING_OVER','MIXED_ROLLOVER'].includes(key)) return 'warn';
    if (['BROAD_STRENGTH'].includes(key)) return 'good';
    if (['BROAD_WEAK'].includes(key)) return 'bad';
    return 'neutral';
  }

  function causeLabel(cause) {
    const key=String(cause?.key||'');
    return ({
      TOP_WEIGHT_LED_NARROW:'上位構成銘柄主導・広がり不足',
      STRONG_TOP_HEAVY:'現在強いが上位構成銘柄寄与大',
      PRICE_LEAD_NARROW:'ETF価格先行・構成株の広がり不足',
      PRICE_HOLD_INTERNAL_ROLLOVER:'ETF価格維持・内部参加低下',
      STRONG_ROLLING_OVER:'20日強いが直近参加低下',
      MIXED_ROLLOVER:'混合状態・直近参加低下',
      BROAD_INTERNAL_IGNITION:'構成株の短期参加拡大',
      INTERNAL_LEAD:'構成株参加先行・ETF追随未確認',
      BROAD_STRENGTH:'現在は広く強い',
      WEAK_EARLY_RECOVERY:'まだ弱いが短期参加改善',
      MIXED_EARLY:'混合状態・短期参加改善',
      BROAD_WEAK:'価格・構成株とも弱い',
      PRICE_LEAD_MIXED:'ETF価格先行・原因は混合',
      MIXED:'価格・構成株の方向が混合'
    })[key] || String(cause?.label||'原因未分類');
  }

  function earlyView(early) {
    const key=String(early?.key||'');
    const mapped=({
      IGNITION_5D:['5日参加拡大（観測）',0],
      EXPANSION_10D:['10日参加拡大（観測）',1],
      SHORT_LEAD:['短期参加改善・20日未確認',2],
      BUILDING:['短期参加改善（観測）',3],
      CONFIRMED_20D:['20日まで広がり確認（現在状態）',8],
      ROLLING_OVER_5D:['20日強い / 直近5日参加低下',9],
      ROLLING_OVER_10D:['20日強い / 直近10日参加低下',10],
      MIXED_SHORT:['短期は移行中',7],
      WEAK_SHORT:['短期の広がり弱い',7]
    })[key];
    return {key,label:mapped?.[0]||String(early?.label||'短期未取得'),priority:mapped?.[1]??7};
  }

  function causePriority(key) {
    return ({TOP_WEIGHT_LED_NARROW:0,PRICE_HOLD_INTERNAL_ROLLOVER:1,PRICE_LEAD_NARROW:2,STRONG_TOP_HEAVY:3,STRONG_ROLLING_OVER:4,INTERNAL_LEAD:6,WEAK_EARLY_RECOVERY:7,MIXED_EARLY:8,MIXED_ROLLOVER:9})[key] ?? 20;
  }

  function horizon(diag,h) { return diag?.horizons?.[String(h)] || {}; }

  function evidenceView(row,evidence) {
    const p=num(row?.price_score), i=num(row?.internal_score), d=num(row?.internal_delta20), f=num(row?.flow_20d_pct_aum);
    const flowReady=Boolean(row?.flow_ready) && Number.isFinite(f);
    const patterns=evidence?.patterns||{};
    if (flowReady && p>=70 && i<50 && f<=0) {
      const x=patterns.DISTRIBUTION_TRAP_11SECTOR||{};
      return {key:'DISTRIBUTION_ANALOG',priority:0,css:'analog-strong',badge:'11セクターPIT類似・強警戒',label:'分配トラップ型（Theme56外挿）',note:`同型の11セクターPITは20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}。Theme56自体はPIT未検証なので、売却シグナルではなく警戒Context。`};
    }
    if (flowReady && p>=70 && Number.isFinite(d) && d<=-20 && f<=0) {
      const x=patterns.DISTRIBUTION_DETERIORATION_11SECTOR||{};
      return {key:'DETERIORATION_ANALOG',priority:1,css:'analog-partial',badge:'11セクターPIT類似・中期警戒',label:'内部急落型（Theme56外挿）',note:`同型の11セクターPITは20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}。20D block CIは0跨ぎ、40Dは両CI負。Theme56では外挿Contextのみ。`};
    }
    if (flowReady && p<60 && i>=50 && Number.isFinite(d) && d>=10 && f>=0) {
      const x=patterns.EARLY_ROTATION_11SECTOR||{};
      return {key:'EARLY_REJECTED',priority:3,css:'rejected',badge:'PITで買い優位否定',label:'内部改善先行・価格追随待ち',note:`11セクターPITのEarly Rotationは20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}で買い優位を再現せず。短期改善だけで「初動候補」に昇格しない。`};
    }
    if (flowReady && p>=70 && i>=60 && f>=0) {
      const x=patterns.CONFIRMED_ACCUMULATION_11SECTOR||{};
      return {key:'CURRENT_STRENGTH_REJECTED',priority:4,css:'rejected',badge:'PITで将来優位未確認',label:'現在は強い（予測シグナルではない）',note:`11セクターPITの強い価格＋強い内部＋Flow流入は20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}。現在の強さはそのまま将来Alphaと解釈しない。`};
    }
    if (flowReady && p>=60 && i>=60 && f<0) {
      const x=patterns.REDEMPTION_DIVERGENCE_11SECTOR||{};
      return {key:'REDEMPTION_DIAGNOSTIC',priority:5,css:'diagnostic',badge:'PIT診断・方向断定なし',label:'価格・内部は強いがETF純流出',note:`11セクターPITでは20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}だが、頑健な売りシグナルとは確認されず。「売り抜け」と断定しない。`};
    }
    if (flowReady && p>=60 && p<70 && i>=60 && f>=0) {
      const x=patterns.HIDDEN_ACCUMULATION_11SECTOR||{};
      return {key:'HIDDEN_REJECTED',priority:6,css:'rejected',badge:'PITで買い優位否定',label:'内部は強いが価格確認前',note:`11セクターPITのHidden Accumulationは20D ${pct(x.confirmation_2024_plus?.mean_excess_20d_pct,2)}、40D ${pct(x.confirmation_2024_plus?.mean_excess_40d_pct,2)}。先回り買いの根拠にはしない。`};
    }
    return {key:'DESCRIPTIVE',priority:20,css:'descriptive',badge:'観測のみ',label:'現在状態の説明',note:'この組合せに対応する頑健なTheme56 PIT予測結果はありません。5D/10D・構成比・内部差は原因理解と状態変化の観測にだけ使います。'};
  }

  function drivers(diag) {
    const top=diag?.concentration?.top_holdings||[];
    return top.slice(0,5).map(x=>`<span class="driver-chip">${esc(x.symbol)} ${finite(x.weight_pct)?fmt(x.weight_pct,1)+'%':'—'} / 5D ${pct(x.ret_5d_pct,1)}</span>`).join('');
  }

  function itemMarkup(diag,row,evidence) {
    const h5=horizon(diag,5),h10=horizon(diag,10),h20=horizon(diag,20);
    const conc=diag.concentration||{},cause=diag.divergence_cause||{},early=earlyView(diag.early_phase||{}),ev=evidenceView(row,evidence);
    const top5=finite(conc.top5_weight_pct)?`${fmt(conc.top5_weight_pct,1)}%`:'—';
    const move=finite(h5.top5_abs_move_share_pct)?`${fmt(h5.top5_abs_move_share_pct,0)}%`:'—';
    return `<div class="divergence-item">
      <div class="divergence-head"><div class="divergence-name">${esc(row?.ticker||diag.ticker)}${row?.label?`｜${esc(row.label)}`:''}</div><div class="divergence-score">価格 ${fmt(row?.price_score,0)} / 構成 ${fmt(row?.internal_score,0)}</div></div>
      <div class="divergence-badges"><span class="cause-pill ${causeTone(cause.key)}">${esc(causeLabel(cause))}</span><span class="early-pill">${esc(early.label)}</span><span class="evidence-pill ${esc(ev.css)}">${esc(ev.badge)}</span></div>
      <div class="divergence-evidence-note"><b>${esc(ev.label)}</b> — ${esc(ev.note)}</div>
      <div class="divergence-metrics">
        <div class="divergence-metric"><span>上位5構成比</span><b>${esc(top5)}</b></div>
        <div class="divergence-metric"><span>5D 上昇銘柄率</span><b>${pct(h5.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>10D 上昇銘柄率</span><b>${pct(h10.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>20D 上昇銘柄率</span><b>${pct(h20.positive_breadth_pct,0)}</b></div>
        <div class="divergence-metric"><span>Internal 20D変化</span><b>${pct(row?.internal_delta20,1)}</b></div>
        <div class="divergence-metric"><span>20D Flow / AUM</span><b>${pct(row?.flow_20d_pct_aum,2)}</b></div>
        <div class="divergence-metric"><span>5D 中央値</span><b>${pct(h5.median_return_pct,1)}</b></div>
        <div class="divergence-metric"><span>10D 中央値</span><b>${pct(h10.median_return_pct,1)}</b></div>
        <div class="divergence-metric"><span>上位5 値動き集中</span><b>${esc(move)}</b></div>
        <div class="divergence-metric"><span>実効銘柄数</span><b>${finite(conc.effective_holdings)?fmt(conc.effective_holdings,1):'—'}</b></div>
      </div>
      ${drivers(diag)?`<div class="driver-line">${drivers(diag)}</div>`:''}
    </div>`;
  }

  function evidenceSummaryMarkup(evidence) {
    const d=evidence?.patterns?.DISTRIBUTION_TRAP_11SECTOR||{},dd=evidence?.patterns?.DISTRIBUTION_DETERIORATION_11SECTOR||{},er=evidence?.patterns?.EARLY_ROTATION_11SECTOR||{};
    return `<div class="evidence-summary">
      <div class="evidence-summary-item"><span>PITで再現</span><b>分配トラップ：20D ${pct(d.confirmation_2024_plus?.mean_excess_20d_pct,2)} / 40D ${pct(d.confirmation_2024_plus?.mean_excess_40d_pct,2)}</b></div>
      <div class="evidence-summary-item"><span>部分支持</span><b>内部急落型：40D ${pct(dd.confirmation_2024_plus?.mean_excess_40d_pct,2)}。20D block CIは0跨ぎ</b></div>
      <div class="evidence-summary-item"><span>先回り買いは不採用</span><b>Early Rotation：20D ${pct(er.confirmation_2024_plus?.mean_excess_20d_pct,2)} / 40D ${pct(er.confirmation_2024_plus?.mean_excess_40d_pct,2)}</b></div>
    </div>`;
  }

  function ensureSection(evidence) {
    let section=document.getElementById('divergenceAnalysisCard');
    if (section) return section;
    const anchor=document.querySelector('.change-card');
    if (!anchor) return null;
    section=document.createElement('div');
    section.id='divergenceAnalysisCard';
    section.className='card s12 divergence-card';
    section.innerHTML=`<div class="section-head"><div><div class="eyebrow">BACKTEST-AWARE ROTATION</div><h2>バックテスト整合のRotation分析</h2><div class="divergence-intro">5日/10日の動きは「早期シグナル」ではなく短期参加の観測として表示します。将来差を強く示すのはPITで再現した条件だけです。11セクターPITの結果をTheme56へ使う場合は必ず「外挿」と明示し、売買ルールにはしません。</div></div></div>${evidenceSummaryMarkup(evidence)}<div class="divergence-columns"><div class="divergence-panel"><div class="divergence-panel-title">5日 / 10日 / 20日の参加変化</div><div class="divergence-panel-sub">20日になる前の変化は見えるように残す。ただし短期RSの追加予測力はバックテストで支持されなかったため、先回り買いには使わない。</div><div id="earlyMotionList" class="divergence-list"></div></div><div class="divergence-panel"><div class="divergence-panel-title">チグハグの原因 + 証拠レベル</div><div class="divergence-panel-sub">価格・構成株・Flow・上位構成銘柄寄与を分け、「過去検証で何が言えるか」まで同時表示。</div><div id="divergenceCauseList" class="divergence-list"></div></div></div><div class="divergence-method">証拠レベル：11セクターPITで再現 / PIT部分支持 / PITで買い優位否定 / 診断のみ / 観測のみ。Theme56の構成比・5D/10D breadth・上位銘柄寄与は現在の原因説明であり、Theme56固有の将来Alphaを主張しません。</div>`;
    anchor.insertAdjacentElement('afterend',section);
    return section;
  }

  function annotateThemeRows(diagByTicker,rowsByTicker,evidence) {
    document.querySelectorAll('#themeList .theme-row[data-ticker]').forEach(node=>{
      const ticker=String(node.dataset.ticker||'').toUpperCase();
      const diag=diagByTicker.get(ticker),row=rowsByTicker.get(ticker);
      if (!diag||diag.status!=='READY'||!row) return;
      const state=node.querySelector('.theme-state');
      if (!state) return;
      let line=state.querySelector('.theme-diagnostic-line');
      if (!line) {
        line=document.createElement('div');
        line.className='theme-diagnostic-line';
        const trajectory=state.querySelector('.trajectory-line');
        if (trajectory) trajectory.insertAdjacentElement('afterend',line); else state.appendChild(line);
      }
      const cause=diag.divergence_cause||{},early=earlyView(diag.early_phase||{}),ev=evidenceView(row,evidence);
      line.innerHTML=`<span class="cause-pill ${causeTone(cause.key)}">${esc(causeLabel(cause))}</span><span class="early-pill">${esc(early.label)}</span><span class="evidence-pill ${esc(ev.css)}">${esc(ev.badge)}</span>`;
    });
  }

  function applyEvidenceLanguage() {
    const strong=document.querySelector('.focus-strong .focus-label');
    const improve=document.querySelector('.focus-improve .focus-label');
    const bad=document.querySelector('.focus-bad .focus-label');
    if (strong) strong.innerHTML='<span>●</span> 現在強い（観測）';
    if (improve) improve.innerHTML='<span>↗</span> 構成株20日改善（観測）';
    if (bad) bad.innerHTML='<span>↘</span> 構成株20日悪化（観測）';
    const changeSub=document.querySelector('.change-card .section-head .sub');
    if (changeSub) changeSub.textContent='20日改善・悪化は状態変化として確認。将来優位はバックテスト証拠を別に見る。';
    const up=document.querySelector('.change-up .change-column-title');
    const down=document.querySelector('.change-down .change-column-title');
    if (up) up.textContent='20日で内部参加が改善';
    if (down) down.textContent='20日で内部参加が悪化';
    const sentence=document.getElementById('heroSentence');
    if (sentence && sentence.textContent && !sentence.textContent.includes('短期変化だけ')) sentence.textContent += ' 短期変化だけでは将来優位を主張しません。';
  }

  function renderSection(diags,rowsByTicker,evidence) {
    const section=ensureSection(evidence);
    if (!section) return false;
    const ready=diags.filter(x=>x&&x.status==='READY');
    const early=ready.filter(x=>['IGNITION_5D','EXPANSION_10D','SHORT_LEAD','BUILDING','ROLLING_OVER_5D','ROLLING_OVER_10D'].includes(x.early_phase?.key))
      .sort((a,b)=>earlyView(a.early_phase).priority-earlyView(b.early_phase).priority || Number(horizon(b,5).positive_breadth_pct||0)-Number(horizon(a,5).positive_breadth_pct||0)).slice(0,8);
    const evidenceFirst=ready.map(x=>({diag:x,row:rowsByTicker.get(String(x.ticker).toUpperCase())})).filter(x=>x.row).sort((a,b)=>evidenceView(a.row,evidence).priority-evidenceView(b.row,evidence).priority || causePriority(a.diag.divergence_cause?.key)-causePriority(b.diag.divergence_cause?.key));
    const mismatch=evidenceFirst.filter(x=>evidenceView(x.row,evidence).priority<20 || causePriority(x.diag.divergence_cause?.key)<20).slice(0,8);
    const earlyHost=document.getElementById('earlyMotionList'),causeHost=document.getElementById('divergenceCauseList');
    if (earlyHost) earlyHost.innerHTML=early.length?early.map(x=>itemMarkup(x,rowsByTicker.get(String(x.ticker).toUpperCase()),evidence)).join(''):'<div class="sub">目立つ短期参加変化なし</div>';
    if (causeHost) causeHost.innerHTML=mismatch.length?mismatch.map(x=>itemMarkup(x.diag,x.row,evidence)).join(''):'<div class="sub">大きなチグハグは限定的</div>';
    return true;
  }

  async function enhance() {
    const [diag,data,status,evidence]=await Promise.all([getJson(diagnosticsUrl),getJson(dataUrl),getJson(statusUrl),getJson(evidenceUrl)]);
    const asof=String(status.asof||'');
    if (diag.status!=='READY'||!asof||String(diag.asof||'')!==asof||String(data.asof||'')!==asof) return false;
    const rows=allRows(data);
    if (!rows.length||!document.querySelector('#themeList .theme-row')) return false;
    ensureStyles();
    const rowsByTicker=new Map(rows.map(x=>[String(x.ticker||'').toUpperCase(),x]));
    const diags=diag.themes||[];
    const diagByTicker=new Map(diags.map(x=>[String(x.ticker||'').toUpperCase(),x]));
    applyEvidenceLanguage();
    annotateThemeRows(diagByTicker,rowsByTicker,evidence);
    return renderSection(diags,rowsByTicker,evidence);
  }

  let attempts=0;
  const run=async()=>{
    attempts+=1;
    try { if (await enhance()) return; } catch (_) {}
    if (attempts<12) window.setTimeout(run,400);
  };
  window.setTimeout(run,350);
})();

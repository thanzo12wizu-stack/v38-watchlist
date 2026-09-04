'use strict';

(() => {
  const nativeFetch = window.fetch.bind(window);
  const mainRaw = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/';
  const prodData = new URL('data/rotation-theme56.json', window.location.href).href;
  const prodStatus = new URL('data/status.json', window.location.href).href;
  const prodContext = new URL('data/rotation-theme56-stock-context.json', window.location.href).href;
  const legacyBriefNeedle = '/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const legacyContextNeedle = '/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';
  let stockDetailIndex = new Map();

  function requestUrl(input) {
    if (typeof input === 'string') return input;
    if (input && typeof input.url === 'string') return input.url;
    return String(input || '');
  }

  async function readJson(url) {
    const response = await nativeFetch(url, {cache: 'no-store'});
    if (!response.ok) throw new Error(`${url} HTTP ${response.status}`);
    return response.json();
  }

  async function contextFallback() {
    let asof = null;
    try { asof = (await readJson(prodStatus)).asof || null; } catch (_) {}
    return new Response(JSON.stringify({
      schema: 'rotation-production-context-1',
      status: 'DATA REQUIRED',
      asof,
      context_scope: 'PRODUCTION_LEADERSHIP_CONTEXT_NOT_READY',
      leadership_coverage: {market_asof: null},
      industry_context: [],
      note: 'Stale research Leadership context is intentionally not displayed.'
    }), {status: 200, headers: {'Content-Type': 'application/json'}});
  }

  async function fetchReadyContext(init) {
    try {
      const [contextResponse, statusResponse] = await Promise.all([
        nativeFetch(prodContext, {...(init || {}), cache: 'no-store'}),
        nativeFetch(prodStatus, {cache: 'no-store'})
      ]);
      if (!contextResponse.ok || !statusResponse.ok) return null;
      const [context, status] = await Promise.all([contextResponse.json(), statusResponse.json()]);
      const contextAsof = String(context.asof || context.leadership_coverage?.market_asof || context.leadership_market?.asof || '');
      const rotationAsof = String(status.asof || '');
      const contextReady = context.status ? context.status === 'READY' : context.research_only === false;
      if (!(contextReady && contextAsof && rotationAsof && contextAsof === rotationAsof)) return null;
      return new Response(JSON.stringify(context), {status: 200, headers: {'Content-Type': 'application/json'}});
    } catch (_) {
      return null;
    }
  }

  window.fetch = async function(input, init) {
    const url = requestUrl(input);
    if (url.includes(legacyBriefNeedle)) return nativeFetch(prodData, {...(init || {}), cache: 'no-store'});
    if (url.includes(legacyContextNeedle)) {
      const ready = await fetchReadyContext(init);
      return ready || contextFallback();
    }
    return nativeFetch(input, init);
  };

  function warningNode() {
    const host = document.getElementById('error');
    if (!host) return null;
    let node = document.getElementById('freshnessWarning');
    if (!node) {
      node = document.createElement('div');
      node.id = 'freshnessWarning';
      node.className = 'error';
      host.prepend(node);
    }
    return node;
  }

  async function applyFreshnessGuard() {
    const node = warningNode();
    try {
      const [status, live, command] = await Promise.all([
        readJson(prodStatus), readJson(mainRaw + 'v38-live-state.json'), readJson(mainRaw + 'state.json')
      ]);
      const expected = String(command.date || '');
      const rot = String(status.asof || '');
      const v38 = String(live.asof || '');
      const ready = status.status === 'READY' && expected && rot === expected && v38 === expected;
      if (!ready) {
        if (node) {
          node.hidden = false;
          node.textContent = `更新遅延：Command Center ${expected || '—'} / V38 ${v38 || '—'} / Rotation ${rot || '—'}。日付が揃うまでRotationの数値は最新扱いしません。`;
        }
      } else if (node) {
        node.hidden = true;
        node.textContent = '';
      }
    } catch (_) {
      if (node) {
        node.hidden = false;
        node.textContent = '更新状況を確認できません。Rotationの数値を最新扱いしないでください。';
      }
    }

    try {
      const ctx = await fetchReadyContext({cache: 'no-store'});
      if (!ctx) {
        const scope = document.getElementById('leaderScope');
        const leaders = document.getElementById('leaders');
        if (scope) scope.textContent = 'Leadership照合 更新待ち';
        if (leaders) leaders.innerHTML = '<div class="sub">現在のRotationと同じ基準日のLeadership照合がREADYになるまで、強い株は表示しません。</div>';
      }
    } catch (_) {}
  }

  function esc(value) {
    return String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch]);
  }

  function finite(value) { return Number.isFinite(Number(value)); }
  function fmt(value, digits = 1, signed = false) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${signed && n > 0 ? '+' : ''}${n.toFixed(digits)}`;
  }
  function pct(value, digits = 1) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`;
  }
  function roleJa(value) { return ({PIONEER:'先導株',LEADER:'主導株'})[String(value || '').toUpperCase()] || String(value || '—'); }
  function phaseJa(value) { return ({EMERGING:'新興',LEADING:'主導',MATURE:'成熟',LOSING:'失速'})[String(value || '').toUpperCase()] || String(value || '—'); }
  function breakoutJa(value) {
    const v = String(value || '').toUpperCase();
    if (!v || v === 'NONE') return '未発火';
    return ({READY:'発火目前',BREAKOUT:'ブレイクアウト',ALREADY_BROKE:'発火済み'})[v] || v;
  }

  function internalLevel(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return {key:'na', label:'未取得'};
    if (n >= 60) return {key:'strong', label:'強'};
    if (n < 45) return {key:'weak', label:'弱'};
    return {key:'mid', label:'中立'};
  }

  function trajectory(row) {
    const current = Number(row?.internal_score);
    const delta = Number(row?.internal_delta20);
    if (!Number.isFinite(current) || !Number.isFinite(delta)) {
      return {key:'na', tone:'neutral', label:'方向未取得', current:Number.isFinite(current)?current:null, previous:null, delta:null, up:false, down:false, priority:99};
    }
    const previous = Math.max(0, Math.min(100, current - delta));
    const now = internalLevel(current);
    const before = internalLevel(previous);
    const up = delta >= 10;
    const down = delta <= -10;

    if (before.key === 'weak' && now.key === 'strong') return {key:'weak_to_strong',tone:'turn',label:'弱→強へ急浮上',current,previous,delta,up:true,down:false,priority:0};
    if (before.key === 'weak' && now.key === 'mid') return {key:'weak_to_mid',tone:'turn',label:'弱→中立へ改善',current,previous,delta,up:true,down:false,priority:1};
    if (before.key === 'weak' && now.key === 'weak' && up) return {key:'bottom_recovery',tone:'turn',label:'最弱圏から改善中',current,previous,delta,up:true,down:false,priority:2};
    if (before.key === 'mid' && now.key === 'strong') return {key:'mid_to_strong',tone:'good',label:'中立→強へ浮上',current,previous,delta,up:true,down:false,priority:3};
    if (now.key === 'strong' && up) return {key:'strong_expanding',tone:'good',label:'強い・さらに改善',current,previous,delta,up:true,down:false,priority:4};
    if (now.key === 'mid' && up) return {key:'mid_recovery',tone:'turn',label:'中立圏で改善中',current,previous,delta,up:true,down:false,priority:5};

    if (before.key === 'strong' && now.key === 'weak') return {key:'strong_to_weak',tone:'bad',label:'強→弱へ急悪化',current,previous,delta,up:false,down:true,priority:0};
    if (before.key === 'strong' && now.key === 'mid') return {key:'strong_to_mid',tone:'risk',label:'強→中立へ悪化',current,previous,delta,up:false,down:true,priority:1};
    if (before.key === 'strong' && now.key === 'strong' && down) return {key:'strong_eroding',tone:'risk',label:'強いが悪化中',current,previous,delta,up:false,down:true,priority:2};
    if (before.key === 'mid' && now.key === 'weak') return {key:'mid_to_weak',tone:'bad',label:'中立→弱へ悪化',current,previous,delta,up:false,down:true,priority:3};
    if (now.key === 'mid' && down) return {key:'mid_eroding',tone:'risk',label:'中立圏で悪化中',current,previous,delta,up:false,down:true,priority:4};
    if (now.key === 'weak' && down) return {key:'weak_falling',tone:'bad',label:'弱い・さらに悪化',current,previous,delta,up:false,down:true,priority:5};

    if (now.key === 'strong') return {key:'strong_hold',tone:'good',label:'強い・高位維持',current,previous,delta,up:false,down:false,priority:6};
    if (now.key === 'weak') return {key:'weak_stalled',tone:'bad',label:'弱い・低位停滞',current,previous,delta,up:false,down:false,priority:8};
    return {key:'mid_flat',tone:'neutral',label:'中立・横ばい',current,previous,delta,up:false,down:false,priority:7};
  }

  function ensureRuntimeStyles() {
    if (document.getElementById('rotationRuntimeStyles')) return;
    const style = document.createElement('style');
    style.id = 'rotationRuntimeStyles';
    style.textContent = `
      .stock-pill[data-stock-detail-key]{cursor:pointer;user-select:none;transition:border-color .15s ease,background .15s ease;outline:none}
      .stock-pill[data-stock-detail-key]:focus-visible{border-color:var(--accent);box-shadow:0 0 0 2px rgba(143,205,242,.16)}
      .stock-pill[data-stock-detail-key].is-open{border-color:var(--accent);background:rgba(143,205,242,.07)}
      .rotation-stock-detail{margin-top:7px;border:1px solid #263545;border-radius:10px;background:rgba(8,13,19,.72);padding:10px}
      .rotation-stock-detail[hidden]{display:none}
      .rotation-stock-detail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px}
      .rotation-stock-detail-symbol{font-size:17px;font-weight:820;letter-spacing:-.02em}
      .rotation-stock-detail-symbol small{display:block;font-size:10px;color:var(--muted);font-weight:560;letter-spacing:0;margin-top:1px}
      .rotation-stock-role{font-size:9px;color:var(--accent);border:1px solid #2a3c4c;border-radius:999px;padding:3px 7px;white-space:nowrap}
      .rotation-stock-detail-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
      .rotation-stock-detail-cell{border:1px solid var(--line2);border-radius:8px;background:rgba(255,255,255,.018);padding:7px 8px;min-width:0}
      .rotation-stock-detail-cell span{display:block;font-size:9px;color:var(--faint)}
      .rotation-stock-detail-cell b{display:block;font-size:11px;color:#dbe4ed;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rotation-stock-detail-note{font-size:10px;color:var(--muted);line-height:1.45;margin-top:8px}
      .rotation-stock-tv{display:flex;align-items:center;justify-content:center;min-height:42px;margin-top:9px;border:1px solid #2f81f7;border-radius:8px;background:rgba(47,129,247,.08);color:#9ecbff;text-decoration:none;font-size:11px;font-weight:800}
      .trajectory-line{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:3px 0 2px;font-size:10px;font-weight:760}
      .trajectory-line small{font-size:9px;color:var(--faint);font-weight:560}
      .trajectory-pill{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:2px 6px;font-size:9px;font-weight:800;white-space:nowrap}
      .trajectory-pill.turn{color:var(--amber);border-color:rgba(228,185,103,.38);background:rgba(228,185,103,.055)}
      .trajectory-pill.good{color:var(--green);border-color:rgba(119,212,158,.34);background:rgba(119,212,158,.05)}
      .trajectory-pill.risk{color:var(--orange);border-color:rgba(231,154,98,.4);background:rgba(231,154,98,.055)}
      .trajectory-pill.bad{color:var(--red);border-color:rgba(223,123,123,.38);background:rgba(223,123,123,.055)}
      .trajectory-pill.neutral{color:var(--muted)}
      .summary-line .trajectory-mini{display:block;margin-top:1px;font-size:9px;color:var(--muted)}
      .trajectory-map-note{font-size:9px;color:var(--faint);margin-top:5px}
      .trajectory-recovery-card{border-color:rgba(228,185,103,.3)}
      .trajectory-recovery-card .leader-state{color:var(--amber)}
      @media(max-width:680px){
        .rotation-stock-detail-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
        .rotation-stock-detail-head{align-items:center}
        .stock-pill[data-stock-detail-key]{padding:7px 8px;min-height:38px}
      }
    `;
    document.head.appendChild(style);
  }

  function stockDetailMarkup(etf, stock) {
    const symbol = String(stock.symbol || '').trim().toUpperCase();
    const tvUrl = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`;
    const group = String(stock.group || '—');
    const name = String(stock.name || '');
    const weight = finite(stock.holding_weight_pct) ? `${fmt(stock.holding_weight_pct, 2)}%` : '—';
    return `
      <div class="rotation-stock-detail-head">
        <div class="rotation-stock-detail-symbol">${esc(symbol)}<small>${esc(name || `${etf} 構成銘柄`)}</small></div>
        <div class="rotation-stock-role">${esc(roleJa(stock.role))} / ${esc(phaseJa(stock.group_phase))}</div>
      </div>
      <div class="rotation-stock-detail-grid">
        <div class="rotation-stock-detail-cell"><span>RS189</span><b>${esc(fmt(stock.rs189,1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>RS63</span><b>${esc(fmt(stock.rs63,1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>RS21</span><b>${esc(fmt(stock.rs21,1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>Leadership強度</span><b>${esc(fmt(stock.strength,1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>短期加速度</span><b>${esc(fmt(stock.acceleration,1,true))}</b></div>
        <div class="rotation-stock-detail-cell"><span>中期加速度</span><b>${esc(fmt(stock.slow_acceleration,1,true))}</b></div>
        <div class="rotation-stock-detail-cell"><span>ETF構成比</span><b>${esc(weight)}</b></div>
        <div class="rotation-stock-detail-cell"><span>ブレイクアウト</span><b>${esc(breakoutJa(stock.breakout_status))}</b></div>
      </div>
      <div class="rotation-stock-detail-note">${esc(group)} / Leadershipグループ順位 ${esc(stock.group_rank ?? '—')} / グループ内順位 ${esc(stock.stock_rank_within_group ?? '—')}。Rotation独自の株スコアではなく、既存Leadershipの情報です。</div>
      <a class="rotation-stock-tv" href="${esc(tvUrl)}" target="_blank" rel="noopener noreferrer">TradingViewで ${esc(symbol)} を開く ↗</a>
    `;
  }

  function closeStockDetails(exceptButton = null) {
    document.querySelectorAll('.stock-pill[data-stock-detail-key].is-open').forEach(button => {
      if (button === exceptButton) return;
      button.classList.remove('is-open');
      button.setAttribute('aria-expanded','false');
    });
    document.querySelectorAll('.rotation-stock-detail:not([hidden])').forEach(panel => {
      if (exceptButton && panel.id === exceptButton.dataset.stockPanelId) return;
      panel.hidden = true;
      panel.innerHTML = '';
    });
  }

  function activateStockDetail(button) {
    const row = stockDetailIndex.get(String(button.dataset.stockDetailKey || ''));
    const panel = document.getElementById(String(button.dataset.stockPanelId || ''));
    if (!row || !panel) return;
    const wasOpen = button.classList.contains('is-open') && !panel.hidden;
    closeStockDetails(button);
    if (wasOpen) {
      button.classList.remove('is-open');
      button.setAttribute('aria-expanded','false');
      panel.hidden = true;
      panel.innerHTML = '';
      return;
    }
    panel.innerHTML = stockDetailMarkup(row.etf,row.stock);
    panel.hidden = false;
    button.classList.add('is-open');
    button.setAttribute('aria-expanded','true');
  }

  function bindStockDetailEvents() {
    if (document.documentElement.dataset.rotationStockDetailsBound === '1') return;
    document.documentElement.dataset.rotationStockDetailsBound = '1';
    document.addEventListener('click', event => {
      const button = event.target.closest('.stock-pill[data-stock-detail-key]');
      if (button) activateStockDetail(button);
    });
    document.addEventListener('keydown', event => {
      const button = event.target.closest?.('.stock-pill[data-stock-detail-key]');
      if (!button || !['Enter',' '].includes(event.key)) return;
      event.preventDefault();
      activateStockDetail(button);
    });
  }

  async function enhanceStockDetails() {
    const response = await fetchReadyContext({cache:'no-store'});
    if (!response) return false;
    const context = await response.json();
    const nextIndex = new Map();
    (context.industry_context || []).forEach(item => {
      const etf = String(item.etf || '').trim().toUpperCase();
      const leaders = item.existing_emerging_or_leading_leaders_in_full_intersection || item.existing_emerging_or_leading_leaders_in_top15_intersection || [];
      leaders.forEach(stock => {
        const symbol = String(stock.symbol || '').trim().toUpperCase();
        if (etf && symbol) nextIndex.set(`${etf}:${symbol}`, {etf,stock});
      });
    });
    stockDetailIndex = nextIndex;
    ensureRuntimeStyles();
    bindStockDetailEvents();

    const cards = Array.from(document.querySelectorAll('#leaders .leader-card'));
    let wired = 0;
    cards.forEach((card, cardIndex) => {
      const title = String(card.querySelector('.leader-title')?.textContent || '').trim();
      const etf = (title.match(/^([A-Z][A-Z0-9.-]{0,9})/) || [])[1] || '';
      card.querySelectorAll('.stocks-line').forEach((line,lineIndex) => {
        let panel = line.nextElementSibling;
        if (!panel || !panel.classList.contains('rotation-stock-detail')) {
          panel = document.createElement('div');
          panel.className = 'rotation-stock-detail';
          panel.id = `rotation-stock-detail-${cardIndex}-${lineIndex}`;
          panel.hidden = true;
          line.insertAdjacentElement('afterend',panel);
        }
        line.querySelectorAll('.stock-pill').forEach(pill => {
          const symbol = String(pill.querySelector('b')?.textContent || '').trim().toUpperCase();
          const key = `${etf}:${symbol}`;
          if (!stockDetailIndex.has(key)) return;
          pill.dataset.stockDetailKey = key;
          pill.dataset.stockPanelId = panel.id;
          pill.setAttribute('role','button');
          pill.setAttribute('tabindex','0');
          pill.setAttribute('aria-expanded','false');
          pill.setAttribute('aria-controls',panel.id);
          pill.setAttribute('aria-label',`${symbol} の詳細を表示`);
          wired += 1;
        });
      });
    });
    return wired > 0;
  }

  function allRows(data) {
    return Object.values(data?.observations?.rotation_buckets || {}).flat().filter(row => row && row.ticker);
  }

  function transitionMarkup(row) {
    const t = trajectory(row);
    if (t.key === 'na') return '<span class="trajectory-pill neutral">方向未取得</span>';
    return `<span class="trajectory-pill ${esc(t.tone)}">${esc(t.label)}</span><small>20日前 ${fmt(t.previous,1)} → 現在 ${fmt(t.current,1)}（${pct(t.delta,1)}）</small>`;
  }

  function enhanceThemeRows(rowsByTicker) {
    document.querySelectorAll('#themeList .theme-row[data-ticker]').forEach(rowNode => {
      const ticker = String(rowNode.dataset.ticker || '').toUpperCase();
      const row = rowsByTicker.get(ticker);
      if (!row) return;
      const state = rowNode.querySelector('.theme-state');
      if (!state) return;
      let line = state.querySelector('.trajectory-line');
      if (!line) {
        line = document.createElement('div');
        line.className = 'trajectory-line';
        const title = state.querySelector('.state-title');
        if (title) title.insertAdjacentElement('afterend',line); else state.prepend(line);
      }
      line.innerHTML = transitionMarkup(row);
    });
  }

  function summaryTrajectory(row) {
    const t = trajectory(row);
    return `<div class="summary-line"><b>${esc(row.ticker)}${row.label?`｜${esc(row.label)}`:''}</b><span class="trajectory-mini"><span class="trajectory-pill ${esc(t.tone)}">${esc(t.label)}</span> ${fmt(t.previous,1)} → ${fmt(t.current,1)}（${pct(t.delta,1)}）</span></div>`;
  }

  function enhanceHero(rows) {
    const improveLabel = document.querySelector('.focus-improve .focus-label');
    const badLabel = document.querySelector('.focus-bad .focus-label');
    if (improveLabel) improveLabel.innerHTML = '<span>↗</span> 底打ち / 改善転換';
    if (badLabel) badLabel.innerHTML = '<span>↘</span> 強から悪化 / 失速';

    const improve = rows.map(row => ({row,t:trajectory(row)})).filter(x => x.t.up)
      .sort((a,b) => a.t.priority-b.t.priority || Number(b.t.delta)-Number(a.t.delta));
    const deteriorate = rows.map(row => ({row,t:trajectory(row)})).filter(x => x.t.down)
      .sort((a,b) => a.t.priority-b.t.priority || Number(a.t.delta)-Number(b.t.delta));
    const strong = rows.filter(row => Number(row.internal_score) >= 60 && Number(row.price_score) >= 70)
      .map(row => ({row,t:trajectory(row)}))
      .sort((a,b) => (a.t.down?1:0)-(b.t.down?1:0) || Number(b.row.price_score)-Number(a.row.price_score));

    const improveHost = document.getElementById('summaryImprove');
    const badHost = document.getElementById('summaryDeteriorate');
    const strongHost = document.getElementById('summaryStrong');
    if (improveHost) improveHost.innerHTML = improve.slice(0,4).map(x => summaryTrajectory(x.row)).join('') || '<div class="summary-empty">明確な改善転換なし</div>';
    if (badHost) badHost.innerHTML = deteriorate.slice(0,4).map(x => summaryTrajectory(x.row)).join('') || '<div class="summary-empty">明確な悪化転換なし</div>';
    if (strongHost && strong.length) strongHost.innerHTML = strong.slice(0,4).map(x => summaryTrajectory(x.row)).join('');

    const sentence = document.getElementById('heroSentence');
    if (sentence) {
      const bits = [];
      if (improve.length) bits.push(`改善転換は ${improve.slice(0,3).map(x=>x.row.ticker).join(' / ')}`);
      if (deteriorate.length) bits.push(`悪化転換は ${deteriorate.slice(0,3).map(x=>x.row.ticker).join(' / ')}`);
      if (bits.length) sentence.textContent = `${bits.join('。')}。構成株は現在値だけでなく「20日前→現在」の遷移で確認。買い許可は既存Dashboardに従います。`;
    }
  }

  function enhanceChanges(rows) {
    const upHost = document.getElementById('improvingList');
    const downHost = document.getElementById('deterioratingList');
    const ready = rows.map(row => ({row,t:trajectory(row)})).filter(x => x.t.key !== 'na');
    const up = ready.filter(x=>x.t.up).sort((a,b)=>a.t.priority-b.t.priority || Number(b.t.delta)-Number(a.t.delta)).slice(0,8);
    const down = ready.filter(x=>x.t.down).sort((a,b)=>a.t.priority-b.t.priority || Number(a.t.delta)-Number(b.t.delta)).slice(0,8);
    const item = x => `<div class="change-row"><div class="change-theme"><b>${esc(x.row.ticker)}${x.row.label?`｜${esc(x.row.label)}`:''}</b><span><span class="trajectory-pill ${esc(x.t.tone)}">${esc(x.t.label)}</span></span></div><div class="change-metrics"><strong class="${x.t.up?'good':'bad'}">${fmt(x.t.previous,1)} → ${fmt(x.t.current,1)}</strong><small>構成株20日 ${pct(x.t.delta,1)} / ETF価格20日 ${pct(x.row.ret_20d_pct,2)}</small></div></div>`;
    if (upHost) upHost.innerHTML = up.map(item).join('') || '<div class="sub">明確な改善転換なし</div>';
    if (downHost) downHost.innerHTML = down.map(item).join('') || '<div class="sub">明確な悪化転換なし</div>';
    const upTitle = document.querySelector('.change-up .change-column-title');
    const downTitle = document.querySelector('.change-down .change-column-title');
    if (upTitle) upTitle.textContent = '底打ち・改善転換（現在地を考慮）';
    if (downTitle) downTitle.textContent = '強から悪化・失速（現在地を考慮）';
  }

  function enhanceMatrix(rows) {
    const svg = document.getElementById('rotationMatrix');
    if (!svg || svg.dataset.trajectoryEnhanced === '1') return;
    const W=760,H=430,L=52,R=18,T=20,B=42,iw=W-L-R,ih=H-T-B;
    const sx=x=>L+(Math.max(0,Math.min(100,x))/100)*iw;
    const sy=y=>T+ih-(Math.max(0,Math.min(100,y))/100)*ih;
    let trails = '<g class="trajectory-trails" pointer-events="none">';
    rows.forEach(row => {
      if (!finite(row.price_score) || !finite(row.internal_score) || !finite(row.internal_delta20)) return;
      const t = trajectory(row);
      if (t.key === 'na' || Math.abs(t.delta) < 2) return;
      const x=sx(Number(row.price_score)), y0=sy(t.previous), y1=sy(t.current);
      const c=t.up?'#77d49e':t.down?'#df7b7b':'#657281';
      trails += `<line x1="${x}" x2="${x}" y1="${y0}" y2="${y1}" stroke="${c}" stroke-width="2" stroke-opacity=".34" stroke-linecap="round"/><circle cx="${x}" cy="${y0}" r="2.2" fill="${c}" fill-opacity=".34"/>`;
    });
    trails += '</g>';
    svg.innerHTML = trails + svg.innerHTML;
    svg.dataset.trajectoryEnhanced = '1';
    const box = svg.parentElement;
    if (box && !box.querySelector('.trajectory-map-note')) {
      const note = document.createElement('div');
      note.className = 'trajectory-map-note';
      note.textContent = '縦線＝構成株の20日前→現在。ETF価格の20日前順位は未取得なので、横方向の軌跡は描きません。';
      box.appendChild(note);
    }
  }

  function recoveryLeaderCard(item,row) {
    const t = trajectory(row);
    const leaders = (item.existing_emerging_or_leading_leaders_in_full_intersection || item.existing_emerging_or_leading_leaders_in_top15_intersection || [])
      .filter(stock => ['PIONEER','LEADER'].includes(String(stock.role || '').toUpperCase()) && ['EMERGING','LEADING'].includes(String(stock.group_phase || '').toUpperCase())).slice(0,5);
    if (!leaders.length) return '';
    const groups = new Map();
    leaders.forEach(stock => { const g=String(stock.group || 'その他'); if(!groups.has(g))groups.set(g,[]); groups.get(g).push(stock); });
    return `<div class="leader-card trajectory-recovery-card"><div class="leader-head"><div class="leader-title">${esc(item.etf)}<small>構成株はまだ上位定着前だが、20日で改善転換。強い株だけを表示。</small></div><div class="leader-state">${esc(t.label)}</div></div><div class="leader-coverage"><span class="trajectory-pill ${esc(t.tone)}">${esc(t.label)}</span> 20日前 ${fmt(t.previous,1)} → 現在 ${fmt(t.current,1)}（${pct(t.delta,1)}）</div>${Array.from(groups.entries()).map(([group,stocks])=>`<div class="theme-block"><div class="theme-name">${esc(group)} ・ ${esc(phaseJa(stocks[0]?.group_phase))}</div><div class="stocks-line">${stocks.map(stock=>`<div class="stock-pill"><b>${esc(stock.symbol)}</b><span>${esc(roleJa(stock.role))} / RS189 ${fmt(stock.rs189,0)} / RS63 ${fmt(stock.rs63,0)}</span></div>`).join('')}</div></div>`).join('')}</div>`;
  }

  function enhanceRecoveryLeaders(rowsByTicker,context) {
    const host = document.getElementById('leaders');
    if (!host || !context) return;
    const existing = new Set(Array.from(host.querySelectorAll('.leader-title')).map(node => (String(node.textContent || '').match(/^([A-Z][A-Z0-9.-]{0,9})/)||[])[1]).filter(Boolean));
    const candidates = (context.industry_context || []).map(item => ({item,row:rowsByTicker.get(String(item.etf || '').toUpperCase())})).filter(x => {
      if (!x.row || existing.has(String(x.item.etf || '').toUpperCase())) return false;
      return ['weak_to_strong','weak_to_mid','bottom_recovery','mid_to_strong','mid_recovery'].includes(trajectory(x.row).key);
    }).sort((a,b)=>trajectory(a.row).priority-trajectory(b.row).priority || Number(b.row.internal_delta20)-Number(a.row.internal_delta20));
    if (!candidates.length) return;
    const html = candidates.slice(0,4).map(x=>recoveryLeaderCard(x.item,x.row)).filter(Boolean).join('');
    if (html) host.insertAdjacentHTML('beforeend',html);
    const scope = document.getElementById('leaderScope');
    if (scope && !scope.textContent.includes('改善転換')) scope.textContent += ' ＋ 改善転換テーマ';
  }

  function bindInternalHelpExtension() {
    if (document.documentElement.dataset.rotationTrajectoryHelpBound === '1') return;
    document.documentElement.dataset.rotationTrajectoryHelpBound = '1';
    document.addEventListener('click', event => {
      const trigger = event.target.closest?.('[data-help-key="internal"]');
      if (!trigger) return;
      window.setTimeout(() => {
        const body = document.getElementById('helpBody');
        if (body && !body.textContent.includes('20日前→現在')) body.textContent += ' さらに現在スコアから20日変化を差し引いて20日前の位置を復元し、「弱→中立」「強→弱」などの遷移を表示します。20日前→現在の方向を現在値と分離して読みます。';
      },0);
    });
  }

  async function enhanceTrajectoryUI() {
    const [data,contextResponse] = await Promise.all([readJson(prodData),fetchReadyContext({cache:'no-store'})]);
    const context = contextResponse ? await contextResponse.json() : null;
    const rows = allRows(data);
    if (!rows.length || !document.querySelector('#themeList .theme-row')) return false;
    const rowsByTicker = new Map(rows.map(row => [String(row.ticker || '').toUpperCase(),row]));
    ensureRuntimeStyles();
    enhanceThemeRows(rowsByTicker);
    enhanceHero(rows);
    enhanceChanges(rows);
    enhanceMatrix(rows);
    enhanceRecoveryLeaders(rowsByTicker,context);
    bindInternalHelpExtension();
    await enhanceStockDetails();
    return true;
  }

  function scheduleEnhancements() {
    let attempts = 0;
    const run = async () => {
      attempts += 1;
      try { if (await enhanceTrajectoryUI()) return; } catch (_) {}
      if (attempts < 12) window.setTimeout(run,350);
    };
    window.setTimeout(run,200);
  }

  const engine = document.createElement('script');
  engine.src = 'app-v2.js?v=production-routing-20260904-trajectory';
  engine.onload = () => {
    scheduleEnhancements();
    let tries = 0;
    const timer = setInterval(() => {
      applyFreshnessGuard();
      tries += 1;
      if (tries >= 8) clearInterval(timer);
    },500);
  };
  engine.onerror = () => {
    const node = warningNode();
    if (node) {
      node.hidden = false;
      node.textContent = 'Rotation表示エンジンを読み込めませんでした。';
    }
  };
  document.head.appendChild(engine);
})();
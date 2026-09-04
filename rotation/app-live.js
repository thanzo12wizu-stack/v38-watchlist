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

  async function contextFallback() {
    let asof = null;
    try {
      const r = await nativeFetch(prodStatus, {cache: 'no-store'});
      if (r.ok) asof = (await r.json()).asof || null;
    } catch (_) {}
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
      const ready = contextReady && contextAsof && rotationAsof && contextAsof === rotationAsof;
      if (!ready) return null;
      return new Response(JSON.stringify(context), {status: 200, headers: {'Content-Type': 'application/json'}});
    } catch (_) {
      return null;
    }
  }

  window.fetch = async function(input, init) {
    const url = requestUrl(input);
    if (url.includes(legacyBriefNeedle)) {
      return nativeFetch(prodData, {...(init || {}), cache: 'no-store'});
    }
    if (url.includes(legacyContextNeedle)) {
      const ready = await fetchReadyContext(init);
      if (ready) return ready;
      return contextFallback();
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
      const [sr, vr, cr] = await Promise.all([
        nativeFetch(prodStatus, {cache: 'no-store'}),
        nativeFetch(mainRaw + 'v38-live-state.json', {cache: 'no-store'}),
        nativeFetch(mainRaw + 'state.json', {cache: 'no-store'})
      ]);
      if (!sr.ok || !vr.ok || !cr.ok) throw new Error('freshness source unavailable');
      const [status, live, command] = await Promise.all([sr.json(), vr.json(), cr.json()]);
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
    } catch (_) {
      const scope = document.getElementById('leaderScope');
      const leaders = document.getElementById('leaders');
      if (scope) scope.textContent = 'Leadership照合 更新待ち';
      if (leaders) leaders.innerHTML = '<div class="sub">現在のRotationと同じ基準日のLeadership照合がREADYになるまで、強い株は表示しません。</div>';
    }
  }

  function esc(value) {
    return String(value ?? '—').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[ch]);
  }

  function fmt(value, digits = 1, signed = false) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${signed && n > 0 ? '+' : ''}${n.toFixed(digits)}`;
  }

  function roleJa(value) {
    return ({PIONEER: '先導株', LEADER: '主導株'})[String(value || '').toUpperCase()] || String(value || '—');
  }

  function phaseJa(value) {
    return ({EMERGING: '新興', LEADING: '主導', MATURE: '成熟', LOSING: '失速'})[String(value || '').toUpperCase()] || String(value || '—');
  }

  function breakoutJa(value) {
    const v = String(value || '').toUpperCase();
    if (!v || v === 'NONE') return '未発火';
    return ({READY: '発火目前', BREAKOUT: 'ブレイクアウト', ALREADY_BROKE: '発火済み'})[v] || v;
  }

  function ensureStockDetailStyles() {
    if (document.getElementById('rotationStockDetailStyles')) return;
    const style = document.createElement('style');
    style.id = 'rotationStockDetailStyles';
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
      .rotation-stock-tv:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
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
    const weight = Number.isFinite(Number(stock.holding_weight_pct)) ? `${fmt(stock.holding_weight_pct, 2)}%` : '—';
    return `
      <div class="rotation-stock-detail-head">
        <div class="rotation-stock-detail-symbol">${esc(symbol)}<small>${esc(name || `${etf} 構成銘柄`)}</small></div>
        <div class="rotation-stock-role">${esc(roleJa(stock.role))} / ${esc(phaseJa(stock.group_phase))}</div>
      </div>
      <div class="rotation-stock-detail-grid">
        <div class="rotation-stock-detail-cell"><span>RS189</span><b>${esc(fmt(stock.rs189, 1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>RS63</span><b>${esc(fmt(stock.rs63, 1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>RS21</span><b>${esc(fmt(stock.rs21, 1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>Leadership強度</span><b>${esc(fmt(stock.strength, 1))}</b></div>
        <div class="rotation-stock-detail-cell"><span>短期加速度</span><b>${esc(fmt(stock.acceleration, 1, true))}</b></div>
        <div class="rotation-stock-detail-cell"><span>中期加速度</span><b>${esc(fmt(stock.slow_acceleration, 1, true))}</b></div>
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
      button.setAttribute('aria-expanded', 'false');
    });
    document.querySelectorAll('.rotation-stock-detail:not([hidden])').forEach(panel => {
      if (exceptButton && panel.id === exceptButton.dataset.stockPanelId) return;
      panel.hidden = true;
      panel.innerHTML = '';
    });
  }

  function activateStockDetail(button) {
    const key = String(button.dataset.stockDetailKey || '');
    const row = stockDetailIndex.get(key);
    const panel = document.getElementById(String(button.dataset.stockPanelId || ''));
    if (!row || !panel) return;
    const wasOpen = button.classList.contains('is-open') && !panel.hidden;
    closeStockDetails(button);
    if (wasOpen) {
      button.classList.remove('is-open');
      button.setAttribute('aria-expanded', 'false');
      panel.hidden = true;
      panel.innerHTML = '';
      return;
    }
    document.querySelectorAll('.stock-pill[data-stock-detail-key].is-open').forEach(other => {
      if (other !== button) {
        other.classList.remove('is-open');
        other.setAttribute('aria-expanded', 'false');
      }
    });
    document.querySelectorAll('.rotation-stock-detail:not([hidden])').forEach(otherPanel => {
      if (otherPanel !== panel) {
        otherPanel.hidden = true;
        otherPanel.innerHTML = '';
      }
    });
    panel.innerHTML = stockDetailMarkup(row.etf, row.stock);
    panel.hidden = false;
    button.classList.add('is-open');
    button.setAttribute('aria-expanded', 'true');
  }

  function bindStockDetailEvents() {
    if (document.documentElement.dataset.rotationStockDetailsBound === '1') return;
    document.documentElement.dataset.rotationStockDetailsBound = '1';
    document.addEventListener('click', event => {
      const button = event.target.closest('.stock-pill[data-stock-detail-key]');
      if (!button) return;
      activateStockDetail(button);
    });
    document.addEventListener('keydown', event => {
      const button = event.target.closest?.('.stock-pill[data-stock-detail-key]');
      if (!button || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      activateStockDetail(button);
    });
  }

  async function enhanceStockDetails() {
    const response = await fetchReadyContext({cache: 'no-store'});
    if (!response) return false;
    const context = await response.json();
    const nextIndex = new Map();
    (context.industry_context || []).forEach(item => {
      const etf = String(item.etf || '').trim().toUpperCase();
      const leaders = item.existing_emerging_or_leading_leaders_in_full_intersection || item.existing_emerging_or_leading_leaders_in_top15_intersection || [];
      leaders.forEach(stock => {
        const symbol = String(stock.symbol || '').trim().toUpperCase();
        if (etf && symbol) nextIndex.set(`${etf}:${symbol}`, {etf, stock});
      });
    });
    stockDetailIndex = nextIndex;
    ensureStockDetailStyles();
    bindStockDetailEvents();

    const cards = Array.from(document.querySelectorAll('#leaders .leader-card'));
    if (!cards.length) return false;
    let wired = 0;
    cards.forEach((card, cardIndex) => {
      const title = String(card.querySelector('.leader-title')?.textContent || '').trim();
      const etf = (title.match(/^([A-Z][A-Z0-9.-]{0,9})/) || [])[1] || '';
      card.querySelectorAll('.stocks-line').forEach((line, lineIndex) => {
        let panel = line.nextElementSibling;
        if (!panel || !panel.classList.contains('rotation-stock-detail')) {
          panel = document.createElement('div');
          panel.className = 'rotation-stock-detail';
          panel.id = `rotation-stock-detail-${cardIndex}-${lineIndex}`;
          panel.hidden = true;
          line.insertAdjacentElement('afterend', panel);
        }
        line.querySelectorAll('.stock-pill').forEach(pill => {
          const symbol = String(pill.querySelector('b')?.textContent || '').trim().toUpperCase();
          const key = `${etf}:${symbol}`;
          if (!stockDetailIndex.has(key)) return;
          pill.dataset.stockDetailKey = key;
          pill.dataset.stockPanelId = panel.id;
          pill.setAttribute('role', 'button');
          pill.setAttribute('tabindex', '0');
          pill.setAttribute('aria-expanded', 'false');
          pill.setAttribute('aria-controls', panel.id);
          pill.setAttribute('aria-label', `${symbol} の詳細を表示`);
          wired += 1;
        });
      });
    });
    return wired > 0;
  }

  function scheduleStockDetailEnhancement() {
    let attempts = 0;
    const run = async () => {
      attempts += 1;
      try {
        if (await enhanceStockDetails()) return;
      } catch (_) {}
      if (attempts < 12) window.setTimeout(run, 350);
    };
    window.setTimeout(run, 200);
  }

  const engine = document.createElement('script');
  engine.src = 'app-v2.js?v=production-routing-20260904-stock-detail';
  engine.onload = () => {
    scheduleStockDetailEnhancement();
    let tries = 0;
    const timer = setInterval(() => {
      applyFreshnessGuard();
      tries += 1;
      if (tries >= 8) clearInterval(timer);
    }, 500);
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
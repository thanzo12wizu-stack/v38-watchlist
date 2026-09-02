'use strict';

(() => {
  const nativeFetch = window.fetch.bind(window);
  const mainRaw = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/';
  const prodData = new URL('data/rotation-theme56.json', window.location.href).href;
  const prodStatus = new URL('data/status.json', window.location.href).href;
  const prodContext = new URL('data/rotation-theme56-stock-context.json', window.location.href).href;
  const legacyBriefNeedle = '/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_public_brief/rotation_theme56_public_brief.json';
  const legacyContextNeedle = '/research/rotation-exact-flow-internals-20260831/leadership/research/rotation_theme56_stock_context/rotation_theme56_stock_context.json';

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

  window.fetch = async function(input, init) {
    const url = requestUrl(input);
    if (url.includes(legacyBriefNeedle)) {
      return nativeFetch(prodData, {...(init || {}), cache: 'no-store'});
    }
    if (url.includes(legacyContextNeedle)) {
      try {
        const r = await nativeFetch(prodContext, {...(init || {}), cache: 'no-store'});
        if (r.ok) return r;
      } catch (_) {}
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
      const ctx = await nativeFetch(prodContext, {cache: 'no-store'});
      if (!ctx.ok) {
        const scope = document.getElementById('leaderScope');
        const leaders = document.getElementById('leaders');
        if (scope) scope.textContent = 'Leadership照合 更新待ち';
        if (leaders) leaders.innerHTML = '<div class="sub">古い研究用Leadership照合は表示していません。現在データの本番照合がREADYになるまで更新待ちです。</div>';
      }
    } catch (_) {
      const scope = document.getElementById('leaderScope');
      const leaders = document.getElementById('leaders');
      if (scope) scope.textContent = 'Leadership照合 更新待ち';
      if (leaders) leaders.innerHTML = '<div class="sub">古い研究用Leadership照合は表示していません。現在データの本番照合がREADYになるまで更新待ちです。</div>';
    }
  }

  const engine = document.createElement('script');
  engine.src = 'app-v2.js?v=production-routing-20260903';
  engine.onload = () => {
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

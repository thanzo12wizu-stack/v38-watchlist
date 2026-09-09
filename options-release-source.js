(() => {
  'use strict';

  const originalFetch = window.fetch.bind(window);
  const repoRawPrefix = '/thanzo12wizu-stack/v38-watchlist/main/';
  const exact = new Map([
    ['options_intelligence.json', 'options_intelligence.json'],
    ['options_positioning.json', 'options_positioning.json'],
    ['options_history.csv', 'options_history.csv'],
    ['options_scan_history.csv', 'options_scan_history.csv'],
    ['universe.csv', 'universe.csv'],
    ['options-rs-leaders.json', 'options-rs-leaders.json'],
    ['state.json', 'state.json'],
    ['trend_history.json', 'trend_history.json'],
    ['options_chart_data.json', 'options_chart_data.json'],
    ['rotation/data/status.json', 'rotation-status.json'],
  ]);

  function releasePath(pathname) {
    const clean = String(pathname || '').replace(/^\/+/, '');
    const sitePrefix = 'v38-watchlist/';
    const rel = clean.startsWith(sitePrefix) ? clean.slice(sitePrefix.length) : clean;
    if (exact.has(rel)) return exact.get(rel);
    if (rel.startsWith('options_chart_history/')) return rel;
    return null;
  }

  function rewrite(input) {
    const raw = input instanceof Request ? input.url : String(input);
    let url;
    try { url = new URL(raw, window.location.href); }
    catch (_) { return input; }

    let mapped = null;
    let rawFallback = false;
    if (url.hostname === 'raw.githubusercontent.com' && url.pathname.startsWith(repoRawPrefix)) {
      mapped = releasePath(url.pathname.slice(repoRawPrefix.length));
      rawFallback = true;
    } else if (url.origin === window.location.origin) {
      mapped = releasePath(url.pathname);
    }
    if (!mapped) return input;

    const target = rawFallback
      ? new URL(`https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/release/options/${mapped}`)
      : new URL(`./release/options/${mapped}`, window.location.href);
    target.search = url.search;

    if (input instanceof Request) return new Request(target.toString(), input);
    return target.toString();
  }

  window.fetch = (input, init) => originalFetch(rewrite(input), init);
  window.V38_OPTIONS_RELEASE_SOURCE = 'release/options';
})();

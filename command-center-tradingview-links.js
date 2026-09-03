(() => {
  'use strict';

  const TV_BASE = 'https://www.tradingview.com/chart/?symbol=';
  const TICKER_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;
  const BLOCKED = new Set([
    'RSI','RS','ATR','ADR','EMA','SMA','MA','OBV','VIX','MC','PF','DD','ETF','USD',
    'BUY','SELL','HOLD','OPEN','CLOSED','READY','ENTRY','EXIT','STOP','ATTACK','DEFENSE',
    'SELECTIVE','WATCH','ERROR','FAIL','LIVE','DATA'
  ]);

  const clean = value => String(value || '').trim().toUpperCase();
  const isTicker = value => {
    const symbol = clean(value);
    return !!symbol && TICKER_RE.test(symbol) && !BLOCKED.has(symbol);
  };
  const hrefFor = symbol => `${TV_BASE}${encodeURIComponent(clean(symbol))}`;

  function decorateAnchor(anchor, symbol) {
    if (!anchor || anchor.dataset.tvLinked === '1') return;
    anchor.href = hrefFor(symbol);
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    anchor.title = `${clean(symbol)} をTradingViewで開く`;
    anchor.dataset.tvLinked = '1';
    anchor.style.color = 'inherit';
    anchor.style.textDecoration = 'none';
    anchor.style.cursor = 'pointer';
    anchor.style.touchAction = 'manipulation';
    anchor.addEventListener('click', event => event.stopPropagation());
  }

  function wrapElement(el, symbol) {
    if (!el || el.closest('a[data-tv-linked="1"]')) return;
    const existing = el.matches('a') ? el : el.querySelector(':scope > a');
    if (existing && clean(existing.textContent) === clean(symbol)) {
      decorateAnchor(existing, symbol);
      return;
    }
    if (clean(el.textContent) !== clean(symbol)) return;
    const a = document.createElement('a');
    a.textContent = el.textContent.trim();
    decorateAnchor(a, symbol);
    el.textContent = '';
    el.appendChild(a);
  }

  function linkTickerCell(cell) {
    if (!cell || cell.querySelector('a[data-tv-linked="1"]')) return;
    const candidates = [...cell.querySelectorAll('b,strong,span,a')];
    const exact = candidates.find(el => isTicker(el.textContent) && clean(el.textContent) === clean(el.textContent.trim()));
    if (exact) {
      wrapElement(exact, exact.textContent);
      return;
    }
    if (isTicker(cell.textContent)) wrapElement(cell, cell.textContent);
  }

  function linkTables(root = document) {
    root.querySelectorAll('table').forEach(table => {
      const headers = [...table.querySelectorAll('thead th')].map(th => clean(th.textContent));
      let tickerIndex = headers.findIndex(h => h === '銘柄' || h === 'TICKER' || h === 'SYMBOL');
      if (tickerIndex < 0) return;
      table.querySelectorAll('tbody tr').forEach(row => {
        const cells = row.querySelectorAll('td');
        if (cells[tickerIndex]) linkTickerCell(cells[tickerIndex]);
      });
    });
  }

  function linkDataAttributes(root = document) {
    root.querySelectorAll('[data-ticker],[data-symbol]').forEach(el => {
      const symbol = clean(el.dataset.ticker || el.dataset.symbol);
      if (!isTicker(symbol)) return;
      const target = el.matches('a,b,strong,span') ? el : el.querySelector('a,b,strong,span');
      if (target && isTicker(target.textContent)) wrapElement(target, symbol);
    });
  }

  function linkKnownTickerAreas(root = document) {
    const selectors = [
      '#hldList b', '#hldList strong', '#hldList .ticker', '#hldList .symbol',
      '#t-v38-stocks b', '#t-v38-stocks strong',
      '#t-v38-holdings b', '#t-v38-holdings strong',
      '#t-v38-today b', '#t-v38-today strong',
      '#taCard b', '#taCard strong'
    ];
    root.querySelectorAll(selectors.join(',')).forEach(el => {
      if (isTicker(el.textContent)) wrapElement(el, el.textContent);
    });
  }

  function run(root = document) {
    linkTables(root);
    linkDataAttributes(root);
    linkKnownTickerAreas(root);
  }

  let scheduled = false;
  const scheduleRun = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      run(document);
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      run(document);
      new MutationObserver(scheduleRun).observe(document.body, { childList: true, subtree: true });
    }, { once: true });
  } else {
    run(document);
    new MutationObserver(scheduleRun).observe(document.body, { childList: true, subtree: true });
  }
})();

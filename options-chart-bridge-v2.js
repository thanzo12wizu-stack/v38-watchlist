(() => {
'use strict';

const SAME = './options_chart_data.json';
const RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_chart_data.json';
const SHARD_BASE = './options_chart_history';
const SHARD_RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_chart_history';
const PRICE_BASE = './options_price_history';
const PRICE_RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_price_history';
const VERSION = '20260909-universe1';
let payloadPromise = null;
const shardPromises = new Map();
const priceShardPromises = new Map();
let activeChart = null;
let scheduled = false;
let mountToken = 0;
let preserveAnchor = null;
let preserveAnchorTop = null;

const finiteValue = value => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};
const numText = text => {
  const m = String(text || '').replaceAll(',', '').match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
};
const money = value => {
  const n = finiteValue(value);
  return n === null ? '—' : '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 });
};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));
const shardKey = ticker => {
  const c = String(ticker || '_').trim().toUpperCase()[0] || '_';
  return /^[A-Z0-9]$/.test(c) ? c : '_';
};
const priceShardKey = ticker => {
  const c = String(ticker || '').trim().toUpperCase()[0] || '';
  return /^[A-Z]$/.test(c) ? c : 'OTHER';
};

async function fetchJson(urls, label) {
  let last = null;
  for (const url of urls) {
    try {
      const join = url.includes('?') ? '&' : '?';
      const response = await fetch(`${url}${join}v=${VERSION}`, { cache: 'default' });
      if (!response.ok) {
        last = new Error(`${label}:${response.status}`);
        continue;
      }
      const body = await response.json();
      if (body && typeof body === 'object') return body;
    } catch (error) {
      last = error;
    }
  }
  throw last || new Error(`${label} unavailable`);
}

async function loadPayload(force = false) {
  if (force) payloadPromise = null;
  if (!payloadPromise) payloadPromise = fetchJson([SAME, RAW], 'chart data');
  return payloadPromise;
}

async function loadShard(ticker) {
  const key = shardKey(ticker);
  if (!shardPromises.has(key)) {
    shardPromises.set(key, fetchJson([
      `${SHARD_BASE}/${key}.json`,
      `${SHARD_RAW}/${key}.json`,
    ], `chart history ${key}`).catch(() => ({ tickers: {} })));
  }
  const shard = await shardPromises.get(key);
  return shard?.tickers?.[ticker] || [];
}

function expandPriceRecord(record) {
  if (!record || !Array.isArray(record.bars)) return record || null;
  const bars = record.bars.map(row => {
    if (!Array.isArray(row)) return row;
    return {
      time: String(row[0] || '').slice(0, 10),
      open: finiteValue(row[1]),
      high: finiteValue(row[2]),
      low: finiteValue(row[3]),
      close: finiteValue(row[4]),
      volume: finiteValue(row[5]) ?? 0,
    };
  }).filter(row => row && row.time && [row.open, row.high, row.low, row.close].every(v => v !== null));
  return { ...record, bars };
}

async function loadPrice(ticker) {
  const key = priceShardKey(ticker);
  if (!priceShardPromises.has(key)) {
    priceShardPromises.set(key, fetchJson([
      `${PRICE_BASE}/${key}.json`,
      `${PRICE_RAW}/${key}.json`,
    ], `price history ${key}`).catch(() => ({ tickers: {} })));
  }
  const shard = await priceShardPromises.get(key);
  return expandPriceRecord(shard?.tickers?.[ticker] || null);
}

function readLevel(card, label) {
  for (const el of card.querySelectorAll('.bigLv')) {
    if (el.querySelector('span')?.textContent?.trim() === label) {
      return numText(el.querySelector('b')?.textContent);
    }
  }
  return null;
}

function readExpected(card) {
  const spans = [...card.querySelectorAll('.expectedRow span')];
  const text = spans.map(x => x.textContent || '').find(x => x.includes('想定レンジ')) || '';
  const clean = text.replaceAll(',', '');
  const match = clean.match(/(?:\$)?(-?\d+(?:\.\d+)?)\s*～\s*(?:\$)?(-?\d+(?:\.\d+)?)/);
  return match ? { low: Number(match[1]), high: Number(match[2]) } : { low: null, high: null };
}

function sanitizeLevels(levels) {
  const out = {};
  for (const key of ['callWall', 'gammaFlip', 'putWall', 'expectedLow', 'expectedHigh']) {
    const value = finiteValue(levels?.[key]);
    out[key] = value === null ? undefined : value;
  }
  return out;
}

function withBroadHistory(detailRec, priceRec, broadRows) {
  const rows = Array.isArray(broadRows) ? broadRows : [];
  const candleRec = detailRec?.bars?.length ? detailRec : priceRec?.bars?.length ? priceRec : null;
  if (candleRec) {
    const fallbackWall = detailRec?.wall_history || [];
    return {
      ...candleRec,
      spot_history: rows,
      wall_history: rows.length ? rows : fallbackWall,
      wall_history_days: (rows.length ? rows : fallbackWall).filter(r => r.call_wall != null || r.put_wall != null || r.gamma_flip != null).length,
      options_history_days: rows.length,
      broad_only: !detailRec && rows.length > 0,
      history_loaded: true,
      chart_mode: 'candles',
    };
  }
  if (detailRec) {
    return {
      ...detailRec,
      spot_history: rows,
      wall_history: rows.length ? rows : (detailRec.wall_history || []),
      wall_history_days: rows.filter(r => r.call_wall != null || r.put_wall != null || r.gamma_flip != null).length,
      options_history_days: rows.length,
      history_loaded: true,
      chart_mode: 'candles',
    };
  }
  if (!rows.length) return null;
  const last = rows.at(-1) || {};
  return {
    ticker: '',
    bars: [],
    spot_history: rows,
    wall_history: rows,
    wall_history_days: rows.filter(r => r.call_wall != null || r.put_wall != null || r.gamma_flip != null).length,
    options_history_days: rows.length,
    history_session_date: last.time || '—',
    stale: false,
    broad_only: true,
    history_loaded: true,
    chart_mode: 'options_spot',
    source: 'broad_daily_options_history',
  };
}

function chartPanel(ticker, rec, rawLevels, payload) {
  const levels = sanitizeLevels(rawLevels);
  const hasCandles = !!rec?.bars?.length;
  const hasSpot = (rec?.spot_history?.length || 0) >= 2;
  const available = hasCandles || hasSpot;
  const stale = !!rec?.stale;
  const historyDay = rec?.history_session_date || rec?.spot_history?.at(-1)?.time || '—';
  const session = payload?.session_date || rec?.spot_history?.at(-1)?.time || '—';
  const wallDays = Number(rec?.wall_history_days || 0);
  const obsDays = Number(rec?.options_history_days || rec?.spot_history?.length || wallDays || 0);
  const modeLabel = hasCandles ? '日足 1年' : 'Options日次履歴';
  const status = stale
    ? '<span class="warn">価格履歴更新失敗・前回値</span>'
    : hasCandles ? '<span>価格履歴 OK</span>' : '<span>Options専用Spot履歴</span>';
  const wallStatus = wallDays > 0
    ? `<span>Wall履歴 ${wallDays}日</span>`
    : rec?.history_loaded ? '<span>Wall履歴なし</span>' : '<span class="warn">Wall履歴読込中</span>';
  const broadStatus = rec?.broad_only && obsDays ? '<span>Broad 7–21DTE</span>' : '';
  const legend = available ? `<div class="v38ChartLegend">
    ${hasCandles ? '<span class="tech ema"><b>21EMA</b></span><span class="tech sma150"><b>150SMA</b></span><span class="tech vwap"><b>63VWAP</b></span>' : '<span><b>Spot</b></span>'}
    ${levels.callWall !== undefined ? `<span class="call">Call <b>${money(levels.callWall)}</b></span>` : ''}
    ${levels.gammaFlip !== undefined ? `<span class="flip">Flip <b>${money(levels.gammaFlip)}</b></span>` : ''}
    ${levels.putWall !== undefined ? `<span class="put">Put <b>${money(levels.putWall)}</b></span>` : ''}
    ${levels.expectedLow !== undefined && levels.expectedHigh !== undefined ? `<span class="exp">Expected <b>${money(levels.expectedLow)}–${money(levels.expectedHigh)}</b></span>` : ''}
  </div>` : '';
  const pending = obsDays === 1
    ? '<div class="v38ChartPending"><b>Options日次履歴 1日</b>2営業日以上たまるとSpotとWall推移を表示します。</div>'
    : '<div class="v38ChartPending"><b>価格履歴を取得できません</b>価格履歴の次回更新時に再取得します。</div>';
  const foot = hasCandles
    ? '現在のWall / Flipは右端の水平線、過去履歴は薄い階段線。観測のない日や満期切替は補間しません。'
    : 'Broad履歴はOptions Intelligence専用の日次7–21DTE観測です。SpotとWallの推移表示に使い、詳細Direction判定へは代用しません。';
  return `<section class="v38ChartPanel" data-chart-ticker="${esc(ticker)}">
    <div class="v38ChartHead"><div class="v38ChartHeadLeft"><span class="v38ChartEyebrow">PRICE + OPTIONS MAP</span><div class="v38ChartTitle"><b>${esc(ticker)}</b><span>${modeLabel}</span></div></div><div class="v38ChartStatus"><span>最終観測 ${esc(historyDay)}</span><span>Options基準 ${esc(session)}</span>${wallStatus}${broadStatus}${status}</div></div>
    ${legend}
    ${available ? '<div class="v38ChartCanvas" data-v38-chart></div>' : pending}
    <div class="v38ChartFoot"><span>${foot}</span><a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts™ · Copyright © 2025 TradingView, Inc.</a></div>
  </section>`;
}

function loadingPanel(ticker) {
  return `<section class="v38ChartPanel" data-chart-ticker="${esc(ticker)}" data-chart-loading="1">
    <div class="v38ChartHead"><div class="v38ChartHeadLeft"><span class="v38ChartEyebrow">PRICE + OPTIONS MAP</span><div class="v38ChartTitle"><b>${esc(ticker)}</b><span>日足を準備中</span></div></div><div class="v38ChartStatus"><span>価格履歴を先読み中</span></div></div>
    <div class="v38ChartCanvas"><div class="v38ChartPending"><b>チャートを読み込み中</b>価格履歴を取得しています。</div></div>
  </section>`;
}

function insertPanel(card, panel) {
  const inline = card.closest('.inlineAnalysis');
  const slot = inline?.querySelector(':scope > .inlineChartSlot');
  if (slot) {
    slot.replaceChildren(panel);
    return;
  }
  const anchor = card.querySelector('.directionHero') || card.querySelector('.selectedBadges') || card.querySelector('.selectedTop');
  if (anchor?.parentNode) anchor.insertAdjacentElement('afterend', panel);
  else card.appendChild(panel);
}

function restoreAnchorPosition() {
  if (!preserveAnchor || preserveAnchorTop === null || !preserveAnchor.isConnected) return;
  const nowTop = preserveAnchor.getBoundingClientRect().top;
  const delta = nowTop - preserveAnchorTop;
  if (Math.abs(delta) > 0.5) window.scrollBy(0, delta);
}

function settleAnchorPosition() {
  restoreAnchorPosition();
  requestAnimationFrame(() => {
    restoreAnchorPosition();
    requestAnimationFrame(() => {
      restoreAnchorPosition();
      preserveAnchor = null;
      preserveAnchorTop = null;
    });
  });
}

function activeSelectedCard() {
  return document.querySelector('.inlineAnalysis .selectedCard') || document.querySelector('#selected .selectedCard');
}

function mountPanel(currentCard, ticker, rec, rawLevels, payload, token) {
  if (!currentCard || token !== mountToken) return false;
  const levels = sanitizeLevels(rawLevels);
  const holder = document.createElement('div');
  holder.innerHTML = chartPanel(ticker, rec, levels, payload);
  const panel = holder.firstElementChild;
  const currentInline = currentCard.closest('.inlineAnalysis');
  const oldPanel = currentInline?.querySelector(':scope > .inlineChartSlot .v38ChartPanel') || currentCard.querySelector('.v38ChartPanel');
  if (oldPanel) oldPanel.replaceWith(panel);
  else insertPanel(currentCard, panel);
  restoreAnchorPosition();
  const canvas = panel.querySelector('[data-v38-chart]');
  if (canvas && rec && window.V38Chart?.mount) {
    if (activeChart) {
      try { activeChart.destroy(); } catch (_) {}
    }
    activeChart = window.V38Chart.mount({
      element: canvas,
      bars: rec.bars || [],
      spotHistory: rec.spot_history || [],
      ticker,
      levels,
      wallHistory: rec.wall_history || [],
      stale: !!rec.stale,
    });
  }
  return true;
}

async function mountCurrent() {
  scheduled = false;
  const card = activeSelectedCard();
  const ticker = card?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (!card || !ticker) {
    if (activeChart) {
      try { activeChart.destroy(); } catch (_) {}
      activeChart = null;
    }
    return;
  }

  const token = ++mountToken;
  if (activeChart) {
    try { activeChart.destroy(); } catch (_) {}
    activeChart = null;
  }
  const inlineRoot = card.closest('.inlineAnalysis');
  (inlineRoot?.querySelector(':scope > .inlineChartSlot .v38ChartPanel') || card.querySelector('.v38ChartPanel'))?.remove();

  const expected = readExpected(card);
  const baseLevels = {
    callWall: readLevel(card, 'Call壁'),
    gammaFlip: readLevel(card, 'Gamma Flip'),
    putWall: readLevel(card, 'Put支持'),
    expectedLow: expected.low,
    expectedHigh: expected.high,
  };

  const loadingHolder = document.createElement('div');
  loadingHolder.innerHTML = loadingPanel(ticker);
  insertPanel(card, loadingHolder.firstElementChild);
  restoreAnchorPosition();

  const broadP = loadShard(ticker).catch(() => []);
  const priceP = loadPrice(ticker).catch(() => null);
  const payload = await loadPayload(false).catch(() => ({ tickers: {} }));

  let currentCard = activeSelectedCard();
  let currentTicker = currentCard?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (token !== mountToken || currentTicker !== ticker || !currentCard) return;

  const detailRec = payload?.tickers?.[ticker] || null;
  let priceRec = null;
  if (detailRec?.bars?.length) {
    mountPanel(currentCard, ticker, detailRec, baseLevels, payload, token);
    settleAnchorPosition();
  } else {
    priceRec = await priceP;
    currentCard = activeSelectedCard();
    currentTicker = currentCard?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
    if (token !== mountToken || currentTicker !== ticker || !currentCard) return;
    if (priceRec?.bars?.length) {
      mountPanel(currentCard, ticker, priceRec, baseLevels, payload, token);
      settleAnchorPosition();
    }
  }

  const broadRows = await broadP;
  if (!priceRec && !detailRec?.bars?.length) priceRec = await priceP;
  currentCard = activeSelectedCard();
  currentTicker = currentCard?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (token !== mountToken || currentTicker !== ticker || !currentCard) return;

  const rec = withBroadHistory(detailRec, priceRec, broadRows);
  const broadLatest = Array.isArray(broadRows) ? broadRows.at(-1) : null;
  const levels = {
    callWall: baseLevels.callWall ?? (detailRec ? null : finiteValue(broadLatest?.call_wall)),
    gammaFlip: baseLevels.gammaFlip ?? (detailRec ? null : finiteValue(broadLatest?.gamma_flip)),
    putWall: baseLevels.putWall ?? (detailRec ? null : finiteValue(broadLatest?.put_wall)),
    expectedLow: baseLevels.expectedLow,
    expectedHigh: baseLevels.expectedHigh,
  };
  mountPanel(currentCard, ticker, rec, levels, payload, token);
  settleAnchorPosition();
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => mountCurrent().catch(error => console.error('OPTIONS_CHART', error)));
}

function installNavigationBehavior() {
  if (document.documentElement.dataset.chartAnchorPatched === '2') return;
  document.documentElement.dataset.chartAnchorPatched = '2';
  document.addEventListener('pointerdown', event => {
    const item = event.target.closest?.('[data-ticker]');
    if (!item) return;
    const ticker = String(item.dataset.ticker || '').trim().toUpperCase();
    if (ticker) {
      loadPrice(ticker).catch(() => null);
      loadShard(ticker).catch(() => []);
    }
    if (item.closest('#suggestions') || item.closest('#selectedSection')) return;
    preserveAnchor = item;
    preserveAnchorTop = item.getBoundingClientRect().top;
  }, true);
}

function boot() {
  const selected = document.querySelector('#selected');
  if (!selected) return;
  installNavigationBehavior();
  loadPayload(false).catch(() => ({ tickers: {} }));
  new MutationObserver(() => {
    restoreAnchorPosition();
    schedule();
  }).observe(selected, { childList: true });
  window.addEventListener('options:inline-selected-change', schedule);
  schedule();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
else boot();
})();

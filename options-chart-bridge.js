(() => {
'use strict';

const SAME = './options_chart_data.json';
const RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_chart_data.json';
const SHARD_BASE = './options_chart_history';
const SHARD_RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_chart_history';
let payloadPromise = null;
const shardPromises = new Map();
let activeChart = null;
let scheduled = false;

const numText = text => {
  const m = String(text || '').replaceAll(',', '').match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
};
const money = v => Number.isFinite(Number(v)) ? '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shardKey = ticker => {
  const c = String(ticker || '_').trim().toUpperCase()[0] || '_';
  return /^[A-Z0-9]$/.test(c) ? c : '_';
};

async function fetchJson(urls, label) {
  let last = null;
  for (const url of urls) {
    try {
      const r = await fetch(`${url}?v=${Date.now()}`, { cache: 'no-store' });
      if (!r.ok) { last = new Error(`${label}:${r.status}`); continue; }
      const j = await r.json();
      if (j && typeof j === 'object') return j;
    } catch (e) { last = e; }
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

function readLevel(card, label) {
  for (const el of card.querySelectorAll('.bigLv')) {
    if (el.querySelector('span')?.textContent?.trim() === label) return numText(el.querySelector('b')?.textContent);
  }
  return null;
}

function readExpected(card) {
  const spans = [...card.querySelectorAll('.expectedRow span')];
  const txt = spans.map(x => x.textContent || '').find(x => x.includes('想定レンジ')) || '';
  const clean = txt.replaceAll(',', '');
  const m = clean.match(/(?:\$)?(-?\d+(?:\.\d+)?)\s*～\s*(?:\$)?(-?\d+(?:\.\d+)?)/);
  return m ? { low: Number(m[1]), high: Number(m[2]) } : { low: null, high: null };
}

function withBroadHistory(detailRec, broadRows) {
  const rows = Array.isArray(broadRows) ? broadRows : [];
  if (detailRec) {
    return {
      ...detailRec,
      spot_history: rows,
      wall_history: rows.length ? rows : (detailRec.wall_history || []),
      wall_history_days: rows.filter(r => r.call_wall != null || r.put_wall != null || r.gamma_flip != null).length,
      options_history_days: rows.length,
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
    chart_mode: 'options_spot',
    source: 'broad_daily_options_history',
  };
}

function chartPanel(ticker, rec, levels, payload) {
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
  const wallStatus = wallDays > 0 ? `<span>Wall履歴 ${wallDays}日</span>` : '<span class="warn">Wall履歴なし</span>';
  const broadStatus = !hasCandles && obsDays ? '<span>Broad 7–21DTE</span>' : '';
  const legend = available ? `<div class="v38ChartLegend">
    ${hasCandles ? '<span><b>21EMA</b></span><span><b>50MA</b></span><span><b>200MA</b></span><span><b>63VWAP</b></span>' : '<span><b>Spot</b></span>'}
    ${levels.callWall !== null ? `<span class="call">Call <b>${money(levels.callWall)}</b></span>` : ''}
    ${levels.gammaFlip !== null ? `<span class="flip">Flip <b>${money(levels.gammaFlip)}</b></span>` : ''}
    ${levels.putWall !== null ? `<span class="put">Put <b>${money(levels.putWall)}</b></span>` : ''}
    ${levels.expectedLow !== null && levels.expectedHigh !== null ? `<span class="exp">Expected <b>${money(levels.expectedLow)}–${money(levels.expectedHigh)}</b></span>` : ''}
  </div>` : '';
  const pending = obsDays === 1
    ? '<div class="v38ChartPending"><b>Options日次履歴 1日</b>2営業日以上たまるとSpotとWall推移を表示します。</div>'
    : '<div class="v38ChartPending"><b>Options日次履歴なし</b>対象銘柄の有効な日次Options観測がたまると自動表示されます。</div>';
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

async function mountCurrent() {
  scheduled = false;
  const selected = document.querySelector('#selected');
  const card = selected?.querySelector('.selectedCard');
  const ticker = card?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (!card || !ticker) return;

  if (activeChart) {
    try { activeChart.destroy(); } catch (_) {}
    activeChart = null;
  }
  card.querySelector('.v38ChartPanel')?.remove();

  let payload = null;
  try { payload = await loadPayload(false); } catch (_) { payload = { tickers: {} }; }
  const [detailRec, broadRows] = await Promise.all([
    Promise.resolve(payload?.tickers?.[ticker] || null),
    loadShard(ticker),
  ]);
  const rec = withBroadHistory(detailRec, broadRows);
  const broadLatest = Array.isArray(broadRows) ? broadRows.at(-1) : null;
  const expected = readExpected(card);
  const levels = {
    callWall: readLevel(card, 'Call壁') ?? (detailRec ? null : Number.isFinite(Number(broadLatest?.call_wall)) ? Number(broadLatest.call_wall) : null),
    gammaFlip: readLevel(card, 'Gamma Flip') ?? (detailRec ? null : Number.isFinite(Number(broadLatest?.gamma_flip)) ? Number(broadLatest.gamma_flip) : null),
    putWall: readLevel(card, 'Put支持') ?? (detailRec ? null : Number.isFinite(Number(broadLatest?.put_wall)) ? Number(broadLatest.put_wall) : null),
    expectedLow: expected.low,
    expectedHigh: expected.high,
  };

  const holder = document.createElement('div');
  holder.innerHTML = chartPanel(ticker, rec, levels, payload);
  const panel = holder.firstElementChild;
  const anchor = card.querySelector('.directionHero') || card.querySelector('.selectedBadges') || card.querySelector('.selectedTop');
  if (anchor?.parentNode) anchor.insertAdjacentElement('afterend', panel);
  else card.appendChild(panel);

  const canvas = panel.querySelector('[data-v38-chart]');
  if (canvas && rec && window.V38Chart?.mount) {
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
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => mountCurrent().catch(err => console.error('OPTIONS_CHART', err)));
}

function boot() {
  const selected = document.querySelector('#selected');
  if (!selected) return;
  new MutationObserver(schedule).observe(selected, { childList: true });
  schedule();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
else boot();
})();

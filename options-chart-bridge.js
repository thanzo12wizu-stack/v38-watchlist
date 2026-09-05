(() => {
'use strict';

const SAME = './options_chart_data.json';
const RAW = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/options_chart_data.json';
let payloadPromise = null;
let activeChart = null;
let scheduled = false;

const numText = text => {
  const m = String(text || '').replaceAll(',', '').match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
};
const money = v => Number.isFinite(Number(v)) ? '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function loadPayload(force = false) {
  if (force) payloadPromise = null;
  if (payloadPromise) return payloadPromise;
  payloadPromise = (async () => {
    let last = null;
    for (const url of [SAME, RAW]) {
      try {
        const r = await fetch(`${url}?v=${Date.now()}`, { cache: 'no-store' });
        if (!r.ok) { last = new Error(`chart data ${r.status}`); continue; }
        const j = await r.json();
        if (j && typeof j === 'object') return j;
      } catch (e) { last = e; }
    }
    throw last || new Error('chart data unavailable');
  })();
  return payloadPromise;
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

function chartPanel(ticker, rec, levels, payload) {
  const available = !!rec?.bars?.length;
  const stale = !!rec?.stale;
  const historyDay = rec?.history_session_date || '—';
  const session = payload?.session_date || '—';
  const wallDays = Number(rec?.wall_history_days || rec?.wall_history?.length || 0);
  const status = stale ? '<span class="warn">履歴更新失敗・前回値</span>' : '<span>価格履歴 OK</span>';
  const wallStatus = wallDays > 0 ? `<span>Wall履歴 ${wallDays}日</span>` : '<span class="warn">Wall履歴なし</span>';
  const legend = available ? `<div class="v38ChartLegend">
    <span><b>21EMA</b></span><span><b>50MA</b></span><span><b>200MA</b></span>
    ${levels.callWall !== null ? `<span class="call">Call <b>${money(levels.callWall)}</b></span>` : ''}
    ${levels.gammaFlip !== null ? `<span class="flip">Flip <b>${money(levels.gammaFlip)}</b></span>` : ''}
    ${levels.putWall !== null ? `<span class="put">Put <b>${money(levels.putWall)}</b></span>` : ''}
    ${levels.expectedLow !== null && levels.expectedHigh !== null ? `<span class="exp">Expected <b>${money(levels.expectedLow)}–${money(levels.expectedHigh)}</b></span>` : ''}
  </div>` : '';
  return `<section class="v38ChartPanel" data-chart-ticker="${esc(ticker)}">
    <div class="v38ChartHead"><div class="v38ChartHeadLeft"><span class="v38ChartEyebrow">PRICE + OPTIONS MAP</span><div class="v38ChartTitle"><b>${esc(ticker)}</b><span>日足 1年</span></div></div><div class="v38ChartStatus"><span>最終足 ${esc(historyDay)}</span><span>Options基準 ${esc(session)}</span>${wallStatus}${status}</div></div>
    ${legend}
    ${available ? '<div class="v38ChartCanvas" data-v38-chart></div>' : '<div class="v38ChartPending"><b>価格チャート履歴を生成中</b>Options判定とは独立した表示専用データです。次のChart Data更新後に自動表示されます。</div>'}
    <div class="v38ChartFoot"><span>現在のWall / Flipは右端の水平線、過去履歴は薄い階段線。観測のない日や満期切替は補間しません。</span><a href="https://www.tradingview.com/" target="_blank" rel="noopener">TradingView Lightweight Charts™ · Copyright © 2025 TradingView, Inc.</a></div>
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
  const rec = payload?.tickers?.[ticker] || null;
  const expected = readExpected(card);
  const levels = {
    callWall: readLevel(card, 'Call壁'),
    gammaFlip: readLevel(card, 'Gamma Flip'),
    putWall: readLevel(card, 'Put支持'),
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
  if (canvas && rec?.bars?.length && window.V38Chart?.mount) {
    activeChart = window.V38Chart.mount({
      element: canvas,
      bars: rec.bars,
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

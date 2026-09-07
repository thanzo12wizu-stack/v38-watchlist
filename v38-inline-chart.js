(() => {
'use strict';

const PRIMARY_BASE = './v38_chart_data';
const ROTATION_BASE = './rotation/data/stock-chart';
const OPTIONS_BROAD = './options_chart_data.json';
const shardPromises = new Map();
let optionsPayloadPromise = null;
let activeChart = null;
let activeSlot = null;
let activeTicker = null;
let annotateScheduled = false;
let depsPromise = null;

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
}[c]));

function bucket(ticker) {
  const c = String(ticker || '').trim().toUpperCase()[0] || 'OTHER';
  return /^[A-Z]$/.test(c) ? c : 'OTHER';
}

function addStyle(href) {
  if ([...document.styleSheets].some(s => String(s.href || '').includes(href.replace('./', '')))) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `${href}?v=20260907-v38inline1`;
  document.head.appendChild(link);
}

function addLocalStyle() {
  if (document.getElementById('v38InlineChartStyle')) return;
  const style = document.createElement('style');
  style.id = 'v38InlineChartStyle';
  style.textContent = `
    [data-v38-chart-symbol]{cursor:pointer}
    .pick[data-v38-chart-symbol]{transition:border-color .15s ease,transform .15s ease}
    .pick[data-v38-chart-symbol]:active{transform:scale(.995)}
    .pick[data-v38-chart-symbol]::after{content:"チャート";position:absolute;right:10px;top:10px;font-size:9px;font-weight:800;letter-spacing:.04em;color:#9ecbff;border:1px solid rgba(158,203,255,.22);background:rgba(22,36,62,.8);border-radius:999px;padding:3px 6px}
    td[data-v38-chart-symbol] b,.poshead [data-v38-chart-symbol]{text-decoration:underline;text-decoration-color:rgba(140,183,255,.45);text-underline-offset:3px}
    .v38InlineChartRow td{padding:0!important;border-bottom:1px solid #20334a}
    .v38InlineChartSlot{grid-column:1/-1;min-width:0;width:100%}
    .v38InlineChartClose{appearance:none;border:1px solid rgba(255,255,255,.12);background:#172334;color:#d8e6f8;border-radius:999px;padding:6px 10px;font-size:11px;font-weight:800;cursor:pointer}
    .v38InlineChartHint{font-size:10px;color:#89919d}
    .v38InlineChartMissing{padding:26px 16px;text-align:center;color:#9caec4;font-size:12px;line-height:1.6}
    @media(max-width:680px){.pick[data-v38-chart-symbol]::after{right:8px;top:8px}.v38InlineChartClose{padding:6px 9px}}
  `;
  document.head.appendChild(style);
}

function loadScript(src, test) {
  if (test?.()) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = [...document.scripts].find(s => String(s.src || '').includes(src));
    if (existing) {
      const timer = setInterval(() => {
        if (test?.()) {
          clearInterval(timer);
          resolve();
        }
      }, 30);
      setTimeout(() => {
        clearInterval(timer);
        test?.() ? resolve() : reject(new Error(`script not ready: ${src}`));
      }, 8000);
      return;
    }
    const script = document.createElement('script');
    script.src = src;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`script load failed: ${src}`));
    document.body.appendChild(script);
  });
}

function ensureDeps() {
  if (depsPromise) return depsPromise;
  addStyle('./options-chart.css');
  addLocalStyle();
  depsPromise = (async () => {
    await loadScript(
      'https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js',
      () => !!window.LightweightCharts,
    );
    await loadScript('./options-chart.js?v=20260907-v38inline1', () => !!window.V38Chart?.mount);
  })();
  return depsPromise;
}

async function fetchJson(url) {
  const response = await fetch(`${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

async function loadShard(ticker) {
  const key = bucket(ticker);
  if (!shardPromises.has(key)) {
    shardPromises.set(key, (async () => {
      try {
        const primary = await fetchJson(`${PRIMARY_BASE}/${key}.json`);
        return { primary, rotation: null };
      } catch (_) {
        try {
          const rotation = await fetchJson(`${ROTATION_BASE}/${key}.json`);
          return { primary: null, rotation };
        } catch (_) {
          return { primary: null, rotation: null };
        }
      }
    })());
  }
  const pair = await shardPromises.get(key);
  return pair.primary?.tickers?.[ticker] || pair.rotation?.tickers?.[ticker] || null;
}

async function loadOptionsFallback(ticker) {
  if (!optionsPayloadPromise) {
    optionsPayloadPromise = fetchJson(OPTIONS_BROAD).catch(() => ({ tickers: {} }));
  }
  const payload = await optionsPayloadPromise;
  return payload?.tickers?.[ticker] || null;
}

async function loadRecord(ticker) {
  const shard = await loadShard(ticker);
  if (shard?.bars?.length) return shard;
  const fallback = await loadOptionsFallback(ticker);
  if (fallback?.bars?.length) return fallback;
  return null;
}

function mark(el, ticker) {
  if (!el || !ticker) return;
  el.dataset.v38ChartSymbol = String(ticker).trim().toUpperCase();
  el.setAttribute('role', el.getAttribute('role') || 'button');
  if (!el.hasAttribute('tabindex')) el.tabIndex = 0;
  el.setAttribute('aria-label', `${ticker} のチャートを開く`);
}

function cellTicker(row, index) {
  const cell = row?.cells?.[index];
  const text = cell?.textContent?.trim()?.toUpperCase();
  const match = text?.match(/[A-Z][A-Z0-9.-]{0,9}/);
  return match?.[0] || null;
}

function annotate() {
  annotateScheduled = false;

  document.querySelectorAll('.pick').forEach(card => {
    const ticker = card.querySelector('.ticker')?.textContent?.trim()?.toUpperCase();
    if (ticker) mark(card, ticker);
  });

  document.querySelectorAll('#candidateRows tr').forEach(row => {
    const cell = row.cells?.[1];
    const ticker = cellTicker(row, 1);
    if (cell && ticker) mark(cell, ticker);
  });

  document.querySelectorAll('#resetHoldingRows tr').forEach(row => {
    const cell = row.cells?.[0];
    const ticker = cellTicker(row, 0);
    if (cell && ticker) mark(cell, ticker);
  });

  document.querySelectorAll('#resetSignalRows tr').forEach(row => {
    const cell = row.cells?.[0];
    const ticker = cellTicker(row, 0);
    if (cell && ticker) mark(cell, ticker);
  });

  document.querySelectorAll('#resetWatchRows tr').forEach(row => {
    const cell = row.cells?.[1];
    const ticker = cellTicker(row, 1);
    if (cell && ticker) mark(cell, ticker);
  });

  document.querySelectorAll('#positionList .pos').forEach(pos => {
    const symbolEl = pos.querySelector('.poshead b:first-child');
    const ticker = symbolEl?.textContent?.trim()?.toUpperCase();
    if (symbolEl && ticker) mark(symbolEl, ticker);
  });
}

function scheduleAnnotate() {
  if (annotateScheduled) return;
  annotateScheduled = true;
  requestAnimationFrame(annotate);
}

function destroyActive() {
  if (activeChart) {
    try { activeChart.destroy(); } catch (_) {}
    activeChart = null;
  }
  activeSlot?.remove();
  activeSlot = null;
  activeTicker = null;
}

function slotFor(trigger) {
  const row = trigger.closest('tr');
  if (row) {
    const chartRow = document.createElement('tr');
    chartRow.className = 'v38InlineChartRow';
    const cell = document.createElement('td');
    cell.colSpan = Math.max(1, row.cells?.length || 1);
    const slot = document.createElement('div');
    slot.className = 'v38InlineChartSlot';
    cell.appendChild(slot);
    chartRow.appendChild(cell);
    row.insertAdjacentElement('afterend', chartRow);
    return { slot, wrapper: chartRow };
  }

  const pick = trigger.closest('.pick');
  if (pick) {
    const grid = pick.closest('.picks');
    const slot = document.createElement('div');
    slot.className = 'v38InlineChartSlot';
    if (grid) grid.insertAdjacentElement('afterend', slot);
    else pick.insertAdjacentElement('afterend', slot);
    return { slot, wrapper: slot };
  }

  const pos = trigger.closest('.pos');
  if (pos) {
    const slot = document.createElement('div');
    slot.className = 'v38InlineChartSlot';
    pos.insertAdjacentElement('afterend', slot);
    return { slot, wrapper: slot };
  }

  const slot = document.createElement('div');
  slot.className = 'v38InlineChartSlot';
  trigger.insertAdjacentElement('afterend', slot);
  return { slot, wrapper: slot };
}

function panelHtml(ticker, rec) {
  const historyDay = rec?.history_session_date || rec?.bars?.at?.(-1)?.time || '—';
  const stale = !!rec?.stale;
  return `
    <section class="v38ChartPanel" data-chart-ticker="${esc(ticker)}">
      <div class="v38ChartHead">
        <div class="v38ChartHeadLeft">
          <span class="v38ChartEyebrow">PRICE CHART</span>
          <div class="v38ChartTitle"><b>${esc(ticker)}</b><span>日足 1年</span></div>
        </div>
        <div class="v38ChartStatus">
          <span>最終足 ${esc(historyDay)}</span>
          ${stale ? '<span class="warn">前回値を表示</span>' : '<span>価格履歴 OK</span>'}
          <button type="button" class="v38InlineChartClose">閉じる</button>
        </div>
      </div>
      <div class="v38ChartLegend">
        <span class="tech ema"><b>21EMA</b></span>
        <span class="tech sma150"><b>150SMA</b></span>
        <span class="tech vwap"><b>63VWAP</b></span>
        <span><b>NQSAR背景</b></span>
      </div>
      <div class="v38ChartCanvas" data-v38-inline-canvas></div>
      <div class="v38ChartFoot">
        <span>表示専用。V38順位・Market Mode・売買ルールには使用しません。</span>
        <span class="v38InlineChartHint">ドラッグ / ピンチ / ホイールで拡大縮小</span>
      </div>
    </section>`;
}

function loadingHtml(ticker) {
  return `
    <section class="v38ChartPanel" data-chart-loading="1">
      <div class="v38ChartHead">
        <div class="v38ChartHeadLeft">
          <span class="v38ChartEyebrow">PRICE CHART</span>
          <div class="v38ChartTitle"><b>${esc(ticker)}</b><span>日足を準備中</span></div>
        </div>
        <button type="button" class="v38InlineChartClose">閉じる</button>
      </div>
      <div class="v38ChartCanvas"><div class="v38ChartPending"><b>チャートを読み込み中</b>V38用の価格履歴を取得しています。</div></div>
    </section>`;
}

function missingHtml(ticker) {
  return `
    <section class="v38ChartPanel">
      <div class="v38ChartHead">
        <div class="v38ChartHeadLeft">
          <span class="v38ChartEyebrow">PRICE CHART</span>
          <div class="v38ChartTitle"><b>${esc(ticker)}</b><span>価格履歴なし</span></div>
        </div>
        <button type="button" class="v38InlineChartClose">閉じる</button>
      </div>
      <div class="v38InlineChartMissing">この銘柄のV38チャート履歴がまだ生成されていません。次回チャート更新時に自動取得対象になります。</div>
    </section>`;
}

async function openChart(trigger, ticker) {
  if (activeTicker === ticker && activeSlot?.isConnected) {
    destroyActive();
    return;
  }

  destroyActive();
  activeTicker = ticker;
  const { slot } = slotFor(trigger);
  activeSlot = slot;
  slot.innerHTML = loadingHtml(ticker);
  slot.querySelector('.v38InlineChartClose')?.addEventListener('click', destroyActive, { once: true });

  const token = ticker;
  try {
    await ensureDeps();
    const rec = await loadRecord(ticker);
    if (activeTicker !== token || !activeSlot?.isConnected) return;

    if (!rec?.bars?.length) {
      activeSlot.innerHTML = missingHtml(ticker);
      activeSlot.querySelector('.v38InlineChartClose')?.addEventListener('click', destroyActive, { once: true });
      return;
    }

    activeSlot.innerHTML = panelHtml(ticker, rec);
    activeSlot.querySelector('.v38InlineChartClose')?.addEventListener('click', destroyActive, { once: true });
    const canvas = activeSlot.querySelector('[data-v38-inline-canvas]');
    activeChart = window.V38Chart.mount({
      element: canvas,
      bars: rec.bars || [],
      ticker,
      levels: {},
      wallHistory: [],
      stale: !!rec.stale,
    });
  } catch (error) {
    console.error('V38_INLINE_CHART', error);
    if (activeTicker !== token || !activeSlot?.isConnected) return;
    activeSlot.innerHTML = missingHtml(ticker);
    activeSlot.querySelector('.v38InlineChartClose')?.addEventListener('click', destroyActive, { once: true });
  }
}

function activate(trigger) {
  const ticker = String(trigger?.dataset?.v38ChartSymbol || '').trim().toUpperCase();
  if (!ticker) return;
  openChart(trigger, ticker);
}

function onClick(event) {
  const trigger = event.target.closest?.('[data-v38-chart-symbol]');
  if (!trigger) return;
  if (event.target.closest('button,input,select,textarea') && !event.target.closest('.v38InlineChartClose')) return;
  const link = event.target.closest('a');
  if (link && /tradingview\.com\/chart/i.test(link.href || '')) {
    event.preventDefault();
    event.stopPropagation();
  }
  activate(trigger);
}

function onKey(event) {
  if (!['Enter', ' '].includes(event.key)) return;
  const trigger = event.target.closest?.('[data-v38-chart-symbol]');
  if (!trigger) return;
  event.preventDefault();
  activate(trigger);
}

function boot() {
  addStyle('./options-chart.css');
  addLocalStyle();
  scheduleAnnotate();
  const observer = new MutationObserver(scheduleAnnotate);
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKey, true);
  window.addEventListener('beforeunload', destroyActive);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
})();
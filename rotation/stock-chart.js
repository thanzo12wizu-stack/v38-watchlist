(() => {
'use strict';

const L = () => window.LightweightCharts;
const finite = value => Number.isFinite(Number(value)) ? Number(value) : null;
const shardCache = new Map();
let regimePromise = null;
const activeHosts = new Set();

function bucketFor(ticker) {
  const first = String(ticker || '').trim().toUpperCase().slice(0, 1);
  return /^[A-Z]$/.test(first) ? first : 'OTHER';
}

async function readJson(url) {
  const response = await fetch(url, {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function loadShard(ticker) {
  const bucket = bucketFor(ticker);
  if (!shardCache.has(bucket)) {
    const url = new URL(`data/stock-chart/${bucket}.json`, window.location.href).href;
    shardCache.set(bucket, readJson(url).catch(error => {
      shardCache.delete(bucket);
      throw error;
    }));
  }
  return shardCache.get(bucket);
}

function loadRegimes() {
  if (!regimePromise) {
    const url = new URL('../trend_history.json', window.location.href).href;
    regimePromise = readJson(url).then(rows => Array.isArray(rows) ? rows : []).catch(error => {
      regimePromise = null;
      throw error;
    });
  }
  return regimePromise;
}

function ema(bars, n) {
  const out = [];
  const k = 2 / (n + 1);
  let previous = null;
  for (const bar of bars) {
    const close = finite(bar.close);
    if (close === null) continue;
    previous = previous === null ? close : close * k + previous * (1 - k);
    out.push({time: bar.time, value: previous});
  }
  return out;
}

function rollingVwap(bars, n) {
  const out = [];
  const queue = [];
  let pvSum = 0;
  let volumeSum = 0;
  for (const bar of bars) {
    const high = finite(bar.high);
    const low = finite(bar.low);
    const close = finite(bar.close);
    const volume = finite(bar.volume);
    if ([high, low, close, volume].some(value => value === null) || volume < 0) continue;
    const pv = ((high + low + close) / 3) * volume;
    queue.push({pv, volume});
    pvSum += pv;
    volumeSum += volume;
    if (queue.length > n) {
      const old = queue.shift();
      pvSum -= old.pv;
      volumeSum -= old.volume;
    }
    if (queue.length === n && volumeSum > 0) {
      out.push({time: bar.time, value: pvSum / volumeSum});
    }
  }
  return out;
}

function addLine(chart, data, color) {
  if (!data.length) return null;
  const lib = L();
  const series = chart.addSeries(lib.LineSeries, {
    title: '',
    priceScaleId: 'right',
    lineWidth: 1,
    color,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  });
  series.setData(data);
  return series;
}

function cleanBars(rows) {
  return (rows || []).map(row => ({
    time: String(row.time || '').slice(0, 10),
    open: finite(row.open),
    high: finite(row.high),
    low: finite(row.low),
    close: finite(row.close),
    volume: finite(row.volume) || 0,
  })).filter(row => row.time && [row.open, row.high, row.low, row.close].every(value => value !== null))
    .sort((a, b) => a.time.localeCompare(b.time));
}

function normalizeRegime(value) {
  const key = String(value || '').trim().toLowerCase();
  return ['blue', 'green', 'yellow', 'red'].includes(key) ? key : null;
}

function createNqsarLayer(element, chart, bars, regimes) {
  const layer = document.createElement('div');
  layer.className = 'rotation-nqsar-layer';
  layer.setAttribute('aria-hidden', 'true');
  element.appendChild(layer);

  const barDates = new Set(bars.map(bar => bar.time));
  const rows = (regimes || []).map(row => ({
    time: String(Array.isArray(row) ? row[0] : row?.date || '').slice(0, 10),
    regime: normalizeRegime(Array.isArray(row) ? row[1] : row?.state),
  })).filter(row => row.time && row.regime && barDates.has(row.time));

  function render() {
    if (!layer.isConnected) return;
    const points = rows.map(row => ({
      ...row,
      x: chart.timeScale().timeToCoordinate(row.time),
    })).filter(row => Number.isFinite(row.x));

    layer.innerHTML = '';
    if (!points.length) return;

    points.forEach((point, index) => {
      const previous = points[index - 1];
      const next = points[index + 1];
      const leftGap = previous ? point.x - previous.x : (next ? next.x - point.x : 6);
      const rightGap = next ? next.x - point.x : (previous ? point.x - previous.x : 6);
      const left = point.x - Math.max(2, leftGap / 2);
      const right = point.x + Math.max(2, rightGap / 2);
      if (right < 0 || left > element.clientWidth) return;
      const band = document.createElement('div');
      band.className = `rotation-nqsar-band ${point.regime}`;
      band.style.left = `${left}px`;
      band.style.width = `${Math.max(1, right - left)}px`;
      layer.appendChild(band);
    });
  }

  const schedule = () => requestAnimationFrame(render);
  chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
  requestAnimationFrame(render);

  return {
    schedule,
    destroy() {
      try { chart.timeScale().unsubscribeVisibleLogicalRangeChange(schedule); } catch (_) {}
      layer.remove();
    },
  };
}

function destroy(element) {
  if (!element) return;
  const state = element.__rotationStockChartState;
  if (state?.destroy) {
    try { state.destroy(); } catch (_) {}
  }
  element.__rotationStockChartState = null;
  activeHosts.delete(element);
}

function sweep() {
  Array.from(activeHosts).forEach(element => {
    if (!element.isConnected) destroy(element);
  });
}

async function mount({element, ticker}) {
  if (!element) return null;
  sweep();
  destroy(element);

  const symbol = String(ticker || '').trim().toUpperCase();
  element.classList.remove('is-stale');
  element.innerHTML = '<div class="rotation-stock-chart-loading">チャートを読み込み中…</div>';

  const lib = L();
  if (!lib) {
    element.innerHTML = '<div class="rotation-stock-chart-error">チャートライブラリを読み込めませんでした。</div>';
    return null;
  }

  let shard;
  let regimes;
  try {
    [shard, regimes] = await Promise.all([loadShard(symbol), loadRegimes()]);
  } catch (error) {
    if (!element.isConnected) return null;
    element.innerHTML = '<div class="rotation-stock-chart-error">価格チャートデータを読み込めませんでした。</div>';
    return null;
  }
  if (!element.isConnected) return null;

  const record = shard?.tickers?.[symbol];
  const bars = cleanBars(record?.bars || []);
  if (!record || bars.length < 20) {
    element.innerHTML = '<div class="rotation-stock-chart-error">この銘柄の価格履歴がまだありません。</div>';
    return null;
  }

  element.innerHTML = '';
  if (record.stale) element.classList.add('is-stale');

  const chart = lib.createChart(element, {
    width: Math.max(280, element.clientWidth || 640),
    height: Math.max(315, element.clientHeight || 390),
    layout: {
      background: {type: lib.ColorType.Solid, color: '#0b0d10'},
      textColor: '#aeb5bf',
      attributionLogo: true,
    },
    grid: {
      vertLines: {color: 'rgba(255,255,255,.035)'},
      horzLines: {color: 'rgba(255,255,255,.045)'},
    },
    rightPriceScale: {
      borderColor: 'rgba(255,255,255,.12)',
      scaleMargins: {top: .07, bottom: .08},
    },
    timeScale: {
      borderColor: 'rgba(255,255,255,.12)',
      timeVisible: false,
      rightOffset: 8,
      barSpacing: 6,
      minBarSpacing: 3,
    },
    crosshair: {mode: lib.CrosshairMode.Normal},
    handleScroll: true,
    handleScale: true,
  });

  const candles = chart.addSeries(lib.CandlestickSeries, {
    priceScaleId: 'right',
    upColor: '#57c785',
    downColor: '#ef6a6a',
    borderUpColor: '#57c785',
    borderDownColor: '#ef6a6a',
    wickUpColor: '#57c785',
    wickDownColor: '#ef6a6a',
    priceLineVisible: false,
  });
  candles.setData(bars.map(({time, open, high, low, close}) => ({time, open, high, low, close})));

  addLine(chart, ema(bars, 21), '#f4c75a');
  addLine(chart, rollingVwap(bars, 63), '#4fc7bd');
  addLine(chart, ema(bars, 150), '#6fb8ff');

  const nqsarLayer = createNqsarLayer(element, chart, bars, regimes);
  const initialFrom = Math.max(0, bars.length - 125);
  chart.timeScale().setVisibleLogicalRange({from: initialFrom, to: bars.length + 5});

  const resizeObserver = new ResizeObserver(() => {
    if (!element.isConnected) return;
    chart.applyOptions({
      width: Math.max(280, element.clientWidth || 640),
      height: Math.max(315, element.clientHeight || 390),
    });
    nqsarLayer.schedule();
  });
  resizeObserver.observe(element);

  const state = {
    ticker: symbol,
    destroy() {
      resizeObserver.disconnect();
      nqsarLayer.destroy();
      try { chart.remove(); } catch (_) {}
    },
  };
  element.__rotationStockChartState = state;
  activeHosts.add(element);
  return state;
}

window.RotationStockChart = {mount, destroy, sweep};
})();

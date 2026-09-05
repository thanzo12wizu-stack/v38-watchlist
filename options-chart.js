(() => {
'use strict';

const L = () => window.LightweightCharts;
const finite = v => Number.isFinite(Number(v)) ? Number(v) : null;

function sma(bars, n) {
  const out = [], q = [];
  let sum = 0;
  for (const b of bars) {
    const c = finite(b.close);
    if (c === null) continue;
    q.push(c); sum += c;
    if (q.length > n) sum -= q.shift();
    if (q.length === n) out.push({ time: b.time, value: sum / n });
  }
  return out;
}

function ema(bars, n) {
  const out = [];
  const k = 2 / (n + 1);
  let prev = null;
  for (const b of bars) {
    const c = finite(b.close);
    if (c === null) continue;
    prev = prev === null ? c : c * k + prev * (1 - k);
    out.push({ time: b.time, value: prev });
  }
  return out;
}

function rollingVwap(bars, n) {
  const out = [], q = [];
  let pvSum = 0, volSum = 0;
  for (const b of bars) {
    const h = finite(b.high), l = finite(b.low), c = finite(b.close), v = finite(b.volume);
    if ([h, l, c, v].some(x => x === null) || v < 0) continue;
    const pv = ((h + l + c) / 3) * v;
    q.push({ pv, v });
    pvSum += pv; volSum += v;
    if (q.length > n) {
      const old = q.shift();
      pvSum -= old.pv; volSum -= old.v;
    }
    if (q.length === n && volSum > 0) out.push({ time: b.time, value: pvSum / volSum });
  }
  return out;
}

function addLine(chart, data, title, opts = {}) {
  if (!data?.length) return null;
  const lib = L();
  const s = chart.addSeries(lib.LineSeries, {
    title,
    lineWidth: opts.lineWidth ?? 1,
    lineStyle: opts.lineStyle ?? lib.LineStyle.Solid,
    lineType: opts.lineType ?? lib.LineType.Simple,
    color: opts.color,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: opts.crosshairMarkerVisible ?? false,
  });
  s.setData(data);
  return s;
}

function historySegments(bars, history, field) {
  const index = new Map(bars.map((b, i) => [b.time, i]));
  const points = (history || [])
    .map(r => ({
      time: String(r.time || '').slice(0, 10),
      value: finite(r[field]),
      expiry: String(r.expiry || ''),
    }))
    .filter(p => p.value !== null && index.has(p.time))
    .sort((a, b) => a.time.localeCompare(b.time));
  const segments = [];
  let seg = [];
  let prev = null;
  for (const p of points) {
    const i = index.get(p.time);
    const consecutive = prev && i === prev.i + 1;
    const sameExpiry = prev && (!prev.expiry || !p.expiry || prev.expiry === p.expiry);
    if (!prev || (consecutive && sameExpiry)) {
      seg.push({ time: p.time, value: p.value });
    } else {
      if (seg.length) segments.push(seg);
      seg = [{ time: p.time, value: p.value }];
    }
    prev = { i, expiry: p.expiry };
  }
  if (seg.length) segments.push(seg);
  return segments;
}

function addHistory(chart, bars, history, field, title, color) {
  const lib = L();
  for (const seg of historySegments(bars, history, field)) {
    if (seg.length < 2) continue;
    addLine(chart, seg, title, {
      color,
      lineWidth: 2,
      lineType: lib.LineType.WithSteps,
      crosshairMarkerVisible: false,
    });
  }
}

function priceLine(series, price, title, color, style) {
  const p = finite(price);
  if (p === null) return null;
  return series.createPriceLine({
    price: p,
    title,
    color,
    lineWidth: 1,
    lineStyle: style,
    axisLabelVisible: true,
  });
}

function mount({ element, bars, ticker, levels = {}, wallHistory = [], stale = false }) {
  if (!element) return null;
  const lib = L();
  if (!lib) {
    element.innerHTML = '<div class="v38ChartError">チャートライブラリを読み込めませんでした。</div>';
    return null;
  }
  const clean = (bars || []).map(b => ({
    time: String(b.time || '').slice(0, 10),
    open: finite(b.open), high: finite(b.high), low: finite(b.low), close: finite(b.close), volume: finite(b.volume) || 0,
  })).filter(b => b.time && [b.open, b.high, b.low, b.close].every(v => v !== null));
  if (clean.length < 20) {
    element.innerHTML = '<div class="v38ChartError">日足履歴が不足しています。</div>';
    return null;
  }

  element.innerHTML = '';
  element.classList.add('v38ChartCanvas');
  const chart = lib.createChart(element, {
    width: Math.max(280, element.clientWidth || 640),
    height: Math.max(330, element.clientHeight || 410),
    layout: {
      background: { type: lib.ColorType.Solid, color: '#0b0d10' },
      textColor: '#aeb5bf',
      attributionLogo: true,
    },
    grid: {
      vertLines: { color: 'rgba(255,255,255,.035)' },
      horzLines: { color: 'rgba(255,255,255,.045)' },
    },
    rightPriceScale: { borderColor: 'rgba(255,255,255,.12)', scaleMargins: { top: .08, bottom: .08 } },
    timeScale: { borderColor: 'rgba(255,255,255,.12)', timeVisible: false, rightOffset: 8, barSpacing: 7, minBarSpacing: 3 },
    crosshair: { mode: lib.CrosshairMode.Normal },
    handleScroll: true,
    handleScale: true,
  });

  const candles = chart.addSeries(lib.CandlestickSeries, {
    upColor: '#57c785', downColor: '#ef6a6a',
    borderUpColor: '#57c785', borderDownColor: '#ef6a6a',
    wickUpColor: '#57c785', wickDownColor: '#ef6a6a',
    priceLineVisible: false,
  });
  candles.setData(clean.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));

  addLine(chart, ema(clean, 21), '21EMA', { color: '#f4c75a', lineWidth: 1 });
  addLine(chart, sma(clean, 50), '50MA', { color: '#6fb8ff', lineWidth: 1 });
  addLine(chart, sma(clean, 200), '200MA', { color: '#b98cff', lineWidth: 1 });
  const vwap63 = rollingVwap(clean, 63);
  const vwap63Series = addLine(chart, vwap63, '63VWAP', { color: '#4fc7bd', lineWidth: 1 });
  const vwap63Last = finite(vwap63.at(-1)?.value);
  if (vwap63Series && vwap63Last !== null) {
    vwap63Series.createPriceLine({
      price: vwap63Last,
      title: '63VWAP',
      color: '#4fc7bd',
      lineWidth: 1,
      lineStyle: lib.LineStyle.Solid,
      lineVisible: false,
      axisLabelVisible: true,
    });
  }

  // Historical Options structure. Only consecutive trading-day observations with
  // the same expiry are connected; sparse scan observations are never interpolated.
  addHistory(chart, clean, wallHistory, 'call_wall', 'Call Wall history', 'rgba(239,119,119,.48)');
  addHistory(chart, clean, wallHistory, 'put_wall', 'Put Wall history', 'rgba(101,201,140,.48)');
  addHistory(chart, clean, wallHistory, 'gamma_flip', 'Gamma Flip history', 'rgba(240,201,77,.44)');

  priceLine(candles, levels.callWall, 'Call Wall', '#ef7777', lib.LineStyle.Dashed);
  priceLine(candles, levels.gammaFlip, 'Gamma Flip', '#f0c94d', lib.LineStyle.Dashed);
  priceLine(candles, levels.putWall, 'Put Wall', '#65c98c', lib.LineStyle.Dashed);
  priceLine(candles, levels.expectedHigh, 'Expected High', 'rgba(120,170,255,.75)', lib.LineStyle.Dotted);
  priceLine(candles, levels.expectedLow, 'Expected Low', 'rgba(120,170,255,.75)', lib.LineStyle.Dotted);

  const band = document.createElement('div');
  band.className = 'v38ExpectedBand';
  element.appendChild(band);
  const lo = finite(levels.expectedLow), hi = finite(levels.expectedHigh);
  function updateBand() {
    if (lo === null || hi === null || hi <= lo || !band.isConnected) {
      band.style.display = 'none';
      return;
    }
    const y1 = candles.priceToCoordinate(hi), y2 = candles.priceToCoordinate(lo);
    if (y1 === null || y2 === null || !Number.isFinite(y1) || !Number.isFinite(y2)) {
      band.style.display = 'none';
      return;
    }
    band.style.display = 'block';
    band.style.top = `${Math.min(y1, y2)}px`;
    band.style.height = `${Math.abs(y2 - y1)}px`;
  }

  chart.timeScale().fitContent();
  requestAnimationFrame(updateBand);
  const scheduleBand = () => requestAnimationFrame(updateBand);
  element.addEventListener('wheel', scheduleBand, { passive: true });
  element.addEventListener('pointermove', scheduleBand, { passive: true });
  element.addEventListener('touchmove', scheduleBand, { passive: true });

  const ro = new ResizeObserver(() => {
    chart.applyOptions({ width: Math.max(280, element.clientWidth || 640), height: Math.max(330, element.clientHeight || 410) });
    scheduleBand();
  });
  ro.observe(element);

  if (stale) element.classList.add('isStale');
  else element.classList.remove('isStale');

  return {
    ticker,
    chart,
    destroy() {
      ro.disconnect();
      try { chart.remove(); } catch (_) {}
    },
  };
}

window.V38Chart = { mount };
})();

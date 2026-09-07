(() => {
'use strict';

function ensureEnhancementAssets() {
  if (!document.querySelector('link[data-rotation-stock-chart-enhancement]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'stock-chart.css?v=20260907-nqsartags2';
    link.dataset.rotationStockChartEnhancement = '1';
    document.head.appendChild(link);
  }
  if (!document.querySelector('script[data-rotation-nqsar-tags]')) {
    const script = document.createElement('script');
    script.src = 'stock-chart-nqsar-tags.js?v=20260907-nqsartags2';
    script.defer = true;
    script.dataset.rotationNqsarTags = '1';
    document.head.appendChild(script);
  }
}

function symbolOf(panel) {
  const node = panel.querySelector('.rotation-stock-detail-symbol');
  if (!node) return '';
  const first = Array.from(node.childNodes).find(item => item.nodeType === 3 && String(item.textContent || '').trim());
  return String(first?.textContent || '').trim().toUpperCase();
}

function addLegend(parent, className, label) {
  const item = document.createElement('span');
  item.className = className;
  item.appendChild(document.createElement('i'));
  item.appendChild(document.createTextNode(label));
  parent.appendChild(item);
}

function addChart(panel, symbol) {
  const shell = document.createElement('section');
  shell.className = 'rotation-stock-chart-shell';

  const head = document.createElement('div');
  head.className = 'rotation-stock-chart-head';
  const title = document.createElement('div');
  title.className = 'rotation-stock-chart-title';
  title.appendChild(document.createTextNode(symbol + ' 日足チャート'));
  const sub = document.createElement('span');
  sub.className = 'rotation-stock-chart-sub';
  sub.textContent = 'NQSAR背景 × テクニカル / 色切替はタグ表示';
  title.appendChild(sub);

  const legend = document.createElement('div');
  legend.className = 'rotation-stock-chart-legend';
  addLegend(legend, 'ema21', '21EMA');
  addLegend(legend, 'vwap63', '63VWAP');
  addLegend(legend, 'ema150', '150EMA');
  addLegend(legend, 'nqsar', 'NQSAR背景');
  head.append(title, legend);

  const host = document.createElement('div');
  host.className = 'rotation-stock-chart-canvas';
  const loading = document.createElement('div');
  loading.className = 'rotation-stock-chart-loading';
  loading.textContent = 'チャートを読み込み中…';
  host.appendChild(loading);

  const foot = document.createElement('div');
  foot.className = 'rotation-stock-chart-foot';
  foot.textContent = '背景色は既存NQSAR履歴。色が切り替わる地点はNQSARタグ表示。履歴が存在しない日付は無着色。';
  shell.append(head, host, foot);

  const link = panel.querySelector('.rotation-stock-tv');
  if (link) link.insertAdjacentElement('beforebegin', shell);
  else panel.appendChild(shell);
  window.RotationStockChart.mount({element: host, ticker: symbol});
}

function scan() {
  const api = window.RotationStockChart;
  if (!api) return;
  api.sweep();
  document.querySelectorAll('.rotation-stock-detail:not([hidden])').forEach(panel => {
    if (panel.querySelector('.rotation-stock-chart-shell')) return;
    const symbol = symbolOf(panel);
    if (symbol) addChart(panel, symbol);
  });
}

ensureEnhancementAssets();
setInterval(scan, 250);
scan();
})();

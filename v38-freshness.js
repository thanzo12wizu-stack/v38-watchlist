'use strict';

(() => {
  const version = '20260907-inline-chart1';
  const add = src => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `${src}?v=${version}`;
    s.onload = resolve;
    s.onerror = reject;
    document.body.appendChild(s);
  });
  add('v38-freshness-core.js').catch(error => console.error('V38 freshness core load failed', error));
  add('v38-model-holdings.js').catch(error => console.error('V38 model holdings load failed', error));
  add('v38-inline-chart.js').catch(error => console.error('V38 inline chart load failed', error));
})();

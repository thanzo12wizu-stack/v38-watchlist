'use strict';

(() => {
  const add = src => new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `${src}?v=20260906-model-holdings`;
    s.onload = resolve;
    s.onerror = reject;
    document.body.appendChild(s);
  });
  add('v38-freshness-core.js').catch(error => console.error('V38 freshness core load failed', error));
  add('v38-model-holdings.js').catch(error => console.error('V38 model holdings load failed', error));
})();

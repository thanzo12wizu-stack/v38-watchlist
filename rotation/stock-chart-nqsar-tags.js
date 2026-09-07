(() => {
'use strict';

const pending = new WeakSet();

function regimeOf(node) {
  for (const key of ['blue', 'green', 'yellow', 'red']) {
    if (node.classList.contains(key)) return key;
  }
  return null;
}

function tagText(regime) {
  return `NQSAR ${String(regime || '').toUpperCase()}`;
}

function syncLayer(layer) {
  if (!layer?.isConnected) return;
  const bands = Array.from(layer.querySelectorAll(':scope > .rotation-nqsar-band'))
    .map(node => ({
      node,
      regime: regimeOf(node),
      left: Number.parseFloat(node.style.left || 'NaN'),
    }))
    .filter(item => item.regime && Number.isFinite(item.left))
    .sort((a, b) => a.left - b.left);
  if (!bands.length) return;

  const transitions = [];
  let previous = null;
  for (const item of bands) {
    if (item.regime !== previous) {
      transitions.push(item);
      previous = item.regime;
    }
  }

  const expected = transitions.map(item => `${item.regime}:${item.left.toFixed(2)}`).join('|');
  if (layer.dataset.nqsarTagSignature === expected) return;
  layer.dataset.nqsarTagSignature = expected;
  layer.querySelectorAll(':scope > .rotation-nqsar-tag').forEach(node => node.remove());

  transitions.forEach(item => {
    const tag = document.createElement('div');
    tag.className = `rotation-nqsar-tag ${item.regime}`;
    tag.textContent = tagText(item.regime);
    tag.style.left = `${Math.max(2, item.left + 2)}px`;
    layer.appendChild(tag);
  });
}

function schedule(layer) {
  if (!layer || pending.has(layer)) return;
  pending.add(layer);
  requestAnimationFrame(() => {
    pending.delete(layer);
    syncLayer(layer);
  });
}

const observer = new MutationObserver(mutations => {
  const layers = new Set();
  for (const mutation of mutations) {
    const direct = mutation.target?.closest?.('.rotation-nqsar-layer');
    if (direct) layers.add(direct);
    mutation.addedNodes?.forEach(node => {
      if (!(node instanceof Element)) return;
      if (node.matches('.rotation-nqsar-layer')) layers.add(node);
      node.querySelectorAll?.('.rotation-nqsar-layer').forEach(layer => layers.add(layer));
    });
  }
  layers.forEach(schedule);
});

function start() {
  document.querySelectorAll('.rotation-nqsar-layer').forEach(schedule);
  observer.observe(document.body, {subtree: true, childList: true});
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
else start();
})();

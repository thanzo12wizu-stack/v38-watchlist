'use strict';

(async () => {
  const mainRaw = 'https://raw.githubusercontent.com/thanzo12wizu-stack/v38-watchlist/main/';

  function show(message, bad = true) {
    const wrap = document.querySelector('.wrap');
    if (!wrap) return;
    let node = document.getElementById('v38FreshnessWarning');
    if (!node) {
      node = document.createElement('div');
      node.id = 'v38FreshnessWarning';
      node.className = 'note';
      const top = wrap.querySelector('.top');
      if (top && top.nextSibling) wrap.insertBefore(node, top.nextSibling);
      else wrap.prepend(node);
    }
    node.style.borderLeftColor = bad ? 'var(--bad)' : 'var(--good)';
    node.style.display = message ? '' : 'none';
    node.textContent = message || '';
  }

  try {
    const [cr, vr] = await Promise.all([
      fetch(mainRaw + 'state.json', {cache: 'no-store'}),
      fetch(mainRaw + 'v38-live-state.json', {cache: 'no-store'})
    ]);
    if (!cr.ok || !vr.ok) throw new Error('freshness source unavailable');
    const [command, live] = await Promise.all([cr.json(), vr.json()]);
    const expected = String(command.date || '');
    const got = String(live.asof || '');
    if (!expected || got !== expected) {
      show(`更新遅延：Command Center ${expected || '—'} / V38 ${got || '—'}。日付が揃うまでV38の数値は最新扱いしません。`, true);
    } else {
      show('', false);
    }
  } catch (_) {
    show('V38の更新状況を確認できません。数値を最新扱いしないでください。', true);
  }
})();

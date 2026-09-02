(() => {
  'use strict';

  const MARKET_URL = 'dashboard-market.json';
  const $ = (id) => document.getElementById(id);
  const isNum = (v) => v !== null && v !== '' && Number.isFinite(Number(v));
  const shortDate = (s) => {
    const p = String(s || '').split('-');
    return p.length === 3 ? `${p[0]}.${p[1]}.${p[2]}` : (s || '—');
  };
  const modeLabel = (m) => ({ATTACK:'攻撃',SELECTIVE:'選別',STOP:'新規停止',DEFENSE:'防御'})[String(m || '').toUpperCase()] || m || '—';
  const crowdRating = (v) => {
    if (!isNum(v)) return '—';
    const n = Number(v);
    if (n < 20) return '極端な恐怖';
    if (n < 40) return '恐怖';
    if (n < 60) return '中立';
    if (n < 80) return '強欲';
    return '極端な強欲';
  };

  let snapshot = null;
  let applying = false;
  let observer = null;

  function actionText(mode) {
    if (mode === 'STOP') return '通常個別株の新規エントリーは停止';
    if (mode === 'DEFENSE') return '防御モード：通常個別株の新規停止';
    if (mode === 'SELECTIVE') return '選別モード：新規候補を絞る';
    if (mode === 'ATTACK') return '攻撃モード：正式V38候補を実行対象へ';
    return '市場モード確認待ち';
  }

  function v38Text(mode) {
    if (mode === 'STOP') return '新規エントリー 0。Rotationが強くても買わない。';
    if (mode === 'DEFENSE') return '新規 0。既存は正式V38の防御ルールに従う。';
    if (mode === 'SELECTIVE') return '最大4枠の補充。Stock RS189中心。';
    if (mode === 'ATTACK') return '最大12枠。正式Eligibilityと攻撃時順位に従う。';
    return '市場モード未確認';
  }

  function setText(id, text) {
    const el = $(id);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function applySnapshot() {
    if (!snapshot || applying) return;
    applying = true;
    if (observer) observer.disconnect();
    try {
      const market = snapshot;
      const mode = String(market.mode || '').toUpperCase();
      const limit = market.new_entry_limit ?? '—';
      const breadth = market.breadth50;
      const nqsar = market.nqsar || '—';
      const senti = market.crowd_temperature;
      const vix = market.vix;
      const mc57 = market.market_conditions;
      const liveAsOf = market.v38_asof || market.crowd_asof || null;

      setText('heroAction', actionText(mode));
      setText('permission', String(limit));
      setText('permissionSub', `NQSAR ${nqsar} / Breadth ${isNum(breadth) ? Number(breadth).toFixed(1) + '%' : '—'}`);

      const modeEl = $('mode');
      if (modeEl) modeEl.innerHTML = `<span class="status ${mode.toLowerCase()}">${modeLabel(mode)}</span>`;
      setText('modeSub', `新規枠上限 ${limit}`);
      setText('breadth', isNum(breadth) ? `${Number(breadth).toFixed(1)}%` : '—');
      setText('nqsar', `NQSAR ${nqsar}`);
      setText('fg', isNum(senti) ? Number(senti).toFixed(1) : '—');
      setText('fgSub', isNum(senti) ? `${crowdRating(senti)} / 既存Dashboard` : '既存Dashboard 群衆温度計');

      const macroTop = $('macroTop');
      if (macroTop) {
        const current = macroTop.textContent || '';
        const rate = current.includes('/') ? current.split('/').slice(1).join('/').trim() : '—';
        macroTop.textContent = `${isNum(vix) ? Number(vix).toFixed(2) : '—'} / ${rate}`;
      }

      const strip = $('macroStrip');
      if (strip) {
        const cells = strip.querySelectorAll('.macro-cell');
        if (cells[0]) {
          const value = cells[0].querySelector('.macro-value');
          if (value) value.textContent = isNum(vix) ? Number(vix).toFixed(2) : '—';
        }
      }

      const facts = $('macroFacts');
      if (facts) {
        facts.querySelectorAll('.obs').forEach((el) => {
          if (el.textContent.includes('市場心理指数')) {
            el.textContent = el.textContent.replace('市場心理指数', '外部参考 Fear & Greed');
          }
        });
        const liveId = 'dashboardLiveContext';
        let liveFact = document.getElementById(liveId);
        if (!liveFact) {
          liveFact = document.createElement('div');
          liveFact.id = liveId;
          liveFact.className = 'obs';
          facts.prepend(liveFact);
        }
        liveFact.textContent = `既存Dashboard最新値（${shortDate(liveAsOf)}）：Market Conditions ${isNum(mc57) ? Number(mc57).toFixed(1) : '—'} / NQSAR ${nqsar} / Breadth ${isNum(breadth) ? Number(breadth).toFixed(2) + '%' : '—'} / 群衆温度計 ${isNum(senti) ? Number(senti).toFixed(1) : '—'} / VIX ${isNum(vix) ? Number(vix).toFixed(2) : '—'}`;
      }

      const hypotheses = $('hypotheses');
      if (hypotheses) {
        hypotheses.querySelectorAll('.obs').forEach((el) => {
          if (el.textContent.includes('市場心理指数')) el.textContent = el.textContent.replace('市場心理指数', '外部参考 Fear & Greed');
        });
      }

      const v38 = $('v38Action');
      if (v38) {
        v38.innerHTML = `<div class="summary-box"><div class="summary-title">現在の扱い</div><div class="summary-line"><b>${modeLabel(mode)}</b>　${v38Text(mode)}　<span class="micro">新規枠上限 ${limit}</span></div></div>`;
      }

      const rotationDateText = $('asofBadge')?.textContent || '';
      const m = rotationDateText.match(/(\d{4}\.\d{2}\.\d{2})/);
      const rotationAsOf = m ? m[1] : null;
      const liveShort = shortDate(liveAsOf);
      const align = $('alignBadge');
      if (align) {
        const same = rotationAsOf && liveShort && rotationAsOf === liveShort;
        align.textContent = same ? 'V38最新値と基準日一致' : `V38最新 ${liveShort}`;
        align.classList.toggle('ok', Boolean(same));
      }

      const quality = $('quality');
      if (quality && liveAsOf) {
        quality.querySelectorAll('.quality > div').forEach((el) => {
          if (el.textContent.startsWith('基準日：')) {
            const rotationDate = rotationAsOf || '—';
            el.innerHTML = `<strong>基準日：</strong>Rotation ${rotationDate} / V38最新 ${liveShort}（市場背景は既存Dashboardを正本として表示）`;
          }
        });
      }
    } finally {
      applying = false;
      if (observer) observer.observe(document.body, {childList:true, subtree:true, characterData:true});
    }
  }

  fetch(MARKET_URL, {cache:'no-store'}).then((r) => {
    if (!r.ok) throw new Error(`dashboard-market HTTP ${r.status}`);
    return r.json();
  }).then((market) => {
    snapshot = market;
    observer = new MutationObserver(() => {
      if (!applying) queueMicrotask(applySnapshot);
    });
    observer.observe(document.body, {childList:true, subtree:true, characterData:true});
    applySnapshot();
    setTimeout(applySnapshot, 250);
    setTimeout(applySnapshot, 1000);
  }).catch((err) => {
    console.warn('Rotation market sync failed:', err);
  });
})();

from pathlib import Path
import re


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


p = Path("options-intelligence.js")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "let expandedTickerCard = null;\nlet leaderFresh = false;",
    "let expandedTickerCard = null;\nlet inlinePeriodMode = null;\nlet leaderFresh = false;",
    "inline period state",
)

pattern = re.compile(r"function closeInlineCard\(\) \{.*?\n\}\nfunction fmtTime\(x\) \{", re.S)
new_block = r'''function closeInlineCard() {
  const card = expandedTickerCard;
  if (!card) return;
  card.querySelector(':scope > .inlineAnalysis')?.remove();
  card.classList.remove('inlineExpanded');
  card.setAttribute('aria-expanded', 'false');
  expandedTickerCard = null;
  inlinePeriodMode = null;
  window.dispatchEvent(new CustomEvent('options:inline-selected-change'));
}
function inlinePeriodData(t, mode) {
  const keep = activePeriod;
  const snapshots = {};
  let html = '';
  try {
    for (const m of ['short', 'swing', 'medium']) {
      activePeriod = m;
      rebuildRecords();
      const o = optionMap[t] || null;
      if (!o) snapshots[m] = { text: 'Optionsなし', cls: 'bLow', confidence: null };
      else if (o.period_unavailable) snapshots[m] = { text: '期間なし', cls: 'bLow', confidence: null };
      else if (!isUsable(o)) snapshots[m] = { text: '判定停止', cls: 'bLow', confidence: null };
      else {
        const d = dirView(o.direction);
        snapshots[m] = { text: `${d.arrow} ${d.label}`, cls: d.cls, confidence: o.direction?.confidence ?? null };
      }
      if (m === mode) html = selectedHtml(t);
    }
    if (!['short', 'swing', 'medium'].includes(mode)) {
      activePeriod = mode;
      rebuildRecords();
      html = selectedHtml(t);
    }
  } finally {
    activePeriod = keep;
    rebuildRecords();
  }
  return { html, snapshots };
}
function inlinePeriodControls(mode, snapshots) {
  const defs = [
    ['short', '短期', '0–6DTE'],
    ['swing', 'スイング', '7–21DTE'],
    ['medium', '中期', '22–45DTE'],
    ['multi', '複数満期', '0–45DTE'],
    ['exact', '満期指定', ''],
  ];
  const buttons = defs.map(([key, label, sub]) =>
    `<button type="button" class="inlinePeriodBtn${mode === key ? ' active' : ''}" data-inline-period="${key}"><b>${label}</b>${sub ? `<small>${sub}</small>` : ''}</button>`
  ).join('');
  const chips = [
    ['short', '短期'],
    ['swing', 'スイング'],
    ['medium', '中期'],
  ].map(([key, label]) => {
    const x = snapshots[key] || { text: '—', cls: 'bLow', confidence: null };
    const conf = x.confidence === null || x.confidence === undefined ? '' : `<small>確度 ${x.confidence}</small>`;
    return `<div class="inlineCompareChip"><span>${label}</span><b class="${x.cls}">${esc(x.text)}</b>${conf}</div>`;
  }).join('');
  return `<div class="inlinePeriodBar"><div class="inlinePeriodTitle"><b>このカードだけ期間切替</b><span>一覧の期間は変えません</span></div><div class="inlinePeriodButtons">${buttons}</div><div class="inlineCompare">${chips}</div></div>`;
}
function renderInlineCard(card, t, mode) {
  t = String(t || '').trim().toUpperCase();
  if (!card || !t || !PERIODS[mode]) return;
  const { html, snapshots } = inlinePeriodData(t, mode);
  let inline = card.querySelector(':scope > .inlineAnalysis');
  if (!inline) {
    inline = document.createElement('div');
    inline.className = 'inlineAnalysis';
    card.appendChild(inline);
  }
  inline.innerHTML = `<div class="inlineAnalysisHead"><span>${esc(t)} の銘柄分析</span><button type="button" class="inlineClose">閉じる</button></div>${inlinePeriodControls(mode, snapshots)}${html}`;
  if (mode !== 'exact') inline.querySelector('#expirySelect')?.closest('.expiryPicker')?.remove();

  inline.querySelector('.inlineClose')?.addEventListener('click', ev => {
    ev.preventDefault();
    ev.stopPropagation();
    closeInlineCard();
  });
  for (const b of inline.querySelectorAll('[data-inline-period]')) {
    b.addEventListener('click', ev => {
      ev.preventDefault();
      ev.stopPropagation();
      const next = b.dataset.inlinePeriod;
      if (!next || next === inlinePeriodMode) return;
      renderInlineCard(card, t, next);
    });
  }
  const expiry = inline.querySelector('#expirySelect');
  if (expiry) {
    expiry.addEventListener('change', ev => {
      ev.stopPropagation();
      exactExpiryByTicker[t] = expiry.value;
      renderInlineCard(card, t, 'exact');
    });
  }

  card.classList.add('inlineExpanded');
  card.setAttribute('aria-expanded', 'true');
  expandedTickerCard = card;
  inlinePeriodMode = mode;
  window.dispatchEvent(new CustomEvent('options:inline-selected-change'));
}
function toggleInlineCard(card, t) {
  t = String(t || '').trim().toUpperCase();
  if (!card || !t) return;
  if (expandedTickerCard === card && card.classList.contains('inlineExpanded')) {
    closeInlineCard();
    return;
  }
  closeInlineCard();
  $('#selectedSection').hidden = true;
  $('#selected').innerHTML = '';
  renderInlineCard(card, t, activePeriod);
}
function bind(root) {
  for (const e of root.querySelectorAll('[data-ticker]')) {
    e.setAttribute('aria-expanded', 'false');
    e.addEventListener('click', ev => {
      if (ev.target.closest('.inlineAnalysis')) return;
      toggleInlineCard(e, e.dataset.ticker);
    });
  }
}
function fmtTime(x) {'''
s, n = pattern.subn(new_block, s, count=1)
if n != 1:
    raise SystemExit("inline card block replacement failed")
p.write_text(s, encoding="utf-8")

p = Path("options-intelligence.css")
c = p.read_text(encoding="utf-8")
marker = ".inlineAnalysis .v38ChartPanel{margin-top:10px}"
addition = marker + (
    ".inlinePeriodBar{margin:0 0 12px;padding:10px;background:#0a111a;border:1px solid rgba(255,255,255,.08);border-radius:12px}"
    ".inlinePeriodTitle{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:8px}"
    ".inlinePeriodTitle b{font-size:10px}.inlinePeriodTitle span{color:var(--muted);font-size:8px}"
    ".inlinePeriodButtons{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px;-webkit-overflow-scrolling:touch;scrollbar-width:none}"
    ".inlinePeriodButtons::-webkit-scrollbar{display:none}"
    ".inlinePeriodBtn{flex:1 0 auto;min-width:94px;border:1px solid #31445b;background:#0d151f;color:#b8c5d3;border-radius:10px;padding:7px 9px;font:inherit;cursor:pointer}"
    ".inlinePeriodBtn b{display:block;font-size:10px}.inlinePeriodBtn small{display:block;color:var(--muted);font-size:7.5px;margin-top:2px}"
    ".inlinePeriodBtn.active{border-color:#6da9ff;background:#142238;color:#eef4fb;box-shadow:0 0 0 2px rgba(109,169,255,.08)}"
    ".inlineCompare{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}"
    ".inlineCompareChip{background:#0d151f;border:1px solid rgba(255,255,255,.06);border-radius:9px;padding:7px}"
    ".inlineCompareChip span{display:block;color:var(--muted);font-size:7.5px;margin-bottom:2px}.inlineCompareChip b{display:block;font-size:10.5px}"
    ".inlineCompareChip small{display:block;color:var(--muted);font-size:7.5px;margin-top:2px}"
)
if marker not in c:
    raise SystemExit("CSS marker missing")
if ".inlinePeriodBar{" in c:
    raise SystemExit("inline period CSS already exists")
c = c.replace(marker, addition, 1)
mobile = ".company{max-width:150px}}"
if mobile not in c:
    raise SystemExit("mobile CSS marker missing")
c = c.replace(
    mobile,
    ".company{max-width:150px}.inlinePeriodTitle{align-items:flex-start;flex-direction:column;gap:2px}.inlinePeriodBtn{min-width:88px}.inlineCompare{gap:4px}.inlineCompareChip{padding:6px 5px}}",
    1,
)
p.write_text(c, encoding="utf-8")

p = Path("options-intelligence.html")
h = p.read_text(encoding="utf-8")
h = replace_once(h, "./options-intelligence.css?v=20260906-inlinecard1", "./options-intelligence.css?v=20260907-inlineperiod1", "css cache")
h = replace_once(h, "./options-intelligence.js?v=20260906-inlinecard1", "./options-intelligence.js?v=20260907-inlineperiod1", "js cache")
p.write_text(h, encoding="utf-8")

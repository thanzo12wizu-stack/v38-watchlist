from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


p = Path("options-intelligence.js")
s = p.read_text(encoding="utf-8")

old = '''function inlinePeriodControls(mode, snapshots) {
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
}'''
new = '''function inlinePeriodControls(mode, t) {
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
  const tv = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(t)}`;
  return `<div class="inlinePeriodBar"><div class="inlinePeriodTitle"><div><b>チャート期間</b><span>このカードだけ切替</span></div><a class="inlineTvBtn" href="${esc(tv)}" target="_blank" rel="noopener">TradingViewで開く ↗</a></div><div class="inlinePeriodButtons">${buttons}</div></div>`;
}
function inlinePeriodCompare(snapshots) {
  const chips = [
    ['short', '短期'],
    ['swing', 'スイング'],
    ['medium', '中期'],
  ].map(([key, label]) => {
    const x = snapshots[key] || { text: '—', cls: 'bLow', confidence: null };
    const conf = x.confidence === null || x.confidence === undefined ? '' : `<small>確度 ${x.confidence}</small>`;
    return `<div class="inlineCompareChip"><span>${label}</span><b class="${x.cls}">${esc(x.text)}</b>${conf}</div>`;
  }).join('');
  return `<div class="inlineCompare">${chips}</div>`;
}'''
s = replace_once(s, old, new, "inlinePeriodControls")

old = '  inline.innerHTML = `<div class="inlineAnalysisHead"><span>${esc(t)} の銘柄分析</span><button type="button" class="inlineClose">閉じる</button></div>${inlinePeriodControls(mode, snapshots)}${html}`;'
new = '  inline.innerHTML = `<div class="inlineAnalysisHead"><span>${esc(t)} の銘柄分析</span><button type="button" class="inlineClose">閉じる</button></div>${inlinePeriodControls(mode, t)}<div class="inlineChartSlot"></div>${inlinePeriodCompare(snapshots)}${html}`;'
s = replace_once(s, old, new, "renderInlineCard")
p.write_text(s, encoding="utf-8")

p = Path("options-chart-bridge.js")
s = p.read_text(encoding="utf-8")
old = '''function insertPanel(card, panel) {
  const anchor = card.querySelector('.directionHero') || card.querySelector('.selectedBadges') || card.querySelector('.selectedTop');
  if (anchor?.parentNode) anchor.insertAdjacentElement('afterend', panel);
  else card.appendChild(panel);
}'''
new = '''function insertPanel(card, panel) {
  const inline = card.closest('.inlineAnalysis');
  const slot = inline?.querySelector(':scope > .inlineChartSlot');
  if (slot) {
    slot.replaceChildren(panel);
    return;
  }
  const anchor = card.querySelector('.directionHero') || card.querySelector('.selectedBadges') || card.querySelector('.selectedTop');
  if (anchor?.parentNode) anchor.insertAdjacentElement('afterend', panel);
  else card.appendChild(panel);
}'''
s = replace_once(s, old, new, "insertPanel")
s = replace_once(
    s,
    "  card.querySelector('.v38ChartPanel')?.remove();",
    "  const inlineRoot = card.closest('.inlineAnalysis');\n  (inlineRoot?.querySelector(':scope > .inlineChartSlot .v38ChartPanel') || card.querySelector('.v38ChartPanel'))?.remove();",
    "chart remove",
)
s = replace_once(
    s,
    '  const oldLoading = currentCard.querySelector(\'.v38ChartPanel[data-chart-loading="1"]\');',
    '  const currentInline = currentCard.closest(\'.inlineAnalysis\');\n  const oldLoading = currentInline?.querySelector(\':scope > .inlineChartSlot .v38ChartPanel[data-chart-loading="1"]\') || currentCard.querySelector(\'.v38ChartPanel[data-chart-loading="1"]\');',
    "oldLoading",
)
p.write_text(s, encoding="utf-8")

p = Path("options-intelligence.css")
s = p.read_text(encoding="utf-8")
if ".inlineChartSlot{" not in s:
    s += '''\n.inlinePeriodTitle{display:flex;align-items:center;justify-content:space-between;gap:10px}.inlinePeriodTitle>div{display:flex;flex-direction:column;gap:2px}.inlineTvBtn{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;border:1px solid #3f6a94;background:#0c1723;color:#9bc9ff;border-radius:9px;padding:7px 10px;font-size:9px;font-weight:800;text-decoration:none}.inlineTvBtn:hover{border-color:#6da9ff;color:#d8ebff}.inlinePeriodBar{margin-bottom:0}.inlinePeriodButtons{margin-bottom:0}.inlineChartSlot{margin:8px 0 10px}.inlineChartSlot .v38ChartPanel{margin-top:0}.inlineCompare{margin:0 0 12px}\n@media(max-width:720px){.inlinePeriodTitle{align-items:flex-start}.inlineTvBtn{padding:7px 8px;font-size:8.5px}.inlineChartSlot{margin-top:7px}}\n'''
p.write_text(s, encoding="utf-8")

p = Path("options-intelligence.html")
h = p.read_text(encoding="utf-8")
for old, new in {
    "options-intelligence.css?v=20260907-inlineperiod1": "options-intelligence.css?v=20260907-chartcontrols1",
    "options-intelligence.js?v=20260907-inlineperiod1": "options-intelligence.js?v=20260907-chartcontrols1",
    "options-chart-bridge.js?v=20260906-inlinecard1": "options-chart-bridge.js?v=20260907-chartcontrols1",
}.items():
    h = replace_once(h, old, new, f"cache {old}")
p.write_text(h, encoding="utf-8")

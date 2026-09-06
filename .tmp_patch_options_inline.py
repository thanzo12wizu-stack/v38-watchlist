from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


# Card taps expand in place; search keeps the top result panel.
p = Path("options-intelligence.js")
s = p.read_text(encoding="utf-8")

s = replace_once(
    s,
    "let selectedTicker = null;\nlet leaderFresh = false;",
    "let selectedTicker = null;\nlet expandedTickerCard = null;\nlet leaderFresh = false;",
    "selectedTicker state",
)

s = replace_once(
    s,
    """function setPeriod(mode, rerender = true) {
  if (!PERIODS[mode]) return;
  activePeriod = mode;
  updatePeriodUi();
  if (rerender) rebuildAndRender(selectedTicker, false);
}""",
    """function setPeriod(mode, rerender = true) {
  if (!PERIODS[mode]) return;
  if (rerender && expandedTickerCard) closeInlineCard();
  activePeriod = mode;
  updatePeriodUi();
  if (rerender) rebuildAndRender(selectedTicker, false);
}""",
    "setPeriod",
)

old_bind = "function bind(root) { for (const e of root.querySelectorAll('[data-ticker]')) e.addEventListener('click', () => selectTicker(e.dataset.ticker, false)); }"
new_bind = """function closeInlineCard() {
  const card = expandedTickerCard;
  if (!card) return;
  card.querySelector(':scope > .inlineAnalysis')?.remove();
  card.classList.remove('inlineExpanded');
  card.setAttribute('aria-expanded', 'false');
  expandedTickerCard = null;
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
  const inline = document.createElement('div');
  inline.className = 'inlineAnalysis';
  inline.innerHTML = `<div class=\"inlineAnalysisHead\"><span>${esc(t)} の銘柄分析</span><button type=\"button\" class=\"inlineClose\">閉じる</button></div>${selectedHtml(t)}`;
  inline.querySelector('#expirySelect')?.closest('.expiryPicker')?.remove();
  card.appendChild(inline);
  card.classList.add('inlineExpanded');
  card.setAttribute('aria-expanded', 'true');
  expandedTickerCard = card;
  inline.querySelector('.inlineClose')?.addEventListener('click', ev => {
    ev.preventDefault();
    ev.stopPropagation();
    closeInlineCard();
  });
  window.dispatchEvent(new CustomEvent('options:inline-selected-change'));
}
function bind(root) {
  for (const e of root.querySelectorAll('[data-ticker]')) {
    e.setAttribute('aria-expanded', 'false');
    e.addEventListener('click', ev => {
      if (ev.target.closest('.inlineAnalysis')) return;
      toggleInlineCard(e, e.dataset.ticker);
    });
  }
}"""
s = replace_once(s, old_bind, new_bind, "card bind")

s = replace_once(
    s,
    """function selectTicker(t, scroll) {
  t = String(t || '').trim().toUpperCase();
  if (!t) return;
  selectedTicker = t;""",
    """function selectTicker(t, scroll) {
  t = String(t || '').trim().toUpperCase();
  if (!t) return;
  closeInlineCard();
  selectedTicker = t;""",
    "selectTicker",
)

if "toggleInlineCard(e, e.dataset.ticker)" not in s:
    raise SystemExit("inline toggle not installed")
if "selectTicker(e.dataset.ticker, false)" in s:
    raise SystemExit("old card navigation still present")
p.write_text(s, encoding="utf-8")


# Mount the chart in an inline expanded card first, or in top search result when searching.
p = Path("options-chart-bridge.js")
s = p.read_text(encoding="utf-8")

s = replace_once(
    s,
    """async function mountCurrent() {
  scheduled = false;
  const selected = document.querySelector('#selected');
  const card = selected?.querySelector('.selectedCard');
  const ticker = card?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (!card || !ticker) return;
  const token = ++mountToken;

  if (activeChart) {""",
    """function activeSelectedCard() {
  return document.querySelector('.inlineAnalysis .selectedCard') || document.querySelector('#selected .selectedCard');
}

async function mountCurrent() {
  scheduled = false;
  const card = activeSelectedCard();
  const ticker = card?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();
  if (!card || !ticker) {
    if (activeChart) {
      try { activeChart.destroy(); } catch (_) {}
      activeChart = null;
    }
    return;
  }
  const token = ++mountToken;

  if (activeChart) {""",
    "bridge mountCurrent",
)

s = replace_once(
    s,
    """  const currentCard = document.querySelector('#selected .selectedCard');
  const currentTicker = currentCard?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();""",
    """  const currentCard = activeSelectedCard();
  const currentTicker = currentCard?.querySelector('.selectedTicker')?.textContent?.trim()?.toUpperCase();""",
    "bridge currentCard",
)

s = replace_once(
    s,
    """  new MutationObserver(() => { restoreAnchorPosition(); schedule(); }).observe(selected, { childList: true });
  schedule();""",
    """  new MutationObserver(() => { restoreAnchorPosition(); schedule(); }).observe(selected, { childList: true });
  window.addEventListener('options:inline-selected-change', schedule);
  schedule();""",
    "bridge event hook",
)

if "activeSelectedCard()" not in s or "options:inline-selected-change" not in s:
    raise SystemExit("bridge inline mount not installed")
if "const currentCard = document.querySelector('#selected .selectedCard')" in s:
    raise SystemExit("bridge still hardcodes top selected card")
p.write_text(s, encoding="utf-8")


# Expanded cards span their grid and the detail reads as part of the tapped card.
p = Path("options-intelligence.css")
s = p.read_text(encoding="utf-8")
marker = ".miniCard.leaderMuted:hover{opacity:.68;filter:saturate(.7)}"
addition = marker + ".miniCard.inlineExpanded{grid-column:1/-1;transform:none;border-color:#405774;opacity:1;filter:none}.miniCard.inlineExpanded:hover{transform:none}.allRow.inlineExpanded{grid-column:1/-1}.inlineAnalysis{grid-column:1/-1;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.10);cursor:default}.inlineAnalysisHead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;color:#cbd7e4;font-size:10px;font-weight:800}.inlineClose{border:1px solid var(--line);background:#0a111a;color:#b8c6d5;border-radius:8px;padding:6px 9px;font:inherit;font-size:9px;cursor:pointer}.inlineAnalysis .selectedCard{background:transparent;border:0;border-radius:0;padding:0;box-shadow:none}.inlineAnalysis .v38ChartPanel{margin-top:10px}"
if ".inlineAnalysis{" in s:
    raise SystemExit("inline CSS already exists unexpectedly")
s = replace_once(s, marker, addition, "CSS miniCard")
p.write_text(s, encoding="utf-8")


# Cache bust only the changed Options Intelligence assets.
p = Path("options-intelligence.html")
h = p.read_text(encoding="utf-8")
for old, new in {
    "./options-intelligence.css?v=20260906-rsperiod3": "./options-intelligence.css?v=20260906-inlinecard1",
    "./options-intelligence.js?v=20260906-cardscroll1": "./options-intelligence.js?v=20260906-inlinecard1",
    "./options-chart-bridge.js?v=20260906-anchor1": "./options-chart-bridge.js?v=20260906-inlinecard1",
}.items():
    h = replace_once(h, old, new, f"HTML cache {old}")
p.write_text(h, encoding="utf-8")

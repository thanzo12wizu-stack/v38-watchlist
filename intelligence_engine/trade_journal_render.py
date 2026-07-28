from __future__ import annotations

import base64
import re
import urllib.parse
from pathlib import Path

from .trade_journal import JournalReport
from .trade_journal_cards import render_daily_card, render_portfolio_card, write_social_copy
from .trade_journal_tabs import render_dashboard as _render_dashboard


_TAB_BUTTON_RE = re.compile(
    r'<button class="tab" data-tab="([^"]+)" role="tab" aria-selected="(true|false)">(.*?)</button>',
    re.DOTALL,
)

_TAB_FALLBACK_CSS = r'''
.tabs .tab{display:inline-flex;align-items:center;text-decoration:none}
html:not(.js) .tab-panel{display:none}
html:not(.js) .tab-panel:target{display:block}
html:not(.js):has(.tab-panel:target) .tab-panel.active:not(:target){display:none}
html:not(.js) .tabs .tab:focus,html:not(.js) .tabs .tab:hover{color:var(--text);border-color:var(--accent)}
'''

_MOBILE_CSS = r'''
@media(max-width:680px){
  html,body,.app{max-width:100%;overflow-x:hidden}
  .tabs{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;overflow:visible!important;margin:0!important;padding:6px 0!important}
  .tabs .tab{min-width:0!important;width:100%;justify-content:center;padding:8px 4px!important;font-size:10px!important;text-align:center}
  .tabs .tab em{display:none}
  .metrics,.metrics.compact{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .risk-strip{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .grid,.grid.equal,.share-grid{grid-template-columns:minmax(0,1fr)!important}
  .panel,.table-wrap,.table-wrap.tall{max-width:100%;overflow:visible!important;max-height:none!important}
  .chart,.treemap,svg{max-width:100%;height:auto}
  table.mobile-cards{display:block;width:100%;white-space:normal!important;background:transparent}
  table.mobile-cards thead{display:none}
  table.mobile-cards tbody{display:grid;gap:7px}
  table.mobile-cards tr{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 10px;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}
  table.mobile-cards td{display:grid;grid-template-columns:minmax(62px,.8fr) minmax(0,1.2fr);align-items:center;gap:7px;width:auto!important;padding:0!important;border:0!important;text-align:right!important;white-space:normal;overflow-wrap:anywhere;font-size:10px!important}
  table.mobile-cards td:before{content:attr(data-label);color:var(--muted);font-size:8px;font-weight:700;text-align:left}
  table.mobile-cards td[data-priority="primary"]{grid-column:1/-1;font-size:12px!important;font-weight:850;padding-bottom:5px!important;border-bottom:1px solid var(--line)!important}
  table.mobile-cards td[data-priority="secondary"]{grid-column:1/-1}
  table.mobile-cards tr[hidden]{display:none!important}
  .heatmap{min-width:0!important;width:100%!important;display:block!important;white-space:normal!important}
  .heatmap thead{display:none}
  .heatmap tbody{display:grid;gap:8px}
  .heatmap tr{display:grid;grid-template-columns:52px repeat(3,minmax(0,1fr));gap:4px;padding:8px;border:1px solid var(--line);border-radius:9px;background:var(--panel2)}
  .heatmap td{display:block!important;padding:7px 2px!important;border-radius:5px;text-align:center;font-size:8px!important;min-width:0}
  .heatmap td:nth-child(n+5){display:none!important}
  .journal-toolbar{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .journal-toolbar>*{min-width:0!important}
  .journal-toolbar input,.journal-toolbar select{width:100%}
  .bar-row{grid-template-columns:84px minmax(0,1fr) 44px!important}
}
'''

_TAB_CLICK_SCRIPT = r'''tabs.forEach(tab => tab.addEventListener('click', event => {
    event.preventDefault();
    const targetHash = '#' + tab.dataset.tab;
    if (location.hash === targetHash) activate(tab.dataset.tab, false);
    else location.hash = targetHash;
  }));'''

_MOBILE_JS = r'''
  const responsiveTables = [...document.querySelectorAll('.table-wrap table')].filter(table => !table.classList.contains('heatmap'));
  responsiveTables.forEach(table => {
    table.classList.add('mobile-cards');
    const labels = [...table.querySelectorAll('thead th')].map(cell => cell.textContent.trim());
    [...table.querySelectorAll('tbody tr')].forEach(row => {
      [...row.children].forEach((cell, index) => {
        cell.dataset.label = labels[index] || '';
        if (index === 0 || /Ticker|銘柄/.test(labels[index] || '')) cell.dataset.priority = 'primary';
        else if (/Setup|テーマ|Sector|内容|Exit理由/.test(labels[index] || '')) cell.dataset.priority = 'secondary';
      });
    });
  });
'''

_OLD_TAB_CLICK_SCRIPT = "tabs.forEach(tab => tab.addEventListener('click', () => activate(tab.dataset.tab)));"


def _data_uri(path: Path, mime: str) -> str | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _embed_artifacts(document: str, output_dir: Path) -> str:
    for name, mime in (("daily_card.png", "image/png"), ("portfolio_card.png", "image/png")):
        uri = _data_uri(output_dir / name, mime)
        if uri:
            document = document.replace(f'src="{name}"', f'src="{uri}"')
            document = document.replace(f'href="{name}"', f'href="{uri}" download="{name}"')
    social = output_dir / "social_post_ja.txt"
    if social.exists():
        uri = "data:text/plain;charset=utf-8," + urllib.parse.quote(social.read_text(encoding="utf-8"))
        document = document.replace('href="social_post_ja.txt"', f'href="{uri}" download="social_post_ja.txt"')
    return document


def _restore_tab_links(document: str) -> str:
    def replace_button(match: re.Match[str]) -> str:
        tab_id, selected, label = match.groups()
        return (
            f'<a class="tab" href="#{tab_id}" data-tab="{tab_id}" role="tab" '
            f'aria-controls="{tab_id}" aria-selected="{selected}">{label}</a>'
        )

    document, count = _TAB_BUTTON_RE.subn(replace_button, document)
    if count != 7:
        raise ValueError(f"expected 7 trade journal tabs, converted {count}")
    document = document.replace("<head>", "<head><script>document.documentElement.classList.add('js')</script>", 1)
    document = document.replace("</style>", _TAB_FALLBACK_CSS + _MOBILE_CSS + "</style>", 1)
    if _OLD_TAB_CLICK_SCRIPT not in document:
        raise ValueError("trade journal tab click handler was not found")
    document = document.replace(_OLD_TAB_CLICK_SCRIPT, _TAB_CLICK_SCRIPT, 1)
    document = document.replace("  filterTrades();\n", "  filterTrades();\n" + _MOBILE_JS, 1)
    document = re.sub(
        r'<noscript><div class="noscript">.*?</div></noscript>',
        '<noscript><div class="noscript">JavaScriptなしでも上のタブリンクから各画面を開けます。</div></noscript>',
        document,
        count=1,
        flags=re.DOTALL,
    )
    return document


def render_dashboard(report: JournalReport, path: Path) -> None:
    """Render one self-contained HTML with durable tabs and mobile-native content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    render_daily_card(report, path.parent / "daily_card.png")
    render_portfolio_card(report, path.parent / "portfolio_card.png")
    write_social_copy(report, path.parent / "social_post_ja.txt")
    staging = path.parent / ".trade_journal_tabs.html"
    _render_dashboard(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)
    document = _restore_tab_links(document)
    path.write_text(_embed_artifacts(document, path.parent), encoding="utf-8")


__all__ = ["render_dashboard", "render_daily_card", "render_portfolio_card", "write_social_copy"]
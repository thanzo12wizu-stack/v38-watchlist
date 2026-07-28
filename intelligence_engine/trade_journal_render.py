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


_TAB_CLICK_SCRIPT = r'''tabs.forEach(tab => tab.addEventListener('click', event => {
    event.preventDefault();
    const targetHash = '#' + tab.dataset.tab;
    if (location.hash === targetHash) activate(tab.dataset.tab, false);
    else location.hash = targetHash;
  }));'''


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
    """Convert cosmetic tab buttons into durable same-file hash links.

    JavaScript enhances the links into page-state tabs. When scripts are blocked,
    the same href targets remain usable through the CSS :target fallback.
    """

    def replace_button(match: re.Match[str]) -> str:
        tab_id, selected, label = match.groups()
        return (
            f'<a class="tab" href="#{tab_id}" data-tab="{tab_id}" role="tab" '
            f'aria-controls="{tab_id}" aria-selected="{selected}">{label}</a>'
        )

    document, count = _TAB_BUTTON_RE.subn(replace_button, document)
    if count != 7:
        raise ValueError(f"expected 7 trade journal tabs, converted {count}")

    document = document.replace(
        "<head>",
        "<head><script>document.documentElement.classList.add('js')</script>",
        1,
    )
    document = document.replace("</style>", _TAB_FALLBACK_CSS + "</style>", 1)
    if _OLD_TAB_CLICK_SCRIPT not in document:
        raise ValueError("trade journal tab click handler was not found")
    document = document.replace(_OLD_TAB_CLICK_SCRIPT, _TAB_CLICK_SCRIPT, 1)
    document = re.sub(
        r'<noscript><div class="noscript">.*?</div></noscript>',
        '<noscript><div class="noscript">JavaScriptなしでも上のタブリンクから各画面を開けます。</div></noscript>',
        document,
        count=1,
        flags=re.DOTALL,
    )
    return document


def render_dashboard(report: JournalReport, path: Path) -> None:
    """Render one self-contained HTML with linked tab page states."""
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

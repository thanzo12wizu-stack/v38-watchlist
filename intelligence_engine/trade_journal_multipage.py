from __future__ import annotations

import re
from pathlib import Path

from .trade_journal import JournalReport
from .trade_journal_tabs import render_dashboard as _render_interactive_dashboard


PAGE_FILES = {
    "today": "index.html",
    "performance": "assets.html",
    "portfolio": "portfolio.html",
    "journal": "trades.html",
    "edge": "edge.html",
    "review": "review.html",
    "share": "share.html",
}


_TAB_BUTTON_RE = re.compile(
    r'<button class="tab" data-tab="([^"]+)" role="tab" aria-selected="(?:true|false)">(.*?)</button>',
    re.DOTALL,
)
_PANEL_RE = re.compile(r'<section class="tab-panel(?: active)?" id="([^"]+)"')
_TAB_SCRIPT_RE = re.compile(
    r"\s*const tabs = \[\.\.\.document\.querySelectorAll\('\.tab'\)\];.*?activate\(location\.hash\.slice\(1\) \|\| 'today', false\);",
    re.DOTALL,
)


def _make_page(document: str, active_tab: str) -> str:
    def replace_tab(match: re.Match[str]) -> str:
        tab_id, label = match.groups()
        href = PAGE_FILES.get(tab_id, "index.html")
        selected = "true" if tab_id == active_tab else "false"
        current = ' aria-current="page"' if tab_id == active_tab else ""
        return (
            f'<a class="tab" data-tab="{tab_id}" href="{href}" role="tab" '
            f'aria-selected="{selected}"{current}>{label}</a>'
        )

    def replace_panel(match: re.Match[str]) -> str:
        panel_id = match.group(1)
        active = " active" if panel_id == active_tab else ""
        return f'<section class="tab-panel{active}" id="{panel_id}"'

    page = _TAB_BUTTON_RE.sub(replace_tab, document)
    page = _PANEL_RE.sub(replace_panel, page)
    # Navigation must remain functional in file previews that block JavaScript.
    # Keep trade filters and copy controls, but remove JS-only tab activation.
    page = _TAB_SCRIPT_RE.sub("", page)
    page = page.replace(
        "Tabs are unavailable without JavaScript.",
        "各画面は独立HTMLのためJavaScriptなしでも閲覧できます。",
    )
    return page


def render_dashboard(report: JournalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / ".trade_journal_interactive.html"
    _render_interactive_dashboard(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)

    for tab_id, filename in PAGE_FILES.items():
        (path.parent / filename).write_text(_make_page(document, tab_id), encoding="utf-8")

    # Respect callers that provide a non-standard main filename.
    canonical = path.parent / PAGE_FILES["today"]
    if path.resolve() != canonical.resolve():
        path.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")

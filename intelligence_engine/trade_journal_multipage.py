from __future__ import annotations

import base64
import re
import urllib.parse
from pathlib import Path

from .trade_journal import JournalReport
from .trade_journal_cards import render_daily_card, render_portfolio_card, write_social_copy
from .trade_journal_tabs import render_dashboard as _render_interactive_dashboard


TAB_LABELS = {
    "today": "今日",
    "performance": "資産",
    "portfolio": "ポートフォリオ",
    "journal": "取引履歴",
    "edge": "エッジ分析",
    "review": "振り返り",
    "share": "共有",
}

_TAB_BUTTON_RE = re.compile(
    r'<button class="tab" data-tab="([^"]+)" role="tab" aria-selected="(?:true|false)">(.*?)</button>',
    re.DOTALL,
)
_TAB_SCRIPT_RE = re.compile(
    r"\s*const tabs = \[\.\.\.document\.querySelectorAll\('\.tab'\)\];.*?activate\(location\.hash\.slice\(1\) \|\| 'today', false\);",
    re.DOTALL,
)


_SINGLE_FILE_CSS = """
/* Single-file, no-JS readable mode. Every section is present in index.html. */
.tab-panel{display:block!important;scroll-margin-top:82px;margin:0 0 30px;padding-top:2px}
.tab-panel:not(:first-of-type){border-top:1px solid var(--line);padding-top:24px}
.tab-panel.active{display:block!important;animation:none}
.tabs .tab{display:inline-flex;align-items:center;text-decoration:none}
.tabs .tab[aria-current="page"],.tabs .tab:hover{background:linear-gradient(135deg,#253454,#242b48);border-color:#3b4b70;color:#fff}
.single-note{margin:0 0 12px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:#101827;color:var(--muted);font-size:12px;line-height:1.55}
"""


def _data_uri(path: Path, mime: str) -> str | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _embed_local_artifacts(document: str, output_dir: Path) -> str:
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


def _make_single_file(document: str, output_dir: Path) -> str:
    def replace_tab(match: re.Match[str]) -> str:
        tab_id, label = match.groups()
        return (
            f'<a class="tab" data-tab="{tab_id}" href="#{tab_id}" role="tab" '
            f'aria-selected="false">{label}</a>'
        )

    page = _TAB_BUTTON_RE.sub(replace_tab, document)
    page = _TAB_SCRIPT_RE.sub("", page)
    page = page.replace(
        "Tabs are unavailable without JavaScript.",
        "このHTMLは1ファイル完結です。上部リンクで各セクションへ移動できます。",
    )
    page = page.replace(
        "</style>",
        _SINGLE_FILE_CSS + "\n</style>",
        1,
    )
    page = page.replace(
        "データとルールを同じ正本から集計",
        "1ファイル完結 / 今日・資産・ポートフォリオ・取引履歴・エッジ・振り返り・共有を同じHTML内に集約",
    )
    page = page.replace(
        "<nav class='tabs'",
        "<p class='single-note'>JSが無効なプレビュー環境でも全セクションを読めるよう、タブはページ内リンク化しています。各タブの内容はこの1ファイル内にすべて入っています。</p><nav class='tabs'",
        1,
    )
    page = _embed_local_artifacts(page, output_dir)
    return page


def render_dashboard(report: JournalReport, path: Path) -> None:
    """Render a single self-contained HTML dashboard.

    File previews sometimes block JavaScript, so this deliberately avoids
    JS-only tab switching. The generated ``index.html`` contains every tab as a
    visible section, with sticky anchor navigation and embedded share-card PNGs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    render_daily_card(report, path.parent / "daily_card.png")
    render_portfolio_card(report, path.parent / "portfolio_card.png")
    write_social_copy(report, path.parent / "social_post_ja.txt")
    staging = path.parent / ".trade_journal_interactive.html"
    _render_interactive_dashboard(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)
    path.write_text(_make_single_file(document, path.parent), encoding="utf-8")

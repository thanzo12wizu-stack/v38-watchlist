from __future__ import annotations

import base64
import re
import urllib.parse
from pathlib import Path

from .trade_journal import JournalReport
from .trade_journal_cards import render_daily_card, render_portfolio_card, write_social_copy
from .trade_journal_tabs import render_dashboard as _render_interactive_dashboard


_TAB_BUTTON_RE = re.compile(
    r'<button class="tab" data-tab="([^"]+)" role="tab" aria-selected="(?:true|false)">(.*?)</button>',
    re.DOTALL,
)
_TAB_SCRIPT_RE = re.compile(
    r"\s*const tabs = \[\.\.\.document\.querySelectorAll\('\.tab'\)\];.*?activate\(location\.hash\.slice\(1\) \|\| 'today', false\);",
    re.DOTALL,
)


_SINGLE_FILE_CSS = r"""
/* V38 SIGNAL LEDGER — editorial terminal, single-file and no-JS readable. */
:root{
  --bg:#eeeae0;--paper:#fffdf6;--ink:#101216;--muted:#6d706f;--line:#101216;
  --blue:#1547ff;--acid:#d7ff38;--coral:#ff5b61;--green:#009b72;--soft:#d7d2c7;
  --surface:var(--paper);--surface2:var(--paper);--surface3:#f3efe5;--text:var(--ink);
  --accent:var(--blue);--accent2:var(--acid);--pos:var(--green);--neg:var(--coral);--warn:#a56f00;--radius:0px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;background:var(--bg)!important;color:var(--ink)!important;font-family:Inter,"Helvetica Neue","Noto Sans JP",Arial,sans-serif;letter-spacing:-.01em}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.22;background-image:linear-gradient(#1012160a 1px,transparent 1px),linear-gradient(90deg,#1012160a 1px,transparent 1px);background-size:24px 24px;z-index:-1}
.app{max-width:1480px!important;margin:auto;padding:18px 24px 80px!important}
.signal-ribbon{display:flex;justify-content:space-between;gap:18px;align-items:center;background:var(--ink);color:#fff;padding:8px 12px;border-left:12px solid var(--acid);font-size:10px;font-weight:900;letter-spacing:.18em;text-transform:uppercase}
.signal-ribbon span:last-child{color:var(--acid)}
.topbar{display:grid!important;grid-template-columns:minmax(0,1fr) auto!important;gap:24px!important;align-items:stretch!important;margin:0 0 12px!important;padding:24px!important;background:var(--paper)!important;border:2px solid var(--ink)!important;border-top:0!important}
.brand small{display:inline-block!important;background:var(--blue);color:#fff!important;padding:6px 9px;font-size:10px!important;font-weight:950!important;letter-spacing:.2em!important}
.brand h1{font-size:clamp(34px,5vw,72px)!important;line-height:.92!important;max-width:860px;margin:16px 0 12px!important;letter-spacing:-.065em!important;font-weight:950!important}
.brand p{max-width:760px;color:var(--muted)!important;font-size:12px!important;line-height:1.55}
.account-head{display:grid!important;grid-template-columns:1fr!important;min-width:250px;gap:0!important;border-left:2px solid var(--ink)}
.head-card{display:flex;flex-direction:column;justify-content:center;min-width:0!important;padding:16px 20px!important;border:0!important;border-bottom:2px solid var(--ink)!important;border-radius:0!important;background:transparent!important}
.head-card:last-child{border-bottom:0!important;background:var(--acid)!important}
.head-card span{font-size:9px!important;text-transform:uppercase;letter-spacing:.16em;color:var(--muted)!important;font-weight:900}
.head-card strong{font-size:24px!important;letter-spacing:-.04em}
.head-card small{color:var(--ink)!important}
.single-note{margin:12px 0!important;padding:10px 14px!important;border:2px solid var(--ink)!important;border-radius:0!important;background:var(--acid)!important;color:var(--ink)!important;font-size:11px!important;font-weight:800;line-height:1.45}
.tabs{position:sticky!important;top:0!important;z-index:50;display:flex!important;gap:0!important;overflow-x:auto;padding:0!important;margin:0 0 28px!important;background:var(--paper)!important;border:2px solid var(--ink)!important;backdrop-filter:none!important;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs .tab{display:inline-flex!important;align-items:center;justify-content:center;flex:0 0 auto;padding:12px 18px!important;border:0!important;border-right:1px solid var(--ink)!important;border-radius:0!important;background:transparent!important;color:var(--ink)!important;text-decoration:none;font-size:11px!important;font-weight:950!important;letter-spacing:.04em}
.tabs .tab:hover,.tabs .tab:focus{background:var(--blue)!important;color:#fff!important;outline:0}
.tabs .tab em{background:var(--ink)!important;color:#fff!important;border-radius:999px!important}
.tab-panel{display:block!important;scroll-margin-top:76px;margin:0 0 56px!important;padding:0!important;border-top:4px solid var(--ink)}
.tab-panel.active{display:block!important;animation:none!important}
.section-head{position:relative!important;display:grid!important;grid-template-columns:180px minmax(0,1fr) auto!important;gap:20px!important;align-items:end!important;margin:0 0 18px!important;padding:18px 0 12px!important;border-bottom:1px solid var(--ink)}
.section-head:before{display:flex;align-items:center;height:100%;font-size:11px;font-weight:950;letter-spacing:.18em;text-transform:uppercase;color:var(--blue)}
#today .section-head:before{content:"01 / OPERATIONS"}#performance .section-head:before{content:"02 / EQUITY LEDGER"}#portfolio .section-head:before{content:"03 / POSITION BOOK"}#journal .section-head:before{content:"04 / TRADE TAPE"}#edge .section-head:before{content:"05 / EDGE LAB"}#review .section-head:before{content:"06 / CONTROL ROOM"}#share .section-head:before{content:"07 / PUBLISH"}
.section-head h2{font-size:clamp(28px,3.5vw,52px)!important;line-height:1!important;letter-spacing:-.055em!important;font-weight:950!important;margin:0!important}
.section-head p{margin:7px 0 0!important;color:var(--muted)!important;font-size:11px!important}
.section-head .context{align-self:center;padding:9px 12px;border:1px solid var(--ink);background:var(--paper);color:var(--ink)!important;font-size:10px!important;text-align:right!important;font-weight:800}
.metrics{display:grid!important;grid-template-columns:repeat(12,minmax(0,1fr))!important;gap:0!important;border:2px solid var(--ink);background:var(--ink)}
.metrics.compact{grid-template-columns:repeat(9,minmax(0,1fr))!important}
.metric{grid-column:span 2;min-width:0!important;padding:16px!important;border:0!important;border-right:1px solid var(--ink)!important;border-radius:0!important;background:var(--paper)!important;box-shadow:none!important}
.metrics.compact .metric{grid-column:span 1}
.metric:first-child{grid-column:span 3;background:var(--blue)!important;color:#fff!important}.metric:first-child span,.metric:first-child small,.metric:first-child strong{color:#fff!important}
.metric:last-child{background:var(--acid)!important}
.metric span,.metric small{display:block;color:var(--muted)!important;font-size:9px!important;letter-spacing:.13em;text-transform:uppercase;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.metric strong{display:block;font-size:clamp(23px,2.4vw,38px)!important;margin:10px 0 8px!important;letter-spacing:-.055em!important;font-weight:950!important}
.grid{display:grid!important;grid-template-columns:7fr 5fr!important;gap:18px!important;margin-top:18px!important}.grid.equal{grid-template-columns:1fr 1fr!important}
.panel,.decision-card{padding:18px!important;border:1.5px solid var(--ink)!important;border-radius:0!important;background:var(--paper)!important;box-shadow:none!important;overflow:hidden}
.panel.full{grid-column:1/-1!important}.panel h3{font-size:15px!important;margin:0 0 4px!important;letter-spacing:.02em;text-transform:uppercase;font-weight:950}.panel .sub{margin-bottom:16px!important;color:var(--muted)!important;font-size:10px!important}
.panel:nth-child(odd){background:#fffaf0!important}
.risk-strip{display:grid!important;grid-template-columns:repeat(4,1fr)!important;gap:0!important;margin-top:18px!important;border:2px solid var(--ink)!important;border-radius:0!important;background:var(--ink)!important;overflow:hidden}
.risk-strip>div{padding:16px!important;background:var(--paper)!important;border-right:1px solid var(--ink)}.risk-strip>div:last-child{border-right:0;background:var(--acid)!important}
.risk-strip span{display:block;color:var(--muted)!important;font-size:9px!important;letter-spacing:.12em;text-transform:uppercase;font-weight:900}.risk-strip strong{font-size:24px!important;letter-spacing:-.04em}
.risk-strip.warning,.risk-strip.critical{border-color:var(--ink)!important}.risk-strip.warning>div:first-child{background:#fff1bb!important}.risk-strip.critical>div:first-child{background:#ffd8d8!important}
.check-row{display:grid!important;grid-template-columns:28px 1fr!important;gap:12px!important;padding:14px 0!important;border-bottom:1px solid var(--ink)!important}.check-row .state{width:22px!important;height:22px!important;margin-top:0!important;border:1px solid var(--ink)!important;border-radius:50%!important;box-shadow:none!important}.state.good{background:var(--acid)!important}.state.warning{background:#ffd04a!important}.state.critical{background:var(--coral)!important}.check-row span,.check-row small{font-size:9px!important;color:var(--muted)!important}.check-row strong{font-size:15px!important}
.chart,.treemap{width:100%;height:auto;background:transparent}.axis,.zero{stroke:#10121644!important}.line{stroke:var(--blue)!important;stroke-width:4!important}.area{fill:#1547ff18!important}.chart-label{fill:var(--ink)!important;font-size:10px!important}
.heatmap{border-collapse:collapse!important;border-spacing:0!important}.heatmap th{padding:7px!important;border:1px solid var(--ink);background:var(--ink);color:#fff!important}.heatmap td{padding:9px 6px!important;border:1px solid var(--ink);border-radius:0!important;color:var(--ink)!important}.heatmap .positive{background:#c9f5dd!important}.heatmap .negative{background:#ffd7d8!important}.heatmap .neutral,.heatmap .na{background:#e5e0d5!important;color:var(--muted)!important}
.table-wrap{border:1px solid var(--ink);overflow:auto}.table-wrap.tall{max-height:70vh}table{border-collapse:collapse!important;background:var(--paper)}th,td{padding:11px 12px!important;border-right:1px solid #10121633!important;border-bottom:1px solid #10121666!important;font-size:10px!important}thead th{top:0!important;background:var(--ink)!important;color:#fff!important;font-size:9px!important;letter-spacing:.08em;text-transform:uppercase}.ticker{color:var(--blue)!important;font-size:12px!important}.positive{color:var(--green)!important}.negative{color:#d72d39!important}
.bar-row{grid-template-columns:125px 1fr 58px!important;font-size:10px!important}.bar-track{height:11px!important;background:#d9d4c9!important;border:1px solid var(--ink);border-radius:0!important}.bar-track i{background:var(--blue)!important;border-radius:0!important}
.tm-pos{fill:#baf0d1!important;stroke:var(--ink)!important}.tm-neg{fill:#ffc7c9!important;stroke:var(--ink)!important}.tm-flat{fill:#ddd7cc!important;stroke:var(--ink)!important}.tm-label{fill:var(--ink)!important;font-size:17px!important}.tm-sub{fill:#31343a!important}
.journal-toolbar{padding:12px!important;border:1px solid var(--ink);background:#f2ede2}.journal-toolbar label span{color:var(--ink)!important}.journal-toolbar input,.journal-toolbar select{border:1px solid var(--ink)!important;border-radius:0!important;background:var(--paper)!important;color:var(--ink)!important}.ghost,.copy-button,.share-card a{border:1px solid var(--ink)!important;border-radius:0!important;background:var(--ink)!important;color:#fff!important}.ghost:hover,.copy-button:hover,.share-card a:hover{background:var(--blue)!important}
.pill{border:1px solid var(--ink);border-radius:999px!important}.pill.ok{background:var(--acid)!important;color:var(--ink)!important}.pill.bad{background:var(--coral)!important;color:var(--ink)!important}
.review{color:var(--ink)!important}.review h3{padding-left:10px;border-left:5px solid var(--blue)}.source-list,.fineprint{color:var(--muted)!important}
.share-grid{display:grid!important;grid-template-columns:1fr 1fr!important;gap:18px!important}.share-card img{border:2px solid var(--ink)!important;border-radius:0!important;background:#fff!important}.copy-box{border:1px solid var(--ink)!important;border-radius:0!important;background:var(--ink)!important;color:#fff!important}
.empty{border:1px dashed var(--ink);color:var(--muted)!important}
@media(max-width:1000px){.metrics,.metrics.compact{grid-template-columns:repeat(6,1fr)!important}.metric,.metrics.compact .metric{grid-column:span 2}.metric:first-child{grid-column:span 4}.grid,.grid.equal{grid-template-columns:1fr!important}.panel.full{grid-column:auto!important}.share-grid{grid-template-columns:1fr!important}.section-head{grid-template-columns:140px 1fr!important}.section-head .context{grid-column:2;text-align:left!important}.risk-strip{grid-template-columns:repeat(2,1fr)!important}}
@media(max-width:680px){.app{padding:10px 10px 48px!important}.signal-ribbon{font-size:8px}.signal-ribbon span:last-child{display:none}.topbar{grid-template-columns:1fr!important;padding:16px!important}.account-head{grid-template-columns:1fr 1fr!important;border:0!important;border-top:2px solid var(--ink)}.head-card{border-right:1px solid var(--ink)!important;border-bottom:0!important}.brand h1{font-size:42px!important}.tabs{margin-bottom:20px!important}.tabs .tab{padding:11px 13px!important}.tab-panel{margin-bottom:42px!important}.section-head{grid-template-columns:1fr!important;gap:7px!important}.section-head:before{height:auto}.section-head .context{grid-column:1}.metrics,.metrics.compact{grid-template-columns:repeat(2,1fr)!important}.metric,.metrics.compact .metric,.metric:first-child{grid-column:span 1}.metric:first-child{grid-column:1/-1}.metric strong{font-size:24px!important}.risk-strip{grid-template-columns:1fr 1fr!important}.journal-toolbar{display:grid!important;grid-template-columns:1fr 1fr!important}.journal-toolbar .search{grid-column:1/-1}.heatmap{min-width:760px}.panel{padding:14px!important}}
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
        return f'<a class="tab" data-tab="{tab_id}" href="#{tab_id}" role="tab" aria-selected="false">{label}</a>'

    page = _TAB_BUTTON_RE.sub(replace_tab, document)
    page = _TAB_SCRIPT_RE.sub("", page)
    page = page.replace("</style>", _SINGLE_FILE_CSS + "\n</style>", 1)
    page = page.replace("V38 PERFORMANCE OS", "V38 / SIGNAL LEDGER")
    page = page.replace("運用実績・ポートフォリオ管理", "PERFORMANCE\nLEDGER")
    page = page.replace(
        "データとルールを同じ正本から集計",
        "Execution, capital, risk and edge — one operating record",
    )
    page = page.replace(
        "<header class=\"topbar\">",
        '<div class="signal-ribbon"><span>V38 PRIVATE OPERATING RECORD / ONE FILE</span><span>CAPITAL · EXECUTION · EDGE · CONTROL</span></div><header class="topbar">',
        1,
    )
    page = page.replace(
        "<nav class=\"tabs\"",
        '<p class="single-note">CONNECTED VIEW / 上部ナビから同じHTML内の各台帳へ移動。外部CSS・外部画像・別ページは不要です。</p><nav class="tabs"',
        1,
    )
    page = _embed_local_artifacts(page, output_dir)
    return page


def render_dashboard(report: JournalReport, path: Path) -> None:
    """Render the self-contained V38 Signal Ledger HTML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    render_daily_card(report, path.parent / "daily_card.png")
    render_portfolio_card(report, path.parent / "portfolio_card.png")
    write_social_copy(report, path.parent / "social_post_ja.txt")
    staging = path.parent / ".trade_journal_interactive.html"
    _render_interactive_dashboard(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)
    path.write_text(_make_single_file(document, path.parent), encoding="utf-8")

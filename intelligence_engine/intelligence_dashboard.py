from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    return html.escape("—" if value is None else str(value))


def _pct(value: Any, digits: int = 1, *, decimal: bool = False) -> str:
    try:
        number = float(value)
        if decimal:
            number *= 100
        return f"{number:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _unwrap(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return value
    wrappers = {
        "sector_rotation": ("sectors",),
        "theme_intelligence": ("themes",),
        "entry_candidates": ("candidates",),
        "external_data": ("records",),
    }
    for candidate in wrappers.get(key, ()):
        if candidate in value:
            return value.get(candidate) or []
    return value


def load_payload(input_path: Path) -> dict:
    """Load the combined index or assemble available sidecar JSON files safely."""
    combined = _read_json(input_path)
    if isinstance(combined, dict):
        combined.setdefault("dashboard_input_status", "INDEX")
        return combined

    root = input_path.parent
    payload: dict[str, Any] = {
        "dashboard_input_status": "BOOTSTRAP_NO_INDEX",
        "manifest": {"dashboard_input_status": "BOOTSTRAP_NO_INDEX"},
    }
    file_map = {
        "market_state": "market_state.json",
        "sector_rotation": "sector_rotation.json",
        "theme_intelligence": "theme_intelligence.json",
        "portfolio_doctor": "portfolio_doctor.json",
        "morning_brief": "morning_brief.json",
        "expectancy_rankings": "expectancy_rankings.json",
        "robust_expectancy": "robust_expectancy.json",
        "leader_transitions": "leader_transitions.json",
        "data_quality": "data_quality.json",
        "entry_candidates": "entry_candidates.json",
        "external_data": "external_data.json",
    }
    for key, filename in file_map.items():
        value = _read_json(root / filename)
        if value is not None:
            payload[key] = _unwrap(value, key)
            if isinstance(value, dict) and not payload.get("generated_at"):
                payload["generated_at"] = value.get("generated_at")

    available = [
        key
        for key in payload
        if key not in {"dashboard_input_status", "manifest", "generated_at"}
    ]
    payload["manifest"]["bootstrap_sections"] = available
    return payload


def _as_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _display_value(item: dict, key: str) -> str:
    value = item.get(key)
    if key in {
        "win_rate",
        "median_excess_return",
        "downside_tail",
        "mean_excess",
    }:
        return _pct(value, 1, decimal=True)
    if key == "weight":
        return _pct(value, 1, decimal=True)
    return _esc(value)


def _cards(
    items: Any,
    fields: list[tuple[str, str]],
    limit: int = 20,
) -> str:
    rows_in = _as_list(items)
    if not rows_in:
        return '<div class="empty">データなし</div>'
    rows = []
    for item in rows_in[:limit]:
        title = (
            item.get("ticker")
            or item.get("theme")
            or item.get("sector")
            or item.get("setup")
            or item.get("label")
            or "Item"
        )
        body = "".join(
            f'<div><span>{_esc(label)}</span><b>{_display_value(item, key)}</b></div>'
            for key, label in fields
        )
        rows.append(f'<article class="item"><h3>{_esc(title)}</h3>{body}</article>')
    return "".join(rows)


def _leader_moves(transitions: dict[str, Any]) -> list[dict]:
    direct = transitions.get("rank_changes") or transitions.get("leaders")
    if isinstance(direct, list):
        return _as_list(direct)
    output = []
    changes = transitions.get("changes") or {}
    if isinstance(changes, dict):
        for label, section in changes.items():
            if not str(label).startswith("rs") or not isinstance(section, dict):
                continue
            try:
                window = int(str(label).replace("rs", ""))
            except ValueError:
                window = label
            for row in _as_list(section.get("rank_changes")):
                record = dict(row)
                record.setdefault("window", window)
                record.setdefault("rank_change", record.get("change"))
                output.append(record)
    return sorted(
        output,
        key=lambda row: (
            -(float(row.get("rank_change") or 0)),
            str(row.get("ticker") or ""),
        ),
    )


def build_html(payload: dict) -> str:
    market = payload.get("market_state") or {}
    brief = payload.get("morning_brief") or {}
    candidates = _as_list(payload.get("entry_candidates"))
    themes = _as_list(payload.get("theme_intelligence"))
    sectors = _as_list(payload.get("sector_rotation"))
    portfolio = payload.get("portfolio_doctor") or {}
    positions = _as_list(portfolio.get("positions"))
    transitions = payload.get("leader_transitions") or {}
    quality = payload.get("data_quality") or {}
    robust = payload.get("robust_expectancy") or {}
    external = _as_list(payload.get("external_data"))
    generated = (
        payload.get("generated_at")
        or (payload.get("manifest") or {}).get("generated_at")
        or "—"
    )
    input_status = (
        payload.get("dashboard_input_status")
        or (payload.get("manifest") or {}).get("dashboard_input_status")
        or "INDEX"
    )

    actionable = [item for item in candidates if item.get("actionable")][:20]
    avoid = [item for item in candidates if not item.get("actionable")][:20]
    setup_rankings = _as_list(
        robust.get("rankings") or robust.get("setup_rankings")
    )
    leader_moves = _leader_moves(transitions)[:30]
    warnings = quality.get("warnings") or quality.get("issues") or []

    css = """
    :root{color-scheme:dark;--bg:#0a0d12;--panel:#121821;--line:#273140;--muted:#8e9aab;--text:#f3f6fa;--good:#49d17d;--warn:#f5c451;--bad:#ff6b6b;--accent:#7db4ff}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.35}.wrap{max-width:1440px;margin:auto;padding:14px}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-end}.top h1{font-size:24px;margin:0}.muted{color:var(--muted);font-size:12px}.banner{margin:10px 0;padding:10px 12px;border:1px solid var(--warn);border-radius:10px;color:var(--warn);background:rgba(245,196,81,.08)}.tabs{display:flex;gap:8px;overflow:auto;position:sticky;top:0;background:rgba(10,13,18,.96);padding:10px 0;z-index:5}.tabs button{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:999px;padding:8px 13px;white-space:nowrap}.tabs button.active{border-color:var(--accent);color:var(--accent)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:8px 0 12px}.metric,.section{background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric{padding:12px}.metric small{color:var(--muted)}.metric strong{display:block;font-size:20px;margin-top:3px}.section{padding:12px;margin-bottom:12px}.section h2{font-size:16px;margin:0 0 10px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.item{border:1px solid var(--line);border-radius:10px;padding:10px;min-width:0}.item h3{font-size:15px;margin:0 0 7px;color:var(--accent)}.item div{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-top:4px}.item span{color:var(--muted)}.item b{overflow:hidden;text-overflow:ellipsis}.empty{color:var(--muted);padding:14px}.copy{width:100%;min-height:180px;background:#090c10;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px}.copybtn{margin-top:8px;border:0;border-radius:9px;padding:9px 14px;background:var(--accent);color:#08111e;font-weight:700}.warnlist{margin:0;padding-left:20px;color:var(--warn)}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:900px){.hero{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.wrap{padding:10px}.grid{grid-template-columns:1fr}.hero{grid-template-columns:1fr 1fr}.top{align-items:flex-start;flex-direction:column}.section{padding:10px}.item{break-inside:avoid}}@media print{.tabs{display:none}.view{display:block!important}.section{break-inside:avoid}}
    """

    def section(title: str, content: str) -> str:
        return (
            f'<section class="section"><h2>{_esc(title)}</h2>'
            f'<div class="grid">{content}</div></section>'
        )

    daily = f"""
    <div class="hero">
      <div class="metric"><small>Market Regime</small><strong>{_esc(market.get('regime'))}</strong></div>
      <div class="metric"><small>Entry Gate</small><strong>{_esc(market.get('entry_gate'))}</strong></div>
      <div class="metric"><small>推奨Exposure</small><strong>{_pct(market.get('recommended_exposure_pct'))}</strong></div>
      <div class="metric"><small>Quality</small><strong>{_esc(quality.get('status'))}</strong></div>
    </div>
    {section('発注可能候補', _cards(actionable, [('setup','Setup'),('entry_score_calibrated','較正Score'),('theme','Theme'),('story_phase','Story'),('earnings_window','決算')]))}
    {section('避ける・待つ候補', _cards(avoid, [('setup','Setup'),('actionable_reason','理由'),('theme','Theme'),('story_phase','Story'),('warnings','警告')]))}
    {section('強いテーマ', _cards(themes, [('phase','Phase'),('score_theme','Score'),('breadth_positive','Breadth'),('leaders','Leaders')], 16))}
    {section('強いセクター', _cards(sectors, [('score_rotation','Rotation'),('score_strength','Strength'),('score_acceleration','Acceleration'),('breadth_positive_63d','Breadth'),('leaders','Leaders')], 12))}
    """

    expectancy = f"""
    {section('実測期待値ランキング', _cards(setup_rankings, [('horizon','期間'),('sample_count','標本'),('win_rate','勝率'),('median_excess_return','中央値超過'),('downside_tail','下方Tail')], 30))}
    <section class="section"><h2>検証ステータス</h2><pre>{_esc(json.dumps({key:value for key,value in robust.items() if key not in {'rankings','setup_rankings'}}, ensure_ascii=False, indent=2))}</pre></section>
    """

    portfolio_html = f"""
    <div class="hero">
      <div class="metric"><small>Gross Exposure</small><strong>{_pct(portfolio.get('gross_exposure'), decimal=True)}</strong></div>
      <div class="metric"><small>Exposure Cap</small><strong>{_pct(portfolio.get('market_exposure_cap'), decimal=True)}</strong></div>
      <div class="metric"><small>Portfolio ADR</small><strong>{_pct(portfolio.get('portfolio_adr_pct'))}</strong></div>
      <div class="metric"><small>Stop Risk</small><strong>{_pct(portfolio.get('portfolio_stop_risk_pct'))}</strong></div>
    </div>
    {section('保有診断', _cards(positions, [('action','Action'),('weight','Weight'),('gain_pct','損益'),('held_days','保有日数'),('stop_distance_pct','Stop距離'),('reasons','理由')], 30))}
    """

    changes = f"""
    {section('リーダー交代', _cards(leader_moves, [('window','RS窓'),('previous_rank','前回'),('current_rank','現在'),('rank_change','変化')], 30))}
    <section class="section"><h2>Leader Transition Raw</h2><pre>{_esc(json.dumps(transitions, ensure_ascii=False, indent=2))}</pre></section>
    """

    data_view = f"""
    <section class="section"><h2>データ品質</h2><ul class="warnlist">{''.join(f'<li>{_esc(item)}</li>' for item in warnings) or '<li>重大警告なし</li>'}</ul></section>
    {section('外部材料', _cards(external, [('next_earnings_date','決算'),('eps_revision_30d_pct','EPS修正'),('guidance','Guidance'),('event_type','Event'),('insider_signal','Insider')], 40))}
    """

    post = brief.get("x_post_ja") or brief.get("market_comment") or ""
    x_view = (
        '<section class="section"><h2>X投稿用</h2>'
        f'<textarea id="xpost" class="copy">{_esc(post)}</textarea>'
        '<button class="copybtn" onclick="navigator.clipboard.writeText(document.getElementById(\'xpost\').value)">コピー</button></section>'
    )
    bootstrap_banner = (
        ""
        if input_status == "INDEX"
        else '<div class="banner">Intelligence Engineの統合JSONがまだ未生成です。現在は取得済みの個別データだけを表示しています。</div>'
    )

    tabs = [
        ("daily", "日次"),
        ("expectancy", "期待値"),
        ("portfolio", "Portfolio"),
        ("changes", "交代"),
        ("data", "Data"),
        ("x", "X投稿"),
    ]
    buttons = "".join(
        f'<button data-tab="{key}" class="{"active" if index == 0 else ""}">{label}</button>'
        for index, (key, label) in enumerate(tabs)
    )
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V38 Intelligence Dashboard</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>V38 Intelligence Dashboard</h1><div class="muted">既存Command Centerとは独立 / generated {_esc(generated)}</div></div><div class="muted">{_esc(brief.get('headline'))}</div></header>{bootstrap_banner}<nav class="tabs">{buttons}</nav><main><div id="daily" class="view active">{daily}</div><div id="expectancy" class="view">{expectancy}</div><div id="portfolio" class="view">{portfolio_html}</div><div id="changes" class="view">{changes}</div><div id="data" class="view">{data_view}</div><div id="x" class="view">{x_view}</div></main></div><script>document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')}})</script></body></html>"""


def generate(input_path: Path, output_path: Path) -> None:
    payload = load_payload(input_path)
    output_path.write_text(build_html(payload), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/intelligence/index.json")
    parser.add_argument("--output", default="intelligence-dashboard.html")
    args = parser.parse_args()
    generate(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _esc(value: Any) -> str:
    return html.escape("—" if value is None else str(value))


def _pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_payload(input_path: Path) -> dict:
    """Load the combined index when available, otherwise assemble known sidecar JSON files.

    The standalone dashboard must be bootstrappable before the first successful Intelligence
    Engine build. Missing or malformed files are neutral and render as unavailable data.
    """
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
    }
    for key, filename in file_map.items():
        value = _read_json(root / filename)
        if value is not None:
            payload[key] = value

    entries = _read_json(root / "entry_candidates.json")
    if isinstance(entries, dict):
        payload["entry_candidates"] = entries.get("candidates") or []
        payload.setdefault("generated_at", entries.get("generated_at"))
    elif isinstance(entries, list):
        payload["entry_candidates"] = entries

    external = _read_json(root / "external_data.json")
    if isinstance(external, dict):
        payload["external_data"] = external.get("records") or []
    elif isinstance(external, list):
        payload["external_data"] = external

    available = [key for key in payload if key not in {"dashboard_input_status", "manifest"}]
    payload["manifest"]["bootstrap_sections"] = available
    return payload


def _cards(items: list[dict], fields: list[tuple[str, str]], limit: int = 20) -> str:
    if not items:
        return '<div class="empty">データなし</div>'
    rows = []
    for item in items[:limit]:
        title = item.get("ticker") or item.get("theme") or item.get("sector") or item.get("setup") or "Item"
        body = "".join(f'<div><span>{_esc(label)}</span><b>{_esc(item.get(key))}</b></div>' for key, label in fields)
        rows.append(f'<article class="item"><h3>{_esc(title)}</h3>{body}</article>')
    return "".join(rows)


def build_html(payload: dict) -> str:
    market = payload.get("market_state") or {}
    brief = payload.get("morning_brief") or {}
    candidates = payload.get("entry_candidates") or []
    themes = payload.get("theme_intelligence") or []
    sectors = payload.get("sector_rotation") or []
    portfolio = payload.get("portfolio_doctor") or {}
    positions = portfolio.get("positions") or []
    transitions = payload.get("leader_transitions") or {}
    quality = payload.get("data_quality") or {}
    robust = payload.get("robust_expectancy") or {}
    external = payload.get("external_data") or []
    generated = payload.get("generated_at") or (payload.get("manifest") or {}).get("generated_at") or "—"
    input_status = payload.get("dashboard_input_status") or (payload.get("manifest") or {}).get("dashboard_input_status") or "INDEX"

    actionable = [x for x in candidates if x.get("actionable")][:20]
    avoid = [x for x in candidates if not x.get("actionable")][:20]
    setup_rankings = robust.get("rankings") or robust.get("setup_rankings") or []
    leader_moves = (transitions.get("rank_changes") or transitions.get("leaders") or [])[:20]
    warnings = quality.get("warnings") or quality.get("issues") or []

    css = """
    :root{color-scheme:dark;--bg:#0a0d12;--panel:#121821;--line:#273140;--muted:#8e9aab;--text:#f3f6fa;--good:#49d17d;--warn:#f5c451;--bad:#ff6b6b;--accent:#7db4ff}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.35}.wrap{max-width:1440px;margin:auto;padding:14px}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-end}.top h1{font-size:24px;margin:0}.muted{color:var(--muted);font-size:12px}.banner{margin:10px 0;padding:10px 12px;border:1px solid var(--warn);border-radius:10px;color:var(--warn);background:rgba(245,196,81,.08)}.tabs{display:flex;gap:8px;overflow:auto;position:sticky;top:0;background:rgba(10,13,18,.96);padding:10px 0;z-index:5}.tabs button{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:999px;padding:8px 13px;white-space:nowrap}.tabs button.active{border-color:var(--accent);color:var(--accent)}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:8px 0 12px}.metric,.section{background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric{padding:12px}.metric small{color:var(--muted)}.metric strong{display:block;font-size:20px;margin-top:3px}.section{padding:12px;margin-bottom:12px}.section h2{font-size:16px;margin:0 0 10px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.item{border:1px solid var(--line);border-radius:10px;padding:10px;min-width:0}.item h3{font-size:15px;margin:0 0 7px;color:var(--accent)}.item div{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-top:4px}.item span{color:var(--muted)}.item b{overflow:hidden;text-overflow:ellipsis}.empty{color:var(--muted);padding:14px}.copy{width:100%;min-height:180px;background:#090c10;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px}.copybtn{margin-top:8px;border:0;border-radius:9px;padding:9px 14px;background:var(--accent);color:#08111e;font-weight:700}.warnlist{margin:0;padding-left:20px;color:var(--warn)}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:900px){.hero{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.wrap{padding:10px}.grid{grid-template-columns:1fr}.hero{grid-template-columns:1fr 1fr}.top{align-items:flex-start;flex-direction:column}.section{padding:10px}.item{break-inside:avoid}}@media print{.tabs{display:none}.view{display:block!important}.section{break-inside:avoid}}
    """

    def section(title: str, content: str) -> str:
        return f'<section class="section"><h2>{_esc(title)}</h2><div class="grid">{content}</div></section>'

    daily = f"""
    <div class="hero">
      <div class="metric"><small>Market Regime</small><strong>{_esc(market.get('regime'))}</strong></div>
      <div class="metric"><small>Entry Gate</small><strong>{_esc(market.get('entry_gate'))}</strong></div>
      <div class="metric"><small>推奨Exposure</small><strong>{_pct(market.get('recommended_exposure_pct'))}</strong></div>
      <div class="metric"><small>Quality</small><strong>{_esc(quality.get('status'))}</strong></div>
    </div>
    {section('発注可能候補', _cards(actionable, [('setup','Setup'),('entry_score_calibrated','較正Score'),('theme','Theme'),('story_phase','Story'),('earnings_window','決算')]))}
    {section('避ける・待つ候補', _cards(avoid, [('setup','Setup'),('actionable_reason','理由'),('theme','Theme'),('story_phase','Story')]))}
    {section('強いテーマ', _cards(themes, [('phase','Phase'),('score_theme','Score'),('breadth','Breadth'),('leaders','Leaders')], 16))}
    {section('強いセクター', _cards(sectors, [('score_rotation','Rotation'),('phase','Phase'),('leaders','Leaders')], 12))}
    """

    expectancy = f"""
    {section('実測期待値ランキング', _cards(setup_rankings, [('horizon','期間'),('sample_count','標本'),('win_rate','勝率'),('median_excess_return','中央値超過'),('downside_tail','下方Tail')], 30))}
    <section class="section"><h2>検証ステータス</h2><pre>{_esc(json.dumps({k:v for k,v in robust.items() if k not in {'rankings','setup_rankings'}}, ensure_ascii=False, indent=2))}</pre></section>
    """

    portfolio_html = f"""
    <div class="hero">
      <div class="metric"><small>Gross Exposure</small><strong>{_pct((portfolio.get('gross_exposure') or 0)*100)}</strong></div>
      <div class="metric"><small>Exposure Cap</small><strong>{_pct((portfolio.get('market_exposure_cap') or 0)*100)}</strong></div>
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
    <section class="section"><h2>データ品質</h2><ul class="warnlist">{''.join(f'<li>{_esc(x)}</li>' for x in warnings) or '<li>重大警告なし</li>'}</ul></section>
    {section('外部材料', _cards(external, [('next_earnings_date','決算'),('eps_revision_30d_pct','EPS修正'),('guidance','Guidance'),('event_type','Event'),('insider_signal','Insider')], 40))}
    """

    post = brief.get("x_post_ja") or brief.get("market_comment") or ""
    x_view = f'<section class="section"><h2>X投稿用</h2><textarea id="xpost" class="copy">{_esc(post)}</textarea><button class="copybtn" onclick="navigator.clipboard.writeText(document.getElementById(\'xpost\').value)">コピー</button></section>'
    bootstrap_banner = "" if input_status == "INDEX" else '<div class="banner">Intelligence Engineの統合JSONがまだ未生成です。現在は取得済みの個別データだけを表示しています。</div>'

    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V38 Intelligence Dashboard</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>V38 Intelligence Dashboard</h1><div class="muted">既存Command Centerとは独立 / generated {_esc(generated)}</div></div><div class="muted">{_esc(brief.get('headline'))}</div></header>{bootstrap_banner}<nav class="tabs">{''.join(f'<button data-tab="{key}" class="{"active" if i==0 else ""}">{label}</button>' for i,(key,label) in enumerate([('daily','日次'),('expectancy','期待値'),('portfolio','Portfolio'),('changes','交代'),('data','Data'),('x','X投稿')]))}</nav><main><div id="daily" class="view active">{daily}</div><div id="expectancy" class="view">{expectancy}</div><div id="portfolio" class="view">{portfolio_html}</div><div id="changes" class="view">{changes}</div><div id="data" class="view">{data_view}</div><div id="x" class="view">{x_view}</div></main></div><script>document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')}})</script></body></html>"""


def generate(input_path: Path, output_path: Path) -> None:
    payload = load_payload(input_path)
    output_path.write_text(build_html(payload), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/intelligence/index.json")
    p.add_argument("--output", default="intelligence-dashboard.html")
    a = p.parse_args()
    generate(Path(a.input), Path(a.output))


if __name__ == "__main__":
    main()

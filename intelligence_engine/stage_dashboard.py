from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from .stage_matrix import build_stage_matrix


def esc(v: Any) -> str:
    if v is None: return "—"
    if isinstance(v, (list, tuple, set)): return html.escape(" / ".join(map(str, v))) if v else "—"
    if isinstance(v, dict): return html.escape(" / ".join(f"{k}:{x}" for k, x in v.items())) if v else "—"
    return html.escape(str(v))


def num(v: Any, d: int = 1) -> str:
    try: return f"{float(v):,.{d}f}"
    except (TypeError, ValueError): return "—"


def pct(v: Any, *, decimal: bool = False, signed: bool = False) -> str:
    try:
        x = float(v) * (100 if decimal else 1)
        return f"{'+' if signed and x > 0 else ''}{x:.1f}%"
    except (TypeError, ValueError): return "—"


def money(v: Any) -> str:
    try: return f"${float(v):,.2f}"
    except (TypeError, ValueError): return "—"


def read(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return None


def load_payload(path: Path) -> dict:
    value = read(path)
    if isinstance(value, dict):
        value.setdefault("dashboard_input_status", "INDEX")
        return value
    root = path.parent; out = {"dashboard_input_status": "BOOTSTRAP_NO_INDEX", "manifest": {}}
    for key, name in {"stage_matrix":"stage_matrix.json", "market_state":"market_state.json", "portfolio_doctor":"portfolio_doctor.json",
                      "morning_brief":"morning_brief.json", "data_quality":"data_quality.json",
                      "entry_candidates":"entry_candidates.json", "external_data":"external_data.json"}.items():
        value = read(root / name)
        if isinstance(value, dict) and key == "entry_candidates": value = value.get("candidates", [])
        if isinstance(value, dict) and key == "external_data": value = value.get("records", [])
        if value is not None: out[key] = value
    return out


def items(v: Any) -> list[dict]: return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def tile(x: dict) -> str:
    action = str(x.get("action") or "NA")
    badges = "".join(f'<i>{esc(b)}</i>' for b in (x.get("badges") or [])[:5])
    return f'''<article class="stock {action.lower()}" data-action="{esc(action)}" data-stage="{esc(x.get('stage'))}" data-text="{esc(str(x.get('ticker'))+' '+str(x.get('sector'))+' '+str(x.get('industry')))}">
    <div class="stock-top"><b>{esc(x.get('ticker'))}</b><span>{esc(x.get('grade'))}</span><em>{esc(action)}</em></div>
    <div class="meta"><span>RS {num(x.get('rs'),0)}</span><span>Q {num(x.get('quality'),0)}</span><span>G {num(x.get('group_score'),0)}</span></div>
    <div class="meta"><span>ATR× {num(x.get('extension'))}</span><span>R/R {num(x.get('rr'))}</span><span>ADR {pct(x.get('adr'))}</span></div>
    <div class="badges">{badges}</div><small>{esc((x.get('reasons') or ['—'])[0])}</small></article>'''


def board(matrix: dict) -> str:
    cols = []
    for col in items(matrix.get("stages")):
        groups = []
        for n, group in enumerate(items(col.get("groups"))):
            content = "".join(tile(x) for x in items(group.get("items")))
            groups.append(f'''<details {'open' if n < 2 and col.get('stage') in {'1A','1B','2A','2B'} else ''}><summary><b>{esc(group.get('industry'))}</b><span>{len(items(group.get('items')))} · G{num(group.get('score'),0)}</span></summary><small class="sector">{esc(group.get('sector'))}</small><div class="list">{content}</div></details>''')
        cols.append(f'''<section class="stage tone-{esc(col.get('tone'))}" data-col="{esc(col.get('stage'))}"><header><b>{esc(col.get('stage'))}</b><span>{esc(col.get('label_ja'))}</span><strong>{esc(col.get('count'))}</strong></header>{''.join(groups) or '<div class="empty">該当なし</div>'}</section>''')
    return '<div id="board" class="board">'+''.join(cols)+'</div>'


def group_table(rows: list[dict], key: str, limit: int) -> str:
    return '<div class="group-table">'+''.join(f'''<div class="group-row {'top' if x.get('top_half') else ''}"><b>#{esc(x.get('rank'))} {esc(x.get(key))}</b><span>Score {num(x.get('score'),0)}</span><span>RS {num(x.get('rs'),0)}</span><span>Stage2 {pct(x.get('stage2_share'),decimal=True)}</span></div>''' for x in rows[:limit])+'</div>'


def build_html(payload: dict) -> str:
    market = payload.get("market_state") or {}; brief = payload.get("morning_brief") or {}
    candidates = payload.get("entry_candidates") or []; external = payload.get("external_data") or []
    if isinstance(candidates, dict): candidates = candidates.get("candidates", [])
    if isinstance(external, dict): external = external.get("records", [])
    matrix = payload.get("stage_matrix") or build_stage_matrix(items(payload.get("stocks")), market,
        candidates=items(candidates), external=items(external), generated_at=payload.get("generated_at"))
    summary = matrix.get("summary") or {}; portfolio = payload.get("portfolio_doctor") or {}
    quality = payload.get("data_quality") or {}; manifest = payload.get("manifest") or {}
    all_items = items(matrix.get("items")); buy = [x for x in all_items if x.get("action") == "BUYABLE"][:16]
    watch = [x for x in all_items if x.get("action") in {"WATCH","WAIT"}][:16]
    risk = [x for x in all_items if x.get("action") in {"TRIM","REDUCE","EXIT"}][:16]
    today = f'''<div class="hero"><div><small>Market Gate</small><b>{esc(summary.get('market_gate'))}</b></div><div><small>Buyable</small><b>{esc(summary.get('buyable_count'))}</b></div><div><small>Bullish</small><b>{pct(summary.get('bullish_pct'),decimal=True)}</b></div><div><small>Risk actions</small><b>{esc(summary.get('risk_action_count'))}</b></div></div>
    <section class="panel"><h2>20秒要約</h2><p>{esc(brief.get('summary_20s') or brief.get('market_comment') or 'Stage × Group × RSで候補を整理')}</p></section>
    <section class="panel"><h2>BUYABLE</h2><div class="grid">{''.join(tile(x) for x in buy) or '<div class="empty">本日の候補なし</div>'}</div></section>
    <section class="panel"><h2>WATCH / WAIT</h2><div class="grid">{''.join(tile(x) for x in watch) or '<div class="empty">候補なし</div>'}</div></section>
    <section class="panel"><h2>保有時の対応候補</h2><div class="grid">{''.join(tile(x) for x in risk) or '<div class="empty">警告なし</div>'}</div></section>'''
    matrix_view = f'''<section class="filters"><select id="af"><option>ALL</option><option>BUYABLE</option><option>WATCH</option><option>WAIT</option><option>TRIM</option><option>REDUCE</option><option>EXIT</option><option>AVOID</option></select><select id="sf"><option>ALL</option>{''.join(f'<option>{esc(s)}</option>' for s in matrix.get('stage_order') or [])}</select><input id="qf" placeholder="Ticker / Sector / Industry"><button onclick="resetF()">解除</button></section>
    <div class="counts">{''.join(f'<button onclick="jump(\'{esc(s)}\')"><b>{esc(s)}</b><span>{esc((summary.get("stage_counts") or {}).get(s,0))}</span></button>' for s in matrix.get('stage_order') or [])}</div>{board(matrix)}'''
    groups_view = f'''<div class="two"><section class="panel"><h2>Sector</h2>{group_table(items(matrix.get('sectors')),'sector',30)}</section><section class="panel"><h2>Industry</h2>{group_table(items(matrix.get('industries')),'industry',80)}</section></div>'''
    pos = portfolio.get("positions") or []
    port_cards = ''.join(f'''<article class="p-card"><b>{esc(x.get('ticker'))}</b><em>{esc(x.get('action'))}</em><div><span>損益</span><b>{pct(x.get('gain_pct'),signed=True)}</b><span>日数</span><b>{esc(x.get('held_days'))}</b><span>Stop</span><b>{money(x.get('stop'))}</b></div></article>''' for x in items(pos))
    portfolio_view = f'''<div class="hero"><div><small>Gross</small><b>{pct(portfolio.get('gross_exposure'),decimal=True)}</b></div><div><small>Cap</small><b>{pct(portfolio.get('market_exposure_cap'),decimal=True)}</b></div><div><small>ADR</small><b>{pct(portfolio.get('portfolio_adr_pct'))}</b></div><div><small>Stop risk</small><b>{pct(portfolio.get('portfolio_stop_risk_pct'))}</b></div></div><section class="panel"><h2>保有診断</h2><div class="grid">{port_cards or '<div class="empty">ポートフォリオ未設定</div>'}</div></section>'''
    research_view = '''<div class="hero"><div><small>旧候補ロジック</small><b>RETIRED</b></div><div><small>Stage score</small><b>RANK ONLY</b></div></div><section class="panel"><h2>運用方針</h2><p>旧EDGE_CONFIRMED等は不採用。Stageは現在地、Groupは資金の向き、RSはリーダー性、Actionは買える位置として分離表示します。</p></section><section class="panel"><h2>次の検証</h2><p>Industry上位50%、Stage遷移、0–4 ATR Entry帯の付加価値を同一約定条件で検証します。</p></section>'''
    data_view = f'''<div class="hero"><div><small>Quality</small><b>{esc(quality.get('status'))}</b></div><div><small>Pool</small><b>{esc(summary.get('pool_count'))}</b></div><div><small>Price as of</small><b>{esc(manifest.get('price_asof'))}</b></div><div><small>Warnings</small><b>{len(quality.get('warnings') or [])}</b></div></div><section class="panel"><p>{esc(quality.get('warnings') or ['重大警告なし'])}</p></section>'''
    tabs = (("today","TODAY"),("matrix","STAGE MATRIX"),("groups","GROUPS"),("portfolio","PORTFOLIO"),("research","RESEARCH"),("data","DATA")); views={"today":today,"matrix":matrix_view,"groups":groups_view,"portfolio":portfolio_view,"research":research_view,"data":data_view}
    buttons=''.join(f'<button class="{"active" if i==0 else ""}" data-tab="{k}">{label}</button>' for i,(k,label) in enumerate(tabs)); view_html=''.join(f'<main id="{k}" class="view {"active" if i==0 else ""}">{views[k]}</main>' for i,(k,_) in enumerate(tabs))
    css='''*{box-sizing:border-box}:root{color-scheme:dark;--bg:#080c12;--p:#111927;--p2:#0d1420;--line:#26344a;--text:#eef4fb;--muted:#8e9cb0;--good:#42d67f;--warn:#f5c34f;--bad:#ff6868}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1680px;margin:auto;padding:10px}.top{display:flex;justify-content:space-between;align-items:end}.top h1{margin:0;font-size:23px}.top small,.stock small{color:var(--muted)}a{color:#83b7ff}.tabs{display:flex;gap:6px;overflow:auto;position:sticky;top:0;z-index:9;background:#080c12f5;padding:9px 0}.tabs button,.filters>*{background:var(--p);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 11px;min-height:40px;white-space:nowrap}.tabs .active{color:#83b7ff;border-color:#83b7ff}.view{display:none}.view.active{display:block}.hero{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:9px}.hero>div,.panel{background:var(--p);border:1px solid var(--line);border-radius:12px;padding:10px}.hero small{color:var(--muted)}.hero b{display:block;font-size:20px}.panel{margin-bottom:9px}.panel h2{font-size:15px;margin:0 0 8px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.stock,.p-card{background:var(--p2);border:1px solid var(--line);border-left:3px solid var(--line);border-radius:8px;padding:7px}.stock.buyable{border-left-color:var(--good)}.stock.watch,.stock.wait{border-left-color:var(--warn)}.stock.trim,.stock.reduce{border-left-color:#6da9ff}.stock.exit,.stock.avoid{border-left-color:var(--bad)}.stock-top{display:flex;gap:6px;align-items:center}.stock-top b{font-size:14px}.stock-top em{margin-left:auto;font-size:9px}.meta{display:flex;justify-content:space-between;color:var(--muted);font-size:9px;margin-top:4px}.badges i{font-size:8px;border:1px solid #40506a;border-radius:4px;padding:1px 3px;margin-right:3px;font-style:normal}.filters{display:flex;gap:6px;overflow:auto;position:sticky;top:57px;z-index:8;background:#080c12f5;padding:7px 0}.counts{display:flex;gap:5px;overflow:auto;margin-bottom:7px}.counts button{min-width:65px;background:var(--p);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px}.counts b,.counts span{display:block}.board{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(255px,1fr);gap:7px;overflow-x:auto;align-items:start}.stage{background:#0b111b;border:1px solid var(--line);border-radius:9px;overflow:hidden}.stage>header{display:grid;grid-template-columns:auto 1fr auto;gap:6px;padding:8px}.tone-amber>header{background:#9b6018}.tone-yellow>header{background:#8d710d}.tone-mint>header{background:#3e906e}.tone-green>header{background:#08773e}.tone-purple>header{background:#7031a0}.tone-blue>header{background:#3d668f}.tone-sky>header{background:#2578ad}.tone-pink>header{background:#9c4b56}.tone-red>header{background:#a72d37}.tone-magenta>header{background:#98266e}.tone-gray>header{background:#4b5360}details{border-top:1px solid #1d2a3d}summary{display:flex;justify-content:space-between;padding:7px;cursor:pointer}.sector{display:block;padding:0 7px 5px}.list{display:grid;gap:4px;padding:0 5px 6px}.two{display:grid;grid-template-columns:1fr 1fr;gap:8px}.group-row{display:grid;grid-template-columns:1.5fr repeat(3,.7fr);gap:5px;padding:6px;background:var(--p2);margin-bottom:4px;font-size:10px}.group-row.top{border-left:3px solid var(--good)}.p-card>div{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:10px}.p-card span{color:var(--muted)}.empty{color:var(--muted);padding:14px}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}}@media(max-width:580px){.top{display:block}.hero{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.board{grid-auto-columns:86vw}.wrap{padding:8px}.tabs{margin:0 -8px;padding:8px}.filters{margin:0 -8px;padding:7px 8px}.group-row{grid-template-columns:1.5fr .7fr .7fr}.group-row span:last-child{display:none}}'''
    script='''document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});function filter(){let a=af.value,s=sf.value,q=qf.value.toUpperCase();document.querySelectorAll('#board .stock').forEach(x=>x.style.display=(a==='ALL'||x.dataset.action===a)&&(s==='ALL'||x.dataset.stage===s)&&(!q||x.dataset.text.toUpperCase().includes(q))?'':'none');document.querySelectorAll('#board .stage').forEach(x=>x.style.display=s==='ALL'||x.dataset.col===s?'':'none')}af?.addEventListener('change',filter);sf?.addEventListener('change',filter);qf?.addEventListener('input',filter);function resetF(){af.value=sf.value='ALL';qf.value='';filter()}function jump(s){document.querySelector('[data-tab="matrix"]').click();document.querySelector('[data-col="'+s+'"]').scrollIntoView({behavior:'smooth',inline:'start'})}'''
    generated=payload.get('generated_at') or matrix.get('generated_at') or '—'; banner='' if payload.get('dashboard_input_status')=='INDEX' else '<div class="empty">統合JSON未生成。取得済みデータのみ表示。</div>'
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>V38 Stage Matrix</title><style>{css}</style></head><body><div class="wrap"><header class="top"><div><h1>V38 Stage × Group × RS</h1><small>現在地・業界強度・RS・買える位置を分離 / {esc(generated)}</small></div><a href="index.html">← Command Center</a></header>{banner}<nav class="tabs">{buttons}</nav>{view_html}</div><script>{script}</script></body></html>'


def generate(input_path: Path, output_path: Path) -> None: output_path.write_text(build_html(load_payload(input_path)), encoding="utf-8")

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--input",default="data/intelligence/index.json"); p.add_argument("--output",default="intelligence-dashboard.html"); a=p.parse_args(); generate(Path(a.input),Path(a.output))

if __name__ == "__main__": main()

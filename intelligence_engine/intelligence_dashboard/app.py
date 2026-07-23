from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .assets import CSS, SCRIPT
from .components import (
    candidate_card,
    candidate_section,
    compact_table,
    meaningful_external,
    sector_rows,
    standard_cards,
    theme_rows,
)
from .formatting import as_list, esc, friendly_status, load_payload, money, num, partition, pct, present


def _market_view(market: dict, brief: dict, sectors: list[dict]) -> str:
    pillars = as_list(brief.get("pillars"))
    qqq = market.get("qqq") or {}
    breadth = market.get("breadth") or {}

    pillar_rows = []
    for item in pillars:
        value = item.get("value")
        width = 0.0
        try:
            number = float(value)
            width = max(0.0, min(100.0, number * 100 if abs(number) <= 1 else number))
        except (TypeError, ValueError):
            pass
        pillar_rows.append(
            f'<div class="signal-row"><div><b>{esc(item.get("name"))}</b><small>{esc(item.get("read"))}</small></div>'
            f'<div class="signal-value"><strong>{pct(value, decimal=True)}</strong><span><i style="width:{width:.0f}%"></i></span></div></div>'
        )

    sector_top = sectors[:8]
    sector_rest = sectors[8:]
    sector_more = ""
    if sector_rest:
        sector_more = (
            f'<details class="more"><summary>残り{len(sector_rest)}セクターを表示</summary>'
            f'{compact_table(["セクター","Phase","Rotation","加速","Breadth"], sector_rows(sector_rest))}</details>'
        )

    return f"""
      <section class="section"><div class="section-head"><h2>市場の柱</h2><span>0–100</span></div><div class="signal-list">{''.join(pillar_rows) or '<div class="empty-state"><b>市場内訳なし</b></div>'}</div></section>
      <section class="split-grid">
        <div class="section"><h2>QQQ</h2>{standard_cards([{'label':'QQQ', **qqq}], 'label', [('price','価格','money'),('return_5d','5日','pct'),('return_21d','21日','pct'),('distance_52w_high_pct','高値距離','pct_raw')],1)}</div>
        <div class="section"><h2>Breadth</h2>{standard_cards([{'label':'市場内部', **breadth}], 'label', [('above_sma10','10日線上','pct'),('above_sma50','50日線上','pct'),('above_sma200','200日線上','pct'),('positive_rs63','RS63プラス','pct'),('positive_rs126','RS126プラス','pct')],1)}</div>
      </section>
      <section class="section"><div class="section-head"><h2>Sector加速</h2><span>上位8</span></div>{compact_table(["セクター","Phase","Rotation","加速","Breadth"], sector_rows(sector_top))}{sector_more}</section>
    """


def _theme_view(themes: list[dict]) -> str:
    top = themes[:10]
    rest = themes[10:]
    more = ""
    if rest:
        more = (
            f'<details class="more"><summary>残り{len(rest)}テーマを表示</summary>'
            f'{compact_table(["テーマ","Phase","Score","Breadth"], theme_rows(rest))}</details>'
        )
    return (
        '<section class="section"><div class="section-head"><h2>Theme Taxonomy</h2><span>上位10</span></div>'
        f'{compact_table(["テーマ","Phase","Score","Breadth"], theme_rows(top))}{more}</section>'
    )


def _leader_view(boards: dict, transitions: dict) -> str:
    board_sections = []
    for key, label in (("rs63", "RS63"), ("rs126", "RS126"), ("rs189", "RS189")):
        rows = as_list(boards.get(key))
        table_rows = []
        for item in rows:
            percentile = item.get("rs_percentile")
            raw = item.get("rs_raw")
            rs_text = num(percentile, 0) if present(percentile) else num(raw, 2)
            change = item.get("rank_change")
            if not present(change):
                change_text = "—"
            else:
                try:
                    change_number = float(change)
                    change_text = f"+{change_number:g}" if change_number > 0 else f"{change_number:g}"
                except (TypeError, ValueError):
                    change_text = str(change)
            table_rows.append([f'<b>#{esc(item.get("rank"))} {esc(item.get("ticker"))}</b>', esc(change_text), rs_text])
        board_sections.append(
            f'<section class="section"><div class="section-head"><h2>{label} Top10</h2><span>RS percentile</span></div>'
            f'{compact_table(["銘柄","順位変化","RS"], table_rows)}</section>'
        )

    changes = transitions.get("changes") or {}
    change_rows = []
    for key in ("rs63", "rs126", "rs189"):
        section = changes.get(key) or {}
        change_rows.append([f'<b>{key.upper()}</b>', esc(section.get("new_top10") or "なし"), esc(section.get("dropped_top10") or "なし")])

    return (
        '<div class="leader-grid">' + "".join(board_sections) + '</div>'
        f'<section class="section"><div class="section-head"><h2>リーダー交代</h2><span>{esc(friendly_status(transitions.get("status")))}</span></div>'
        f'{compact_table(["窓","Top10新規","Top10脱落"], change_rows)}</section>'
    )


def _expectancy_view(expectancy: dict, robust: dict) -> str:
    rankings = as_list(expectancy.get("rankings") or expectancy.get("setup_stats"))
    rankings = [item for item in rankings if item.get("usable") or item.get("qualified")]
    ranking_rows = []
    for item in rankings[:15]:
        ranking_rows.append([
            f'<b>{esc(item.get("setup"))}</b><small class="subline">{esc(item.get("horizon"))}日</small>',
            num(item.get("samples"), 0),
            pct(item.get("win_rate"), decimal=True),
            pct(item.get("mean_excess_return"), decimal=True, signed=True),
            pct(item.get("downside_tail_p10"), decimal=True),
        ])

    walk_rows = []
    for item in as_list(expectancy.get("walk_forward"))[-10:]:
        walk_rows.append([
            esc(item.get("test_year")),
            f'{esc(item.get("selected_setup"))} / {esc(item.get("horizon"))}日',
            num(item.get("test_samples"), 0),
            pct(item.get("mean_excess"), decimal=True, signed=True),
            pct(item.get("win_rate"), decimal=True),
        ])

    return f"""
      <div class="hero">
        <div class="metric"><small>履歴標本</small><strong>{num(expectancy.get('sample_count'),0)}</strong></div>
        <div class="metric"><small>対象銘柄</small><strong>{num(expectancy.get('ticker_count'),0)}</strong></div>
        <div class="metric"><small>履歴期間</small><strong>{esc(expectancy.get('years'))}</strong></div>
        <div class="metric"><small>実運用</small><strong>{esc(friendly_status(robust.get('status')))}</strong></div>
      </div>
      <section class="section"><div class="section-head"><h2>実測期待値</h2><span>上位15</span></div>{compact_table(["Setup / 期間","標本","勝率","平均超過","P10"], ranking_rows, empty='有効な期待値なし')}</section>
      <section class="section"><div class="section-head"><h2>Walk-forward</h2><span>直近10検証</span></div>{compact_table(["年","選択","標本","平均超過","勝率"], walk_rows, empty='Walk-forward結果なし')}</section>
      <section class="section info-panel"><b>実運用Forward</b><span>{esc(friendly_status(robust.get('status')))}</span></section>
    """


def _portfolio_view(portfolio: dict) -> str:
    positions = as_list(portfolio.get("positions"))
    if not positions:
        return """
          <section class="section"><div class="section-head"><h2>Portfolio</h2><span>未設定</span></div><div class="empty-state"><b>Portfolio未設定</b><span>保有情報をSecret経由で登録すると、Exit・集中・Stop Riskを表示します。</span></div></section>
          <section class="section info-panel"><b>表示される内容</b><span>保有日数、損益、21EMA Low／10MA Stop、3・5・10営業日ルール、ADD／HOLD／REDUCE／EXIT、Sector・Theme・相関集中。</span></section>
        """

    rows = []
    for item in positions:
        rows.append([
            f'<b>{esc(item.get("ticker"))}</b><small class="subline">{esc(item.get("action"))}</small>',
            pct(item.get("weight"), decimal=True),
            pct(item.get("gain_pct")),
            money(item.get("stop")),
            pct(item.get("risk_contribution_pct")),
        ])

    concentration_rows = []
    for label, values in (
        ("Sector", portfolio.get("sector_weights")),
        ("Theme", portfolio.get("theme_weights")),
        ("Correlation", (portfolio.get("correlation") or {}).get("high_correlation_pairs")),
    ):
        if present(values):
            concentration_rows.append([f'<b>{label}</b>', esc(values)])

    return f"""
      <div class="hero">
        <div class="metric"><small>Gross Exposure</small><strong>{pct(portfolio.get('gross_exposure'),decimal=True)}</strong></div>
        <div class="metric"><small>Exposure Cap</small><strong>{pct(portfolio.get('market_exposure_cap'),decimal=True)}</strong></div>
        <div class="metric"><small>Portfolio ADR</small><strong>{pct(portfolio.get('portfolio_adr_pct'))}</strong></div>
        <div class="metric"><small>Stop Risk</small><strong>{pct(portfolio.get('portfolio_stop_risk_pct'))}</strong></div>
      </div>
      <section class="section"><div class="section-head"><h2>保有診断</h2><button class="smallbtn" onclick="copyText('{esc(portfolio.get('positions_copy'))}')">銘柄コピー</button></div>{compact_table(["銘柄 / Action","Weight","損益","Stop","Risk寄与"], rows)}</section>
      <section class="section"><div class="section-head"><h2>集中・警告</h2><span>{len(portfolio.get('warnings') or [])}件</span></div><p class="note">{esc(portfolio.get('warnings') or ['重大警告なし'])}</p>{compact_table(["分類","内容"], concentration_rows, empty='集中データなし')}</section>
    """


def _data_view(quality: dict, manifest: dict, external: list[dict]) -> str:
    meaningful = [record for record in external if meaningful_external(record)]
    rows = []
    for record in meaningful[:20]:
        earnings = record.get("next_earnings_date") or record.get("earnings_date")
        rows.append([
            f'<b>{esc(record.get("ticker"))}</b>',
            esc(earnings or "—"),
            pct(record.get("eps_revision_30d_pct"), signed=True),
            esc(record.get("guidance_direction") or record.get("event_type") or "—"),
            esc(record.get("warnings") or "—"),
        ])
    metrics = quality.get("metrics") or {}
    return f"""
      <div class="hero">
        <div class="metric"><small>Status</small><strong>{esc(quality.get('status'))}</strong></div>
        <div class="metric"><small>価格Coverage</small><strong>{pct(metrics.get('price_coverage_ratio'),decimal=True)}</strong></div>
        <div class="metric"><small>価格基準日</small><strong>{esc(manifest.get('price_asof') or metrics.get('qqq_last_date'))}</strong></div>
        <div class="metric"><small>外部材料</small><strong>{len(meaningful)}/{len(external)}</strong></div>
      </div>
      <section class="section"><div class="section-head"><h2>品質警告</h2><span>{len(quality.get('warnings') or [])}件</span></div><p class="note">{esc(quality.get('warnings') or ['重大警告なし'])}</p></section>
      <section class="section"><div class="section-head"><h2>取得済み外部材料</h2><span>空欄銘柄は非表示</span></div>{compact_table(["銘柄","決算","EPS修正","材料","警告"], rows, empty='取得済み外部材料なし')}</section>
      <section class="section info-panel"><b>未取得データ</b><span>確認できない項目は推定せず、候補判定では欠損を中立扱いします。</span></section>
    """


def build_html(payload: dict) -> str:
    market = payload.get("market_state") or {}
    brief = payload.get("morning_brief") or {}
    candidates = as_list(payload.get("entry_candidates"))
    partitions = partition(candidates)
    themes = as_list(payload.get("theme_intelligence"))
    sectors = as_list(payload.get("sector_rotation"))
    portfolio = payload.get("portfolio_doctor") or {}
    transitions = payload.get("leader_transitions") or {}
    boards = payload.get("leader_board") or transitions.get("leader_board") or {}
    quality = payload.get("data_quality") or {}
    expectancy = payload.get("expectancy_rankings") or {}
    robust = payload.get("robust_expectancy") or {}
    external = as_list(payload.get("external_data"))
    manifest = payload.get("manifest") or {}
    generated = payload.get("generated_at") or manifest.get("generated_at") or "—"
    input_status = payload.get("dashboard_input_status") or manifest.get("dashboard_input_status") or "INDEX"
    summary = brief.get("summary_20s") or brief.get("market_comment") or "データを確認中"
    counts = market.get("candidate_counts") or {
        "actionable": len(partitions["ACTIONABLE"]),
        "ready": len(partitions["READY"]),
        "avoid": len(partitions["AVOID"]),
    }

    decision_strip = f"""
      <section class="decision-strip">
        <button onclick="openCandidates('ACTIONABLE')"><small>発注可能</small><strong>{counts.get('actionable', 0)}</strong></button>
        <button onclick="openCandidates('READY')"><small>準備</small><strong>{counts.get('ready', 0)}</strong></button>
        <button onclick="openCandidates('AVOID')"><small>回避</small><strong>{counts.get('avoid', 0)}</strong></button>
      </section>"""

    daily = f"""
      <div class="hero">
        <div class="metric"><small>地合い</small><strong>{esc(market.get('regime'))}</strong></div>
        <div class="metric"><small>新規</small><strong>{esc(market.get('entry_gate'))}</strong></div>
        <div class="metric"><small>推奨露出</small><strong>{pct(market.get('recommended_exposure_pct'))}</strong></div>
        <div class="metric"><small>データ品質</small><strong>{esc(quality.get('status'))}</strong></div>
      </div>
      <section class="section summary"><div class="section-head"><h2>今日の結論</h2><span>20秒</span></div><pre>{esc(summary)}</pre></section>
      {decision_strip}
      {candidate_section('今すぐ確認', partitions['ACTIONABLE'], '本日の発注候補なし', 3, 'ACTIONABLE')}
      {candidate_section('次に備える', partitions['READY'], '準備候補なし', 5, 'READY')}
      {candidate_section('触らない', partitions['AVOID'], '明確な回避候補なし', 3, 'AVOID')}
    """

    setups = sorted({str(item.get("setup")) for item in candidates if present(item.get("setup"))})
    setup_options = "".join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in setups)
    filters = f"""
      <div class="filters">
        <select id="statusFilter"><option value="ALL">全状態</option><option value="ACTIONABLE">発注可能</option><option value="READY">準備</option><option value="AVOID">回避</option></select>
        <select id="setupFilter"><option value="ALL">全セットアップ</option>{setup_options}</select>
        <input id="tickerSearch" placeholder="ティッカー・テーマ検索"><button onclick="resetFilters()">解除</button>
      </div>"""
    candidate_all = "".join(candidate_card(item) for item in candidates) or '<div class="empty-state"><b>候補なし</b></div>'
    candidate_view = f'<section class="section"><div class="section-head"><h2>候補ランキング</h2><span>タップで詳細</span></div>{filters}<div id="candidateList" class="candidate-list">{candidate_all}</div></section>'

    post_ja = brief.get("x_post_ja") or brief.get("market_comment") or ""
    post_en = brief.get("x_post_en") or ""
    x_view = f"""
      <section class="section"><div class="section-head"><h2>X投稿 日本語</h2><span>{len(str(post_ja))}文字</span></div><textarea id="xpostja" class="copy">{esc(post_ja)}</textarea><button class="copybtn" onclick="copyArea('xpostja')">コピー</button></section>
      <section class="section"><div class="section-head"><h2>X post English</h2><span>{len(str(post_en))} chars</span></div><textarea id="xposten" class="copy">{esc(post_en)}</textarea><button class="copybtn" onclick="copyArea('xposten')">Copy</button></section>
    """

    tabs = [("daily", "日次"), ("market", "市場"), ("candidates", "候補"), ("themes", "テーマ"), ("leaders", "リーダー"), ("expectancy", "期待値"), ("portfolio", "Portfolio"), ("data", "Data"), ("x", "X投稿")]
    buttons = "".join(f'<button data-tab="{key}" class="{"active" if index == 0 else ""}">{label}</button>' for index, (key, label) in enumerate(tabs))
    views = {
        "daily": daily,
        "market": _market_view(market, brief, sectors),
        "candidates": candidate_view,
        "themes": _theme_view(themes),
        "leaders": _leader_view(boards, transitions),
        "expectancy": _expectancy_view(expectancy, robust),
        "portfolio": _portfolio_view(portfolio),
        "data": _data_view(quality, manifest, external),
        "x": x_view,
    }
    view_html = "".join(f'<div id="{key}" class="view {"active" if index == 0 else ""}">{views[key]}</div>' for index, (key, _) in enumerate(tabs))
    bootstrap_banner = "" if input_status == "INDEX" else '<div class="banner">統合JSON未生成。取得済みセクションのみ表示中。</div>'

    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>V38 Intelligence Dashboard</title><style>{CSS}</style></head><body><div class="wrap"><header class="top"><div><h1>V38 Intelligence Dashboard</h1><div class="muted">個人用詳細分析 / generated {esc(generated)}</div></div><div><a class="hub" href="index.html">← Command Hub</a><div class="muted">{esc(brief.get("headline"))}</div></div></header>{bootstrap_banner}<nav class="tabs">{buttons}</nav><main>{view_html}</main></div><script>{SCRIPT}</script></body></html>'


def generate(input_path: Path, output_path: Path) -> None:
    output_path.write_text(build_html(load_payload(input_path)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/intelligence/index.json")
    parser.add_argument("--output", default="intelligence-dashboard.html")
    args = parser.parse_args()
    generate(Path(args.input), Path(args.output))

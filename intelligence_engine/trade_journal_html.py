from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .trade_journal import JournalReport


MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]


def _yen(value: Any, compact: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    if compact:
        absolute = abs(number)
        sign = "-" if number < 0 else ""
        if absolute >= 100_000_000:
            return f"{sign}¥{absolute / 100_000_000:.2f}億"
        if absolute >= 10_000:
            return f"{sign}¥{absolute / 10_000:.1f}万"
    return f"¥{number:,.0f}"


def _pct(value: Any, digits: int = 1, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{number:+.{digits}%}" if signed else f"{number:.{digits}%}"


def _num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "∞" if number > 0 else "—"
    return f"{number:.{digits}f}"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _tone(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "neutral"
    return "positive" if float(value) > 0 else "negative" if float(value) < 0 else "neutral"


def _svg_polyline(values: Iterable[float], width: int, height: int, *, padding: int = 10) -> str:
    points = [float(v) for v in values if pd.notna(v) and math.isfinite(float(v))]
    if len(points) < 2:
        return ""
    low, high = min(points), max(points)
    span = high - low or 1.0
    usable_w = width - padding * 2
    usable_h = height - padding * 2
    coords = []
    for i, value in enumerate(points):
        x = padding + usable_w * i / (len(points) - 1)
        y = padding + usable_h * (1 - (value - low) / span)
        coords.append(f"{x:.1f},{y:.1f}")
    return " ".join(coords)


def _line_chart_svg(frame: pd.DataFrame, value_col: str, width: int = 980, height: int = 260, *, zero_line: bool = False) -> str:
    if frame.empty or value_col not in frame:
        return '<div class="empty">データなし</div>'
    values = pd.to_numeric(frame[value_col], errors="coerce").dropna().tolist()
    if len(values) < 2:
        return '<div class="empty">データ不足</div>'
    points = _svg_polyline(values, width, height, padding=24)
    low, high = min(values), max(values)
    zero = ""
    if zero_line and low <= 0 <= high and high != low:
        y = 24 + (height - 48) * (1 - (0 - low) / (high - low))
        zero = f'<line x1="24" y1="{y:.1f}" x2="{width-24}" y2="{y:.1f}" class="zero" />'
    fill = ""
    if not zero_line:
        fill_points = f"24,{height-24} {points} {width-24},{height-24}"
        fill = f'<polygon points="{fill_points}" class="area" />'
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">'
        f'<line x1="24" y1="24" x2="24" y2="{height-24}" class="axis" />'
        f'<line x1="24" y1="{height-24}" x2="{width-24}" y2="{height-24}" class="axis" />'
        f'{zero}{fill}<polyline points="{points}" class="line" />'
        f'<text x="26" y="20" class="chart-label">{_esc(_yen(high, compact=True) if not zero_line else _pct(high))}</text>'
        f'<text x="26" y="{height-6}" class="chart-label">{_esc(_yen(low, compact=True) if not zero_line else _pct(low))}</text>'
        '</svg>'
    )


def _monthly_heatmap(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="empty">月次データなし</div>'
    cells = ["<table class='heatmap'><thead><tr><th>年</th>"]
    cells.extend(f"<th>{m}</th>" for m in MONTHS)
    cells.append("<th>YTD</th></tr></thead><tbody>")
    for _, row in frame.iterrows():
        cells.append(f"<tr><th>{int(row['year'])}</th>")
        for month in range(1, 13):
            value = row.get(month)
            if pd.isna(value):
                cells.append("<td class='na'>—</td>")
            else:
                v = float(value)
                strength = min(5, max(1, int(abs(v) / 0.03) + 1))
                cells.append(f"<td class='{_tone(v)} s{strength}'>{v:+.1%}</td>")
        ytd = row.get("YTD")
        cells.append("<td class='na'>—</td>" if pd.isna(ytd) else f"<td class='{_tone(float(ytd))} s5'>{float(ytd):+.1%}</td>")
        cells.append("</tr>")
    cells.append("</tbody></table>")
    return "".join(cells)


def _table(frame: pd.DataFrame, columns: list[tuple[str, str, str]], limit: int = 20) -> str:
    if frame.empty:
        return '<div class="empty">データなし</div>'
    rows = ["<div class='table-wrap'><table><thead><tr>"]
    rows.extend(f"<th>{_esc(label)}</th>" for _, label, _ in columns)
    rows.append("</tr></thead><tbody>")
    for _, row in frame.head(limit).iterrows():
        rows.append("<tr>")
        for key, _, fmt in columns:
            value = row.get(key)
            if fmt == "yen":
                text = _yen(value)
            elif fmt == "pct":
                text = _pct(value)
            elif fmt == "spct":
                text = _pct(value, signed=True)
            elif fmt == "num":
                text = _num(value)
            elif fmt == "int":
                text = "—" if pd.isna(value) else f"{int(value)}"
            elif fmt == "date":
                text = "—" if pd.isna(value) else pd.Timestamp(value).date().isoformat()
            else:
                text = "—" if pd.isna(value) else str(value)
            cls = _tone(float(value)) if fmt in {"yen", "pct", "spct"} and pd.notna(value) else ""
            rows.append(f"<td class='{cls}'>{_esc(text)}</td>")
        rows.append("</tr>")
    rows.append("</tbody></table></div>")
    return "".join(rows)


def _sector_bars(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="empty">保有なし</div>'
    top = frame.head(10)
    max_value = max(float(top["allocation"].max()), 0.0001)
    parts = ["<div class='bars'>"]
    for _, row in top.iterrows():
        width = min(100, float(row["allocation"]) / max_value * 100)
        parts.append(
            f"<div class='bar-row'><span>{_esc(row.iloc[0])}</span><div class='bar-track'><i style='width:{width:.1f}%'></i></div>"
            f"<b>{_pct(row['allocation'])}</b></div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _treemap_rects(values: list[float], labels: list[str], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float, str, float]]:
    if not values or sum(values) <= 0:
        return []
    indexed = sorted(zip(values, labels), reverse=True)
    result: list[tuple[float, float, float, float, str, float]] = []

    def split(items: list[tuple[float, str]], rx: float, ry: float, rw: float, rh: float) -> None:
        if not items:
            return
        if len(items) == 1:
            value, label = items[0]
            result.append((rx, ry, rw, rh, label, value))
            return
        total = sum(v for v, _ in items)
        running = 0.0
        cut = 1
        for i, (value, _) in enumerate(items[:-1], start=1):
            running += value
            cut = i
            if running >= total / 2:
                break
        left, right = items[:cut], items[cut:]
        left_total = sum(v for v, _ in left)
        ratio = left_total / total if total else 0.5
        if rw >= rh:
            lw = rw * ratio
            split(left, rx, ry, lw, rh)
            split(right, rx + lw, ry, rw - lw, rh)
        else:
            lh = rh * ratio
            split(left, rx, ry, rw, lh)
            split(right, rx, ry + lh, rw, rh - lh)

    split(indexed, x, y, w, h)
    return result


def _treemap_svg(holdings: pd.DataFrame, width: int = 980, height: int = 360) -> str:
    if holdings.empty:
        return '<div class="empty">保有なし</div>'
    values = holdings["market_value_jpy"].astype(float).clip(lower=0).tolist()
    labels = holdings["ticker"].astype(str).tolist()
    rects = _treemap_rects(values, labels, 0, 0, width, height)
    lookup = holdings.set_index("ticker")
    parts = [f'<svg class="treemap" viewBox="0 0 {width} {height}">']
    total = sum(values) or 1
    for x, y, w, h, label, value in rects:
        pnl = float(lookup.loc[label, "unrealized_pct"]) if label in lookup.index and pd.notna(lookup.loc[label, "unrealized_pct"]) else 0.0
        cls = "tm-pos" if pnl > 0 else "tm-neg" if pnl < 0 else "tm-flat"
        parts.append(f'<g><rect x="{x+1:.1f}" y="{y+1:.1f}" width="{max(0,w-2):.1f}" height="{max(0,h-2):.1f}" class="{cls}" rx="8" />')
        if w > 85 and h > 42:
            parts.append(f'<text x="{x+10:.1f}" y="{y+23:.1f}" class="tm-label">{_esc(label)}</text>')
            parts.append(f'<text x="{x+10:.1f}" y="{y+43:.1f}" class="tm-sub">{value/total:.1%} / {pnl:+.1%}</text>')
        parts.append('</g>')
    parts.append('</svg>')
    return "".join(parts)


def _metric(label: str, value: str, tone: str = "neutral", sub: str = "") -> str:
    return f"<div class='metric'><span>{_esc(label)}</span><strong class='{tone}'>{_esc(value)}</strong><small>{_esc(sub)}</small></div>"


def render_dashboard(report: JournalReport, path: Path) -> None:
    k = report.kpis
    risk = report.portfolio_risk
    metrics = "".join([
        _metric("総資産", _yen(report.account_equity_jpy), "neutral", f"現金 {_pct(k.get('cash_fraction'))}"),
        _metric("総損益", _yen(k.get("net_pnl_jpy")), _tone(k.get("net_pnl_jpy")), f"含み {_yen(k.get('unrealized_pnl_jpy'))}"),
        _metric("勝率", _pct(k.get("win_rate")), "neutral", f"{k.get('trades', 0)} trades"),
        _metric("PF", _num(k.get("profit_factor")), "positive" if (k.get("profit_factor") or 0) > 1 else "negative", f"平均R {_num(k.get('average_r'))}"),
        _metric("最大DD", _pct(k.get("max_drawdown")), "negative", f"Sharpe {_num(k.get('sharpe'))}"),
        _metric("相関調整Heat", _pct(risk.get("correlation_adjusted_heat")), "negative" if (risk.get("correlation_adjusted_heat") or 0) > 0.024 else "neutral", f"名目 {_pct(risk.get('nominal_heat'))}"),
    ])
    holdings_table = _table(report.holdings, [
        ("ticker", "Ticker", "text"), ("market_value_jpy", "評価額", "yen"), ("allocation", "比率", "pct"),
        ("unrealized_pct", "含み", "spct"), ("heat_fraction", "Heat", "pct"), ("hold_days", "保有日数", "int"),
        ("sector", "Sector", "text"), ("setup", "Setup", "text"),
    ], 30)
    trades_table = _table(report.trades.sort_values("exit_date", ascending=False), [
        ("entry_date", "Entry", "date"), ("ticker", "Ticker", "text"), ("setup", "Setup", "text"),
        ("nq_color", "NQ", "text"), ("return_pct", "損益率", "spct"), ("r_multiple", "R", "num"),
        ("net_pnl_jpy", "損益", "yen"), ("hold_days", "日数", "int"), ("exit_reason", "Exit", "text"),
    ], 80)
    setup_table = _table(report.setup_analysis, [
        ("setup", "Setup", "text"), ("trades", "件数", "int"), ("win_rate", "勝率", "pct"),
        ("profit_factor", "PF", "num"), ("avg_r", "平均R", "num"), ("net_pnl_jpy", "損益", "yen"),
    ], 30)
    regime_table = _table(report.regime_analysis, [
        ("nq_color", "NQ色", "text"), ("trades", "件数", "int"), ("win_rate", "勝率", "pct"),
        ("profit_factor", "PF", "num"), ("avg_r", "平均R", "num"), ("net_pnl_jpy", "損益", "yen"),
    ], 10)
    missed_table = _table(report.missed_analysis, [
        ("bucket", "区分", "text"), ("candidates", "候補数", "int"), ("avg_forward_10d", "10日後", "spct"),
        ("avg_qqq_excess_10d", "QQQ超過", "spct"), ("positive_rate", "上昇率", "pct"),
    ], 10)
    violation_table = _table(report.rule_violations, [
        ("entry_date", "Entry", "date"), ("ticker", "Ticker", "text"), ("severity", "重要度", "text"),
        ("violation", "違反", "text"), ("detail", "内容", "text"),
    ], 50)
    notes = "".join(f"<li>{_esc(note)}</li>" for note in report.source_notes) or "<li>入力ソースの注記なし</li>"
    css = """
:root{--bg:#080b12;--panel:#111725;--panel2:#151d2d;--text:#f4f7fb;--muted:#8792a7;--line:#273147;--accent:#7aa2ff;--pos:#2ed49b;--neg:#ff667d;--warn:#f8c55b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#18223a 0,#080b12 36%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans JP","Hiragino Sans",sans-serif}.shell{max-width:1240px;margin:auto;padding:24px}.hero{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:8px 0 22px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em}.hero h1{font-size:34px;margin:6px 0}.hero p{color:var(--muted);margin:0}.badge{padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:#101725;font-weight:800}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.metric,.panel{background:linear-gradient(145deg,var(--panel2),var(--panel));border:1px solid var(--line);box-shadow:0 18px 50px #0005}.metric{padding:16px;border-radius:16px}.metric span,.metric small{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;font-size:24px;margin:8px 0}.grid{display:grid;grid-template-columns:1.45fr 1fr;gap:16px;margin-top:16px}.panel{padding:18px;border-radius:18px;overflow:hidden}.panel.full{grid-column:1/-1}.panel h2{font-size:18px;margin:0 0 4px}.panel .sub{color:var(--muted);font-size:12px;margin-bottom:14px}.chart{width:100%;height:auto}.axis,.zero{stroke:#34415b;stroke-width:1}.zero{stroke-dasharray:5 5}.line{fill:none;stroke:var(--accent);stroke-width:3}.area{fill:#7aa2ff22}.chart-label{fill:var(--muted);font-size:11px}.heatmap{width:100%;border-collapse:separate;border-spacing:4px}.heatmap th{font-size:11px;color:var(--muted)}.heatmap td{padding:8px 5px;border-radius:6px;text-align:center;font-size:11px;font-weight:700}.heatmap .positive{background:#20c99733;color:#78efc6}.heatmap .negative{background:#ff5c7333;color:#ff95a5}.heatmap .neutral,.heatmap .na{background:#20293a;color:#718096}.heatmap .s4,.heatmap .s5{outline:1px solid #ffffff22}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:10px 12px;border-bottom:1px solid var(--line);font-size:12px;text-align:right}th:first-child,td:first-child{text-align:left}thead th{position:sticky;top:0;background:#111725;color:var(--muted);z-index:1}.positive{color:var(--pos)}.negative{color:var(--neg)}.neutral{color:var(--text)}.bars{display:grid;gap:12px}.bar-row{display:grid;grid-template-columns:110px 1fr 54px;gap:10px;align-items:center;font-size:12px}.bar-track{height:9px;background:#222b3d;border-radius:99px;overflow:hidden}.bar-track i{display:block;height:100%;background:linear-gradient(90deg,#6d8cff,#8b5cf6);border-radius:99px}.treemap{width:100%;height:auto}.tm-pos{fill:#153f36;stroke:#2ed49b55}.tm-neg{fill:#4d1d2b;stroke:#ff667d55}.tm-flat{fill:#283249;stroke:#66708555}.tm-label{fill:white;font-size:16px;font-weight:800}.tm-sub{fill:#cbd5e1;font-size:11px}.review{line-height:1.75;color:#dbe4f3}.review h1,.review h2{font-size:18px}.empty{padding:36px;text-align:center;color:var(--muted)}ul{color:var(--muted);line-height:1.7}@media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.panel.full{grid-column:auto}.hero{display:block}.badge{display:inline-block;margin-top:12px}}@media(max-width:520px){.shell{padding:12px}.hero h1{font-size:27px}.metric strong{font-size:20px}.heatmap{min-width:760px}.panel{padding:14px}.metrics{gap:8px}}
"""
    review_html = "".join(
        f"<p>{_esc(line)}</p>" if line and not line.startswith("#") and not line[0].isdigit() else
        f"<h2>{_esc(line.lstrip('# '))}</h2>" if line.startswith("#") else
        f"<p>{_esc(line)}</p>" if line else ""
        for line in report.weekly_review.splitlines()
    )
    document = f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Trade Journal</title><style>{css}</style></head><body><main class='shell'>
<section class='hero'><div><div class='eyebrow'>V38 PERFORMANCE OS</div><h1>Trade Journal & Portfolio Analytics</h1><p>{report.as_of.date().isoformat()} / データとルールを同じ正本から集計</p></div><div class='badge'>NQ {report.nq_color}</div></section>
<section class='metrics'>{metrics}</section>
<section class='grid'>
<div class='panel'><h2>資産推移</h2><div class='sub'>入出金調整後の資産曲線</div>{_line_chart_svg(report.equity,'adjusted_equity_jpy')}</div>
<div class='panel'><h2>ドローダウン</h2><div class='sub'>ピークからの下落率</div>{_line_chart_svg(report.equity,'drawdown',zero_line=True)}</div>
<div class='panel full'><h2>月次ヒートマップ</h2><div class='sub'>月末ベースの入出金調整後リターン</div><div class='table-wrap'>{_monthly_heatmap(report.monthly_returns)}</div></div>
<div class='panel full'><h2>ポートフォリオ Treemap</h2><div class='sub'>面積＝評価額 / 色＝含み損益</div>{_treemap_svg(report.holdings)}</div>
<div class='panel'><h2>セクター配分</h2><div class='sub'>現在評価額ベース</div>{_sector_bars(report.sector_allocation)}</div>
<div class='panel'><h2>現在保有</h2><div class='sub'>比率・含み損益・Heat・保有日数</div>{holdings_table}</div>
<div class='panel full'><h2>Trade Journal</h2><div class='sub'>取引履歴・R・地合い・Exit理由</div>{trades_table}</div>
<div class='panel'><h2>セットアップ別</h2><div class='sub'>勝率ではなくPFと平均Rを重視</div>{setup_table}</div>
<div class='panel'><h2>地合い別</h2><div class='sub'>NQ色別の実績</div>{regime_table}</div>
<div class='panel'><h2>Missed Trade</h2><div class='sub'>買った候補と見送った候補</div>{missed_table}</div>
<div class='panel'><h2>ルール逸脱</h2><div class='sub'>重大な失敗を他の好条件で相殺しない</div>{violation_table}</div>
<div class='panel full review'><h2>AI週次レビュー</h2><div class='sub'>数値根拠から生成する決定論的コーチ</div>{review_html}</div>
<div class='panel full'><h2>入力ソース</h2><ul>{notes}</ul></div>
</section></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")

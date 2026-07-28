from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .trade_journal import JournalReport
from .trade_journal_html import _num, _pct, _treemap_rects, _yen

BG = "#080C12"
PANEL = "#111927"
PANEL_2 = "#0D1420"
LINE = "#26344A"
TEXT = "#EEF4FB"
MUTED = "#8E9CB0"
ACCENT = "#83B7FF"
GOOD = "#42D67F"
BAD = "#FF6868"
WARN = "#F5C34F"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: str = PANEL, outline: str = LINE, radius: int = 18) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _draw_grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], columns: int = 8, rows: int = 4) -> None:
    x0, y0, x1, y1 = box
    for i in range(columns + 1):
        x = x0 + (x1 - x0) * i / columns
        draw.line((x, y0, x, y1), fill="#1B2637", width=1)
    for i in range(rows + 1):
        y = y0 + (y1 - y0) * i / rows
        draw.line((x0, y, x1, y), fill="#1B2637", width=1)


def _draw_sparkline(draw: ImageDraw.ImageDraw, values: list[float], box: tuple[int, int, int, int]) -> None:
    if len(values) < 2:
        return
    x0, y0, x1, y1 = box
    low, high = min(values), max(values)
    span = high - low or 1.0
    points: list[tuple[float, float]] = []
    for i, value in enumerate(values):
        x = x0 + (x1 - x0) * i / (len(values) - 1)
        y = y1 - (y1 - y0) * (value - low) / span
        points.append((x, y))
    draw.polygon([(x0, y1), *points, (x1, y1)], fill="#16243B")
    draw.line(points, fill=ACCENT, width=4, joint="curve")
    px, py = points[-1]
    draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=ACCENT)


def _metric(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, value: str, sub: str, tone: str = TEXT) -> None:
    x0, y0, x1, y1 = box
    _rounded(draw, box, fill=PANEL)
    draw.text((x0 + 16, y0 + 13), label, font=_font(14, True), fill=MUTED)
    draw.text((x0 + 16, y0 + 42), value, font=_font(31, True), fill=tone)
    draw.text((x0 + 16, y1 - 27), sub, font=_font(13), fill=MUTED)


def render_daily_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 7), fill=ACCENT)

    draw.text((48, 35), "V38 TRADE JOURNAL", font=_font(21, True), fill=ACCENT)
    draw.text((48, 68), report.as_of.date().isoformat(), font=_font(15), fill=MUTED)
    draw.text((48, 104), _yen(report.account_equity_jpy), font=_font(56, True), fill=TEXT)
    draw.text((50, 170), "TOTAL EQUITY / 入出金調整後", font=_font(14, True), fill=MUTED)

    nq_fill = {"BLUE": "#285A9D", "GREEN": "#16664D", "YELLOW": "#7A5B16", "RED": "#762D3D"}.get(report.nq_color, PANEL_2)
    _rounded(draw, (956, 34, 1148, 102), fill=nq_fill, outline=nq_fill, radius=16)
    draw.text((976, 48), "MARKET GATE", font=_font(13, True), fill="#D9E3F1")
    draw.text((976, 71), f"NQ {report.nq_color}", font=_font(22, True), fill=TEXT)

    k = report.kpis
    widths = [(48, 222, 310, 340), (324, 222, 586, 340), (600, 222, 862, 340), (876, 222, 1148, 340)]
    _metric(draw, widths[0], "TODAY", _pct(k.get("daily_return"), signed=True), _yen(report.account_equity_jpy * (k.get("daily_return") or 0)), GOOD if (k.get("daily_return") or 0) >= 0 else BAD)
    _metric(draw, widths[1], "MONTH TO DATE", _pct(k.get("mtd_return"), signed=True), f"PF {_num(k.get('profit_factor'))}", GOOD if (k.get("mtd_return") or 0) >= 0 else BAD)
    _metric(draw, widths[2], "YEAR TO DATE", _pct(k.get("ytd_return"), signed=True), f"MAX DD {_pct(k.get('max_drawdown'))}", GOOD if (k.get("ytd_return") or 0) >= 0 else BAD)
    _metric(draw, widths[3], "CORRELATION HEAT", _pct(report.portfolio_risk.get("correlation_adjusted_heat")), f"CASH {_pct(k.get('cash_fraction'))}", WARN)

    _rounded(draw, (48, 360, 786, 626), fill=PANEL)
    draw.text((68, 382), "EQUITY CURVE", font=_font(16, True), fill=TEXT)
    draw.text((68, 407), "直近90営業日", font=_font(12), fill=MUTED)
    _draw_grid(draw, (68, 446, 766, 598))
    values = report.equity["adjusted_equity_jpy"].tail(90).astype(float).tolist() if not report.equity.empty else []
    _draw_sparkline(draw, values, (68, 446, 766, 598))

    _rounded(draw, (804, 360, 1148, 626), fill=PANEL)
    draw.text((826, 382), "TOP POSITIONS", font=_font(16, True), fill=TEXT)
    draw.text((826, 407), "WEIGHT / P&L", font=_font(12), fill=MUTED)
    y = 452
    for _, row in report.holdings.head(4).iterrows():
        pnl = float(row.get("unrealized_pct") or 0)
        tone = GOOD if pnl >= 0 else BAD
        draw.text((826, y), str(row["ticker"]), font=_font(22, True), fill=TEXT)
        draw.text((1010, y + 3), _pct(row.get("allocation")), font=_font(15), fill=MUTED, anchor="ra")
        draw.text((1122, y + 3), _pct(pnl, signed=True), font=_font(15, True), fill=tone, anchor="ra")
        draw.line((826, y + 31, 1122, y + 31), fill=LINE, width=1)
        y += 43

    draw.text((48, 646), "PRIVATE PERFORMANCE RECORD", font=_font(11, True), fill=MUTED)
    draw.text((1148, 646), "V38", font=_font(12, True), fill=ACCENT, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def render_portfolio_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 7), fill=ACCENT)
    draw.text((48, 34), "V38 PORTFOLIO", font=_font(22, True), fill=ACCENT)
    draw.text((48, 68), f"{report.as_of.date().isoformat()}  |  {_yen(report.account_equity_jpy)}  |  CASH {_pct(report.kpis.get('cash_fraction'))}", font=_font(15), fill=MUTED)

    _rounded(draw, (48, 112, 830, 626), fill=PANEL)
    draw.text((68, 134), "ALLOCATION MAP", font=_font(16, True), fill=TEXT)
    draw.text((68, 159), "面積＝評価額 / 色＝含み損益", font=_font(12), fill=MUTED)
    if not report.holdings.empty:
        values = report.holdings["market_value_jpy"].astype(float).clip(lower=0).tolist()
        labels = report.holdings["ticker"].astype(str).tolist()
        total = sum(values) or 1.0
        rects = _treemap_rects(values, labels, 68, 198, 742, 402)
        lookup = report.holdings.set_index("ticker")
        for x, y, w, h, label, value in rects:
            pnl = float(lookup.loc[label, "unrealized_pct"]) if pd.notna(lookup.loc[label, "unrealized_pct"]) else 0.0
            fill = "#173E31" if pnl > 0 else "#4B2029" if pnl < 0 else "#263246"
            draw.rounded_rectangle((int(x + 2), int(y + 2), int(x + w - 2), int(y + h - 2)), radius=10, fill=fill, outline=LINE, width=1)
            if w > 95 and h > 58:
                draw.text((x + 11, y + 8), label, font=_font(21, True), fill=TEXT)
                draw.text((x + 11, y + 37), f"{value / total:.1%}  {pnl:+.1%}", font=_font(14, True), fill=GOOD if pnl >= 0 else BAD)

    _rounded(draw, (848, 112, 1152, 626), fill=PANEL)
    draw.text((870, 134), "RISK SNAPSHOT", font=_font(16, True), fill=TEXT)
    items = [
        ("GROSS", _pct(report.portfolio_risk.get("gross_exposure"))),
        ("NOMINAL HEAT", _pct(report.portfolio_risk.get("nominal_heat"))),
        ("CORR. HEAT", _pct(report.portfolio_risk.get("correlation_adjusted_heat"))),
        ("UNREALIZED", _yen(report.kpis.get("unrealized_pnl_jpy"), compact=True)),
    ]
    y = 180
    for label, value in items:
        draw.text((870, y), label, font=_font(12, True), fill=MUTED)
        draw.text((870, y + 24), value, font=_font(28, True), fill=TEXT if label != "CORR. HEAT" else WARN)
        draw.line((870, y + 62, 1130, y + 62), fill=LINE, width=1)
        y += 78

    draw.text((870, 504), "TOP SECTORS", font=_font(13, True), fill=MUTED)
    y = 534
    for _, row in report.sector_allocation.head(3).iterrows():
        draw.text((870, y), str(row["sector"])[:18], font=_font(14, True), fill=TEXT)
        draw.text((1128, y), _pct(row["allocation"]), font=_font(14, True), fill=ACCENT, anchor="ra")
        y += 25

    draw.text((48, 646), "SIZE = MARKET VALUE / COLOR = UNREALIZED RETURN", font=_font(11, True), fill=MUTED)
    draw.text((1152, 646), "V38 TRADE JOURNAL", font=_font(11, True), fill=ACCENT, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def write_social_copy(report: JournalReport, path: Path) -> None:
    k = report.kpis
    risk = report.portfolio_risk
    top = ", ".join(report.holdings.head(5)["ticker"].tolist()) if not report.holdings.empty else "なし"
    text = (
        f"【運用実績｜{report.as_of.date().isoformat()}】\n"
        f"総資産 {_yen(report.account_equity_jpy)}｜本日 {_pct(k.get('daily_return'), signed=True)}｜月初来 {_pct(k.get('mtd_return'), signed=True)}｜年初来 {_pct(k.get('ytd_return'), signed=True)}\n"
        f"PF {_num(k.get('profit_factor'))}｜勝率 {_pct(k.get('win_rate'))}｜最大DD {_pct(k.get('max_drawdown'))}\n"
        f"NQ {report.nq_color}｜相関調整後Heat {_pct(risk.get('correlation_adjusted_heat'))}｜現金 {_pct(k.get('cash_fraction'))}\n"
        f"主な保有: {top}\n"
        "数字は入出金調整後。地合い・セットアップ・ルール遵守まで継続検証。\n"
    )
    path.write_text(text, encoding="utf-8")

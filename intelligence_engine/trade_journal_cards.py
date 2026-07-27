from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .trade_journal import JournalReport
from .trade_journal_html import _num, _pct, _treemap_rects, _yen


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


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, radius: int = 24, outline: str | None = None) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1 if outline else 0)


def _draw_sparkline(draw: ImageDraw.ImageDraw, values: list[float], box: tuple[int, int, int, int], line: str = "#7aa2ff") -> None:
    if len(values) < 2:
        return
    x0, y0, x1, y1 = box
    low, high = min(values), max(values)
    span = high - low or 1
    points = []
    for i, value in enumerate(values):
        x = x0 + (x1 - x0) * i / (len(values) - 1)
        y = y1 - (y1 - y0) * (value - low) / span
        points.append((x, y))
    polygon = [(x0, y1), *points, (x1, y1)]
    draw.polygon(polygon, fill="#18274a")
    draw.line(points, fill=line, width=5, joint="curve")


def _metric_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, label: str, value: str, sub: str, tone: str = "#f4f7fb") -> None:
    _rounded(draw, (x, y, x + w, y + 116), "#121a29", 20, "#273147")
    draw.text((x + 18, y + 14), label, font=_font(19), fill="#8f9bb0")
    draw.text((x + 18, y + 40), value, font=_font(34, True), fill=tone)
    draw.text((x + 18, y + 87), sub, font=_font(16), fill="#68758b")


def render_daily_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), "#080b12")
    draw = ImageDraw.Draw(image)
    draw.ellipse((-120, -180, 520, 460), fill="#111d38")
    draw.text((58, 42), "V38 DAILY PERFORMANCE", font=_font(22, True), fill="#7aa2ff")
    draw.text((58, 82), report.as_of.date().isoformat(), font=_font(19), fill="#8f9bb0")
    draw.text((58, 126), _yen(report.account_equity_jpy), font=_font(58, True), fill="#f4f7fb")
    draw.text((58, 195), "TOTAL EQUITY", font=_font(18, True), fill="#66758d")
    badge_fill = {"BLUE": "#284a83", "GREEN": "#166b57", "YELLOW": "#84661d", "RED": "#7a2639"}.get(report.nq_color, "#293246")
    _rounded(draw, (975, 48, 1140, 98), badge_fill, 25)
    draw.text((1001, 60), f"NQ {report.nq_color}", font=_font(20, True), fill="#ffffff")
    k = report.kpis
    _metric_card(draw, 58, 258, 250, "TODAY", _pct(k.get("daily_return"), signed=True), _yen(report.account_equity_jpy * (k.get("daily_return") or 0)), "#2ed49b" if (k.get("daily_return") or 0) >= 0 else "#ff667d")
    _metric_card(draw, 324, 258, 250, "MTD", _pct(k.get("mtd_return"), signed=True), f"PF {_num(k.get('profit_factor'))}", "#2ed49b" if (k.get("mtd_return") or 0) >= 0 else "#ff667d")
    _metric_card(draw, 590, 258, 250, "YTD", _pct(k.get("ytd_return"), signed=True), f"Max DD {_pct(k.get('max_drawdown'))}", "#2ed49b" if (k.get("ytd_return") or 0) >= 0 else "#ff667d")
    _metric_card(draw, 856, 258, 284, "PORTFOLIO HEAT", _pct(report.portfolio_risk.get("correlation_adjusted_heat")), f"Cash {_pct(k.get('cash_fraction'))}", "#f8c55b")
    _rounded(draw, (58, 398, 760, 620), "#101725", 24, "#273147")
    draw.text((84, 422), "EQUITY CURVE", font=_font(18, True), fill="#8f9bb0")
    values = report.equity["adjusted_equity_jpy"].tail(90).astype(float).tolist() if not report.equity.empty else []
    _draw_sparkline(draw, values, (84, 462, 733, 589))
    _rounded(draw, (780, 398, 1140, 620), "#101725", 24, "#273147")
    draw.text((806, 422), "TOP POSITIONS", font=_font(18, True), fill="#8f9bb0")
    y = 462
    for _, row in report.holdings.head(4).iterrows():
        tone = "#2ed49b" if float(row.get("unrealized_pct") or 0) >= 0 else "#ff667d"
        draw.text((806, y), str(row["ticker"]), font=_font(24, True), fill="#f4f7fb")
        draw.text((930, y + 2), _pct(row.get("allocation")), font=_font(19), fill="#8f9bb0")
        draw.text((1042, y + 2), _pct(row.get("unrealized_pct"), signed=True), font=_font(19, True), fill=tone)
        y += 38
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def render_portfolio_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), "#080b12")
    draw = ImageDraw.Draw(image)
    draw.text((50, 38), "V38 PORTFOLIO MAP", font=_font(24, True), fill="#7aa2ff")
    draw.text((50, 78), f"{report.as_of.date().isoformat()}  |  {_yen(report.account_equity_jpy)}  |  CASH {_pct(report.kpis.get('cash_fraction'))}", font=_font(18), fill="#8f9bb0")
    _rounded(draw, (50, 122, 810, 625), "#101725", 24, "#273147")
    if not report.holdings.empty:
        values = report.holdings["market_value_jpy"].astype(float).clip(lower=0).tolist()
        labels = report.holdings["ticker"].astype(str).tolist()
        rects = _treemap_rects(values, labels, 66, 138, 728, 471)
        lookup = report.holdings.set_index("ticker")
        for x, y, w, h, label, value in rects:
            pnl = float(lookup.loc[label, "unrealized_pct"]) if pd.notna(lookup.loc[label, "unrealized_pct"]) else 0.0
            fill = "#153f36" if pnl > 0 else "#4d1d2b" if pnl < 0 else "#283249"
            draw.rounded_rectangle((int(x + 2), int(y + 2), int(x + w - 2), int(y + h - 2)), radius=12, fill=fill, outline="#ffffff22")
            if w > 95 and h > 58:
                draw.text((x + 12, y + 9), label, font=_font(23, True), fill="#ffffff")
                draw.text((x + 12, y + 39), f"{value/sum(values):.1%}  {pnl:+.1%}", font=_font(16), fill="#d5deeb")
    _rounded(draw, (830, 122, 1150, 625), "#101725", 24, "#273147")
    draw.text((856, 150), "RISK SNAPSHOT", font=_font(19, True), fill="#8f9bb0")
    items = [
        ("Gross", _pct(report.portfolio_risk.get("gross_exposure"))),
        ("Nominal Heat", _pct(report.portfolio_risk.get("nominal_heat"))),
        ("Corr. Heat", _pct(report.portfolio_risk.get("correlation_adjusted_heat"))),
        ("Unrealized", _yen(report.kpis.get("unrealized_pnl_jpy"), compact=True)),
    ]
    y = 198
    for label, value in items:
        draw.text((856, y), label, font=_font(17), fill="#7f8ca2")
        draw.text((856, y + 26), value, font=_font(31, True), fill="#f4f7fb")
        y += 78
    draw.text((856, 516), "SECTOR MIX", font=_font(18, True), fill="#8f9bb0")
    y = 552
    for _, row in report.sector_allocation.head(3).iterrows():
        draw.text((856, y), str(row["sector"])[:18], font=_font(16), fill="#dbe4f3")
        draw.text((1080, y), _pct(row["allocation"]), font=_font(16, True), fill="#7aa2ff")
        y += 24
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

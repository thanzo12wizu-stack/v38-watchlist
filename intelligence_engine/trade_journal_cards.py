from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .trade_journal import JournalReport
from .trade_journal_html import _num, _pct, _treemap_rects, _yen


PAPER = "#F2EEE3"
PAPER_2 = "#FFFDF6"
INK = "#101216"
BLUE = "#1547FF"
ACID = "#D7FF38"
CORAL = "#FF5B61"
GREEN = "#009B72"
MUTED = "#737570"
GRID = "#C9C4B9"


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


def _label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, fill: str = INK, inverse: bool = False) -> None:
    x, y = xy
    font = _font(17, True)
    bbox = draw.textbbox((x, y), text, font=font)
    width = bbox[2] - bbox[0]
    background = INK if inverse else ACID
    foreground = PAPER_2 if inverse else fill
    draw.rectangle((x, y, x + width + 22, y + 30), fill=background)
    draw.text((x + 11, y + 4), text, font=font, fill=foreground)


def _draw_grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], columns: int = 8, rows: int = 4) -> None:
    x0, y0, x1, y1 = box
    for i in range(columns + 1):
        x = x0 + (x1 - x0) * i / columns
        draw.line((x, y0, x, y1), fill=GRID, width=1)
    for i in range(rows + 1):
        y = y0 + (y1 - y0) * i / rows
        draw.line((x0, y, x1, y), fill=GRID, width=1)


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
    draw.polygon([(x0, y1), *points, (x1, y1)], fill="#CCD6FF")
    draw.line(points, fill=BLUE, width=5, joint="curve")
    draw.ellipse((points[-1][0] - 7, points[-1][1] - 7, points[-1][0] + 7, points[-1][1] + 7), fill=ACID, outline=INK, width=2)


def _metric(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, value: str, sub: str, tone: str = INK, *, accent: str | None = None) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=accent or PAPER_2, outline=INK, width=2)
    draw.text((x0 + 16, y0 + 12), label, font=_font(15, True), fill=MUTED if accent is None else INK)
    draw.text((x0 + 16, y0 + 39), value, font=_font(32, True), fill=tone)
    draw.text((x0 + 16, y1 - 28), sub, font=_font(14), fill=MUTED if accent is None else INK)


def render_daily_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 18, 675), fill=BLUE)
    draw.rectangle((18, 0, 1200, 12), fill=INK)
    _label(draw, (52, 36), "V38 / DAILY LEDGER", inverse=True)
    draw.text((52, 82), report.as_of.date().isoformat(), font=_font(18), fill=MUTED)
    draw.text((52, 118), _yen(report.account_equity_jpy), font=_font(61, True), fill=INK)
    draw.text((55, 186), "TOTAL EQUITY / 入出金調整後", font=_font(16, True), fill=MUTED)

    nq_fill = {"BLUE": BLUE, "GREEN": GREEN, "YELLOW": "#E9B82C", "RED": CORAL}.get(report.nq_color, INK)
    draw.rectangle((958, 36, 1148, 104), fill=nq_fill, outline=INK, width=2)
    draw.text((978, 48), "MARKET GATE", font=_font(14, True), fill=PAPER_2)
    draw.text((978, 72), f"NQ {report.nq_color}", font=_font(23, True), fill=PAPER_2)

    k = report.kpis
    _metric(draw, (52, 238, 316, 356), "TODAY", _pct(k.get("daily_return"), signed=True), _yen(report.account_equity_jpy * (k.get("daily_return") or 0)), GREEN if (k.get("daily_return") or 0) >= 0 else CORAL, accent=ACID)
    _metric(draw, (316, 238, 580, 356), "MONTH TO DATE", _pct(k.get("mtd_return"), signed=True), f"PF {_num(k.get('profit_factor'))}", GREEN if (k.get("mtd_return") or 0) >= 0 else CORAL)
    _metric(draw, (580, 238, 844, 356), "YEAR TO DATE", _pct(k.get("ytd_return"), signed=True), f"MAX DD {_pct(k.get('max_drawdown'))}", GREEN if (k.get("ytd_return") or 0) >= 0 else CORAL)
    _metric(draw, (844, 238, 1148, 356), "CORRELATION HEAT", _pct(report.portfolio_risk.get("correlation_adjusted_heat")), f"CASH {_pct(k.get('cash_fraction'))}", INK, accent="#C8D3FF")

    draw.rectangle((52, 384, 786, 626), fill=PAPER_2, outline=INK, width=2)
    _label(draw, (72, 400), "EQUITY TAPE")
    _draw_grid(draw, (72, 448, 764, 600))
    values = report.equity["adjusted_equity_jpy"].tail(90).astype(float).tolist() if not report.equity.empty else []
    _draw_sparkline(draw, values, (72, 448, 764, 600))

    draw.rectangle((808, 384, 1148, 626), fill=INK)
    draw.text((830, 403), "POSITION BOOK", font=_font(18, True), fill=ACID)
    draw.text((830, 431), "WEIGHT / P&L", font=_font(12, True), fill="#A7AAA5")
    y = 465
    for index, (_, row) in enumerate(report.holdings.head(4).iterrows(), start=1):
        pnl = float(row.get("unrealized_pct") or 0)
        tone = ACID if pnl >= 0 else CORAL
        draw.text((830, y), f"0{index}", font=_font(14, True), fill="#70746F")
        draw.text((867, y - 4), str(row["ticker"]), font=_font(24, True), fill=PAPER_2)
        draw.text((995, y), _pct(row.get("allocation")), font=_font(16), fill="#C8CBC5")
        draw.text((1080, y), _pct(pnl, signed=True), font=_font(16, True), fill=tone, anchor="ra")
        draw.line((830, y + 31, 1124, y + 31), fill="#404349", width=1)
        y += 42

    draw.text((52, 646), "PRIVATE OPERATING RECORD", font=_font(12, True), fill=MUTED)
    draw.text((1148, 646), "V38", font=_font(14, True), fill=BLUE, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def render_portfolio_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 14), fill=BLUE)
    draw.rectangle((40, 38, 1160, 106), fill=INK)
    draw.text((62, 52), "V38 / POSITION BOOK", font=_font(25, True), fill=ACID)
    draw.text((62, 82), f"{report.as_of.date().isoformat()}  /  {_yen(report.account_equity_jpy)}  /  CASH {_pct(report.kpis.get('cash_fraction'))}", font=_font(16), fill=PAPER_2)

    draw.rectangle((40, 128, 832, 628), fill=PAPER_2, outline=INK, width=2)
    _label(draw, (60, 146), "ALLOCATION MAP")
    if not report.holdings.empty:
        values = report.holdings["market_value_jpy"].astype(float).clip(lower=0).tolist()
        labels = report.holdings["ticker"].astype(str).tolist()
        total = sum(values) or 1.0
        rects = _treemap_rects(values, labels, 60, 192, 752, 414)
        lookup = report.holdings.set_index("ticker")
        for x, y, w, h, label, value in rects:
            pnl = float(lookup.loc[label, "unrealized_pct"]) if pd.notna(lookup.loc[label, "unrealized_pct"]) else 0.0
            fill = "#BCEED2" if pnl > 0 else "#FFC9CB" if pnl < 0 else "#DDD8CE"
            draw.rectangle((int(x + 2), int(y + 2), int(x + w - 2), int(y + h - 2)), fill=fill, outline=INK, width=2)
            if w > 92 and h > 56:
                draw.text((x + 11, y + 8), label, font=_font(23, True), fill=INK)
                draw.text((x + 11, y + 38), f"{value / total:.1%}  {pnl:+.1%}", font=_font(15, True), fill=GREEN if pnl >= 0 else "#D72D39")

    draw.rectangle((854, 128, 1160, 628), fill=INK)
    draw.text((878, 150), "RISK / CONTROL", font=_font(18, True), fill=ACID)
    items = [
        ("GROSS", _pct(report.portfolio_risk.get("gross_exposure"))),
        ("NOMINAL HEAT", _pct(report.portfolio_risk.get("nominal_heat"))),
        ("CORR. HEAT", _pct(report.portfolio_risk.get("correlation_adjusted_heat"))),
        ("UNREALIZED", _yen(report.kpis.get("unrealized_pnl_jpy"), compact=True)),
    ]
    y = 198
    for number, (label, value) in enumerate(items, start=1):
        draw.text((878, y), f"0{number}  {label}", font=_font(13, True), fill="#969A95")
        draw.text((878, y + 25), value, font=_font(31, True), fill=PAPER_2 if number != 3 else ACID)
        draw.line((878, y + 64, 1135, y + 64), fill="#46494F", width=1)
        y += 82

    draw.text((878, 530), "TOP SECTORS", font=_font(14, True), fill="#969A95")
    y = 556
    for index, (_, row) in enumerate(report.sector_allocation.head(3).iterrows(), start=1):
        draw.text((878, y), f"{index:02d}", font=_font(13, True), fill=ACID)
        draw.text((912, y), str(row["sector"])[:18], font=_font(14, True), fill=PAPER_2)
        draw.text((1132, y), _pct(row["allocation"]), font=_font(14, True), fill=PAPER_2, anchor="ra")
        y += 23

    draw.text((40, 650), "SIZE = MARKET VALUE / COLOR = UNREALIZED RETURN", font=_font(12, True), fill=MUTED)
    draw.text((1160, 650), "V38 SIGNAL LEDGER", font=_font(12, True), fill=BLUE, anchor="ra")
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

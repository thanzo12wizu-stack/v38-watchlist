from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .journal import JournalReport


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

BG = "#F5F2EA"
PANEL = "#FFFDF8"
PANEL_2 = "#FAF6EC"
LINE = "#DFD6BF"
LINE_STRONG = "#C9BC9C"
TEXT = "#211D14"
MUTED = "#726A58"
ACCENT = "#1F4FA8"
ACCENT_SOFT = "#E6ECF9"
GOOD = "#0F6B3F"
GOOD_SOFT = "#E4F2E8"
BAD = "#A3311A"
BAD_SOFT = "#F7E6E1"
WARN = "#8A5A06"
WARN_SOFT = "#F6ECD9"


def _font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if serif:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Bold.otf" if bold else "/usr/share/fonts/opentype/noto/NotoSerifCJKjp-Regular.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                pass
    return ImageFont.load_default()


def _rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: str = PANEL,
    outline: str = LINE,
    radius: int = 18,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _tone(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return GOOD if number >= 0 else BAD


def _draw_header(draw: ImageDraw.ImageDraw, title: str, as_of: str) -> None:
    draw.text((48, 28), "V38 COMMAND CENTER", font=_font(16, True), fill=ACCENT)
    draw.text((48, 53), title, font=_font(37, True, serif=True), fill=TEXT)
    draw.text((1152, 33), as_of, font=_font(15), fill=MUTED, anchor="ra")
    draw.text((1152, 58), "TRADE JOURNAL ALMANAC", font=_font(12, True), fill=MUTED, anchor="ra")
    draw.line((48, 104, 1152, 104), fill=LINE_STRONG, width=1)


def _metric(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    sub: str = "",
    tone: str = TEXT,
) -> None:
    x0, y0, _, y1 = box
    _rounded(draw, box, fill=PANEL, radius=15)
    draw.text((x0 + 15, y0 + 12), label, font=_font(12, True), fill=MUTED)
    draw.text((x0 + 15, y0 + 38), value, font=_font(29, True), fill=tone)
    if sub:
        draw.text((x0 + 15, y1 - 24), sub, font=_font(11), fill=MUTED)


def _draw_sparkline(draw: ImageDraw.ImageDraw, values: list[float], box: tuple[int, int, int, int]) -> None:
    if len(values) < 2:
        return
    x0, y0, x1, y1 = box
    low, high = min(values), max(values)
    span = high - low or 1.0
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = x0 + (x1 - x0) * index / (len(values) - 1)
        y = y1 - (y1 - y0) * (value - low) / span
        points.append((x, y))
    for step in range(1, 5):
        y = y0 + (y1 - y0) * step / 5
        draw.line((x0, y, x1, y), fill=LINE, width=1)
    draw.polygon([(x0, y1), *points, (x1, y1)], fill=ACCENT_SOFT)
    draw.line(points, fill=ACCENT, width=4, joint="curve")
    px, py = points[-1]
    draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=ACCENT)


def _allocation_bars(
    draw: ImageDraw.ImageDraw,
    rows: list[tuple[str, float]],
    box: tuple[int, int, int, int],
    *,
    limit: int = 6,
) -> None:
    x0, y0, x1, _ = box
    selected = rows[:limit]
    maximum = max((value for _, value in selected), default=1.0) or 1.0
    y = y0
    for name, value in selected:
        draw.text((x0, y), name[:22], font=_font(13, True), fill=TEXT)
        draw.text((x1, y), f"{value:.1%}", font=_font(13, True), fill=TEXT, anchor="ra")
        track_y = y + 24
        draw.rounded_rectangle((x0, track_y, x1, track_y + 8), radius=4, fill="#EEE8DA")
        width = max(2, int((x1 - x0) * value / maximum))
        draw.rounded_rectangle((x0, track_y, x0 + width, track_y + 8), radius=4, fill=ACCENT)
        y += 51


def render_daily_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Trade Journal Almanac", report.as_of.date().isoformat())

    draw.text((48, 126), "TOTAL EQUITY", font=_font(12, True), fill=MUTED)
    draw.text((48, 145), _yen(report.account_equity_jpy), font=_font(45, True, serif=True), fill=TEXT)
    draw.text((48, 211), "入出金調整後の日次口座評価額", font=_font(10), fill=MUTED)

    gate_fill = {"BLUE": ACCENT_SOFT, "GREEN": GOOD_SOFT, "YELLOW": WARN_SOFT, "RED": BAD_SOFT}.get(report.nq_color, PANEL_2)
    gate_tone = {"BLUE": ACCENT, "GREEN": GOOD, "YELLOW": WARN, "RED": BAD}.get(report.nq_color, MUTED)
    _rounded(draw, (912, 126, 1152, 210), fill=gate_fill, outline=LINE, radius=16)
    draw.text((934, 142), "MARKET GATE", font=_font(11, True), fill=MUTED)
    draw.text((934, 169), f"NQ {report.nq_color}", font=_font(24, True), fill=gate_tone)

    k = report.kpis
    risk = report.portfolio_risk
    boxes = [(48, 244, 310, 352), (324, 244, 586, 352), (600, 244, 862, 352), (876, 244, 1152, 352)]
    _metric(draw, boxes[0], "TODAY", _pct(k.get("daily_return"), signed=True), "資産ベース", _tone(k.get("daily_return")))
    _metric(draw, boxes[1], "MONTH TO DATE", _pct(k.get("mtd_return"), signed=True), f"PF {_num(k.get('profit_factor'))}", _tone(k.get("mtd_return")))
    _metric(draw, boxes[2], "YEAR TO DATE", _pct(k.get("ytd_return"), signed=True), f"MAX DD {_pct(k.get('max_drawdown'))}", _tone(k.get("ytd_return")))
    _metric(draw, boxes[3], "CORRELATION HEAT", _pct(risk.get("correlation_adjusted_heat")), f"NOMINAL {_pct(risk.get('nominal_heat'))}", WARN)

    _rounded(draw, (48, 374, 792, 624), fill=PANEL, radius=17)
    draw.text((68, 395), "EQUITY CURVE", font=_font(14, True), fill=TEXT)
    draw.text((68, 420), "直近90営業日", font=_font(11), fill=MUTED)
    values = report.equity["adjusted_equity_jpy"].tail(90).astype(float).tolist() if not report.equity.empty else []
    _draw_sparkline(draw, values, (68, 456, 772, 594))

    _rounded(draw, (812, 374, 1152, 624), fill=PANEL, radius=17)
    draw.text((834, 395), "RISK SNAPSHOT", font=_font(14, True), fill=TEXT)
    snapshots = [
        ("GROSS EXPOSURE", _pct(risk.get("gross_exposure"))),
        ("CASH", _pct(k.get("cash_fraction"))),
        ("POSITIONS", f"{len(report.holdings)}"),
        ("RULE ADHERENCE", _pct(k.get("rule_adherence"))),
    ]
    y = 435
    for label, value in snapshots:
        draw.text((834, y), label, font=_font(10, True), fill=MUTED)
        draw.text((1128, y - 3), value, font=_font(19, True), fill=TEXT, anchor="ra")
        draw.line((834, y + 31, 1128, y + 31), fill=LINE, width=1)
        y += 47

    draw.text((48, 648), "PRIVATE PERFORMANCE RECORD", font=_font(10, True), fill=MUTED)
    draw.text((1152, 648), "V38", font=_font(11, True), fill=ACCENT, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def render_portfolio_card(report: JournalReport, path: Path) -> None:
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, "Portfolio Almanac", report.as_of.date().isoformat())

    risk = report.portfolio_risk
    k = report.kpis
    boxes = [(48, 126, 310, 230), (324, 126, 586, 230), (600, 126, 862, 230), (876, 126, 1152, 230)]
    _metric(draw, boxes[0], "GROSS", _pct(risk.get("gross_exposure")), "総エクスポージャー")
    _metric(draw, boxes[1], "NOMINAL HEAT", _pct(risk.get("nominal_heat")), "Stop基準", WARN)
    _metric(draw, boxes[2], "CORRELATION HEAT", _pct(risk.get("correlation_adjusted_heat")), "相関調整後", WARN)
    _metric(draw, boxes[3], "UNREALIZED", _yen(k.get("unrealized_pnl_jpy"), compact=True), f"CASH {_pct(k.get('cash_fraction'))}", _tone(k.get("unrealized_pnl_jpy")))

    _rounded(draw, (48, 252, 586, 624), fill=PANEL, radius=17)
    draw.text((70, 275), "SECTOR ALLOCATION", font=_font(14, True), fill=TEXT)
    draw.text((70, 299), "個別銘柄名を出さない公開用集計", font=_font(10), fill=MUTED)
    sectors = [
        (str(row.get("sector") or "UNKNOWN"), float(row.get("allocation") or 0))
        for _, row in report.sector_allocation.iterrows()
    ]
    _allocation_bars(draw, sectors, (70, 337, 558, 602), limit=5)

    _rounded(draw, (606, 252, 1152, 624), fill=PANEL, radius=17)
    draw.text((628, 275), "THEME ALLOCATION", font=_font(14, True), fill=TEXT)
    draw.text((628, 299), f"{len(report.holdings)} positions / largest cluster {risk.get('largest_cluster') or '—'}", font=_font(10), fill=MUTED)
    themes = [
        (str(row.get("theme") or "UNKNOWN"), float(row.get("allocation") or 0))
        for _, row in report.theme_allocation.iterrows()
    ]
    _allocation_bars(draw, themes, (628, 337, 1124, 602), limit=5)

    draw.text((48, 648), "AGGREGATED VIEW / NO TICKERS OR SETUP DETAILS", font=_font(10, True), fill=MUTED)
    draw.text((1152, 648), "V38 TRADE JOURNAL", font=_font(10, True), fill=ACCENT, anchor="ra")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=95)


def write_social_copy(report: JournalReport, path: Path) -> None:
    k = report.kpis
    risk = report.portfolio_risk
    text = (
        f"【運用実績｜{report.as_of.date().isoformat()}】\n"
        f"総資産 {_yen(report.account_equity_jpy)}｜本日 {_pct(k.get('daily_return'), signed=True)}｜月初来 {_pct(k.get('mtd_return'), signed=True)}｜年初来 {_pct(k.get('ytd_return'), signed=True)}\n"
        f"PF {_num(k.get('profit_factor'))}｜勝率 {_pct(k.get('win_rate'))}｜平均R {_num(k.get('average_r'))}｜最大DD {_pct(k.get('max_drawdown'))}\n"
        f"NQ {report.nq_color}｜相関調整Heat {_pct(risk.get('correlation_adjusted_heat'))}｜現金 {_pct(k.get('cash_fraction'))}\n"
        "数字は入出金調整後。個別銘柄・Setup・売買ルールの詳細は非公開。\n"
    )
    path.write_text(text, encoding="utf-8")

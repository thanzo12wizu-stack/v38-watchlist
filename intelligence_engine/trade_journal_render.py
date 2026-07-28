from __future__ import annotations

import base64
import urllib.parse
from pathlib import Path

from .trade_journal import JournalReport
from .trade_journal_almanac import render_dashboard as _render_dashboard
from .trade_journal_cards import render_daily_card, render_portfolio_card, write_social_copy


def _data_uri(path: Path, mime: str) -> str | None:
    if not path.exists() or path.stat().st_size <= 0:
        return None
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _embed_artifacts(document: str, output_dir: Path) -> str:
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


def render_dashboard(report: JournalReport, path: Path) -> None:
    """Render the single-file, mobile-first Almanac Trade Journal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    render_daily_card(report, path.parent / "daily_card.png")
    render_portfolio_card(report, path.parent / "portfolio_card.png")
    write_social_copy(report, path.parent / "social_post_ja.txt")
    staging = path.parent / ".trade_journal_almanac.html"
    _render_dashboard(report, staging)
    document = staging.read_text(encoding="utf-8")
    staging.unlink(missing_ok=True)
    path.write_text(_embed_artifacts(document, path.parent), encoding="utf-8")


__all__ = ["render_dashboard", "render_daily_card", "render_portfolio_card", "write_social_copy"]

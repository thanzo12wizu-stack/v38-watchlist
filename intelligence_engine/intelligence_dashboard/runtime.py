from __future__ import annotations

import argparse
from pathlib import Path

from .app import build_html as _build_html
from .formatting import as_list, esc, load_payload, present


def _material_tags(payload: dict) -> list[str]:
    tags: list[str] = []
    for record in as_list(payload.get("external_data")):
        ticker = str(record.get("ticker") or "").strip()
        for key in ("guidance_direction", "event_type"):
            value = record.get(key)
            if not present(value):
                continue
            label = f"{ticker}:{value}" if ticker else str(value)
            if label not in tags:
                tags.append(label)
    return tags[:24]


def build_html(payload: dict) -> str:
    """Render the dashboard while preserving established display contracts."""
    text = (
        _build_html(payload)
        .replace("<small>準備</small>", "<small>準備候補</small>")
        .replace('<option value="READY">準備</option>', '<option value="READY">準備候補</option>')
        .replace("<small>Entry</small>", "<small>Entry帯</small>")
    )

    tags = _material_tags(payload)
    if tags:
        extra = (
            '<section class="section info-panel"><b>Guidance・材料タグ</b>'
            f'<span>{esc(tags)}</span></section>'
        )
        x_marker = '<div id="x" class="view'
        x_index = text.find(x_marker)
        data_close = text.rfind("</div>", 0, x_index) if x_index >= 0 else -1
        if data_close >= 0:
            text = text[:data_close] + extra + text[data_close:]
    return text


def generate(input_path: Path, output_path: Path) -> None:
    output_path.write_text(build_html(load_payload(input_path)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/intelligence/index.json")
    parser.add_argument("--output", default="intelligence-dashboard.html")
    args = parser.parse_args()
    generate(Path(args.input), Path(args.output))

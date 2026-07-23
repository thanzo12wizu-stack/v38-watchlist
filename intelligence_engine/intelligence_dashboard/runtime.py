from __future__ import annotations

import argparse
from pathlib import Path

from .app import build_html as _build_html
from .formatting import load_payload


def build_html(payload: dict) -> str:
    """Render the dashboard while preserving established Japanese UI labels."""
    text = _build_html(payload)
    return (
        text.replace("<small>準備</small>", "<small>準備候補</small>")
        .replace('<option value="READY">準備</option>', '<option value="READY">準備候補</option>')
    )


def generate(input_path: Path, output_path: Path) -> None:
    output_path.write_text(build_html(load_payload(input_path)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/intelligence/index.json")
    parser.add_argument("--output", default="intelligence-dashboard.html")
    args = parser.parse_args()
    generate(Path(args.input), Path(args.output))

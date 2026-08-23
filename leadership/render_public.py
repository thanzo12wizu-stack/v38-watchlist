from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from leadership.render_japanese import render_html
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from render_japanese import render_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Japanese V38-style Leadership public page")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(model), encoding="utf-8")


if __name__ == "__main__":
    main()

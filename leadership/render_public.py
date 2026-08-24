from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from leadership.render_structured import render_html
    from leadership.structure_overlay import apply_structure_overlay
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from render_structured import render_html
    from structure_overlay import apply_structure_overlay


def render_public_html(model: dict) -> str:
    return render_html(apply_structure_overlay(model))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render V38-style Leadership with supply/demand structure")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    enriched = apply_structure_overlay(model)
    args.model.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(enriched), encoding="utf-8")


if __name__ == "__main__":
    main()

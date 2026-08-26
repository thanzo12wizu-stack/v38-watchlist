from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from leadership.diffusion_overlay import apply_diffusion_overlay
    from leadership.prebreakout_overlay import apply_prebreakout_overlay
    from leadership.render_public import _attach_exchange, _load_exchange_map
    from leadership.render_rotation import render_html
    from leadership.rotation_diffusion import apply_diffusion_rotation
    from leadership.structure_overlay import apply_structure_overlay
except ModuleNotFoundError:  # direct execution
    from diffusion_overlay import apply_diffusion_overlay
    from prebreakout_overlay import apply_prebreakout_overlay
    from render_public import _attach_exchange, _load_exchange_map
    from render_rotation import render_html
    from rotation_diffusion import apply_diffusion_rotation
    from structure_overlay import apply_structure_overlay


def build_public_model(
    model: dict[str, Any],
    market_snapshot: dict[str, Any] | None = None,
    exchange_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    structured = apply_structure_overlay(model)
    prepared = apply_prebreakout_overlay(structured)
    prepared = _attach_exchange(prepared, exchange_map)
    prepared = apply_diffusion_overlay(prepared, market_snapshot)
    return apply_diffusion_rotation(prepared)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Leadership with Sector Diffusion as the primary discovery axis")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--market-snapshot", type=Path, default=Path("leadership/market_snapshot.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    market_snapshot = json.loads(args.market_snapshot.read_text(encoding="utf-8")) if args.market_snapshot.exists() else {}
    enriched = build_public_model(model, market_snapshot, _load_exchange_map(args.universe))
    args.model.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(enriched), encoding="utf-8")


if __name__ == "__main__":
    main()

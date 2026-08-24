from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from leadership.prebreakout_overlay import apply_prebreakout_overlay
    from leadership.render_rotation import render_html
    from leadership.rotation_overlay import apply_rotation_overlay
    from leadership.structure_overlay import apply_structure_overlay
except ModuleNotFoundError:  # direct `python leadership/...py` execution
    from prebreakout_overlay import apply_prebreakout_overlay
    from render_rotation import render_html
    from rotation_overlay import apply_rotation_overlay
    from structure_overlay import apply_structure_overlay


def _load_exchange_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            exchange = str(row.get("取引所") or row.get("exchange") or row.get("Exchange") or "").strip().upper()
            if symbol and exchange:
                out[symbol] = exchange
    return out


def _attach_exchange(model: dict[str, Any], exchange_map: dict[str, str] | None) -> dict[str, Any]:
    out = deepcopy(model)
    if not exchange_map:
        return out
    for group in list(out.get("groups") or []):
        for stock in list(group.get("stocks") or []):
            symbol = str(stock.get("symbol") or "").upper()
            if symbol in exchange_map:
                stock["exchange"] = exchange_map[symbol]
    return out


def build_public_model(model: dict[str, Any], exchange_map: dict[str, str] | None = None) -> dict[str, Any]:
    structured = apply_structure_overlay(model)
    prepared = apply_prebreakout_overlay(structured)
    prepared = _attach_exchange(prepared, exchange_map)
    return apply_rotation_overlay(prepared)


def render_public_html(model: dict[str, Any], exchange_map: dict[str, str] | None = None) -> str:
    return render_html(build_public_model(model, exchange_map))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render sector-rotation-first Leadership view")
    parser.add_argument("--model", type=Path, default=Path("leadership/dist/leadership.json"))
    parser.add_argument("--output", type=Path, default=Path("leadership/dist/index.html"))
    parser.add_argument("--universe", type=Path, default=Path("universe.csv"))
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    enriched = build_public_model(model, _load_exchange_map(args.universe))
    args.model.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(enriched), encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def build_context(state_path: Path, live_path: Path) -> dict:
    state = _load(state_path)
    live = _load(live_path)
    market = live.get("market") if isinstance(live.get("market"), dict) else {}
    panic = live.get("panic_tqqq") if isinstance(live.get("panic_tqqq"), dict) else {}

    state_date = str(state.get("date") or "")
    live_date = str(live.get("asof") or "")
    if not state_date or not live_date or state_date != live_date:
        raise ValueError(f"dashboard market date mismatch: state={state_date!r} live={live_date!r}")

    return {
        "schema": "rotation-dashboard-market-1",
        "asof": live_date,
        "market_conditions": panic.get("mc57"),
        "nqsar": market.get("nqsar"),
        "breadth50": market.get("breadth50"),
        "mode": market.get("mode"),
        "new_entry_limit": market.get("new_entry_limit"),
        "crowd_temperature": state.get("senti"),
        "vix": panic.get("vix_close"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Rotation market context from existing Dashboard state")
    parser.add_argument("--state", type=Path, default=Path("state.json"))
    parser.add_argument("--live", type=Path, default=Path("v38-live-state.json"))
    parser.add_argument("--out", type=Path, default=Path("rotation/dashboard-market.json"))
    args = parser.parse_args()

    payload = build_context(args.state, args.live)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

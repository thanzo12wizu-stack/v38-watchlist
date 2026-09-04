from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class AtomicPublishError(RuntimeError):
    """Raised when the live site is not safe to publish as one atomic snapshot."""


def _read_json(root: Path, name: str) -> dict[str, Any]:
    path = root / name
    if not path.is_file():
        raise AtomicPublishError(f"ATOMIC_PUBLISH_MISSING_FILE {name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AtomicPublishError(
            f"ATOMIC_PUBLISH_INVALID_JSON {name}: {type(exc).__name__}: {exc}"
        ) from None
    if not isinstance(value, dict):
        raise AtomicPublishError(f"ATOMIC_PUBLISH_INVALID_OBJECT {name}")
    return value


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise AtomicPublishError(f"{code} {detail}")


def _asof(value: Any) -> str:
    return str(value or "").strip()


def validate_atomic_live_snapshot(root: Path) -> dict[str, Any]:
    """Require every live decision layer to be READY on exactly one as-of date.

    The public mirror must never expose a mixture of sessions.  If any producer is
    stale, incomplete, or DATA REQUIRED, this function raises and the publisher
    leaves the previously published clean snapshot untouched.
    """
    root = root.resolve()
    state = _read_json(root, "state.json")
    live = _read_json(root, "v38-live-state.json")
    tqqq = _read_json(root, "tqqq-panic-state.json")
    sleeve = _read_json(root, "v38-sleeve-state.json")
    rotation_status = _read_json(root, "rotation/data/status.json")
    rotation = _read_json(root, "rotation/data/rotation-theme56.json")

    target = _asof(state.get("date"))
    _require(bool(target), "ATOMIC_PUBLISH_NO_ASOF", "state.json date missing")

    command_center = root / "command-center.html"
    _require(command_center.is_file(), "ATOMIC_PUBLISH_MISSING_FILE", "command-center.html")
    command_text = command_center.read_text(encoding="utf-8", errors="replace")
    _require(
        f"分析基準日 {target}" in command_text,
        "ATOMIC_PUBLISH_COMMAND_CENTER_MISMATCH",
        f"expected={target}",
    )

    normal = sleeve.get("normal_stock") if isinstance(sleeve.get("normal_stock"), dict) else {}
    reset = sleeve.get("rsi_reset") if isinstance(sleeve.get("rsi_reset"), dict) else {}
    current30 = tqqq.get("current30") if isinstance(tqqq.get("current30"), dict) else {}
    rotation_alignment = (
        rotation.get("input_alignment")
        if isinstance(rotation.get("input_alignment"), dict)
        else {}
    )

    dates = {
        "Command Center": target,
        "V38": _asof(live.get("asof")),
        "TQQQ": _asof(tqqq.get("asof")),
        "Sleeve": _asof(sleeve.get("asof")),
        "Normal Stock": _asof(normal.get("asof")),
        "RSI Reset": _asof(reset.get("asof")),
        "Rotation": _asof(rotation_status.get("asof")),
        "Rotation V38": _asof(rotation_status.get("v38_asof")),
        "Rotation brief": _asof(rotation.get("asof")),
        "Rotation brief V38": _asof(rotation_alignment.get("v38_asof")),
    }
    mismatches = {name: value for name, value in dates.items() if value != target}
    _require(
        not mismatches,
        "ATOMIC_PUBLISH_ASOF_MISMATCH",
        json.dumps({"expected": target, "actual": mismatches}, ensure_ascii=False, sort_keys=True),
    )

    _require(
        live.get("schema") == "v38-live-state-1",
        "ATOMIC_PUBLISH_V38_SCHEMA",
        repr(live.get("schema")),
    )
    market = live.get("market") if isinstance(live.get("market"), dict) else {}
    _require(
        market.get("mode") in {"ATTACK", "SELECTIVE", "STOP", "DEFENSE"},
        "ATOMIC_PUBLISH_MARKET_MODE_NOT_READY",
        repr(market.get("mode")),
    )

    _require(
        tqqq.get("schema") == "v38-tqqq-panic-state-1",
        "ATOMIC_PUBLISH_TQQQ_SCHEMA",
        repr(tqqq.get("schema")),
    )
    _require(
        tqqq.get("live_generation_status") == "READY",
        "ATOMIC_PUBLISH_TQQQ_NOT_READY",
        f"status={tqqq.get('live_generation_status')!r} reason={tqqq.get('reason')!r}",
    )
    _require(
        current30.get("status") == "READY",
        "ATOMIC_PUBLISH_CURRENT30_NOT_READY",
        repr(current30.get("status")),
    )
    _require(
        tqqq.get("underlying_target_pct") is not None
        and tqqq.get("requested_target_pct") is not None,
        "ATOMIC_PUBLISH_TQQQ_TARGET_MISSING",
        f"underlying={tqqq.get('underlying_target_pct')!r} requested={tqqq.get('requested_target_pct')!r}",
    )
    _require(
        tqqq.get("sleeve_live_status") == "READY",
        "ATOMIC_PUBLISH_TQQQ_SLEEVE_NOT_READY",
        repr(tqqq.get("sleeve_live_status")),
    )

    _require(
        sleeve.get("schema") == "v38-sleeve-live-1" and sleeve.get("status") == "READY",
        "ATOMIC_PUBLISH_SLEEVE_NOT_READY",
        f"schema={sleeve.get('schema')!r} status={sleeve.get('status')!r}",
    )
    _require(
        normal.get("status") == "READY",
        "ATOMIC_PUBLISH_NORMAL_STOCK_NOT_READY",
        repr(normal.get("status")),
    )
    _require(
        reset.get("status") == "READY",
        "ATOMIC_PUBLISH_RSI_RESET_NOT_READY",
        repr(reset.get("status")),
    )
    quality = reset.get("download_quality") if isinstance(reset.get("download_quality"), dict) else {}
    _require(
        quality.get("coverage_ok") is True,
        "ATOMIC_PUBLISH_RSI_RESET_COVERAGE_NOT_READY",
        json.dumps(quality, ensure_ascii=False, sort_keys=True),
    )

    reset_positions = [p for p in reset.get("positions", []) if isinstance(p, dict)]
    reset_summary = reset.get("monitor_summary") if isinstance(reset.get("monitor_summary"), dict) else {}
    reset_count = reset.get("position_count")
    _require(
        isinstance(reset_count, int)
        and reset_count == len(reset_positions)
        and reset_summary.get("active_positions") == len(reset_positions),
        "ATOMIC_PUBLISH_RSI_RESET_POSITION_MISMATCH",
        json.dumps(
            {
                "position_count": reset_count,
                "positions": [p.get("symbol") for p in reset_positions],
                "active_positions": reset_summary.get("active_positions"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    live_reset = live.get("panic_reset") if isinstance(live.get("panic_reset"), dict) else {}
    live_reset_positions = [p for p in live_reset.get("positions", []) if isinstance(p, dict)]
    reset_symbols = sorted(str(p.get("symbol") or "") for p in reset_positions if str(p.get("symbol") or ""))
    live_reset_symbols = sorted(str(p.get("symbol") or "") for p in live_reset_positions if str(p.get("symbol") or ""))
    _require(
        live_reset.get("position_count") == len(live_reset_positions)
        and live_reset.get("position_count") == reset_count
        and live_reset_symbols == reset_symbols,
        "ATOMIC_PUBLISH_RSI_RESET_V38_MISMATCH",
        json.dumps(
            {
                "sleeve_count": reset_count,
                "sleeve_symbols": reset_symbols,
                "v38_count": live_reset.get("position_count"),
                "v38_symbols": live_reset_symbols,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    gross = live.get("gross100_allocation") if isinstance(live.get("gross100_allocation"), dict) else {}
    _require(
        "LIVE ALLOCATION READY" in str(gross.get("status") or ""),
        "ATOMIC_PUBLISH_GROSS100_NOT_READY",
        repr(gross.get("status")),
    )

    _require(
        rotation_status.get("schema") == "rotation-live-status-1"
        and rotation_status.get("status") == "READY",
        "ATOMIC_PUBLISH_ROTATION_NOT_READY",
        f"schema={rotation_status.get('schema')!r} status={rotation_status.get('status')!r}",
    )
    _require(
        rotation_alignment.get("same_asof") is True,
        "ATOMIC_PUBLISH_ROTATION_ALIGNMENT_NOT_READY",
        json.dumps(rotation_alignment, ensure_ascii=False, sort_keys=True),
    )

    return {
        "schema": "v38-atomic-publish-gate-1",
        "status": "READY",
        "asof": target,
        "layers": {
            "command_center": "READY",
            "v38": "READY",
            "current30": "READY",
            "tqqq": "READY",
            "sleeve": "READY",
            "rsi_reset": "READY",
            "rotation": "READY",
        },
        "market_mode": market.get("mode"),
        "normal_entry_limit": market.get("new_entry_limit"),
        "tqqq_underlying_target_pct": tqqq.get("underlying_target_pct"),
        "tqqq_requested_target_pct": tqqq.get("requested_target_pct"),
        "rsi_reset_pending_entries": len((reset.get("pending") or {}).get("entries") or [])
        if isinstance(reset.get("pending"), dict)
        else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail closed unless the full V38 public snapshot is atomic")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_atomic_live_snapshot(args.root)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()

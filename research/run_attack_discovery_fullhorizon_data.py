from __future__ import annotations

import sys
from typing import Any

import pandas as pd

from research import audit_attack_regime_discovery as discovery
from research import run_backtest_8t3i1e_tqqq_resilient as resilient


DISCOVERY_END_EXCLUSIVE = pd.Timestamp("2022-01-01")
FULL_DATA_END_EXCLUSIVE = "2026-03-21"
_original_resilient = resilient.resilient_download_ohlcv


def full_horizon_download_then_hard_slice(
    symbols: list[str], start: str, end: str, batch_size: int
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Execution/data-quality wrapper only.

    Download through the same frozen comparison horizon so the quality denominator
    is not penalized by current-universe stocks that IPO'd after 2021. Before any
    research feature is built, hard-slice every OHLCV frame to the discovery end.
    Thus no 2022+ value can enter discovery signals, ranks, breadth, NQSAR, or returns.
    """
    requested_end = pd.Timestamp(end)
    if requested_end != DISCOVERY_END_EXCLUSIVE:
        raise RuntimeError(
            f"DISCOVERY_END_UNEXPECTED requested={requested_end.date()} "
            f"expected={DISCOVERY_END_EXCLUSIVE.date()}"
        )

    full, diag = _original_resilient(symbols, start, FULL_DATA_END_EXCLUSIVE, batch_size)
    sliced: dict[str, pd.DataFrame] = {}
    for key, frame in full.items():
        z = frame.loc[frame.index < DISCOVERY_END_EXCLUSIVE].copy()
        if len(z.index) and pd.Timestamp(z.index.max()) >= DISCOVERY_END_EXCLUSIVE:
            raise RuntimeError(f"POST_DISCOVERY_ROW_LEAK key={key}")
        sliced[key] = z

    historical_symbols = [
        s for s in sliced["close"].columns
        if pd.to_numeric(sliced["close"][s], errors="coerce").notna().any()
    ]
    diag = dict(diag)
    diag.update({
        "quality_horizon_end_exclusive": FULL_DATA_END_EXCLUSIVE,
        "research_hard_slice_end_exclusive": str(DISCOVERY_END_EXCLUSIVE.date()),
        "historically_available_by_discovery_end": len(historical_symbols),
        "historically_available_share_of_full_downloaded": (
            len(historical_symbols) / max(1, int(diag.get("downloaded_common") or 0))
        ),
        "post_discovery_rows_passed_to_features": 0,
    })
    print(f"DISCOVERY_FULL_HORIZON_QUALITY_THEN_HARD_SLICE {diag}", flush=True)
    return sliced, diag


def main() -> None:
    # discovery.main assigns audit.download_ohlcv from this module attribute.
    # Patch only the data-acquisition function it reads; no strategy/search code changes.
    discovery.resilient.resilient_download_ohlcv = full_horizon_download_then_hard_slice
    discovery.main()


if __name__ == "__main__":
    main()

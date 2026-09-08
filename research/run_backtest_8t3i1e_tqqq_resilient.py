from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import backtest_8t3i1e_vs_current_with_tqqq as backtest
from build_v38_tqqq_live import download_yahoo_chart


_original_download_ohlcv = audit.download_ohlcv


def _fallback_one(symbol: str, start: str, end: str):
    yahoo = audit.ys(symbol)
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            frame = download_yahoo_chart(yahoo, start=start)
            if frame is None or frame.empty:
                raise RuntimeError("empty")
            frame = frame.copy()
            idx = pd.to_datetime(frame.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            frame.index = idx.normalize()
            frame = frame[frame.index < pd.Timestamp(end)]
            required = ["Open", "High", "Low", "Close", "Volume"]
            if frame.empty or not set(required).issubset(frame.columns):
                raise RuntimeError("ohlcv_missing")
            if not all(pd.to_numeric(frame[c], errors="coerce").notna().any() for c in required):
                raise RuntimeError("ohlcv_empty")
            return symbol, frame[required], None
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
            if attempt < 3:
                time.sleep(0.75 * attempt)
    return symbol, None, " | ".join(errors)


def resilient_download_ohlcv(symbols: list[str], start: str, end: str, batch_size: int):
    out, diag0 = _original_download_ohlcv(symbols, start, end, batch_size)
    requested = list(dict.fromkeys(symbols))
    missing = [
        s for s in requested
        if not all(s in out[k].columns and out[k][s].notna().any() for k in out)
    ]
    print(
        f"PRIMARY_OHLCV coverage={diag0.get('coverage')} missing={len(missing)}; "
        "starting crumb-free Yahoo Chart recovery",
        flush=True,
    )

    recovered: dict[str, pd.DataFrame] = {}
    failed: dict[str, str] = {}
    if missing:
        # Low concurrency intentionally avoids repeating the yfinance burst that triggered HTTP 429.
        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as executor:
            futures = {
                executor.submit(_fallback_one, s, start, end): s
                for s in missing
            }
            for n, future in enumerate(as_completed(futures), 1):
                symbol, frame, error = future.result()
                if frame is not None:
                    recovered[symbol] = frame
                else:
                    failed[symbol] = str(error or "unknown")
                if n % 50 == 0 or n == len(missing):
                    print(
                        f"CHART_RECOVERY {n}/{len(missing)} recovered={len(recovered)} failed={len(failed)}",
                        flush=True,
                    )

    fmap = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    if recovered:
        for key, field in fmap.items():
            add = pd.DataFrame({
                symbol: pd.to_numeric(frame[field], errors="coerce")
                for symbol, frame in recovered.items()
            })
            if not add.empty:
                add.index = pd.to_datetime(add.index).tz_localize(None).normalize()
                merged = pd.concat([out[key], add], axis=1)
                merged = merged.loc[:, ~merged.columns.duplicated(keep="last")]
                out[key] = merged.sort_index().replace([np.inf, -np.inf], np.nan)

    common = [
        s for s in requested
        if all(s in out[k].columns and out[k][s].notna().any() for k in out)
    ]
    for key in out:
        out[key] = out[key].reindex(columns=common)
    diag = {
        "requested": len(requested),
        "downloaded_common": len(common),
        "coverage": len(common) / max(1, len(requested)),
        "failed_batches": int(diag0.get("failed_batches") or 0),
        "primary_downloaded_common": int(diag0.get("downloaded_common") or 0),
        "chart_fallback_requested": len(missing),
        "chart_fallback_recovered": len(recovered),
        "chart_fallback_failed": len(failed),
    }
    print(f"RESILIENT_OHLCV {diag}", flush=True)
    return out, diag


def main():
    # Execution/data-acquisition patch only. Strategy, signals, costs, dates and TQQQ/Gross100 logic remain untouched.
    audit.download_ohlcv = resilient_download_ohlcv
    backtest.main()


if __name__ == "__main__":
    main()

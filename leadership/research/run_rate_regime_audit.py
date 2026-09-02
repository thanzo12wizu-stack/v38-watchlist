from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rate_regimes as base

# Use one official source for the whole research window.  This avoids mixing the
# repo's short recent FRED cache with a different historical provider.
base.SERIES = {
    "dgs2": "UST_PAR_2Y",
    "dgs10": "UST_PAR_10Y",
    "real10": "UST_REAL_PAR_10Y",
    "be10": "UST_BE10_PROXY",
    "dff": "UNUSED_DFF",
}

_FRAMES: dict[tuple[str, int, int], pd.DataFrame] = {}


def _norm(v: object) -> str:
    return "".join(ch.lower() for ch in str(v) if ch.isalnum())


def _find_col(df: pd.DataFrame, wanted: str) -> str:
    key = _norm(wanted)
    exact = { _norm(c): c for c in df.columns }
    if key in exact:
        return exact[key]
    raise KeyError(f"Treasury column {wanted!r} not found; columns={list(df.columns)}")


def _curl_csv(url: str, label: str) -> bytes:
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            print(f"TREASURY_FETCH {label} attempt={attempt}", flush=True)
            cp = subprocess.run(
                [
                    "curl", "--http1.1", "-fL",
                    "--retry", "2", "--retry-all-errors", "--retry-delay", "2",
                    "--connect-timeout", "20", "--max-time", "120",
                    "-A", "Mozilla/5.0 V38-rate-audit",
                    url,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=150,
            )
            if not cp.stdout:
                raise RuntimeError("empty response")
            return cp.stdout
        except Exception as e:
            last = e
            print(f"TREASURY_FETCH_FAIL {label} attempt={attempt}: {type(e).__name__}: {e}", flush=True)
            time.sleep(min(8, 2 * attempt))
    raise RuntimeError(f"Unable to retrieve Treasury data {label}: {last}")


def _treasury_frame(kind: str, start: str, end: str) -> pd.DataFrame:
    sy, ey = pd.Timestamp(start).year, pd.Timestamp(end).year
    cache_key = (kind, sy, ey)
    if cache_key in _FRAMES:
        return _FRAMES[cache_key].copy()

    frames: list[pd.DataFrame] = []
    for year in range(sy, ey + 1):
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            f"daily-treasury-rates.csv/{year}/all?_format=csv&field_tdr_date_value={year}"
            f"&page=&type={kind}"
        )
        raw = _curl_csv(url, f"{kind}:{year}")
        df = pd.read_csv(io.BytesIO(raw))
        if df.empty:
            raise RuntimeError(f"Treasury returned no rows for {kind} {year}")
        date_col = _find_col(df, "Date")
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
        frames.append(df)

    out = pd.concat(frames, axis=0).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.loc[(out.index >= pd.Timestamp(start)) & (out.index <= pd.Timestamp(end))]
    if out.empty:
        raise RuntimeError(f"Treasury history empty after date filter for {kind}")
    _FRAMES[cache_key] = out
    print(f"TREASURY_SOURCE {kind} rows={len(out)} {out.index.min().date()}..{out.index.max().date()}", flush=True)
    return out.copy()


def _col_series(df: pd.DataFrame, wanted: str, name: str) -> pd.Series:
    col = _find_col(df, wanted)
    s = pd.to_numeric(df[col], errors="coerce")
    s.name = name
    return s.dropna().sort_index()


def treasury_series(series_id: str, start: str, end: str) -> pd.Series:
    if series_id == "UST_PAR_2Y":
        n = _treasury_frame("daily_treasury_yield_curve", start, end)
        s = _col_series(n, "2 YR", series_id)
    elif series_id == "UST_PAR_10Y":
        n = _treasury_frame("daily_treasury_yield_curve", start, end)
        s = _col_series(n, "10 YR", series_id)
    elif series_id == "UST_REAL_PAR_10Y":
        r = _treasury_frame("daily_treasury_real_yield_curve", start, end)
        s = _col_series(r, "10 YR", series_id)
    elif series_id == "UST_BE10_PROXY":
        n = _col_series(_treasury_frame("daily_treasury_yield_curve", start, end), "10 YR", "nom10")
        r = _col_series(_treasury_frame("daily_treasury_real_yield_curve", start, end), "10 YR", "real10")
        z = pd.concat([n, r], axis=1).dropna()
        s = (z["nom10"] - z["real10"]).rename(series_id)
        print("TREASURY_SOURCE UST_BE10_PROXY=nominal10-real10", flush=True)
    elif series_id == "UNUSED_DFF":
        # Kept only because the base research script computes generic features for
        # every series. DFF is not used by any tested overlay or regime comparison.
        n = _col_series(_treasury_frame("daily_treasury_yield_curve", start, end), "2 YR", "idx")
        s = pd.Series(np.nan, index=n.index, name=series_id, dtype=float)
        print("TREASURY_SOURCE UNUSED_DFF=NA (not used in tested features)", flush=True)
    else:
        raise KeyError(series_id)

    if series_id != "UNUSED_DFF" and s.empty:
        raise RuntimeError(f"Treasury series empty: {series_id}")
    print(f"RATE_SOURCE {series_id}=US_TREASURY rows={len(s)}", flush=True)
    return s


if __name__ == "__main__":
    base.fetch_fred = treasury_series
    base.main()

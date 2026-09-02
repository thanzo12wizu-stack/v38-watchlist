from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

import audit_rate_regimes as base


def cached_series(series_id: str, start: str, end: str) -> pd.Series | None:
    p = Path("fred_cache.json")
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        rec = obj.get(series_id) or {}
        vals = rec.get("vals") or []
        if not vals:
            return None
        df = pd.DataFrame(vals, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        s = df.dropna().set_index("date")["value"].sort_index()
        if s.empty:
            return None
        # Only trust cache as full historical source when it spans essentially the requested window.
        if s.index.min() <= pd.Timestamp(start) + pd.Timedelta(days=14) and s.index.max() >= pd.Timestamp(end) - pd.Timedelta(days=14):
            print(f"RATE_SOURCE {series_id}=repo_cache rows={len(s)} {s.index.min().date()}..{s.index.max().date()}", flush=True)
            return s.rename(series_id)
        print(f"RATE_CACHE_PARTIAL {series_id} rows={len(s)} {s.index.min().date()}..{s.index.max().date()}", flush=True)
    except Exception as e:
        print(f"RATE_CACHE_ERROR {series_id}: {type(e).__name__}: {e}", flush=True)
    return None


def curl_fred(series_id: str, start: str, end: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
    last: Exception | None = None
    for attempt in range(1, 6):
        try:
            print(f"RATE_FETCH {series_id} attempt={attempt}", flush=True)
            cp = subprocess.run(
                ["curl", "-fL", "--retry", "3", "--retry-all-errors", "--retry-delay", "3",
                 "--connect-timeout", "20", "--max-time", "240", "-A", "Mozilla/5.0 V38-rate-audit", url],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=270,
            )
            df = pd.read_csv(io.BytesIO(cp.stdout))
            date_col = "DATE" if "DATE" in df.columns else ("observation_date" if "observation_date" in df.columns else df.columns[0])
            value_col = series_id if series_id in df.columns else df.columns[-1]
            s = pd.Series(pd.to_numeric(df[value_col], errors="coerce").to_numpy(dtype=float),
                          index=pd.to_datetime(df[date_col], errors="coerce"), name=series_id).dropna()
            s = s[~s.index.duplicated(keep="last")].sort_index()
            if s.empty:
                raise RuntimeError("empty FRED response")
            print(f"RATE_SOURCE {series_id}=FRED rows={len(s)} {s.index.min().date()}..{s.index.max().date()}", flush=True)
            return s
        except Exception as e:
            last = e
            print(f"RATE_FETCH_FAIL {series_id} attempt={attempt}: {type(e).__name__}: {e}", flush=True)
            time.sleep(min(15, 3 * attempt))
    raise RuntimeError(f"Unable to retrieve {series_id} from FRED after retries: {last}")


def robust_fetch(series_id: str, start: str, end: str) -> pd.Series:
    c = cached_series(series_id, start, end)
    if c is not None:
        return c
    return curl_fred(series_id, start, end)


if __name__ == "__main__":
    base.fetch_fred = robust_fetch
    base.main()

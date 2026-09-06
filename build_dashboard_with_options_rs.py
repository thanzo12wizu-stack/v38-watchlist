#!/usr/bin/env python3
"""Build Command Center and export the exact Dashboard RS pool Top12 for Options."""
import json
import math
import os
from pathlib import Path

import build_dashboard as dashboard

OUT = Path(os.environ.get("V38_OPTIONS_RS_JSON", "options-rs-leaders.json"))
_exported = False
_orig_rs_compare_tab = dashboard._rs_compare_tab

def _finite(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None

def _export_dashboard_rs(m):
    global _exported
    if _exported or m is None or getattr(m, "empty", True):
        return
    df = m.copy()
    if "rs_pool" in df.columns:
        df = df[df["rs_pool"].fillna(False)]

    specs = (
        ("short", "RS63", "rs63", "rank_rs63"),
        ("swing", "RS126", "rs126", "rank_rs126"),
        ("medium", "RS189", "rs189", "rank_rs189"),
    )
    rankings = {}
    union = {}
    for mode, label, col, rank_key in specs:
        if col not in df.columns:
            raise RuntimeError(f"Dashboard RS column missing: {col}")
        top = df.dropna(subset=[col]).sort_values(col, ascending=False).head(12)
        if len(top) != 12:
            raise RuntimeError(f"Dashboard {label} Top12 incomplete: {len(top)}")
        rows = []
        for rank, (ticker, row) in enumerate(top.iterrows(), 1):
            ticker = str(ticker).strip().upper()
            value = _finite(row.get(col))
            rec = union.setdefault(ticker, {
                "symbol": ticker,
                "ticker": ticker,
                "role": "DASHBOARD_RS",
            })
            rec[rank_key] = rank
            for metric in ("rs63", "rs126", "rs189"):
                v = _finite(row.get(metric))
                if v is not None:
                    rec[metric] = round(v, 6)
            rows.append({"ticker": ticker, "rank": rank, "value": round(value, 6) if value is not None else None})
        rankings[mode] = {"label": label, "metric": col, "rows": rows}
        dashboard_top10 = [str(t).strip().upper() for t in df.dropna(subset=[col]).sort_values(col, ascending=False).head(10).index]
        if dashboard_top10 != [r["ticker"] for r in rows[:10]]:
            raise RuntimeError(f"{label} Top10 parity check failed")

    asof = str(getattr(dashboard, "_ANALYSIS_ASOF", None) or "")[:10]
    if not asof:
        raise RuntimeError("Dashboard analysis as-of is unavailable")
    payload = {
        "schema_version": 1,
        "asof": asof,
        "source": "command-center.rs_pool",
        "mapping": {
            "short": {"dte": "0-6", "metric": "RS63"},
            "swing": {"dte": "7-21", "metric": "RS126"},
            "medium": {"dte": "22-45", "metric": "RS189"},
        },
        "leadership_market": {"asof": asof},
        "rankings": rankings,
        "leaders": list(union.values()),
    }
    tmp = OUT.with_suffix(OUT.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    _exported = True
    print("OPTIONS_RS_EXPORT", asof, " ".join(f"{k}=12" for k in ("RS63", "RS126", "RS189")))

def _rs_compare_tab_with_export(m, *args, **kwargs):
    _export_dashboard_rs(m)
    return _orig_rs_compare_tab(m, *args, **kwargs)

dashboard._rs_compare_tab = _rs_compare_tab_with_export

if __name__ == "__main__":
    dashboard.main()
    if not _exported or not OUT.is_file():
        raise SystemExit("Options RS Top12 export did not run")

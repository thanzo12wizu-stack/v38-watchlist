from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import rotation_divergence_proxy_backtest as proxy
import rotation_theme56_fullstack_snapshot as fullstack

COMPONENTS = ("breadth21", "breadth50", "ad20_score", "obv_positive20", "updown_volume20")


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def percentile_vs_reference(value: float | None, reference: list[float]) -> float | None:
    if value is None or len(reference) < 20:
        return None
    arr = np.asarray(reference, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 20:
        return None
    less = float(np.sum(arr < value))
    equal = float(np.sum(arr == value))
    return 100.0 * (less + 0.5 * equal) / len(arr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Overlay DRAM supplemental current Internals and 1M Flow without altering the existing Theme55 rankings")
    ap.add_argument("--fullstack", type=Path, required=True)
    ap.add_argument("--price", type=Path, required=True)
    ap.add_argument("--dram-supplement", type=Path, required=True)
    ap.add_argument("--dram-holdings", type=Path, required=True)
    ap.add_argument("--download-start", default="2025-10-01")
    ap.add_argument("--download-end", default="2026-09-02")
    args = ap.parse_args()

    fs = load_json(args.fullstack)
    price = load_json(args.price)
    supp = load_json(args.dram_supplement)
    rows = fs.get("rows") if isinstance(fs.get("rows"), list) else []
    if len(rows) != 56:
        raise RuntimeError(f"expected 56 full-stack rows, got {len(rows)}")
    dram = next((x for x in rows if isinstance(x, dict) and x.get("ticker") == "DRAM"), None)
    if dram is None:
        raise RuntimeError("DRAM row missing from full stack")
    price_row = next((x for x in (price.get("rows") or []) if isinstance(x, dict) and x.get("ticker") == "DRAM"), None)
    if not isinstance(price_row, dict) or price_row.get("quality") != "MARKET_PRICE_SERIES_RS189_PENDING":
        raise RuntimeError("DRAM partial price contract missing")

    holdings = pd.read_csv(args.dram_holdings)
    if set(("sector_etf", "symbol")) - set(holdings.columns):
        raise RuntimeError("DRAM holdings schema mismatch")
    holdings = holdings[holdings["sector_etf"].astype(str).str.upper() == "DRAM"].copy()
    holdings["symbol"] = holdings["symbol"].astype(str).str.upper().str.strip()
    holdings = holdings[~holdings["symbol"].isin({"", "NAN", "--", "-"})].drop_duplicates("symbol")
    if len(holdings) < 8:
        raise RuntimeError(f"DRAM supplemental holdings too small: {len(holdings)}")

    symbols = holdings["symbol"].tolist()
    ohlcv, dl_diag = fullstack.download_theme56_ohlcv(symbols, args.download_start, args.download_end, 20)
    close, volume = ohlcv["close"], ohlcv["volume"]
    downloaded = [s for s in symbols if s in close.columns and s in volume.columns and close[s].notna().sum() >= 80]
    coverage = len(downloaded) / len(symbols) if symbols else 0.0
    if len(downloaded) < 5 or coverage < 0.75:
        raise RuntimeError(f"DRAM supplemental Internal coverage insufficient: {len(downloaded)}/{len(symbols)}={coverage:.3f}")

    comp = proxy.compute_internal_components(close, volume, downloaded, 0.75)
    comp_latest: dict[str, float | None] = {}
    comp_pct: dict[str, float | None] = {}
    for name in COMPONENTS:
        series = pd.to_numeric(comp[name], errors="coerce").dropna()
        latest = None if series.empty else float(series.iloc[-1])
        refs = [num(x.get(name)) for x in rows if isinstance(x, dict) and x.get("ticker") != "DRAM"]
        ref_values = [x for x in refs if x is not None]
        comp_latest[name] = latest
        comp_pct[name] = percentile_vs_reference(latest, ref_values)
    available_pct = [x for x in comp_pct.values() if x is not None]
    internal_score = float(np.median(available_pct)) if len(available_pct) >= 4 else None
    if internal_score is None:
        raise RuntimeError("DRAM supplemental Internal score unavailable")

    flow = supp.get("flow") if isinstance(supp.get("flow"), dict) else {}
    if flow.get("flow_quality") != "SUPPLEMENTAL_ACTUAL_FUND_FLOW_1M":
        raise RuntimeError("DRAM supplemental 1M Flow contract missing")

    dram.update({
        "inception_date": price_row.get("inception_date"),
        "rs189_pending": True,
        "rs63_vs_spy": price_row.get("rs63_vs_spy"),
        "internal_supplemental_score_55ref": internal_score,
        "internal_supplemental_components": comp_latest,
        "internal_supplemental_component_percentiles_55ref": comp_pct,
        "internal_supplemental_members": len(symbols),
        "internal_supplemental_downloaded_members": len(downloaded),
        "internal_supplemental_coverage": coverage,
        "internal_supplemental_quality": "CURRENT_DIRECT_EQUITIES_55THEME_REFERENCE_PERCENTILE",
        "internal_supplemental_membership_asof": (supp.get("holdings") or {}).get("membership_asof"),
        "flow_1m_usd": flow.get("flow_1m_usd"),
        "flow_1m_pct_aum": flow.get("flow_1m_pct_aum"),
        "flow_1m_aum_usd": flow.get("aum_usd"),
        "flow_1m_provider": flow.get("flow_provider"),
        "flow_1m_quality": flow.get("flow_quality"),
        "flow_1m_window": "1M",
        "state": "RS189_PENDING",
        "quality": "DRAM_SUPPLEMENTAL_RS189_PENDING",
    })

    fs["dram_supplemental"] = {
        "enabled": True,
        "ticker": "DRAM",
        "inception_date": price_row.get("inception_date"),
        "price_contract": "Short price history and RS63 are available; RS189 and the established composite Price Score remain pending.",
        "internal_contract": "Supplemental Internal is calculated from current direct listed equity holdings and expressed as a percentile versus the frozen existing 55-theme raw-component reference. Existing 55-theme ranks are not recalculated.",
        "flow_contract": "TradingView fund_flows.1M is displayed as supplemental 1M actual fund flow only. It is not relabeled as 20D and does not enter existing Theme56 state rules.",
        "internal_score_55ref": internal_score,
        "internal_members": len(symbols),
        "internal_downloaded_members": len(downloaded),
        "internal_coverage": coverage,
        "flow_1m_usd": flow.get("flow_1m_usd"),
        "flow_1m_pct_aum": flow.get("flow_1m_pct_aum"),
        "flow_provider": flow.get("flow_provider"),
        "download_diagnostics": dl_diag,
    }
    fs["rows"] = rows
    args.fullstack.write_text(json.dumps(fs, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "ticker": "DRAM",
        "internal_score_55ref": internal_score,
        "internal_coverage": coverage,
        "flow_1m_usd": flow.get("flow_1m_usd"),
        "flow_1m_pct_aum": flow.get("flow_1m_pct_aum"),
        "existing_full_stack_count": fs.get("measured_full_stack_count"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

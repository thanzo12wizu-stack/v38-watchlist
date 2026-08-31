from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pitindex
import rotation_divergence_proxy_backtest as proxy

GICS_TO_ETF = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Information Technology": "XLK",
    "Utilities": "XLU",
}
ETFS = list(GICS_TO_ETF.values())


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def month_ends(start: str, end: str) -> list[pd.Timestamp]:
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    dates = list(pd.date_range(s, e, freq="ME"))
    if not dates or dates[-1] != e:
        dates.append(e)
    return sorted(set(pd.Timestamp(x).normalize() for x in dates if x >= s and x <= e))


def clean_sector(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none"} else None


def snapshot_rows(asof: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pitindex.get_constituents(str(asof.date()), index="sp500").copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["gics_sector"] = df["gics_sector"].map(clean_sector)
    df["sector_etf"] = df["gics_sector"].map(GICS_TO_ETF)
    total = int(len(df))
    known = int(df["sector_etf"].notna().sum())
    unknown = total - known
    per_sector = (
        df.dropna(subset=["sector_etf"])
        .groupby("sector_etf", observed=True)["ticker"]
        .nunique()
        .reindex(ETFS, fill_value=0)
        .astype(int)
        .to_dict()
    )
    unknown_tickers = sorted(df.loc[df["sector_etf"].isna(), "ticker"].dropna().unique().tolist())
    return df, {
        "asof": str(asof.date()),
        "total": total,
        "gics_mapped": known,
        "gics_missing": unknown,
        "mapping_rate": (known / total) if total else None,
        "unknown_tickers": unknown_tickers,
        "known_members_by_sector": per_sector,
    }


def current_alignment(current_pit: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    session = requests.Session()
    rows: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}
    for etf in ETFS:
        ssga = proxy.fetch_ssga_current_holdings(session, etf)
        ssga_set = set(ssga["symbol"].astype(str).str.upper())
        pit_set = set(current_pit.loc[current_pit["sector_etf"] == etf, "ticker"].astype(str).str.upper())
        union = ssga_set | pit_set
        inter = ssga_set & pit_set
        jaccard = len(inter) / len(union) if union else None
        rows.append({
            "sector_etf": etf,
            "pit_members": len(pit_set),
            "ssga_members": len(ssga_set),
            "intersection": len(inter),
            "jaccard": jaccard,
            "pit_only": len(pit_set - ssga_set),
            "ssga_only": len(ssga_set - pit_set),
        })
        detail[etf] = {
            "pit_only": sorted(pit_set - ssga_set),
            "ssga_only": sorted(ssga_set - pit_set),
            "intersection": len(inter),
            "jaccard": jaccard,
        }
    return pd.DataFrame(rows), detail


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit free PIT S&P500 membership/GICS coverage for Sector Rotation survivorship cleanup")
    ap.add_argument("--start", default="2022-01-31")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_pit_membership_audit_outputs"))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    dates = month_ends(args.start, args.end)
    summary_rows: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    snapshots: dict[str, pd.DataFrame] = {}

    for asof in dates:
        df, info = snapshot_rows(asof)
        snapshots[info["asof"]] = df
        summary_rows.append({k: v for k, v in info.items() if k not in {"unknown_tickers", "known_members_by_sector"}})
        for ticker in info["unknown_tickers"]:
            row = df.loc[df["ticker"] == ticker].iloc[0]
            unknown_rows.append({
                "asof": info["asof"],
                "ticker": ticker,
                "name": row.get("name"),
                "cik": row.get("cik"),
                "gics_sector": row.get("gics_sector"),
                "gics_sub_industry": row.get("gics_sub_industry"),
            })
        for etf, n in info["known_members_by_sector"].items():
            sector_rows.append({"asof": info["asof"], "sector_etf": etf, "known_members": n, "total_unknown_sp500": info["gics_missing"]})
        print(f"PIT {info['asof']}: total={info['total']} mapped={info['gics_mapped']} missing={info['gics_missing']} rate={info['mapping_rate']:.2%}", flush=True)

    coverage = pd.DataFrame(summary_rows)
    unknown = pd.DataFrame(unknown_rows)
    sectors = pd.DataFrame(sector_rows)
    coverage.to_csv(args.output / "monthly_gics_coverage.csv", index=False)
    unknown.to_csv(args.output / "monthly_unknown_constituents.csv", index=False)
    sectors.to_csv(args.output / "monthly_sector_known_counts.csv", index=False)

    current_date = max(snapshots)
    current = snapshots[current_date]
    alignment, alignment_detail = current_alignment(current)
    alignment.to_csv(args.output / "current_pit_vs_ssga_alignment.csv", index=False)

    recurring_unknown = pd.DataFrame()
    if not unknown.empty:
        recurring_unknown = (
            unknown.groupby(["ticker", "name"], dropna=False)
            .agg(months_missing=("asof", "nunique"), first_seen=("asof", "min"), last_seen=("asof", "max"))
            .reset_index()
            .sort_values(["months_missing", "ticker"], ascending=[False, True])
        )
        recurring_unknown.to_csv(args.output / "unknown_constituent_frequency.csv", index=False)

    mapping_min = float(coverage["mapping_rate"].min()) if not coverage.empty else None
    mapping_median = float(coverage["mapping_rate"].median()) if not coverage.empty else None
    mapping_latest = float(coverage.iloc[-1]["mapping_rate"]) if not coverage.empty else None
    max_missing = int(coverage["gics_missing"].max()) if not coverage.empty else None
    total_unique_unknown = int(unknown["ticker"].nunique()) if not unknown.empty else 0
    align_min = float(alignment["jaccard"].min()) if not alignment.empty else None
    align_median = float(alignment["jaccard"].median()) if not alignment.empty else None

    # Research usability threshold: historical GICS coverage >=98% monthly and current sector-set Jaccard >=95%.
    # This is deliberately strict because a handful of missing names can distort small sectors.
    usable_for_pit_sector_internal = bool(
        mapping_min is not None and mapping_min >= 0.98
        and align_min is not None and align_min >= 0.95
    )

    report = {
        "schema": 1,
        "research_only": True,
        "source": "pitindex pinned public dataset + official current SSGA sector ETF holdings",
        "pitindex_version": getattr(pitindex, "__version__", None),
        "pitindex_info": pitindex.info(index="sp500"),
        "window": {"start": str(dates[0].date()), "end": str(dates[-1].date()), "snapshots": len(dates)},
        "gics_coverage": {
            "min_mapping_rate": mapping_min,
            "median_mapping_rate": mapping_median,
            "latest_mapping_rate": mapping_latest,
            "max_missing_in_snapshot": max_missing,
            "unique_unknown_tickers": total_unique_unknown,
        },
        "current_alignment": {
            "min_jaccard": align_min,
            "median_jaccard": align_median,
            "detail": alignment_detail,
        },
        "decision": {
            "usable_for_pit_sector_internal_without_extra_sector_backfill": usable_for_pit_sector_internal,
            "thresholds": {"monthly_gics_mapping_min": 0.98, "current_sector_jaccard_min": 0.95},
            "reason": (
                "PIT membership/GICS coverage and current sector alignment clear strict guards."
                if usable_for_pit_sector_internal
                else "Fails strict PIT sector-classification/alignment guard; do not use directly for final Distribution validation without remediation."
            ),
        },
        "limitations": [
            "pitindex states that GICS metadata for delisted/removed historical constituents can be missing.",
            "Current SSGA holdings comparison validates present-day mapping only, not historical Select Sector index membership weights.",
            "No historical weights are used; intended downstream internal test is equal-weight only.",
        ],
    }
    (args.output / "pit_membership_audit.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# PIT Sector Membership Audit", "",
        "Research-only audit before using free PIT S&P500 membership to re-test Distribution.", "",
        f"- Monthly GICS mapping min: {mapping_min:.2%}" if mapping_min is not None else "- Monthly GICS mapping min: n/a",
        f"- Monthly GICS mapping median: {mapping_median:.2%}" if mapping_median is not None else "- Monthly GICS mapping median: n/a",
        f"- Max missing constituents in one snapshot: {max_missing}",
        f"- Unique historical unknown tickers: {total_unique_unknown}",
        f"- Current SSGA-vs-PIT sector Jaccard min: {align_min:.2%}" if align_min is not None else "- Current SSGA-vs-PIT sector Jaccard min: n/a",
        f"- Decision: {'PASS' if usable_for_pit_sector_internal else 'FAIL'}", "",
        "## Current alignment", "",
        "| ETF | PIT | SSGA | Intersection | Jaccard | PIT only | SSGA only |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in alignment.itertuples(index=False):
        lines.append(f"| {r.sector_etf} | {r.pit_members} | {r.ssga_members} | {r.intersection} | {r.jaccard:.2%} | {r.pit_only} | {r.ssga_only} |")
    if not recurring_unknown.empty:
        lines += ["", "## Most persistent missing-GICS historical members", ""]
        for r in recurring_unknown.head(20).itertuples(index=False):
            lines.append(f"- {r.ticker}: {int(r.months_missing)} monthly snapshots ({r.first_seen} to {r.last_seen})")
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"DECISION {'PASS' if usable_for_pit_sector_internal else 'FAIL'} min_mapping={mapping_min:.4f} min_jaccard={align_min:.4f}", flush=True)


if __name__ == "__main__":
    main()

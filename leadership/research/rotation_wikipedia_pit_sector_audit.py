from __future__ import annotations

import argparse
import io
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import pitindex

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List of S&P 500 companies"
UA = "V38-Rotation-Research/1.0 (public-data research; github.com/thanzo12wizu-stack/v38-watchlist)"
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
    return sorted(set(pd.Timestamp(x).normalize() for x in dates if s <= x <= e))


def norm_ticker(v: Any) -> str | None:
    if v is None or pd.isna(v):
        return None
    s = re.sub(r"\[[^\]]*\]", "", str(v)).strip().upper()
    s = s.replace("–", "-").replace("—", "-")
    if not s or s in {"NAN", "NONE", "-"}:
        return None
    return s


def clean_text(v: Any) -> str | None:
    if v is None or pd.isna(v):
        return None
    s = re.sub(r"\[[^\]]*\]", "", str(v)).strip()
    return s if s and s.lower() not in {"nan", "none"} else None


def revision_at_or_before(session: requests.Session, asof: pd.Timestamp) -> dict[str, Any]:
    # Use end-of-calendar-day UTC. This avoids using any revision after the observation date.
    cutoff = (pd.Timestamp(asof).normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "revisions",
        "titles": WIKI_PAGE,
        "rvprop": "ids|timestamp",
        "rvlimit": "1",
        "rvdir": "older",
        "rvstart": cutoff,
        "redirects": "1",
    }
    r = session.get(WIKI_API, params=params, headers={"User-Agent": UA}, timeout=45)
    r.raise_for_status()
    payload = r.json()
    pages = payload.get("query", {}).get("pages", [])
    if not pages or not pages[0].get("revisions"):
        raise RuntimeError(f"Wikipedia revision not found for {asof.date()}")
    rev = pages[0]["revisions"][0]
    return {"revid": int(rev["revid"]), "timestamp": rev["timestamp"]}


def parse_revision_roster(session: requests.Session, revid: int) -> pd.DataFrame:
    url = f"https://en.wikipedia.org/w/index.php?title=List_of_S%26P_500_companies&oldid={revid}"
    r = session.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    chosen = None
    for t in tables:
        cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        low = [c.lower() for c in cols]
        if any("symbol" in c for c in low) and any("gics sector" in c for c in low):
            t = t.copy()
            t.columns = cols
            chosen = t
            break
    if chosen is None:
        raise RuntimeError(f"S&P 500 constituent table not found in revision {revid}")

    def find_col(fragment: str) -> str | None:
        for c in chosen.columns:
            if fragment in c.lower():
                return c
        return None

    c_symbol = find_col("symbol")
    c_security = find_col("security")
    c_sector = find_col("gics sector")
    c_sub = find_col("gics sub-industry") or find_col("gics sub industry")
    if not c_symbol or not c_sector:
        raise RuntimeError(f"revision {revid}: required columns missing")

    out = pd.DataFrame({
        "ticker": chosen[c_symbol].map(norm_ticker),
        "name": chosen[c_security].map(clean_text) if c_security else None,
        "gics_sector": chosen[c_sector].map(clean_text),
        "gics_sub_industry": chosen[c_sub].map(clean_text) if c_sub else None,
    })
    out = out.dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first")
    out["sector_etf"] = out["gics_sector"].map(GICS_TO_ETF)
    return out.reset_index(drop=True)


def audit_date(session: requests.Session, asof: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    rev = revision_at_or_before(session, asof)
    wiki = parse_revision_roster(session, rev["revid"])
    pit = pitindex.get_constituents(str(asof.date()), index="sp500").copy()
    pit["ticker"] = pit["ticker"].map(norm_ticker)
    pit = pit.dropna(subset=["ticker"]).drop_duplicates("ticker", keep="first")

    wiki_set = set(wiki["ticker"])
    pit_set = set(pit["ticker"])
    inter = wiki_set & pit_set
    union = wiki_set | pit_set
    mapped = wiki[wiki["ticker"].isin(pit_set) & wiki["sector_etf"].notna()]["ticker"].nunique()
    total = len(pit_set)
    missing = sorted(pit_set - set(wiki.loc[wiki["sector_etf"].notna(), "ticker"]))

    detail: list[dict[str, Any]] = []
    for ticker in missing:
        wr = wiki.loc[wiki["ticker"] == ticker]
        detail.append({
            "asof": str(asof.date()),
            "ticker": ticker,
            "in_wikipedia_revision": not wr.empty,
            "wiki_sector": None if wr.empty else wr.iloc[0].get("gics_sector"),
            "revision_id": rev["revid"],
            "revision_timestamp": rev["timestamp"],
        })

    info = {
        "asof": str(asof.date()),
        "revision_id": rev["revid"],
        "revision_timestamp": rev["timestamp"],
        "pit_size": total,
        "wikipedia_size": len(wiki_set),
        "intersection": len(inter),
        "jaccard": (len(inter) / len(union)) if union else None,
        "pit_sector_mapped": mapped,
        "pit_sector_mapping_rate": (mapped / total) if total else None,
        "pit_missing_sector": len(missing),
    }
    wiki = wiki.copy()
    wiki["asof"] = str(asof.date())
    wiki["revision_id"] = rev["revid"]
    wiki["revision_timestamp"] = rev["timestamp"]
    return wiki, info, detail


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit point-in-time Wikipedia GICS sector snapshots against pinned PIT S&P500 membership")
    ap.add_argument("--start", default="2022-01-31")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_wikipedia_pit_sector_audit_outputs"))
    ap.add_argument("--sleep", type=float, default=0.10)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    dates = month_ends(args.start, args.end)
    summaries: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    snapshots: list[pd.DataFrame] = []

    for i, asof in enumerate(dates, 1):
        wiki, info, missing = audit_date(session, asof)
        summaries.append(info)
        missing_rows.extend(missing)
        snapshots.append(wiki)
        print(
            f"WIKI_PIT {i}/{len(dates)} {info['asof']} rev={info['revision_id']} "
            f"jaccard={info['jaccard']:.2%} sector_map={info['pit_sector_mapping_rate']:.2%} missing={info['pit_missing_sector']}",
            flush=True,
        )
        if args.sleep > 0:
            time.sleep(args.sleep)

    summary = pd.DataFrame(summaries)
    missing_df = pd.DataFrame(missing_rows)
    snapshot_df = pd.concat(snapshots, ignore_index=True) if snapshots else pd.DataFrame()
    summary.to_csv(args.output / "monthly_wikipedia_pit_quality.csv", index=False)
    missing_df.to_csv(args.output / "monthly_wikipedia_pit_missing.csv", index=False)
    snapshot_df.to_csv(args.output / "monthly_wikipedia_sector_snapshots.csv", index=False)

    min_jaccard = float(summary["jaccard"].min()) if not summary.empty else None
    med_jaccard = float(summary["jaccard"].median()) if not summary.empty else None
    min_mapping = float(summary["pit_sector_mapping_rate"].min()) if not summary.empty else None
    med_mapping = float(summary["pit_sector_mapping_rate"].median()) if not summary.empty else None
    max_missing = int(summary["pit_missing_sector"].max()) if not summary.empty else None
    usable = bool(min_jaccard is not None and min_jaccard >= 0.98 and min_mapping is not None and min_mapping >= 0.98)

    report = {
        "schema": 1,
        "research_only": True,
        "source": "Wikipedia point-in-time page revisions at-or-before observation date + pitindex pinned S&P500 membership",
        "pitindex_version": getattr(pitindex, "__version__", None),
        "window": {"start": str(dates[0].date()), "end": str(dates[-1].date()), "snapshots": len(dates)},
        "quality": {
            "min_roster_jaccard": min_jaccard,
            "median_roster_jaccard": med_jaccard,
            "min_sector_mapping_rate": min_mapping,
            "median_sector_mapping_rate": med_mapping,
            "max_missing_sector_in_snapshot": max_missing,
        },
        "decision": {
            "usable_as_pit_sector_source_for_distribution_retest": usable,
            "thresholds": {"min_roster_jaccard": 0.98, "min_sector_mapping_rate": 0.98},
            "reason": "Clears strict PIT roster and sector coverage guards." if usable else "Fails strict PIT roster/sector coverage guard; do not use for final Distribution validation.",
        },
        "limitations": [
            "Wikipedia revisions are public-information snapshots, not official S&P/State Street constituent files.",
            "Revision is chosen at or before end-of-calendar-day UTC to avoid using future revisions.",
            "Monthly audit validates the reconstruction route; final backtest must densify PIT sectors across membership and GICS-classification change dates rather than freeze one current roster.",
        ],
    }
    (args.output / "wikipedia_pit_sector_audit.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Wikipedia PIT Sector Audit",
        "",
        "Research-only validation of historical GICS sector reconstruction before Distribution PIT retest.",
        "",
        f"- Roster Jaccard min: {min_jaccard:.2%}" if min_jaccard is not None else "- Roster Jaccard min: n/a",
        f"- Roster Jaccard median: {med_jaccard:.2%}" if med_jaccard is not None else "- Roster Jaccard median: n/a",
        f"- Sector mapping min: {min_mapping:.2%}" if min_mapping is not None else "- Sector mapping min: n/a",
        f"- Sector mapping median: {med_mapping:.2%}" if med_mapping is not None else "- Sector mapping median: n/a",
        f"- Max missing sector names: {max_missing}",
        f"- Decision: {'PASS' if usable else 'FAIL'}",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DECISION {'PASS' if usable else 'FAIL'} min_jaccard={min_jaccard:.4f} min_mapping={min_mapping:.4f}", flush=True)


if __name__ == "__main__":
    main()

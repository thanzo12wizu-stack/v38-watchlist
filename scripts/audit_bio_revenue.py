#!/usr/bin/env python3
"""Warning-only revenue diagnostic for the clinical-stage biotech exclusion.

This script MUST NOT change Core 12 / picks.  It only measures whether a
future mechanical rule can separate low-revenue clinical-stage healthcare
names from established commercial healthcare companies.

Primary diagnostic rule (provisional, not a trading rule):
    healthcare-like AND market cap < $10B AND TTM revenue < $50M

SEC/network/mapping/revenue missing data is PASS + visible warning.  Missing
fundamentals must never silently remove a stock from the selection.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import time
import urllib.request
from pathlib import Path

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DEFAULT_MCAP_MAX = 10_000_000_000.0
DEFAULT_REVENUE_MAX = 50_000_000.0
CACHE_TTL_DAYS = 7
# Audit controls only.  These are NOT production overrides and never affect picks.
CONTROL_TICKERS = ("SYRE", "AMLX", "BFLY", "LLY", "JNJ")
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().replace(microsecond=0).isoformat()


def _finite_number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _parse_date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _norm_ticker(value: str) -> str:
    return str(value or "").strip().upper()


def _ticker_key(value: str) -> str:
    # SEC mapping and market-data sources sometimes differ only in class punctuation.
    return _norm_ticker(value).replace(".", "-").replace("/", "-")


def _read_json(path: Path, default):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj
    except Exception:
        return default


def _read_state_picks(path: Path):
    state = _read_json(path, {})
    out = []
    for ticker in state.get("picks") or []:
        t = _norm_ticker(ticker)
        if t and t not in out:
            out.append(t)
    return state, out


def _read_universe(path: Path):
    rows = {}
    if not path.exists():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = _norm_ticker(row.get("シンボル") or row.get("ticker") or row.get("symbol"))
            if ticker:
                rows[ticker] = row
    return rows


def _healthcare_like(meta) -> bool:
    sector = str((meta or {}).get("セクター") or (meta or {}).get("sector") or "").upper()
    industry = str((meta or {}).get("業種") or (meta or {}).get("industry") or "").upper()
    text = sector + " | " + industry
    return any(token in text for token in (
        "HEALTH", "BIOTECH", "PHARM", "MEDICAL", "DRUG",
    ))


def _mcap(meta):
    return _finite_number((meta or {}).get("時価総額") or (meta or {}).get("market_cap") or (meta or {}).get("mcap"))


def _fresh(rec, now: dt.datetime) -> bool:
    if not isinstance(rec, dict):
        return False
    ts = rec.get("checked_at")
    try:
        checked = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=dt.timezone.utc)
        return (now - checked).total_seconds() < CACHE_TTL_DAYS * 86400
    except Exception:
        return False


def _request_json(url: str, user_agent: str, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        # urllib does not always decode gzip automatically.
        enc = str(response.headers.get("Content-Encoding") or "").lower()
        if "gzip" in enc:
            import gzip
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def _load_sec_ticker_map(user_agent: str):
    raw = _request_json(SEC_TICKERS_URL, user_agent)
    out = {}
    vals = raw.values() if isinstance(raw, dict) else raw
    for item in vals:
        if not isinstance(item, dict):
            continue
        ticker = _norm_ticker(item.get("ticker"))
        try:
            cik = int(item.get("cik_str"))
        except Exception:
            continue
        if ticker:
            out[_ticker_key(ticker)] = cik
    return out


def _dedupe_facts(items):
    """Normalize SEC duration facts and keep the latest filing for duplicates."""
    by_key = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("form") or "") not in ("10-Q", "10-K"):
            continue
        value = _finite_number(item.get("val"))
        start = _parse_date(item.get("start"))
        end = _parse_date(item.get("end"))
        filed = _parse_date(item.get("filed"))
        if value is None or value < 0 or start is None or end is None or end < start:
            continue
        duration = (end - start).days + 1
        rec = {
            "value": value,
            "start": start,
            "end": end,
            "filed": filed or end,
            "duration": duration,
            "form": str(item.get("form")),
            "fp": str(item.get("fp") or ""),
            "fy": item.get("fy"),
            "accn": str(item.get("accn") or ""),
        }
        key = (start, end, rec["form"], rec["fp"])
        old = by_key.get(key)
        if old is None or rec["filed"] >= old["filed"]:
            by_key[key] = rec
    return list(by_key.values())


def _revenue_from_tag(companyfacts, tag):
    try:
        units = companyfacts["facts"]["us-gaap"][tag]["units"]
    except Exception:
        return None
    usd = units.get("USD") if isinstance(units, dict) else None
    facts = _dedupe_facts(usd)
    if not facts:
        return None

    annual = [r for r in facts if r["form"] == "10-K" and r["fp"] == "FY" and 250 <= r["duration"] <= 430]
    if not annual:
        return None
    annual.sort(key=lambda r: (r["end"], r["filed"]))
    fy = annual[-1]

    # Exact TTM when a post-FY 10-Q exists:
    # latest FY + current-YTD - comparable prior-year-YTD.
    q_after = [r for r in facts if r["form"] == "10-Q" and r["fp"] in ("Q1", "Q2", "Q3") and r["end"] > fy["end"]]
    if q_after:
        latest_end = max(r["end"] for r in q_after)
        same_end = [r for r in q_after if r["end"] == latest_end]
        current = max(same_end, key=lambda r: (r["duration"], r["filed"]))
        # For the same fiscal period in the prior year, choose the longest-duration
        # fact (YTD rather than the standalone quarter) and the closest annual offset.
        prior = [
            r for r in facts
            if r["form"] == "10-Q" and r["fp"] == current["fp"] and r["end"] < current["end"]
            and 300 <= (current["end"] - r["end"]).days <= 430
        ]
        if prior:
            prior_end = max(r["end"] for r in prior)
            prior_same_end = [r for r in prior if r["end"] == prior_end]
            previous = max(prior_same_end, key=lambda r: (r["duration"], r["filed"]))
            ttm = fy["value"] + current["value"] - previous["value"]
            if math.isfinite(ttm) and ttm >= 0:
                return {
                    "revenue_ttm": ttm,
                    "revenue_latest_fy": fy["value"],
                    "revenue_period_end": current["end"].isoformat(),
                    "method": "fy_plus_current_ytd_minus_prior_ytd",
                    "tag": tag,
                }

    # Do not mislabel an annual figure as TTM.  Keep it as a visible fallback only.
    return {
        "revenue_ttm": None,
        "revenue_latest_fy": fy["value"],
        "revenue_period_end": fy["end"].isoformat(),
        "method": "latest_fy_fallback",
        "tag": tag,
    }


def _extract_revenue(companyfacts):
    fallback = None
    for tag in REVENUE_TAGS:
        rec = _revenue_from_tag(companyfacts, tag)
        if not rec:
            continue
        if rec.get("revenue_ttm") is not None:
            return rec
        if fallback is None:
            fallback = rec
    return fallback


def _sec_record(ticker, cik_map, user_agent):
    cik = cik_map.get(_ticker_key(ticker))
    checked_at = _iso_now()
    if cik is None:
        return {"status": "missing_cik", "checked_at": checked_at}
    try:
        facts = _request_json(SEC_FACTS_URL.format(cik=cik), user_agent)
        revenue = _extract_revenue(facts)
        if not revenue:
            return {
                "status": "missing_revenue_fact",
                "cik": cik,
                "checked_at": checked_at,
            }
        return {
            "status": "ok" if revenue.get("revenue_ttm") is not None else "annual_fallback",
            "cik": cik,
            "checked_at": checked_at,
            **revenue,
        }
    except Exception as exc:
        return {
            "status": "fetch_error",
            "cik": cik,
            "checked_at": checked_at,
            "error": type(exc).__name__,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--universe", default="universe.csv")
    ap.add_argument("--output", default="bio_revenue_audit.json")
    ap.add_argument("--mcap-max", type=float, default=DEFAULT_MCAP_MAX)
    ap.add_argument("--revenue-max", type=float, default=DEFAULT_REVENUE_MAX)
    args = ap.parse_args()

    state, picks = _read_state_picks(Path(args.state))
    universe = _read_universe(Path(args.universe))
    out_path = Path(args.output)
    previous = _read_json(out_path, {})
    old_records = previous.get("records") if isinstance(previous, dict) else {}
    old_records = old_records if isinstance(old_records, dict) else {}
    now = _now()

    targets = []
    for ticker in list(picks) + list(CONTROL_TICKERS):
        if ticker not in targets:
            targets.append(ticker)

    records = dict(old_records)
    user_agent = str(os.environ.get("SEC_USER_AGENT") or "").strip()
    cik_map = None
    map_error = None
    if user_agent:
        try:
            cik_map = _load_sec_ticker_map(user_agent)
        except Exception as exc:
            map_error = type(exc).__name__
    else:
        map_error = "SEC_USER_AGENT_missing"

    diagnostics = []
    for ticker in targets:
        meta = universe.get(ticker, {})
        healthcare = _healthcare_like(meta)
        mcap = _mcap(meta)
        cached = records.get(ticker)
        if _fresh(cached, now):
            rec = cached
        elif cik_map is None:
            # PASS + flag.  Keep a fresh prior successful value if one exists;
            # otherwise expose the missing dependency without changing selection.
            rec = dict(cached) if isinstance(cached, dict) else {}
            rec.update({
                "status": "sec_unavailable",
                "checked_at": _iso_now(),
                "error": map_error,
            })
        else:
            rec = _sec_record(ticker, cik_map, user_agent)
            records[ticker] = rec
            time.sleep(0.12)

        revenue_ttm = _finite_number(rec.get("revenue_ttm")) if isinstance(rec, dict) else None
        data_ok = revenue_ttm is not None
        small = mcap is not None and mcap < args.mcap_max
        would_exclude = bool(healthcare and small and data_ok and revenue_ttm < args.revenue_max)
        missing_data = bool(healthcare and small and not data_ok)
        diag = {
            "ticker": ticker,
            "in_core12": ticker in picks,
            "sector": str(meta.get("セクター") or meta.get("sector") or ""),
            "industry": str(meta.get("業種") or meta.get("industry") or ""),
            "market_cap": mcap,
            "healthcare_like": healthcare,
            "under_mcap_cap": small,
            "revenue_ttm": revenue_ttm,
            "revenue_latest_fy": _finite_number(rec.get("revenue_latest_fy")) if isinstance(rec, dict) else None,
            "revenue_status": str(rec.get("status") or "missing") if isinstance(rec, dict) else "missing",
            "revenue_method": str(rec.get("method") or "") if isinstance(rec, dict) else "",
            "revenue_tag": str(rec.get("tag") or "") if isinstance(rec, dict) else "",
            "would_exclude_at_50m": would_exclude,
            "missing_revenue_passes": missing_data,
        }
        diagnostics.append(diag)

        if would_exclude:
            print(
                "::warning::bio-revenue diagnostic only: "
                f"{ticker} would be excluded at ${args.revenue_max/1e6:.0f}M "
                f"(TTM=${revenue_ttm/1e6:.1f}M, mcap=${mcap/1e9:.2f}B); picks unchanged"
            )
        elif missing_data:
            print(
                "::warning::bio-revenue missing/pass: "
                f"{ticker} status={diag['revenue_status']}; picks unchanged"
            )

    payload = {
        "version": 1,
        "mode": "warning_only_no_selection_effect",
        "checked_at": _iso_now(),
        "state_date": state.get("date"),
        "thresholds": {
            "healthcare_like": True,
            "market_cap_lt": args.mcap_max,
            "revenue_ttm_lt": args.revenue_max,
        },
        "missing_data_policy": "pass_with_visible_flag",
        "controls_are_diagnostic_only": list(CONTROL_TICKERS),
        "records": records,
        "diagnostics": diagnostics,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    core = [d for d in diagnostics if d["in_core12"]]
    flagged = [d["ticker"] for d in core if d["would_exclude_at_50m"]]
    missing = [d["ticker"] for d in core if d["missing_revenue_passes"]]
    print(
        f"[bio-revenue] warning-only core={len(core)} would_exclude={flagged} "
        f"missing_pass={missing} output={out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

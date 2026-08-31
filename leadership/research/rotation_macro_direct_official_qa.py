from __future__ import annotations

import argparse
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import requests

UA = "Mozilla/5.0 V38-Rotation-Research/1.0"
TREASURY_BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
FED_BROAD_DAILY = "https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm"


def local(tag: str) -> str:
    return tag.split("}")[-1]


def fetch_treasury(session: requests.Session, data_name: str, field: str, year: int) -> tuple[pd.DataFrame | None, str | None, str]:
    url = f"{TREASURY_BASE}?data={data_name}&field_tdr_date_value={year}"
    try:
        r = session.get(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,*/*"}, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        rows: list[dict[str, Any]] = []
        for elem in root.iter():
            if local(elem.tag) != "properties":
                continue
            rec = {local(child.tag): child.text for child in list(elem)}
            if rec:
                rows.append(rec)
        df = pd.DataFrame(rows)
        if df.empty or "NEW_DATE" not in df.columns or field not in df.columns:
            raise RuntimeError(f"missing required columns; got={list(df.columns)[:20]}")
        df = df[["NEW_DATE", field]].rename(columns={"NEW_DATE": "date", field: "value"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["date", "value"]).sort_values("date")
        if len(df) < 20:
            raise RuntimeError(f"too few valid rows: {len(df)}")
        return df, None, url
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", url


def fetch_fed_broad(session: requests.Session) -> tuple[pd.DataFrame | None, str | None]:
    try:
        r = session.get(FED_BROAD_DAILY, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        hit = None
        for table in tables:
            cols = [str(c).strip().lower() for c in table.columns]
            if len(cols) >= 2 and "date" in cols[0] and "rate" in cols[1]:
                hit = table.iloc[:, :2].copy()
                break
        if hit is None:
            raise RuntimeError("Date/Rate table not found")
        hit.columns = ["date", "value"]
        hit["date"] = pd.to_datetime(hit["date"], errors="coerce")
        hit["value"] = pd.to_numeric(hit["value"], errors="coerce")
        hit = hit.dropna(subset=["date", "value"]).sort_values("date")
        if len(hit) < 1000:
            raise RuntimeError(f"too few Broad Dollar rows: {len(hit)}")
        return hit, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def diag(name: str, df: pd.DataFrame | None, error: str | None, source: str) -> dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "quality": "EXACT_OFFICIAL" if df is not None and error is None else "DATA_REQUIRED",
        "error": error,
        "rows": 0 if df is None else int(len(df)),
        "first_date": None if df is None or df.empty else str(df.date.iloc[0].date()),
        "last_date": None if df is None or df.empty else str(df.date.iloc[-1].date()),
        "last_value": None if df is None or df.empty else float(df.value.iloc[-1]),
        "change_20obs": None if df is None or len(df) < 21 else float(df.value.iloc[-1] - df.value.iloc[-21]),
        "high_252": None if df is None or df.empty else float(df.value.tail(252).max()),
        "low_252": None if df is None or df.empty else float(df.value.tail(252).min()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="QA direct official Macro WHY sources without FRED dependency")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    nominal, nerr, nurl = fetch_treasury(session, "daily_treasury_yield_curve", "BC_10YEAR", args.year)
    real, rerr, rurl = fetch_treasury(session, "daily_treasury_real_yield_curve", "TC_10YEAR", args.year)
    broad, berr = fetch_fed_broad(session)

    if nominal is not None:
        nominal.to_csv(args.output / "treasury_10y.csv", index=False, date_format="%Y-%m-%d")
    if real is not None:
        real.to_csv(args.output / "treasury_real10y.csv", index=False, date_format="%Y-%m-%d")
    if broad is not None:
        broad.to_csv(args.output / "fed_broad_dollar_daily.csv", index=False, date_format="%Y-%m-%d")

    report = {
        "schema": 1,
        "research_only": True,
        "series": {
            "us10y": diag("US 10Y Treasury Par Yield", nominal, nerr, nurl),
            "real10y": diag("US 10Y Treasury Par Real Yield", real, rerr, rurl),
            "broad_usd": diag("Federal Reserve Nominal Broad Dollar Index", broad, berr, FED_BROAD_DAILY),
            "ig_oas": {"quality": "DATA_REQUIRED", "reason": "FRED endpoint times out from GitHub Actions; no unverified proxy substituted."},
            "hy_oas": {"quality": "DATA_REQUIRED", "reason": "FRED endpoint times out from GitHub Actions; CNN Junk Bond Demand remains available as a separate exact sentiment component."},
            "dxy": {"quality": "DATA_REQUIRED", "reason": "No stable source contract proven; Broad Dollar is kept separate and never relabeled DXY."},
        },
        "guardrail": "Macro WHY is explanatory only and never a V38 trading Gate.",
    }
    passed = all(report["series"][x]["quality"] == "EXACT_OFFICIAL" for x in ["us10y", "real10y", "broad_usd"])
    report["core_direct_official_pass"] = passed
    (args.output / "macro_direct_official_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Rotation Macro Direct Official QA", "", f"Core direct official: {'PASS' if passed else 'FAIL'}", ""]
    for key in ["us10y", "real10y", "broad_usd", "ig_oas", "hy_oas", "dxy"]:
        x = report["series"][key]
        lines.append(f"- {key}: {x['quality']}" + (f" last={x.get('last_value')} asof={x.get('last_date')}" if x.get("last_value") is not None else ""))
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE MACRO DIRECT OFFICIAL QA pass={passed}", flush=True)


if __name__ == "__main__":
    main()

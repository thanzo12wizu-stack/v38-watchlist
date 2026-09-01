from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


def safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    z = pd.concat([pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")], axis=1).dropna()
    if len(z) < 20 or z.iloc[:, 0].nunique() < 2 or z.iloc[:, 1].nunique() < 2:
        return None
    return float(z.iloc[:, 0].corr(z.iloc[:, 1]))


def sign_agreement(a: pd.Series, b: pd.Series, eps: float = 1e-10) -> tuple[float | None, int]:
    z = pd.concat([pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")], axis=1).dropna()
    z = z[(z.iloc[:, 0].abs() > eps) | (z.iloc[:, 1].abs() > eps)]
    if z.empty:
        return None, 0
    sa = np.sign(z.iloc[:, 0].to_numpy(float))
    sb = np.sign(z.iloc[:, 1].to_numpy(float))
    return float((sa == sb).mean()), int(len(z))


def yahoo_shares(ticker: str, start: str, end: str) -> pd.Series:
    s = yf.Ticker(ticker).get_shares_full(start=start, end=end)
    if s is None or len(s) == 0:
        return pd.Series(dtype=float)
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    idx = pd.to_datetime(s.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    s.index = idx.normalize()
    return s.groupby(level=0).last().sort_index()


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate Yahoo historical ETF shares outstanding as a Creation/Redemption fallback against official exact flow")
    ap.add_argument("--official-flows", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_exact_flows.csv"))
    ap.add_argument("--provider-qa", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_provider_qa.csv"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_shareflow_validation"))
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-09-02")
    args = ap.parse_args()

    qa = pd.read_csv(args.provider_qa)
    ok = qa[qa["full_stack_adapter"].astype(str).str.lower().isin({"true", "1", "yes"})]
    tickers = sorted(ok["ticker"].astype(str).str.upper().unique().tolist())
    official = pd.read_csv(args.official_flows, usecols=lambda c: c in {"date", "ticker", "shares_outstanding", "flow_20d_pct_aum"})
    official["date"] = pd.to_datetime(official["date"], errors="coerce").dt.normalize()
    official["ticker"] = official["ticker"].astype(str).str.upper()
    official = official[(official["date"] >= pd.Timestamp(args.start)) & (official["date"] < pd.Timestamp(args.end))]

    rows: list[dict[str, Any]] = []
    aligned_frames: list[pd.DataFrame] = []
    for ticker in tickers:
        off = official[official["ticker"] == ticker].dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").copy()
        rec: dict[str, Any] = {"ticker": ticker, "official_rows": int(len(off))}
        try:
            ys = yahoo_shares(ticker, args.start, args.end)
            rec["yahoo_observations"] = int(len(ys))
            if ys.empty:
                raise RuntimeError("Yahoo shares series empty")
            calendar = off[["date", "shares_outstanding", "flow_20d_pct_aum"]].copy().set_index("date")
            calendar["yahoo_shares_raw"] = ys.reindex(calendar.index)
            calendar["yahoo_shares"] = ys.reindex(calendar.index).ffill()
            first_valid = calendar["yahoo_shares"].first_valid_index()
            if first_valid is not None:
                calendar = calendar.loc[first_valid:].copy()
            calendar["official_shares"] = pd.to_numeric(calendar["shares_outstanding"], errors="coerce")
            calendar["yahoo_share_rel_error"] = (calendar["yahoo_shares"] - calendar["official_shares"]).abs() / calendar["official_shares"].abs()
            calendar["share_cr_20d_pct"] = 100.0 * (calendar["yahoo_shares"] / calendar["yahoo_shares"].shift(20) - 1.0)
            calendar["official_share_cr_20d_pct"] = 100.0 * (calendar["official_shares"] / calendar["official_shares"].shift(20) - 1.0)

            rel = calendar["yahoo_share_rel_error"].replace([np.inf, -np.inf], np.nan).dropna()
            rec["aligned_days"] = int(calendar[["yahoo_shares", "official_shares"]].dropna().shape[0])
            rec["median_share_rel_error"] = None if rel.empty else float(rel.median())
            rec["p95_share_rel_error"] = None if rel.empty else float(rel.quantile(0.95))
            rec["share_cr20_corr_vs_official_shares"] = safe_corr(calendar["share_cr_20d_pct"], calendar["official_share_cr_20d_pct"])
            sa_share, n_share = sign_agreement(calendar["share_cr_20d_pct"], calendar["official_share_cr_20d_pct"])
            rec["share_cr20_sign_agreement_vs_official_shares"] = sa_share
            rec["share_cr20_sign_n"] = n_share
            rec["share_cr20_corr_vs_exact_flow_aum"] = safe_corr(calendar["share_cr_20d_pct"], calendar["flow_20d_pct_aum"])
            sa_flow, n_flow = sign_agreement(calendar["share_cr_20d_pct"], calendar["flow_20d_pct_aum"])
            rec["share_cr20_sign_agreement_vs_exact_flow_aum"] = sa_flow
            rec["flow_sign_n"] = n_flow
            rec["status"] = "MEASURED"
            z = calendar.reset_index()
            z["ticker"] = ticker
            aligned_frames.append(z)
        except Exception as exc:
            rec["status"] = "DATA_REQUIRED"
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    df = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output / "shareflow_validation_by_etf.csv", index=False)
    if aligned_frames:
        aligned = pd.concat(aligned_frames, ignore_index=True)
        aligned.to_csv(args.output / "shareflow_validation_aligned.csv", index=False, date_format="%Y-%m-%d")

    measured = df[df["status"] == "MEASURED"].copy()
    def med(col: str) -> float | None:
        x = pd.to_numeric(measured.get(col), errors="coerce").dropna()
        return None if x.empty else float(x.median())

    decision = "RESEARCH_ONLY"
    if len(measured) >= max(10, int(0.7 * len(tickers))):
        err = med("median_share_rel_error")
        share_sign = med("share_cr20_sign_agreement_vs_official_shares")
        flow_sign = med("share_cr20_sign_agreement_vs_exact_flow_aum")
        flow_corr = med("share_cr20_corr_vs_exact_flow_aum")
        if err is not None and err <= 0.005 and share_sign is not None and share_sign >= 0.95 and flow_sign is not None and flow_sign >= 0.85 and flow_corr is not None and flow_corr >= 0.85:
            decision = "CANDIDATE_FALLBACK_FOR_VALIDATION"
        else:
            decision = "DO_NOT_USE_AS_FLOW_FALLBACK"

    report = {
        "schema": 1,
        "research_only": True,
        "window": {"start": args.start, "end": args.end},
        "official_reference_tickers": len(tickers),
        "measured_tickers": int(len(measured)),
        "decision": decision,
        "median_of_etf_median_share_rel_error": med("median_share_rel_error"),
        "median_share_cr20_sign_agreement_vs_official_shares": med("share_cr20_sign_agreement_vs_official_shares"),
        "median_share_cr20_corr_vs_exact_flow_aum": med("share_cr20_corr_vs_exact_flow_aum"),
        "median_share_cr20_sign_agreement_vs_exact_flow_aum": med("share_cr20_sign_agreement_vs_exact_flow_aum"),
        "guardrails": [
            "This test does not relabel Yahoo data as official Exact Flow.",
            "The candidate metric is Creation/Redemption from shares outstanding; no dollar-volume proxy is used.",
            "Adoption requires measured agreement against official SSGA/iShares shares and Exact Flow, then separate Theme56 state validation.",
        ],
    }
    (args.output / "shareflow_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

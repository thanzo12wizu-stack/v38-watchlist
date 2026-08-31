from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import pitindex

import rotation_distribution_pit_backtest as base
import validate_pioneer_leader as pl


def load_cached_snapshots(path: Path, quality_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = pd.read_csv(path)
    q = pd.read_csv(quality_path)
    s["anchor_date"] = pd.to_datetime(s["asof"]).dt.normalize()
    s["ticker"] = s["ticker"].astype(str)
    s = s[s["sector_etf"].isin(base.SECTORS)].copy()
    q["anchor_date"] = pd.to_datetime(q["asof"]).dt.normalize()
    q = q.rename(columns={"pit_sector_mapping_rate": "mapping_rate"})
    return s[["anchor_date", "ticker", "sector_etf", "gics_sector", "revision_id", "revision_timestamp"]], q


def period_results(events: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    return {period: base.summarize(pev, calendar, seed + i * 10) for i, (period, pev) in enumerate(base.period_frames(events).items())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Cached PIT Distribution validation using pre-audited historical Wikipedia snapshots")
    ap.add_argument("--snapshots", type=Path, required=True)
    ap.add_argument("--snapshot-quality", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--analysis-start", default="2022-04-18")
    ap.add_argument("--analysis-end", default="2026-08-17")
    ap.add_argument("--price-download-start", default="2021-01-01")
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    snapshots, sq = load_cached_snapshots(args.snapshots, args.snapshot_quality)
    pit_end = pd.Timestamp(pitindex.info(index="sp500")["end_date"]).normalize()
    start = pd.Timestamp(args.analysis_start).normalize()
    end = min(pd.Timestamp(args.analysis_end).normalize(), pit_end)
    sector_start = pd.Timestamp(snapshots["anchor_date"].min()).normalize()
    if sq["mapping_rate"].min() < 0.98 or sq["jaccard"].min() < 0.98:
        raise RuntimeError("cached PIT source no longer satisfies 98% quality gate")

    provisional_dates = pd.bdate_range(sector_start, end)
    provisional_membership, _ = base.membership_by_day(provisional_dates, snapshots)
    tickers = sorted({t for groups in provisional_membership.values() for members in groups.values() for t in members})
    requested = tickers + ["SPY", *base.SECTORS]
    ohlcv, download_diag = pl.download_ohlcv(requested, args.price_download_start, str((end + pd.Timedelta(days=70)).date()), args.batch_size)
    trading_dates = ohlcv["close"].index[(ohlcv["close"].index >= sector_start) & (ohlcv["close"].index <= end)]
    membership, map_q = base.membership_by_day(trading_dates, snapshots)
    map_q.to_csv(args.output / "daily_pit_mapping_quality.csv", index=False, date_format="%Y-%m-%d")
    if map_q.empty or map_q["mapping_rate"].min() < 0.98:
        raise RuntimeError(f"daily PIT mapping fails 98% guard: {map_q['mapping_rate'].min() if not map_q.empty else 'empty'}")

    session = requests.Session()
    flows, flow_diag = base.exact_flows(session, pd.Timestamp(args.price_download_start), end)
    flows.to_csv(args.output / "exact_sector_flows.csv", index=False, date_format="%Y-%m-%d")

    report: dict[str, Any] = {
        "schema": 1,
        "research_only": True,
        "pit_membership": "pitindex pinned commit; daily S&P500 membership",
        "pit_sector": "pre-audited Wikipedia revisions, monthly snapshots used only from their as-of date forward (no future fill)",
        "pit_sector_caveat": "GICS changes between snapshots are recognized with up-to-one-month lag; conservative/stale, never look-ahead.",
        "flow_quality": "EXACT_OFFICIAL_SSGA_SHARES_OUTSTANDING_DERIVED",
        "internal": "dynamic PIT equal-weight, five independent components, cross-sectional percentile ranks, median rank",
        "window": {"sector_history_start": str(sector_start.date()), "analysis_start": str(start.date()), "analysis_end": str(end.date()), "price_download_start": args.price_download_start},
        "source_quality": {"monthly_snapshot_min_mapping": float(sq["mapping_rate"].min()), "monthly_snapshot_min_jaccard": float(sq["jaccard"].min()), "daily_mapping_min": float(map_q["mapping_rate"].min()), "download": download_diag, "flow": flow_diag},
        "coverage_levels": {},
        "decision": {},
    }

    grid = [(p, i, f) for p in (65.0, 70.0, 75.0) for i in (45.0, 50.0, 55.0) for f in (0.0, 0.5, 1.0)]
    result_rows: list[dict[str, Any]] = []
    all_events: list[pd.DataFrame] = []
    coverage_rows: list[pd.DataFrame] = []

    for ci, cov in enumerate(base.COVERAGE_LEVELS):
        components, covdiag = base.build_dynamic_components(ohlcv, membership, map_q, cov)
        coverage_rows.append(covdiag)
        panel = base.build_panel(ohlcv, components, flows)
        panel = panel[(panel["date"] >= start) & (panel["date"] <= end)].copy()
        panel.to_csv(args.output / f"distribution_pit_panel_cov{int(cov*100)}.csv", index=False, date_format="%Y-%m-%d")
        calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
        cov_out: dict[str, Any] = {"grid": {}, "ablation": {}}

        for gi, (p, icut, fcut) in enumerate(grid):
            label = f"P{int(p)}_I{int(icut)}_F{fcut:g}"
            ev = base.eventize(panel, base.distribution_mask(panel, p, icut, fcut), label)
            if not ev.empty:
                tagged = ev.copy()
                tagged["coverage_level"] = cov
                tagged["p"] = p
                tagged["i"] = icut
                tagged["flow_cut"] = fcut
                all_events.append(tagged)
            po = period_results(ev, calendar, 10000 + ci * 100000 + gi * 1000)
            cov_out["grid"][label] = po
            for period, summary in po.items():
                for h in base.HORIZONS:
                    hs = summary.get("horizons", {}).get(str(h), {})
                    result_rows.append({"coverage_level": cov, "config": label, "p": p, "i": icut, "flow_cut": fcut, "period": period, "horizon": h, "n": hs.get("n", 0), "mean_excess": hs.get("mean"), "median_excess": hs.get("median"), "negative_rate": hs.get("negative_rate"), "block_ci_lo": (hs.get("block20_ci95") or [None, None])[0], "block_ci_hi": (hs.get("block20_ci95") or [None, None])[1], "sector_ci_lo": (hs.get("sector_cluster_ci95") or [None, None])[0], "sector_ci_hi": (hs.get("sector_cluster_ci95") or [None, None])[1]})

        masks = {"FLOW_OUT_ONLY": panel["flow20_pct_aum"] <= 0, "PRICE_INTERNAL": (panel["price_score"] >= 70) & (panel["internal_score"] < 50), "FULL_DISTRIBUTION": base.distribution_mask(panel, 70, 50, 0)}
        for ai, (label, mask) in enumerate(masks.items()):
            ev = base.eventize(panel, mask, label)
            cov_out["ablation"][label] = period_results(ev, calendar, 700000 + ci * 10000 + ai * 1000)
        report["coverage_levels"][str(cov)] = cov_out

    results = pd.DataFrame(result_rows)
    results.to_csv(args.output / "distribution_pit_grid_results.csv", index=False)
    pd.concat(coverage_rows, ignore_index=True).to_csv(args.output / "distribution_pit_data_coverage.csv", index=False)
    if all_events:
        pd.concat(all_events, ignore_index=True).sort_values(["date", "coverage_level", "config", "sector"]).to_csv(args.output / "distribution_pit_events.csv", index=False, date_format="%Y-%m-%d")

    robust: dict[str, Any] = {}
    pass_all = True
    for cov in base.COVERAGE_LEVELS:
        robust[str(cov)] = {}
        for h in (20, 40):
            sub = results[(results.coverage_level == cov) & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon == h)]
            vals = pd.to_numeric(sub["mean_excess"], errors="coerce").dropna()
            frac_neg = float((vals < 0).mean()) if len(vals) else None
            med = float(vals.median()) if len(vals) else None
            robust[str(cov)][str(h)] = {"configs_with_result": len(vals), "fraction_negative": frac_neg, "median_config_mean_excess": med}
            if frac_neg is None or frac_neg < 0.80:
                pass_all = False

    baseline = results[(results.coverage_level == 0.80) & (results.config == "P70_I50_F0") & (results.period == "CONFIRMATION_2024_PLUS")]
    base_ok = True
    for h in (20, 40):
        r = baseline[baseline.horizon == h]
        if r.empty or pd.isna(r.iloc[0].mean_excess) or float(r.iloc[0].mean_excess) >= 0 or int(r.iloc[0].n) < 10:
            base_ok = False
    survives = bool(pass_all and base_ok)
    report["decision"] = {"robustness": robust, "baseline_cov80": baseline.to_dict("records"), "survives_pit_as_research_distribution_context": survives, "production_adoption": False, "trading_gate": False, "forced_exit": False, "interpretation": "Eligible only as Sector Distribution warning context; never a V38 entry/exit gate." if survives else "Reject Distribution as operational signal under strict PIT robustness rules."}
    (args.output / "distribution_pit_report.json").write_text(json.dumps(base.safe(report), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = ["# Cached PIT Distribution Trap Validation", "", "Research-only. No main/UI/trading-rule changes.", "", f"- Analysis: {start.date()} to {end.date()}", f"- Monthly source mapping min: {sq['mapping_rate'].min():.2%}", f"- Daily carried-forward mapping min: {map_q['mapping_rate'].min():.2%}", f"- Decision: {'SURVIVES AS CONTEXT CANDIDATE' if survives else 'REJECT'}", "", "## Confirmation 2024+ baseline P70 / Internal<50 / Flow<=0", "", "| Coverage | 20D | 40D |", "|---:|---:|---:|"]
    for cov in base.COVERAGE_LEVELS:
        vals = []
        for h in (20, 40):
            r = results[(results.coverage_level == cov) & (results.config == "P70_I50_F0") & (results.period == "CONFIRMATION_2024_PLUS") & (results.horizon == h)]
            vals.append("n/a" if r.empty or pd.isna(r.iloc[0].mean_excess) else f"{100*r.iloc[0].mean_excess:+.2f}% (n={int(r.iloc[0].n)})")
        lines.append(f"| {cov:.0%} | {vals[0]} | {vals[1]} |")
    lines += ["", "Guardrails: exact official Fund Flow; no volume-flow substitution; PIT membership; historical GICS only after its snapshot date; 20d Sector cooldown; all 27 thresholds retained; context only."]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DONE CACHED_PIT_DISTRIBUTION survives={survives} rows={len(results)}", flush=True)


if __name__ == "__main__":
    main()

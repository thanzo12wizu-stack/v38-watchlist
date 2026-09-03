from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_five_year_leader_capture as lc
import audit_leader_factor_horizon_discovery as disc


def pack(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"n": 0}
    return {
        "n": int(len(df)),
        "hit12_n": int(df["hit12"].sum()),
        "hit12_rate": float(df["hit12"].mean()),
        "early12_n": int(df["early12"].sum()),
        "early12_rate_all": float(df["early12"].mean()),
        "early12_share_hits": float(df["early12"].sum() / max(1, int(df["hit12"].sum()))),
        "hit20_n": int(df["hit20"].sum()),
        "hit20_rate": float(df["hit20"].mean()),
        "early20_n": int(df["early20"].sum()),
        "early20_rate_all": float(df["early20"].mean()),
        "early20_share_hits": float(df["early20"].sum() / max(1, int(df["hit20"].sum()))),
        "median_first12_progress": float(pd.to_numeric(df.loc[df["hit12"], "first12_progress"], errors="coerce").median()) if bool(df["hit12"].any()) else None,
    }


def period_pack(df: pd.DataFrame) -> dict[str, Any]:
    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    return {
        "all": pack(df),
        "dev_2021_2023": pack(df.loc[years.between(2021, 2023)]),
        "oos_2024_2026": pack(df.loc[years.between(2024, 2026)]),
        "by_year": {str(k): pack(g) for k, g in df.groupby("period", sort=True)},
    }


def day_masks(meta: dict[str, Any], idx: pd.DatetimeIndex) -> dict[str, pd.Series]:
    nq_only = pd.Series(False, index=idx)
    breadth_only = pd.Series(False, index=idx)
    for d0 in idx:
        d = pd.Timestamp(d0)
        color = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        b = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        nq_only.at[d] = color in ("Blue", "Green")
        breadth_only.at[d] = base.breadth_bucket(b) >= 1
    return {
        "CURRENT_NQ_AND_BREADTH": nq_only & breadth_only,
        "NQ_ONLY": nq_only,
        "BREADTH_ONLY": breadth_only,
        "ALL_DAYS": pd.Series(True, index=idx),
    }


def structure_specific_rs63_high(close: pd.DataFrame, rs63: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the high-proximity percentile inside each structural population.
    Important: do not reuse HIGH63 precomputed under TREND_FULL, or structure ablation is impossible.
    """
    prior63 = close.shift(1).rolling(63, min_periods=50).max()
    high_raw = close / prior63
    high_pct = (high_raw.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)
    return (0.75 * rs63 + 0.25 * high_pct).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--leader-start", default="2021-01-04")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    idx = meta["analysis_idx"]
    close = matrices["close"]

    print("FREEZE leaders", flush=True)
    annual = lc.build_annual_leaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    annual10 = annual.loc[pd.to_numeric(annual["rank"], errors="coerce") <= 10].copy()
    rolling = lc.build_rolling_superleaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    annual.to_csv(out / "annual_leaders_frozen.csv", index=False)
    rolling.to_csv(out / "rolling_126_leaders_frozen.csv", index=False)

    print("BUILD common/factors", flush=True)
    common = disc.build_common(root, matrices)
    rs = disc.build_rs(close, common["BASE_POOL"])
    theme = disc.theme_frame(peer_ctx, close)
    comp = disc.build_factor_components(close, common, rs, theme)
    specs = disc.factor_specs(rs, comp)
    factors = {
        "RS21": specs["RS21"],
        "RS63_HIGH": specs["RS63_HIGH"],
        "RS63_ACCEL": specs["RS63_ACCEL"],
        "RS63_P20_THEME": specs["RS63_P20_THEME"],
        "CURRENT_189_THEME": specs["CURRENT_189_THEME"],
    }
    days = day_masks(meta, idx)

    result: dict[str, Any] = {
        "status": "LEADER_CAPTURE_BOTTLENECK_AUDIT_V2",
        "analysis_window": {"start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start, "downloaded": int(meta["downloaded"])},
        "design": {
            "purpose": "Decompose early-leader recognition loss across market-mode gating and structural ranking population before changing the portfolio.",
            "primary": "Annual Top10 leader recognized in Top12 while <=20% through hindsight start-to-peak run.",
            "day_masks": ["CURRENT_NQ_AND_BREADTH", "NQ_ONLY", "BREADTH_ONLY", "ALL_DAYS"],
            "ranking_masks": ["TREND_FULL", "ABOVE200", "SMA50_GT_200", "BASE_POOL"],
            "structural_fix": "HIGH63 percentile and RS63_HIGH score are rebuilt separately inside each structural population; no TREND_FULL-precomputed high component is reused.",
            "no_portfolio_change": True,
        },
        "factor_day_mask": {},
        "rs63_high_structure_mask": {},
    }

    print("AUDIT factor x market day mask", flush=True)
    for fname, fmat in factors.items():
        rankmat = disc.top_rank_matrix(fmat, common["TREND_FULL"], maxk=20)
        result["factor_day_mask"][fname] = {}
        for dname, dmask in days.items():
            _, adf = disc.eval_factor_on_leaders(fname, rankmat, annual10, close, idx, dmask)
            _, rdf = disc.eval_factor_on_leaders(fname, rankmat, rolling, close, idx, dmask)
            adf.to_csv(out / f"annual10_{fname}_{dname}.csv", index=False)
            result["factor_day_mask"][fname][dname] = {"annual_top10": period_pack(adf), "rolling126": period_pack(rdf)}

    print("AUDIT RS63_HIGH x structural population", flush=True)
    for mname in ("TREND_FULL", "ABOVE200", "SMA50_GT_200", "BASE_POOL"):
        fmat = structure_specific_rs63_high(close, rs[63], common[mname])
        rankmat = disc.top_rank_matrix(fmat, common[mname], maxk=20)
        result["rs63_high_structure_mask"][mname] = {}
        for dname, dmask in days.items():
            _, adf = disc.eval_factor_on_leaders("RS63_HIGH", rankmat, annual10, close, idx, dmask)
            _, rdf = disc.eval_factor_on_leaders("RS63_HIGH", rankmat, rolling, close, idx, dmask)
            adf.to_csv(out / f"annual10_RS63_HIGH_STRUCT_{mname}_{dname}.csv", index=False)
            result["rs63_high_structure_mask"][mname][dname] = {"annual_top10": period_pack(adf), "rolling126": period_pack(rdf)}

    p = out / "summary_leader_capture_bottlenecks.json"
    p.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADER_CAPTURE_BOTTLENECK_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADER_CAPTURE_BOTTLENECK_JSON ===", flush=True)


if __name__ == "__main__":
    main()

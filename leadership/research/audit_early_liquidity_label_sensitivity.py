from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_five_year_leader_capture as lc
import audit_leader_factor_horizon_discovery as disc


TOPKS = (3, 5, 10, 20)
CANDIDATE_DDV_LEVELS = (10_000_000.0, 20_000_000.0, 30_000_000.0, 40_000_000.0, 50_000_000.0, 75_000_000.0, 100_000_000.0)
LABEL_DDV_LEVELS = (0.0, 10_000_000.0, 20_000_000.0, 50_000_000.0)
DEV_YEARS = range(2016, 2021)
OOS_YEARS = range(2021, 2026)
ANNUAL_TOP_N = 20
ANNUAL_MIN_RETURN = 0.40


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def build_annual_leaders_floor(
    matrices: dict[str, pd.DataFrame],
    leader_start: pd.Timestamp,
    analysis_end: pd.Timestamp,
    ddv_floor: float,
) -> pd.DataFrame:
    """Exact annual-leader construction used by the legacy audit, with DDV floor parameterized."""
    close = matrices["close"]
    dvol = matrices["dvol"]
    rows: list[dict[str, Any]] = []
    for year in range(leader_start.year, analysis_end.year + 1):
        p0 = max(leader_start, pd.Timestamp(f"{year}-01-01"))
        p1 = min(analysis_end, pd.Timestamp(f"{year}-12-31"))
        dates = close.index[(close.index >= p0) & (close.index <= p1)]
        if len(dates) < 40:
            continue
        first, last, cov = lc.period_first_last(close, dates)
        period_ret = last / first - 1.0
        min_cov = max(40, int(math.floor(len(dates) * 0.80)))
        early_dates = dates[: min(20, len(dates))]
        early_dvol = dvol.reindex(early_dates).median(axis=0, skipna=True)
        liquid = early_dvol.notna() if ddv_floor <= 0 else (early_dvol >= ddv_floor)
        valid = (
            first.notna()
            & last.notna()
            & (first >= 5.0)
            & (cov >= min_cov)
            & liquid
            & period_ret.notna()
            & (period_ret >= ANNUAL_MIN_RETURN)
        )
        ranked = period_ret.where(valid).dropna().sort_values(ascending=False).head(ANNUAL_TOP_N)
        for rank0, (sym, r) in enumerate(ranked.items(), start=1):
            s = close.loc[dates, sym].dropna()
            peak_date = pd.Timestamp(s.idxmax())
            peak_price = float(s.loc[peak_date])
            start_date = pd.Timestamp(s.index[0])
            start_price = float(s.iloc[0])
            rows.append(
                {
                    "leader_type": f"ANNUAL_LABEL_DDV{int(ddv_floor / 1_000_000)}",
                    "label_ddv_floor": float(ddv_floor),
                    "period": f"{year}" if p1.month == 12 else f"{year}YTD",
                    "rank": rank0,
                    "symbol": str(sym),
                    "start_date": start_date,
                    "end_date": p1,
                    "peak_date": peak_date,
                    "start_price": start_price,
                    "period_end_price": float(s.iloc[-1]),
                    "peak_price": peak_price,
                    "period_return": float(r),
                    "peak_return": peak_price / start_price - 1.0,
                    "early_dvol": float(early_dvol.loc[sym]) if pd.notna(early_dvol.loc[sym]) else np.nan,
                    "coverage_sessions": int(cov.loc[sym]),
                    "period_sessions": int(len(dates)),
                }
            )
    return pd.DataFrame(rows)


def build_base_score(
    close: pd.DataFrame,
    dvol: pd.DataFrame,
    base_pool: pd.DataFrame,
    rs: dict[int, pd.DataFrame],
    ddv_floor: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Freeze the existing BASE early score; only candidate liquidity changes."""
    radar = base_pool & (dvol >= ddv_floor) & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, radar)
    acc10 = pct(rs[21] - rs[21].shift(10), radar)
    rs21 = rs[21].where(radar)
    score = (0.50 * rs21.fillna(50.0) + 0.25 * high63.fillna(50.0) + 0.25 * acc10.fillna(50.0)).astype(np.float32)
    return radar, score


def rank_matrix(score: pd.DataFrame, radar: pd.DataFrame) -> np.ndarray:
    return disc.top_rank_matrix(score, radar, maxk=max(TOPKS))


def evaluate_leaders(
    ranks: np.ndarray,
    radar: pd.DataFrame,
    leaders: pd.DataFrame,
    close: pd.DataFrame,
) -> dict[str, Any]:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_pos = {str(s): i for i, s in enumerate(close.columns)}
    rows: list[dict[str, Any]] = []

    for _, rr in leaders.iterrows():
        rec = dict(rr)
        sym = str(rr["symbol"])
        si = stock_pos.get(sym)
        start = pd.Timestamp(rr["start_date"])
        peak = pd.Timestamp(rr["peak_date"])
        sp = float(rr["start_price"])
        dates = close.index[(close.index >= start) & (close.index <= peak)]
        rec["radar_found"] = False
        rec["first_radar_runup"] = np.nan
        for k in TOPKS:
            rec[f"hit{k}"] = False
            rec[f"first{k}_runup"] = np.nan
            rec[f"first{k}_le30"] = False
            rec[f"first{k}_le50"] = False

        if si is not None:
            for d0 in dates:
                d = pd.Timestamp(d0)
                if bool(radar.at[d, sym]):
                    rec["radar_found"] = True
                    rec["first_radar_runup"] = float(close.at[d, sym] / sp - 1.0)
                    break
            for k in TOPKS:
                for d0 in dates:
                    d = pd.Timestamp(d0)
                    di = date_pos[d]
                    if int(ranks[di, si]) <= k:
                        runup = float(close.at[d, sym] / sp - 1.0)
                        rec[f"hit{k}"] = True
                        rec[f"first{k}_runup"] = runup
                        rec[f"first{k}_le30"] = bool(runup <= 0.30 + 1e-12)
                        rec[f"first{k}_le50"] = bool(runup <= 0.50 + 1e-12)
                        break
        rows.append(rec)

    df = pd.DataFrame(rows)

    def pack(z: pd.DataFrame) -> dict[str, Any]:
        if z.empty:
            return {"n": 0}
        out: dict[str, Any] = {"n": int(len(z))}
        rf = z["radar_found"].astype(bool)
        ru = pd.to_numeric(z["first_radar_runup"], errors="coerce")
        out["radar_found_rate"] = float(rf.mean())
        out["radar_le30_rate"] = float((ru <= 0.30).mean())
        out["radar_le50_rate"] = float((ru <= 0.50).mean())
        for k in TOPKS:
            hit = z[f"hit{k}"].astype(bool)
            run = pd.to_numeric(z.loc[hit, f"first{k}_runup"], errors="coerce")
            out[f"top{k}_hit_rate"] = float(hit.mean())
            out[f"top{k}_le30_rate"] = float(z[f"first{k}_le30"].astype(bool).mean())
            out[f"top{k}_le50_rate"] = float(z[f"first{k}_le50"].astype(bool).mean())
            out[f"top{k}_median_first_runup"] = float(run.median()) if run.notna().any() else None
        return out

    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    return {
        "all": pack(df),
        "dev_2016_2020": pack(df.loc[years.isin(list(DEV_YEARS))]),
        "oos_2021_2025": pack(df.loc[years.isin(list(OOS_YEARS))]),
        "by_year": {str(int(y)): pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }


def event_quality(
    ranks: np.ndarray,
    close: pd.DataFrame,
    base_pool: pd.DataFrame,
    k: int = 5,
    cooldown: int = 20,
) -> dict[str, Any]:
    """Independent forward label: exact 126-session +80% and top-2% cross-sectional return."""
    idx = close.index
    f126 = close.shift(-126) / close - 1.0
    f126_pct = f126.where(base_pool).rank(axis=1, pct=True, method="average") * 100.0
    rows: list[dict[str, Any]] = []
    last: dict[str, int] = {}
    for i, d0 in enumerate(idx):
        selected = np.flatnonzero(ranks[i] <= k)
        for j in selected:
            sym = str(close.columns[j])
            if i - last.get(sym, -10_000) < cooldown:
                continue
            last[sym] = i
            p0 = float(close.iat[i, j]) if pd.notna(close.iat[i, j]) else np.nan
            rec: dict[str, Any] = {"date": pd.Timestamp(d0), "year": int(pd.Timestamp(d0).year), "symbol": sym}
            for h in (21, 63, 126):
                jj = i + h
                p1 = float(close.iat[jj, j]) if jj < len(idx) and pd.notna(close.iat[jj, j]) else np.nan
                rec[f"ret{h}"] = p1 / p0 - 1.0 if np.isfinite(p0) and p0 > 0 and np.isfinite(p1) else np.nan
            fr = float(f126.iat[i, j]) if pd.notna(f126.iat[i, j]) else np.nan
            fp = float(f126_pct.iat[i, j]) if pd.notna(f126_pct.iat[i, j]) else np.nan
            rec["future126_superleader"] = bool(fr >= 0.80 and fp >= 98.0) if np.isfinite(fr) and np.isfinite(fp) else np.nan
            rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0}

    def pack(z: pd.DataFrame) -> dict[str, Any]:
        ans: dict[str, Any] = {"n": int(len(z)), "symbols": int(z["symbol"].nunique())}
        for h in (21, 63, 126):
            x = pd.to_numeric(z[f"ret{h}"], errors="coerce").dropna()
            ans[f"ret{h}_n"] = int(len(x))
            ans[f"ret{h}_median"] = float(x.median()) if len(x) else None
            ans[f"ret{h}_positive"] = float((x > 0).mean()) if len(x) else None
            ans[f"ret{h}_gt50"] = float((x > 0.50).mean()) if len(x) else None
        s = z["future126_superleader"].dropna()
        ans["future126_superleader_n"] = int(len(s))
        ans["future126_superleader_rate"] = float(s.astype(bool).mean()) if len(s) else None
        return ans

    return {
        "all": pack(df),
        "dev_2016_2020": pack(df.loc[df["year"].isin(list(DEV_YEARS))]),
        "oos_2021_2025": pack(df.loc[df["year"].isin(list(OOS_YEARS))]),
        "by_year": {str(int(y)): pack(z) for y, z in df.groupby("year")},
        "events_per_year": {str(int(y)): int(n) for y, n in df.groupby("year").size().items()},
    }


def label_overlap(a: pd.DataFrame, b: pd.DataFrame) -> dict[str, Any]:
    ka = set(zip(a["period"].astype(str), a["symbol"].astype(str))) if not a.empty else set()
    kb = set(zip(b["period"].astype(str), b["symbol"].astype(str))) if not b.empty else set()
    union = ka | kb
    return {
        "a_n": int(len(ka)),
        "b_n": int(len(kb)),
        "intersection": int(len(ka & kb)),
        "jaccard": float(len(ka & kb) / len(union)) if union else None,
    }


def robust_dev_table(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ckey, item in result["candidate_ddv"].items():
        t30, t550 = [], []
        for lkey in result["label_sets"]:
            d = item["annual_labels"][lkey]["dev_2016_2020"]
            t30.append(float(d["top3_le30_rate"]))
            t550.append(float(d["top5_le50_rate"]))
        q = item["top5_event_quality"]["dev_2016_2020"]
        rows.append(
            {
                "candidate": ckey,
                "top3_le30_worst": float(min(t30)),
                "top3_le30_avg": float(np.mean(t30)),
                "top5_le50_worst": float(min(t550)),
                "top5_le50_avg": float(np.mean(t550)),
                "future126_superleader_rate": q.get("future126_superleader_rate"),
                "ret126_median": q.get("ret126_median"),
                "events": q.get("n"),
            }
        )
    rows.sort(
        key=lambda r: (
            r["top3_le30_worst"],
            r["top3_le30_avg"],
            r["top5_le50_worst"],
            r["top5_le50_avg"],
            r["future126_superleader_rate"] if r["future126_superleader_rate"] is not None else -1.0,
        ),
        reverse=True,
    )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2025-12-31")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    close = matrices["close"]
    common = disc.build_common(root, matrices)
    rs = disc.build_rs(close, common["BASE_POOL"])

    result: dict[str, Any] = {
        "status": "EARLY_LIQUIDITY_LABEL_SENSITIVITY_AUDIT",
        "design": {
            "purpose": "Test whether apparent DDV50 early-capture improvement survives when target-label liquidity is independent of candidate liquidity.",
            "score": "Frozen BASE only: 50% RS21 + 25% 63d-high proximity percentile + 25% RS21 10-session acceleration percentile.",
            "radar": "BASE_POOL plus candidate daily DDV floor plus ANY(RS21,RS42,RS63)>=85; no Full Eligibility; no market gate.",
            "candidate_ddv_levels": list(CANDIDATE_DDV_LEVELS),
            "annual_label_ddv_levels": list(LABEL_DDV_LEVELS),
            "annual_label": "Per-calendar-year Top20 by year-end return after price>=5, >=80% coverage, return>=40%; evaluation uses frozen Top5. Only the first-20-session median DDV floor changes.",
            "rolling_quality_label": "Top5 candidate event is a forward superleader if exact +126-session return>=80% and cross-sectional forward-return percentile>=98.",
            "selection": "Candidate DDV robust ordering is frozen from 2016-2020 using worst/average capture across all annual label floors. 2021-2025 is robustness only because DDV50 OOS has already been inspected in prior audit.",
            "diagnostic_fix": "No truncated Top20 first-radar-rank diagnostic is used; only direct Radar membership and TopK ranks are evaluated.",
            "no_portfolio_change": True,
            "no_main_change": True,
        },
        "coverage": {"downloaded": int(meta["downloaded"]), "sessions": int(len(close)), "symbols": int(len(close.columns))},
        "label_sets": {},
        "label_overlap": {},
        "legacy50_reproduction": {},
        "candidate_ddv": {},
        "dev_robust_order": [],
        "dev_selected": None,
    }

    print("BUILD independent annual label sets", flush=True)
    label_frames: dict[str, pd.DataFrame] = {}
    for floor in LABEL_DDV_LEVELS:
        key = f"LABEL_DDV{int(floor / 1_000_000)}"
        all20 = build_annual_leaders_floor(matrices, pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end), floor)
        top5 = all20.loc[pd.to_numeric(all20["rank"], errors="coerce") <= 5].copy()
        label_frames[key] = top5
        top5.to_csv(out / f"annual_top5_{key}.csv", index=False)
        result["label_sets"][key] = {
            "n": int(len(top5)),
            "symbols": int(top5["symbol"].nunique()) if len(top5) else 0,
            "median_early_dvol": float(pd.to_numeric(top5["early_dvol"], errors="coerce").median()) if len(top5) else None,
            "by_year_n": {str(int(y)): int(n) for y, n in pd.to_numeric(top5["period"].astype(str).str[:4], errors="coerce").value_counts().sort_index().items()} if len(top5) else {},
        }

    keys = list(label_frames)
    for a in keys:
        result["label_overlap"][a] = {}
        for b in keys:
            result["label_overlap"][a][b] = label_overlap(label_frames[a], label_frames[b])

    legacy = lc.build_annual_leaders(matrices, pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end))
    legacy5 = legacy.loc[pd.to_numeric(legacy["rank"], errors="coerce") <= 5].copy()
    ours50 = label_frames["LABEL_DDV50"]
    legacy_keys = list(zip(legacy5["period"].astype(str), legacy5["rank"].astype(int), legacy5["symbol"].astype(str)))
    ours_keys = list(zip(ours50["period"].astype(str), ours50["rank"].astype(int), ours50["symbol"].astype(str)))
    result["legacy50_reproduction"] = {
        "legacy_n": int(len(legacy5)),
        "parameterized_n": int(len(ours50)),
        "identity_match": bool(legacy_keys == ours_keys),
    }
    if legacy_keys != ours_keys:
        raise RuntimeError("Parameterized LABEL_DDV50 does not reproduce legacy annual Top5 labels exactly")

    print("TEST candidate DDV levels with frozen BASE score", flush=True)
    for floor in CANDIDATE_DDV_LEVELS:
        ckey = f"CAND_DDV{int(floor / 1_000_000)}"
        print(f"RANK {ckey}", flush=True)
        radar, score = build_base_score(close, matrices["dvol"], common["BASE_POOL"], rs, floor)
        ranks = rank_matrix(score, radar)
        item: dict[str, Any] = {
            "candidate_ddv_floor": float(floor),
            "annual_labels": {},
            "top5_event_quality": event_quality(ranks, close, common["BASE_POOL"], k=5, cooldown=20),
        }
        for lkey, leaders in label_frames.items():
            item["annual_labels"][lkey] = evaluate_leaders(ranks, radar, leaders, close)
        result["candidate_ddv"][ckey] = item

    robust = robust_dev_table(result)
    result["dev_robust_order"] = robust
    result["dev_selected"] = robust[0]["candidate"] if robust else None

    p = out / "summary_early_liquidity_label_sensitivity.json"
    p.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_LIQUIDITY_LABEL_SENSITIVITY_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_LIQUIDITY_LABEL_SENSITIVITY_JSON ===", flush=True)


if __name__ == "__main__":
    main()

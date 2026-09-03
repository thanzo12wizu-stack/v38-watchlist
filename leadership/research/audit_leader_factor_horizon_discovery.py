from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_five_year_leader_capture as lc

HORIZONS = (21, 42, 63, 126, 189, 252)
TOPKS = (12, 20)


def safe(v: Any) -> Any:
    return base.safe(v)


def px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, default=np.nan) -> float:
    try:
        x = float(frame.at[d, sym])
        return x if np.isfinite(x) else default
    except Exception:
        return default


def freeze_labels(out: Path, annual: pd.DataFrame, rolling: pd.DataFrame) -> dict[str, Any]:
    a = annual.copy()
    r = rolling.copy()
    a["evaluation_set"] = "ANNUAL_LIQUID"
    r["evaluation_set"] = "ROLLING_126_SUPERLEADER"
    cols = sorted(set(a.columns) | set(r.columns))
    frozen = pd.concat([a.reindex(columns=cols), r.reindex(columns=cols)], ignore_index=True)
    sort_cols = [c for c in ["evaluation_set", "period", "rank", "symbol", "start_date"] if c in frozen.columns]
    frozen = frozen.sort_values(sort_cols, na_position="last").reset_index(drop=True)
    path = out / "leader_labels_frozen.csv"
    frozen.to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "leader_labels_sha256.txt").write_text(digest + "\n", encoding="utf-8")
    return {"rows": int(len(frozen)), "sha256": digest}


def market_tradable(meta: dict[str, Any], idx: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(False, index=idx)
    for d0 in idx:
        d = pd.Timestamp(d0)
        color = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        b = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        out.at[d] = bool(color in ("Blue", "Green") and base.breadth_bucket(b) >= 1)
    return out


def build_common(root: Path, matrices: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close = matrices["close"]
    dvol = matrices["dvol"]
    sma50, sma200 = matrices["sma50"], matrices["sma200"]
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    bio = base.read_structural_bio_exclusions(root, list(close.columns))
    if bio:
        cols = [s for s in bio if s in base_pool.columns]
        if cols:
            base_pool.loc[:, cols] = False
    above200 = base_pool & (close > sma200)
    trend_cross = base_pool & (sma50 > sma200)
    trend_full = above200 & (sma50 > sma200)
    above50 = base_pool & (close > sma50)
    return {
        "BASE_POOL": base_pool,
        "ABOVE50": above50,
        "ABOVE200": above200,
        "SMA50_GT_200": trend_cross,
        "TREND_FULL": trend_full,
    }


def build_rs(close: pd.DataFrame, base_pool: pd.DataFrame) -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for h in HORIZONS:
        print(f"BUILD RS{h}", flush=True)
        ret = close / close.shift(h) - 1.0
        rs = ret.where(base_pool & ret.notna()).rank(axis=1, pct=True, method="average") * 100.0
        out[h] = rs.astype(np.float32)
    return out


def theme_frame(peer_ctx: dict[str, Any], close: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        np.asarray(peer_ctx["best_score"], dtype=np.float32),
        index=close.index,
        columns=close.columns,
    )


def percentile(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def build_factor_components(close, common, rs, theme):
    trend = common["TREND_FULL"]
    ret20 = close / close.shift(20) - 1.0
    p20 = percentile(ret20, trend)
    acc63 = percentile(rs[63] - rs[63].shift(20), trend)
    acc126 = percentile(rs[126] - rs[126].shift(20), trend)
    prior63 = close.shift(1).rolling(63, min_periods=50).max()
    high63 = percentile(close / prior63, trend)
    prior126 = close.shift(1).rolling(126, min_periods=90).max()
    high126 = percentile(close / prior126, trend)
    return {
        "P20": p20,
        "ACC63": acc63,
        "ACC126": acc126,
        "HIGH63": high63,
        "HIGH126": high126,
        "THEME": theme.astype(np.float32),
    }


def factor_specs(rs, comp):
    blend63126 = ((rs[63] + rs[126]) / 2.0).astype(np.float32)
    blend63189 = ((rs[63] + rs[189]) / 2.0).astype(np.float32)
    blend126189 = ((rs[126] + rs[189]) / 2.0).astype(np.float32)
    blend3 = ((rs[63] + rs[126] + rs[189]) / 3.0).astype(np.float32)
    fast = (0.35 * rs[42] + 0.35 * rs[63] + 0.30 * rs[126]).astype(np.float32)
    return {
        "RS21": rs[21],
        "RS42": rs[42],
        "RS63": rs[63],
        "RS126": rs[126],
        "RS189": rs[189],
        "RS252": rs[252],
        "BLEND_63_126": blend63126,
        "BLEND_63_189": blend63189,
        "BLEND_126_189": blend126189,
        "BLEND_63_126_189": blend3,
        "FAST_42_63_126": fast,
        "RS63_ACCEL": (0.75 * rs[63] + 0.25 * comp["ACC63"]).astype(np.float32),
        "RS126_ACCEL": (0.75 * rs[126] + 0.25 * comp["ACC126"]).astype(np.float32),
        "RS63_HIGH": (0.75 * rs[63] + 0.25 * comp["HIGH63"]).astype(np.float32),
        "RS126_HIGH": (0.75 * rs[126] + 0.25 * comp["HIGH126"]).astype(np.float32),
        "CURRENT_189_THEME": (0.70 * rs[189] + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
        "RS63_THEME": (0.70 * rs[63] + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
        "RS126_THEME": (0.70 * rs[126] + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
        "BLEND63126_THEME": (0.70 * blend63126 + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
        "BLEND3_THEME": (0.70 * blend3 + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
        "RS63_P20_THEME": (0.50 * rs[63] + 0.20 * comp["P20"] + 0.30 * comp["THEME"].fillna(50.0)).astype(np.float32),
    }


def top_rank_matrix(score: pd.DataFrame, mask: pd.DataFrame, maxk: int = 20) -> np.ndarray:
    arr = score.to_numpy(dtype=np.float32, copy=False)
    m = mask.to_numpy(dtype=bool, copy=False)
    nrow, ncol = arr.shape
    out = np.full((nrow, ncol), 32767, dtype=np.int16)
    for i in range(nrow):
        valid = m[i] & np.isfinite(arr[i])
        idx = np.flatnonzero(valid)
        if idx.size == 0:
            continue
        k = min(maxk, idx.size)
        vals = arr[i, idx]
        if idx.size > k:
            part = np.argpartition(vals, -k)[-k:]
            cand = idx[part]
        else:
            cand = idx
        order = cand[np.argsort(arr[i, cand], kind="mergesort")[::-1]]
        for r, j in enumerate(order[:k], start=1):
            out[i, j] = r
    return out


def progress_at(close: pd.DataFrame, d: pd.Timestamp, row: pd.Series) -> float:
    sym = str(row["symbol"])
    p = px(close, d, sym)
    sp = float(row["start_price"])
    pp = float(row["peak_price"])
    total = pp / sp - 1.0
    if not np.isfinite(p) or total <= 0:
        return np.nan
    return float((p / sp - 1.0) / total)


def episode_window(row: pd.Series, close: pd.DataFrame, analysis_idx: pd.DatetimeIndex, tradable: pd.Series, early_cut=0.20):
    sym = str(row["symbol"])
    start = pd.Timestamp(row["start_date"])
    peak = pd.Timestamp(row["peak_date"])
    dates = analysis_idx[(analysis_idx >= start) & (analysis_idx <= peak)]
    dates = pd.DatetimeIndex([d for d in dates if bool(tradable.get(pd.Timestamp(d), False))])
    if len(dates) == 0 or sym not in close.columns:
        return dates, pd.DatetimeIndex([])
    early = []
    for d0 in dates:
        d = pd.Timestamp(d0)
        pr = progress_at(close, d, row)
        if np.isfinite(pr) and pr <= early_cut + 1e-12:
            early.append(d)
        elif early:
            break
    return dates, pd.DatetimeIndex(early)


def eval_factor_on_leaders(
    name: str,
    rankmat: np.ndarray,
    leaders: pd.DataFrame,
    close: pd.DataFrame,
    analysis_idx: pd.DatetimeIndex,
    tradable: pd.Series,
) -> tuple[dict[str, Any], pd.DataFrame]:
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_pos = {str(s): i for i, s in enumerate(close.columns)}
    rows = []
    for _, rr in leaders.iterrows():
        row = rr.copy()
        sym = str(row["symbol"])
        si = stock_pos.get(sym)
        dates, early = episode_window(row, close, analysis_idx, tradable)
        rec = dict(row)
        rec.update({
            "factor": name,
            "hit12": False, "hit20": False,
            "early12": False, "early20": False,
            "first12_date": pd.NaT, "first12_progress": np.nan,
            "first20_date": pd.NaT, "first20_progress": np.nan,
        })
        if si is not None:
            early_set = set(pd.Timestamp(d) for d in early)
            for k in TOPKS:
                found = None
                for d0 in dates:
                    d = pd.Timestamp(d0)
                    di = date_pos.get(d)
                    if di is None:
                        continue
                    if int(rankmat[di, si]) <= k:
                        found = d
                        break
                if found is not None:
                    rec[f"hit{k}"] = True
                    rec[f"first{k}_date"] = found
                    rec[f"first{k}_progress"] = progress_at(close, found, row)
                    rec[f"early{k}"] = found in early_set
        rows.append(rec)
    df = pd.DataFrame(rows)

    def pack(z: pd.DataFrame) -> dict[str, Any]:
        if z.empty:
            return {"n": 0}
        p12 = pd.to_numeric(z.loc[z["hit12"], "first12_progress"], errors="coerce")
        p20 = pd.to_numeric(z.loc[z["hit20"], "first20_progress"], errors="coerce")
        return {
            "n": int(len(z)),
            "hit12_n": int(z["hit12"].sum()),
            "hit12_rate": float(z["hit12"].mean()),
            "early12_n": int(z["early12"].sum()),
            "early12_rate_all": float(z["early12"].mean()),
            "early12_share_hits": float(z["early12"].sum() / max(1, z["hit12"].sum())),
            "median_first12_progress": float(p12.median()) if p12.notna().any() else None,
            "hit20_n": int(z["hit20"].sum()),
            "hit20_rate": float(z["hit20"].mean()),
            "early20_n": int(z["early20"].sum()),
            "early20_rate_all": float(z["early20"].mean()),
            "median_first20_progress": float(p20.median()) if p20.notna().any() else None,
        }

    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    summary = {
        "all": pack(df),
        "dev_2021_2023": pack(df.loc[years.between(2021, 2023)]),
        "oos_2024_2026": pack(df.loc[years.between(2024, 2026)]),
        "by_year": {str(int(y)): pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }
    return summary, df


def gate_specs(common: dict[str, pd.DataFrame], rs: dict[int, pd.DataFrame]):
    trend = common["TREND_FULL"]
    b63126 = (rs[63] + rs[126]) / 2.0
    return {
        "BASE_POOL": common["BASE_POOL"],
        "ABOVE200": common["ABOVE200"],
        "SMA50_GT_200": common["SMA50_GT_200"],
        "TREND_FULL": trend,
        "TREND_RS63_80": trend & (rs[63] >= 80),
        "TREND_RS63_85": trend & (rs[63] >= 85),
        "TREND_RS63_90": trend & (rs[63] >= 90),
        "TREND_RS126_80": trend & (rs[126] >= 80),
        "TREND_RS126_85": trend & (rs[126] >= 85),
        "TREND_RS126_90": trend & (rs[126] >= 90),
        "TREND_RS189_80": trend & (rs[189] >= 80),
        "TREND_RS189_85": trend & (rs[189] >= 85),
        "TREND_RS189_90": trend & (rs[189] >= 90),
        "TREND_RS252_85": trend & (rs[252] >= 85),
        "CURRENT_RS63_189_85": trend & (rs[63] >= 85) & (rs[189] >= 85),
        "TREND_RS63_126_85": trend & (rs[63] >= 85) & (rs[126] >= 85),
        "TREND_RS126_189_85": trend & (rs[126] >= 85) & (rs[189] >= 85),
        "TREND_ANY2_63_126_189_85": trend & (((rs[63] >= 85).astype(int) + (rs[126] >= 85).astype(int) + (rs[189] >= 85).astype(int)) >= 2),
        "TREND_BLEND63_126_85": trend & (b63126 >= 85),
    }


def eval_gate_on_leaders(name, gate, leaders, close, analysis_idx, tradable):
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_pos = {str(s): i for i, s in enumerate(close.columns)}
    arr = gate.to_numpy(dtype=bool, copy=False)
    rows = []
    for _, rr in leaders.iterrows():
        row = rr.copy()
        sym = str(row["symbol"])
        si = stock_pos.get(sym)
        dates, early = episode_window(row, close, analysis_idx, tradable)
        early_set = set(pd.Timestamp(d) for d in early)
        first = None
        if si is not None:
            for d0 in dates:
                d = pd.Timestamp(d0)
                di = date_pos.get(d)
                if di is not None and bool(arr[di, si]):
                    first = d
                    break
        rec = dict(row)
        rec["gate"] = name
        rec["passed"] = first is not None
        rec["early_pass"] = first in early_set if first is not None else False
        rec["first_pass_date"] = first
        rec["first_pass_progress"] = progress_at(close, first, row) if first is not None else np.nan
        rows.append(rec)
    df = pd.DataFrame(rows)

    def pack(z):
        if z.empty:
            return {"n": 0}
        p = pd.to_numeric(z.loc[z["passed"], "first_pass_progress"], errors="coerce")
        return {
            "n": int(len(z)),
            "pass_n": int(z["passed"].sum()),
            "pass_rate": float(z["passed"].mean()),
            "early_pass_n": int(z["early_pass"].sum()),
            "early_pass_rate_all": float(z["early_pass"].mean()),
            "median_first_pass_progress": float(p.median()) if p.notna().any() else None,
        }

    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    active_dates = analysis_idx[[bool(tradable.get(pd.Timestamp(d), False)) for d in analysis_idx]]
    avg_count = float(gate.reindex(active_dates).sum(axis=1).mean()) if len(active_dates) else None
    med_count = float(gate.reindex(active_dates).sum(axis=1).median()) if len(active_dates) else None
    return {
        "all": pack(df),
        "dev_2021_2023": pack(df.loc[years.between(2021, 2023)]),
        "oos_2024_2026": pack(df.loc[years.between(2024, 2026)]),
        "avg_eligible_on_tradable_days": avg_count,
        "median_eligible_on_tradable_days": med_count,
        "by_year": {str(int(y)): pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }, df


def dev_factor_key(item):
    _, s = item
    a = s["annual"]["dev_2021_2023"]
    r = s["rolling"]["dev_2021_2023"]
    med = a.get("median_first12_progress")
    medv = med if med is not None and np.isfinite(med) else 999.0
    return (a["early12_n"], a["hit12_n"], r["early12_n"], r["hit12_n"], -medv)


def dev_gate_key(item):
    _, s = item
    a = s["annual"]["dev_2021_2023"]
    r = s["rolling"]["dev_2021_2023"]
    avg = s.get("avg_eligible_on_tradable_days")
    avgv = avg if avg is not None and np.isfinite(avg) else 1e9
    return (a["early_pass_n"], a["pass_n"], r["early_pass_n"], r["pass_n"], -avgv)


def main():
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
    close = matrices["close"]
    analysis_idx = meta["analysis_idx"]
    print(f"UNIVERSE downloaded={meta['downloaded']}", flush=True)

    print("FREEZE strategy-independent leader labels", flush=True)
    annual = lc.build_annual_leaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    annual10 = annual.loc[pd.to_numeric(annual["rank"], errors="coerce") <= 10].copy()
    rolling = lc.build_rolling_superleaders(matrices, pd.Timestamp(args.leader_start), pd.Timestamp(args.analysis_end))
    freeze = freeze_labels(out, annual, rolling)
    annual.to_csv(out / "annual_leaders_frozen.csv", index=False)
    rolling.to_csv(out / "rolling_126_leaders_frozen.csv", index=False)

    print("BUILD common universes and market gate", flush=True)
    common = build_common(root, matrices)
    tradable = market_tradable(meta, close.index)
    rs = build_rs(close, common["BASE_POOL"])

    print("BUILD theme context", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    theme = theme_frame(peer_ctx, close)
    comp = build_factor_components(close, common, rs, theme)

    result: dict[str, Any] = {
        "status": "LEADER_FACTOR_HORIZON_DISCOVERY_AUDIT",
        "analysis_window": {
            "start": args.analysis_start, "end": args.analysis_end, "leader_start": args.leader_start,
            "downloaded": int(meta["downloaded"]),
        },
        "freeze": freeze,
        "design": {
            "purpose": "Test whether RS189 is actually the best early-leader identifier without using RS189 as a prerequisite for the ranking comparison.",
            "ranking_population": "Common trend/liquidity universe only: price>=5, DDV>=floor, structural biotech excluded, SMA50>SMA200, close>SMA200. No RS threshold is used for the factor ranking audit.",
            "primary_kpi": "Annual liquid Top10 leader appears in factor Top12 while price progress is <=20% of its hindsight start-to-peak run.",
            "secondary": "Top20 recognition, rolling-126 superleader recognition, first-recognition progress, and market-aware results.",
            "split": "2021-2023 development; 2024-2026YTD out-of-sample reporting. OOS is not used to choose the winner.",
            "gate_audit": "Eligibility gates are evaluated separately from ranking to avoid the current RS189 gate mechanically favoring RS189 ranking.",
        },
        "factors": {},
        "gates": {},
        "dev_factor_order": [],
        "dev_gate_order": [],
    }

    specs = factor_specs(rs, comp)
    trend = common["TREND_FULL"]
    factor_detail = []
    for n, (name, score) in enumerate(specs.items(), start=1):
        print(f"FACTOR {n}/{len(specs)} {name}", flush=True)
        rankmat = top_rank_matrix(score, trend, maxk=max(TOPKS))
        sa, dfa = eval_factor_on_leaders(name, rankmat, annual10, close, analysis_idx, tradable)
        sr, dfr = eval_factor_on_leaders(name, rankmat, rolling, close, analysis_idx, tradable)
        result["factors"][name] = {"annual": sa, "rolling": sr}
        dfa.to_csv(out / f"factor_annual_{name}.csv", index=False)
        dfr.to_csv(out / f"factor_rolling_{name}.csv", index=False)
        factor_detail.append((name, result["factors"][name]))
        del rankmat

    gates = gate_specs(common, rs)
    gate_detail = []
    for n, (name, gate) in enumerate(gates.items(), start=1):
        print(f"GATE {n}/{len(gates)} {name}", flush=True)
        sa, dfa = eval_gate_on_leaders(name, gate, annual10, close, analysis_idx, tradable)
        sr, dfr = eval_gate_on_leaders(name, gate, rolling, close, analysis_idx, tradable)
        result["gates"][name] = {
            "annual": sa["all"],
            "annual_dev_2021_2023": sa["dev_2021_2023"],
            "annual_oos_2024_2026": sa["oos_2024_2026"],
            "rolling": sr["all"],
            "rolling_dev_2021_2023": sr["dev_2021_2023"],
            "rolling_oos_2024_2026": sr["oos_2024_2026"],
            "avg_eligible_on_tradable_days": sa["avg_eligible_on_tradable_days"],
            "median_eligible_on_tradable_days": sa["median_eligible_on_tradable_days"],
            "annual_by_year": sa["by_year"],
            "rolling_by_year": sr["by_year"],
        }
        normalized = {
            "annual": {"dev_2021_2023": sa["dev_2021_2023"]},
            "rolling": {"dev_2021_2023": sr["dev_2021_2023"]},
            "avg_eligible_on_tradable_days": sa["avg_eligible_on_tradable_days"],
        }
        gate_detail.append((name, normalized))
        dfa.to_csv(out / f"gate_annual_{name}.csv", index=False)
        dfr.to_csv(out / f"gate_rolling_{name}.csv", index=False)

    result["dev_factor_order"] = [name for name, _ in sorted(factor_detail, key=dev_factor_key, reverse=True)]
    result["dev_gate_order"] = [name for name, _ in sorted(gate_detail, key=dev_gate_key, reverse=True)]
    result["dev_selected_factor"] = result["dev_factor_order"][0] if result["dev_factor_order"] else None
    result["dev_selected_gate"] = result["dev_gate_order"][0] if result["dev_gate_order"] else None

    path = out / "summary_leader_factor_horizon_discovery.json"
    path.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADER_FACTOR_HORIZON_DISCOVERY_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADER_FACTOR_HORIZON_DISCOVERY_JSON ===", flush=True)


if __name__ == "__main__":
    main()

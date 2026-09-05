from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_five_year_leader_capture as lc
import audit_leader_factor_horizon_discovery as disc


TOPKS = (3, 5, 10, 20)
DDV_LEVELS = (10_000_000.0, 20_000_000.0, 50_000_000.0)
DEV_YEARS = range(2016, 2021)
OOS_YEARS = range(2021, 2026)


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def continuous_age(mask: pd.DataFrame) -> pd.DataFrame:
    arr = mask.to_numpy(dtype=bool, copy=False)
    out = np.full(arr.shape, np.nan, dtype=np.float32)
    age = np.zeros(arr.shape[1], dtype=np.int16)
    for i in range(arr.shape[0]):
        age = np.where(arr[i], age + 1, 0)
        out[i, arr[i]] = age[arr[i]].astype(np.float32)
    return pd.DataFrame(out, index=mask.index, columns=mask.columns)


def rank_matrix(score: pd.DataFrame, mask: pd.DataFrame, maxk: int = 20) -> np.ndarray:
    return disc.top_rank_matrix(score, mask, maxk=maxk)


def build_features(close: pd.DataFrame, dvol: pd.DataFrame, base_pool: pd.DataFrame, rs: dict[int, pd.DataFrame], theme: pd.DataFrame, ddv_floor: float) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    pool = base_pool & (dvol >= ddv_floor)
    radar = pool & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))

    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, radar)
    acc10 = pct(rs[21] - rs[21].shift(10), radar)
    acc20 = pct(rs[21] - rs[21].shift(20), radar)

    age = continuous_age(radar)
    fresh = pct(-age, radar)

    theme_level = pct(theme, radar)
    # The LOO helper returns each stock's strongest peer-only theme score. Delta can
    # occasionally include a best-theme switch, so this is tested as a separate
    # component rather than silently baked into the baseline.
    theme_acc10 = pct(theme - theme.shift(10), radar)
    theme_acc20 = pct(theme - theme.shift(20), radar)

    rs21 = rs[21].where(radar).astype(np.float32)
    rs42 = rs[42].where(radar).astype(np.float32)
    rs63 = rs[63].where(radar).astype(np.float32)

    feats = {
        "RS21": rs21,
        "RS42": rs42,
        "RS63": rs63,
        "HIGH63": high63,
        "ACC10": acc10,
        "ACC20": acc20,
        "FRESH": fresh,
        "THEME": theme_level,
        "THEME_ACC10": theme_acc10,
        "THEME_ACC20": theme_acc20,
    }
    return radar, feats


def score_specs(f: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    neutral = lambda x: x.fillna(50.0)
    return {
        # Existing research direction: short RS + high proximity + acceleration.
        "BASE_RS21_HIGH_ACC": (0.50 * neutral(f["RS21"]) + 0.25 * neutral(f["HIGH63"]) + 0.25 * neutral(f["ACC10"])).astype(np.float32),
        # Test whether being newly strong matters more than simply being very strong.
        "FRESH": (0.40 * neutral(f["RS21"]) + 0.20 * neutral(f["HIGH63"]) + 0.20 * neutral(f["ACC10"]) + 0.20 * neutral(f["FRESH"])).astype(np.float32),
        # Current peer-only theme level.
        "THEME_LEVEL": (0.40 * neutral(f["RS21"]) + 0.20 * neutral(f["HIGH63"]) + 0.20 * neutral(f["ACC10"]) + 0.20 * neutral(f["THEME"])).astype(np.float32),
        # Peer theme acceleration, not absolute theme rank.
        "THEME_ACCEL": (0.40 * neutral(f["RS21"]) + 0.20 * neutral(f["HIGH63"]) + 0.20 * neutral(f["ACC10"]) + 0.20 * neutral(f["THEME_ACC20"])).astype(np.float32),
        # Fresh stock + peer theme acceleration.
        "FRESH_THEME_ACCEL": (0.35 * neutral(f["RS21"]) + 0.20 * neutral(f["HIGH63"]) + 0.15 * neutral(f["ACC10"]) + 0.15 * neutral(f["FRESH"]) + 0.15 * neutral(f["THEME_ACC20"])).astype(np.float32),
        # More diversified early score; intentionally simple and frozen.
        "EARLY_BALANCED": (0.30 * neutral(f["RS21"]) + 0.15 * neutral(f["RS42"]) + 0.15 * neutral(f["HIGH63"]) + 0.15 * neutral(f["ACC10"]) + 0.10 * neutral(f["FRESH"]) + 0.075 * neutral(f["THEME"]) + 0.075 * neutral(f["THEME_ACC20"])).astype(np.float32),
        # RS curve shape without theme information.
        "FAST_SHAPE": (0.35 * neutral(f["RS21"]) + 0.20 * neutral(f["RS42"]) + 0.15 * neutral(f["HIGH63"]) + 0.15 * neutral(f["ACC20"]) + 0.15 * neutral(f["FRESH"])).astype(np.float32),
    }


def first_radar_rank(ranks: np.ndarray, radar: pd.DataFrame, row: pd.Series, close: pd.DataFrame) -> tuple[float, float | None]:
    sym = str(row["symbol"])
    if sym not in close.columns:
        return np.nan, None
    si = close.columns.get_loc(sym)
    start = pd.Timestamp(row["start_date"])
    peak = pd.Timestamp(row["peak_date"])
    dates = close.index[(close.index >= start) & (close.index <= peak)]
    for d in dates:
        if bool(radar.at[d, sym]):
            di = close.index.get_loc(d)
            r = int(ranks[di, si])
            return float(r) if r < 32767 else np.nan, float(close.at[d, sym] / float(row["start_price"]) - 1.0)
    return np.nan, None


def evaluate_leaders(name: str, ranks: np.ndarray, radar: pd.DataFrame, leaders: pd.DataFrame, close: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    date_pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    stock_pos = {str(s): i for i, s in enumerate(close.columns)}

    for _, rr in leaders.iterrows():
        rec = dict(rr)
        sym = str(rr["symbol"])
        si = stock_pos.get(sym)
        start = pd.Timestamp(rr["start_date"])
        peak = pd.Timestamp(rr["peak_date"])
        sp = float(rr["start_price"])
        dates = close.index[(close.index >= start) & (close.index <= peak)]
        rec["variant"] = name
        rec["first_radar_rank"] = np.nan
        rec["first_radar_runup"] = np.nan
        for k in TOPKS:
            rec[f"hit{k}"] = False
            rec[f"first{k}_date"] = pd.NaT
            rec[f"first{k}_runup"] = np.nan
            rec[f"first{k}_le30"] = False
            rec[f"first{k}_le50"] = False
        if si is not None:
            first_rank, first_runup = first_radar_rank(ranks, radar, rr, close)
            rec["first_radar_rank"] = first_rank
            rec["first_radar_runup"] = first_runup if first_runup is not None else np.nan
            for k in TOPKS:
                found = None
                for d0 in dates:
                    d = pd.Timestamp(d0)
                    di = date_pos[d]
                    if int(ranks[di, si]) <= k:
                        found = d
                        break
                if found is not None:
                    runup = float(close.at[found, sym] / sp - 1.0)
                    rec[f"hit{k}"] = True
                    rec[f"first{k}_date"] = found
                    rec[f"first{k}_runup"] = runup
                    rec[f"first{k}_le30"] = bool(runup <= 0.30 + 1e-12)
                    rec[f"first{k}_le50"] = bool(runup <= 0.50 + 1e-12)
        rows.append(rec)

    df = pd.DataFrame(rows)

    def pack(z: pd.DataFrame) -> dict[str, Any]:
        if z.empty:
            return {"n": 0}
        out: dict[str, Any] = {"n": int(len(z))}
        fr = pd.to_numeric(z["first_radar_rank"], errors="coerce")
        fu = pd.to_numeric(z["first_radar_runup"], errors="coerce")
        out["radar_found_n"] = int(fr.notna().sum())
        out["median_first_radar_rank"] = float(fr.median()) if fr.notna().any() else None
        out["radar_le30_rate"] = float((fu <= 0.30).mean())
        out["radar_le50_rate"] = float((fu <= 0.50).mean())
        for k in TOPKS:
            hit = z[f"hit{k}"].astype(bool)
            run = pd.to_numeric(z.loc[hit, f"first{k}_runup"], errors="coerce")
            out[f"top{k}_hit_rate"] = float(hit.mean())
            out[f"top{k}_le30_rate"] = float(z[f"first{k}_le30"].astype(bool).mean())
            out[f"top{k}_le50_rate"] = float(z[f"first{k}_le50"].astype(bool).mean())
            out[f"top{k}_median_first_runup"] = float(run.median()) if run.notna().any() else None
        return out

    years = pd.to_numeric(df["period"].astype(str).str[:4], errors="coerce")
    dev = df.loc[years.isin(list(DEV_YEARS))]
    oos = df.loc[years.isin(list(OOS_YEARS))]
    return {
        "all": pack(df),
        "dev_2016_2020": pack(dev),
        "oos_2021_2025": pack(oos),
        "by_year": {str(int(y)): pack(df.loc[years == y]) for y in sorted(years.dropna().unique())},
    }, df


def event_noise(ranks: np.ndarray, radar: pd.DataFrame, close: pd.DataFrame, k: int = 5, cooldown: int = 20) -> dict[str, Any]:
    rows = []
    last: dict[str, int] = {}
    idx = close.index
    for i, d in enumerate(idx):
        selected = np.flatnonzero(ranks[i] <= k)
        for j in selected:
            sym = str(close.columns[j])
            if i - last.get(sym, -10_000) < cooldown:
                continue
            last[sym] = i
            p0 = float(close.iat[i, j]) if pd.notna(close.iat[i, j]) else np.nan
            rec = {"date": pd.Timestamp(d), "year": int(pd.Timestamp(d).year), "symbol": sym}
            for h in (21, 63, 126):
                jj = i + h
                p1 = float(close.iat[jj, j]) if jj < len(idx) and pd.notna(close.iat[jj, j]) else np.nan
                rec[f"ret{h}"] = p1 / p0 - 1.0 if np.isfinite(p0) and p0 > 0 and np.isfinite(p1) else np.nan
            rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0}

    def pack(z: pd.DataFrame) -> dict[str, Any]:
        ans: dict[str, Any] = {"n": int(len(z)), "symbols": int(z["symbol"].nunique())}
        for h in (21, 63, 126):
            x = pd.to_numeric(z[f"ret{h}"], errors="coerce").dropna()
            ans[f"ret{h}_median"] = float(x.median()) if len(x) else None
            ans[f"ret{h}_positive"] = float((x > 0).mean()) if len(x) else None
            ans[f"ret{h}_gt50"] = float((x > 0.50).mean()) if len(x) else None
        return ans

    return {
        "all": pack(df),
        "dev_2016_2020": pack(df.loc[df["year"].isin(list(DEV_YEARS))]),
        "oos_2021_2025": pack(df.loc[df["year"].isin(list(OOS_YEARS))]),
        "events_per_year": {str(int(y)): int(n) for y, n in df.groupby("year").size().items()},
    }


def dev_key(summary: dict[str, Any]) -> tuple[float, ...]:
    d = summary["dev_2016_2020"]
    # Frozen objective prioritizes actually buying annual Top5 before +30/+50,
    # not eventual leader recognition.
    return (
        float(d.get("top3_le30_rate", 0.0)),
        float(d.get("top5_le50_rate", 0.0)),
        float(d.get("top10_le50_rate", 0.0)),
        -float(d.get("top3_median_first_runup") if d.get("top3_median_first_runup") is not None else 99.0),
    )


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
    print("BUILD leave-one-out theme context", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    theme = disc.theme_frame(peer_ctx, close)

    print("FREEZE annual Top5 leader labels", flush=True)
    annual = lc.build_annual_leaders(matrices, pd.Timestamp(args.analysis_start), pd.Timestamp(args.analysis_end))
    leaders = annual.loc[pd.to_numeric(annual["rank"], errors="coerce") <= 5].copy()
    leaders.to_csv(out / "annual_top5_frozen.csv", index=False)

    result: dict[str, Any] = {
        "status": "EARLY_RADAR_RERANKER_AUDIT",
        "design": {
            "purpose": "Rerank stocks already visible in the early Radar; Radar itself is not redesigned.",
            "radar": "price/base-liquidity pool plus ANY(RS21,RS42,RS63)>=85; no Full Eligibility and no market gate",
            "primary_ddv": 20_000_000,
            "ddv_sensitivity": [10_000_000, 50_000_000],
            "leader_label": "annual liquid Top5, frozen independently of the candidate ranker",
            "selection_split": "2016-2020 development chooses one named score at DDV20 only; 2021-2025 is untouched holdout",
            "primary_kpi": "first Top3/5 ranking while stock is still <=+30%/+50% from annual-period start price",
            "theme": "leave-one-out peer theme score; target stock is excluded from theme calculation",
            "theme_acceleration_caveat": "delta is on the strongest LOO theme score and can contain a best-theme switch; therefore it is exploratory, not an adopted rule",
            "no_market_gate": True,
            "no_full_eligibility": True,
            "no_portfolio_change": True,
        },
        "coverage": {"downloaded": int(meta["downloaded"]), "leaders_top5": int(len(leaders)), "peer": peer_ctx.get("coverage", {})},
        "variants": {},
        "dev_order_ddv20": [],
        "dev_selected_ddv20": None,
    }

    detail_frames = []
    for ddv in DDV_LEVELS:
        label = f"DDV{int(ddv / 1_000_000)}"
        print(f"BUILD RADAR {label}", flush=True)
        radar, feats = build_features(close, matrices["dvol"], common["BASE_POOL"], rs, theme, ddv)
        specs = score_specs(feats)
        for name, score in specs.items():
            key = f"{label}_{name}"
            print(f"RANK {key}", flush=True)
            ranks = rank_matrix(score, radar, maxk=max(TOPKS))
            summary, detail = evaluate_leaders(key, ranks, radar, leaders, close)
            noise = event_noise(ranks, radar, close, k=5, cooldown=20)
            result["variants"][key] = {"leader_capture": summary, "top5_event_noise": noise}
            detail.to_csv(out / f"leader_detail_{key}.csv", index=False)
            if ddv == 20_000_000.0:
                detail_frames.append((key, summary))

    ordered = sorted(detail_frames, key=lambda x: dev_key(x[1]), reverse=True)
    result["dev_order_ddv20"] = [k for k, _ in ordered]
    result["dev_selected_ddv20"] = ordered[0][0] if ordered else None

    p = out / "summary_early_radar_reranker.json"
    p.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY_RADAR_RERANKER_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY_RADAR_RERANKER_JSON ===", flush=True)


if __name__ == "__main__":
    main()

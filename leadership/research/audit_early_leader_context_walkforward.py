from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_radar_cohort_discriminator as disc
import validate_early_rotation as er

WINDOWS = (5, 10, 20)
TOPKS = (3, 5, 10)
SCORES = (
    "HIGH_ACCEL",
    "THEME",
    "INDUSTRY",
    "VOLUME_DRY",
    "HIGH_ACCEL_THEME",
    "HIGH_ACCEL_INDUSTRY",
    "CONTEXT_BLEND",
    "CONTEXT_BLEND_DRY",
)


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def safe(v: Any) -> Any:
    if isinstance(v, dict): return {k: safe(x) for k, x in v.items()}
    if isinstance(v, list): return [safe(x) for x in v]
    if isinstance(v, (np.floating,)): return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, pd.Timestamp): return v.isoformat()
    return v


def industry_members(root: Path, cols: list[str]) -> dict[str, list[str]]:
    obj = json.loads((root / "sector_snapshot.json").read_text(encoding="utf-8"))
    s2i = obj.get("s2i", {}) if isinstance(obj, dict) else {}
    colset = set(cols)
    groups: dict[str, list[str]] = {}
    for sym, ind in s2i.items():
        if sym in colset and isinstance(ind, str) and ind.strip():
            groups.setdefault(ind.strip(), []).append(sym)
    return {g: m for g, m in groups.items() if len(m) >= 3}


def build_industry_loo_score(root: Path, matrices: dict[str, pd.DataFrame], pool: pd.DataFrame) -> pd.DataFrame:
    close = matrices["close"]
    ret = er.arithmetic_returns(close)
    groups = industry_members(root, list(close.columns))
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=np.float32)
    ema21 = close.ewm(span=21, adjust=False, min_periods=15).mean()
    above = (close > ema21).where(close.notna() & ema21.notna())
    minp = int(math.ceil(63 * 0.8))

    # Build peer-only group metrics per stock, then rank cross-sectionally by date.
    peer63 = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=np.float32)
    peerbreadth = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=np.float32)
    for n, (g, members) in enumerate(groups.items(), start=1):
        vals = ret[members].to_numpy(float)
        valid = np.isfinite(vals)
        sums = np.where(valid, vals, 0.0).sum(axis=1)
        counts = valid.sum(axis=1)
        den = counts[:, None] - valid.astype(np.int16)
        num = sums[:, None] - np.where(valid, vals, 0.0)
        peer_daily = np.divide(num, den, out=np.full_like(num, np.nan), where=den >= 2)
        peer_log = np.log1p(np.where(peer_daily > -0.999999, peer_daily, np.nan))
        p63 = np.expm1(pd.DataFrame(peer_log, index=close.index).rolling(63, min_periods=minp).sum().to_numpy(float))
        peer63.loc[:, members] = p63.astype(np.float32)

        av = above[members].astype(float).to_numpy()
        vb = np.isfinite(av)
        ab = np.nan_to_num(av, nan=0.0)
        tv = vb.sum(axis=1)
        ta = ab.sum(axis=1)
        pvalid = tv[:, None] - vb.astype(np.int16)
        pabove = ta[:, None] - ab
        pb = np.divide(pabove * 100.0, pvalid, out=np.full_like(pabove, np.nan), where=pvalid >= 2)
        peerbreadth.loc[:, members] = pb.astype(np.float32)
        if n % 25 == 0 or n == len(groups):
            print(f"INDUSTRY_LOO {n}/{len(groups)}", flush=True)

    p63_pct = pct(peer63, pool)
    accel = p63_pct - p63_pct.shift(20)
    accel_pct = pct(accel, pool)
    breadth_pct = pct(peerbreadth, pool)
    ok = p63_pct.notna() & accel_pct.notna() & breadth_pct.notna()
    out = ((p63_pct + accel_pct + breadth_pct) / 3.0).where(ok).astype(np.float32)
    return out


def build_components(root: Path, matrices: dict[str, pd.DataFrame], pool: pd.DataFrame, rs: dict[int, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close = matrices["close"]
    dvol = matrices["dvol"]
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = pct(close / prior63, pool)
    acc21 = pct(rs[21] - rs[21].shift(20), pool)
    high_accel = (0.50 * rs[21] + 0.25 * high63 + 0.25 * acc21).astype(np.float32)

    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    theme = pd.DataFrame(np.asarray(peer_ctx["best_score"], dtype=np.float32), index=close.index, columns=close.columns)
    industry = build_industry_loo_score(root, matrices, pool)

    v10 = dvol.rolling(10, min_periods=7).mean()
    v20 = dvol.rolling(20, min_periods=14).mean()
    dry_ratio = v10 / v20
    # Smaller ratio = stronger contraction, so reverse percentile.
    volume_dry = (100.0 - pct(dry_ratio, pool)).astype(np.float32)

    return {"HIGH_ACCEL": high_accel, "THEME": theme, "INDUSTRY": industry, "VOLUME_DRY": volume_dry}


def score(name: str, c: dict[str, pd.DataFrame]) -> pd.DataFrame:
    h, t, i, v = c["HIGH_ACCEL"], c["THEME"].fillna(50.0), c["INDUSTRY"].fillna(50.0), c["VOLUME_DRY"].fillna(50.0)
    if name == "HIGH_ACCEL": return h
    if name == "THEME": return t
    if name == "INDUSTRY": return i
    if name == "VOLUME_DRY": return v
    if name == "HIGH_ACCEL_THEME": return (0.70*h + 0.30*t).astype(np.float32)
    if name == "HIGH_ACCEL_INDUSTRY": return (0.70*h + 0.30*i).astype(np.float32)
    if name == "CONTEXT_BLEND": return (0.55*h + 0.25*t + 0.20*i).astype(np.float32)
    if name == "CONTEXT_BLEND_DRY": return (0.50*h + 0.20*t + 0.20*i + 0.10*v).astype(np.float32)
    raise ValueError(name)


def active_from_fresh(fresh: pd.DataFrame, window: int) -> pd.DataFrame:
    return fresh.rolling(window, min_periods=1).max().fillna(False).astype(bool)


def selections(s: pd.DataFrame, active: pd.DataFrame, idx: pd.DatetimeIndex) -> dict[pd.Timestamp, list[str]]:
    out: dict[pd.Timestamp, list[str]] = {}
    for n, d0 in enumerate(idx, start=1):
        d = pd.Timestamp(d0)
        row = pd.to_numeric(s.loc[d].where(active.loc[d]), errors="coerce").dropna().nlargest(max(TOPKS))
        out[d] = [str(x) for x in row.index]
        if n % 700 == 0: print(f"SELECT {n}/{len(idx)}", flush=True)
    return out


def split(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    y = pd.to_datetime(events["anchor_date"]).dt.year
    return {
        "dev_2016_2020": events.loc[y.between(2016, 2020)],
        "confirm_2021_2023": events.loc[y.between(2021, 2023)],
        "holdout_2024_2026": events.loc[y >= 2024],
        "all": events,
    }


def objective(pack: dict[str, Any]) -> float:
    # Predeclared development score; heavily rewards actual early capture.
    return 0.55 * float(pack.get("within_30pct_all") or 0.0) + 0.30 * float(pack.get("within_50pct_all") or 0.0) + 0.15 * float(pack.get("captured_rate") or 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    close = matrices["close"]
    pool = delay.current_base_pool(root, matrices).fillna(False)
    rs = delay.rs_matrices(close, pool)
    radar = (pool & ((rs[21] >= 85.0) | (rs[42] >= 85.0) | (rs[63] >= 85.0))).fillna(False)
    fresh = (radar & ~radar.shift(1).fillna(False)).fillna(False)
    comps = build_components(root, matrices, pool, rs)

    annual = disc.annual_top5(close, pool, idx)
    rolling = disc.rolling126_top10(close, pool, idx)
    labels = {"annual_top5": split(annual), "rolling126_top10": split(rolling)}

    result: dict[str, Any] = {
        "status": "EARLY_LEADER_CONTEXT_WALKFORWARD",
        "scope": "research only; production/main/UI untouched",
        "design": {
            "radar": "Any(RS21,RS42,RS63)>=85 in current tradability pool",
            "windows": list(WINDOWS), "topks": list(TOPKS), "scores": list(SCORES),
            "development": "2016-2020 only selects winner",
            "confirmation": "2021-2023 untouched",
            "holdout": "2024-2026 untouched",
            "industry": "leave-one-out s2i industry group 63d RS percentile + 20d rank acceleration percentile + EMA21 breadth percentile",
            "theme": "existing strict leave-one-out Peer Theme Score",
            "volume_dry": "reverse percentile of 10d/20d average dollar volume ratio",
            "no_market_gate": True,
            "note": "recognition/ranking audit only; not a tradable portfolio",
        },
        "grid": {}, "winner": {},
    }

    dev_rows = []
    for w in WINDOWS:
        active = active_from_fresh(fresh, w)
        for nm in SCORES:
            print(f"RUN {nm} W{w}", flush=True)
            sel = selections(score(nm, comps), active, idx)
            rec: dict[str, Any] = {}
            for label_name, splits in labels.items():
                rec[label_name] = {}
                for split_name, ev in splits.items():
                    rec[label_name][split_name] = {str(k): disc.event_pack(ev, sel, close, k) for k in TOPKS}
            key = f"{nm}_W{w}"
            result["grid"][key] = rec
            p = rec["annual_top5"]["dev_2016_2020"]["3"]
            dev_rows.append((objective(p), nm, w, p))

    dev_rows.sort(key=lambda z: (z[0], z[3].get("within_30pct_all") or 0, z[3].get("within_50pct_all") or 0), reverse=True)
    best_obj, best_nm, best_w, best_pack = dev_rows[0]
    best_key = f"{best_nm}_W{best_w}"
    result["winner"] = {
        "score": best_nm, "window": best_w, "development_objective": best_obj,
        "dev_top3": best_pack,
        "confirmation_top3": result["grid"][best_key]["annual_top5"]["confirm_2021_2023"]["3"],
        "holdout_top3": result["grid"][best_key]["annual_top5"]["holdout_2024_2026"]["3"],
        "confirmation_top5": result["grid"][best_key]["annual_top5"]["confirm_2021_2023"]["5"],
        "holdout_top5": result["grid"][best_key]["annual_top5"]["holdout_2024_2026"]["5"],
        "rolling_holdout_top3": result["grid"][best_key]["rolling126_top10"]["holdout_2024_2026"]["3"],
    }

    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for key, rec in result["grid"].items():
        nm, w = key.rsplit("_W", 1)
        for split_name in ("dev_2016_2020", "confirm_2021_2023", "holdout_2024_2026"):
            for k in TOPKS:
                p = rec["annual_top5"][split_name][str(k)]
                rows.append({"score": nm, "window": int(w), "split": split_name, "topk": k, **p})
    pd.DataFrame(rows).to_csv(out / "annual_top5_grid.csv", index=False)
    print("=== EARLY_LEADER_CONTEXT_WALKFORWARD_RESULT ===", flush=True)
    print(json.dumps(safe(result["winner"]), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

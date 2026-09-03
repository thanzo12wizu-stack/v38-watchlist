from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_exit_trail as ex

WINDOWS = (5, 10, 20)
SCORES = ("RS21", "RS63_HIGH", "RS21_HIGH", "RS21_ACCEL", "RS21_HIGH_ACCEL", "RS21_RS63_HIGH")
TOPKS = (3, 5, 10)


def safe(x: Any) -> Any:
    return base.safe(x)


def pct(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def annual_top5(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    e = delay.annual_leader_events(close, pool, idx, include_partial_2026=False)
    return e[e["top5"]][["anchor_date", "final_date", "symbol", "final_return"]].copy()


def rolling126_top10(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    aps = [pos[pd.Timestamp(d)] for d in idx if pd.Timestamp(d) in pos]
    if not aps:
        return pd.DataFrame()
    first, last = min(aps), max(aps)
    rows = []
    for p in range(first, last - 126 + 1, 21):
        a, e = pd.Timestamp(close.index[p]), pd.Timestamp(close.index[p + 126])
        if a not in idx or e > idx[-1]:
            continue
        ret = (close.loc[e] / close.loc[a] - 1.0).where(pool.loc[a]).dropna().sort_values(ascending=False).head(10)
        for rank, (sym, r) in enumerate(ret.items(), 1):
            rows.append({"anchor_date": a, "final_date": e, "symbol": str(sym), "final_return": float(r), "rank": rank, "anchor_pos": p})
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
    keep = []
    for _, g in raw.sort_values(["symbol", "anchor_pos"]).groupby("symbol", observed=True):
        last_kept = -10**9
        for j, r in g.iterrows():
            p = int(r["anchor_pos"])
            if p - last_kept >= 63:
                keep.append(j); last_kept = p
    return raw.loc[keep].reset_index(drop=True)


def market_gate(meta: dict[str, Any], idx: pd.DatetimeIndex) -> pd.Series:
    vals = []
    for d0 in idx:
        color, bucket, _ = delay.market_state(meta, pd.Timestamp(d0))
        vals.append(bool(color in ("Blue", "Green") and bucket >= 1))
    return pd.Series(vals, index=idx, dtype=bool)


def build_scores(close: pd.DataFrame, pool: pd.DataFrame, rs: dict[int, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high = pct(close / prior63, pool)
    acc = pct(rs[21] - rs[21].shift(20), pool)
    return {
        "RS21": rs[21].astype(np.float32),
        "RS63_HIGH": (0.75 * rs[63] + 0.25 * high).astype(np.float32),
        "RS21_HIGH": (0.75 * rs[21] + 0.25 * high).astype(np.float32),
        "RS21_ACCEL": (0.75 * rs[21] + 0.25 * acc).astype(np.float32),
        "RS21_HIGH_ACCEL": (0.50 * rs[21] + 0.25 * high + 0.25 * acc).astype(np.float32),
        "RS21_RS63_HIGH": (0.45 * rs[21] + 0.30 * rs[63] + 0.25 * high).astype(np.float32),
    }


def selection_masks(score: pd.DataFrame, active: pd.DataFrame, idx: pd.DatetimeIndex, gate: pd.Series | None) -> dict[int, pd.DataFrame]:
    s = score.loc[idx].where(active.loc[idx])
    if gate is not None:
        s = s.where(gate.reindex(idx).fillna(False), axis=0)
    ranks = s.rank(axis=1, ascending=False, method="first", na_option="bottom")
    valid = s.notna()
    return {k: (valid & ranks.le(k)) for k in TOPKS}


def eval_events(events: pd.DataFrame, selected: pd.DataFrame, close: pd.DataFrame) -> dict[str, Any]:
    rows = []
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol); a = pd.Timestamp(ev.anchor_date); e = pd.Timestamp(ev.final_date)
        if sym not in selected.columns or a not in close.index:
            continue
        ap = delay.px(close, a, sym, None)
        if ap is None:
            continue
        sel = selected.loc[(selected.index >= a) & (selected.index <= e), sym].fillna(False)
        hits = sel.index[sel]
        if not len(hits):
            rows.append({"captured": False, "gain": np.nan, "peak": np.nan})
            continue
        d = pd.Timestamp(hits[0])
        cp = delay.px(close, d, sym, None)
        hist = pd.to_numeric(close.loc[(close.index >= a) & (close.index <= d), sym], errors="coerce").dropna()
        peak = float(hist.max() / ap - 1.0) if len(hist) else np.nan
        gain = float(cp / ap - 1.0) if cp is not None else np.nan
        rows.append({"captured": True, "gain": gain, "peak": peak})
    x = pd.DataFrame(rows)
    if x.empty:
        return {"n": 0}
    cap = x["captured"]
    g = pd.to_numeric(x["gain"], errors="coerce")
    p = pd.to_numeric(x["peak"], errors="coerce")
    return {
        "n": int(len(x)), "captured_n": int(cap.sum()), "captured_rate": float(cap.mean()),
        "within20_all": float((p <= 0.20).fillna(False).mean()),
        "within30_all": float((p <= 0.30).fillna(False).mean()),
        "within50_all": float((p <= 0.50).fillna(False).mean()),
        "median_entry_gain": float(g[cap].median()) if cap.any() else None,
        "median_prior_peak": float(p[cap].median()) if cap.any() else None,
    }


def splits(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    y = pd.to_datetime(events["anchor_date"]).dt.year
    return {"all": events, "dev_2016_2020": events[y <= 2020], "conf_2021_2025": events[y.between(2021, 2025)]}


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
    gate = market_gate(meta, idx)
    scores = build_scores(close, pool, rs)
    labels = {"annual_top5": splits(annual_top5(close, pool, idx)), "rolling126_top10": splits(rolling126_top10(close, pool, idx))}

    result: dict[str, Any] = {
        "status": "RADAR_COHORT_FOCUSED_CONFIRMATION",
        "scope": "research only; strict historical-peak cutoff; no main/UI change",
        "design": "predeclared focused candidates from prior Factor Horizon study; choose only on 2016-2020; 2021-2025 confirmation untouched",
        "configs": {},
    }
    dev_order = []
    for w in WINDOWS:
        active = fresh.rolling(w, min_periods=1).max().astype(bool)
        for name in SCORES:
            score = scores[name]
            for market, mgate in (("IGNORE_MARKET", None), ("CURRENT_GATE", gate)):
                print(f"EVAL W{w} {name} {market}", flush=True)
                masks = selection_masks(score, active, idx, mgate)
                key = f"W{w}_{name}_{market}"
                cfg = {"window": w, "score": name, "market": market, "labels": {}}
                for lab, sp in labels.items():
                    cfg["labels"][lab] = {sn: {f"TOP{k}": eval_events(ev, masks[k], close) for k in TOPKS} for sn, ev in sp.items()}
                result["configs"][key] = cfg
                if market == "IGNORE_MARKET":
                    a = cfg["labels"]["annual_top5"]["dev_2016_2020"]["TOP3"]
                    r = cfg["labels"]["rolling126_top10"]["dev_2016_2020"]["TOP3"]
                    dev_order.append({"key": key, "annual30": a["within30_all"], "annual_capture": a["captured_rate"], "rolling30": r["within30_all"], "rolling_capture": r["captured_rate"]})
    dev_order.sort(key=lambda z: (z["annual30"], z["rolling30"], z["annual_capture"], z["rolling_capture"]), reverse=True)
    result["development_order"] = dev_order
    result["development_selected"] = dev_order[0]["key"] if dev_order else None
    if dev_order:
        stem = dev_order[0]["key"].rsplit("_IGNORE_MARKET", 1)[0]
        result["selected_ignore_market"] = result["configs"].get(stem + "_IGNORE_MARKET")
        result["selected_current_gate"] = result["configs"].get(stem + "_CURRENT_GATE")
    (out / "summary_radar_cohort_focused_confirmation.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== FOCUSED_RADAR_JSON ===")
    print(json.dumps(safe({"development_selected": result.get("development_selected"), "top10": dev_order[:10], "selected_ignore_market": result.get("selected_ignore_market"), "selected_current_gate": result.get("selected_current_gate")}), ensure_ascii=False, indent=2))
    print("=== END_FOCUSED_RADAR_JSON ===")


if __name__ == "__main__":
    main()

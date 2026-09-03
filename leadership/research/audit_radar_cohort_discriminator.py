from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_major_leader_entry_delay as delay
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo
import audit_ordinary_stock_exit_trail as ex

WINDOWS = (5, 10, 20)
TOPKS = (3, 5, 10)
SCORE_NAMES = (
    "RS21",
    "RS63_HIGH_OLD",
    "RS21_HIGH63",
    "RS21_ACCEL",
    "RS21_HIGH_ACCEL",
    "RS21_RS63_HIGH",
    "RS21_P20_THEME",
    "RS21_HIGH_THEME",
    "RS21_ACCEL_HIGH_THEME",
    "RS21_HIGH_VOL",
    "RS21_TREND_HIGH",
)


def safe(v: Any) -> Any:
    return base.safe(v)


def percentile(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return (frame.where(mask).rank(axis=1, pct=True, method="average") * 100.0).astype(np.float32)


def rolling126_top10(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    pos = {pd.Timestamp(d): i for i, d in enumerate(close.index)}
    ap = [pos[pd.Timestamp(d)] for d in idx if pd.Timestamp(d) in pos]
    if not ap:
        return pd.DataFrame()
    first, last = min(ap), max(ap)
    rows: list[dict[str, Any]] = []
    for p in range(first, last - 126 + 1, 21):
        d0, d1 = pd.Timestamp(close.index[p]), pd.Timestamp(close.index[p + 126])
        if d0 not in idx or d1 > idx[-1]:
            continue
        tradable = pool.loc[d0].fillna(False)
        ret = (close.loc[d1] / close.loc[d0] - 1.0).where(tradable).dropna().sort_values(ascending=False).head(10)
        for rank, (sym, r) in enumerate(ret.items(), start=1):
            rows.append({
                "event_type": "ROLL126_TOP10", "anchor_date": d0, "final_date": d1,
                "symbol": str(sym), "future_return": float(r), "rank": rank, "anchor_pos": p,
            })
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
    keep: list[int] = []
    for _, g in raw.sort_values(["symbol", "anchor_pos"]).groupby("symbol", observed=True):
        last_kept = -10**9
        for j, r in g.iterrows():
            p = int(r["anchor_pos"])
            if p - last_kept >= 63:
                keep.append(j)
                last_kept = p
    return raw.loc[keep].sort_values(["anchor_date", "rank"]).reset_index(drop=True)


def annual_top5(close: pd.DataFrame, pool: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    e = delay.annual_leader_events(close, pool, idx, include_partial_2026=False)
    x = e[e["top5"]].copy()
    return x.rename(columns={"final_return": "future_return"})[["year", "anchor_date", "final_date", "symbol", "future_return"]].assign(event_type="ANNUAL_TOP5")


def market_allowed(meta: dict[str, Any], idx: pd.DatetimeIndex) -> pd.Series:
    vals = []
    for d0 in idx:
        d = pd.Timestamp(d0)
        color, bucket, _ = delay.market_state(meta, d)
        vals.append(bool(color in ("Blue", "Green") and bucket >= 1))
    return pd.Series(vals, index=idx, dtype=bool)


def build_components(root: Path, matrices: dict[str, pd.DataFrame], pool: pd.DataFrame, rs: dict[int, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    close = matrices["close"]
    dvol = matrices["dvol"]
    p20 = percentile(close / close.shift(20) - 1.0, pool)
    acc21 = percentile(rs[21] - rs[21].shift(20), pool)
    prior63 = close.shift(1).rolling(63, min_periods=40).max()
    high63 = percentile(close / prior63, pool)
    dvol_rel = dvol / dvol.rolling(20, min_periods=10).median()
    vol20 = percentile(dvol_rel, pool)
    trend50 = percentile(close / matrices["sma50"], pool)
    print("BUILD STRICT LOO THEME", flush=True)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    theme = pd.DataFrame(
        np.asarray(peer_ctx["best_score"], dtype=np.float32),
        index=close.index, columns=close.columns,
    )
    return {"P20": p20, "ACC21": acc21, "HIGH63": high63, "VOL20": vol20, "TREND50": trend50, "THEME": theme}


def score_frame(name: str, rs: dict[int, pd.DataFrame], c: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if name == "RS21":
        return rs[21].astype(np.float32)
    if name == "RS63_HIGH_OLD":
        return (0.75 * rs[63] + 0.25 * c["HIGH63"]).astype(np.float32)
    if name == "RS21_HIGH63":
        return (0.75 * rs[21] + 0.25 * c["HIGH63"]).astype(np.float32)
    if name == "RS21_ACCEL":
        return (0.75 * rs[21] + 0.25 * c["ACC21"]).astype(np.float32)
    if name == "RS21_HIGH_ACCEL":
        return (0.50 * rs[21] + 0.25 * c["HIGH63"] + 0.25 * c["ACC21"]).astype(np.float32)
    if name == "RS21_RS63_HIGH":
        return (0.45 * rs[21] + 0.30 * rs[63] + 0.25 * c["HIGH63"]).astype(np.float32)
    if name == "RS21_P20_THEME":
        return (0.50 * rs[21] + 0.20 * c["P20"] + 0.30 * c["THEME"].fillna(50.0)).astype(np.float32)
    if name == "RS21_HIGH_THEME":
        return (0.55 * rs[21] + 0.25 * c["HIGH63"] + 0.20 * c["THEME"].fillna(50.0)).astype(np.float32)
    if name == "RS21_ACCEL_HIGH_THEME":
        return (0.40 * rs[21] + 0.20 * c["ACC21"] + 0.20 * c["HIGH63"] + 0.20 * c["THEME"].fillna(50.0)).astype(np.float32)
    if name == "RS21_HIGH_VOL":
        return (0.55 * rs[21] + 0.25 * c["HIGH63"] + 0.20 * c["VOL20"]).astype(np.float32)
    if name == "RS21_TREND_HIGH":
        return (0.55 * rs[21] + 0.25 * c["HIGH63"] + 0.20 * c["TREND50"]).astype(np.float32)
    raise ValueError(name)


def selections_for(score: pd.DataFrame, active: pd.DataFrame, idx: pd.DatetimeIndex, allowed: pd.Series | None) -> dict[pd.Timestamp, list[str]]:
    out: dict[pd.Timestamp, list[str]] = {}
    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        if allowed is not None and not bool(allowed.get(d, False)):
            out[d] = []
            continue
        mask = active.loc[d].fillna(False)
        s = pd.to_numeric(score.loc[d].where(mask), errors="coerce").dropna().nlargest(max(TOPKS))
        out[d] = [str(x) for x in s.index]
        if (i + 1) % 700 == 0:
            print(f"SELECT {i + 1}/{len(idx)}", flush=True)
    return out


def event_pack(events: pd.DataFrame, selections: dict[pd.Timestamp, list[str]], close: pd.DataFrame, k: int) -> dict[str, Any]:
    if events.empty:
        return {"n": 0}
    rows: list[dict[str, Any]] = []
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for ev in events.itertuples(index=False):
        sym = str(ev.symbol); a = pd.Timestamp(ev.anchor_date); e = pd.Timestamp(ev.final_date)
        ap = delay.px(close, a, sym, None)
        if ap is None or a not in pos:
            continue
        found = None; gain = None
        for d0 in idx[(idx >= a) & (idx <= e)]:
            d = pd.Timestamp(d0)
            cp = delay.px(close, d, sym, None)
            if cp is None:
                continue
            g = float(cp / ap - 1.0)
            if sym in selections.get(d, [])[:k]:
                found = d; gain = g; break
        rows.append({"captured": found is not None, "gain": gain if gain is not None else np.nan})
    x = pd.DataFrame(rows)
    g = pd.to_numeric(x["gain"], errors="coerce")
    return {
        "n": int(len(x)),
        "captured_n": int(x["captured"].sum()),
        "captured_rate": float(x["captured"].mean()) if len(x) else None,
        "within_20pct_all": float((g <= 0.20).fillna(False).mean()) if len(x) else None,
        "within_30pct_all": float((g <= 0.30).fillna(False).mean()) if len(x) else None,
        "within_50pct_all": float((g <= 0.50).fillna(False).mean()) if len(x) else None,
        "median_first_gain_captured": float(g[x["captured"]].median()) if x["captured"].any() else None,
    }


def split_events(events: pd.DataFrame, dev_end: int = 2020) -> dict[str, pd.DataFrame]:
    years = pd.to_datetime(events["anchor_date"]).dt.year
    return {
        "all": events,
        "dev_2016_2020": events.loc[years <= dev_end],
        "conf_2021_2025": events.loc[years >= 2021],
    }


def selection_quality(selections: dict[pd.Timestamp, list[str]], fresh: pd.DataFrame, close: pd.DataFrame, window: int, k: int = 3) -> dict[str, Any]:
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    seen: set[tuple[str, pd.Timestamp]] = set()
    rows = []
    for d0, syms in selections.items():
        d = pd.Timestamp(d0); i = pos.get(d)
        if i is None:
            continue
        for sym in syms[:k]:
            lo = max(0, i - window + 1)
            z = fresh[sym].iloc[lo:i + 1]
            hits = z.index[z.fillna(False)]
            episode = pd.Timestamp(hits[-1]) if len(hits) else d
            key = (sym, episode)
            if key in seen:
                continue
            seen.add(key)
            p0 = delay.px(close, d, sym, None)
            p63 = delay.px(close, pd.Timestamp(idx[i + 63]), sym, None) if i + 63 < len(idx) else None
            p126 = delay.px(close, pd.Timestamp(idx[i + 126]), sym, None) if i + 126 < len(idx) else None
            rows.append({
                "date": d, "symbol": sym,
                "fwd63": float(p63 / p0 - 1.0) if p0 and p63 else np.nan,
                "fwd126": float(p126 / p0 - 1.0) if p0 and p126 else np.nan,
            })
    x = pd.DataFrame(rows)
    def pack(z: pd.DataFrame) -> dict[str, Any]:
        if z.empty:
            return {"n": 0}
        r63 = pd.to_numeric(z["fwd63"], errors="coerce").dropna()
        r126 = pd.to_numeric(z["fwd126"], errors="coerce").dropna()
        return {
            "n": int(len(z)),
            "fwd63_n": int(len(r63)), "fwd63_median": float(r63.median()) if len(r63) else None,
            "fwd63_positive": float((r63 > 0).mean()) if len(r63) else None,
            "fwd126_n": int(len(r126)), "fwd126_median": float(r126.median()) if len(r126) else None,
            "fwd126_positive": float((r126 > 0).mean()) if len(r126) else None,
            "fwd126_ge50": float((r126 >= 0.50).mean()) if len(r126) else None,
        }
    years = pd.to_datetime(x["date"]).dt.year if not x.empty else pd.Series(dtype=int)
    return {
        "all": pack(x),
        "dev_2016_2020": pack(x.loc[years <= 2020]) if not x.empty else {"n": 0},
        "conf_2021_2025": pack(x.loc[years.between(2021, 2025)]) if not x.empty else {"n": 0},
    }


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
    allowed = market_allowed(meta, idx)
    comp = build_components(root, matrices, pool, rs)

    annual = annual_top5(close, pool, idx)
    rolling = rolling126_top10(close, pool, idx)
    label_splits = {"annual_top5": split_events(annual), "rolling126_top10": split_events(rolling)}

    result: dict[str, Any] = {
        "status": "RADAR_COHORT_DISCRIMINATOR_AUDIT",
        "scope": "research only; main/UI/production untouched",
        "design": {
            "radar": "base tradability pool and first crossing into Any(RS21,RS42,RS63)>=85",
            "active_windows": list(WINDOWS),
            "question": "Among fresh early-radar candidates, can contemporaneous features rank true future leaders into Top3 early enough?",
            "selection": "daily score rank within active fresh-radar cohort; no current Full Eligibility or RS189 prerequisite",
            "development": "2016-2020 only; confirmation 2021-2025 is not used to choose winner",
            "market_modes": ["IGNORE_MARKET", "CURRENT_GATE"],
            "note": "Recognition audit, not a tradable portfolio. Portfolio returns must be tested only after a ranker survives confirmation.",
        },
        "label_counts": {"annual_top5": int(len(annual)), "rolling126_top10": int(len(rolling))},
        "configs": {},
    }

    config_dev_rows = []
    for window in WINDOWS:
        print(f"ACTIVE WINDOW {window}", flush=True)
        active = fresh.rolling(window, min_periods=1).max().astype(bool)
        active_counts = active.loc[idx].sum(axis=1)
        for score_name in SCORE_NAMES:
            print(f"SCORE {score_name} W{window}", flush=True)
            score = score_frame(score_name, rs, comp)
            for market_name, gate in (("IGNORE_MARKET", None), ("CURRENT_GATE", allowed)):
                selections = selections_for(score, active, idx, gate)
                key = f"W{window}_{score_name}_{market_name}"
                packed: dict[str, Any] = {
                    "window": window, "score": score_name, "market": market_name,
                    "active_candidates_median": float(active_counts.median()),
                    "active_candidates_p90": float(active_counts.quantile(0.90)),
                    "leader_capture": {},
                    "selection_quality_top3": selection_quality(selections, fresh, close, window, 3),
                }
                for label_name, splits in label_splits.items():
                    packed["leader_capture"][label_name] = {}
                    for split_name, evs in splits.items():
                        packed["leader_capture"][label_name][split_name] = {
                            f"TOP{k}": event_pack(evs, selections, close, k) for k in TOPKS
                        }
                result["configs"][key] = packed
                if market_name == "IGNORE_MARKET":
                    a = packed["leader_capture"]["annual_top5"]["dev_2016_2020"]["TOP3"]
                    r = packed["leader_capture"]["rolling126_top10"]["dev_2016_2020"]["TOP3"]
                    q = packed["selection_quality_top3"]["dev_2016_2020"]
                    config_dev_rows.append({
                        "key": key,
                        "annual30": a.get("within_30pct_all") or 0.0,
                        "rolling30": r.get("within_30pct_all") or 0.0,
                        "annual_capture": a.get("captured_rate") or 0.0,
                        "fwd126_median": q.get("fwd126_median") if q.get("fwd126_median") is not None else -999.0,
                    })
            del score

    order = sorted(
        config_dev_rows,
        key=lambda z: (z["annual30"], z["rolling30"], z["annual_capture"], z["fwd126_median"]),
        reverse=True,
    )
    result["development_order_ignore_market"] = order
    result["development_selected"] = order[0]["key"] if order else None
    if order:
        selected_prefix = order[0]["key"].rsplit("_IGNORE_MARKET", 1)[0]
        result["selected_pair"] = {
            "ignore_market": result["configs"].get(selected_prefix + "_IGNORE_MARKET"),
            "current_gate": result["configs"].get(selected_prefix + "_CURRENT_GATE"),
        }

    (out / "summary_radar_cohort_discriminator.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== RADAR_COHORT_DISCRIMINATOR_JSON ===", flush=True)
    print(json.dumps(safe({
        "status": result["status"], "label_counts": result["label_counts"],
        "development_selected": result.get("development_selected"),
        "development_order_top10": order[:10], "selected_pair": result.get("selected_pair"),
    }), ensure_ascii=False, indent=2), flush=True)
    print("=== END_RADAR_COHORT_DISCRIMINATOR_JSON ===", flush=True)


if __name__ == "__main__":
    main()

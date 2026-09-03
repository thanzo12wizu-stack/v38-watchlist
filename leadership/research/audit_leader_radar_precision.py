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
import audit_leader_factor_horizon_discovery as disc

TOPN = 20
COOLDOWN = 20


def summarize_events(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"n": int(len(df))}
    if df.empty:
        return out
    for h in (20, 63, 126):
        x = pd.to_numeric(df[f"ret{h}"], errors="coerce").dropna()
        out[f"ret{h}"] = {
            "n": int(len(x)),
            "mean": float(x.mean()) if len(x) else None,
            "median": float(x.median()) if len(x) else None,
            "positive_rate": float((x > 0).mean()) if len(x) else None,
            "gt20_rate": float((x > 0.20).mean()) if len(x) else None,
        }
    s = df["future126_superleader"].dropna()
    out["future126_superleader_rate"] = float(s.astype(bool).mean()) if len(s) else None
    out["symbols"] = int(df["symbol"].nunique())
    return out


def top_mask(score: pd.DataFrame, mask: pd.DataFrame, n: int = TOPN) -> pd.DataFrame:
    arr = score.where(mask).to_numpy(dtype=float)
    out = np.zeros(arr.shape, dtype=bool)
    for i in range(arr.shape[0]):
        valid = np.flatnonzero(np.isfinite(arr[i]))
        if not len(valid):
            continue
        k = min(n, len(valid))
        if len(valid) > k:
            p = np.argpartition(arr[i, valid], -k)[-k:]
            sel = valid[p]
        else:
            sel = valid
        out[i, sel] = True
    return pd.DataFrame(out, index=score.index, columns=score.columns)


def tradable_mask(meta: dict[str, Any], idx: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(False, index=idx)
    for d0 in idx:
        d = pd.Timestamp(d0)
        c = str(meta["nq"].at[d, "nq_color"]) if d in meta["nq"].index and pd.notna(meta["nq"].at[d, "nq_color"]) else ""
        b = float(meta["breadth"].loc[d]) if d in meta["breadth"].index and pd.notna(meta["breadth"].loc[d]) else np.nan
        out.at[d] = bool(c in ("Blue", "Green") and base.breadth_bucket(b) >= 1)
    return out


def event_table(top: pd.DataFrame, close: pd.DataFrame, base_pool: pd.DataFrame, tradable: pd.Series) -> pd.DataFrame:
    idx = close.index
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    # Future 126d relative-return label, evaluation only.
    f126 = close.shift(-126) / close - 1.0
    f126_pct = f126.where(base_pool).rank(axis=1, pct=True, method="average") * 100.0
    rows = []
    last: dict[str, int] = {}
    prev = pd.Series(False, index=top.columns)
    for i, d0 in enumerate(top.index):
        d = pd.Timestamp(d0)
        cur = top.loc[d].fillna(False).astype(bool)
        adds = cur & ~prev
        for sym in adds.index[adds]:
            jlast = last.get(str(sym), -10_000)
            if i - jlast < COOLDOWN:
                continue
            last[str(sym)] = i
            rec: dict[str, Any] = {"signal_date": d, "symbol": str(sym), "market_tradable": bool(tradable.get(d, False))}
            p0 = float(close.at[d, sym]) if pd.notna(close.at[d, sym]) else np.nan
            for h in (20, 63, 126):
                j = pos.get(d, -1) + h
                p1 = float(close.iloc[j][sym]) if 0 <= j < len(idx) and pd.notna(close.iloc[j][sym]) else np.nan
                rec[f"ret{h}"] = p1 / p0 - 1.0 if np.isfinite(p0) and p0 > 0 and np.isfinite(p1) else np.nan
            fr = float(f126.at[d, sym]) if d in f126.index and sym in f126.columns and pd.notna(f126.at[d, sym]) else np.nan
            fp = float(f126_pct.at[d, sym]) if d in f126_pct.index and sym in f126_pct.columns and pd.notna(f126_pct.at[d, sym]) else np.nan
            rec["future126_return"] = fr
            rec["future126_pct"] = fp
            rec["future126_superleader"] = bool(fr >= 0.80 and fp >= 98.0) if np.isfinite(fr) and np.isfinite(fp) else np.nan
            rows.append(rec)
        prev = cur
    return pd.DataFrame(rows)


def list_stats(top: pd.DataFrame) -> dict[str, Any]:
    idx = top.index
    counts = top.sum(axis=1)
    additions = (top & ~top.shift(1).fillna(False)).sum(axis=1)
    years = pd.Series(idx.year, index=idx)
    unique_by_year = {}
    for y in sorted(years.unique()):
        z = top.loc[years == y]
        unique_by_year[str(int(y))] = int(z.columns[z.any(axis=0)].size)
    return {
        "avg_daily_count": float(counts.mean()),
        "avg_daily_additions": float(additions.mean()),
        "avg_daily_turnover_fraction": float((additions / counts.replace(0, np.nan)).mean()),
        "unique_symbols_by_year": unique_by_year,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2020-01-02")
    ap.add_argument("--analysis-end", default="2026-09-02")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD PIT inputs", flush=True)
    meta, matrices = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root, matrices)
    close = matrices["close"]
    common = disc.build_common(root, matrices)
    rs = disc.build_rs(close, common["BASE_POOL"])
    theme = disc.theme_frame(peer_ctx, close)
    comp = disc.build_factor_components(close, common, rs, theme)
    specs = disc.factor_specs(rs, comp)
    factors = {
        "CURRENT_189_THEME": specs["CURRENT_189_THEME"],
        "RS21": specs["RS21"],
        "RS63_ACCEL": specs["RS63_ACCEL"],
        "RS63_HIGH_TREND": specs["RS63_HIGH"],
    }
    # Rebuild high proximity in ABOVE200 so it is independent of SMA50>SMA200.
    prior63 = close.shift(1).rolling(63, min_periods=50).max()
    high_above200 = (close / prior63).where(common["ABOVE200"]).rank(axis=1, pct=True, method="average") * 100.0
    factors["RS63_HIGH_ABOVE200"] = (0.75 * rs[63] + 0.25 * high_above200).astype(np.float32)
    factor_masks = {
        "CURRENT_189_THEME": common["TREND_FULL"],
        "RS21": common["TREND_FULL"],
        "RS63_ACCEL": common["TREND_FULL"],
        "RS63_HIGH_TREND": common["TREND_FULL"],
        "RS63_HIGH_ABOVE200": common["ABOVE200"],
    }
    tradable = tradable_mask(meta, close.index)

    result: dict[str, Any] = {
        "status": "LEADER_RADAR_PRECISION_AUDIT",
        "design": {
            "topn": TOPN,
            "event": "new Top20 entrance with 20-session symbol cooldown",
            "future_superleader": "126-session return >=80% and cross-sectional forward-return percentile >=98; evaluation label only",
            "market_split": "current ordinary-stock tradable days vs days blocked by current NQSAR/Breadth gate",
            "no_portfolio_change": True,
        },
        "factors": {},
    }

    for name, score in factors.items():
        print(f"RADAR {name}", flush=True)
        top = top_mask(score, factor_masks[name], TOPN)
        events = event_table(top, close, common["BASE_POOL"], tradable)
        events.to_csv(out / f"events_{name}.csv", index=False)
        ls = list_stats(top)
        years = pd.to_numeric(events["signal_date"].astype(str).str[:4], errors="coerce") if not events.empty else pd.Series(dtype=float)
        result["factors"][name] = {
            "list": ls,
            "events_all": summarize_events(events),
            "events_dev_2021_2023": summarize_events(events.loc[years.between(2021, 2023)]) if len(events) else {"n": 0},
            "events_oos_2024_2026": summarize_events(events.loc[years.between(2024, 2026)]) if len(events) else {"n": 0},
            "events_tradable": summarize_events(events.loc[events["market_tradable"].astype(bool)]) if len(events) else {"n": 0},
            "events_blocked_market": summarize_events(events.loc[~events["market_tradable"].astype(bool)]) if len(events) else {"n": 0},
        }

    p = out / "summary_leader_radar_precision.json"
    p.write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADER_RADAR_PRECISION_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADER_RADAR_PRECISION_JSON ===", flush=True)


if __name__ == "__main__":
    main()

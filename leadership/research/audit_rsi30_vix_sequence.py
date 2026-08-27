from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

METHOD = "RISE_LE30_W20"
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
H = 20

EXPECTED_RECENT = [
    ("2018-02-06", "2018-02-12", "2018-02-13"),
    ("2020-02-28", "2020-03-04", "2020-03-23"),
    ("2024-08-05", "2024-08-07", "2024-08-09"),
    ("2025-04-07", "2025-04-11", "2025-04-14"),
]


def safe(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def lwma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1.0, n + 1.0)
    den = float(w.sum())
    return s.rolling(n).apply(lambda x: float(np.dot(x, w) / den), raw=True)


def load_vix(start: str, end: str) -> pd.DataFrame:
    raw = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("^VIX download returned empty frame")
    if isinstance(raw.columns, pd.MultiIndex):
        if "^VIX" in raw.columns.get_level_values(-1):
            raw = raw.xs("^VIX", axis=1, level=-1)
        else:
            raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    raw = raw.sort_index()
    need = ["High", "Close"]
    if any(c not in raw.columns for c in need):
        raise RuntimeError(f"^VIX missing columns: {raw.columns.tolist()}")
    z = raw[need].astype(float).dropna(how="all")
    return z


def add_expanding_sigma(vix: pd.DataFrame) -> pd.DataFrame:
    # Production VIX Fear Cycle convention:
    # daily ^VIX High -> monthly High from 1990; log10; completed months only.
    # Each trading day uses the distribution through the PREVIOUS completed month.
    x = vix.copy()
    month_key = x.index.to_period("M")
    monthly = x["High"].groupby(month_key).max().sort_index()
    logm = np.log10(monthly.where(monthly > 0))
    mu = logm.expanding(min_periods=12).mean()
    sig = logm.expanding(min_periods=12).std(ddof=0)
    plus1_m = 10.0 ** (mu + sig)
    plus2_m = 10.0 ** (mu + 2.0 * sig)
    # Strictly completed-month information: shift one month.
    p1_map = plus1_m.shift(1)
    p2_map = plus2_m.shift(1)
    x["plus1"] = [p1_map.get(p, np.nan) for p in month_key]
    x["plus2"] = [p2_map.get(p, np.nan) for p in month_key]
    x["lwma5"] = lwma(x["High"], 5)
    x["lwma10"] = lwma(x["High"], 10)
    x["vix_chg1"] = x["Close"].pct_change(1)
    x["vix_chg5"] = x["Close"].pct_change(5)
    x["vix_chg10"] = x["Close"].pct_change(10)
    return x


def build_sequence(vix: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    x = vix.copy()
    phase = []
    state = "NORMAL"
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for i, (d, r) in enumerate(x.iterrows()):
        hi = r["High"]
        p1 = r["plus1"]
        p2 = r["plus2"]
        w5 = r["lwma5"]
        w10 = r["lwma10"]
        prev_w5 = x["lwma5"].iloc[i - 1] if i else np.nan
        prev_w10 = x["lwma10"].iloc[i - 1] if i else np.nan
        above2 = pd.notna(hi) and pd.notna(p2) and hi > p2
        below1 = pd.notna(hi) and pd.notna(p1) and hi < p1
        w5_falling = pd.notna(w5) and pd.notna(prev_w5) and w5 < prev_w5
        cross_down = (
            pd.notna(w5) and pd.notna(w10) and pd.notna(prev_w5) and pd.notna(prev_w10)
            and w5 < w10 and prev_w5 >= prev_w10
        )

        if state in ("NORMAL", "REARM"):
            if above2:
                state = "EVENT"
                current = {"event": d, "roll": None, "bottom": None, "peak": float(hi)}
                events.append(current)
            else:
                state = "NORMAL"
        elif state == "EVENT":
            if current is not None and pd.notna(hi):
                current["peak"] = max(float(current["peak"]), float(hi))
            if w5_falling:
                state = "ROLLOVER"
                if current is not None and current["roll"] is None:
                    current["roll"] = d
        elif state == "ROLLOVER":
            if current is not None and pd.notna(hi):
                current["peak"] = max(float(current["peak"]), float(hi))
            if cross_down:
                state = "BOTTOM"
                if current is not None and current["bottom"] is None:
                    current["bottom"] = d
        elif state == "BOTTOM":
            if above2:
                state = "RE_EXTREME"
                if current is not None and pd.notna(hi):
                    current["peak"] = max(float(current["peak"]), float(hi))
            elif below1:
                state = "REARM"
        elif state == "RE_EXTREME":
            if current is not None and pd.notna(hi):
                current["peak"] = max(float(current["peak"]), float(hi))
            if below1:
                state = "REARM"

        phase.append(state)

    x["phase"] = phase
    return x, events


def validate_recent(events: list[dict[str, Any]]) -> dict[str, Any]:
    got = {
        (pd.Timestamp(e["event"]).strftime("%Y-%m-%d") if e.get("event") is not None else None): (
            pd.Timestamp(e["roll"]).strftime("%Y-%m-%d") if e.get("roll") is not None else None,
            pd.Timestamp(e["bottom"]).strftime("%Y-%m-%d") if e.get("bottom") is not None else None,
        )
        for e in events
    }
    checks = []
    for ev, ro, bo in EXPECTED_RECENT:
        actual = got.get(ev)
        ok = actual == (ro, bo)
        checks.append({"event": ev, "expected_roll": ro, "expected_bottom": bo, "actual": actual, "ok": ok})
    return {"checks": checks, "all_match": all(c["ok"] for c in checks)}


def pf(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors="coerce").dropna()
    if z.empty:
        return None
    pos = float(z[z > 0].sum())
    neg = float(-z[z < 0].sum())
    return None if neg == 0 else pos / neg


def cluster_ci(df: pd.DataFrame, cluster: str, seed: int, reps: int = 2500) -> list[float | None]:
    z = df[[cluster, "entry_20"]].dropna()
    if z.empty:
        return [None, None]
    means = z.groupby(cluster, observed=True)["entry_20"].mean().to_numpy(float)
    if len(means) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(means, size=(reps, len(means)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975])
    return [float(q[0]), float(q[1])]


def stats(g: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict[str, Any]:
    z = g.dropna(subset=["entry_20"]).copy()
    if z.empty:
        return {"n": 0}
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    p = pos.reindex(pd.to_datetime(z.signal_date)).to_numpy(float)
    z["block20"] = np.floor(p / 20.0).astype("int64")
    r = pd.to_numeric(z.entry_20, errors="coerce")
    mae = pd.to_numeric(z.mae_20, errors="coerce")
    mfe = pd.to_numeric(z.mfe_20, errors="coerce")
    q = r.quantile([0.10, 0.90, 0.95])
    return {
        "n": int(len(z)),
        "signal_dates": int(z.signal_date.nunique()),
        "themes": int(z.theme.nunique()),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "win": float((r > 0).mean()),
        "pf": pf(r),
        "mae": float(mae.mean()),
        "mfe": float(mfe.mean()),
        "p10": float(q.loc[0.10]),
        "p90": float(q.loc[0.90]),
        "p95": float(q.loc[0.95]),
        "date_ci95": cluster_ci(z, "signal_date", seed),
        "block20_ci95": cluster_ci(z, "block20", seed + 1000),
        "theme_ci95": cluster_ci(z, "theme", seed + 2000),
    }


def bins(df: pd.DataFrame) -> pd.DataFrame:
    z = df.copy()
    z["vix_level_bin"] = pd.cut(
        z.vix_close,
        [-np.inf, 20, 30, 40, np.inf],
        labels=["<20", "20-30", "30-40", ">=40"],
        right=False,
    )
    z["vix_chg5_bin"] = pd.cut(
        z.vix_chg5,
        [-np.inf, 0, 0.25, 0.50, np.inf],
        labels=["<=0%", "0-25%", "25-50%", ">=50%"],
        right=False,
    )
    z["sigma_zone"] = np.select(
        [z.vix_high < z.plus1, z.vix_high < z.plus2],
        ["BELOW_1SIG", "1_TO_2SIG"],
        default="ABOVE_2SIG",
    )
    return z


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--vix-start", default="1990-01-02")
    ap.add_argument("--vix-end", default="2026-08-27")
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    tr = pd.read_csv(args.input, compression="gzip", parse_dates=["day0_date", "signal_date", "entry_date"])
    tr = tr[tr.method.eq(METHOD)].copy()
    if tr.empty:
        raise RuntimeError(f"no {METHOD} trades in input")
    # Independent union of RS63 / RS189, same rule as focused audit.
    tr = tr.sort_values(["day0_date", "theme", "symbol", "method", "rank_type"]).drop_duplicates(
        ["day0_date", "theme", "symbol", "method"], keep="first"
    )
    tr["period"] = np.where(tr.day0_date <= DISC_END, "DISCOVERY", "CONFIRM")
    tr["signal_year"] = tr.signal_date.dt.year

    vix = add_expanding_sigma(load_vix(args.vix_start, args.vix_end))
    vix, events = build_sequence(vix)
    validation = validate_recent(events)
    (out / "sequence_validation.json").write_text(json.dumps(safe(validation), ensure_ascii=False, indent=2), encoding="utf-8")
    if not validation["all_match"]:
        print(json.dumps(safe(validation), ensure_ascii=False, indent=2), flush=True)
        raise RuntimeError("VIX Sequence reconstruction does not match production event/roll/bottom dates")

    vm = vix.reset_index().rename(columns={"Date": "signal_date", "index": "signal_date", "High": "vix_high", "Close": "vix_close"})
    keep = ["signal_date", "vix_high", "vix_close", "plus1", "plus2", "lwma5", "lwma10", "vix_chg1", "vix_chg5", "vix_chg10", "phase"]
    vm = vm[keep]
    tr = tr.merge(vm, on="signal_date", how="left", validate="many_to_one")
    if tr.vix_close.isna().any():
        missing = tr.loc[tr.vix_close.isna(), "signal_date"].drop_duplicates().astype(str).tolist()[:20]
        raise RuntimeError(f"missing VIX on signal dates: {missing}")
    tr = bins(tr)
    tr.to_csv(out / "rsi30_vix_trades.csv.gz", index=False, compression="gzip")

    summary: dict[str, Any] = {
        "method": METHOD,
        "union_dedup_rule": ["day0_date", "theme", "symbol", "method"],
        "sequence_validation": validation,
        "vix_rows": int(len(vix)),
        "vix_start": str(vix.index.min().date()),
        "vix_end": str(vix.index.max().date()),
        "production_sequence_events": [
            {k: (pd.Timestamp(v).strftime("%Y-%m-%d") if k in ("event", "roll", "bottom") and v is not None else v) for k, v in e.items()}
            for e in events
            if pd.Timestamp(e["event"]).year >= 2000
        ],
        "periods": {},
        "year_20d": {},
        "2020": {},
    }

    calendar = vix.index
    policy_masks = {
        "ALL": pd.Series(True, index=tr.index),
        "NOT_EVENT_ROLLOVER": ~tr.phase.isin(["EVENT", "ROLLOVER"]),
        "BOTTOM_REEXTREME": tr.phase.isin(["BOTTOM", "RE_EXTREME"]),
        "NORMAL_ONLY": tr.phase.eq("NORMAL"),
    }

    seed = 10000
    for period, g0 in tr.groupby("period", observed=True):
        block: dict[str, Any] = {"policies": {}, "by_phase": {}, "by_vix_level": {}, "by_vix_chg5": {}, "by_sigma_zone": {}}
        for name, mask in policy_masks.items():
            g = g0[mask.loc[g0.index]]
            block["policies"][name] = stats(g, calendar, seed); seed += 10
        for col, dest in [
            ("phase", "by_phase"),
            ("vix_level_bin", "by_vix_level"),
            ("vix_chg5_bin", "by_vix_chg5"),
            ("sigma_zone", "by_sigma_zone"),
        ]:
            for key, g in g0.groupby(col, observed=True, dropna=False):
                block[dest][str(key)] = stats(g, calendar, seed); seed += 10
        # Continuous relation, descriptive only.
        q = g0[["entry_20", "mae_20", "vix_close", "vix_chg5", "vix_high", "plus2"]].corr(method="spearman")
        block["spearman"] = {
            "ret20_vs_vix": float(q.loc["entry_20", "vix_close"]),
            "ret20_vs_vix_chg5": float(q.loc["entry_20", "vix_chg5"]),
            "mae20_vs_vix": float(q.loc["mae_20", "vix_close"]),
            "mae20_vs_vix_chg5": float(q.loc["mae_20", "vix_chg5"]),
        }
        summary["periods"][period] = block

    for y, g in tr.groupby("signal_year", observed=True):
        summary["year_20d"][str(int(y))] = {
            "all": stats(g, calendar, seed),
            "phase_counts": {str(k): int(v) for k, v in g.phase.value_counts(dropna=False).items()},
        }
        seed += 10

    g20 = tr[tr.signal_year.eq(2020)].copy()
    summary["2020"] = {
        "all": stats(g20, calendar, seed),
        "by_phase": {str(k): stats(g, calendar, seed + i * 10) for i, (k, g) in enumerate(g20.groupby("phase", observed=True))},
        "signals": g20[["signal_date", "entry_date", "theme", "symbol", "entry_20", "mae_20", "mfe_20", "vix_close", "vix_high", "vix_chg5", "phase"]]
            .sort_values(["signal_date", "entry_20"]).to_dict(orient="records"),
    }

    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("VIX_SEQUENCE_VALIDATION", json.dumps(safe(validation), ensure_ascii=False), flush=True)
    print("TRADES", len(tr), flush=True)
    for period in ("DISCOVERY", "CONFIRM"):
        if period in summary["periods"]:
            print(period, json.dumps(safe(summary["periods"][period]["policies"]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

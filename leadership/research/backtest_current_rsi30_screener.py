from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import audit_rsi_reset_portfolio as portfolio
import audit_rsi_reset_robust as prior
import audit_rsi_strength_thresholds as strength
import validate_rsi_divergence_strong as rd

COST_BPS = 5.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
SEARCH = 20
COOLDOWN = 20
HORIZONS = (5, 10, 20, 40)


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x


def trade_return(op: pd.DataFrame, cl: pd.DataFrame, sym: str, entry: int, end: int) -> float:
    if entry < 0 or end < entry or end >= len(cl):
        return np.nan
    a = op.at[cl.index[entry], sym]
    b = cl.at[cl.index[end], sym]
    if pd.isna(a) or pd.isna(b) or a <= 0:
        return np.nan
    return float(b / a - 1.0 - 2 * COST_BPS / 10000.0)


def excursions(op: pd.DataFrame, hi: pd.DataFrame, lo: pd.DataFrame,
               sym: str, entry: int, end: int) -> tuple[float, float]:
    if entry < 0 or end < entry or end >= len(hi):
        return np.nan, np.nan
    a = op.at[hi.index[entry], sym]
    if pd.isna(a) or a <= 0:
        return np.nan, np.nan
    ix = hi.index[entry:end + 1]
    return float(hi.loc[ix, sym].max() / a - 1.0), float(lo.loc[ix, sym].min() / a - 1.0)


def pf(x: pd.Series) -> float | None:
    z = pd.to_numeric(x, errors="coerce").dropna()
    pos = float(z[z > 0].sum())
    neg = float(-z[z < 0].sum())
    return None if neg == 0 else pos / neg


def cluster_ci(df: pd.DataFrame, value: str, cluster: str, seed: int, reps: int = 3000):
    z = df[[cluster, value]].dropna().groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(z) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(z, size=(reps, len(z)), replace=True).mean(axis=1)
    return [float(v) for v in np.quantile(draws, [0.025, 0.975])]


def summarize(df: pd.DataFrame, prefix: str, seed: int) -> dict:
    col = f"{prefix}_ret20"
    z = df.dropna(subset=[col]).copy()
    if z.empty:
        return {"n": 0}
    r = z[col].astype(float)
    out = {
        "n": int(len(z)),
        "events": int(z[["day0_date", "theme"]].drop_duplicates().shape[0]),
        "symbols": int(z.symbol.nunique()),
        "mean20": float(r.mean()),
        "median20": float(r.median()),
        "win20": float((r > 0).mean()),
        "pf20": pf(r),
        "p10_20": float(r.quantile(0.10)),
        "mae20": float(z[f"{prefix}_mae20"].mean()),
        "mfe20": float(z[f"{prefix}_mfe20"].mean()),
        "date_ci95": cluster_ci(z, col, f"{prefix}_signal_date", seed),
        "theme_ci95": cluster_ci(z, col, "theme", seed + 1),
        "symbol_ci95": cluster_ci(z, col, "symbol", seed + 2),
    }
    for h in (5, 10, 40):
        c = f"{prefix}_ret{h}"
        if c in z:
            x = z[c].dropna().astype(float)
            out[f"mean{h}"] = float(x.mean()) if len(x) else None
            out[f"win{h}"] = float((x > 0).mean()) if len(x) else None
    return out


def period_filter(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if period == "DISCOVERY":
        return df[df.day0_date <= DISC_END]
    if period == "CONFIRM":
        return df[df.day0_date >= CONF_START]
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    frozen = pd.read_csv(args.input, compression="gzip", parse_dates=["date"])
    # Frozen rows are already Theme Momentum activations: Theme RS>=80,
    # 20-session rank improvement>=15pt, and Theme breadth21>=60%.
    if not ((frozen.theme_rs_pct >= 80).all() and
            (frozen.theme_rank_delta20 >= 15).all() and
            (frozen.theme_breadth >= 60).all()):
        raise RuntimeError("frozen input is not the adopted activation universe")

    cand = strength.candidates(frozen)
    cand = cand[cand.RS63_TOP3].copy()
    cand = cand.sort_values(["date", "theme", "rank63", "symbol"]).drop_duplicates(
        ["date", "theme", "symbol"], keep="first")

    market = prior.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    cl, op, hi, lo = market["close"], market["open"], market["high"], market["low"]
    cal = cl.index
    cand = cand[cand.symbol.isin(cl.columns) & cand.date.isin(cal)].copy()
    rsi = rd.rsi(cl, 14)
    ret63 = cl.pct_change(63, fill_method=None)
    pos = {pd.Timestamp(d): i for i, d in enumerate(cal)}

    # Same frozen-taxonomy roster convention as the adopted strict-variant audit.
    members = {
        str(theme): sorted(set(g.symbol.astype(str)) & set(cl.columns))
        for theme, g in frozen.groupby("theme", observed=True)
    }
    top_cache: dict[tuple[pd.Timestamp, str], set[str]] = {}

    def top3_at(d: pd.Timestamp, theme: str) -> set[str]:
        key = (d, theme)
        if key in top_cache:
            return top_cache[key]
        syms = members.get(theme, [])
        if d not in ret63.index or not syms:
            top_cache[key] = set()
            return set()
        z = ret63.loc[d, syms].dropna().sort_values(ascending=False)
        top_cache[key] = set(z.head(3).index.astype(str)) if len(z) >= 3 else set()
        return top_cache[key]

    cooldown_until: dict[str, int] = defaultdict(lambda: -1)
    records = []
    for r in cand.itertuples(index=False):
        day0 = pd.Timestamp(r.date)
        theme = str(r.theme)
        sym = str(r.symbol)
        ep = pos.get(day0, -1)
        if ep < 0 or ep <= cooldown_until[sym] or sym not in rsi.columns:
            continue
        last = min(len(cal) - 2, ep + SEARCH)
        rr = rsi[sym]

        touch = None
        for j in range(ep, last + 1):
            v = rr.iloc[j]
            if pd.notna(v) and float(v) <= 30.0:
                touch = j
                break

        formal = None
        if touch is not None:
            for j in range(touch + 1, last + 1):
                a, b = rr.iloc[j], rr.iloc[j - 1]
                if pd.notna(a) and pd.notna(b) and float(a) > float(b) and sym in top3_at(cal[j], theme):
                    formal = j
                    break

        # Current screener: adopted Day0 leader + still Theme RS63 Top3 +
        # RSI<=40 + signal window alive. Formal signal today is always shown,
        # even if the one-day rebound jumps RSI above 40.
        screen = None
        for j in range(ep, last + 1):
            if formal is not None and j > formal:
                break
            v = rr.iloc[j]
            in_band = pd.notna(v) and float(v) <= 40.0 and sym in top3_at(cal[j], theme)
            if in_band or (formal is not None and j == formal):
                screen = j
                break

        if formal is not None:
            cooldown_until[sym] = formal + COOLDOWN
        if screen is None or screen + 1 >= len(cal):
            continue

        rec = {
            "day0_date": day0,
            "theme": theme,
            "symbol": sym,
            "rank_priority": int(r.rank63 - 1),
            "screen_signal_date": pd.Timestamp(cal[screen]),
            "screen_entry_date": pd.Timestamp(cal[screen + 1]),
            "screen_rsi": float(rr.iloc[screen]) if pd.notna(rr.iloc[screen]) else np.nan,
            "formal_signal": formal is not None,
            "formal_signal_date": pd.Timestamp(cal[formal]) if formal is not None else pd.NaT,
            "formal_entry_date": pd.Timestamp(cal[formal + 1]) if formal is not None and formal + 1 < len(cal) else pd.NaT,
            "formal_rsi": float(rr.iloc[formal]) if formal is not None and pd.notna(rr.iloc[formal]) else np.nan,
            "screen_to_formal_sessions": None if formal is None else int(formal - screen),
            "day0_rank63": float(r.rank63),
        }
        for h in HORIZONS:
            se = screen + 1
            end = se + h - 1
            rec[f"screen_ret{h}"] = trade_return(op, cl, sym, se, end) if end < len(cal) else np.nan
            mfe, mae = excursions(op, hi, lo, sym, se, end) if end < len(cal) else (np.nan, np.nan)
            rec[f"screen_mfe{h}"] = mfe
            rec[f"screen_mae{h}"] = mae
            if formal is not None and formal + 1 + h - 1 < len(cal):
                fe = formal + 1
                fend = fe + h - 1
                rec[f"formal_ret{h}"] = trade_return(op, cl, sym, fe, fend)
                fmfe, fmae = excursions(op, hi, lo, sym, fe, fend)
                rec[f"formal_mfe{h}"] = fmfe
                rec[f"formal_mae{h}"] = fmae
            else:
                rec[f"formal_ret{h}"] = np.nan
                rec[f"formal_mfe{h}"] = np.nan
                rec[f"formal_mae{h}"] = np.nan
        records.append(rec)

    screens = pd.DataFrame(records)
    if screens.empty:
        raise RuntimeError("no current-screener events")
    screens.to_csv(out / "current_screener_events.csv.gz", index=False, compression="gzip")

    rows = []
    summary = {
        "status": "CURRENT_RSI30_SCREENER_BACKTEST",
        "definition": {
            "activation": "Theme RS percentile>=80 + 20-session rank improvement>=15pt + Theme breadth21>=60% + Day0 Theme RS63 Top3",
            "screen": "within 20 sessions of Day0, still Theme RS63 Top3 and RSI14<=40; formal-signal-today always visible",
            "formal_entry": "RSI14<=30 once, then first RSI up-day while Theme RS63 Top3; next open",
            "cost": "5 bps per side",
            "hold_for_comparison": "5/10/20/40 sessions; adopted Reset remains fixed 20 sessions",
            "cooldown": "after formal signal, same symbol activations blocked through signal+20 sessions",
        },
        "coverage": {
            "frozen_activation_rows": int(len(frozen)),
            "day0_top3_candidates": int(len(cand)),
            "screen_events": int(len(screens)),
            "formal_signals_from_screen": int(screens.formal_signal.sum()),
            "market_download": market["diag"],
        },
        "periods": {},
        "limitations": [
            "Uses the same frozen current-taxonomy/current-universe retrospective research basis as the adopted strict-variant audit; this is not a pristine historical PIT taxonomy backtest.",
            "2022+ is confirmation, not a pristine untouched holdout, because prior RSI research inspected it.",
            "Yahoo adjusted OHLCV can differ from TradingView.",
        ],
    }

    ema21 = cl.ewm(span=21, adjust=False).mean()
    for period, lo, hi_date in (
        ("ALL", "2016-01-04", "2026-06-30"),
        ("DISCOVERY", "2016-01-04", "2021-12-31"),
        ("CONFIRM", "2022-01-03", "2026-06-30"),
    ):
        z = period_filter(screens, period)
        formal_z = z[z.formal_signal].copy()
        ix = cal[(cal >= lo) & (cal <= hi_date)]
        conversion = float(z.formal_signal.mean()) if len(z) else None
        delay = float(formal_z.screen_to_formal_sessions.median()) if len(formal_z) else None

        screen_trades = z.rename(columns={"screen_entry_date": "entry_date", "screen_rsi": "rsi_signal"}).copy()
        formal_trades = formal_z.rename(columns={"formal_entry_date": "entry_date", "formal_rsi": "rsi_signal"}).copy()
        screen_trades = screen_trades[screen_trades.entry_date.isin(ix)]
        formal_trades = formal_trades[formal_trades.entry_date.isin(ix)]
        sm, _ = portfolio.simulate(ix, op, cl, market["active"], ema21, screen_trades,
                                   0.029, 4, 20, "full", False)
        fm, _ = portfolio.simulate(ix, op, cl, market["active"], ema21, formal_trades,
                                   0.029, 4, 20, "full", False)

        block = {
            "screen": summarize(z, "screen", 900000 + len(rows) * 10),
            "conversion_to_formal": conversion,
            "screen_to_formal_median_sessions": delay,
            "formal": summarize(formal_z, "formal", 910000 + len(rows) * 10),
            "screen_buy_portfolio_2p9x4_hold20": sm,
            "formal_portfolio_2p9x4_hold20": fm,
        }
        summary["periods"][period] = block
        rows.append({"period": period, "type": "screen", "conversion": conversion, **block["screen"],
                     "portfolio_cagr": sm.get("cagr"), "portfolio_mdd": sm.get("mdd"),
                     "portfolio_accepted": sm.get("accepted")})
        rows.append({"period": period, "type": "formal", "conversion": conversion, **block["formal"],
                     "portfolio_cagr": fm.get("cagr"), "portfolio_mdd": fm.get("mdd"),
                     "portfolio_accepted": fm.get("accepted")})

    pd.DataFrame(rows).to_csv(out / "current_screener_summary.csv", index=False)
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(safe(summary), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import validate_early_rotation as er
import validate_ignition_quality as iq
import audit_rsi30_mc_nqsar as market_audit

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
N_PORT = 12
DVOL_FLOOR = 10_000_000.0
RS_MIN = 85.0
REBAL_ANCHOR = pd.Timestamp("2026-07-13")
BIO_EXCLUDE_INDUSTRIES = {"Biotechnology", "Pharmaceuticals: Other"}
BIO_KEEP_MCAP = 10_000_000_000.0
BIO_REVENUE_MAX = 50_000_000.0
EXPECTED_BASELINE = {
    "full_cagr": 0.1897,
    "full_mdd": -0.5192,
    "full_sharpe": 0.718,
    "confirmation_cagr": 0.2419,
    "confirmation_mdd": -0.2269,
}


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def metrics(equity: pd.Series) -> dict[str, Any]:
    e = pd.to_numeric(equity, errors="coerce").dropna()
    if len(e) < 5:
        return {"n": int(len(e))}
    r = e.pct_change(fill_method=None).dropna()
    years = max(len(r) / 252.0, 1.0 / 252.0)
    cagr = float((e.iloc[-1] / e.iloc[0]) ** (1.0 / years) - 1.0) if e.iloc[0] > 0 else np.nan
    dd = e / e.cummax() - 1.0
    sd = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(r.mean() / sd * np.sqrt(252.0)) if np.isfinite(sd) and sd > 0 else np.nan
    return {
        "n": int(len(e)),
        "total_return": float(e.iloc[-1] / e.iloc[0] - 1.0),
        "cagr": cagr,
        "mdd": float(dd.min()),
        "sharpe": sharpe,
        "positive_days": float((r > 0).mean()) if len(r) else None,
    }


def slice_metrics(equity: pd.Series) -> dict[str, Any]:
    e = equity.dropna()
    parts = {
        "full": e,
        "discovery": e.loc[e.index <= DISC_END],
        "confirmation": e.loc[e.index >= CONF_START],
        "2016_2019": e.loc[(e.index >= "2016-01-01") & (e.index <= "2019-12-31")],
        "2020_2021": e.loc[(e.index >= "2020-01-01") & (e.index <= "2021-12-31")],
        "2022_2023": e.loc[(e.index >= "2022-01-01") & (e.index <= "2023-12-31")],
        "2024_2026H1": e.loc[e.index >= "2024-01-01"],
    }
    return {k: metrics(v) for k, v in parts.items()}


def read_structural_bio_exclusions(root: Path, symbols: list[str]) -> set[str]:
    try:
        u = pd.read_csv(root / "universe.csv")
        sym_col = "シンボル" if "シンボル" in u.columns else u.columns[0]
        ind_col = "業種" if "業種" in u.columns else None
        mc_col = "時価総額" if "時価総額" in u.columns else None
        rev_col = "売上高TTM" if "売上高TTM" in u.columns else None
        if not ind_col or not mc_col or not rev_col:
            return set()
        u = u.drop_duplicates(sym_col).set_index(sym_col)
        idx = u.index.intersection(symbols)
        ind = u.loc[idx, ind_col].astype(str)
        mc = pd.to_numeric(u.loc[idx, mc_col], errors="coerce")
        rev = pd.to_numeric(u.loc[idx, rev_col], errors="coerce")
        # Production rule is fail-open for missing revenue.
        mask = ind.isin(BIO_EXCLUDE_INDUSTRIES) & (mc < BIO_KEEP_MCAP) & rev.notna() & (rev < BIO_REVENUE_MAX)
        return set(idx[mask])
    except Exception:
        return set()


def build_rebalance_flags(calendar: pd.DatetimeIndex) -> pd.Series:
    idx = pd.DatetimeIndex(calendar).normalize()
    flags = pd.Series(False, index=idx)
    if len(idx) == 0:
        return flags
    sessions = set(idx)
    d0 = idx.min().normalize() - pd.Timedelta(days=7)
    d1 = idx.max().normalize() + pd.Timedelta(days=7)
    mondays = pd.date_range(d0 - pd.Timedelta(days=d0.weekday()), d1, freq="7D")
    for mon in mondays:
        if ((mon.normalize() - REBAL_ANCHOR).days % 14) != 0:
            continue
        candidates = idx[(idx >= mon.normalize()) & (idx <= mon.normalize() + pd.Timedelta(days=4))]
        if len(candidates):
            flags.loc[candidates[0]] = True
    return flags


def breadth_bucket(x: float | None) -> int:
    if x is None or not np.isfinite(float(x)):
        return -1
    if x < 50.0:
        return 0
    if x < 60.0:
        return 1
    return 2


def build_inputs(root: Path, analysis_start: str, analysis_end: str, max_tickers: int, batch_size: int) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    snapshot = er.load_json(root / "sector_snapshot.json")
    theme_members_all, _ = er.extract_theme_members(snapshot)
    industry_map = er.read_industry_map(root / "industry_map.json")
    universe = er.read_universe_symbols(root / "universe.csv")
    allowed = set(industry_map) & universe
    selected = er.stratified_symbols(theme_members_all, allowed, max_tickers)
    if len(selected) < 500:
        raise RuntimeError(f"selected universe too small: {len(selected)}")
    warmup = str((pd.Timestamp(analysis_start) - pd.Timedelta(days=1150)).date())
    download_end = str((pd.Timestamp(analysis_end) + pd.Timedelta(days=10)).date())
    ohlcv, diag = iq.download_ohlcv(selected, warmup, download_end, batch_size)
    close = ohlcv["close"]
    stock_cols = [s for s in selected if s in close.columns]
    if len(stock_cols) < 500:
        raise RuntimeError(f"downloaded stock coverage too small: {len(stock_cols)}")
    ohlcv = {k: v[stock_cols].copy() for k, v in ohlcv.items()}
    close = ohlcv["close"]
    volume = ohlcv["volume"]

    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    dvol = close * vol20
    ret63 = close / close.shift(63) - 1.0
    ret189 = close / close.shift(189) - 1.0

    bio_excluded = read_structural_bio_exclusions(root, stock_cols)
    base_pool = (close >= 5.0) & (dvol >= DVOL_FLOOR)
    if bio_excluded:
        excols = [s for s in bio_excluded if s in base_pool.columns]
        base_pool.loc[:, excols] = False

    # Production RS definition: cross-sectional percentile inside tradable pool.
    rs63 = ret63.where(base_pool & ret63.notna()).rank(axis=1, pct=True) * 100.0
    rs189 = ret189.where(base_pool & ret189.notna()).rank(axis=1, pct=True) * 100.0

    new_eligible = (
        base_pool & (sma50 > sma200) & (close > sma200)
        & (rs189 >= RS_MIN) & (rs63 >= RS_MIN)
    )
    continuation_eligible = base_pool & (sma50 > sma200) & (rs189 >= RS_MIN)

    # Production all-stock >50MA breadth: denominator is only names with valid MA50;
    # coverage guard is max(floor, 45% of names observed that day).
    nobs = close.notna().sum(axis=1)
    floor = max(5, min(30, int(max(1, close.shape[1]) * 0.20)))
    v50 = sma50.notna().sum(axis=1)
    pa50 = close.gt(sma50).sum(axis=1) / v50.replace(0, np.nan) * 100.0
    pa50 = pa50.where(v50 >= np.maximum(floor, nobs * 0.45))

    analysis_idx = close.index[(close.index >= pd.Timestamp(analysis_start)) & (close.index <= pd.Timestamp(analysis_end))]
    if len(analysis_idx) < 1000:
        raise RuntimeError(f"analysis calendar too short: {len(analysis_idx)}")

    nq = market_audit.build_nqsar(str((pd.Timestamp(analysis_start) - pd.Timedelta(days=40)).date()), download_end)
    nq = nq.reindex(close.index).ffill(limit=1)

    matrices = {
        "open": ohlcv["open"],
        "close": close,
        "sma50": sma50,
        "sma200": sma200,
        "dvol": dvol,
        "rs63": rs63,
        "rs189": rs189,
        "new_eligible": new_eligible,
        "continuation_eligible": continuation_eligible,
    }
    meta = {
        "selected": len(selected),
        "downloaded": len(stock_cols),
        "bio_excluded": len(bio_excluded),
        "download": diag,
        "analysis_idx": analysis_idx,
        "breadth": pa50,
        "nq": nq,
        "rebalance": build_rebalance_flags(close.index),
    }
    return meta, matrices


def top_candidates(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], n: int = N_PORT) -> list[str]:
    elig = matrices["new_eligible"].loc[d]
    rs = matrices["rs189"].loc[d].where(elig)
    return list(rs.nlargest(n).dropna().index)


def continuation_set(d: pd.Timestamp, matrices: dict[str, pd.DataFrame], n: int = 2 * N_PORT) -> set[str]:
    elig = matrices["continuation_eligible"].loc[d]
    rs = matrices["rs189"].loc[d].where(elig)
    return set(rs.nlargest(n).dropna().index)


def simulate(
    meta: dict[str, Any], matrices: dict[str, pd.DataFrame], selective_slots: int,
    red_confirm_sessions: int = 1, immediate_red_recovery: bool = True,
) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    opens = matrices["open"]
    closes = matrices["close"]
    breadth: pd.Series = meta["breadth"]
    nq: pd.DataFrame = meta["nq"]
    rebal: pd.Series = meta["rebalance"]

    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    equities: list[tuple[pd.Timestamp, float]] = []
    trades: list[dict[str, Any]] = []
    red_run = 0

    def px_at(frame: pd.DataFrame, date: pd.Timestamp, sym: str, fallback: float | None = None) -> float | None:
        try:
            x = float(frame.at[date, sym])
            if np.isfinite(x) and x > 0:
                return x
        except Exception:
            pass
        return fallback

    def exit_symbol(sym: str, date: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        p = pos.pop(sym)
        cash += float(p["shares"]) * price
        trades.append({
            "symbol": sym,
            "entry_date": p["entry_date"],
            "exit_date": date,
            "entry_price": p["entry_price"],
            "exit_price": price,
            "return": price / float(p["entry_price"]) - 1.0,
            "entry_bucket": p["entry_bucket"],
            "exit_reason": reason,
        })

    for i, d in enumerate(idx):
        d = pd.Timestamp(d)
        if i == 0:
            prev = None
        else:
            prev = pd.Timestamp(idx[i - 1])

        # Apply signals known at previous close to today's open. No same-close execution.
        if prev is not None:
            prev_color = str(nq.at[prev, "nq_color"]) if prev in nq.index and pd.notna(nq.at[prev, "nq_color"]) else ""
            if prev_color == "Red":
                red_run += 1
            else:
                red_run = 0
            red_force = prev_color == "Red" and red_run >= max(1, red_confirm_sessions)

            # Overnight mark is naturally captured by execution prices and today's close value.
            # First process forced Red exits or ordinary stop exits.
            if red_force:
                for sym in list(pos):
                    fallback = px_at(closes, prev, sym, pos[sym]["entry_price"])
                    opx = px_at(opens, d, sym, fallback)
                    if opx is not None:
                        exit_symbol(sym, d, opx, "RED")
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px_at(closes, prev, sym, p["entry_price"])
                    if pc is None:
                        continue
                    stop = max(float(p["entry_price"]) * 0.75, float(p["peak"]) * 0.70)
                    if pc <= stop:
                        opx = px_at(opens, d, sym, pc)
                        if opx is not None:
                            exit_symbol(sym, d, opx, "WIDE_STOP")

            prev_b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = breadth_bucket(prev_b)
            is_bull = prev_color in ("Blue", "Green")
            capacity = N_PORT if is_bull and bucket == 2 else selective_slots if is_bull and bucket == 1 else 0
            scheduled = bool(rebal.get(prev, False))
            prior_color = ""
            if i >= 2:
                pp = pd.Timestamp(idx[i - 2])
                if pp in nq.index and pd.notna(nq.at[pp, "nq_color"]):
                    prior_color = str(nq.at[pp, "nq_color"])
            red_recovery = immediate_red_recovery and prior_color == "Red" and is_bull and bucket >= 1

            # Normal continuation pruning happens on the system's scheduled rebuild only.
            # Breadth capacity itself never forces a trim.
            if scheduled and not red_force:
                keep = continuation_set(prev, matrices)
                for sym in list(pos):
                    if sym not in keep:
                        pc = px_at(closes, prev, sym, pos[sym]["entry_price"])
                        opx = px_at(opens, d, sym, pc)
                        if opx is not None:
                            exit_symbol(sym, d, opx, "REBAL_CONTINUATION")

            do_fill = (scheduled or red_recovery) and (not red_force) and capacity > 0
            if do_fill and len(pos) < capacity:
                cands = top_candidates(prev, matrices, N_PORT)
                nav_open = cash
                for sym, p in pos.items():
                    fb = px_at(closes, prev, sym, p["entry_price"])
                    opx = px_at(opens, d, sym, fb)
                    if opx is not None:
                        nav_open += float(p["shares"]) * opx
                slot_cash = nav_open / N_PORT
                for sym in cands:
                    if len(pos) >= capacity or cash <= 0:
                        break
                    if sym in pos:
                        continue
                    opx = px_at(opens, d, sym, px_at(closes, prev, sym, None))
                    if opx is None:
                        continue
                    alloc = min(slot_cash, cash)
                    if alloc <= 1e-10:
                        break
                    shares = alloc / opx
                    cash -= alloc
                    pos[sym] = {
                        "shares": shares,
                        "entry_price": opx,
                        "entry_date": d,
                        "peak": opx,
                        "entry_bucket": bucket,
                    }

        nav = cash
        for sym, p in pos.items():
            fb = px_at(opens, d, sym, p["entry_price"])
            cp = px_at(closes, d, sym, fb)
            if cp is None:
                cp = float(p["entry_price"])
            p["peak"] = max(float(p["peak"]), cp)
            nav += float(p["shares"]) * cp
        equities.append((d, nav))

    eq = pd.Series(dict(equities), dtype=float).sort_index()
    tdf = pd.DataFrame(trades)
    return {
        "equity": eq,
        "metrics": slice_metrics(eq),
        "trades": tdf,
        "trade_count": int(len(tdf)),
        "selective_entry_trades": int((tdf["entry_bucket"] == 1).sum()) if len(tdf) else 0,
        "selective_entry_mean_return": float(tdf.loc[tdf["entry_bucket"] == 1, "return"].mean()) if len(tdf) and (tdf["entry_bucket"] == 1).any() else None,
    }


def rolling_252_stats(eq: pd.Series) -> dict[str, Any]:
    e = eq.dropna()
    if len(e) < 253:
        return {}
    ret = e / e.shift(252) - 1.0
    z = ret.dropna()
    return {
        "positive_rate": float((z > 0).mean()),
        "worst": float(z.min()),
        "median": float(z.median()),
        "n": int(len(z)),
    }


def bootstrap_block_win(a: pd.Series, b: pd.Series, block: int = 20, reps: int = 2000, seed: int = 20260829) -> float | None:
    x = pd.concat([a.pct_change(fill_method=None).rename("a"), b.pct_change(fill_method=None).rename("b")], axis=1).dropna()
    if len(x) < block * 5:
        return None
    diff = np.log1p(x["a"].clip(lower=-0.999999)).to_numpy() - np.log1p(x["b"].clip(lower=-0.999999)).to_numpy()
    starts = np.arange(0, len(diff) - block + 1)
    rng = np.random.default_rng(seed)
    wins = 0
    for _ in range(reps):
        out = []
        while len(out) < len(diff):
            s = int(rng.choice(starts))
            out.extend(diff[s:s + block])
        wins += float(np.sum(out[:len(diff)])) > 0.0
    return float(wins / reps)


def breadth_missingness_stress(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], reps: int = 20, keep_frac: float = 0.80, seed: int = 20260829) -> dict[str, Any]:
    close = matrices["close"]
    sma50 = matrices["sma50"]
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    base = meta["breadth"].reindex(idx)
    base_bucket = base.map(lambda x: breadth_bucket(float(x)) if pd.notna(x) else -1)
    cols = np.array(close.columns)
    rng = np.random.default_rng(seed)
    concord = []
    abs_err = []
    boundary_flip = []
    boundary = base.between(47.5, 62.5, inclusive="both")
    take_n = max(50, int(len(cols) * keep_frac))
    for _ in range(reps):
        take = list(rng.choice(cols, size=take_n, replace=False))
        c = close.loc[idx, take]
        m = sma50.loc[idx, take]
        v = m.notna().sum(axis=1)
        b = c.gt(m).sum(axis=1) / v.replace(0, np.nan) * 100.0
        buck = b.map(lambda x: breadth_bucket(float(x)) if pd.notna(x) else -1)
        valid = (base_bucket >= 0) & (buck >= 0)
        if valid.any():
            concord.append(float((base_bucket[valid] == buck[valid]).mean()))
            abs_err.append(float((base[valid] - b[valid]).abs().mean()))
        vb = valid & boundary
        if vb.any():
            boundary_flip.append(float((base_bucket[vb] != buck[vb]).mean()))
    return {
        "reps": reps,
        "keep_fraction": keep_frac,
        "bucket_concordance_mean": float(np.mean(concord)) if concord else None,
        "bucket_concordance_min": float(np.min(concord)) if concord else None,
        "breadth_mae_pp_mean": float(np.mean(abs_err)) if abs_err else None,
        "boundary_47p5_62p5_flip_rate_mean": float(np.mean(boundary_flip)) if boundary_flip else None,
        "boundary_47p5_62p5_flip_rate_max": float(np.max(boundary_flip)) if boundary_flip else None,
    }


def episode_stats(meta: dict[str, Any]) -> dict[str, Any]:
    idx: pd.DatetimeIndex = meta["analysis_idx"]
    b = meta["breadth"].reindex(idx)
    nq = meta["nq"].reindex(idx)
    bull = nq["nq_color"].isin(["Blue", "Green"])
    sel = bull & b.between(50.0, 60.0, inclusive="left")
    runs = []
    cur = 0
    for v in sel.fillna(False).to_numpy(bool):
        if v:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return {
        "selective_days": int(sel.sum()),
        "selective_share": float(sel.mean()),
        "episodes": int(len(runs)),
        "median_episode_days": float(np.median(runs)) if runs else 0.0,
        "p90_episode_days": float(np.quantile(runs, 0.90)) if runs else 0.0,
        "max_episode_days": int(max(runs)) if runs else 0,
    }


def calibration_check(base: dict[str, Any]) -> dict[str, Any]:
    m = base["metrics"]
    got = {
        "full_cagr": m["full"].get("cagr"),
        "full_mdd": m["full"].get("mdd"),
        "full_sharpe": m["full"].get("sharpe"),
        "confirmation_cagr": m["confirmation"].get("cagr"),
        "confirmation_mdd": m["confirmation"].get("mdd"),
    }
    tol = {"full_cagr": 0.03, "full_mdd": 0.06, "full_sharpe": 0.12, "confirmation_cagr": 0.04, "confirmation_mdd": 0.06}
    delta = {k: (got[k] - EXPECTED_BASELINE[k] if got[k] is not None else None) for k in EXPECTED_BASELINE}
    passed = all(delta[k] is not None and abs(delta[k]) <= tol[k] for k in tol)
    return {"passed": passed, "expected": EXPECTED_BASELINE, "got": got, "delta": delta, "tolerance": tol}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-06-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()

    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)
    meta, matrices = build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)

    variants: dict[str, dict[str, Any]] = {}
    for slots in (0, 3, 4, 6):
        key = f"SELECTIVE_{slots}_OF_12"
        print(f"SIM {key}", flush=True)
        variants[key] = simulate(meta, matrices, selective_slots=slots, red_confirm_sessions=1, immediate_red_recovery=True)

    print("SIM RED_2DAY_CONFIRM", flush=True)
    variants["RED_2DAY_CONFIRM"] = simulate(meta, matrices, selective_slots=4, red_confirm_sessions=2, immediate_red_recovery=True)
    print("SIM RECOVERY_SCHEDULED_ONLY", flush=True)
    variants["RECOVERY_SCHEDULED_ONLY"] = simulate(meta, matrices, selective_slots=4, red_confirm_sessions=1, immediate_red_recovery=False)

    base = variants["SELECTIVE_4_OF_12"]
    calibration = calibration_check(base)
    comparisons = {}
    for key in ("SELECTIVE_3_OF_12", "SELECTIVE_6_OF_12", "SELECTIVE_0_OF_12", "RED_2DAY_CONFIRM", "RECOVERY_SCHEDULED_ONLY"):
        v = variants[key]
        comparisons[key] = {
            "vs_4slot_block20_win_prob": bootstrap_block_win(v["equity"], base["equity"], block=20, reps=2000, seed=20260829 + len(comparisons) * 17),
            "full_cagr_delta": v["metrics"]["full"].get("cagr") - base["metrics"]["full"].get("cagr"),
            "full_mdd_delta": v["metrics"]["full"].get("mdd") - base["metrics"]["full"].get("mdd"),
            "full_sharpe_delta": v["metrics"]["full"].get("sharpe") - base["metrics"]["full"].get("sharpe"),
            "confirmation_cagr_delta": v["metrics"]["confirmation"].get("cagr") - base["metrics"]["confirmation"].get("cagr"),
            "confirmation_mdd_delta": v["metrics"]["confirmation"].get("mdd") - base["metrics"]["confirmation"].get("mdd"),
        }

    result = {
        "status": "ORDINARY_STOCK_MARKET_MODE_ROBUSTNESS",
        "scope": "ordinary individual-stock sleeve only; RSI30, shallow-pullback and TQQQ rules untouched",
        "execution": {
            "signal_time": "daily close",
            "trade_time": "next session open",
            "red_baseline": "first Red close -> next open full exit",
            "breadth_selective": "50<=breadth<60 constrains only new fills; never forces breadth-only trim",
            "yellow_or_breadth_lt50": "no new fills; existing names retain ordinary stop/rebalance exits",
            "red_recovery_baseline": "Red -> Blue/Green and breadth>=50 can refill next open",
            "scheduled_rebuild": "biweekly cycle anchored 2026-07-13; holiday shifted to first session",
            "normal_exit": "entry*0.75 then peak*0.70 wide close-signal, next-open exit; continuation pruning on scheduled rebuild",
        },
        "coverage": {
            "selected": meta["selected"],
            "downloaded": meta["downloaded"],
            "bio_excluded": meta["bio_excluded"],
            "analysis_sessions": int(len(meta["analysis_idx"])),
            "download": meta["download"],
        },
        "calibration_to_prior_reconstruction": calibration,
        "selective_episode_stats": episode_stats(meta),
        "breadth_missingness_stress": breadth_missingness_stress(meta, matrices, reps=20, keep_frac=0.80),
        "variants": {},
        "comparisons": comparisons,
    }
    for key, v in variants.items():
        result["variants"][key] = {
            "metrics": v["metrics"],
            "rolling252": rolling_252_stats(v["equity"]),
            "trade_count": v["trade_count"],
            "selective_entry_trades": v["selective_entry_trades"],
            "selective_entry_mean_return": v["selective_entry_mean_return"],
        }
        v["equity"].rename("equity").to_csv(out / f"equity_{key.lower()}.csv", header=True)
        if len(v["trades"]):
            v["trades"].to_csv(out / f"trades_{key.lower()}.csv", index=False)

    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== ORDINARY_STOCK_MARKET_MODE_RESULT_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_ORDINARY_STOCK_MARKET_MODE_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()

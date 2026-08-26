from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,9}$")
HORIZONS = (5, 10, 20, 63)
BASE_CONFIG = {"theme_min": 80.0, "parent_max": 60.0, "delta20_min": 15.0, "breadth_min": 60.0}


def is_ticker(value: Any) -> bool:
    return isinstance(value, str) and bool(TICKER_RE.fullmatch(value.strip().upper()))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def leaf_strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(leaf_strings(item, depth + 1))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        preferred = ("theme", "themes", "subtheme", "subthemes", "name", "label")
        for key in preferred:
            if key in value:
                out.extend(leaf_strings(value[key], depth + 1))
        if out:
            return out
        for item in value.values():
            out.extend(leaf_strings(item, depth + 1))
        return out
    return []


def ticker_map_candidates(node: Any, path: str = "root", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 5:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        ticker_items = [(str(k).upper(), v) for k, v in node.items() if is_ticker(k)]
        if len(ticker_items) >= 50 and len(ticker_items) >= max(50, int(len(node) * 0.45)):
            mapping: dict[str, list[str]] = {}
            for sym, value in ticker_items:
                vals = []
                seen: set[str] = set()
                for s in leaf_strings(value):
                    if not s or is_ticker(s) or s in seen:
                        continue
                    seen.add(s)
                    vals.append(s)
                if vals:
                    mapping[sym] = vals
            unique = sorted({x for vals in mapping.values() for x in vals})
            if mapping:
                out.append({"path": path, "mapping": mapping, "mapped": len(mapping), "unique": len(unique)})
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                out.extend(ticker_map_candidates(value, f"{path}.{key}", depth + 1))
    elif isinstance(node, list):
        for i, value in enumerate(node[:200]):
            if isinstance(value, (dict, list)):
                out.extend(ticker_map_candidates(value, f"{path}[{i}]", depth + 1))
    return out


def extract_theme_members(snapshot: Any) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    candidates = ticker_map_candidates(snapshot)
    diagnostics = [{k: c[k] for k in ("path", "mapped", "unique")} for c in candidates]
    plausible = [c for c in candidates if 200 <= c["unique"] <= 800]
    if not plausible:
        raise RuntimeError(f"No plausible ticker→subtheme map found. candidates={diagnostics[:20]}")
    chosen = min(plausible, key=lambda c: (abs(c["unique"] - 367), -c["mapped"]))
    theme_members: dict[str, list[str]] = defaultdict(list)
    for sym, themes in chosen["mapping"].items():
        for theme in themes:
            theme_members[theme].append(sym)
    return {k: sorted(set(v)) for k, v in theme_members.items()}, diagnostics + [{"chosen": chosen["path"], "mapped": chosen["mapped"], "unique": chosen["unique"]}]


def read_industry_map(path: Path) -> dict[str, tuple[str, str]]:
    raw = load_json(path)
    mapping = raw.get("map", raw) if isinstance(raw, dict) else {}
    out: dict[str, tuple[str, str]] = {}
    if not isinstance(mapping, dict):
        return out
    for sym, pair in mapping.items():
        if not is_ticker(sym):
            continue
        sector = industry = ""
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            sector, industry = str(pair[0] or ""), str(pair[1] or "")
        elif isinstance(pair, dict):
            sector = str(pair.get("sector") or pair.get("Sector") or "")
            industry = str(pair.get("industry") or pair.get("Industry") or "")
        if industry:
            out[str(sym).upper()] = (sector, industry)
    return out


def read_universe_symbols(path: Path) -> set[str]:
    out: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sym = str(row.get("シンボル") or row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if is_ticker(sym):
                out.add(sym)
    return out


def stratified_symbols(theme_members: dict[str, list[str]], allowed: set[str], maximum: int) -> list[str]:
    pools = {theme: [s for s in members if s in allowed] for theme, members in theme_members.items()}
    chosen: list[str] = []
    seen: set[str] = set()
    round_n = 0
    while len(chosen) < maximum:
        added = False
        for theme in sorted(pools):
            pool = pools[theme]
            if round_n < len(pool):
                sym = pool[round_n]
                if sym not in seen:
                    seen.add(sym)
                    chosen.append(sym)
                    added = True
                    if len(chosen) >= maximum:
                        break
        if not added:
            break
        round_n += 1
    return chosen


def yahoo_symbol(sym: str) -> str:
    return sym.replace(".", "-")


def download_adjusted_close(symbols: list[str], start: str, end: str, batch_size: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    failed_batches: list[list[str]] = []
    requested = list(dict.fromkeys(symbols))
    for pos in range(0, len(requested), batch_size):
        batch = requested[pos: pos + batch_size]
        yf_names = [yahoo_symbol(s) for s in batch]
        reverse = {yahoo_symbol(s): s for s in batch}
        try:
            raw = yf.download(
                yf_names,
                start=start,
                end=end,
                auto_adjust=False,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
                timeout=30,
            )
        except Exception:
            failed_batches.append(batch)
            continue
        if raw is None or len(raw) == 0:
            failed_batches.append(batch)
            continue
        cols: dict[str, pd.Series] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            level0 = set(str(x) for x in raw.columns.get_level_values(0))
            for ysym in yf_names:
                if ysym not in level0:
                    continue
                part = raw[ysym]
                field = "Adj Close" if "Adj Close" in part.columns else ("Close" if "Close" in part.columns else None)
                if field:
                    cols[reverse[ysym]] = pd.to_numeric(part[field], errors="coerce")
        else:
            field = "Adj Close" if "Adj Close" in raw.columns else ("Close" if "Close" in raw.columns else None)
            if field and len(batch) == 1:
                cols[batch[0]] = pd.to_numeric(raw[field], errors="coerce")
        if cols:
            frames.append(pd.DataFrame(cols))
        print(f"DOWNLOAD {min(pos + batch_size, len(requested))}/{len(requested)} columns={sum(f.shape[1] for f in frames)}", flush=True)
    if not frames:
        raise RuntimeError("Yahoo download returned no usable adjusted-close data")
    close = pd.concat(frames, axis=1)
    close = close.loc[:, ~close.columns.duplicated()].sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.replace([np.inf, -np.inf], np.nan)
    diag = {
        "requested": len(requested),
        "downloaded": int(close.shape[1]),
        "rows": int(close.shape[0]),
        "start": str(close.index.min().date()),
        "end": str(close.index.max().date()),
        "failed_batches": len(failed_batches),
    }
    return close, diag


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    ret = close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    ret = ret.where(ret > -0.999999)
    return np.log1p(ret)


def grouped_equal_weight(logret: pd.DataFrame, groups: dict[str, list[str]], min_daily: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    values: dict[str, pd.Series] = {}
    counts: dict[str, pd.Series] = {}
    for name, members in groups.items():
        cols = [s for s in members if s in logret.columns]
        if len(cols) < min_daily:
            continue
        part = logret[cols]
        count = part.notna().sum(axis=1)
        series = part.mean(axis=1, skipna=True).where(count >= min_daily)
        values[name] = series
        counts[name] = count
    return pd.DataFrame(values), pd.DataFrame(counts)


def period_return_from_log(logret: pd.DataFrame | pd.Series, window: int, min_ratio: float = 0.8):
    min_periods = max(1, int(math.ceil(window * min_ratio)))
    sums = logret.rolling(window, min_periods=min_periods).sum()
    return np.expm1(sums)


def forward_return_from_log(logret: pd.DataFrame | pd.Series, horizon: int, min_ratio: float = 0.8):
    shifted = logret.shift(-1)
    rev = shifted.iloc[::-1]
    min_periods = max(1, int(math.ceil(horizon * min_ratio)))
    sums = rev.rolling(horizon, min_periods=min_periods).sum().iloc[::-1]
    return np.expm1(sums)


def build_parent_weights(theme_members: dict[str, list[str]], industry_map: dict[str, tuple[str, str]], max_industries: int = 3) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for theme, members in theme_members.items():
        counts = Counter(industry_map[s][1] for s in members if s in industry_map and industry_map[s][1])
        top = counts.most_common(max_industries)
        total = sum(n for _, n in top)
        if total:
            out[theme] = [(industry, n / total) for industry, n in top]
    return out


def weighted_matrix(source: pd.DataFrame, weights: dict[str, list[tuple[str, float]]], columns: list[str]) -> pd.DataFrame:
    out: dict[str, pd.Series] = {}
    for name in columns:
        pairs = [(key, w) for key, w in weights.get(name, []) if key in source.columns]
        if not pairs:
            continue
        num = pd.Series(0.0, index=source.index)
        den = pd.Series(0.0, index=source.index)
        for key, w in pairs:
            s = source[key]
            ok = s.notna()
            num = num.add(s.fillna(0.0) * w, fill_value=0.0)
            den = den.add(ok.astype(float) * w, fill_value=0.0)
        out[name] = (num / den.replace(0.0, np.nan)).where(den > 0)
    return pd.DataFrame(out)


def breadth_above_ema21(close: pd.DataFrame, theme_members: dict[str, list[str]], min_daily: int) -> pd.DataFrame:
    ema = close.ewm(span=21, adjust=False, min_periods=15).mean()
    valid = close.notna() & ema.notna()
    above = (close > ema).where(valid)
    out: dict[str, pd.Series] = {}
    for theme, members in theme_members.items():
        cols = [s for s in members if s in close.columns]
        if len(cols) < min_daily:
            continue
        part = above[cols]
        count = part.notna().sum(axis=1)
        out[theme] = (part.mean(axis=1, skipna=True) * 100.0).where(count >= min_daily)
    return pd.DataFrame(out)


def event_mask(theme_pct: pd.DataFrame, parent_pct: pd.DataFrame, breadth: pd.DataFrame, config: dict[str, float]) -> pd.DataFrame:
    common = theme_pct.columns.intersection(parent_pct.columns).intersection(breadth.columns)
    t = theme_pct[common]
    p = parent_pct[common]
    b = breadth[common]
    delta = t - t.shift(20)
    return (t >= config["theme_min"]) & (p < config["parent_max"]) & (delta >= config["delta20_min"]) & (b >= config["breadth_min"])


def extract_events(mask: pd.DataFrame, theme_pct: pd.DataFrame, parent_pct: pd.DataFrame, breadth: pd.DataFrame, member_counts: dict[str, int], analysis_start: pd.Timestamp, analysis_end: pd.Timestamp, cooldown: int = 20) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for theme in mask.columns:
        active = mask[theme].fillna(False)
        last_pos = -10_000
        for pos, (date, value) in enumerate(active.items()):
            if date < analysis_start or date > analysis_end or not bool(value):
                continue
            previous = bool(active.iloc[pos - 1]) if pos > 0 else False
            if previous or pos - last_pos < cooldown:
                continue
            last_pos = pos
            rows.append({
                "date": date,
                "theme": theme,
                "theme_rs_pct": float(theme_pct.at[date, theme]),
                "parent_rs_pct": float(parent_pct.at[date, theme]),
                "rank_delta20": float(theme_pct.at[date, theme] - theme_pct[theme].shift(20).at[date]),
                "breadth": float(breadth.at[date, theme]),
                "members_current_taxonomy": int(member_counts.get(theme, 0)),
            })
    return pd.DataFrame(rows).sort_values(["date", "theme"]).reset_index(drop=True) if rows else pd.DataFrame(columns=["date", "theme"])


def clustered_bootstrap(values: pd.DataFrame, metric: str, seed: int = 38, reps: int = 4000) -> dict[str, Any]:
    use = values[["date", metric]].dropna()
    if use.empty:
        return {"n": 0, "dates": 0, "mean": None, "median": None, "ci95": [None, None]}
    by_date = use.groupby("date", observed=True)[metric].mean()
    arr = by_date.to_numpy(float)
    rng = np.random.default_rng(seed)
    samples = rng.choice(arr, size=(reps, len(arr)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return {
        "n": int(len(use)),
        "dates": int(len(arr)),
        "mean": float(use[metric].mean()),
        "median": float(use[metric].median()),
        "ci95": [float(lo), float(hi)],
        "positive_rate": float((use[metric] > 0).mean()),
    }


def attach_outcomes(events: pd.DataFrame, horizons: tuple[int, ...], theme_fwd: dict[int, pd.DataFrame], spy_fwd: dict[int, pd.Series], parent_fwd: dict[int, pd.DataFrame], theme_pct: pd.DataFrame, parent_pct: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    rows: list[dict[str, Any]] = []
    for event in events.to_dict("records"):
        date = pd.Timestamp(event["date"])
        theme = str(event["theme"])
        row = dict(event)
        pos = theme_pct.index.get_indexer([date])[0]
        for h in horizons:
            tr = theme_fwd[h].at[date, theme] if theme in theme_fwd[h].columns and date in theme_fwd[h].index else np.nan
            sr = spy_fwd[h].at[date] if date in spy_fwd[h].index else np.nan
            pr = parent_fwd[h].at[date, theme] if theme in parent_fwd[h].columns and date in parent_fwd[h].index else np.nan
            med = theme_fwd[h].loc[date].median(skipna=True) if date in theme_fwd[h].index else np.nan
            future_pos = pos + h if pos >= 0 else -1
            future_rs = theme_pct.iloc[future_pos][theme] if 0 <= future_pos < len(theme_pct) and theme in theme_pct.columns else np.nan
            future_parent = parent_pct.iloc[future_pos][theme] if 0 <= future_pos < len(parent_pct) and theme in parent_pct.columns else np.nan
            row[f"theme_ret_{h}"] = tr
            row[f"spy_excess_{h}"] = tr - sr if pd.notna(tr) and pd.notna(sr) else np.nan
            row[f"parent_excess_{h}"] = tr - pr if pd.notna(tr) and pd.notna(pr) else np.nan
            row[f"median_theme_excess_{h}"] = tr - med if pd.notna(tr) and pd.notna(med) else np.nan
            row[f"rs_delta_{h}"] = future_rs - row["theme_rs_pct"] if pd.notna(future_rs) else np.nan
            row[f"top20_retained_{h}"] = float(future_rs >= 80.0) if pd.notna(future_rs) else np.nan
            row[f"parent_top20_{h}"] = float(future_parent >= 80.0) if pd.notna(future_parent) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_outcomes(outcomes: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for h in HORIZONS:
        metrics = {}
        for metric in (f"spy_excess_{h}", f"parent_excess_{h}", f"median_theme_excess_{h}", f"rs_delta_{h}"):
            metrics[metric] = clustered_bootstrap(outcomes, metric)
        for metric in (f"top20_retained_{h}", f"parent_top20_{h}"):
            use = outcomes[metric].dropna() if metric in outcomes else pd.Series(dtype=float)
            metrics[metric] = {"n": int(len(use)), "rate": float(use.mean()) if len(use) else None}
        core_a = metrics[f"spy_excess_{h}"]["ci95"][0]
        core_b = metrics[f"parent_excess_{h}"]["ci95"][0]
        metrics["core_significant_positive"] = bool(core_a is not None and core_b is not None and core_a > 0 and core_b > 0)
        summary[str(h)] = metrics
    return summary


def regime_table(outcomes: pd.DataFrame) -> list[dict[str, Any]]:
    regimes = [("2016-2019", "2016-01-01", "2019-12-31"), ("2020-2022", "2020-01-01", "2022-12-31"), ("2023-2026H1", "2023-01-01", "2026-06-30")]
    rows = []
    for label, start, end in regimes:
        use = outcomes[(outcomes["date"] >= pd.Timestamp(start)) & (outcomes["date"] <= pd.Timestamp(end))]
        for h in (20, 63):
            col = f"spy_excess_{h}"
            vals = use[col].dropna() if col in use else pd.Series(dtype=float)
            rows.append({"regime": label, "horizon": h, "n": int(len(vals)), "mean_spy_excess": float(vals.mean()) if len(vals) else None, "win_rate": float((vals > 0).mean()) if len(vals) else None})
    return rows


def sensitivity_table(theme_pct: pd.DataFrame, parent_pct: pd.DataFrame, breadth: pd.DataFrame, member_counts: dict[str, int], analysis_start: pd.Timestamp, analysis_end: pd.Timestamp, theme_fwd20: pd.DataFrame, spy_fwd20: pd.Series, parent_fwd20: pd.DataFrame) -> list[dict[str, Any]]:
    variants: list[tuple[str, dict[str, float]]] = [("base", dict(BASE_CONFIG))]
    for key, values in {
        "theme_min": (75.0, 85.0),
        "parent_max": (50.0, 70.0),
        "delta20_min": (10.0, 20.0),
        "breadth_min": (50.0, 70.0),
    }.items():
        for value in values:
            cfg = dict(BASE_CONFIG)
            cfg[key] = value
            variants.append((f"{key}={value:g}", cfg))
    rows: list[dict[str, Any]] = []
    for label, cfg in variants:
        events = extract_events(event_mask(theme_pct, parent_pct, breadth, cfg), theme_pct, parent_pct, breadth, member_counts, analysis_start, analysis_end)
        if events.empty:
            rows.append({"variant": label, "events": 0, "dates": 0, "mean_spy_excess20": None, "mean_parent_excess20": None})
            continue
        temp = attach_outcomes(events, (20,), {20: theme_fwd20}, {20: spy_fwd20}, {20: parent_fwd20}, theme_pct, parent_pct)
        a = clustered_bootstrap(temp, "spy_excess_20", reps=2000)
        b = clustered_bootstrap(temp, "parent_excess_20", reps=2000)
        rows.append({
            "variant": label,
            "events": int(len(temp)),
            "dates": int(temp["date"].nunique()),
            "mean_spy_excess20": a["mean"],
            "spy_ci_low": a["ci95"][0],
            "mean_parent_excess20": b["mean"],
            "parent_ci_low": b["ci95"][0],
        })
    return rows


def safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="leadership/research/output")
    parser.add_argument("--analysis-start", default="2016-01-04")
    parser.add_argument("--analysis-end", default="2026-06-20")
    parser.add_argument("--max-tickers", type=int, default=1500)
    parser.add_argument("--batch-size", type=int, default=75)
    parser.add_argument("--min-members", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    snapshot = load_json(root / "sector_snapshot.json")
    theme_members_all, taxonomy_candidates = extract_theme_members(snapshot)
    industry_map = read_industry_map(root / "industry_map.json")
    universe = read_universe_symbols(root / "universe.csv")

    eligible_symbols = set(industry_map) & universe
    selected = stratified_symbols(theme_members_all, eligible_symbols, args.max_tickers)
    # SPY is always required as the benchmark.
    requested = selected + (["SPY"] if "SPY" not in selected else [])
    download_start = str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=320)).date())
    download_end = str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=100)).date())
    close, download_diag = download_adjusted_close(requested, download_start, download_end, args.batch_size)
    if "SPY" not in close.columns:
        raise RuntimeError("SPY benchmark missing from Yahoo download")

    stock_cols = [s for s in selected if s in close.columns]
    stock_close = close[stock_cols]
    stock_log = log_returns(stock_close)
    spy_log = log_returns(close[["SPY"]])["SPY"]

    theme_members = {theme: [s for s in members if s in stock_cols] for theme, members in theme_members_all.items()}
    member_counts = {theme: len(members) for theme, members in theme_members.items()}
    theme_log, _ = grouped_equal_weight(stock_log, theme_members, args.min_members)

    industry_groups: dict[str, list[str]] = defaultdict(list)
    for sym in stock_cols:
        pair = industry_map.get(sym)
        if pair and pair[1]:
            industry_groups[pair[1]].append(sym)
    industry_log, _ = grouped_equal_weight(stock_log, dict(industry_groups), args.min_members)

    parent_weights = build_parent_weights(theme_members_all, industry_map, max_industries=3)
    common_themes = sorted(set(theme_log.columns) & set(parent_weights))
    theme_log = theme_log[common_themes]

    theme_63 = period_return_from_log(theme_log, 63)
    spy_63 = period_return_from_log(spy_log, 63)
    theme_rel63 = theme_63.sub(spy_63, axis=0)
    theme_pct = theme_rel63.rank(axis=1, pct=True, method="average") * 100.0

    industry_63 = period_return_from_log(industry_log, 63)
    industry_rel63 = industry_63.sub(spy_63, axis=0)
    industry_pct = industry_rel63.rank(axis=1, pct=True, method="average") * 100.0
    parent_pct = weighted_matrix(industry_pct, parent_weights, common_themes)
    parent_log = weighted_matrix(industry_log, parent_weights, common_themes)

    breadth = breadth_above_ema21(stock_close, theme_members, args.min_members)
    breadth = breadth.reindex(columns=common_themes)

    theme_fwd = {h: forward_return_from_log(theme_log, h) for h in HORIZONS}
    spy_fwd = {h: forward_return_from_log(spy_log, h) for h in HORIZONS}
    parent_fwd = {h: forward_return_from_log(parent_log, h) for h in HORIZONS}

    analysis_start = pd.Timestamp(args.analysis_start)
    analysis_end = pd.Timestamp(args.analysis_end)
    base_mask = event_mask(theme_pct, parent_pct, breadth, BASE_CONFIG)
    events = extract_events(base_mask, theme_pct, parent_pct, breadth, member_counts, analysis_start, analysis_end)
    outcomes = attach_outcomes(events, HORIZONS, theme_fwd, spy_fwd, parent_fwd, theme_pct, parent_pct)
    summary = summarize_outcomes(outcomes)
    sensitivity = sensitivity_table(theme_pct, parent_pct, breadth, member_counts, analysis_start, analysis_end, theme_fwd[20], spy_fwd[20], parent_fwd[20])
    regimes = regime_table(outcomes) if not outcomes.empty else []

    graph_diag = {
        "themes_current_taxonomy": len(theme_members_all),
        "themes_with_downloaded_min_members": int(len(theme_log.columns)),
        "industries_with_downloaded_min_members": int(len(industry_log.columns)),
        "selected_stock_symbols": len(selected),
        "downloaded_stock_symbols": len(stock_cols),
        "themes_member_ge3": int(sum(n >= 3 for n in member_counts.values())),
        "themes_member_ge5": int(sum(n >= 5 for n in member_counts.values())),
        "themes_member_ge10": int(sum(n >= 10 for n in member_counts.values())),
    }
    result = {
        "status": "PRELIMINARY_FIXED_CURRENT_TAXONOMY",
        "bias_warning": "Current ticker→theme and ticker→industry memberships are applied retrospectively. This is hypothesis filtering, not final survivorship/look-ahead-free proof.",
        "signal_definition_frozen_before_outcomes": BASE_CONFIG,
        "event_policy": "first condition day after inactive state, 20-trading-day per-theme cooldown",
        "theme_index": "equal-weight daily constituent log returns; no market-cap weighting",
        "parent": "top 1-3 current TradingView industries by constituent count, weighted by current constituent share",
        "rs_definition": "63-trading-day theme or industry return minus SPY 63d return, cross-sectional percentile",
        "breadth_definition": "share of available current constituents above EMA21",
        "analysis_window": [args.analysis_start, args.analysis_end],
        "download": download_diag,
        "taxonomy_candidates": taxonomy_candidates,
        "coverage": graph_diag,
        "events": int(len(outcomes)),
        "event_dates": int(outcomes["date"].nunique()) if not outcomes.empty else 0,
        "horizons": summary,
        "regimes": regimes,
        "sensitivity_20d_one_factor_only": sensitivity,
    }

    outcomes.to_csv(output / "events_with_outcomes.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(output / "sensitivity_20d.csv", index=False)
    pd.DataFrame(regimes).to_csv(output / "regimes.csv", index=False)
    (output / "summary.json").write_text(json.dumps(safe_json(result), ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== EARLY_ROTATION_RESULT_JSON ===")
    print(json.dumps(safe_json(result), ensure_ascii=False, indent=2))
    print("=== END_EARLY_ROTATION_RESULT_JSON ===", flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Iterable

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests

SEEDS = (11, 37, 71, 149)
TRAIN_END = pd.Timestamp("2021-09-30")
HOLDOUT_START = pd.Timestamp("2022-01-03")
COST_BPS_SIDE = 5.0
MIN_POOL = 3
HORIZONS = (20, 40, 63)

TECH_FEATURES = [
    "theme_rs_pct", "theme_rank_delta20", "theme_breadth", "parent_rs_pct",
    "theme_member_count", "theme_disp20", "theme_disp63",
    "close_location", "rvol20", "signed_rvol20", "ema21_atr", "sma50_atr",
    "dist_prior_high20", "dist_prior_high63", "compression_5v20", "gap_pct",
    "ret5", "ret10", "ret20", "ret63", "ret126", "ret189",
    "vol20", "vol63", "atr_pct", "dist_high252", "dollar_volume20_log",
    "ret5_rank", "ret10_rank", "ret20_rank", "ret63_rank", "ret126_rank",
    "ret189_rank", "vol20_rank", "rvol20_rank", "compression_rank", "high63_rank",
]

FUND_FEATURES = [
    "sec_has_data", "sec_days_since_filing", "sec_recent_30", "sec_recent_60",
    "rev_yoy", "rev_accel_pp", "rev_accel_confirmed",
    "ni_yoy", "ni_accel_pp", "ni_turnaround",
    "eps_yoy", "eps_accel_pp", "eps_turnaround",
    "op_margin", "op_margin_yoy_pp",
    "gross_margin", "gross_margin_yoy_pp",
]

METRIC_SPECS = {
    "revenue": {
        "tags": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "units": ("USD",),
    },
    "net_income": {"tags": ("NetIncomeLoss",), "units": ("USD",)},
    "eps": {"tags": ("EarningsPerShareDiluted",), "units": ("USD/shares",)},
    "operating_income": {"tags": ("OperatingIncomeLoss",), "units": ("USD",)},
    "gross_profit": {"tags": ("GrossProfit",), "units": ("USD",)},
}


def safe_num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if np.isfinite(x) else np.nan


def sec_session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    })
    return s


def load_ticker_map(session: requests.Session, user_agent: str) -> dict[str, str]:
    r = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=60,
    )
    r.raise_for_status()
    payload = r.json()
    out = {}
    for item in payload.values():
        ticker = str(item.get("ticker", "")).upper().strip()
        cik = item.get("cik_str")
        if ticker and cik is not None:
            out[ticker] = f"{int(cik):010d}"
    return out


def normalize_ticker(ticker: str) -> tuple[str, ...]:
    x = str(ticker).upper().strip()
    variants = [x]
    if "." in x:
        variants.append(x.replace(".", "-"))
    if "-" in x:
        variants.append(x.replace("-", "."))
    return tuple(dict.fromkeys(variants))


def fetch_companyfacts(
    session: requests.Session,
    cik: str,
    cache_dir: Path,
    min_interval: float = 0.12,
) -> dict | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"CIK{cik}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            path.unlink(missing_ok=True)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    for attempt in range(4):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            time.sleep(min_interval)
            return data
        except Exception:
            if attempt == 3:
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def choose_metric_entries(companyfacts: dict, tags: Iterable[str], units: Iterable[str]) -> pd.DataFrame:
    gaap = (((companyfacts or {}).get("facts") or {}).get("us-gaap") or {})
    best = None
    best_score = -1
    for tag in tags:
        node = gaap.get(tag) or {}
        unit_map = node.get("units") or {}
        for unit in units:
            vals = unit_map.get(unit) or []
            rows = []
            for x in vals:
                form = str(x.get("form", ""))
                if form not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}:
                    continue
                start = pd.to_datetime(x.get("start"), errors="coerce")
                end = pd.to_datetime(x.get("end"), errors="coerce")
                filed = pd.to_datetime(x.get("filed"), errors="coerce")
                val = safe_num(x.get("val"))
                if pd.isna(start) or pd.isna(end) or pd.isna(filed) or not np.isfinite(val):
                    continue
                duration = int((end - start).days)
                if 55 <= duration <= 125:
                    rows.append({
                        "start": start, "end": end, "filed": filed, "value": val,
                        "duration": duration, "form": form, "tag": tag, "unit": unit,
                    })
            if rows:
                z = pd.DataFrame(rows)
                score = z["end"].nunique()
                if score > best_score:
                    best = z
                    best_score = score
    if best is None:
        return pd.DataFrame(columns=["start", "end", "filed", "value", "duration", "form", "tag", "unit"])
    return best.sort_values(["end", "filed"]).reset_index(drop=True)


def point_in_time_quarters(entries: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    if entries.empty:
        return entries.copy()
    z = entries[(entries["filed"] <= asof) & (entries["end"] <= asof)].copy()
    if z.empty:
        return z
    z = z.sort_values(["end", "filed"]).groupby("end", as_index=False).tail(1)
    return z.sort_values("end").reset_index(drop=True)


def nearest_prior(q: pd.DataFrame, end: pd.Timestamp, low_days: int, high_days: int):
    if q.empty:
        return None
    delta = (end - q["end"]).dt.days
    cand = q[(delta >= low_days) & (delta <= high_days)].copy()
    if cand.empty:
        return None
    cand["dist"] = (delta.loc[cand.index] - (low_days + high_days) / 2).abs()
    return cand.sort_values(["dist", "end"], ascending=[True, False]).iloc[0]


def growth(cur: float, prev: float) -> tuple[float, float]:
    if not np.isfinite(cur) or not np.isfinite(prev):
        return np.nan, np.nan
    if cur > 0 and prev > 0:
        return (cur / prev - 1.0) * 100.0, 0.0
    if prev <= 0 < cur:
        return np.nan, 1.0
    return np.nan, 0.0


def metric_snapshot(entries: pd.DataFrame, asof: pd.Timestamp) -> dict:
    q = point_in_time_quarters(entries, asof)
    if q.empty:
        return {
            "latest_end": pd.NaT, "latest_filed": pd.NaT, "latest": np.nan,
            "yoy": np.nan, "accel_pp": np.nan, "accel_confirmed": np.nan,
            "turnaround": np.nan, "yago": np.nan,
        }
    latest = q.iloc[-1]
    yago = nearest_prior(q.iloc[:-1], latest["end"], 315, 410)
    yoy, turnaround = growth(safe_num(latest["value"]), safe_num(yago["value"]) if yago is not None else np.nan)

    prev = nearest_prior(q.iloc[:-1], latest["end"], 55, 145)
    prev_yoy = np.nan
    accel = np.nan
    confirmed = np.nan
    if prev is not None:
        prev_candidates = q[q["end"] < prev["end"]]
        prev_yago = nearest_prior(prev_candidates, prev["end"], 315, 410)
        prev_yoy, _ = growth(
            safe_num(prev["value"]),
            safe_num(prev_yago["value"]) if prev_yago is not None else np.nan,
        )
        if np.isfinite(yoy) and np.isfinite(prev_yoy):
            accel = yoy - prev_yoy
            confirmed = float(accel > 0)
    return {
        "latest_end": latest["end"], "latest_filed": latest["filed"], "latest": safe_num(latest["value"]),
        "yoy": yoy, "accel_pp": accel, "accel_confirmed": confirmed,
        "turnaround": turnaround, "yago": safe_num(yago["value"]) if yago is not None else np.nan,
    }


def margin_snapshot(
    numerator_entries: pd.DataFrame,
    revenue_entries: pd.DataFrame,
    asof: pd.Timestamp,
) -> tuple[float, float]:
    n = point_in_time_quarters(numerator_entries, asof)
    r = point_in_time_quarters(revenue_entries, asof)
    if n.empty or r.empty:
        return np.nan, np.nan
    n_latest = n.iloc[-1]
    match = r[r["end"] == n_latest["end"]]
    if match.empty:
        return np.nan, np.nan
    r_latest = match.iloc[-1]
    if not np.isfinite(r_latest["value"]) or r_latest["value"] == 0:
        return np.nan, np.nan
    margin = float(n_latest["value"] / r_latest["value"] * 100.0)

    n_yago = nearest_prior(n.iloc[:-1], n_latest["end"], 315, 410)
    r_yago = nearest_prior(r[r["end"] < r_latest["end"]], r_latest["end"], 315, 410)
    if n_yago is None or r_yago is None or not np.isfinite(r_yago["value"]) or r_yago["value"] == 0:
        return margin, np.nan
    yago_margin = float(n_yago["value"] / r_yago["value"] * 100.0)
    return margin, margin - yago_margin


def build_sec_feature_rows(
    rows: pd.DataFrame,
    ticker_map: dict[str, str],
    session: requests.Session,
    cache_dir: Path,
) -> tuple[pd.DataFrame, dict]:
    symbols = sorted(rows["symbol"].astype(str).unique())
    event_dates = {
        s: sorted(pd.to_datetime(rows.loc[rows.symbol.astype(str) == s, "date"].unique()))
        for s in symbols
    }
    records = []
    stats = {"symbols": len(symbols), "mapped": 0, "companyfacts_ok": 0, "companyfacts_missing": 0}
    for i, symbol in enumerate(symbols, 1):
        cik = None
        for v in normalize_ticker(symbol):
            if v in ticker_map:
                cik = ticker_map[v]
                break
        if cik is None:
            for d in event_dates[symbol]:
                records.append({"date": d, "symbol": symbol, "sec_has_data": 0.0})
            continue
        stats["mapped"] += 1
        cf = fetch_companyfacts(session, cik, cache_dir)
        if not cf:
            stats["companyfacts_missing"] += 1
            for d in event_dates[symbol]:
                records.append({"date": d, "symbol": symbol, "sec_has_data": 0.0})
            continue
        stats["companyfacts_ok"] += 1
        metric_entries = {
            name: choose_metric_entries(cf, spec["tags"], spec["units"])
            for name, spec in METRIC_SPECS.items()
        }
        for d in event_dates[symbol]:
            asof = pd.Timestamp(d)
            rev = metric_snapshot(metric_entries["revenue"], asof)
            ni = metric_snapshot(metric_entries["net_income"], asof)
            eps = metric_snapshot(metric_entries["eps"], asof)
            opm, opm_yoy = margin_snapshot(metric_entries["operating_income"], metric_entries["revenue"], asof)
            gm, gm_yoy = margin_snapshot(metric_entries["gross_profit"], metric_entries["revenue"], asof)

            filed_dates = [x["latest_filed"] for x in (rev, ni, eps) if pd.notna(x["latest_filed"])]
            latest_filed = max(filed_dates) if filed_dates else pd.NaT
            days = float((asof - latest_filed).days) if pd.notna(latest_filed) else np.nan
            has = float(
                np.isfinite(rev["yoy"]) or np.isfinite(ni["yoy"]) or np.isfinite(eps["yoy"])
                or np.isfinite(opm) or np.isfinite(gm)
            )
            records.append({
                "date": asof, "symbol": symbol, "sec_has_data": has,
                "sec_days_since_filing": days,
                "sec_recent_30": float(np.isfinite(days) and 0 <= days <= 30),
                "sec_recent_60": float(np.isfinite(days) and 0 <= days <= 60),
                "rev_yoy": rev["yoy"], "rev_accel_pp": rev["accel_pp"],
                "rev_accel_confirmed": rev["accel_confirmed"],
                "ni_yoy": ni["yoy"], "ni_accel_pp": ni["accel_pp"], "ni_turnaround": ni["turnaround"],
                "eps_yoy": eps["yoy"], "eps_accel_pp": eps["accel_pp"], "eps_turnaround": eps["turnaround"],
                "op_margin": opm, "op_margin_yoy_pp": opm_yoy,
                "gross_margin": gm, "gross_margin_yoy_pp": gm_yoy,
            })
        if i % 100 == 0:
            print("SEC_PROGRESS", i, "/", len(symbols), stats, flush=True)
    return pd.DataFrame(records), stats


def candidate_pool(rows: pd.DataFrame, union_rs189: bool = False) -> pd.DataFrame:
    out = []
    for _, g in rows.groupby(["date", "theme"], observed=True, sort=True):
        if len(g) < MIN_POOL:
            continue
        a = g.sort_values(["ret63", "symbol"], ascending=[False, True]).head(3)
        if union_rs189:
            b = g.sort_values(["ret189", "symbol"], ascending=[False, True]).head(3)
            a = pd.concat([a, b], ignore_index=True).drop_duplicates("symbol")
        out.append(a)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=rows.columns)


def grouped(df: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    z = df.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)
    groups = z.groupby(["date", "theme"], observed=True, sort=True).size().tolist()
    return z, groups


def rank_label(df: pd.DataFrame, source: str) -> pd.Series:
    pct = df.groupby(["date", "theme"], observed=True)[source].rank(pct=True, method="average")
    return np.floor((pct.clip(0, 0.999999) * 5)).astype(int)


def params(seed: int) -> dict:
    return dict(
        objective="lambdarank", metric="ndcg", learning_rate=0.035,
        n_estimators=220, num_leaves=7, max_depth=3,
        min_child_samples=30, reg_lambda=2.0, reg_alpha=0.2,
        subsample=0.9, subsample_freq=1, colsample_bytree=0.85,
        random_state=seed, bagging_seed=seed, feature_fraction_seed=seed,
        data_random_seed=seed, deterministic=True, force_col_wise=True,
        n_jobs=1, verbosity=-1,
    )


def fit_predict_ensemble(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    label_col: str,
    prefix: str,
) -> pd.Series:
    tr, groups = grouped(train)
    te = test.sort_values(["date", "theme", "symbol"]).reset_index()
    preds = []
    for seed in SEEDS:
        model = lgb.LGBMRanker(**params(seed))
        model.fit(tr[features], tr[label_col].astype(int), group=groups)
        preds.append(model.predict(te[features]))
    avg = np.mean(np.vstack(preds), axis=0)
    s = pd.Series(avg, index=te["index"].to_numpy(), name=prefix)
    return s.reindex(test.index)


def choose_top1(df: pd.DataFrame, score: str, ascending: bool = False) -> pd.DataFrame:
    order = [True, True, ascending, True]
    z = df.sort_values(["date", "theme", score, "symbol"], ascending=order)
    return z.groupby(["date", "theme"], observed=True, sort=True).head(1).copy()


def evaluate(chosen: pd.DataFrame, full_rows: pd.DataFrame, method: str) -> pd.DataFrame:
    theme_means = full_rows.groupby(["date", "theme"], observed=True)[[f"fwd_ret{h}" for h in HORIZONS]].mean()
    z = chosen.set_index(["date", "theme"]).copy()
    recs = []
    for key, r in z.iterrows():
        rec = {"date": key[0], "theme": key[1], "symbol": r["symbol"], "method": method}
        for h in HORIZONS:
            raw = safe_num(r[f"fwd_ret{h}"])
            base = safe_num(theme_means.loc[key, f"fwd_ret{h}"]) if key in theme_means.index else np.nan
            rec[f"ret_cost_{h}"] = raw - 2 * COST_BPS_SIDE / 10000.0 if np.isfinite(raw) else np.nan
            rec[f"vs_theme_{h}"] = raw - base if np.isfinite(raw) and np.isfinite(base) else np.nan
        recs.append(rec)
    return pd.DataFrame(recs)


def paired_summary(events: pd.DataFrame, method: str, baseline: str) -> dict:
    out = {}
    for h in HORIZONS:
        metric = f"ret_cost_{h}"
        a = events[events.method == method][["date", "theme", metric]].rename(columns={metric: "a"})
        b = events[events.method == baseline][["date", "theme", metric]].rename(columns={metric: "b"})
        m = a.merge(b, on=["date", "theme"]).dropna()
        d = m["a"] - m["b"]
        out[str(h)] = {
            "n": int(len(d)),
            "mean": float(d.mean()) if len(d) else None,
            "median": float(d.median()) if len(d) else None,
            "positive_rate": float((d > 0).mean()) if len(d) else None,
        }
    return out


def year_summary(events: pd.DataFrame, method: str, baseline: str) -> list[dict]:
    out = []
    for h in HORIZONS:
        metric = f"ret_cost_{h}"
        a = events[events.method == method][["date", "theme", metric]].rename(columns={metric: "a"})
        b = events[events.method == baseline][["date", "theme", metric]].rename(columns={metric: "b"})
        m = a.merge(b, on=["date", "theme"]).dropna()
        m["year"] = pd.to_datetime(m["date"]).dt.year
        for y, g in m.groupby("year"):
            out.append({"horizon": h, "year": int(y), "n": int(len(g)), "mean_diff": float((g.a - g.b).mean())})
    return out


def coverage_summary(df: pd.DataFrame) -> dict:
    x = df.copy()
    x["year"] = pd.to_datetime(x["date"]).dt.year
    out = {
        "rows": int(len(x)),
        "symbols": int(x["symbol"].nunique()),
        "has_sec_rate": float(pd.to_numeric(x["sec_has_data"], errors="coerce").fillna(0).mean()),
        "by_year": {},
    }
    for y, g in x.groupby("year"):
        out["by_year"][str(int(y))] = {
            "rows": int(len(g)),
            "has_sec_rate": float(pd.to_numeric(g["sec_has_data"], errors="coerce").fillna(0).mean()),
            "rev_yoy_rate": float(pd.to_numeric(g["rev_yoy"], errors="coerce").notna().mean()),
            "eps_yoy_rate": float(pd.to_numeric(g["eps_yoy"], errors="coerce").notna().mean()),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--sec-user-agent", default=os.getenv("SEC_USER_AGENT", ""))
    args = ap.parse_args()

    if not args.sec_user_agent.strip():
        raise SystemExit("SEC_USER_AGENT is required")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rows = pd.read_csv(args.input, compression="gzip", parse_dates=["date"])
    rows = rows.sort_values(["date", "theme", "symbol"]).reset_index(drop=True)

    rs63_pool = candidate_pool(rows, union_rs189=False)
    union_pool = candidate_pool(rows, union_rs189=True)
    needed = rows[rows["symbol"].astype(str).isin(set(union_pool["symbol"].astype(str)))][["date", "symbol"]].drop_duplicates()

    session = sec_session(args.sec_user_agent)
    ticker_map = load_ticker_map(session, args.sec_user_agent)
    sec_features, sec_stats = build_sec_feature_rows(needed, ticker_map, session, Path(args.cache_dir))
    sec_features["date"] = pd.to_datetime(sec_features["date"])
    sec_features.to_csv(out / "sec_point_in_time_features.csv.gz", index=False, compression="gzip")

    enriched = rows.merge(sec_features, on=["date", "symbol"], how="left")
    for c in FUND_FEATURES:
        if c not in enriched:
            enriched[c] = np.nan
    enriched["sec_has_data"] = enriched["sec_has_data"].fillna(0.0)

    results = []
    model_summaries = {}
    for pool_name, union_flag in [("RS63_TOP3", False), ("RS63_RS189_UNION", True)]:
        pool = candidate_pool(enriched, union_rs189=union_flag).copy()
        if pool.empty:
            continue
        pool["label40_local"] = rank_label(pool, "fwd_ret40")
        pool["label_mfe_local"] = rank_label(pool, "fwd_mfe63")
        train = pool[pool.date <= TRAIN_END].copy()
        test = pool[pool.date >= HOLDOUT_START].copy()

        tech_features = [c for c in TECH_FEATURES if c in pool.columns]
        hybrid_features = tech_features + [c for c in FUND_FEATURES if c in pool.columns]

        for objective, label in [("RET40", "label40_local"), ("MFE63", "label_mfe_local")]:
            test[f"tech_{objective}"] = fit_predict_ensemble(train, test, tech_features, label, f"tech_{objective}")
            test[f"hybrid_{objective}"] = fit_predict_ensemble(train, test, hybrid_features, label, f"hybrid_{objective}")

        for kind in ("tech", "hybrid"):
            cols = []
            for objective in ("RET40", "MFE63"):
                c = f"{kind}_{objective}"
                rc = f"{c}_rank"
                test[rc] = test.groupby(["date", "theme"], observed=True)[c].rank(pct=True, method="average")
                cols.append(rc)
            test[f"{kind}_ensemble"] = test[cols].mean(axis=1)

        rs63 = choose_top1(test, "ret63")
        rs189 = choose_top1(test, "ret189")
        tech = choose_top1(test, "tech_ensemble")
        hybrid = choose_top1(test, "hybrid_ensemble")
        fund_parts = []
        for fc in ("rev_accel_pp", "eps_accel_pp", "op_margin_yoy_pp"):
            rc = f"{fc}_fund_rank"
            test[rc] = test.groupby(["date", "theme"], observed=True)[fc].rank(pct=True, method="average")
            fund_parts.append(rc)
        test["fund_simple"] = test[fund_parts].mean(axis=1)
        fund = choose_top1(test, "fund_simple")

        ev = pd.concat([
            evaluate(rs63, enriched, f"{pool_name}_RS63_TOP1"),
            evaluate(rs189, enriched, f"{pool_name}_RS189_TOP1"),
            evaluate(tech, enriched, f"{pool_name}_TECH_ML_TOP1"),
            evaluate(hybrid, enriched, f"{pool_name}_HYBRID_ML_TOP1"),
            evaluate(fund, enriched, f"{pool_name}_FUND_DIAG_TOP1"),
        ], ignore_index=True)
        results.append(ev)

        base = f"{pool_name}_RS63_TOP1"
        model_summaries[pool_name] = {
            "train_rows": int(len(train)), "test_rows": int(len(test)),
            "test_events": int(test[["date", "theme"]].drop_duplicates().shape[0]),
            "coverage": coverage_summary(test),
            "hybrid_vs_rs63": paired_summary(ev, f"{pool_name}_HYBRID_ML_TOP1", base),
            "tech_vs_rs63": paired_summary(ev, f"{pool_name}_TECH_ML_TOP1", base),
            "hybrid_vs_tech": paired_summary(ev, f"{pool_name}_HYBRID_ML_TOP1", f"{pool_name}_TECH_ML_TOP1"),
            "rs189_vs_rs63": paired_summary(ev, f"{pool_name}_RS189_TOP1", base),
            "hybrid_years_vs_rs63": year_summary(ev, f"{pool_name}_HYBRID_ML_TOP1", base),
            "tech_years_vs_rs63": year_summary(ev, f"{pool_name}_TECH_ML_TOP1", base),
        }
        test.to_csv(out / f"holdout_candidates_{pool_name.lower()}.csv.gz", index=False, compression="gzip")

    events = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    events.to_csv(out / "hybrid_event_results.csv.gz", index=False, compression="gzip")
    summary = {
        "status": "RESEARCH_TECHNICAL_FIRST_SEC_RERANK",
        "train_end": str(TRAIN_END.date()),
        "holdout_start": str(HOLDOUT_START.date()),
        "cost_bps_side": COST_BPS_SIDE,
        "seeds": list(SEEDS),
        "sec_stats": sec_stats,
        "models": model_summaries,
        "limitations": [
            "Current universe/current taxonomy are retrospectively applied.",
            "SEC CompanyFacts are filtered by filed<=signal date to avoid future-filing leakage.",
            "Only direct 55-125 day quarterly XBRL facts are used; Q4 annual-minus-quarter derivation is intentionally omitted in v1.",
            "Foreign issuers/non-US-GAAP filers may have missing SEC features; missingness is retained rather than backfilled from future data.",
            "Non-price features only rerank technical candidates; they do not change Theme Momentum, entry, exit, or risk logic.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

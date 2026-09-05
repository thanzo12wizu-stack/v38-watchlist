#!/usr/bin/env python3
"""Third-stage research-only robustness validation for Options Intelligence.

This script reads the already-created event_features.csv and performs no network calls.
It never writes production V38 / Dashboard / Rotation / Leadership / Options artifacts.

Questions:
1) Is the current Direction Bias asymmetric (DOWN more useful than UP), using an exact
   reconstruction of the production score where Gamma Flip requires a 2% price gap?
2) Does Gamma Flip retain cross-sectional value across market/sector/DTE/quality strata?
3) Are Wall levels better treated as path/touch information than directional RR?
4) Which Options feature groups add out-of-date information beyond technical/sector data?
5) Are results robust when ranking inside sector/date rather than only inside date?

Guardrail: only 11 independent option-snapshot sessions exist. All results are exploratory.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
INFILE = HERE / "event_features.csv"
SEED = 20260905
RNG = np.random.default_rng(SEED)
HORIZONS = (1, 3, 5, 10)
UP_THRESHOLDS = (60, 64, 68, 72, 76, 80)
DOWN_THRESHOLDS = (40, 36, 32, 28, 24, 20)


def pct(x):
    return "—" if x is None or not np.isfinite(x) else f"{100*x:.2f}%"


def num(x, nd=3):
    return "—" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def date_boot_ci(values, n=5000):
    a = np.asarray([x for x in values if np.isfinite(x)], float)
    if len(a) == 0:
        return np.nan, np.nan, np.nan
    mean = float(a.mean())
    if len(a) < 3:
        return mean, np.nan, np.nan
    sims = np.empty(n)
    for i in range(n):
        sims[i] = RNG.choice(a, size=len(a), replace=True).mean()
    lo, hi = np.quantile(sims, [0.025, 0.975])
    return mean, float(lo), float(hi)


def safe_rank_spread(g: pd.DataFrame, feature: str, outcome: str):
    z = g[[feature, outcome]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(z) < 25 or z[feature].nunique() < 4:
        return None
    r = z[feature].rank(method="average", pct=True)
    top = z.loc[r >= .8, outcome]
    bot = z.loc[r <= .2, outcome]
    if len(top) < 4 or len(bot) < 4:
        return None
    return float(top.mean() - bot.mean()), len(z), len(top), len(bot)


def exact_direction_scores(d: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct current production Direction Bias from historical feature columns.

    Production JS uses a >2% spot-vs-flip gap, not the 0.35 ATR approximation used by
    the first broad research pass. Wall RR and technical point values match production.
    Also create diagnostic variants that remove individual feature groups; these are
    research comparisons, not proposed production changes.
    """
    d = d.copy()
    spot = pd.to_numeric(d["spot"], errors="coerce")
    gf = pd.to_numeric(d["gamma_flip"], errors="coerce")
    valid = (spot > 0) & (gf > 0)
    flip_pct = pd.Series(np.nan, index=d.index, dtype=float)
    flip_pct.loc[valid] = spot.loc[valid] / gf.loc[valid] - 1.0
    d["flip_pct_exact"] = flip_pct

    def build(include_flip=True, include_wall=True, include_tech=True):
        s = np.full(len(d), 50.0)
        if include_flip:
            s += np.where(flip_pct > .02, 10, np.where(flip_pct < -.02, -10, 0))
        if include_wall:
            rr = pd.to_numeric(d["wall_rr"], errors="coerce").to_numpy(float)
            s += np.where(rr >= 1.4, 10,
                          np.where(rr <= .7, -10,
                                   np.where(rr >= 1.15, 4, np.where(rr <= .87, -4, 0))))
        if include_tech:
            ae = pd.to_numeric(d["above_ema21"], errors="coerce").to_numpy(float)
            av = pd.to_numeric(d["above_vwap63"], errors="coerce").to_numpy(float)
            r1 = pd.to_numeric(d["ret1_today"], errors="coerce").to_numpy(float)
            s += np.where(ae == 1, 8, np.where(ae == 0, -8, 0))
            s += np.where(av == 1, 5, np.where(av == 0, -5, 0))
            s += np.where(r1 >= .02, 5, np.where(r1 <= -.02, -5, 0))
        return np.clip(s, 0, 100)

    d["score_exact_current"] = build(True, True, True)
    d["score_no_wall"] = build(True, False, True)
    d["score_tech_only"] = build(False, False, True)
    d["score_flip_only"] = build(True, False, False)
    return d


def threshold_sweep(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for score_col in ("score_exact_current", "score_no_wall", "score_tech_only"):
        for side, thresholds in (("UP", UP_THRESHOLDS), ("DOWN", DOWN_THRESHOLDS)):
            for th in thresholds:
                mask = d[score_col] >= th if side == "UP" else d[score_col] <= th
                z = d.loc[mask].copy()
                for h in HORIZONS:
                    out = f"r{h}_exqqq"
                    q = z[["date", out]].replace([np.inf, -np.inf], np.nan).dropna()
                    if len(q) < 20:
                        continue
                    daily = q.groupby("date")[out].mean()
                    mean_daily, lo, hi = date_boot_ci(daily.to_numpy())
                    sign = 1 if side == "UP" else -1
                    rows.append({
                        "score_variant": score_col,
                        "side": side,
                        "threshold": th,
                        "horizon": h,
                        "n": len(q),
                        "dates": q.date.nunique(),
                        "pooled_mean_exqqq": q[out].mean(),
                        "equal_date_mean_exqqq": mean_daily,
                        "date_ci_lo": lo,
                        "date_ci_hi": hi,
                        "event_directional_hit": float((q[out] * sign > 0).mean()),
                        "date_directional_hit": float((daily * sign > 0).mean()),
                    })
    return pd.DataFrame(rows)


def score_variant_validation(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for score_col in ("score_exact_current", "score_no_wall", "score_tech_only", "score_flip_only"):
        for h in HORIZONS:
            out = f"r{h}_exqqq"
            for dt, g in d.groupby("date"):
                res = safe_rank_spread(g, score_col, out)
                if res is None:
                    continue
                spread, n, tn, bn = res
                rows.append({"score_variant": score_col, "horizon": h, "date": dt,
                             "n": n, "top_n": tn, "bottom_n": bn, "spread": spread})
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame()
    sums = []
    for (v, h), g in detail.groupby(["score_variant", "horizon"]):
        mean, lo, hi = date_boot_ci(g.spread)
        sums.append({"score_variant": v, "horizon": h, "dates": len(g), "n_total": int(g.n.sum()),
                     "top_bottom_spread": mean, "ci_lo": lo, "ci_hi": hi,
                     "positive_date_fraction": float((g.spread > 0).mean())})
    return pd.DataFrame(sums)


def flip_spread_for_subset(d, name, mask, within_sector=False):
    z = d.loc[mask].copy()
    rows = []
    outcome = "r5_exqqq"
    if within_sector:
        for (dt, sec), g in z.groupby(["date", "sector"]):
            if not str(sec).strip():
                continue
            res = safe_rank_spread(g, "flip_dist_atr", outcome)
            if res is None:
                continue
            spread, n, tn, bn = res
            rows.append({"date": dt, "sector": sec, "spread": spread, "n": n})
    else:
        for dt, g in z.groupby("date"):
            res = safe_rank_spread(g, "flip_dist_atr", outcome)
            if res is None:
                continue
            spread, n, tn, bn = res
            rows.append({"date": dt, "spread": spread, "n": n})
    if not rows:
        return None
    x = pd.DataFrame(rows)
    # Equal-weight independent dates. For sector-neutral tests first average sector spreads per date.
    daily = x.groupby("date").spread.mean()
    mean, lo, hi = date_boot_ci(daily)
    return {"stratum": name, "dates": len(daily), "groups": len(x), "n_group_sum": int(x.n.sum()),
            "spread_5d_exqqq": mean, "ci_lo": lo, "ci_hi": hi,
            "positive_date_fraction": float((daily > 0).mean())}


def flip_strata(d: pd.DataFrame):
    masks = [
        ("ALL", pd.Series(True, index=d.index)),
        ("QQQ above EMA21", d.qqq_above_ema21.eq(1)),
        ("QQQ below EMA21", d.qqq_above_ema21.eq(0)),
        ("Sector momentum >=0", d.sector_ret20.ge(0)),
        ("Sector momentum <0", d.sector_ret20.lt(0)),
        ("DTE 0-6", d.dte.between(0, 6)),
        ("DTE 7-13", d.dte.between(7, 13)),
        ("DTE 14-21", d.dte.between(14, 21)),
        ("DTE 22-45", d.dte.between(22, 45)),
        ("OI>=5k & strikes>=20", d.total_oi.ge(5000) & d.n_strikes.ge(20)),
        ("OI<5k or strikes<20", d.total_oi.lt(5000) | d.n_strikes.lt(20)),
        ("DDV 10-50M", d.dvol_m.between(10, 50, inclusive="left")),
        ("DDV >=50M", d.dvol_m.ge(50)),
        ("SCAN source", d.source.astype(str).eq("SCAN")),
        ("DETAIL source", d.source.astype(str).eq("DETAIL")),
    ]
    rows = []
    for name, mask in masks:
        r = flip_spread_for_subset(d, name, mask, False)
        if r:
            rows.append(r)
    sector = flip_spread_for_subset(d, "Within sector/date", pd.Series(True, index=d.index), True)
    return pd.DataFrame(rows), pd.DataFrame([sector] if sector else [])


def wall_diagnostics(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    bins = [(0, .5, "0-0.5ATR"), (.5, 1, "0.5-1ATR"), (1, 2, "1-2ATR"), (2, np.inf, "2ATR+")]
    for side in ("call", "put"):
        dist = f"{side}_dist_atr"
        touch = f"{side}_touch5"
        brk = f"{side}_break5"
        for lo, hi, label in bins:
            mask = d[dist].ge(lo) & (d[dist].lt(hi) if np.isfinite(hi) else pd.Series(True, index=d.index))
            z = d.loc[mask, ["date", dist, touch, brk, "r5_exqqq", "mfe5", "mae5"]].replace([np.inf, -np.inf], np.nan)
            z = z.dropna(subset=[dist])
            if len(z) < 20:
                continue
            rows.append({
                "kind": "distance_bin", "side": side, "bucket": label, "n": len(z), "dates": z.date.nunique(),
                "touch5": z[touch].mean(), "break5": z[brk].mean(),
                "hold_given_touch": float(((z[touch] == 1) & (z[brk] != 1)).sum() / max(1, (z[touch] == 1).sum())),
                "mean_5d_exqqq": z.r5_exqqq.mean(), "mean_mfe5": z.mfe5.mean(), "mean_mae5": z.mae5.mean(),
            })
    # Directional quintile diagnostics for each Wall dimension and RR.
    for feature in ("call_dist_atr", "put_dist_atr", "wall_rr"):
        vals = []
        for dt, g in d.groupby("date"):
            res = safe_rank_spread(g, feature, "r5_exqqq")
            if res:
                vals.append((dt, res[0], res[1]))
        if vals:
            x = pd.DataFrame(vals, columns=["date", "spread", "n"])
            mean, lo, hi = date_boot_ci(x.spread)
            rows.append({"kind": "directional_quintile", "side": "", "bucket": feature,
                         "n": int(x.n.sum()), "dates": len(x), "touch5": np.nan, "break5": np.nan,
                         "hold_given_touch": np.nan, "mean_5d_exqqq": mean, "mean_mfe5": lo, "mean_mae5": hi})
    return pd.DataFrame(rows)


def prepare_model_features(d):
    x = d.copy()
    gp = pd.to_numeric(x.gex_per_oi, errors="coerce").to_numpy(float)
    x["signed_log_gex_per_oi"] = np.sign(gp) * np.log1p(np.abs(gp))
    x["log_oi"] = np.log1p(pd.to_numeric(x.total_oi, errors="coerce").clip(lower=0))
    # Cap extremely remote / malformed levels for regression stability only.
    for c in ("flip_dist_atr", "call_dist_atr", "put_dist_atr"):
        x[c + "_cap"] = pd.to_numeric(x[c], errors="coerce").clip(-5, 5)
    return x


def zfit(train, test, cols):
    mu = train[cols].mean()
    sd = train[cols].std(ddof=0).replace(0, 1).fillna(1)
    return (train[cols] - mu) / sd, (test[cols] - mu) / sd


def ridge_predict(X, y, Xt, lam=5.0):
    X = np.column_stack([np.ones(len(X)), X])
    Xt = np.column_stack([np.ones(len(Xt)), Xt])
    pen = np.eye(X.shape[1]); pen[0, 0] = 0
    beta = np.linalg.solve(X.T @ X + lam * pen, X.T @ y)
    return Xt @ beta


def pred_stats(pred, yy):
    ic = spearmanr(pred, yy).statistic if len(np.unique(pred)) > 1 else np.nan
    rank = pd.Series(pred).rank(pct=True).to_numpy()
    top = yy[rank >= .8]; bot = yy[rank <= .2]
    spread = float(np.mean(top) - np.mean(bot)) if len(top) and len(bot) else np.nan
    mse = float(np.mean((pred - yy) ** 2))
    return ic, spread, mse


def ablation_lodo(d: pd.DataFrame, h=5):
    y = f"r{h}_exqqq"
    base = ["ret1_today", "ret20", "dist20hi", "sector_ret20", "hv20", "above_ema21", "above_vwap63"]
    groups = {
        "baseline": [],
        "baseline+flip": ["flip_dist_atr_cap"],
        "baseline+wall": ["call_dist_atr_cap", "put_dist_atr_cap"],
        "baseline+gex": ["signed_log_gex_per_oi"],
        "baseline+depth": ["log_oi", "n_strikes"],
        "baseline+all_options": ["flip_dist_atr_cap", "call_dist_atr_cap", "put_dist_atr_cap", "signed_log_gex_per_oi", "log_oi", "n_strikes"],
    }
    all_cols = list(dict.fromkeys(base + groups["baseline+all_options"]))
    z = d[["date", "ticker", y] + all_cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    dates = sorted(z.date.unique())
    rows = []
    for dt in dates:
        test = z[z.date == dt]
        train = z[z.date != dt]
        if len(test) < 25 or len(train) < 100:
            continue
        yy = test[y].to_numpy(float)
        for name, extra in groups.items():
            cols = base + extra
            X, Xt = zfit(train, test, cols)
            pred = ridge_predict(X.to_numpy(float), train[y].to_numpy(float), Xt.to_numpy(float))
            ic, spread, mse = pred_stats(pred, yy)
            rows.append({"date": dt, "model": name, "n": len(test), "ic": ic, "spread": spread, "mse": mse})
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame(), detail
    piv = detail.pivot(index="date", columns="model", values=["ic", "spread", "mse"])
    sums = []
    for model in groups:
        g = detail[detail.model == model]
        if g.empty:
            continue
        base_g = detail[detail.model == "baseline"].set_index("date")
        for metric in ("ic", "spread", "mse"):
            vals = g.set_index("date")[metric]
            common = vals.index.intersection(base_g.index)
            arr = vals.loc[common].to_numpy(float)
            delta = arr - base_g.loc[common, metric].to_numpy(float)
            mean, lo, hi = date_boot_ci(arr)
            dm, dlo, dhi = date_boot_ci(delta)
            sums.append({"model": model, "metric": metric, "dates": len(common),
                         "mean": mean, "ci_lo": lo, "ci_hi": hi,
                         "delta_vs_baseline": dm, "delta_ci_lo": dlo, "delta_ci_hi": dhi,
                         "improved_date_fraction": float((delta > 0).mean()) if metric != "mse" else float((delta < 0).mean())})
    return pd.DataFrame(sums), detail


def write_report(d, thresholds, variants, fstrata, fsector, walls, abl, abld):
    lines = [
        "# Options Intelligence robustness validation — 2026-09-05",
        "",
        "Research only. No production file or upstream V38 / Dashboard / Rotation / Leadership artifact was changed.",
        "",
        "## Data / methodological guardrail",
        "",
        f"- Event rows: {len(d):,}",
        f"- Tickers: {d.ticker.nunique():,}",
        f"- Independent option-snapshot sessions: {d.date.nunique()}",
        "- Thresholds are compared for stability, not optimized to the best in-sample number.",
        "- Cross-sectional spreads are calculated within each date; confidence intervals resample independent dates.",
        "- Exact production-score reconstruction uses the production Gamma Flip rule: spot must be >2% above/below Flip for ±10.",
        "",
        "## 1. Exact current score: asymmetric threshold sweep (5d ex-QQQ)",
        "",
        "|Variant|Side|Threshold|N|Dates|Equal-date mean|95% date CI|Event hit|Date hit|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    t5 = thresholds[thresholds.horizon == 5].copy()
    for _, r in t5.iterrows():
        lines.append(f"|{r.score_variant}|{r.side}|{int(r.threshold)}|{int(r.n)}|{int(r.dates)}|{pct(r.equal_date_mean_exqqq)}|{pct(r.date_ci_lo)} to {pct(r.date_ci_hi)}|{pct(r.event_directional_hit)}|{pct(r.date_directional_hit)}|")

    lines += ["", "## 2. Score component ablation: within-date top-bottom spread", "",
              "|Variant|Horizon|Dates|Top-bottom ex-QQQ|95% date CI|Positive dates|",
              "|---|---:|---:|---:|---:|---:|"]
    for _, r in variants.iterrows():
        lines.append(f"|{r.score_variant}|{int(r.horizon)}d|{int(r.dates)}|{pct(r.top_bottom_spread)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")

    lines += ["", "## 3. Gamma Flip robustness (5d ex-QQQ)", "",
              "Within each stratum/date, rank by Flip distance in ATR; report top 20% minus bottom 20%.", "",
              "|Stratum|Dates|Groups|Spread|95% date CI|Positive dates|",
              "|---|---:|---:|---:|---:|---:|"]
    for _, r in pd.concat([fstrata, fsector], ignore_index=True).iterrows():
        lines.append(f"|{r.stratum}|{int(r.dates)}|{int(r.groups)}|{pct(r.spread_5d_exqqq)}|{pct(r.ci_lo)} to {pct(r.ci_hi)}|{pct(r.positive_date_fraction)}|")

    lines += ["", "## 4. Wall diagnostics", "",
              "Distance-bin rows show 5-session path behavior. Directional-quintile rows use Mean 5d ex-QQQ as the top-minus-bottom spread; MFE/MAE columns then contain its bootstrap CI bounds.", "",
              "|Kind|Side/feature|Bucket|N|Dates|Touch|Break|Hold if touched|5d ex-QQQ / spread|MFE or CI-lo|MAE or CI-hi|",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, r in walls.iterrows():
        sf = r.side if str(r.side) else r.bucket
        lines.append(f"|{r.kind}|{sf}|{r.bucket}|{int(r.n)}|{int(r.dates)}|{pct(r.touch5)}|{pct(r.break5)}|{pct(r.hold_given_touch)}|{pct(r.mean_5d_exqqq)}|{pct(r.mean_mfe5)}|{pct(r.mean_mae5)}|")

    lines += ["", "## 5. Out-of-date feature-group ablation (5d ex-QQQ)", "",
              "All models use the same complete-case observations. Baseline is technical + sector context. Each Options group is added separately, then all are added together.", "",
              "|Model|Metric|Dates|Mean|Delta vs baseline|95% delta CI|Improved dates|",
              "|---|---|---:|---:|---:|---:|---:|"]
    for _, r in abl.iterrows():
        formatter = num if r.metric in ("ic", "mse") else pct
        mean = formatter(r["mean"])
        delta = formatter(r.delta_vs_baseline)
        lo = formatter(r.delta_ci_lo); hi = formatter(r.delta_ci_hi)
        lines.append(f"|{r.model}|{r.metric}|{int(r.dates)}|{mean}|{delta}|{lo} to {hi}|{pct(r.improved_date_fraction)}|")

    # Conservative, programmatic interpretation.
    lines += ["", "## Research interpretation", ""]
    exact5 = t5[t5.score_variant == "score_exact_current"]
    up = exact5[exact5.side == "UP"]
    dn = exact5[exact5.side == "DOWN"]
    if not up.empty and not dn.empty:
        up_stable = up[(up.dates >= 4) & (up.equal_date_mean_exqqq > 0) & (up.date_directional_hit >= .6)]
        dn_stable = dn[(dn.dates >= 4) & (dn.equal_date_mean_exqqq < 0) & (dn.date_directional_hit >= .6)]
        if dn_stable.shape[0] > up_stable.shape[0]:
            lines.append("- The exact current score remains more stable on the DOWN side than the UP side across nearby thresholds. This supports asymmetric treatment as a research hypothesis, not an automatic threshold change.")
        elif up_stable.shape[0] > dn_stable.shape[0]:
            lines.append("- The exact current score is at least as stable on the UP side in this sample; the earlier apparent downside asymmetry weakens under the exact 2% Flip reconstruction.")
        else:
            lines.append("- Nearby-threshold stability does not clearly favor one side after exact-score reconstruction; retain caution about asymmetry.")

    all_flip = fstrata[fstrata.stratum == "ALL"]
    sec_flip = fsector[fsector.stratum == "Within sector/date"] if not fsector.empty else pd.DataFrame()
    if not all_flip.empty:
        r = all_flip.iloc[0]
        lines.append(f"- Gamma Flip cross-sectional spread is {pct(r.spread_5d_exqqq)} over {int(r.dates)} dates in the all-sample test.")
    if not sec_flip.empty:
        r = sec_flip.iloc[0]
        lines.append(f"- Sector/date-neutral Gamma Flip spread is {pct(r.spread_5d_exqqq)} over {int(r.dates)} dates. If its sign survives, Flip is less likely to be only a sector-selection artifact.")

    wall_rr = walls[(walls.kind == "directional_quintile") & (walls.bucket == "wall_rr")]
    if not wall_rr.empty:
        r = wall_rr.iloc[0]
        lines.append(f"- Wall RR top-minus-bottom spread is {pct(r.mean_5d_exqqq)}. Its sign should be interpreted diagnostically; reversing the production weight from this short sample would be overfit.")

    if not abl.empty:
        a = abl[(abl.metric == "spread") & (abl.model != "baseline")].sort_values("delta_vs_baseline", ascending=False)
        if not a.empty:
            r = a.iloc[0]
            lines.append(f"- Best feature-group addition by out-of-date spread in this sample: {r.model}, delta {pct(r.delta_vs_baseline)} across {int(r.dates)} left-out dates. This identifies where the incremental signal came from; it is not an adoption rule.")

    lines += ["", "## Evidence threshold", "",
              "Do not tune production thresholds from 11 sessions. Continue daily all-liquid snapshots and repeat the same frozen tests at ~40 and ~120 independent sessions. A production change should require sign stability across time, sector-neutral confirmation, and out-of-date improvement.", ""]
    (HERE / "ROBUSTNESS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    if not INFILE.exists():
        raise SystemExit("event_features.csv not found")
    d = pd.read_csv(INFILE, parse_dates=["date"], low_memory=False)
    numeric_cols = ["spot", "gamma_flip", "wall_rr", "above_ema21", "above_vwap63", "ret1_today",
                    "flip_dist_atr", "call_dist_atr", "put_dist_atr", "qqq_above_ema21", "sector_ret20",
                    "dte", "total_oi", "n_strikes", "dvol_m", "gex_per_oi", "ret20", "dist20hi", "hv20",
                    "call_touch5", "call_break5", "put_touch5", "put_break5", "r5_exqqq", "mfe5", "mae5"]
    for c in numeric_cols:
        if c not in d:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if "sector" not in d: d["sector"] = ""
    if "source" not in d: d["source"] = ""
    d = exact_direction_scores(d)
    d = prepare_model_features(d)

    thresholds = threshold_sweep(d)
    variants = score_variant_validation(d)
    fstrata, fsector = flip_strata(d)
    walls = wall_diagnostics(d)
    abl, abld = ablation_lodo(d, 5)

    thresholds.to_csv(HERE / "threshold_sweep.csv", index=False)
    variants.to_csv(HERE / "score_variant_validation.csv", index=False)
    fstrata.to_csv(HERE / "flip_strata.csv", index=False)
    fsector.to_csv(HERE / "flip_sector_neutral.csv", index=False)
    walls.to_csv(HERE / "wall_diagnostics.csv", index=False)
    abl.to_csv(HERE / "ablation_lodo.csv", index=False)
    abld.to_csv(HERE / "ablation_lodo_by_date.csv", index=False)
    write_report(d, thresholds, variants, fstrata, fsector, walls, abl, abld)
    summary = {"rows": len(d), "tickers": int(d.ticker.nunique()), "dates": int(d.date.nunique()),
               "threshold_rows": len(thresholds), "flip_strata_rows": len(fstrata),
               "sector_neutral_rows": len(fsector), "wall_rows": len(walls),
               "ablation_summary_rows": len(abl), "ablation_dates": int(abld.date.nunique()) if not abld.empty else 0}
    (HERE / "robustness_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

PRIMARY_SCENARIO = "STOCK_PLUS_TQQQ"
PRIMARY_TIMING = "SAME_DAY_GROSS"
PRIMARY_COST = 25
CURRENT = "CURRENT_RULE"
NEW = "NEW_8T3I1E"
SEED = 20260909


def safe(x):
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
        return str(x.date())
    return x


def load_frame(base: Path, scenario: str, timing: str, cost: int, variant: str) -> pd.DataFrame:
    path = base / f"integrated_{scenario}_{timing}_{cost}_{variant}.csv.gz"
    if not path.exists():
        raise FileNotFoundError(path)
    d = pd.read_csv(path, compression="gzip")
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date").sort_index()


def metrics(ret: pd.Series) -> dict:
    r = pd.to_numeric(ret, errors="coerce").fillna(0.0)
    if len(r) < 2:
        return {"days": len(r), "cagr": None, "mdd": None, "sharpe": None, "end_multiple": None}
    eq = (1.0 + r).cumprod()
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    sd = float(r.std(ddof=1))
    return {
        "days": len(r),
        "cagr": float(eq.iloc[-1] ** (1.0 / years) - 1.0),
        "mdd": float((eq / eq.cummax() - 1.0).min()),
        "sharpe": float(r.mean() / sd * np.sqrt(252.0)) if sd > 0 else None,
        "end_multiple": float(eq.iloc[-1]),
    }


def normal_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def newey_west_mean_t(x: np.ndarray, lag: int) -> float | None:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < max(20, lag + 5):
        return None
    u = x - x.mean()
    gamma0 = float(np.dot(u, u) / n)
    lrv = gamma0
    for j in range(1, lag + 1):
        gamma = float(np.dot(u[j:], u[:-j]) / n)
        weight = 1.0 - j / (lag + 1.0)
        lrv += 2.0 * weight * gamma
    if lrv <= 0:
        return None
    return float(x.mean() / math.sqrt(lrv / n))


def moving_block_bootstrap(diff: np.ndarray, block: int, sims: int = 5000) -> dict:
    x = np.asarray(diff, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < block:
        return {"block": block, "sims": sims, "prob_mean_gt_zero": None, "one_sided_p": None}
    rng = np.random.default_rng(SEED + block)
    starts = np.arange(n - block + 1)
    means = np.empty(sims, float)
    for k in range(sims):
        chunks = []
        total = 0
        while total < n:
            st = int(rng.choice(starts))
            chunk = x[st:st + block]
            chunks.append(chunk)
            total += len(chunk)
        means[k] = np.concatenate(chunks)[:n].mean()
    prob = float((means > 0).mean())
    return {
        "block": block,
        "sims": sims,
        "prob_mean_gt_zero": prob,
        "one_sided_p": float(1.0 - prob),
        "mean_ci_2_5": float(np.quantile(means, 0.025)),
        "mean_ci_97_5": float(np.quantile(means, 0.975)),
    }


def verify_freeze(root: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["freeze_sha256"]
    core = dict(manifest)
    core.pop("freeze_sha256", None)
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    actual = hashlib.sha256(canonical).hexdigest()
    source_checks = {}
    for rel, pinned in manifest.get("source_pins", {}).items():
        p = root / rel
        if not p.exists():
            source_checks[rel] = {"expected": pinned, "actual": None, "match": False}
            continue
        actual_blob = subprocess.check_output(["git", "hash-object", str(p)], text=True).strip()
        source_checks[rel] = {"expected": pinned, "actual": actual_blob, "match": actual_blob == pinned}
    return {
        "freeze_sha256_expected": expected,
        "freeze_sha256_actual": actual,
        "manifest_match": actual == expected,
        "source_checks": source_checks,
        "all_sources_match": all(x["match"] for x in source_checks.values()),
    }


def paired(base: Path, scenario: str, timing: str, cost: int):
    a = load_frame(base, scenario, timing, cost, CURRENT)
    b = load_frame(base, scenario, timing, cost, NEW)
    common = a.index.intersection(b.index)
    a = a.reindex(common)
    b = b.reindex(common)
    diff = pd.to_numeric(b["return"], errors="coerce").fillna(0) - pd.to_numeric(a["return"], errors="coerce").fillna(0)
    return a, b, diff


def period_table(a: pd.DataFrame, b: pd.DataFrame) -> list[dict]:
    periods = [
        ("2016_2018", "2016-01-01", "2018-12-31"),
        ("2019_2021", "2019-01-01", "2021-12-31"),
        ("2022_2024", "2022-01-01", "2024-12-31"),
        ("2025_2026M3", "2025-01-01", "2026-03-20"),
        ("2016_2021", "2016-01-01", "2021-12-31"),
        ("2022_2026M3", "2022-01-01", "2026-03-20"),
    ]
    rows = []
    for name, lo, hi in periods:
        ai = a.loc[lo:hi, "return"]
        bi = b.loc[lo:hi, "return"]
        ma, mb = metrics(ai), metrics(bi)
        rows.append({
            "period": name,
            "current": ma,
            "new": mb,
            "delta_cagr": None if ma["cagr"] is None or mb["cagr"] is None else mb["cagr"] - ma["cagr"],
            "delta_mdd": None if ma["mdd"] is None or mb["mdd"] is None else mb["mdd"] - ma["mdd"],
        })
    return rows


def anchored_fixed_tests(a: pd.DataFrame, b: pd.DataFrame) -> list[dict]:
    windows = [
        ("train_through_2018_test_2019_2021", "2019-01-01", "2021-12-31"),
        ("train_through_2021_test_2022_2023", "2022-01-01", "2023-12-31"),
        ("train_through_2023_test_2024_2026M3", "2024-01-01", "2026-03-20"),
    ]
    out = []
    for name, lo, hi in windows:
        d = (b.loc[lo:hi, "return"] - a.loc[lo:hi, "return"]).dropna()
        mb, ma = metrics(b.loc[lo:hi, "return"]), metrics(a.loc[lo:hi, "return"])
        t20 = newey_west_mean_t(d.to_numpy(), 20)
        out.append({
            "fold": name,
            "days": len(d),
            "delta_cagr": mb["cagr"] - ma["cagr"],
            "newey_west_t_lag20": t20,
            "one_sided_normal_p": normal_sf(t20) if t20 is not None else None,
            "reselected_within_fold": False,
            "classification": "TEMPORAL_STABILITY_NOT_TRUE_OOS",
        })
    return out


def regime_decomposition(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    z = pd.DataFrame(index=a.index)
    z["diff"] = b["return"] - a["return"]
    z["mode"] = a["market_mode"].astype(str)
    z["tqqq_native"] = pd.to_numeric(a["tqqq_native"], errors="coerce").fillna(0.0)
    rows = []
    for mode, g in z.groupby("mode"):
        rows.append({
            "regime": f"MARKET_MODE:{mode}",
            "days": len(g),
            "annual_arithmetic_delta": float(g["diff"].mean() * 252),
            "log_wealth_delta": float((np.log1p(b.loc[g.index, "return"]) - np.log1p(a.loc[g.index, "return"])).sum()),
        })
    off = z[z["tqqq_native"] <= 1e-12]
    on = z[z["tqqq_native"] > 1e-12]
    for name, g in [("TQQQ_NATIVE_OFF", off), ("TQQQ_NATIVE_ON", on)]:
        rows.append({
            "regime": name,
            "days": len(g),
            "annual_arithmetic_delta": float(g["diff"].mean() * 252) if len(g) else None,
            "log_wealth_delta": float((np.log1p(b.loc[g.index, "return"]) - np.log1p(a.loc[g.index, "return"])).sum()) if len(g) else None,
        })

    modes = z["mode"]
    prior = modes.shift(1).fillna("START")
    trans = []
    for label in ["ATTACK->SELECTIVE", "SELECTIVE->ATTACK", "SELECTIVE->STOP", "STOP->SELECTIVE"]:
        p, q = label.split("->")
        idx = z.index[(prior == p) & (modes == q)]
        if len(idx):
            trans.append({
                "transition": label,
                "days": len(idx),
                "annual_arithmetic_delta": float(z.loc[idx, "diff"].mean() * 252),
                "log_wealth_delta": float((np.log1p(b.loc[idx, "return"]) - np.log1p(a.loc[idx, "return"])).sum()),
            })
    return {
        "available": rows,
        "transitions": trans,
        "not_evaluated": {
            "VIX_high_low": "No frozen point-in-time VIX series is embedded in the integrated artifact.",
            "rates_up_down": "No frozen point-in-time rate series is embedded in the integrated artifact.",
            "QQQ_up_down": "QQQ return is not embedded in the integrated artifact; TQQQ return is not a substitute.",
            "breadth_buckets": "Breadth is not embedded in the integrated artifact.",
            "NQSAR_color_transition": "Only the canonical aggregate market_mode is embedded; raw color transition is not.",
        },
    }


def contribution_concentration(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    d = (b["return"] - a["return"]).dropna()
    logd = (np.log1p(b.loc[d.index, "return"]) - np.log1p(a.loc[d.index, "return"]))
    total = float(logd.sum())
    s = logd.sort_values(ascending=False)
    out = {"total_log_wealth_delta": total}
    for n in (1, 5, 10, 20, 50):
        v = float(s.head(n).sum())
        out[f"top_{n}_days_log_delta"] = v
        out[f"top_{n}_days_share_of_total"] = v / total if abs(total) > 1e-12 else None
    return out


def selection_stress(bootstrap_rows: list[dict]) -> dict:
    ref = next((x for x in bootstrap_rows if x["block"] == 20), bootstrap_rows[0])
    p = ref.get("one_sided_p")
    if p is None:
        return {"exact_full_discovery_test_available": False}
    stresses = []
    for m in (4, 6, 12, 24, 50):
        bonf = min(1.0, p * m)
        sidak = 1.0 - (1.0 - p) ** m
        stresses.append({"candidate_count": m, "bonferroni_p": bonf, "sidak_p": sidak, "pass_5pct_bonferroni": bonf < 0.05})
    return {
        "exact_full_discovery_test_available": False,
        "reason": "The full daily-return matrix for every candidate tried during discovery was not retained. A White Reality Check/SPA over the complete search would otherwise be mislabeled.",
        "reference_block": ref["block"],
        "unadjusted_one_sided_block_p": p,
        "multiplicity_sensitivity_only": stresses,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--manifest", default="research/8t3i1e_freeze_manifest.json")
    args = ap.parse_args()
    root = Path(args.root)
    base = root / args.input
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    freeze = verify_freeze(root, root / args.manifest)
    scenarios = []
    for scenario in ("STOCK_PLUS_TQQQ", "FULL_GROSS100_WITH_RESET"):
        for timing in ("SAME_DAY_GROSS", "LAG1_GROSS"):
            for cost in (0, 25):
                try:
                    a, b, d = paired(base, scenario, timing, cost)
                except FileNotFoundError:
                    continue
                ma, mb = metrics(a["return"]), metrics(b["return"])
                scenarios.append({
                    "scenario": scenario,
                    "timing": timing,
                    "cost_bps": cost,
                    "current": ma,
                    "new": mb,
                    "delta_cagr": mb["cagr"] - ma["cagr"],
                    "delta_mdd": mb["mdd"] - ma["mdd"],
                })

    a, b, diff = paired(base, PRIMARY_SCENARIO, PRIMARY_TIMING, PRIMARY_COST)
    hac = []
    for lag in (5, 10, 20, 40, 63):
        t = newey_west_mean_t(diff.to_numpy(), lag)
        hac.append({"lag": lag, "t": t, "one_sided_normal_p": normal_sf(t) if t is not None else None})
    boots = [moving_block_bootstrap(diff.to_numpy(), block) for block in (5, 10, 20, 40, 63)]

    report = {
        "audit_id": "8T3I1E_POST_SELECTION_FIXED_20260909",
        "freeze": freeze,
        "primary": {
            "scenario": PRIMARY_SCENARIO,
            "timing": PRIMARY_TIMING,
            "cost_bps": PRIMARY_COST,
            "current": metrics(a["return"]),
            "new": metrics(b["return"]),
            "daily_spread_mean": float(diff.mean()),
            "daily_spread_sd": float(diff.std(ddof=1)),
            "annual_arithmetic_spread": float(diff.mean() * 252),
        },
        "all_frozen_integration_scenarios": scenarios,
        "newey_west": hac,
        "moving_block_bootstrap": boots,
        "temporal_periods": period_table(a, b),
        "anchored_fixed_tests": anchored_fixed_tests(a, b),
        "regime_decomposition": regime_decomposition(a, b),
        "contribution_concentration": contribution_concentration(a, b),
        "selection_adjustment": selection_stress(boots),
        "interpretation_guardrails": [
            "No fold re-selects or retunes 8T3I1E.",
            "Historical folds are temporal stability tests, not genuine post-freeze OOS.",
            "Exact full-discovery White Reality Check/SPA is unavailable without the retained daily-return matrix for every tried candidate.",
            "Missing frozen PIT regime series are reported as not evaluated rather than backfilled with hindsight-prone substitutes.",
            "Production is not modified."
        ],
        "production_changed": False,
    }
    (out / "postselection_audit.json").write_text(json.dumps(safe(report), ensure_ascii=False, indent=2), encoding="utf-8")

    p20 = next(x["one_sided_p"] for x in boots if x["block"] == 20)
    primary = report["primary"]
    stop = next((x for x in report["regime_decomposition"]["available"] if x["regime"] == "MARKET_MODE:STOP"), None)
    t20 = next(x["t"] for x in hac if x["lag"] == 20)
    lines = [
        "# 8T3I1E fixed post-selection audit",
        "",
        f"- Freeze manifest match: **{freeze['manifest_match']}**",
        f"- Frozen source pins all match: **{freeze['all_sources_match']}**",
        f"- Primary CAGR: current **{primary['current']['cagr']:.4%}**, 8T3I1E **{primary['new']['cagr']:.4%}**, delta **{primary['new']['cagr']-primary['current']['cagr']:.4%}**",
        f"- Primary MDD: current **{primary['current']['mdd']:.4%}**, 8T3I1E **{primary['new']['mdd']:.4%}**",
        f"- Newey-West lag20 t: **{t20:.3f}**",
        f"- Moving-block 20d one-sided p: **{p20:.4f}**",
    ]
    if stop:
        lines.append(f"- STOP regime annual-arithmetic spread: **{stop['annual_arithmetic_delta']:.2%}** across {stop['days']} days")
    lines += [
        "",
        "## Selection-bias status",
        "",
        "A complete White Reality Check / SPA over the full discovery search is **not claimed** because the daily-return matrix for every candidate tried during discovery was not retained in this artifact.",
        "The report therefore includes conservative multiplicity sensitivity and fixed-rule temporal stability, while keeping the candidate frozen.",
        "",
        "## Production",
        "",
        "**Unchanged.**",
    ]
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DONE_8T3I1E_POSTSELECTION_AUDIT", flush=True)


if __name__ == "__main__":
    main()

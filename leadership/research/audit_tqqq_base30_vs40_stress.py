from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


def metrics(r: np.ndarray) -> dict:
    x = np.asarray(r, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"cagr": np.nan, "mdd": np.nan, "sharpe": np.nan, "end": np.nan}
    eq = np.cumprod(1.0 + x)
    years = len(x) / 252.0
    cagr = float(eq[-1] ** (1.0 / years) - 1.0) if years > 0 and eq[-1] > 0 else np.nan
    peak = np.maximum.accumulate(eq)
    mdd = float(np.min(eq / peak - 1.0))
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else np.nan
    sharpe = float(np.mean(x) / sd * np.sqrt(252.0)) if np.isfinite(sd) and sd > 0 else np.nan
    return {"cagr": cagr, "mdd": mdd, "sharpe": sharpe, "end": float(eq[-1])}


def paired_block_bootstrap(r30: np.ndarray, r40: np.ndarray, nsim: int = 2000, block: int = 120, horizon: int = 2520, seed: int = 340901) -> tuple[pd.DataFrame, dict]:
    n = min(len(r30), len(r40))
    h = min(horizon, n)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(h / block))
    starts = rng.integers(0, n - block + 1, size=(nsim, nb))
    offs = np.arange(block)
    paths = (starts[:, :, None] + offs).reshape(nsim, -1)[:, :h]
    rows = []
    for i, ix in enumerate(paths):
        m30 = metrics(r30[ix])
        m40 = metrics(r40[ix])
        rows.append({"sim": i, "candidate": "B30", **m30})
        rows.append({"sim": i, "candidate": "B40", **m40})
    df = pd.DataFrame(rows)
    p = df.pivot(index="sim", columns="candidate", values=["cagr", "mdd", "end", "sharpe"])
    dc = p[("cagr", "B40")] - p[("cagr", "B30")]
    dm = p[("mdd", "B40")] - p[("mdd", "B30")]
    de = np.log(p[("end", "B40")]) - np.log(p[("end", "B30")])
    out = {
        "nsim": nsim,
        "block": block,
        "horizon": h,
        "prob_b40_cagr_better": float(np.mean(dc > 0)),
        "delta_cagr_median": float(np.median(dc)),
        "delta_cagr_p05": float(np.quantile(dc, 0.05)),
        "delta_cagr_p95": float(np.quantile(dc, 0.95)),
        "prob_b40_terminal_wealth_better": float(np.mean(de > 0)),
        "delta_log_terminal_wealth_median": float(np.median(de)),
        "prob_b40_mdd_no_worse": float(np.mean(dm >= -1e-12)),
        "delta_mdd_median": float(np.median(dm)),
        "delta_mdd_p05": float(np.quantile(dm, 0.05)),
        "prob_b40_both_cagr_better_and_mdd_no_worse": float(np.mean((dc > 0) & (dm >= -1e-12))),
    }
    return df, out


def run_stage34_tqqq_stress(repo: Path, outdir: Path, nsim: int = 1000) -> dict:
    old = Path.cwd()
    os.chdir(repo)
    try:
        src = Path("research/tqqq_stage34_final_gb_runner_validation.py").read_text()
        prefix = src.split("# ---------- historical exact validation ----------")[0]
        g: dict = {"__name__": "__stage34_audit__"}
        exec(compile(prefix, "stage34-prefix", "exec"), g)

        A = g["A"]
        KEYS = g["KEYS"]
        PBASE = g["PBASE"]
        simulate = g["simulate"]
        make_episode = g["make_episode"]

        p30 = {**PBASE, "base": 0.30, "ext_exp": 0, "ext_max": 40}
        p40 = {**PBASE, "base": 0.40, "ext_exp": 0, "ext_max": 40}
        hist = pd.DataFrame([
            {"candidate": "B30", **simulate(A, p30, 0.0005)},
            {"candidate": "B40", **simulate(A, p40, 0.0005)},
        ])
        hist.to_csv(outdir / "tqqq_stage34_historical_30vs40.csv", index=False)

        H = 2520
        BLOCK = 120
        L = len(A["ret"])
        nb = int(np.ceil(H / BLOCK))
        offs = np.arange(BLOCK)

        # Exact Stage34 normal moving-block setup, paired on identical paths.
        rng = np.random.default_rng(340827)
        starts = rng.integers(0, L - BLOCK + 1, size=(nsim, nb))
        paths = (starts[:, :, None] + offs).reshape(nsim, -1)[:, :H]
        normal = []
        for sim in range(nsim):
            ix = paths[sim]
            B = {k: A[k][ix].copy() for k in KEYS}
            normal.append({"sim": sim, "candidate": "B30", **simulate(B, p30, 0.0005)})
            normal.append({"sim": sim, "candidate": "B40", **simulate(B, p40, 0.0005)})
        normal = pd.DataFrame(normal)
        normal.to_csv(outdir / "tqqq_stage34_normal_mc_30vs40.csv", index=False)

        # Exact Stage34 adversarial family mix / path construction, paired on identical paths and episodes.
        rng = np.random.default_rng(340828)
        starts = rng.integers(0, L - BLOCK + 1, size=(nsim, nb))
        paths = (starts[:, :, None] + offs).reshape(nsim, -1)[:, :H]
        families = np.array((['dotcom_like'] * 250) + (['gfc_like'] * 250) + (['covid_like'] * 250) + (['2022_like'] * 250), dtype=object)
        if nsim != 1000:
            basefam = np.array(['dotcom_like', 'gfc_like', 'covid_like', '2022_like'], dtype=object)
            families = np.resize(basefam, nsim)
        rng.shuffle(families)
        bear = []
        for sim in range(nsim):
            ix = paths[sim]
            B = {k: A[k][ix].copy() for k in KEYS}
            fam = str(families[sim])
            ep = make_episode(fam, rng)
            le = len(ep['ret'])
            if le >= H - 504:
                cut = (le - (H - 504)) // 2
                ep = {k: v[cut:cut + (H - 504)] for k, v in ep.items()}
                le = len(ep['ret'])
            pos = int(rng.integers(252, max(253, H - le - 252)))
            for k in KEYS:
                B[k][pos:pos + le] = ep[k]
            bear.append({"sim": sim, "family": fam, "candidate": "B30", **simulate(B, p30, 0.0005)})
            bear.append({"sim": sim, "family": fam, "candidate": "B40", **simulate(B, p40, 0.0005)})
        bear = pd.DataFrame(bear)
        bear.to_csv(outdir / "tqqq_stage34_bear_mc_30vs40.csv", index=False)

        def pair(df: pd.DataFrame) -> dict:
            p = df.pivot(index="sim", columns="candidate", values=["cagr", "mdd"])
            dc = p[("cagr", "B40")] - p[("cagr", "B30")]
            dm = p[("mdd", "B40")] - p[("mdd", "B30")]
            return {
                "prob_b40_cagr_better": float(np.mean(dc > 0)),
                "delta_cagr_median": float(np.median(dc)),
                "delta_cagr_p05": float(np.quantile(dc, 0.05)),
                "delta_cagr_p95": float(np.quantile(dc, 0.95)),
                "prob_b40_mdd_no_worse": float(np.mean(dm >= -1e-12)),
                "delta_mdd_median": float(np.median(dm)),
                "delta_mdd_p05": float(np.quantile(dm, 0.05)),
                "prob_b40_both": float(np.mean((dc > 0) & (dm >= -1e-12))),
            }

        famrows = []
        for fam, d in bear.groupby("family"):
            z = pair(d)
            famrows.append({"family": fam, **z})
        pd.DataFrame(famrows).to_csv(outdir / "tqqq_stage34_bear_family_pair_30vs40.csv", index=False)

        return {
            "historical": hist.to_dict("records"),
            "normal_pair": pair(normal),
            "bear_pair": pair(bear),
            "bear_family_pair": famrows,
            "nsim": nsim,
            "block": BLOCK,
            "horizon": H,
            "cost_oneway_bps": 5,
        }
    finally:
        os.chdir(old)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--integrated-dir", required=True)
    ap.add_argument("--tqqq-repo", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    idir = Path(args.integrated_dir)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    d30 = pd.read_csv(idir / "daily_base_30.csv.gz", parse_dates=["date"])
    d40 = pd.read_csv(idir / "daily_base_40.csv.gz", parse_dates=["date"])
    if not d30.date.equals(d40.date):
        raise RuntimeError("B30/B40 date alignment mismatch")

    h30 = metrics(d30["return"].to_numpy(float))
    h40 = metrics(d40["return"].to_numpy(float))
    paired, psummary = paired_block_bootstrap(d30["return"].to_numpy(float), d40["return"].to_numpy(float))
    paired.to_csv(out / "integrated_paired_block_mc_30vs40.csv", index=False)

    stage34 = run_stage34_tqqq_stress(Path(args.tqqq_repo), out, 1000)

    summary = {
        "status": "TQQQ_BASE30_VS40_FINAL_STRESS_AUDIT",
        "scope": "Only normal Stage34 base exposure differs: 30% vs 40%. Final portfolio rules remain fixed for integrated bootstrap; TQQQ hierarchy/risk rules remain fixed for Stage34 normal/adversarial stress.",
        "integrated_historical": {"B30": h30, "B40": h40},
        "integrated_paired_block": psummary,
        "stage34_tqqq": stage34,
        "limitations": [
            "Integrated block bootstrap resamples the observed final-portfolio daily return pairs and does not synthesize individual-stock behavior inside artificial bear episodes.",
            "Adversarial Bear stress is therefore applied to the TQQQ hierarchy itself using the exact Stage34 synthetic episode machinery; stock/Reset sleeves are held outside that synthetic test.",
            "Existing MC57 PIT/survivorship and NQSAR proxy caveats remain unchanged.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float))
    print("=== TQQQ BASE30 VS BASE40 FINAL STRESS ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=float))


if __name__ == "__main__":
    main()

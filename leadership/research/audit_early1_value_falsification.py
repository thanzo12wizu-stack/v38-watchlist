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
import audit_early1_operational_final as op


def safe(v: Any) -> Any:
    return base.safe(v)


def exact_metrics(eq: pd.Series, start: str, end: str) -> dict[str, Any]:
    z = eq.loc[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))].dropna()
    if len(z) < 5:
        return {"n": int(len(z))}
    r = z.pct_change(fill_method=None).dropna()
    years = max(len(r) / 252.0, 1.0 / 252.0)
    cagr = float((z.iloc[-1] / z.iloc[0]) ** (1.0 / years) - 1.0)
    dd = z / z.cummax() - 1.0
    sd = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    sharpe = float(r.mean() / sd * np.sqrt(252.0)) if np.isfinite(sd) and sd > 0 else np.nan
    return {
        "n": int(len(z)), "total_return": float(z.iloc[-1] / z.iloc[0] - 1.0),
        "cagr": cagr, "mdd": float(dd.min()), "sharpe": sharpe,
    }


def early_trade_breakdown(trades: pd.DataFrame, start_year: int) -> dict[str, Any]:
    if trades.empty:
        return {"n": 0}
    z = trades.copy()
    z["entry_date"] = pd.to_datetime(z["entry_date"])
    z = z.loc[(z["entry_layer"] == "EARLY") & (z["entry_date"].dt.year >= start_year)]
    if z.empty:
        return {"n": 0}
    out: dict[str, Any] = {
        "n": int(len(z)), "mean_return": float(z["return"].mean()), "median_return": float(z["return"].median()),
        "win_rate": float((z["return"] > 0).mean()), "promoted_n": int(z["promoted"].astype(bool).sum()),
    }
    for flag, label in [(True, "promoted"), (False, "not_promoted")]:
        q = z.loc[z["promoted"].astype(bool) == flag]
        out[label] = {
            "n": int(len(q)),
            "mean_return": float(q["return"].mean()) if len(q) else None,
            "median_return": float(q["return"].median()) if len(q) else None,
            "win_rate": float((q["return"] > 0).mean()) if len(q) else None,
        }
    return out


def bootstrap_window(a: pd.Series, b: pd.Series, start: str, end: str, seed: int) -> float | None:
    aa = a.loc[(a.index >= pd.Timestamp(start)) & (a.index <= pd.Timestamp(end))]
    bb = b.loc[(b.index >= pd.Timestamp(start)) & (b.index <= pd.Timestamp(end))]
    return base.bootstrap_block_win(aa, bb, block=20, reps=10000, seed=seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="."); ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04"); ap.add_argument("--analysis-end", default="2025-12-31")
    ap.add_argument("--max-tickers", type=int, default=6000); ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD same PIT inputs", flush=True)
    meta, raw = ex.build_inputs_ext(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    m, rs, base20 = op.build_ddv20_inputs(root, raw)
    peer_ctx = loo.build_leave_one_out_scores(root, m)
    radar, scores = op.build_early_scores(m, rs, base20)
    arch = op.ARCHS[0]  # WITHIN12 primary only
    no_radar = pd.DataFrame(False, index=radar.index, columns=radar.columns)

    print("SIM EARLY0", flush=True)
    sims = {
        "EARLY0": op.simulate(meta, m, peer_ctx, no_radar, scores["BASE"], "EARLY0", arch, 0.0),
        "EARLY1_BASE": op.simulate(meta, m, peer_ctx, radar, scores["BASE"], "BASE", arch, 0.0),
        "EARLY1_LIQ_ACCEL": op.simulate(meta, m, peer_ctx, radar, scores["LIQ_ACCEL"], "LIQ_ACCEL", arch, 0.0),
    }

    result: dict[str, Any] = {
        "status": "EARLY1_VALUE_FALSIFICATION",
        "design": {
            "purpose": "Test whether LIQ_ACCEL's portfolio improvement is genuine Early1 value or merely a move toward Core-only by reducing harmful Early trades.",
            "architecture": "WITHIN12 only; identical DDV20 Core and exits. EARLY0 is created by making the Early Radar empty. No parameter selection.",
            "dev": "2016-2020", "oos": "2021-2025", "block_bootstrap": "20 sessions, 10,000 reps",
            "no_main_change": True, "no_live_change": True,
        },
        "variants": {}, "pairwise": {},
    }
    for name, sim in sims.items():
        eq = sim["equity"]
        result["variants"][name] = {
            "dev_2016_2020": exact_metrics(eq, "2016-01-01", "2020-12-31"),
            "oos_2021_2025": exact_metrics(eq, "2021-01-01", "2025-12-31"),
            "full": exact_metrics(eq, "2016-01-01", "2025-12-31"),
            "year_metrics": op.year_metrics(eq),
            "entries": int(len(sim["entries"])),
            "early_entries": int((sim["entries"]["entry_layer"] == "EARLY").sum()) if not sim["entries"].empty else 0,
            "promotions": op.promotion_pack(sim["promotions"], sim["entries"]),
            "early_trade_oos": early_trade_breakdown(sim["trades"], 2021),
            "pnl_concentration_oos": op.pnl_concentration(sim["trades"], 2021),
        }
        eq.rename("equity").to_csv(out / f"equity_{name}.csv")
        sim["entries"].to_csv(out / f"entries_{name}.csv", index=False)
        sim["trades"].to_csv(out / f"trades_{name}.csv", index=False)

    names = list(sims)
    for a in names:
        result["pairwise"][a] = {}
        for b in names:
            if a == b:
                continue
            result["pairwise"][a][b] = {
                "full_win_prob": base.bootstrap_block_win(sims[a]["equity"], sims[b]["equity"], block=20, reps=10000, seed=93000 + 31 * names.index(a) + names.index(b)),
                "dev_win_prob": bootstrap_window(sims[a]["equity"], sims[b]["equity"], "2016-01-01", "2020-12-31", 94000 + 31 * names.index(a) + names.index(b)),
                "oos_win_prob": bootstrap_window(sims[a]["equity"], sims[b]["equity"], "2021-01-01", "2025-12-31", 95000 + 31 * names.index(a) + names.index(b)),
            }

    path = out / "summary_early1_value_falsification.json"
    path.write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== EARLY1_VALUE_FALSIFICATION_JSON ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_EARLY1_VALUE_FALSIFICATION_JSON ===", flush=True)


if __name__ == "__main__":
    main()

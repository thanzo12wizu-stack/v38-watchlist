from __future__ import annotations

import argparse
import json
from pathlib import Path

import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_ranking as tr
import audit_ordinary_stock_theme_attack_only as atk


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

    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)

    tr.MIN_GROUP_MEMBERS = 3
    ctx3 = tr.build_group_context(root, matrices)
    baseline = tr.simulate(meta, matrices, ctx3, "STOCK_RS189")

    sims = {}
    coverage = {}
    for n in (3, 5, 10):
        print(f"BUILD/SIM minimum theme members={n}", flush=True)
        tr.MIN_GROUP_MEMBERS = n
        ctx = tr.build_group_context(root, matrices)
        coverage[str(n)] = ctx["coverage"]
        sims[str(n)] = atk.simulate_attack_only(meta, matrices, ctx)

    result = {
        "status": "THEME_GROUP_SIZE_STRESS",
        "question": "Does Theme30 Attack-only survive stricter minimum group sizes, reducing single-stock self-influence?",
        "baseline": atk.pack(baseline),
        "coverage": coverage,
        "variants": {},
    }
    for n, sim in sims.items():
        result["variants"][n] = {
            **atk.pack(sim),
            "block20_win_vs_stock_rs189": base.bootstrap_block_win(sim["equity"], baseline["equity"], block=20, reps=10000, seed=97000 + int(n)),
        }
        sim["equity"].rename("equity").to_csv(out / f"equity_theme30_attack_min{n}.csv")
        sim["entries"].to_csv(out / f"entries_theme30_attack_min{n}.csv", index=False)
    baseline["equity"].rename("equity").to_csv(out / "equity_stock_rs189.csv")
    (out / "summary_theme_group_size.json").write_text(json.dumps(base.safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== THEME_GROUP_SIZE_JSON ===", flush=True)
    print(json.dumps(base.safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_THEME_GROUP_SIZE_JSON ===", flush=True)


if __name__ == "__main__":
    main()

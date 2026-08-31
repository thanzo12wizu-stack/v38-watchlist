from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASELINE_VARIANT = "PEAK30_PART25_R3"
PANEL_START = pd.Timestamp("2022-04-18")
CONFIRM_START = pd.Timestamp("2024-01-01")


def finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def norm(v: Any) -> str:
    return " ".join(str(v or "").strip().split())


def norm_symbol(v: Any) -> str:
    return str(v or "").strip().upper()


def current_sector_etf(sector_raw: Any, industry_raw: Any) -> str | None:
    """Conservative current-classification bridge to the 11 SPDR GICS sectors.

    This is deliberately incomplete. Ambiguous TradingView sector/industry
    combinations return None rather than being forced into a GICS sector.
    It is used only for a look-ahead sensitivity screen and can never prove
    production eligibility by itself.
    """
    s = norm(sector_raw)
    i = norm(industry_raw)
    il = i.lower()

    # Cross-sector overrides first.
    if any(k in il for k in ("real estate investment trust", "real estate development", "real estate operators")):
        return "XLRE"
    if "aerospace & defense" in il or "aerospace and defense" in il:
        return "XLI"
    if any(k in il for k in ("movies/entertainment", "broadcasting", "cable/satellite tv", "wireless telecommunications", "specialty telecommunications")):
        return "XLC"
    if any(k in il for k in ("internet retail", "home improvement chains", "department stores", "restaurants", "hotels/resorts/cruise lines", "casinos/gaming", "motor vehicles")):
        return "XLY"
    if any(k in il for k in ("beverages: non-alcoholic", "food:", "tobacco", "household/personal care", "food distributors")):
        return "XLP"
    if any(k in il for k in ("integrated oil", "oil & gas production", "oilfield services/equipment", "coal")):
        return "XLE"
    if any(k in il for k in ("major banks", "investment banks/brokers", "investment managers", "finance/rental/leasing", "property/casualty insurance", "life/health insurance", "multi-line insurance")):
        return "XLF"
    if any(k in il for k in ("biotechnology", "pharmaceutical", "medical specialties", "managed health care", "hospital/nursing management", "health industry services")):
        return "XLV"
    if any(k in il for k in ("semiconductors", "computer processing hardware", "computer peripherals", "electronic components", "telecommunications equipment")):
        return "XLK"
    if any(k in il for k in ("chemicals:", "other metals/minerals", "aluminum", "steel", "precious metals", "construction materials", "forest products", "containers/packaging")):
        return "XLB"
    if any(k in il for k in ("air freight/couriers", "airlines", "railroads", "trucking", "marine shipping", "industrial conglomerates", "building products", "electrical products", "trucks/construction/farm machinery")):
        return "XLI"

    # Broad categories only where the mapping is structurally unambiguous.
    if s in {"Health Technology", "Health Services"}:
        return "XLV"
    if s == "Finance":
        return "XLF"
    if s == "Energy Minerals":
        return "XLE"
    if s == "Utilities":
        return "XLU"
    if s in {"Non-Energy Minerals", "Process Industries"}:
        return "XLB"
    if s == "Communications":
        return "XLC"
    if s == "Consumer Durables":
        return "XLY"
    if s == "Consumer Non-Durables":
        # Apparel/footwear is discretionary and was handled above only when explicit;
        # keep other consumer non-durables as staples.
        if any(k in il for k in ("apparel", "footwear")):
            return "XLY"
        return "XLP"
    if s == "Electronic Technology":
        return "XLK"
    if s == "Technology Services":
        # Internet Software/Services mixes GICS IT and Communication Services.
        if "internet software/services" in il:
            return None
        return "XLK"
    if s == "Transportation":
        return "XLI"
    if s == "Retail Trade":
        # Specialty stores includes both staples and discretionary (e.g. WMT/COST),
        # so only explicit industry overrides above are accepted.
        return None
    if s in {"Producer Manufacturing", "Commercial Services", "Distribution Services", "Consumer Services"}:
        return None
    return None


def latest_current_validation(universe: pd.DataFrame, snapshots: pd.DataFrame) -> dict[str, Any]:
    latest = snapshots["asof"].max()
    snap = snapshots[snapshots["asof"] == latest][["ticker", "sector_etf"]].drop_duplicates("ticker")
    u = universe.copy()
    sym_col = "シンボル" if "シンボル" in u.columns else "symbol"
    sec_col = "セクター" if "セクター" in u.columns else "sector"
    ind_col = "業種" if "業種" in u.columns else "industry"
    u["symbol"] = u[sym_col].map(norm_symbol)
    u["pred_sector_etf"] = [current_sector_etf(s, i) for s, i in zip(u[sec_col], u[ind_col])]
    z = u[["symbol", "pred_sector_etf"]].merge(snap.rename(columns={"ticker": "symbol", "sector_etf": "actual_sector_etf"}), on="symbol", how="inner")
    use = z[z["pred_sector_etf"].notna()].copy()
    if use.empty:
        return {"latest_snapshot": str(latest.date()), "n_common": int(len(z)), "n_classified": 0, "accuracy": None, "by_predicted": []}
    use["correct"] = use["pred_sector_etf"] == use["actual_sector_etf"]
    by = (
        use.groupby("pred_sector_etf", observed=True)
        .agg(n=("correct", "size"), accuracy=("correct", "mean"))
        .reset_index()
        .sort_values("pred_sector_etf")
        .to_dict("records")
    )
    return {
        "latest_snapshot": str(latest.date()),
        "n_common": int(len(z)),
        "n_classified": int(len(use)),
        "classification_coverage_common": float(len(use) / len(z)) if len(z) else None,
        "accuracy": float(use["correct"].mean()),
        "by_predicted": by,
    }


def pit_map_trades(trades: pd.DataFrame, snapshots: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    snaps = snapshots[["ticker", "sector_etf", "asof"]].drop_duplicates().sort_values(["ticker", "asof"])
    for sym, grp in trades.groupby("symbol", sort=False):
        src = snaps[snaps["ticker"] == sym]
        g = grp.sort_values("entry_date").copy()
        if src.empty:
            g["pit_sector_asof"] = pd.NaT
            g["pit_sector_etf"] = pd.NA
        else:
            g = pd.merge_asof(
                g,
                src[["asof", "sector_etf"]].sort_values("asof"),
                left_on="entry_date",
                right_on="asof",
                direction="backward",
            ).rename(columns={"asof": "pit_sector_asof", "sector_etf": "pit_sector_etf"})
        parts.append(g)
    z = pd.concat(parts, ignore_index=True) if parts else trades.copy()
    p = panel.copy()
    p["dist_trap"] = (p["price_score"] >= 70.0) & (p["internal_score"] < 50.0) & (p["flow20_pct_aum"] <= 0.0)
    p = p[["date", "sector", "dist_trap"]]
    return z.merge(p, left_on=["entry_date", "pit_sector_etf"], right_on=["date", "sector"], how="left")


def summarize_group(g: pd.DataFrame) -> dict[str, Any]:
    if g.empty:
        return {"n": 0}
    r = pd.to_numeric(g["return"], errors="coerce").dropna()
    if r.empty:
        return {"n": 0}
    return {
        "n": int(len(r)),
        "mean_return": float(r.mean()),
        "median_return": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "loss8_rate": float((r <= -0.08).mean()),
    }


def bootstrap_delta(g: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int = 381904, reps: int = 5000) -> list[float | None]:
    z = g[["entry_date", "return", "dist_trap"]].dropna().copy()
    if z.empty or z["dist_trap"].nunique() < 2:
        return [None, None]
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    ix = pos.reindex(pd.to_datetime(z["entry_date"])).to_numpy(float)
    ok = np.isfinite(ix)
    z = z.loc[ok].copy()
    z["block20"] = np.floor(ix[ok] / 20.0).astype(int)
    blocks = sorted(z["block20"].unique())
    if len(blocks) < 3:
        return [None, None]
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(reps):
        picked = rng.choice(blocks, size=len(blocks), replace=True)
        sample = pd.concat([z[z["block20"] == b] for b in picked], ignore_index=True)
        a = sample.loc[sample["dist_trap"] == True, "return"]  # noqa: E712
        b = sample.loc[sample["dist_trap"] == False, "return"]  # noqa: E712
        if len(a) and len(b):
            vals.append(float(a.mean() - b.mean()))
    if len(vals) < 100:
        return [None, None]
    return [float(x) for x in np.quantile(vals, [0.025, 0.975])]


def sensitivity_screen(trades: pd.DataFrame, universe: pd.DataFrame, panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    u = universe.copy()
    sym_col = "シンボル" if "シンボル" in u.columns else "symbol"
    sec_col = "セクター" if "セクター" in u.columns else "sector"
    ind_col = "業種" if "業種" in u.columns else "industry"
    u["symbol"] = u[sym_col].map(norm_symbol)
    u["current_sector_etf"] = [current_sector_etf(s, i) for s, i in zip(u[sec_col], u[ind_col])]
    u = u[["symbol", "current_sector_etf", sec_col, ind_col]].drop_duplicates("symbol")

    z = trades.merge(u, on="symbol", how="left")
    p = panel.copy()
    p["dist_trap"] = (p["price_score"] >= 70.0) & (p["internal_score"] < 50.0) & (p["flow20_pct_aum"] <= 0.0)
    p = p[["date", "sector", "price_score", "internal_score", "flow20_pct_aum", "dist_trap"]]
    z = z.merge(p, left_on=["entry_date", "current_sector_etf"], right_on=["date", "sector"], how="left")
    z["period"] = np.where(z["entry_date"] >= CONFIRM_START, "CONFIRMATION_2024_PLUS", "DISCOVERY_2022_2023")

    calendar = pd.DatetimeIndex(sorted(panel["date"].unique()))
    out: dict[str, Any] = {
        "total_trades_in_panel_window": int(len(trades)),
        "current_sector_classified": int(z["current_sector_etf"].notna().sum()),
        "daily_state_matched": int(z["dist_trap"].notna().sum()),
        "periods": {},
    }
    for name, g in [("ALL_2022_PLUS", z[z["dist_trap"].notna()]), *[(pname, z[(z["period"] == pname) & z["dist_trap"].notna()]) for pname in ("DISCOVERY_2022_2023", "CONFIRMATION_2024_PLUS")]]:
        trap = g[g["dist_trap"] == True]  # noqa: E712
        non = g[g["dist_trap"] == False]  # noqa: E712
        ts = summarize_group(trap)
        ns = summarize_group(non)
        delta = None
        if ts.get("n", 0) and ns.get("n", 0):
            delta = float(ts["mean_return"] - ns["mean_return"])
        out["periods"][name] = {
            "trap": ts,
            "nontrap": ns,
            "mean_return_delta_trap_minus_nontrap": delta,
            "block20_bootstrap_ci95": bootstrap_delta(g, calendar, seed=381904 + len(out["periods"]) * 1000),
        }
    return z, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=Path, required=True)
    ap.add_argument("--trades", type=Path, required=True)
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--snapshots", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    universe = pd.read_csv(args.universe)
    trades = pd.read_csv(args.trades)
    panel = pd.read_csv(args.panel)
    snapshots = pd.read_csv(args.snapshots)
    trades["symbol"] = trades["symbol"].map(norm_symbol)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"]).dt.normalize()
    trades["exit_date"] = pd.to_datetime(trades["exit_date"]).dt.normalize()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    snapshots["asof"] = pd.to_datetime(snapshots["asof"]).dt.normalize()

    panel_end = panel["date"].max()
    use = trades[(trades["entry_date"] >= max(PANEL_START, panel["date"].min())) & (trades["entry_date"] <= panel_end)].copy()

    validation = latest_current_validation(universe, snapshots)
    classifier_valid = bool(
        validation.get("n_classified", 0) >= 250
        and validation.get("accuracy") is not None
        and float(validation["accuracy"]) >= 0.90
    )

    pit = pit_map_trades(use, snapshots, panel)
    pit_summary = {
        "trades": int(len(use)),
        "pit_sector_mapped": int(pit["pit_sector_etf"].notna().sum()),
        "pit_daily_state_matched": int(pit["dist_trap"].notna().sum()),
        "pit_distribution_trap_entries": int((pit["dist_trap"] == True).sum()),  # noqa: E712
    }

    detail, screen = sensitivity_screen(use, universe, panel)
    confirm = screen["periods"]["CONFIRMATION_2024_PLUS"]
    allp = screen["periods"]["ALL_2022_PLUS"]
    confirm_n = int(confirm["trap"].get("n", 0))
    confirm_delta = confirm.get("mean_return_delta_trap_minus_nontrap")
    all_delta = allp.get("mean_return_delta_trap_minus_nontrap")
    ci = confirm.get("block20_bootstrap_ci95") or [None, None]

    if not classifier_valid:
        decision = "CLASSIFIER_INVALID"
    elif confirm_n < 8:
        decision = "INCONCLUSIVE_TOO_FEW_TRAP_ENTRIES"
    elif confirm_delta is None or confirm_delta >= 0:
        decision = "REJECT_VETO_NO_NEGATIVE_INCREMENT"
    elif all_delta is not None and all_delta < 0 and ci[1] is not None and ci[1] < 0:
        decision = "LOOKAHEAD_SCREEN_POSITIVE_NEEDS_FULL_UNIVERSE_PIT"
    else:
        decision = "INCONCLUSIVE_LOOKAHEAD_WEAK"

    report = {
        "schema": 1,
        "research_only": True,
        "baseline_variant": BASELINE_VARIANT,
        "distribution_trap_definition": "price_score>=70 AND internal_score<50 AND exact 20d flow_pct_aum<=0",
        "strict_pit_trade_screen": pit_summary,
        "current_classification_validation": {**validation, "valid_for_sensitivity": classifier_valid, "guard": "n>=250 and >=90% accuracy against latest PIT S&P500 sector snapshot"},
        "lookahead_sensitivity": screen,
        "decision": decision,
        "interpretation_guard": {
            "positive_screen": "cannot be adopted; requires historical full-universe PIT sector classification and then portfolio A/B",
            "negative_screen": "sufficient to reject/deprioritize the veto hypothesis because the sensitivity already benefits from current-classification look-ahead",
            "production_change": False,
        },
    }
    (args.output / "distribution_trap_trade_screen.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    detail.to_csv(args.output / "distribution_trap_trade_screen_trades.csv", index=False, date_format="%Y-%m-%d")

    lines = [
        "# Distribution Trap vs Final Ordinary-Stock Trades",
        "",
        "Research-only. No production/UI/ranking/gate/exit changes.",
        "",
        f"- Baseline: `{BASELINE_VARIANT}`",
        f"- Strict PIT mapped trades: {pit_summary['pit_sector_mapped']} / {pit_summary['trades']}",
        f"- Strict PIT Distribution Trap entries: {pit_summary['pit_distribution_trap_entries']}",
        f"- Current-classification validation: n={validation.get('n_classified', 0)}, accuracy={validation.get('accuracy')}",
        f"- Sensitivity decision: **{decision}**",
        "",
        "| Period | Trap n | Trap mean | Non-trap n | Non-trap mean | Delta | block20 CI95 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for period in ("ALL_2022_PLUS", "DISCOVERY_2022_2023", "CONFIRMATION_2024_PLUS"):
        r = screen["periods"][period]
        t, n = r["trap"], r["nontrap"]
        delta = r["mean_return_delta_trap_minus_nontrap"]
        bci = r["block20_bootstrap_ci95"]
        fmt = lambda x: "n/a" if x is None else f"{100*float(x):+.2f}%"
        lines.append(f"| {period} | {t.get('n',0)} | {fmt(t.get('mean_return'))} | {n.get('n',0)} | {fmt(n.get('mean_return'))} | {fmt(delta)} | {fmt(bci[0])} to {fmt(bci[1])} |")
    lines += [
        "",
        "A positive look-ahead sensitivity result is not adoption evidence. It only justifies acquiring/constructing full-universe historical PIT sector classification and then running the final portfolio A/B.",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "strict_pit": pit_summary, "validation": validation, "confirmation": confirm}, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_market_rs189_rsi_reset as market_audit
import audit_rsi30_mc_nqsar as state_audit
import audit_rsi_reset_portfolio as panic_portfolio
import audit_rsi_reset_robust as market_base
import validate_early_rotation as universe_base
import validate_rsi_divergence_strong as rsi_base

COST = 5.0 / 10000.0
DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")
SLOT = 0.029
HOLD = 20

# Focused, pre-registered thresholds. The broad RS189/RSI grid has already been run.
MC_CUTS = (20.0, 35.0, 50.0, 65.0)
SECTOR_CUTS = (50.0, 60.0, 70.0, 80.0)
RSI_MIN_CUTS = (25.0, 27.5, 30.0)


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
        return x.isoformat()
    return x


def pf(r: pd.Series) -> float | None:
    z = pd.to_numeric(r, errors="coerce").dropna()
    gp = float(z[z > 0].sum())
    gl = float(-z[z < 0].sum())
    return None if gl <= 0 else gp / gl


def cluster_ci(df: pd.DataFrame, cluster: str, seed: int, reps: int = 2500) -> tuple[float | None, float | None]:
    z = df[[cluster, "entry_20"]].dropna()
    if z.empty:
        return (None, None)
    v = z.groupby(cluster, observed=True).entry_20.mean().to_numpy(float)
    if len(v) < 2:
        return (None, None)
    rng = np.random.default_rng(seed)
    draws = rng.choice(v, size=(reps, len(v)), replace=True).mean(axis=1)
    q = np.quantile(draws, [0.025, 0.975])
    return float(q[0]), float(q[1])


def stats(df: pd.DataFrame, calendar: pd.DatetimeIndex, seed: int) -> dict:
    z = df.dropna(subset=["entry_20"]).copy()
    if z.empty:
        return {"n": 0}
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    p = pos.reindex(pd.to_datetime(z.signal_date)).to_numpy(float)
    good = np.isfinite(p)
    z = z.loc[good].copy()
    p = p[good]
    z["block20"] = np.floor(p / 20.0).astype("int64")
    r = pd.to_numeric(z.entry_20, errors="coerce")
    return {
        "n": int(len(z)),
        "signal_dates": int(z.signal_date.nunique()),
        "symbols": int(z.symbol.nunique()),
        "sectors": int(z.sector.nunique()),
        "mean20": float(r.mean()),
        "median20": float(r.median()),
        "win20": float((r > 0).mean()),
        "pf20": pf(r),
        "mae20": float(pd.to_numeric(z.mae_20, errors="coerce").mean()),
        "mfe20": float(pd.to_numeric(z.mfe_20, errors="coerce").mean()),
        "p10_20": float(r.quantile(0.10)),
        "p90_20": float(r.quantile(0.90)),
        "date_ci95": cluster_ci(z, "signal_date", seed),
        "block20_ci95": cluster_ci(z, "block20", seed + 1000),
        "symbol_ci95": cluster_ci(z, "symbol", seed + 2000),
        "sector_ci95": cluster_ci(z, "sector", seed + 3000),
        "mc_mean": float(pd.to_numeric(z.mc, errors="coerce").mean()),
        "sector_rs63_pct_mean": float(pd.to_numeric(z.sector_rs63_pct, errors="coerce").mean()),
        "sector_breadth80_mean": float(pd.to_numeric(z.sector_breadth80, errors="coerce").mean()),
        "rsi_min_reset_mean": float(pd.to_numeric(z.rsi_min_reset, errors="coerce").mean()),
    }


def build_sector_state(close: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    imap = universe_base.read_industry_map(root / "industry_map.json")
    sector_map = {s: (imap.get(s, ("UNMAPPED", "UNMAPPED"))[0] or "UNMAPPED") for s in close.columns}
    ret63 = close.pct_change(63, fill_method=None)
    stock_rs63_pct = ret63.rank(axis=1, pct=True, method="average") * 100.0

    sector_ret = {}
    sector_breadth = {}
    for sector in sorted(set(sector_map.values())):
        syms = [s for s, sec in sector_map.items() if sec == sector]
        if not syms:
            continue
        x = ret63[syms]
        valid = x.notna().sum(axis=1)
        sector_ret[sector] = x.median(axis=1, skipna=True).where(valid >= 3)
        rs = stock_rs63_pct[syms]
        denom = rs.notna().sum(axis=1)
        sector_breadth[sector] = (rs.ge(80.0).sum(axis=1) / denom.replace(0, np.nan)).where(denom >= 3)

    sec_ret = pd.DataFrame(sector_ret, index=close.index)
    sec_pct = sec_ret.rank(axis=1, pct=True, method="average") * 100.0
    sec_breadth = pd.DataFrame(sector_breadth, index=close.index)
    return sec_pct, sec_breadth, sector_map


def attach_context(
    trades: pd.DataFrame,
    close: pd.DataFrame,
    root: Path,
    asof: str,
    nq_start: str,
) -> pd.DataFrame:
    z = trades[(trades.rs_cut == 85) & (trades.rsi_cut == 30)].copy()
    z["touch_date"] = pd.to_datetime(z.touch_date).dt.normalize()
    z["signal_date"] = pd.to_datetime(z.signal_date).dt.normalize()
    z["entry_date"] = pd.to_datetime(z.entry_date).dt.normalize()

    rsi = rsi_base.rsi(close, 14)
    sec_pct, sec_breadth, sector_map = build_sector_state(close, root)
    z["sector"] = z.symbol.map(sector_map).fillna("UNMAPPED")

    rsi_min = []
    sector_pct_signal = []
    sector_breadth_signal = []
    for r in z.itertuples(index=False):
        if r.symbol in rsi.columns and r.touch_date in rsi.index and r.signal_date in rsi.index:
            rsi_min.append(float(rsi.loc[r.touch_date:r.signal_date, r.symbol].min()))
        else:
            rsi_min.append(np.nan)
        try:
            sector_pct_signal.append(float(sec_pct.at[r.signal_date, r.sector]))
        except Exception:
            sector_pct_signal.append(np.nan)
        try:
            sector_breadth_signal.append(float(sec_breadth.at[r.signal_date, r.sector]))
        except Exception:
            sector_breadth_signal.append(np.nan)
    z["rsi_min_reset"] = rsi_min
    z["sector_rs63_pct"] = sector_pct_signal
    z["sector_breadth80"] = sector_breadth_signal

    mc = state_audit.build_mc(asof)
    nq_end = (pd.Timestamp(asof) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    nq = state_audit.build_nqsar(nq_start, nq_end)
    mc2 = mc.copy(); mc2.index.name = "signal_date"; mc2 = mc2.reset_index()
    nq2 = nq.copy(); nq2.index.name = "signal_date"; nq2 = nq2.reset_index()
    z = z.merge(mc2, on="signal_date", how="left", validate="many_to_one")
    z = z.merge(nq2, on="signal_date", how="left", validate="many_to_one")

    if float(z.mc.notna().mean()) < 0.98:
        raise RuntimeError("MC coverage below 98%")
    if float(z.sector_rs63_pct.notna().mean()) < 0.95:
        raise RuntimeError("sector strength coverage below 95%")
    if float(z.rsi_min_reset.notna().mean()) < 0.98:
        raise RuntimeError("RSI reset-min coverage below 98%")
    return z


def rule_masks(z: pd.DataFrame) -> dict[str, pd.Series]:
    m: dict[str, pd.Series] = {"BASE_RS85_RSI30": pd.Series(True, index=z.index)}
    for cut in RSI_MIN_CUTS:
        m[f"RSI_MIN_LE{str(cut).replace('.', 'P')}"] = z.rsi_min_reset <= cut
    for cut in MC_CUTS:
        m[f"MC_GE{int(cut)}"] = z.mc >= cut
    m["MC_GE20_UP1"] = (z.mc >= 20) & z.mc_up1.astype(bool)
    m["MC_GE35_UP1"] = (z.mc >= 35) & z.mc_up1.astype(bool)
    for cut in SECTOR_CUTS:
        m[f"SECTOR_RS63_PCT_GE{int(cut)}"] = z.sector_rs63_pct >= cut

    # Pre-registered combinations: deliberately small to reduce multiple-testing risk.
    m["C1_SEC70_MC20"] = (z.sector_rs63_pct >= 70) & (z.mc >= 20)
    m["C2_SEC70_MC35"] = (z.sector_rs63_pct >= 70) & (z.mc >= 35)
    m["C3_RSI25_SEC70_MC20"] = (z.rsi_min_reset <= 25) & (z.sector_rs63_pct >= 70) & (z.mc >= 20)
    m["C4_RSI25_SEC70_MC35"] = (z.rsi_min_reset <= 25) & (z.sector_rs63_pct >= 70) & (z.mc >= 35)
    m["C5_SEC80_MC20"] = (z.sector_rs63_pct >= 80) & (z.mc >= 20)
    m["C6_SEC70_MC20_UP1"] = (z.sector_rs63_pct >= 70) & (z.mc >= 20) & z.mc_up1.astype(bool)
    m["C7_SEC70_MC20_NQ_BULL"] = (z.sector_rs63_pct >= 70) & (z.mc >= 20) & z.nq_bull.astype(bool)
    return m


def portfolio_max1(z: pd.DataFrame, market: dict, mask: pd.Series, period: str, start: str, end: str) -> dict:
    cl, op, active = market["close"], market["open"], market["active"]
    ema21 = cl.ewm(span=21, adjust=False).mean()
    cal = cl.index[(cl.index >= start) & (cl.index <= end)]
    q = z.loc[mask & z.entry_date.isin(cal)].copy()
    q["theme"] = q.symbol
    # Stronger sector first, then stronger RS189, then deeper reset.
    q["rank_priority"] = (
        (100.0 - q.sector_rs63_pct) * 10000.0
        + (100.0 - q.rs189_signal) * 100.0
        + q.rsi_min_reset
    )
    m, _ = panic_portfolio.simulate(cal, op, cl, active, ema21, q, SLOT, 1, HOLD, "full", False)
    return {"period": period, "input_signals": int(len(q)), **m}


def run_rule_table(z: pd.DataFrame, market: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    masks = rule_masks(z)
    cal = market["close"].index
    rows = []
    port = []
    periods = [
        ("DISCOVERY", pd.Timestamp("2016-01-04"), DISC_END),
        ("CONFIRM", CONF_START, pd.Timestamp("2026-06-30")),
    ]
    for i, (name, mask) in enumerate(masks.items()):
        for pidx, (period, start, end) in enumerate(periods):
            p = z.signal_date.between(start, end)
            s = stats(z.loc[mask & p], cal, seed=2800 + i * 20 + pidx)
            base = z.loc[p].dropna(subset=["entry_20"])
            rejected = z.loc[(~mask) & p].dropna(subset=["entry_20"])
            rows.append({
                "rule": name,
                "period": period,
                "accept_rate": float((mask & p).sum() / max(1, p.sum())),
                "rejected_n": int(len(rejected)),
                "rejected_mean20": float(rejected.entry_20.mean()) if len(rejected) else np.nan,
                **s,
            })
            pm = portfolio_max1(z, market, mask, period, str(start.date()), str(end.date()))
            port.append({"rule": name, **pm})
    return pd.DataFrame(rows), pd.DataFrame(port)


def select_rule(summary: pd.DataFrame, portfolio: pd.DataFrame) -> dict:
    # Decision is based on confirmation robustness with a discovery guardrail.
    disc = summary[summary.period == "DISCOVERY"].set_index("rule")
    conf = summary[summary.period == "CONFIRM"].set_index("rule")
    pc = portfolio[portfolio.period == "CONFIRM"].set_index("rule")
    candidates = []
    base_conf = conf.loc["BASE_RS85_RSI30"]
    for rule in conf.index:
        if rule == "BASE_RS85_RSI30" or rule not in disc.index or rule not in pc.index:
            continue
        d, c, p = disc.loc[rule], conf.loc[rule], pc.loc[rule]
        # Guardrails: enough observations, positive medians and means in both halves,
        # and no worse confirmation tail than the unfiltered base.
        if min(int(d.n), int(c.n)) < 40:
            continue
        if min(float(d.mean20), float(c.mean20), float(d.median20), float(c.median20)) <= 0:
            continue
        if float(c.p10_20) < float(base_conf.p10_20):
            continue
        if float(c.mae20) < float(base_conf.mae20) - 0.005:
            continue
        candidates.append({
            "rule": rule,
            "disc_n": int(d.n),
            "conf_n": int(c.n),
            "disc_mean20": float(d.mean20),
            "conf_mean20": float(c.mean20),
            "conf_median20": float(c.median20),
            "conf_win20": float(c.win20),
            "conf_pf20": float(c.pf20) if pd.notna(c.pf20) else np.nan,
            "conf_mae20": float(c.mae20),
            "conf_p10_20": float(c.p10_20),
            "conf_port_cagr": float(p.cagr),
            "conf_port_mdd": float(p.mdd),
            "score": (
                float(c.median20) * 3.0
                + float(c.mean20)
                + float(d.mean20) * 0.5
                + max(float(c.p10_20), -0.25) * 0.5
                + float(p.cagr) * 0.5
                + float(p.mdd) * 0.25
            ),
        })
    rank = pd.DataFrame(candidates).sort_values("score", ascending=False) if candidates else pd.DataFrame()
    if rank.empty:
        return {"selected": None, "reason": "No contextual filter passed the pre-registered guardrails.", "ranking": []}
    return {"selected": str(rank.iloc[0].rule), "reason": "Highest score among filters passing discovery/confirmation guardrails.", "ranking": rank.to_dict("records")}


def simulate_combined_preempt(
    cal: pd.DatetimeIndex,
    op: pd.DataFrame,
    cl: pd.DataFrame,
    theme: pd.DataFrame,
    market: pd.DataFrame,
) -> dict:
    cash = 1.0
    lots: list[dict] = []
    navs = []
    exposures = []
    turnover = 0.0
    accepted_theme = accepted_market = preemptions = 0
    skipped_market_no_slot = skipped_market_cap = 0

    theme_by = {d: g for d, g in theme.groupby("entry_date", observed=True)}
    market_by = {d: g for d, g in market.groupby("entry_date", observed=True)}

    for i, d in enumerate(cal):
        # Scheduled exits at today's open.
        keep = []
        for lot in lots:
            px = op.at[d, lot["symbol"]] if lot["symbol"] in op.columns else np.nan
            if i >= lot["exit_i"] and pd.notna(px) and px > 0:
                gross = lot["shares"] * float(px)
                cash += gross * (1 - COST)
                turnover += gross
            else:
                keep.append(lot)
        lots = keep

        tday = theme_by.get(d, pd.DataFrame())
        if not tday.empty:
            tday = tday.sort_values(["rank_priority", "rsi_signal", "symbol"])
            for r in tday.itertuples(index=False):
                if any(x["symbol"] == r.symbol for x in lots):
                    continue
                if sum(x["source"] == "theme" and x["theme"] == r.theme for x in lots) >= 2:
                    continue
                if len(lots) >= 4:
                    # Theme owns priority. Preempt the market sleeve if present.
                    mids = [j for j, x in enumerate(lots) if x["source"] == "market"]
                    if mids:
                        j = mids[0]
                        lot = lots.pop(j)
                        px = op.at[d, lot["symbol"]]
                        if pd.notna(px) and px > 0:
                            gross = lot["shares"] * float(px)
                            cash += gross * (1 - COST)
                            turnover += gross
                            preemptions += 1
                    else:
                        continue
                px = op.at[d, r.symbol]
                if pd.isna(px) or px <= 0:
                    continue
                mark = cash + sum(x["shares"] * float(op.at[d, x["symbol"]]) for x in lots if pd.notna(op.at[d, x["symbol"]]))
                amount = SLOT * mark
                if cash < amount * (1 + COST):
                    continue
                cash -= amount * (1 + COST)
                turnover += amount
                lots.append({"symbol": r.symbol, "theme": r.theme, "source": "theme",
                             "shares": amount / float(px), "exit_i": min(i + HOLD, len(cal) - 1)})
                accepted_theme += 1

        mday = market_by.get(d, pd.DataFrame())
        if not mday.empty:
            mday = mday.sort_values(["rank_priority", "symbol"])
            for r in mday.itertuples(index=False):
                if any(x["symbol"] == r.symbol for x in lots):
                    continue
                if any(x["source"] == "market" for x in lots):
                    skipped_market_cap += 1
                    continue
                if len(lots) >= 4:
                    skipped_market_no_slot += 1
                    continue
                px = op.at[d, r.symbol]
                if pd.isna(px) or px <= 0:
                    continue
                mark = cash + sum(x["shares"] * float(op.at[d, x["symbol"]]) for x in lots if pd.notna(op.at[d, x["symbol"]]))
                amount = SLOT * mark
                if cash < amount * (1 + COST):
                    continue
                cash -= amount * (1 + COST)
                turnover += amount
                lots.append({"symbol": r.symbol, "theme": r.theme, "source": "market",
                             "shares": amount / float(px), "exit_i": min(i + HOLD, len(cal) - 1)})
                accepted_market += 1

        gross = sum(x["shares"] * float(cl.at[d, x["symbol"]]) for x in lots if pd.notna(cl.at[d, x["symbol"]]))
        nav = cash + gross
        navs.append(nav)
        exposures.append(gross / nav if nav > 0 else np.nan)

    ns = pd.Series(navs, index=cal)
    m = panic_portfolio.metrics(ns)
    return {
        **m,
        "avg_exposure": float(np.nanmean(exposures)),
        "max_exposure": float(np.nanmax(exposures)),
        "accepted_theme": accepted_theme,
        "accepted_market": accepted_market,
        "market_preemptions": preemptions,
        "skipped_market_no_slot": skipped_market_no_slot,
        "skipped_market_cap": skipped_market_cap,
        "turnover_nav": float(turnover / np.mean(navs)),
    }


def run_combined(theme_path: Path, z: pd.DataFrame, selected_rule: str | None, market: dict) -> pd.DataFrame:
    if selected_rule is None:
        return pd.DataFrame()
    theme = pd.read_csv(theme_path, compression="gzip", parse_dates=["entry_date", "signal_date"])
    theme = theme[(theme.kind == "RISE") & (theme.threshold == 30) & theme.RS63_TOP3.astype(bool) & theme.signal_top3.astype(bool)].copy()
    theme["source"] = "theme"
    theme["rank_priority"] = theme.rank63
    theme = theme[["entry_date", "signal_date", "symbol", "theme", "source", "rank_priority", "rsi_signal"]]

    mask = rule_masks(z)[selected_rule]
    mk = z.loc[mask].copy()
    mk["source"] = "market"
    mk["theme"] = mk.symbol
    mk["rank_priority"] = (
        (100.0 - mk.sector_rs63_pct) * 10000.0
        + (100.0 - mk.rs189_signal) * 100.0
        + mk.rsi_min_reset
    )
    mk = mk[["entry_date", "signal_date", "symbol", "theme", "source", "rank_priority", "rsi_signal"]]

    rows = []
    cl, op = market["close"], market["open"]
    for period, start, end in (
        ("DISCOVERY", pd.Timestamp("2016-01-04"), DISC_END),
        ("CONFIRM", CONF_START, pd.Timestamp("2026-06-30")),
    ):
        cal = cl.index[(cl.index >= start) & (cl.index <= end)]
        th = theme[theme.entry_date.isin(cal)].copy()
        ma = mk[mk.entry_date.isin(cal)].copy()
        # Theme-only comparator.
        base = simulate_combined_preempt(cal, op, cl, th, ma.iloc[0:0])
        add = simulate_combined_preempt(cal, op, cl, th, ma)
        rows.append({"period": period, "scenario": "THEME_ONLY", **base})
        rows.append({"period": period, "scenario": f"THEME_PLUS_{selected_rule}_PREEMPT", **add})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--market-trades", required=True)
    ap.add_argument("--theme-trades", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--asof", default="2026-08-28")
    ap.add_argument("--nq-start", default="2010-01-01")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    trades = pd.read_csv(args.market_trades, compression="gzip",
                         parse_dates=["touch_date", "signal_date", "entry_date"])
    market = market_base.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    z = attach_context(trades, market["close"], root, args.asof, args.nq_start)
    z.to_csv(out / "market_rs189_context_trades.csv.gz", index=False, compression="gzip")

    summary, port = run_rule_table(z, market)
    summary.to_csv(out / "context_rule_summary.csv", index=False)
    port.to_csv(out / "context_portfolio_max1.csv", index=False)

    decision = select_rule(summary, port)
    combined = run_combined(Path(args.theme_trades), z, decision["selected"], market)
    combined.to_csv(out / "context_combined_preempt.csv", index=False)

    result = {
        "status": "MARKET_RS189_CONTEXT_AUDIT",
        "base_rule": "market-wide RS189 percentile >=85; RSI14 <=30 reset; first RSI rise; next-open; 20 sessions",
        "new_context_dimensions": {
            "rsi": "minimum RSI from first <=30 touch through signal",
            "mc57": "production MC57 on signal date; fixed cutoffs and one-day slope",
            "sector_strength": "current-classification sector median 63d return ranked across sectors; signal-date percentile",
            "nqsar": "production-reconstructed NQSAR used only in one pre-registered combination",
        },
        "selection": decision,
        "limitations": [
            "Current-universe and current industry classification survivorship bias remain.",
            "2022+ is confirmation, not pristine untouched out-of-sample, because prior research has inspected it.",
            "Sector strength is a simple point-in-time return/breadth reconstruction, not the dashboard's broader Theme Momentum score.",
            "No tax model in the individual-stock sleeve.",
            "Context search is deliberately limited to pre-registered cutoffs to reduce multiple-testing risk.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2))
    print(json.dumps(safe(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import audit_market_rs189_context as v1
import audit_rsi_reset_robust as market_base

V1_RULE_MASKS = v1.rule_masks

SHORTLIST = (
    "BASE_RS85_RSI30",
    "MC_GE20_UP1",
    "SECTOR_RS63_PCT_GE60",
    "MC_LT50",
    "MC_20_50",
    "MC_20_35",
    "MC_35_50",
    "MC_20_50_SEC50",
    "MC_20_50_SEC60",
    "MC_20_50_SEC70",
    "MC_20_50_SEC60_UP1",
    "RSI27P5_MC_20_50_SEC60",
    "RSI25_MC_20_50_SEC60",
)


def safe(x):
    return v1.safe(x)


def rule_masks(z: pd.DataFrame) -> dict[str, pd.Series]:
    m = V1_RULE_MASKS(z)
    m["MC_LT50"] = z.mc < 50
    m["MC_20_50"] = (z.mc >= 20) & (z.mc < 50)
    m["MC_20_35"] = (z.mc >= 20) & (z.mc < 35)
    m["MC_35_50"] = (z.mc >= 35) & (z.mc < 50)
    m["MC_20_50_SEC50"] = (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 50)
    m["MC_20_50_SEC60"] = (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 60)
    m["MC_20_50_SEC70"] = (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 70)
    m["MC_20_50_SEC60_UP1"] = (
        (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 60) & z.mc_up1.astype(bool)
    )
    m["RSI27P5_MC_20_50_SEC60"] = (
        (z.rsi_min_reset <= 27.5) & (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 60)
    )
    m["RSI25_MC_20_50_SEC60"] = (
        (z.rsi_min_reset <= 25.0) & (z.mc >= 20) & (z.mc < 50) & (z.sector_rs63_pct >= 60)
    )
    return m


def select_rule(summary: pd.DataFrame, portfolio: pd.DataFrame) -> dict:
    disc = summary[summary.period == "DISCOVERY"].set_index("rule")
    conf = summary[summary.period == "CONFIRM"].set_index("rule")
    pdsc = portfolio[portfolio.period == "DISCOVERY"].set_index("rule")
    pcnf = portfolio[portfolio.period == "CONFIRM"].set_index("rule")
    base_c = conf.loc["BASE_RS85_RSI30"]
    base_pd = pdsc.loc["BASE_RS85_RSI30"]
    base_pc = pcnf.loc["BASE_RS85_RSI30"]
    rows = []
    for rule in conf.index:
        if rule == "BASE_RS85_RSI30":
            continue
        if rule not in disc.index or rule not in pdsc.index or rule not in pcnf.index:
            continue
        d, c = disc.loc[rule], conf.loc[rule]
        p_d, p_c = pdsc.loc[rule], pcnf.loc[rule]
        if min(int(d.n), int(c.n)) < 80:
            continue
        if min(float(d.mean20), float(c.mean20), float(d.median20), float(c.median20)) <= 0:
            continue
        if float(c.p10_20) < float(base_c.p10_20) - 0.01:
            continue
        if float(c.mae20) < float(base_c.mae20) - 0.005:
            continue
        if float(p_d.cagr) <= 0 or float(p_c.cagr) <= 0:
            continue
        if float(p_d.mdd) < float(base_pd.mdd) - 0.01:
            continue
        if float(p_c.mdd) < float(base_pc.mdd) - 0.01:
            continue
        rows.append({
            "rule": rule,
            "disc_n": int(d.n),
            "conf_n": int(c.n),
            "disc_mean20": float(d.mean20),
            "conf_mean20": float(c.mean20),
            "disc_median20": float(d.median20),
            "conf_median20": float(c.median20),
            "conf_win20": float(c.win20),
            "conf_pf20": float(c.pf20),
            "conf_mae20": float(c.mae20),
            "conf_p10_20": float(c.p10_20),
            "disc_port_cagr": float(p_d.cagr),
            "disc_port_mdd": float(p_d.mdd),
            "conf_port_cagr": float(p_c.cagr),
            "conf_port_mdd": float(p_c.mdd),
            "score": (
                2.0 * float(c.median20)
                + float(c.mean20)
                + 0.75 * float(d.mean20)
                + 0.5 * float(c.p10_20)
                + 0.75 * float(p_c.cagr)
                + 0.25 * float(p_d.cagr)
                + 0.25 * float(p_c.mdd)
            ),
        })
    rank = pd.DataFrame(rows)
    if rank.empty:
        return {"selected_pre_combined": None, "ranking": []}
    rank = rank.sort_values(["score", "conf_port_cagr", "conf_pf20"], ascending=False)
    return {"selected_pre_combined": str(rank.iloc[0].rule), "ranking": rank.to_dict("records")}


def combined_for_rules(theme_path: Path, z: pd.DataFrame, market: dict, rules: list[str]) -> pd.DataFrame:
    theme = pd.read_csv(theme_path, compression="gzip", parse_dates=["entry_date", "signal_date"])
    theme = theme[
        (theme.kind == "RISE")
        & (theme.threshold == 30)
        & theme.RS63_TOP3.astype(bool)
        & theme.signal_top3.astype(bool)
    ].copy()
    theme["source"] = "theme"
    theme["rank_priority"] = theme.rank63
    theme = theme[["entry_date", "signal_date", "symbol", "theme", "source", "rank_priority", "rsi_signal"]]

    masks = rule_masks(z)
    cl, op = market["close"], market["open"]
    rows = []
    for period, start, end in (
        ("DISCOVERY", pd.Timestamp("2016-01-04"), v1.DISC_END),
        ("CONFIRM", v1.CONF_START, pd.Timestamp("2026-06-30")),
    ):
        cal = cl.index[(cl.index >= start) & (cl.index <= end)]
        th = theme[theme.entry_date.isin(cal)].copy()
        base = v1.simulate_combined_preempt(cal, op, cl, th, th.iloc[0:0])
        rows.append({"period": period, "rule": "THEME_ONLY", **base})
        for rule in rules:
            if rule == "BASE_RS85_RSI30":
                mk = z.copy()
            else:
                mk = z.loc[masks[rule]].copy()
            mk = mk[mk.entry_date.isin(cal)].copy()
            mk["source"] = "market"
            mk["theme"] = mk.symbol
            mk["rank_priority"] = (
                (100.0 - mk.sector_rs63_pct) * 10000.0
                + (100.0 - mk.rs189_signal) * 100.0
                + mk.rsi_min_reset
            )
            mk = mk[["entry_date", "signal_date", "symbol", "theme", "source", "rank_priority", "rsi_signal"]]
            res = v1.simulate_combined_preempt(cal, op, cl, th, mk)
            rows.append({"period": period, "rule": rule, **res})
    return pd.DataFrame(rows)


def finalize(pre: dict, combined: pd.DataFrame) -> dict:
    if not pre.get("ranking"):
        return {"selected": None, "reason": "No rule passed event and max-one portfolio guardrails.", "ranking": []}
    d = combined[combined.period == "DISCOVERY"].set_index("rule")
    c = combined[combined.period == "CONFIRM"].set_index("rule")
    bd, bc = d.loc["THEME_ONLY"], c.loc["THEME_ONLY"]
    ranked = []
    for r in pre["ranking"]:
        rule = r["rule"]
        if rule not in d.index or rule not in c.index:
            continue
        rd, rc = d.loc[rule], c.loc[rule]
        if int(rd.accepted_theme) != int(bd.accepted_theme) or int(rc.accepted_theme) != int(bc.accepted_theme):
            continue
        if float(rd.cagr) <= float(bd.cagr) or float(rc.cagr) <= float(bc.cagr):
            continue
        if float(rc.mdd) < float(bc.mdd) - 0.02:
            continue
        q = dict(r)
        q.update({
            "disc_combined_cagr_delta": float(rd.cagr - bd.cagr),
            "disc_combined_mdd_delta": float(rd.mdd - bd.mdd),
            "conf_combined_cagr_delta": float(rc.cagr - bc.cagr),
            "conf_combined_mdd_delta": float(rc.mdd - bc.mdd),
            "conf_market_accepted": int(rc.accepted_market),
            "conf_market_preemptions": int(rc.market_preemptions),
        })
        q["final_score"] = (
            q["conf_combined_cagr_delta"] * 2.0
            + q["disc_combined_cagr_delta"]
            + q["conf_median20"]
            + 0.25 * q["conf_p10_20"]
        )
        ranked.append(q)
    ranked = sorted(ranked, key=lambda x: x["final_score"], reverse=True)
    if not ranked:
        return {
            "selected": None,
            "reason": "No contextual rule added return in both halves without displacing theme signals and staying inside the drawdown guardrail.",
            "ranking": [],
        }
    return {
        "selected": ranked[0]["rule"],
        "reason": "Passed event, max-one, and theme-preempted combined portfolio guardrails; highest final score.",
        "ranking": ranked,
    }


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

    trades = pd.read_csv(
        args.market_trades, compression="gzip",
        parse_dates=["touch_date", "signal_date", "entry_date"]
    )
    market = market_base.rebuild_market(root, "2016-01-04", "2026-06-30", 6000, 75, 3)
    z = v1.attach_context(trades, market["close"], root, args.asof, args.nq_start)
    z.to_csv(out / "market_rs189_context_trades.csv.gz", index=False, compression="gzip")

    v1.rule_masks = rule_masks
    summary, port = v1.run_rule_table(z, market)
    summary.to_csv(out / "context_rule_summary.csv", index=False)
    port.to_csv(out / "context_portfolio_max1.csv", index=False)

    pre = select_rule(summary, port)
    combined_rules = list(dict.fromkeys(list(SHORTLIST) + [x["rule"] for x in pre.get("ranking", [])]))
    combined = combined_for_rules(Path(args.theme_trades), z, market, combined_rules)
    combined.to_csv(out / "context_combined_preempt.csv", index=False)
    final = finalize(pre, combined)

    result = {
        "status": "MARKET_RS189_CONTEXT_AUDIT_V2",
        "base_rule": "market-wide RS189 percentile >=85; RSI14 <=30 reset; first RSI rise; next-open; 20 sessions",
        "decision": final,
        "pre_combined": pre,
        "interpretation_contract": {
            "rsi": "Do not demand a deeper reset than RSI30 unless it proves better; deep <=25 and <=27.5 are tested subgroups, not assumptions.",
            "mc57": "Test both market level and direction; V2 explicitly tests 20<=MC57<50 and its 20-35/35-50 sub-bands after V1 showed high-MC deterioration.",
            "sector_strength": "signal-date sector RS63 percentile; >=60 means sector is in the top 40% of sectors by median 63d return.",
            "slot": "supplemental market-wide sleeve max1; Theme RSI signals have preemption priority so market-wide names cannot steal a theme slot.",
        },
        "limitations": [
            "Current-universe and current industry classification survivorship bias remain.",
            "2022+ is confirmation, not pristine untouched out-of-sample.",
            "Sector strength is reconstructed from current classification and 63d median return, not Theme Momentum.",
            "No individual-stock tax model.",
            "V2 adds only a small fixed neighborhood of MC-band / sector / RSI interactions motivated by V1 diagnostics.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2))
    print(json.dumps(safe(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

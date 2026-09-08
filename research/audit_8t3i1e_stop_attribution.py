from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from research import audit_stock_nqsar_theme30_pit as audit
from research import preimpl_core11_early1_pit as pit
from research import nqsar_centric_broad_scan as broad
from research import nqsar_hybrid_three_role_exact as hybrid
from research import backtest_8t3i1e_vs_current_with_tqqq as backtest
from research.run_backtest_8t3i1e_tqqq_resilient import resilient_download_ohlcv
import build_v38_early1_live as earlylive
import build_v38_sleeve_live as sleeve

START = backtest.START
END = backtest.END
VARIANTS = (("CURRENT_RULE", "CURRENT"), ("NEW_8T3I1E", "HYBRID8T3I_E1"))


def safe(x):
    if isinstance(x, dict):
        return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [safe(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x)
        return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp):
        return str(x.date())
    return x


def git_blob(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def verify_freeze(root: Path) -> dict:
    manifest = json.loads((root / "research/8t3i1e_freeze_manifest.json").read_text(encoding="utf-8"))
    checked = {}
    for rel, expected in manifest.get("source_pins", {}).items():
        got = git_blob(root / rel)
        checked[rel] = {"expected": expected, "got": got, "match": got == expected}
        if got != expected:
            raise RuntimeError(f"FREEZE_SOURCE_CHANGED {rel} expected={expected} got={got}")
    return {"freeze_sha256": manifest.get("freeze_sha256"), "checked": checked}


def px(frame: pd.DataFrame, d: pd.Timestamp, s: str) -> float:
    try:
        z = float(frame.at[d, s])
        return z if np.isfinite(z) and z > 0 else np.nan
    except Exception:
        return np.nan


def candidate_sources(c: dict, kind: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in c.get("candidates") or []:
        sym = str(row.get("ticker") or "")
        if not sym:
            continue
        if kind == "CURRENT":
            out[sym] = "CURRENT_CORE"
        else:
            out[sym] = str(row.get("source") or "HYBRID_CORE")
    early = c.get("early1") or {}
    for row in early.get("candidates") or []:
        sym = str(row.get("ticker") or "")
        if sym:
            out.setdefault(sym, "EARLY1")
    return out


def winner_flag(p: dict | None) -> bool:
    if not p:
        return False
    try:
        return bool(p.get("partial_done")) or float(p.get("peak_close") or 0) >= float(p.get("entry_price") or np.inf) * 1.24
    except Exception:
        return False


def simulate_detail(idx, mx, nq, e, m, name: str, kind: str):
    first = pd.Timestamp(idx[0])
    state = {
        "status": "READY",
        "asof": str(first.date()),
        "cash": 1.0,
        "positions": [],
        "pending": {"full_exits": [], "partial25": [], "entries": []},
    }
    daily = []
    attrs = []
    source_by_signal: dict[str, dict[str, str]] = {}
    instance_source: dict[tuple[str, str], str] = {}

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev_d = pd.Timestamp(idx[i - 1]) if i > 0 else d
        prev_nav = float(state.get("nav") or 1.0)
        before_pos = {str(p["symbol"]): dict(p) for p in state.get("positions", [])}
        pending_before = dict(state.get("pending") or {})
        exit_reason = {str(r.get("symbol")): str(r.get("reason") or "") for r in pending_before.get("full_exits", [])}
        partial_symbols = {str(r.get("symbol")) for r in pending_before.get("partial25", [])}

        c = pit.companion(d, mx, {}, nq, e, True)
        if kind != "CURRENT":
            c = dict(c)
            c["candidates"] = hybrid.hybrid_rows(d, m, kind)
        source_by_signal[str(d.date())] = candidate_sources(c, kind)

        state = sleeve.advance_normal(state, c, str(d.date()), mx["open"], mx["close"])
        after_pos = {str(p["symbol"]): dict(p) for p in state.get("positions", [])}
        ret = float(state["nav"] / prev_nav - 1.0) if i > 0 else 0.0
        mode = str((c.get("market") or {}).get("mode") or "STOP")

        entry_count = 0
        exit_count = 0
        partial_count = 0
        contrib_sum = 0.0

        if i > 0:
            for sym in sorted(set(before_pos) | set(after_pos)):
                b = before_pos.get(sym)
                a = after_pos.get(sym)
                bsh = float(b.get("shares") or 0.0) if b else 0.0
                ash = float(a.get("shares") or 0.0) if a else 0.0
                opx = px(mx["open"], d, sym)
                cpx = px(mx["close"], d, sym)
                pc = px(mx["close"], prev_d, sym)
                pnl = 0.0
                if bsh > 0:
                    if not np.isfinite(opx) or not np.isfinite(pc):
                        raise RuntimeError(f"ATTR_PRICE_REQUIRED {name} {d.date()} {sym} overnight")
                    pnl += bsh * (opx - pc)
                if ash > 0:
                    if not np.isfinite(opx) or not np.isfinite(cpx):
                        raise RuntimeError(f"ATTR_PRICE_REQUIRED {name} {d.date()} {sym} intraday")
                    pnl += ash * (cpx - opx)

                if a and not b:
                    entry_count += 1
                    signal_date = str(a.get("entry_signal_date") or "")
                    src = "EARLY1" if str(a.get("sleeve") or "") == "EARLY" else source_by_signal.get(signal_date, {}).get(sym, "UNKNOWN_CORE")
                    instance_source[(sym, str(a.get("entry_date") or d.date()))] = src
                    action = "ENTRY"
                elif b and not a:
                    exit_count += 1
                    action = "EXIT"
                elif b and a and ash < bsh - 1e-12:
                    partial_count += 1
                    action = "PARTIAL"
                else:
                    action = "HOLD"

                p = a or b or {}
                entry_date = str(p.get("entry_date") or "")
                src = instance_source.get((sym, entry_date))
                if not src:
                    if str(p.get("sleeve") or "") == "EARLY":
                        src = "EARLY1"
                    else:
                        sig = str(p.get("entry_signal_date") or "")
                        src = source_by_signal.get(sig, {}).get(sym, "CURRENT_CORE" if kind == "CURRENT" else "UNKNOWN_CORE")
                    instance_source[(sym, entry_date)] = src

                contrib = pnl / max(prev_nav, 1e-12)
                contrib_sum += contrib
                attrs.append({
                    "variant": name,
                    "date": d,
                    "market_mode": mode,
                    "symbol": sym,
                    "action": action,
                    "entry_date": entry_date,
                    "entry_signal_date": str(p.get("entry_signal_date") or ""),
                    "entry_source": src,
                    "sleeve_before": str(b.get("sleeve") or "") if b else "",
                    "sleeve_after": str(a.get("sleeve") or "") if a else "",
                    "shares_before": bsh,
                    "shares_after": ash,
                    "winner_before": winner_flag(b),
                    "winner_after": winner_flag(a),
                    "partial_done_before": bool(b.get("partial_done")) if b else False,
                    "partial_done_after": bool(a.get("partial_done")) if a else False,
                    "exit_reason": exit_reason.get(sym, ""),
                    "partial_signal": sym in partial_symbols,
                    "pnl_nav_units": pnl,
                    "contribution_return": contrib,
                })

            if abs(contrib_sum - ret) > 2e-9:
                raise RuntimeError(f"ATTRIBUTION_RESIDUAL {name} {d.date()} ret={ret} sum={contrib_sum}")

        daily.append({
            "variant": name,
            "date": d,
            "nav": float(state["nav"]),
            "return": ret,
            "market_mode": mode,
            "positions": int(state.get("position_count") or 0),
            "gross_exposure": float(state.get("desired_pct") or 0.0) / 100.0,
            "entries_at_open": entry_count,
            "exits_at_open": exit_count,
            "partials_at_open": partial_count,
            "attribution_residual": ret - contrib_sum if i > 0 else 0.0,
        })

    return pd.DataFrame(daily), pd.DataFrame(attrs)


def add_stop_episodes(shared: pd.DataFrame) -> pd.DataFrame:
    z = shared[["date", "market_mode"]].drop_duplicates("date").sort_values("date").copy()
    eps = []
    day_idx = []
    trans = []
    ep = 0
    k = 0
    prev = None
    for mode in z["market_mode"].astype(str):
        if mode == "STOP":
            if prev != "STOP":
                ep += 1
                k = 1
                trans.append(str(prev or "START"))
            else:
                k += 1
                trans.append("")
            eps.append(ep)
            day_idx.append(k)
        else:
            eps.append(0)
            day_idx.append(0)
            trans.append("")
            k = 0
        prev = mode
    z["stop_episode"] = eps
    z["stop_day"] = day_idx
    z["transition_from"] = trans
    return z


def exact_compound(s: pd.Series) -> float:
    return float((1.0 + pd.to_numeric(s, errors="coerce").fillna(0.0)).prod() - 1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    args = ap.parse_args()
    root = Path(args.root)
    out = root / args.output
    out.mkdir(parents=True, exist_ok=True)

    freeze = verify_freeze(root)
    symbols, bio = audit.load_universe(root / "universe.csv")
    allowed = earlylive._industry_symbols(root / "industry_map.json")
    early_excluded = set(bio)
    if allowed:
        early_excluded.update(set(symbols) - set(allowed))
    warm = str((START - pd.Timedelta(days=1600)).date())
    end_download = str((END + pd.Timedelta(days=1)).date())

    print("DOWNLOAD_STOCKS", flush=True)
    ohlcv, diag = resilient_download_ohlcv(symbols, warm, end_download, args.batch_size)
    if diag["coverage"] < 0.85:
        raise RuntimeError(diag)
    print("BUILD_INPUTS", flush=True)
    m = broad.build_inputs(ohlcv, bio)
    mx = audit.build_stock_inputs(ohlcv, bio, END)
    e = pit.early_inputs(ohlcv["close"], ohlcv["volume"], early_excluded)
    nq = audit.market_nqsar(str((START - pd.Timedelta(days=120)).date()), end_download).reindex(mx["close"].index).ffill(limit=2)
    idx = mx["close"].index[(mx["close"].index >= START) & (mx["close"].index <= END)]

    dailies = []
    attrs = []
    for name, kind in VARIANTS:
        print("SIM_DETAIL", name, flush=True)
        d, a = simulate_detail(idx, mx, nq, e, m, name, kind)
        ref = backtest.simulate_stock(idx, mx, nq, e, m, kind)
        chk = d.set_index("date")["nav"].reindex(ref.index)
        max_nav_err = float((chk - ref["nav"]).abs().max())
        if max_nav_err > 2e-10:
            raise RuntimeError(f"REFERENCE_NAV_MISMATCH {name} {max_nav_err}")
        d["reference_nav_max_error"] = max_nav_err
        dailies.append(d)
        attrs.append(a)

    daily = pd.concat(dailies, ignore_index=True)
    attr = pd.concat(attrs, ignore_index=True)
    mode_check = daily.pivot(index="date", columns="variant", values="market_mode")
    if not mode_check["CURRENT_RULE"].equals(mode_check["NEW_8T3I1E"]):
        raise RuntimeError("MARKET_MODE_CHANGED_BETWEEN_VARIANTS")

    episodes = add_stop_episodes(daily[daily["variant"] == "CURRENT_RULE"])
    daily = daily.merge(episodes[["date", "stop_episode", "stop_day", "transition_from"]], on="date", how="left")
    attr = attr.merge(episodes[["date", "stop_episode", "stop_day"]], on="date", how="left")

    ep_start = episodes[episodes["stop_day"] == 1].set_index("stop_episode")["date"].to_dict()
    def origin(row):
        ep = int(row.get("stop_episode") or 0)
        if ep <= 0:
            return "NON_STOP"
        start = pd.Timestamp(ep_start[ep])
        try:
            ed = pd.Timestamp(row.get("entry_date"))
        except Exception:
            return "UNKNOWN"
        if ed < start:
            return "PRE_STOP_HELD"
        if ed == start:
            return "FIRST_STOP_DAY_EXEC_FROM_PRIOR_SIGNAL"
        return "LATE_STOP_ENTRY"
    attr["stop_origin"] = attr.apply(origin, axis=1)

    daily.to_csv(out / "daily_variant.csv.gz", index=False, compression="gzip")
    attr.to_csv(out / "position_attribution.csv.gz", index=False, compression="gzip")

    stop_daily = daily[daily["market_mode"] == "STOP"].copy()
    ep_rows = []
    for ep, g0 in stop_daily.groupby("stop_episode"):
        rec = {"stop_episode": int(ep), "start": str(g0["date"].min().date()), "end": str(g0["date"].max().date()), "days": int(g0["date"].nunique())}
        trans0 = episodes[episodes["stop_episode"] == ep]["transition_from"].replace("", np.nan).dropna()
        rec["transition_from"] = str(trans0.iloc[0]) if len(trans0) else ""
        for variant, g in g0.groupby("variant"):
            rec[f"{variant}_return"] = exact_compound(g.sort_values("date")["return"])
            rec[f"{variant}_sum_daily_return"] = float(g["return"].sum())
        cur = g0[g0["variant"] == "CURRENT_RULE"].set_index("date")["return"]
        new = g0[g0["variant"] == "NEW_8T3I1E"].set_index("date")["return"]
        common = cur.index.intersection(new.index)
        rec["excess_log_return"] = float(np.log1p(new.reindex(common)).sum() - np.log1p(cur.reindex(common)).sum())
        ep_rows.append(rec)
    episode_df = pd.DataFrame(ep_rows).sort_values("excess_log_return", ascending=False)
    episode_df.to_csv(out / "stop_episode_summary.csv", index=False)

    sd = stop_daily.pivot(index=["date", "stop_episode", "stop_day"], columns="variant", values="return").reset_index()
    sd["excess_return"] = sd["NEW_8T3I1E"] - sd["CURRENT_RULE"]
    sd["excess_log_return"] = np.log1p(sd["NEW_8T3I1E"]) - np.log1p(sd["CURRENT_RULE"])
    sd.sort_values("excess_log_return", ascending=False).to_csv(out / "stop_daily_excess.csv", index=False)
    sd.groupby("stop_day", as_index=False).agg(days=("date", "count"), mean_excess_return=("excess_return", "mean"), sum_excess_log=("excess_log_return", "sum")).to_csv(out / "stop_day_index_summary.csv", index=False)

    sa = attr[attr["market_mode"] == "STOP"].copy()
    sym = sa.groupby(["variant", "symbol"], as_index=False).agg(contribution=("contribution_return", "sum"), active_rows=("date", "count"))
    sp = sym.pivot(index="symbol", columns="variant", values="contribution").fillna(0.0).reset_index()
    sp["delta_contribution"] = sp["NEW_8T3I1E"] - sp["CURRENT_RULE"]
    sp.sort_values("delta_contribution", ascending=False).to_csv(out / "stop_symbol_delta.csv", index=False)

    grouped = sa.groupby(["variant", "entry_source", "stop_origin", "winner_before", "action"], as_index=False).agg(contribution=("contribution_return", "sum"), rows=("symbol", "count"), symbols=("symbol", "nunique"))
    gp = grouped.pivot_table(index=["entry_source", "stop_origin", "winner_before", "action"], columns="variant", values="contribution", fill_value=0.0).reset_index()
    for v in ("CURRENT_RULE", "NEW_8T3I1E"):
        if v not in gp.columns:
            gp[v] = 0.0
    gp["delta_contribution"] = gp["NEW_8T3I1E"] - gp["CURRENT_RULE"]
    gp.sort_values("delta_contribution", ascending=False).to_csv(out / "stop_mechanism_groups.csv", index=False)

    exitg = sa[sa["action"].isin(["EXIT", "PARTIAL"])].groupby(["variant", "action", "exit_reason"], as_index=False).agg(count=("symbol", "count"), contribution=("contribution_return", "sum"))
    exitg.to_csv(out / "stop_exit_interaction.csv", index=False)

    starts = sa[sa["stop_origin"].isin(["PRE_STOP_HELD", "FIRST_STOP_DAY_EXEC_FROM_PRIOR_SIGNAL"])].groupby(["variant", "stop_episode", "symbol", "entry_source", "stop_origin", "winner_before"], as_index=False).agg(stop_contribution=("contribution_return", "sum"), stop_rows=("date", "count"), exit_count=("action", lambda x: int((x == "EXIT").sum())))
    starts.to_csv(out / "stop_starting_position_summary.csv", index=False)

    pos_delta = sp[sp["delta_contribution"] > 0].sort_values("delta_contribution", ascending=False)
    positive = float(pos_delta["delta_contribution"].sum())
    net = float(sp["delta_contribution"].sum())
    conc = {"positive_delta_total": positive, "net_delta_total": net}
    for k in (1, 5, 10, 20):
        top = float(pos_delta.head(k)["delta_contribution"].sum())
        conc[f"top{k}_share_of_positive_delta"] = top / positive if positive > 0 else None
        conc[f"top{k}_share_of_net_delta"] = top / net if abs(net) > 1e-12 else None
    late = sa[sa["stop_origin"] == "LATE_STOP_ENTRY"]
    conc["late_stop_entry_rows"] = int(len(late))
    conc["late_stop_entry_symbols"] = int(late["symbol"].nunique()) if len(late) else 0

    top_days = sd.sort_values("excess_log_return", ascending=False)
    positive_day_log = float(top_days.loc[top_days["excess_log_return"] > 0, "excess_log_return"].sum())
    for k in (1, 5, 10, 20):
        v = float(top_days.head(k)["excess_log_return"].sum())
        conc[f"top{k}_stop_days_share_of_positive_excess_log"] = v / positive_day_log if positive_day_log > 0 else None

    summary = {
        "method": "Frozen 8T3I1E vs CURRENT Normal Stock STOP attribution. No strategy parameters changed. Daily stock PnL is exactly decomposed into prior-close-to-open PnL on pre-existing shares plus open-to-close PnL on post-open shares; attribution is asserted to reconcile to sleeve NAV return and sleeve NAV is asserted against the frozen reference simulator.",
        "period": [str(START.date()), str(END.date())],
        "coverage": diag,
        "freeze": freeze,
        "stop_episodes": int(episode_df["stop_episode"].nunique()) if len(episode_df) else 0,
        "stop_days": int(sd["date"].nunique()) if len(sd) else 0,
        "concentration": conc,
        "questions": {
            "pre_stop_selection": "stop_starting_position_summary.csv and stop_origin groups",
            "stop_timing": "stop_day_index_summary.csv and stop_episode_summary.csv",
            "few_big_winners": "stop_symbol_delta.csv plus concentration",
            "winner_trail_interaction": "stop_mechanism_groups.csv and stop_exit_interaction.csv"
        },
        "production_changed": False,
        "strategy_changed": False,
    }
    (out / "summary.json").write_text(json.dumps(safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE_STOP_ATTRIBUTION", flush=True)


if __name__ == "__main__":
    main()

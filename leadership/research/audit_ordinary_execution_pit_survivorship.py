from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

import audit_ordinary_stock_exit_trail as ex
import audit_ordinary_stock_market_mode_robustness as base
import audit_ordinary_stock_theme_leave_one_out as loo

SELECTIVE_SLOTS = 4
PARTIAL_FRAC = 0.25


def safe(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [safe(v) for v in x]
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, (np.floating, float)):
        z = float(x); return z if math.isfinite(z) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    return x


def simulate(meta: dict[str, Any], matrices: dict[str, pd.DataFrame], peer_ctx: dict[str, Any],
             ranking: str, cost_bps: float) -> dict[str, Any]:
    """Final PEAK30_PART25_R3 mechanics with constituent-level execution cost.

    Signals use prior completed close and trades use the actual next Open already present
    in the historical OHLC matrix. `cost_bps` is an additional one-way spread/slippage
    haircut on each actual constituent buy/sell gross, not an artificial overnight-gap penalty.
    """
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    opens, closes = matrices["open"], matrices["close"]
    breadth, nq = meta["breadth"], meta["nq"]
    c = float(cost_bps) / 10000.0
    cash = 1.0
    pos: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    red_run = 0
    turnover = 0.0
    fees = 0.0

    def px(frame, date, sym, fallback=None):
        try:
            z = float(frame.at[date, sym])
            if np.isfinite(z) and z > 0: return z
        except Exception: pass
        return fallback

    def sell(sym: str, date: pd.Timestamp, price: float, reason: str, frac: float = 1.0) -> None:
        nonlocal cash, turnover, fees
        p = pos[sym]
        shares = float(p["shares"]) * float(frac)
        gross = shares * price
        fee = gross * c
        cash += gross - fee
        turnover += gross; fees += fee
        p["shares"] -= shares
        if frac >= 1.0 - 1e-12 or p["shares"] <= 1e-15:
            pos.pop(sym, None)
        trades.append({"ranking":ranking,"cost_bps":cost_bps,"symbol":sym,"date":date,"side":"SELL","reason":reason,"price":price,"gross":gross,"fee":fee})

    for i, d0 in enumerate(idx):
        d = pd.Timestamp(d0)
        prev = None if i == 0 else pd.Timestamp(idx[i-1])
        if prev is not None:
            color = str(nq.at[prev,"nq_color"]) if prev in nq.index and pd.notna(nq.at[prev,"nq_color"]) else ""
            red_run = red_run + 1 if color == "Red" else 0
            red_force = color == "Red" and red_run >= 1
            if red_force:
                for sym in list(pos):
                    opx = px(opens,d,sym,px(closes,prev,sym,pos[sym]["entry_price"]))
                    if opx is not None: sell(sym,d,opx,"RED",1.0)
            else:
                for sym in list(pos):
                    p = pos[sym]
                    pc = px(closes,prev,sym,p["entry_price"])
                    if pc is None: continue
                    if (not p["partial_done"]) and pc >= p["entry_price"] * 1.24:
                        opx = px(opens,d,sym,pc)
                        if opx is not None:
                            sell(sym,d,opx,"PARTIAL25",PARTIAL_FRAC)
                            if sym in pos: pos[sym]["partial_done"] = True
                    if sym not in pos: continue
                    p = pos[sym]
                    stop = max(p["entry_price"] * 0.92, p["peak_close"] * 0.70)
                    if pc <= stop:
                        opx = px(opens,d,sym,pc)
                        if opx is not None: sell(sym,d,opx,"INITIAL_OR_PEAK30_STOP",1.0)

            b = float(breadth.loc[prev]) if prev in breadth.index and pd.notna(breadth.loc[prev]) else np.nan
            bucket = base.breadth_bucket(b)
            bull = color in ("Blue","Green")
            cap = base.N_PORT if bull and bucket == 2 else SELECTIVE_SLOTS if bull and bucket == 1 else 0
            if (not red_force) and cap > 0 and len(pos) < cap:
                if ranking == "FINAL_THEME_ATTACK":
                    candidates = ex.ranked_candidates(prev, matrices, peer_ctx, bucket, base.N_PORT)
                elif ranking == "STOCK_RS_ONLY":
                    candidates = loo.stock_only_candidates(prev, matrices, base.N_PORT)
                else:
                    raise ValueError(ranking)
                nav_open = cash
                for sym,p in pos.items():
                    opx = px(opens,d,sym,px(closes,prev,sym,p["entry_price"]))
                    if opx is not None: nav_open += p["shares"] * opx
                slot_gross = nav_open / base.N_PORT
                for sym, info in candidates:
                    if len(pos) >= cap or cash <= 1e-12: break
                    if sym in pos: continue
                    opx = px(opens,d,sym,px(closes,prev,sym,None))
                    if opx is None: continue
                    gross = min(slot_gross, cash / (1.0 + c))
                    if gross <= 1e-10: break
                    fee = gross * c
                    cash -= gross + fee; turnover += gross; fees += fee
                    pos[sym] = {"shares":gross/opx,"entry_price":opx,"entry_date":d,"peak_close":opx,"partial_done":False,**info}
                    entries.append({"ranking":ranking,"cost_bps":cost_bps,"symbol":sym,"signal_date":prev,"entry_date":d,"price":opx,"gross":gross,"fee":fee,"entry_bucket":bucket,**info})

        gross_value = 0.0; nav = cash
        for sym,p in pos.items():
            cp = px(closes,d,sym,px(opens,d,sym,p["entry_price"]))
            if cp is None: cp = p["entry_price"]
            p["peak_close"] = max(p["peak_close"], cp)
            mv = p["shares"] * cp; gross_value += mv; nav += mv
        rows.append({"date":d,"nav":nav,"gross_value":gross_value,"gross_exposure":gross_value/nav if nav>0 else np.nan,"positions":len(pos)})

    daily = pd.DataFrame(rows).set_index("date")
    return {
        "daily": daily,
        "metrics": base.slice_metrics(daily["nav"]),
        "rolling_252": base.rolling_252_stats(daily["nav"]),
        "turnover_gross": float(turnover), "execution_cost_paid": float(fees),
        "trades": pd.DataFrame(trades), "entries": pd.DataFrame(entries),
    }


def fmp_delisted_probe() -> dict[str, Any]:
    key = os.environ.get("FMP_API_KEY", "").strip()
    if not key:
        return {"status":"UNAVAILABLE","reason":"FMP_API_KEY_NOT_CONFIGURED"}
    endpoints = [
        "https://financialmodelingprep.com/stable/delisted-companies",
        "https://financialmodelingprep.com/api/v3/delisted-companies",
    ]
    last_error = None
    for endpoint in endpoints:
        all_rows: list[dict[str, Any]] = []
        try:
            for page in range(0, 20):
                params = {"page":page,"limit":1000,"apikey":key}
                req = Request(endpoint + "?" + urlencode(params), headers={"User-Agent":"V38-audit/1.0"})
                with urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                rows = payload if isinstance(payload,list) else payload.get("historical",[]) if isinstance(payload,dict) else []
                if not rows:
                    if page == 0 and isinstance(payload,dict) and payload.get("Error Message"):
                        raise RuntimeError(str(payload.get("Error Message")))
                    break
                all_rows.extend([z for z in rows if isinstance(z,dict)])
                if len(rows) < 1000: break
            if all_rows:
                d = pd.DataFrame(all_rows)
                date_col = next((x for x in ("delistedDate","delisted_date","date") if x in d.columns), None)
                if date_col:
                    dt = pd.to_datetime(d[date_col], errors="coerce")
                    in_window = (dt >= "2016-01-01") & (dt <= "2026-03-20")
                else:
                    in_window = pd.Series(False,index=d.index)
                exch_col = next((x for x in ("exchange","exchangeShortName") if x in d.columns), None)
                return {
                    "status":"READY","endpoint":endpoint,"rows_downloaded":int(len(d)),
                    "delisted_2016_to_2026M3":int(in_window.sum()),
                    "exchange_counts_window": d.loc[in_window,exch_col].fillna("UNKNOWN").astype(str).value_counts().head(20).to_dict() if exch_col else {},
                    "date_field":date_col,
                }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return {"status":"UNAVAILABLE","reason":last_error or "NO_ROWS"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-03-20")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = Path(args.output); out.mkdir(parents=True,exist_ok=True)

    meta, matrices = ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    peer_ctx = loo.build_leave_one_out_scores(root,matrices)

    # Quantify how the current-survivor universe thins backward through history.
    close = matrices["close"]
    yearly = []
    for y in range(2016,2027):
        z = close.loc[(close.index.year==y)]
        if z.empty: continue
        valid = z.notna().any(axis=0)
        yearly.append({"year":y,"current_universe_names_with_any_price":int(valid.sum()),"downloaded_current_universe_names":int(close.shape[1])})
    pd.DataFrame(yearly).to_csv(out/"current_universe_history_coverage.csv",index=False)

    sims: dict[str,Any] = {}
    for ranking in ("FINAL_THEME_ATTACK","STOCK_RS_ONLY"):
        for bps in (0.0,10.0,25.0,50.0):
            name = f"{ranking}_{int(bps)}BP"
            print("SIM",name,flush=True)
            sim = simulate(meta,matrices,peer_ctx,ranking,bps)
            sims[name] = {
                "metrics":sim["metrics"],"rolling_252":sim["rolling_252"],
                "turnover_gross":sim["turnover_gross"],"execution_cost_paid":sim["execution_cost_paid"],
                "entries":int(len(sim["entries"])),"trade_actions":int(len(sim["trades"])),
            }
            sim["daily"].to_csv(out/f"daily_{name.lower()}.csv")
            if bps in (0.0,50.0):
                sim["entries"].to_csv(out/f"entries_{name.lower()}.csv",index=False)
                sim["trades"].to_csv(out/f"trades_{name.lower()}.csv",index=False)

    rows=[]
    for name,v in sims.items():
        m=v["metrics"]["full"]; conf=v["metrics"]["confirmation"]
        rows.append({"variant":name,"cagr":m.get("cagr"),"mdd":m.get("mdd"),"sharpe":m.get("sharpe"),"confirmation_cagr":conf.get("cagr"),"turnover_gross":v["turnover_gross"],"execution_cost_paid":v["execution_cost_paid"],"entries":v["entries"]})
    pd.DataFrame(rows).to_csv(out/"execution_theme_comparison.csv",index=False)

    fmp = fmp_delisted_probe()
    taxonomy_warning = (
        "FAIL: the historical ordinary-stock research builds the ticker universe from the current universe.csv / current industry_map.json and applies the current sector_snapshot.json theme memberships retrospectively. "
        "Therefore the 2016-2026 ordinary-stock result is not point-in-time taxonomy clean and is not survivorship-free. STOCK_RS_ONLY removes Theme-ranking dependence but does not repair the current-survivor universe denominator."
    )
    result = {
        "status":"ORDINARY_EXECUTION_PIT_SURVIVORSHIP_AUDIT",
        "coverage":{"start":args.analysis_start,"end":args.analysis_end,"selected_current_universe":int(meta["selected"]),"downloaded_current_universe":int(meta["downloaded"])},
        "data_quality":{
            "pit_taxonomy":"FAIL","survivorship_free":"FAIL","reason":taxonomy_warning,
            "fmp_delisted_probe":fmp,
            "what_is_quantified":"execution-cost sensitivity and a Theme-removal dependency bound inside the same current-survivor universe",
            "what_is_not_proven":"a fully survivorship-free/PIT-clean CAGR, because a complete historical eligible-universe + historical taxonomy source is not present in the research inputs",
        },
        "execution_method":"Actual next-session Open prices already include overnight gaps; extra 0/10/25/50bp is charged on each constituent buy/sell gross.",
        "variants":sims,
    }
    (out/"summary.json").write_text(json.dumps(safe(result),ensure_ascii=False,indent=2),encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False))
    print("=== ORDINARY_EXECUTION_PIT_SURVIVORSHIP_JSON ===")
    print(json.dumps(safe(result),ensure_ascii=False,indent=2))
    print("=== END_ORDINARY_EXECUTION_PIT_SURVIVORSHIP_JSON ===")

if __name__ == "__main__":
    main()

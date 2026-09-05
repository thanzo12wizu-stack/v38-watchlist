from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_rotation_exit_overlays as core
import audit_rotation_exit_sensitivity as sens


@dataclass(frozen=True)
class ConfirmVariant:
    name: str
    threshold: float
    confirm: str


VARIANTS = [
    ConfirmVariant("W10_SMA10", -10, "SMA10"),
    ConfirmVariant("W20_SMA10", -20, "SMA10"),
    ConfirmVariant("W10_EMA21LOW", -10, "EMA21LOW"),
    ConfirmVariant("W20_EMA21LOW", -20, "EMA21LOW"),
    ConfirmVariant("W10_RS63_LT85", -10, "RS63_LT85"),
    ConfirmVariant("W20_RS63_LT85", -20, "RS63_LT85"),
    ConfirmVariant("W10_PEAK_DD10", -10, "PEAK_DD10"),
    ConfirmVariant("W20_PEAK_DD10", -20, "PEAK_DD10"),
    ConfirmVariant("W10_PEAK_DD15", -10, "PEAK_DD15"),
    ConfirmVariant("W20_PEAK_DD15", -20, "PEAK_DD15"),
]


def px(frame: pd.DataFrame, d: pd.Timestamp, sym: str, fallback=None):
    try:
        x = float(frame.at[d, sym])
        if np.isfinite(x) and x > 0:
            return x
    except Exception:
        pass
    return fallback


def stock_confirm(kind: str, sym: str, prev: pd.Timestamp, pc: float, peak: float, matrices: dict[str, pd.DataFrame]) -> bool:
    if kind == "SMA10":
        x = px(matrices["sma10"], prev, sym, None)
        return x is not None and pc <= x
    if kind == "EMA21LOW":
        x = px(matrices["ema21_low"], prev, sym, None)
        return x is not None and pc <= x
    if kind == "RS63_LT85":
        x = px(matrices["rs63"], prev, sym, None)
        return x is not None and x < 85.0
    if kind == "PEAK_DD10":
        return pc <= peak * 0.90
    if kind == "PEAK_DD15":
        return pc <= peak * 0.85
    raise ValueError(kind)


def replay(row: pd.Series, v: ConfirmVariant | None, state_source, matrices, idx: pd.DatetimeIndex) -> dict[str, Any]:
    sym = str(row["symbol"])
    entry = pd.Timestamp(row["entry_date"])
    baseline_exit = pd.Timestamp(row["exit_date"])
    entry_px = float(row["entry_price"])
    baseline_exit_px = float(row["exit_price"])
    baseline_ret = float(row["total_return"])
    pos = pd.Series(np.arange(len(idx)), index=idx)
    if entry not in pos.index or baseline_exit not in pos.index:
        return {"usable": False}
    a, b = int(pos.at[entry]), int(pos.at[baseline_exit])
    if b <= a:
        return {"usable": False}

    shares, realized = 1.0, 0.0
    partial = False
    armed = False
    arm_date = None
    action_date = None
    exit_date, exit_px = baseline_exit, baseline_exit_px
    exit_reason = "BASELINE_ORIGINAL_EXIT"
    peak = entry_px
    c0 = px(matrices["close"], entry, sym, entry_px)
    peak = max(peak, c0 if c0 is not None else entry_px)

    for j in range(a + 1, b + 1):
        d = pd.Timestamp(idx[j]); prev = pd.Timestamp(idx[j - 1])
        pc = px(matrices["close"], prev, sym, entry_px)
        if pc is None:
            continue
        peak = max(peak, pc)
        if v is not None:
            st = state_source.state(sym, prev)
            w = core.warning(st, core.Variant(name="ARM", threshold=v.threshold))
            if w and not armed:
                armed = True
                arm_date = prev
            confirmed = armed and stock_confirm(v.confirm, sym, prev, pc, peak, matrices)
        else:
            confirmed = False

        if d == baseline_exit:
            break
        op = px(matrices["open"], d, sym, pc)
        if op is None:
            continue
        if confirmed:
            exit_date, exit_px = d, op
            exit_reason = f"ROT_ARM_{v.confirm}"
            action_date = prev
            break
        # Preserve adopted +24% / next-open 25% partial before the original exit.
        if (not partial) and pc >= entry_px * 1.24:
            sold = shares * .25
            realized += sold * op
            shares -= sold
            partial = True
        dc = px(matrices["close"], d, sym, pc)
        if dc is not None:
            peak = max(peak, dc)

    total = realized + shares * exit_px
    overlay_ret = total / entry_px - 1.0
    ie = int(pos.at[exit_date]) if exit_date in pos.index else None
    future = {}
    close_a = matrices["close"].reindex(idx)
    for h in (20, 40, 63):
        val = np.nan
        if ie is not None and sym in close_a.columns:
            z = pd.to_numeric(close_a.iloc[ie + 1:min(len(idx), ie + 1 + h)][sym], errors="coerce").dropna()
            if len(z):
                val = float(z.max() / exit_px - 1.0)
        future[h] = val
    return {
        "usable": True, "symbol": sym, "entry_date": entry, "baseline_exit_date": baseline_exit,
        "overlay_exit_date": exit_date, "baseline_return": baseline_ret, "overlay_return": overlay_ret,
        "delta_vs_baseline": overlay_ret - baseline_ret, "armed": armed,
        "acted": action_date is not None, "arm_date": arm_date, "action_date": action_date,
        "exit_reason": exit_reason, "days_earlier": int((baseline_exit - exit_date).days),
        "post20_max": future[20], "post40_max": future[40], "post63_max": future[63],
        "baseline_big50": baseline_ret >= .50, "baseline_big100": baseline_ret >= 1.0,
    }


def cluster_ci(z: pd.DataFrame, cluster: str, reps=5000, seed=5):
    a = z[[cluster, "delta_vs_baseline"]].dropna()
    keys = a[cluster].unique()
    if len(keys) < 4:
        return [None, None]
    rng = np.random.default_rng(seed); vals=[]
    groups = {k:a.loc[a[cluster]==k,"delta_vs_baseline"].to_numpy(float) for k in keys}
    for _ in range(reps):
        ks = rng.choice(keys, len(keys), replace=True)
        x = np.concatenate([groups[k] for k in ks])
        vals.append(float(np.mean(x)))
    return [float(x) for x in np.quantile(vals,[.025,.975])]


def summarize(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, Any]:
    z=df[df.usable==True].copy()  # noqa: E712
    acted=z[z.acted==True].copy()  # noqa: E712
    if acted.empty:
        return {"n":int(len(z)),"acted_n":0}
    p=pd.Series(np.arange(len(calendar)),index=calendar)
    loc=p.reindex(pd.to_datetime(acted.entry_date)).to_numpy(float)
    acted=acted[np.isfinite(loc)].copy(); loc=loc[np.isfinite(loc)]
    acted["block20"]=(loc//20).astype(int)
    d=pd.to_numeric(acted.delta_vs_baseline,errors="coerce")
    return {
        "n":int(len(z)), "armed_n":int(z.armed.sum()), "acted_n":int(len(acted)),
        "mean_delta":float(d.mean()), "median_delta":float(d.median()), "better_rate":float((d>0).mean()),
        "mean_days_earlier":float(pd.to_numeric(acted.days_earlier,errors="coerce").mean()),
        "post20_ge20_rate":float((pd.to_numeric(acted.post20_max,errors="coerce")>=.20).mean()),
        "post40_ge20_rate":float((pd.to_numeric(acted.post40_max,errors="coerce")>=.20).mean()),
        "post63_ge50_rate":float((pd.to_numeric(acted.post63_max,errors="coerce")>=.50).mean()),
        "big50_acted":int(acted.baseline_big50.sum()), "big100_acted":int(acted.baseline_big100.sum()),
        "block20_ci95":cluster_ci(acted,"block20",seed=5107),
        "symbol_cluster_ci95":cluster_ci(acted,"symbol",seed=6107),
    }


def period_summaries(df: pd.DataFrame, calendar: pd.DatetimeIndex):
    return {
        "DISCOVERY_2022_2023":summarize(df[(df.entry_date>=pd.Timestamp('2022-04-18'))&(df.entry_date<=pd.Timestamp('2023-12-31'))],calendar),
        "CONFIRMATION_2024_PLUS":summarize(df[df.entry_date>=pd.Timestamp('2024-01-01')],calendar),
        "RECENT_2025_PLUS":summarize(df[df.entry_date>=pd.Timestamp('2025-01-01')],calendar),
        "ALL_2022_PLUS":summarize(df,calendar),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default='.')
    ap.add_argument('--panel',type=Path,required=True); ap.add_argument('--snapshots',type=Path,required=True)
    ap.add_argument('--output',required=True); ap.add_argument('--analysis-start',default='2022-04-18'); ap.add_argument('--analysis-end',default='2026-06-20')
    ap.add_argument('--max-tickers',type=int,default=6000); ap.add_argument('--batch-size',type=int,default=60)
    args=ap.parse_args(); root=Path(args.root); out=root/args.output; out.mkdir(parents=True,exist_ok=True)

    panel,snaps=core.load_rotation(args.panel,args.snapshots); strict=core.PITState(panel,snaps)
    broad=sens.CurrentClassificationState(panel,sens.build_current_map(root/'universe.csv'))
    meta,matrices=core.ex.build_inputs_ext(root,args.analysis_start,args.analysis_end,args.max_tickers,args.batch_size)
    peer=core.loo.build_leave_one_out_scores(root,matrices)
    base_sim=core.simulate(meta,matrices,peer,strict,core.VARIANTS[0]); trades=base_sim['trades'].copy()
    calendar=meta['analysis_idx']

    noop=pd.DataFrame([replay(r,None,strict,matrices,calendar) for _,r in trades.iterrows()])
    err=pd.to_numeric(noop.delta_vs_baseline,errors='coerce').abs().dropna()
    result={
      'status':'ROTATION_STOCK_CONFIRM_EXIT_SCREEN','research_only':True,'stage':'EXPLORATORY_SECOND_STAGE',
      'warning':'Sector PriceScore>=70 then Internal20D deterioration arms stock-specific confirmation. Warning itself never exits.',
      'replay_qa':{'n':int(len(err)),'mean_abs_error':float(err.mean()),'max_abs_error':float(err.max())},
      'strict_pit':{},'broad_current_classification_sensitivity':{},
      'guardrails':['Strict PIT is primary but low coverage.','Broad current-classification mapping is look-ahead sensitivity only.','Standalone SMA10/EMA21/RS weakness exits were previously rejected; only their AND with a prior Sector warning is screened here.','No production rule is changed.']
    }
    for v in VARIANTS:
        for label,state,key in [('strict',strict,'strict_pit'),('broad',broad,'broad_current_classification_sensitivity')]:
            df=pd.DataFrame([replay(r,v,state,matrices,calendar) for _,r in trades.iterrows()])
            df.to_csv(out/f'{label}_{v.name}.csv',index=False)
            result[key][v.name]=period_summaries(df,calendar)
    (out/'summary_rotation_stock_confirm.json').write_text(json.dumps(core.safe(result),ensure_ascii=False,indent=2),encoding='utf-8')
    print('=== ROTATION_STOCK_CONFIRM_JSON ==='); print(json.dumps(core.safe(result),ensure_ascii=False,indent=2)); print('=== END_ROTATION_STOCK_CONFIRM_JSON ===')

if __name__=='__main__': main()

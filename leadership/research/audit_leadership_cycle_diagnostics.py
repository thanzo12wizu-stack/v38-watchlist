from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import audit_ordinary_stock_market_mode_robustness as base
import audit_leadership_cycle as lc

DISC_END = pd.Timestamp("2021-12-31")
CONF_START = pd.Timestamp("2022-01-03")


def safe(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [safe(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def transitions(mask: pd.Series) -> list[pd.Timestamp]:
    m = mask.fillna(False).astype(bool)
    x = m & ~m.shift(1, fill_value=False)
    return [pd.Timestamp(d) for d in x.index[x]]


def cooldown_dates(ds: list[pd.Timestamp], idx: pd.DatetimeIndex, cooldown: int = 20) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    last = -10**9
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    for d in ds:
        i = pos.get(pd.Timestamp(d))
        if i is None:
            continue
        if i - last >= cooldown:
            out.append(pd.Timestamp(d))
            last = i
    return out


def transition_recall(
    red_starts: list[pd.Timestamp], signal_crosses: list[pd.Timestamp], idx: pd.DatetimeIndex,
    lookback: int,
) -> dict[str, Any]:
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    sigpos = sorted(pos[d] for d in signal_crosses if d in pos)
    leads_earliest: list[int] = []
    leads_latest: list[int] = []
    hit_dates: list[str] = []
    misses: list[str] = []
    for d in red_starts:
        p = pos.get(d)
        if p is None:
            continue
        z = [s for s in sigpos if p - lookback <= s < p]
        if z:
            leads_earliest.append(p - min(z))
            leads_latest.append(p - max(z))
            hit_dates.append(str(d.date()))
        else:
            misses.append(str(d.date()))
    n = len(hit_dates) + len(misses)
    return {
        "red_transitions": n,
        "hits": len(hit_dates),
        "recall": float(len(hit_dates) / n) if n else None,
        "earliest_lead_median": float(np.median(leads_earliest)) if leads_earliest else None,
        "earliest_lead_mean": float(np.mean(leads_earliest)) if leads_earliest else None,
        "latest_lead_median": float(np.median(leads_latest)) if leads_latest else None,
        "latest_lead_mean": float(np.mean(leads_latest)) if leads_latest else None,
        "miss_dates": misses,
    }


def false_alarm_rate(
    signal_crosses: list[pd.Timestamp], red_starts: list[pd.Timestamp], idx: pd.DatetimeIndex,
    forward: int,
) -> dict[str, Any]:
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    redpos = sorted(pos[d] for d in red_starts if d in pos)
    alarms = []
    false = []
    for d in signal_crosses:
        p = pos.get(d)
        if p is None:
            continue
        alarms.append(d)
        if not any(p < r <= p + forward for r in redpos):
            false.append(d)
    years = max((idx.max() - idx.min()).days / 365.25, 1.0)
    return {
        "alarms": len(alarms),
        "false_alarms": len(false),
        "false_alarm_share": float(len(false) / len(alarms)) if alarms else None,
        "false_alarms_per_year": float(len(false) / years),
        "false_dates": [str(d.date()) for d in false],
    }


def future_mdd(close: pd.Series, h: int = 60) -> pd.Series:
    arr = pd.to_numeric(close, errors="coerce").to_numpy(float)
    out = np.full(len(arr), np.nan)
    for i in range(len(arr)):
        j = i + h
        if j >= len(arr) or not np.isfinite(arr[i]):
            continue
        z = arr[i:j + 1]
        if np.isfinite(z).sum() < max(5, h // 2):
            continue
        s = pd.Series(z).dropna()
        out[i] = float((s / s.cummax() - 1.0).min())
    return pd.Series(out, index=close.index)


def forward_return(close: pd.Series, h: int) -> pd.Series:
    return close.shift(-h) / close - 1.0


def state_stats(df: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    z = df.loc[mask.reindex(df.index).fillna(False)].dropna(subset=["mdd60"])
    if z.empty:
        return {"n": 0}
    return {
        "n": int(len(z)),
        "dd10_prob": float((z["mdd60"] <= -0.10).mean()),
        "dd5_prob": float((z["mdd60"] <= -0.05).mean()),
        "mdd60_mean": float(z["mdd60"].mean()),
        "ret20_mean": float(z["ret20"].mean()),
        "ret60_mean": float(z["ret60"].mean()),
    }


def odds(ae: int, an: int, be: int, bn: int) -> float:
    return float(((ae + 0.5) * (bn + 0.5)) / ((an + 0.5) * (be + 0.5)))


def compare_state(df: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    m = mask.reindex(df.index).fillna(False)
    a = df.loc[m].dropna(subset=["mdd60"])
    b = df.loc[~m].dropna(subset=["mdd60"])
    if len(a) < 3 or len(b) < 10:
        return {"state": state_stats(df, m), "nonstate": state_stats(df, ~m)}
    ae = int((a["mdd60"] <= -0.10).sum()); an = len(a) - ae
    be = int((b["mdd60"] <= -0.10).sum()); bn = len(b) - be
    return {
        "state": state_stats(df, m),
        "nonstate": state_stats(df, ~m),
        "dd10_odds_ratio": odds(ae, an, be, bn),
        "dd10_risk_difference": float((a["mdd60"] <= -0.10).mean() - (b["mdd60"] <= -0.10).mean()),
        "ret20_difference": float(a["ret20"].mean() - b["ret20"].mean()),
        "mdd60_difference": float(a["mdd60"].mean() - b["mdd60"].mean()),
    }


def nonoverlap_ensemble(df: pd.DataFrame, mask: pd.Series, step: int = 20) -> dict[str, Any]:
    ors: list[float] = []
    rds: list[float] = []
    retd: list[float] = []
    for off in range(step):
        sub = df.iloc[off::step]
        m = mask.reindex(sub.index).fillna(False)
        a = sub.loc[m].dropna(subset=["mdd60"])
        b = sub.loc[~m].dropna(subset=["mdd60"])
        if len(a) < 3 or len(b) < 5:
            continue
        ae = int((a.mdd60 <= -0.10).sum()); an = len(a) - ae
        be = int((b.mdd60 <= -0.10).sum()); bn = len(b) - be
        ors.append(odds(ae, an, be, bn))
        rds.append(float((a.mdd60 <= -0.10).mean() - (b.mdd60 <= -0.10).mean()))
        retd.append(float(a.ret20.mean() - b.ret20.mean()))
    return {
        "valid_offsets": len(ors),
        "dd10_or_median": float(np.median(ors)) if ors else None,
        "dd10_or_p25": float(np.quantile(ors, 0.25)) if ors else None,
        "dd10_or_p75": float(np.quantile(ors, 0.75)) if ors else None,
        "risk_diff_median": float(np.median(rds)) if rds else None,
        "ret20_diff_median": float(np.median(retd)) if retd else None,
    }


def correction_episodes(close: pd.Series, threshold: float = -0.10, recover: float = -0.03) -> list[dict[str, Any]]:
    s = pd.to_numeric(close, errors="coerce").dropna()
    if s.empty:
        return []
    peak = float(s.iloc[0]); peak_date = pd.Timestamp(s.index[0])
    active = False
    start = None
    trough_date = None
    trough_px = None
    episode_peak = peak
    rows: list[dict[str, Any]] = []
    for d0, px0 in s.items():
        d = pd.Timestamp(d0); px = float(px0)
        if not active:
            if px > peak:
                peak, peak_date = px, d
            dd = px / peak - 1.0
            if dd <= threshold:
                active = True
                start = d
                trough_date = d
                trough_px = px
                episode_peak = peak
        else:
            if px < float(trough_px):
                trough_px, trough_date = px, d
            dd = px / episode_peak - 1.0
            if dd >= recover:
                rows.append({
                    "start": start, "trough": trough_date, "end": d,
                    "peak": episode_peak, "trough_px": trough_px,
                    "depth": float(trough_px / episode_peak - 1.0),
                })
                active = False
                peak, peak_date = px, d
                start = trough_date = trough_px = None
    if active and trough_date is not None:
        rows.append({
            "start": start, "trough": trough_date, "end": s.index[-1],
            "peak": episode_peak, "trough_px": trough_px,
            "depth": float(trough_px / episode_peak - 1.0), "open_episode": True,
        })
    return rows


def bottom_signal_audit(
    episodes: list[dict[str, Any]], series: pd.Series, threshold: float,
    idx: pd.DatetimeIndex, lookback: int = 40,
) -> dict[str, Any]:
    pos = {pd.Timestamp(d): i for i, d in enumerate(idx)}
    state = (series <= threshold).reindex(idx).fillna(False)
    crosses = transitions(state)
    crosspos = [pos[d] for d in crosses if d in pos]
    hits = 0; leads_first: list[int] = []; leads_latest: list[int] = []
    detail = []
    for ep in episodes:
        t = pd.Timestamp(ep["trough"])
        p = pos.get(t)
        if p is None:
            continue
        state_window = state.iloc[max(0, p - lookback):p + 1]
        z = [c for c in crosspos if p - lookback <= c <= p]
        hit = bool(state_window.any())
        if hit:
            hits += 1
        if z:
            leads_first.append(p - min(z)); leads_latest.append(p - max(z))
        detail.append({"trough": str(t.date()), "depth": ep.get("depth"), "hit": hit,
                       "first_cross_lead": p - min(z) if z else None,
                       "latest_cross_lead": p - max(z) if z else None})
    n = len(detail)
    return {
        "episodes": n,
        "state_seen_hits": hits,
        "state_seen_recall": float(hits / n) if n else None,
        "cross_hits": len(leads_latest),
        "cross_recall": float(len(leads_latest) / n) if n else None,
        "first_cross_lead_median": float(np.median(leads_first)) if leads_first else None,
        "latest_cross_lead_median": float(np.median(leads_latest)) if leads_latest else None,
        "detail": detail,
    }


def correlation(sig: pd.DataFrame, breadth: pd.Series, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict[str, Any]:
    x = sig[["f1", "f2", "f3", "leader_temp", "run_fade_share"]].copy()
    x["breadth50"] = breadth
    if start is not None:
        x = x.loc[x.index >= start]
    if end is not None:
        x = x.loc[x.index <= end]
    return safe(x.corr(method="spearman").round(4).to_dict())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--output", required=True)
    ap.add_argument("--analysis-start", default="2016-01-04")
    ap.add_argument("--analysis-end", default="2026-09-01")
    ap.add_argument("--max-tickers", type=int, default=6000)
    ap.add_argument("--batch-size", type=int, default=75)
    args = ap.parse_args()
    root = Path(args.root); out = root / args.output; out.mkdir(parents=True, exist_ok=True)

    print("BUILD INPUTS", flush=True)
    meta, matrices = base.build_inputs(root, args.analysis_start, args.analysis_end, args.max_tickers, args.batch_size)
    idx = pd.DatetimeIndex(meta["analysis_idx"])
    sig = lc.build_leadership_series(matrices).reindex(idx)
    breadth = meta["breadth"].reindex(idx)
    nq_color = meta["nq"].reindex(idx)["nq_color"].ffill(limit=1)

    market = lc.download_market(
        str((pd.Timestamp(args.analysis_start) - pd.Timedelta(days=10)).date()),
        str((pd.Timestamp(args.analysis_end) + pd.Timedelta(days=120)).date()),
    )
    qqq = market["QQQ"].reindex(idx)
    mkt = pd.DataFrame(index=idx)
    mkt["qqq_close"] = qqq["Close"]
    mkt["mdd60"] = future_mdd(mkt["qqq_close"], 60)
    mkt["ret20"] = forward_return(mkt["qqq_close"], 20)
    mkt["ret60"] = forward_return(mkt["qqq_close"], 60)

    red = nq_color.eq("Red")
    red_starts = transitions(red)
    f1_cross = transitions(sig.f1 >= 0.30)
    f2_cross = transitions(sig.f2 >= 0.40)

    red_audit: dict[str, Any] = {}
    for split_name, start, end in (
        ("full", None, None),
        ("discovery", None, DISC_END),
        ("confirmation", CONF_START, None),
    ):
        reds = [d for d in red_starts if (start is None or d >= start) and (end is None or d <= end)]
        f1s = [d for d in f1_cross if (start is None or d >= start - pd.Timedelta(days=100)) and (end is None or d <= end)]
        f2s = [d for d in f2_cross if (start is None or d >= start - pd.Timedelta(days=100)) and (end is None or d <= end)]
        red_audit[split_name] = {}
        for lb in (20, 40, 60, 80):
            red_audit[split_name][f"F1_LB{lb}"] = transition_recall(reds, f1s, idx, lb)
            red_audit[split_name][f"F2_LB{lb}"] = transition_recall(reds, f2s, idx, lb)
        red_audit[split_name]["F1_FALSE60_RAW"] = false_alarm_rate(f1s, reds, idx, 60)
        red_audit[split_name]["F2_FALSE60_RAW"] = false_alarm_rate(f2s, reds, idx, 60)
        red_audit[split_name]["F1_FALSE60_CD20"] = false_alarm_rate(cooldown_dates(f1s, idx, 20), reds, idx, 60)
        red_audit[split_name]["F2_FALSE60_CD20"] = false_alarm_rate(cooldown_dates(f2s, idx, 20), reds, idx, 60)

    families = {
        "F1_30": sig.f1 >= 0.30,
        "F2_40": sig.f2 >= 0.40,
        "F2_60": sig.f2 >= 0.60,
        "F3_40": sig.f3 >= 0.40,
        "F3_60": sig.f3 >= 0.60,
        "TEMP_LE10": sig.leader_temp <= 10.0,
        "RUN_FADE": sig.run_health.eq("fade"),
        "F1_F2": (sig.f1 >= 0.30) & (sig.f2 >= 0.40),
        "F1_F2_BULL60": (sig.f1 >= 0.30) & (sig.f2 >= 0.40) & nq_color.isin(["Blue", "Green"]) & (breadth >= 60.0),
        "F1_F2_WEAK_GATE": (sig.f1 >= 0.30) & (sig.f2 >= 0.40) & (~nq_color.isin(["Blue", "Green"]) | (breadth < 60.0)),
    }
    state_audit: dict[str, Any] = {}
    for fam, mask in families.items():
        state_audit[fam] = {}
        for split_name, start, end in (
            ("full", None, None),
            ("discovery", None, DISC_END),
            ("confirmation", CONF_START, None),
        ):
            z = mkt
            mm = mask
            if start is not None:
                z = z.loc[z.index >= start]; mm = mm.loc[mm.index >= start]
            if end is not None:
                z = z.loc[z.index <= end]; mm = mm.loc[mm.index <= end]
            state_audit[fam][split_name] = {
                "all_days": compare_state(z, mm),
                "nonoverlap20_ensemble": nonoverlap_ensemble(z, mm, 20),
            }

    episodes = correction_episodes(mkt.qqq_close, -0.10, -0.03)
    temp_bottom = {str(th): bottom_signal_audit(episodes, sig.leader_temp, th, idx, 40) for th in (5.0, 10.0, 15.0, 20.0)}

    # Also test F1/F2 presence before the same objective correction troughs.
    bottom_context = {
        "F1_30": bottom_signal_audit(episodes, -sig.f1 * 100.0, -30.0, idx, 40),
        "F2_40": bottom_signal_audit(episodes, -sig.f2 * 100.0, -40.0, idx, 40),
    }

    series_out = sig.copy()
    series_out["breadth50"] = breadth
    series_out["nqsar"] = nq_color
    series_out["qqq_close"] = mkt.qqq_close
    series_out["qqq_mdd60_fwd"] = mkt.mdd60
    series_out["qqq_ret20_fwd"] = mkt.ret20
    series_out["qqq_ret60_fwd"] = mkt.ret60
    series_out.to_csv(out / "diagnostic_series.csv")
    pd.DataFrame(episodes).to_csv(out / "qqq_correction_episodes.csv", index=False)

    result = {
        "status": "LEADERSHIP_CYCLE_DIAGNOSTICS",
        "coverage": {
            "selected": meta.get("selected"), "downloaded": meta.get("downloaded"),
            "analysis_sessions": len(idx), "analysis_end": args.analysis_end,
        },
        "red_transition_count": len(red_starts),
        "red_transition_dates": [str(d.date()) for d in red_starts],
        "red_transition_audit": red_audit,
        "state_depth_audit": state_audit,
        "qqq_dd10_episode_count": len(episodes),
        "temperature_vs_correction_bottoms": temp_bottom,
        "warning_vs_correction_bottoms": bottom_context,
        "spearman": {
            "full": correlation(sig, breadth),
            "discovery": correlation(sig, breadth, end=DISC_END),
            "confirmation": correlation(sig, breadth, start=CONF_START),
        },
        "files": ["diagnostic_series.csv", "qqq_correction_episodes.csv"],
        "limitations": [
            "Current-universe survivorship remains in stock-derived signals.",
            "All-day state statistics overlap heavily; nonoverlap20 ensemble is the robustness check.",
            "Correction bottoms are objective QQQ >=10% drawdown episodes ending after recovery to within 3% of the episode peak.",
        ],
    }
    (out / "summary_diagnostics.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== LEADERSHIP_DIAGNOSTICS ===", flush=True)
    print(json.dumps(safe(result), ensure_ascii=False, indent=2), flush=True)
    print("=== END_LEADERSHIP_DIAGNOSTICS ===", flush=True)


if __name__ == "__main__":
    main()

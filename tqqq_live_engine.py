from __future__ import annotations

import numpy as np
import pandas as pd

PCUR = {
    "base": 0.30, "fast_dd": -0.065, "fast_rec": 4,
    "rg_slow": 0.50, "rg_fast": 0.80, "gb": 0.90,
    "rg_mc_slow": 40, "cooldown": 20, "panic": 1.0,
}


def wilder_rsi(values, n: int = 14) -> np.ndarray:
    """TradingView/Pine-style Wilder RMA seed used by Stage51 4H research."""
    a = np.asarray(values, float)
    d = np.diff(a, prepend=np.nan)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(a), np.nan)
    ad = np.full(len(a), np.nan)
    if len(a) > n:
        au[n] = np.nanmean(up[1:n + 1])
        ad[n] = np.nanmean(dn[1:n + 1])
        for i in range(n + 1, len(a)):
            au[i] = (au[i - 1] * (n - 1) + up[i]) / n
            ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    rs = au / ad
    r = 100 - 100 / (1 + rs)
    r[(ad == 0) & np.isfinite(au)] = 100.0
    r[(au == 0) & (ad == 0)] = 50.0
    return r


def build_4h_bars(five_minute: pd.DataFrame) -> pd.DataFrame:
    """Stage51 RTH bars: 09:30-13:30 and 13:30-16:00 ET partial."""
    x = five_minute.copy()
    if x.empty:
        return pd.DataFrame()
    idx = pd.to_datetime(x.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    x.index = idx
    x = x.sort_index()
    mins = x.index.hour * 60 + x.index.minute
    x = x[(mins >= 570) & (mins < 960)].copy()
    mins = x.index.hour * 60 + x.index.minute
    x["date"] = x.index.normalize()
    x["slot"] = np.where(mins < 810, 0, 1)
    bars = x.groupby(["date", "slot"], sort=True).agg(
        Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
        Close=("Close", "last"), n=("Close", "size"),
    ).reset_index()
    bars = bars[bars.n >= 6].copy().sort_values(["date", "slot"]).reset_index(drop=True)
    bars["rsi14"] = wilder_rsi(bars.Close.to_numpy(float), 14)
    r = bars.rsi14.to_numpy(float)
    bars["touch30"] = (r <= 30) & np.r_[False, r[:-1] > 30]
    return bars


def current30_trace(B: dict[str, np.ndarray], p: dict | None = None) -> dict[str, np.ndarray]:
    """Exact target-state logic from Stage34 PCUR, excluding return accounting."""
    p = dict(PCUR if p is None else p)
    mcv = np.asarray(B["mc"], float)
    nq = np.asarray(B["nq"], np.int8)
    panic = np.asarray(B["panic"], bool)
    a50 = np.asarray(B["a50"], bool)
    a63 = np.asarray(B["a63"], bool)
    a200 = np.asarray(B["a200"], bool)
    a252 = np.asarray(B["a252"], bool)
    gte10 = np.asarray(B["gte10"], bool)
    lte21 = np.asarray(B["lte21"], bool)
    s50x = np.asarray(B["s50a"], float)
    dd = np.asarray(B["dd10"], float)
    n = len(mcv)

    rawbear = (~a200) & (~a252)
    bear5 = np.zeros(n, bool)
    for i in range(4, n):
        bear5[i] = rawbear[i - 4:i + 1].all()
    score3 = (a50.astype(int) + a63.astype(int) + (mcv >= 35).astype(int) + (nq != 0).astype(int)) >= 3
    fr = int(p["fast_rec"])
    rec = np.zeros(n, bool)
    for i in range(fr - 1, n):
        rec[i] = gte10[i - fr + 1:i + 1].all()
    arm = np.empty(n, float)
    for i in range(n):
        arm[i] = np.nanmin(s50x[max(0, i - 19):i + 1])

    slow_a = np.zeros(n, bool)
    fast_a = np.zeros(n, bool)
    mc_a = np.zeros(n, bool)
    slow = fast = mclock = False
    for i in range(n):
        if bear5[i]:
            slow = True
        if slow and (not rawbear[i]) and score3[i] and mcv[i] >= 35:
            slow = False
        if mcv[i] < 25:
            mclock = True
        if mclock and mcv[i] >= 35 and score3[i] and nq[i] != 0:
            mclock = False
        if dd[i] <= p["fast_dd"] and lte21[i]:
            fast = True
        if fast and rec[i]:
            fast = False
        slow_a[i], fast_a[i], mc_a[i] = slow, fast, mclock
    risklock = slow_a | fast_a | mc_a

    base = np.zeros(n, float)
    strong = np.zeros(n, bool)
    for i in range(n):
        x = 0.0 if risklock[i] else p["base"]
        if x > 0 and mcv[i] >= 65 and nq[i] == 3 and a50[i] and a63[i] and s50x[i] <= 2.5:
            x = 1.0
            strong[i] = True
        if panic[i] and s50x[i] <= -2:
            x = max(x, p.get("panic", 1.0))
        base[i] = min(1.0, x)

    target = base.copy()
    sleeve = np.zeros(n, np.int8)
    active = 0
    entry = 0
    seen_blue = False
    cool_until = 0
    for i in range(1, n):
        tr_rg = nq[i - 1] == 0 and nq[i] == 2
        tr_gb = nq[i - 1] == 2 and nq[i] == 3
        tr_bg = nq[i - 1] == 3 and nq[i] == 2
        tr_by = nq[i - 1] == 3 and nq[i] == 1
        if active == 0:
            rgmc = p["rg_mc_slow"] if slow_a[i] else 35
            if tr_rg and arm[i] <= -2 and mcv[i] >= rgmc and risklock[i] and i >= cool_until:
                active, entry, seen_blue = 1, i + 1, False
            elif tr_gb and arm[i] <= -1.5 and mcv[i] >= 35 and (not risklock[i]):
                active, entry, seen_blue = 2, i + 1, True
        if active == 1:
            if nq[i] == 3:
                seen_blue = True
            hold = max(0, i - (entry - 1))
            if (nq[i] in (0, 1)) or hold >= 7:
                if (not seen_blue) and slow_a[i] and p["cooldown"] > 0:
                    cool_until = i + p["cooldown"]
                active = 0
            else:
                if (not risklock[i]) and nq[i] == 3:
                    active, entry, total = 2, i + 1, p["gb"]
                else:
                    total = p["rg_slow"] if slow_a[i] else p["rg_fast"]
                if base[i] >= .999:
                    total = 1.0
                target[i] = max(base[i], total)
                sleeve[i] = active
        elif active == 2:
            hold = max(0, i - (entry - 1))
            bad = risklock[i] or tr_bg or tr_by or nq[i] == 0
            if bad or hold >= 20:
                active = 0
            else:
                total = 1.0 if base[i] >= .999 else p["gb"]
                target[i] = max(base[i], total)
                sleeve[i] = 2

    return {
        "target": np.clip(target, 0, 1), "risklock": risklock,
        "slow_lock": slow_a, "fast_lock": fast_a, "mc_lock": mc_a,
        "sleeve": sleeve, "strong": strong,
    }


def stage56_overlay(
    B: dict[str, np.ndarray], vix_close: np.ndarray, touch30_daily: np.ndarray,
    underlying: np.ndarray | None = None, floor: float = 0.80, max_days: int = 10,
) -> dict[str, np.ndarray]:
    """Stage56 M30_TOUCH30_F80_D10 state with close signal / next-open intent."""
    if underlying is None:
        underlying = current30_trace(B)["target"]
    t = np.asarray(underlying, float).copy()
    mc = np.asarray(B["mc"], float)
    s50a = np.asarray(B["s50a"], float)
    dd10 = np.asarray(B["dd10"], float)
    a200 = np.asarray(B["a200"], bool)
    a252 = np.asarray(B["a252"], bool)
    vx = np.asarray(vix_close, float)
    sig = np.asarray(touch30_daily, bool)
    seed = (s50a <= -0.50) & (vx >= 23.0) & (dd10 <= -0.02)
    n = len(t)
    age = 10**9
    active = False
    entry = -1
    consumed = -1
    active_after_close = np.zeros(n, bool)
    entered = np.zeros(n, bool)
    exited = np.zeros(n, bool)
    held = np.full(n, -1, int)
    seed_age = np.full(n, 10**9, int)
    rawbear = (~a200) & (~a252)
    for i in range(n):
        age = 0 if seed[i] else age + 1
        seed_age[i] = age
        recent = age <= 30
        last = np.flatnonzero(seed[:i + 1])
        sid = int(last[-1]) if len(last) else -1
        allow = mc[i] >= 20
        if (not active) and recent and sig[i] and allow and sid > consumed:
            active = True
            entry = i
            consumed = sid
            entered[i] = True
        if active:
            if seed[i]:
                consumed = max(consumed, i)
            h = i - entry
            held[i] = h
            done = h >= max_days
            bad = mc[i] < 20 or (rawbear[i] and h >= 10) or done or h >= 20
            if bad:
                active = False
                entry = -1
                exited[i] = True
            else:
                t[i] = max(t[i], floor)
        active_after_close[i] = active
    active_at_open = np.r_[False, active_after_close[:-1]]
    return {
        "target": np.clip(t, 0, 1), "seed": seed, "seed_age": seed_age,
        "active_after_close": active_after_close, "active_at_open": active_at_open,
        "entered_close": entered, "exited_close": exited, "held_signal_sessions": held,
    }

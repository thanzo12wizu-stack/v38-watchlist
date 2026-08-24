#!/usr/bin/env python3
from pathlib import Path
import re

p = Path("build_dashboard.py")
s = p.read_text(encoding="utf-8")
orig = s


def replace_once(old, new, label):
    global s
    n = s.count(old)
    if n == 1:
        s = s.replace(old, new, 1)
    elif n == 0 and new in s:
        return
    else:
        raise SystemExit(f"{label}: expected exactly one old occurrence, found {n}")

# 1) Revert the unrequested NQ-gate rename. Keep the pre-existing UI wording.
s = s.replace("NQSAR（短期）", "トレンド判定")
s = s.replace("NQSAR", "NQ 4色ゲート")

# 2) Keep the Market Conditions core description, but remove unrelated overlay renaming/commentary.
replace_once(
    "  D. Market Conditions=中長期の市場構造（短期15・中期55・長期20・Damage10）。NQ 4色ゲート=短期、VIX FEAR CYCLE=パニック/底形成として独立表示。",
    "  D. Market Conditions=中長期の市場構造（短期15・中期55・長期20・Damage10）。",
    "top Market Conditions description",
)
replace_once(
    '    """Market Conditions v3 (display/state only; allocation remains NQ 4色ゲート-driven).\n\n    43 non-levered ETFs, family balanced.  Score is descriptive market health,\n    not a forward-return predictor and does not contain NQ 4色ゲート/VIX/VVIX/credit.\n    """',
    '    """Market Conditions v3.\n\n    43 non-levered ETFs, family balanced. The score is descriptive market health.\n    """',
    "mri_frame docstring",
)

# Restore the pre-existing VIX card title. Market Conditions work must not rename other cards.
s = s.replace("<h2>パニック・底形成 ", "<h2>VIX反転シーケンス ")

# 3) Recovery was validation telemetry, not requested production UI/logic. Remove it.
replace_once(
    '        vals["repair_breadth"] = np.nan; vals["repair_thrust10"] = np.nan\n        vals["qqq_dd"] = np.nan; vals["bottom_context"] = 0.0; vals["mc_coverage"] = 0.0',
    '        vals["mc_coverage"] = 0.0',
    "fallback recovery telemetry",
)
replace_once(
    '    # Recovery telemetry intentionally excludes 5D return/10SMA: this is broader\n    # repair after a damaged market, not a second copy of NQ 4色ゲート.\n    repair_breadth = pd.concat([p["above20"],p["ret21"],p["above50"],p["ma20_gt_50"]],axis=1).mean(axis=1,skipna=True)\n    repair_thrust10 = repair_breadth - repair_breadth.shift(10)\n    qqq = pd.to_numeric(macro.get("QQQ", pd.DataFrame()).get("Close"), errors="coerce") if macro.get("QQQ") is not None else pd.Series(dtype=float)\n    qqq = qqq.reindex(score.index).ffill() if len(qqq) else pd.Series(np.nan,index=score.index)\n    qqq_dd = qqq/qqq.rolling(252,min_periods=126).max()-1.0\n    recent_shock = qqq_dd.rolling(60,min_periods=1).min() <= -0.08\n    bottom_context = (recent_shock & (qqq_dd < -0.02)).astype(float)\n    coverage = c.notna().sum(axis=1) / float(len(MC_MARKET_TICKERS)) * 100.0',
    '    coverage = c.notna().sum(axis=1) / float(len(MC_MARKET_TICKERS)) * 100.0',
    "recovery telemetry block",
)
replace_once(
    '    vals["repair_breadth"] = repair_breadth; vals["repair_thrust10"] = repair_thrust10\n    vals["qqq_dd"] = qqq_dd; vals["bottom_context"] = bottom_context; vals["mc_coverage"] = coverage',
    '    vals["mc_coverage"] = coverage',
    "recovery vals columns",
)

# 4) Preserve the old downstream note contract. The score no longer uses these columns,
#    but existing UI code still reads them. Keeping them avoids coupling a calculator swap
#    to unrelated presentation logic.
compat_anchor = '    vals["median_dd"] = med_dd*100.0\n'
compat_block = '''    vals["median_dd"] = med_dd*100.0

    def _compat_close(ticker):
        d = macro.get(ticker)
        if d is None or not hasattr(d, "columns") or "Close" not in d.columns:
            return pd.Series(np.nan, index=vals.index, dtype=float)
        x = pd.to_numeric(d["Close"], errors="coerce")
        try:
            x.index = pd.to_datetime(x.index).tz_localize(None)
        except Exception:
            pass
        return x.reindex(vals.index).ffill()

    _qqq = _compat_close("QQQ")
    _spy = _compat_close("SPY")
    _rsp = _compat_close("RSP")
    _qqqe = _compat_close("QQQE")
    vals["qqq_50"] = _qqq / _qqq.rolling(50).mean() - 1.0
    vals["qqq_200"] = _qqq / _qqq.rolling(200).mean() - 1.0
    vals["spy_50"] = _spy / _spy.rolling(50).mean() - 1.0
    vals["spy_200"] = _spy / _spy.rolling(200).mean() - 1.0
    vals["rsp_50"] = _rsp / _rsp.rolling(50).mean() - 1.0
    vals["rsp_200"] = _rsp / _rsp.rolling(200).mean() - 1.0
    vals["qqqe_50"] = _qqqe / _qqqe.rolling(50).mean() - 1.0
'''
if compat_block not in s:
    replace_once(compat_anchor, compat_block, "legacy downstream compatibility")

# 5) Remove the unrequested recovery stage / 5D presentation additions.
old_aux = '''    drop = hi20-cur
    if drop < 4: peak="高値圏"
    elif drop < 10: peak="押し目"
    else: peak="深押し"
    delta5 = float(cur-clean.iloc[-6]) if len(clean) >= 6 else 0.0
    rb = float(last.get("repair_breadth")) if pd.notna(last.get("repair_breadth")) else np.nan
    rt = float(last.get("repair_thrust10")) if pd.notna(last.get("repair_thrust10")) else np.nan
    med = float(last.get("pillar_medium")) if pd.notna(last.get("pillar_medium")) else np.nan
    ctx = bool(last.get("bottom_context",0.0) >= 0.5)
    recovery = None
    if ctx and np.isfinite(rb) and np.isfinite(rt):
        if cur >= 55.0 and np.isfinite(med) and med >= 50.0 and rb >= 55.0:
            recovery = "CONFIRMED"
        elif cur >= 45.0 and rb >= 45.0 and rt > 0.0:
            recovery = "REPAIRING"
        elif rb >= 35.0 and rt >= 10.0:
            recovery = "EARLY REPAIR"
    cov = float(last.get("mc_coverage")) if pd.notna(last.get("mc_coverage")) else 0.0
    return dict(cur=cur,hl=hl,slope=slope_dir,bear_n=bear_n,bear_flags=bear_flags,
                peak=peak,drop=drop,hi20=hi20,delta5=delta5,recovery=recovery,
                repair_breadth=rb,repair_thrust10=rt,coverage=cov)
'''
new_aux = '''    drop = hi20-cur
    if drop < 3:    peak = "通常"
    elif drop < 7:  peak = "注意"
    elif drop < 12: peak = "減速"
    else:           peak = "深押し"
    return dict(cur=cur, hl=hl, slope=slope_dir, bear_n=bear_n, bear_flags=bear_flags,
                peak=peak, drop=drop, hi20=hi20)
'''
replace_once(old_aux, new_aux, "auxiliary/recovery rollback")

rec_ui = '''    _rec = aux.get("recovery")
    _rcol = {"EARLY REPAIR":"#fbbf24","REPAIRING":"#58a6ff","CONFIRMED":"#34d399"}.get(_rec,"#9aa4b2")
    _recovery_html = (f'<div class="st" style="font-size:12px;color:{_rcol};margin-top:2px">RECOVERY · <b>{_rec}</b></div>' if _rec else "")
'''
if rec_ui in s:
    s = s.replace(rec_ui, "", 1)
else:
    # Accept formatting-equivalent code through a narrow regex.
    s, n = re.subn(
        r'    _rec = aux\.get\("recovery"\)\n    _rcol = .*?\n    _recovery_html = .*?\n',
        '', s, count=1,
    )
    if n != 1 and "_recovery_html" in s:
        raise SystemExit("recovery UI block: could not remove exactly")

s = s.replace(
    '<div class="st">{band_lab} <span style="font-size:12px;font-weight:700">5D {aux.get(\'delta5\',0.0):+.1f}</span></div>{_recovery_html}',
    '<div class="st">{band_lab}</div>',
)

# Required invariants: no unrequested NQSAR/Recovery additions remain, old NQ/VIX labels are restored.
if "NQSAR" in s or "NQSAR（短期）" in s:
    raise SystemExit("unrequested NQSAR wording remains")
if "_recovery_html" in s or 'aux.get("recovery")' in s or 'repair_thrust10' in s:
    raise SystemExit("unrequested Recovery production code remains")
if "トレンド判定" not in s:
    raise SystemExit("pre-existing trend label was not restored")
if 'if "トレンド判定" not in html: errs.append("trend pill missing")' not in s:
    raise SystemExit("trend-pill selftest was not restored")
if '<h2>VIX反転シーケンス ' not in s:
    raise SystemExit("pre-existing VIX fear-cycle title was not restored")

if s != orig:
    p.write_text(s, encoding="utf-8")
    print("Applied minimal Market Conditions repair")
else:
    print("Minimal Market Conditions repair already applied")

#!/usr/bin/env python3
"""Directional Call/Put walls for fresh chains and stale cache fallbacks.

Dashboard meaning is strict:
  * Call Wall / 上値の壁 = largest absolute call GEX strictly ABOVE spot.
  * Put Wall / 下値の支え = largest absolute put GEX strictly BELOW spot.
A wrong-side strike may be a pin, but it must not be labelled resistance/support.
If the correct side has no usable level, expose None instead of a false wall.
"""
import json
import sys
from pathlib import Path

import build_options_positioning as base

_orig_analyse_expiry = base.analyse_expiry


def _directional(rows, spot, side, n=3):
    vals = []
    field = "call" if side == "call" else "put"
    for row in rows or []:
        try:
            strike = float(row.get("k"))
            gex = float(row.get(field) or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if side == "call" and strike <= spot:
            continue
        if side == "put" and strike >= spot:
            continue
        if abs(gex) <= 0:
            continue
        vals.append((abs(gex), strike))
    vals.sort(reverse=True)
    return [dict(strike=float(strike), gex=float(gex)) for gex, strike in vals[:n]]


def _repair_expiry(exp, spot):
    if not isinstance(exp, dict):
        return exp
    calls_above = _directional(exp.get("strikes"), spot, "call")
    puts_below = _directional(exp.get("strikes"), spot, "put")
    exp["call_walls"] = calls_above
    exp["put_walls"] = puts_below
    exp["call_wall"] = calls_above[0]["strike"] if calls_above else None
    exp["put_wall"] = puts_below[0]["strike"] if puts_below else None
    return exp


def _dist(level, spot, atr):
    if level is None:
        return {"px": None, "pct": None, "atr": None}
    try:
        a = float(atr)
    except (TypeError, ValueError):
        a = 0.0
    return {
        "px": round(float(level), 2),
        "pct": round(float(level) / spot - 1.0, 5),
        "atr": round((float(level) - spot) / a, 2) if a > 0 else None,
    }


def _explain_wall(label, level, spot, atr):
    if level is None:
        return ("現値より上にあるコール建玉/GEXの有効な集中は見つからない。" if label == "call"
                else "現値より下にあるプット建玉/GEXの有効な集中は見つからない。")
    try:
        a = float(atr)
    except (TypeError, ValueError):
        a = 0.0
    pct = (float(level) / spot - 1.0) * 100.0
    days = abs(float(level) - spot) / a if a > 0 else None
    tail = f"現値から{pct:+.1f}%" + (f"、いつもの値動き{days:.1f}日分。" if days is not None else "。")
    if label == "call":
        return "現値より上にあるコール建玉/GEXの最大集中。上値抵抗候補。" + tail
    return "現値より下にあるプット建玉/GEXの最大集中。下値支持候補。" + tail


def _repair_record(rec):
    if not isinstance(rec, dict):
        return rec
    try:
        spot = float(rec.get("spot"))
    except (TypeError, ValueError):
        return rec
    if not spot:
        return rec
    per = rec.get("expiries") or {}
    if not isinstance(per, dict):
        return rec
    for exp in per.values():
        _repair_expiry(exp, spot)

    nearest = rec.get("nearest")
    first = per.get(nearest) if nearest else None
    if not isinstance(first, dict):
        return rec

    cw = first.get("call_wall")
    pw = first.get("put_wall")
    rec["call_wall"] = _dist(cw, spot, rec.get("atr14"))
    rec["put_wall"] = _dist(pw, spot, rec.get("atr14"))
    # Keep confluence only when the selected wall itself is directionally valid.
    conf = rec.get("confluence")
    if not isinstance(conf, dict):
        conf = {}
        rec["confluence"] = conf
    try:
        conf["call_wall"] = base.confluence(cw, rec.get("tech") or {}, spot, rec.get("atr14"))
    except Exception:
        conf["call_wall"] = []
    try:
        conf["put_wall"] = base.confluence(pw, rec.get("tech") or {}, spot, rec.get("atr14"))
    except Exception:
        conf["put_wall"] = []
    rec["range_pos"] = base.position_in_range(spot, pw, cw)

    explain = rec.get("explain")
    if not isinstance(explain, dict):
        explain = {}
        rec["explain"] = explain
    explain["call_wall"] = _explain_wall("call", cw, spot, rec.get("atr14"))
    explain["put_wall"] = _explain_wall("put", pw, spot, rec.get("atr14"))

    # Last-resort invariant: labels can never point to the wrong side of spot.
    if cw is not None and float(cw) <= spot:
        first["call_wall"] = None
        first["call_walls"] = []
        rec["call_wall"] = _dist(None, spot, rec.get("atr14"))
    if pw is not None and float(pw) >= spot:
        first["put_wall"] = None
        first["put_walls"] = []
        rec["put_wall"] = _dist(None, spot, rec.get("atr14"))
    return rec


def analyse_expiry(calls, puts, spot, expiry, asof):
    result = _orig_analyse_expiry(calls, puts, spot, expiry, asof)
    return _repair_expiry(result, float(spot)) if result else result


base.analyse_expiry = analyse_expiry


def _repair_existing_caches():
    cache_dir = Path(base.CACHE_DIR)
    if not cache_dir.is_dir():
        return
    for path in cache_dir.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            _repair_record(rec)
            path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"[opt-wall] cache repair skipped {path.name}: {type(exc).__name__} {exc}\n")


def _repair_output():
    path = Path(base.OUT_JSON)
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = []
    for ticker, rec in (data.get("tickers") or {}).items():
        try:
            _repair_record(rec)
            spot = float(rec.get("spot"))
            cw = (rec.get("call_wall") or {}).get("px")
            pw = (rec.get("put_wall") or {}).get("px")
            if cw is not None and float(cw) <= spot:
                bad.append((ticker, "call", spot, cw))
            if pw is not None and float(pw) >= spot:
                bad.append((ticker, "put", spot, pw))
            if cw is not None and pw is not None and float(cw) == float(pw):
                bad.append((ticker, "same", spot, cw))
        except Exception as exc:
            sys.stderr.write(f"[opt-wall] output repair skipped {ticker}: {type(exc).__name__} {exc}\n")
    if bad:
        raise RuntimeError(f"directional wall invariant failed: {bad[:10]}")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    sys.stderr.write(f"[opt-wall] directional invariants OK for {len(data.get('tickers') or {})} tickers\n")


if __name__ == "__main__":
    _repair_existing_caches()
    rc = base.main()
    _repair_output()
    sys.exit(rc)

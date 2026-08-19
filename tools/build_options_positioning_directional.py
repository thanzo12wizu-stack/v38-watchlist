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
        except (TypeError, ValueError):
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


def _repair_record(rec):
    if not isinstance(rec, dict):
        return rec
    try:
        spot = float(rec.get("spot"))
    except (TypeError, ValueError):
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
    gf = first.get("gamma_flip")
    atr = rec.get("atr14")
    tech = rec.get("tech") or {}
    rec["call_wall"] = base.dist_block(cw, spot, atr)
    rec["put_wall"] = base.dist_block(pw, spot, atr)
    rec.setdefault("confluence", {})["call_wall"] = base.confluence(cw, tech, spot, atr)
    rec.setdefault("confluence", {})["put_wall"] = base.confluence(pw, tech, spot, atr)
    rec["range_pos"] = base.position_in_range(spot, pw, cw)
    reg = base.regime(spot, gf, atr)
    rec["regime"] = reg
    rec["explain"] = base.explain(
        spot, cw, pw, gf, first.get("net_gex", rec.get("net_gex", 0.0)), atr, reg
    )
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
            sys.stderr.write(f"[opt-wall] cache repair skipped {path.name}: {type(exc).__name__}\n")


def _repair_output():
    path = Path(base.OUT_JSON)
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for rec in (data.get("tickers") or {}).values():
        _repair_record(rec)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    # Repair cached records BEFORE base.main so a provider failure cannot reintroduce
    # a same-side/same-strike wall into history or the dashboard snapshot.
    _repair_existing_caches()
    rc = base.main()
    # Safety pass over the final payload covers any fallback path in the base builder.
    _repair_output()
    sys.exit(rc)

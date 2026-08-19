#!/usr/bin/env python3
"""Run the existing options builder with directional Call/Put wall semantics.

The raw builder keeps all strike-level GEX.  For the dashboard labels we must not
call a strike below spot an "upper wall", or a strike above spot a "lower
support".  This wrapper repairs the analysed expiry from its stored strike table:
  * Call Wall = largest absolute call GEX strictly above spot
  * Put Wall  = largest absolute put GEX strictly below spot
If the correct side has no usable level, the wall is None rather than a
mislabelled opposite-side strike.
"""
import sys
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


def analyse_expiry(calls, puts, spot, expiry, asof):
    result = _orig_analyse_expiry(calls, puts, spot, expiry, asof)
    if not result:
        return result
    calls_above = _directional(result.get("strikes"), float(spot), "call")
    puts_below = _directional(result.get("strikes"), float(spot), "put")
    result["call_walls"] = calls_above
    result["put_walls"] = puts_below
    result["call_wall"] = calls_above[0]["strike"] if calls_above else None
    result["put_wall"] = puts_below[0]["strike"] if puts_below else None
    return result


base.analyse_expiry = analyse_expiry

if __name__ == "__main__":
    sys.exit(base.main())

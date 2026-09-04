#!/usr/bin/env python3
"""Directional Call/Put walls for fresh chains and stale cache fallbacks.

Dashboard meaning is strict:
  * Call GEX concentration / resistance candidate = largest absolute call GEX strictly ABOVE spot.
  * Put GEX concentration / support candidate = largest absolute put GEX strictly BELOW spot.
A wrong-side strike may be a pin, but it must not be labelled resistance/support.
If the correct side has no usable level, expose None instead of a false wall.
"""
import json
import sys
from pathlib import Path

import build_options_positioning as base

_orig_analyse_expiry = base.analyse_expiry


def _clean_positioning_rows(df, kind):
    """Keep valid OI/IV rows even when premarket quotes are all zero.

    The positioning proxy is calculated from open interest and implied
    volatility. Yahoo can legitimately report bid=ask=volume=0 outside the
    regular session, so quote inactivity alone must not erase valid OI.
    """
    if df is None or len(df) == 0:
        return base.pd.DataFrame()
    d = df.copy()
    for c in ("strike", "openInterest", "impliedVolatility", "volume", "bid", "ask"):
        if c not in d.columns:
            d[c] = base.np.nan
        d[c] = base.pd.to_numeric(d[c], errors="coerce")
    d = d[(d["strike"] > 0) & (d["openInterest"].fillna(0) > 0)]
    d = d[d["impliedVolatility"].between(base.MIN_IV, base.MAX_IV)]
    d["kind"] = kind
    return d[["strike", "openInterest", "impliedVolatility", "volume", "bid", "ask", "kind"]]


# The workflow runs this directional wrapper. Patch the base module before its
# original analyse_expiry executes so both detailed records and broad scans use
# the same OI/IV-valid chain handling.
base._clean = _clean_positioning_rows


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


def _concentration(rows, spot, side):
    """Use every directional strike so the displayed share is not a top-3 share."""
    walls = _directional(rows, spot, side, n=10_000)
    total = sum(float(w["gex"]) for w in walls)
    share = float(walls[0]["gex"]) / total if walls and total > 0 else None
    lead = (
        float(walls[0]["gex"]) / float(walls[1]["gex"])
        if len(walls) >= 2 and float(walls[1]["gex"]) > 0 else None
    )
    return share, lead


def _repair_expiry(exp, spot):
    if not isinstance(exp, dict):
        return exp
    calls_above = _directional(exp.get("strikes"), spot, "call")
    puts_below = _directional(exp.get("strikes"), spot, "put")
    exp["call_walls"] = calls_above
    exp["put_walls"] = puts_below
    exp["call_wall"] = calls_above[0]["strike"] if calls_above else None
    exp["put_wall"] = puts_below[0]["strike"] if puts_below else None
    for prefix in ("call", "put"):
        share, lead = _concentration(exp.get("strikes"), spot, prefix)
        exp[f"{prefix}_wall_share"] = share
        exp[f"{prefix}_wall_vs_second"] = lead
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
    atr_units = abs(float(level) - spot) / a if a > 0 else None
    tail = f"現値から{pct:+.1f}%" + (f"、{atr_units:.1f} ATR。" if atr_units is not None else "。")
    if label == "call":
        return ("現値より上にあるCallのOI×推定Gamma最大集中。上値抵抗候補だが、"
                "実ディーラーポジションではない。" + tail)
    return ("現値より下にあるPutのOI×推定Gamma最大集中。下値支持候補だが、"
            "維持を保証しない。" + tail)


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

    selected = rec.get("selected_expiry") or rec.get("nearest")
    first = per.get(selected) if selected else None
    if not isinstance(first, dict):
        return rec

    cw = first.get("call_wall")
    pw = first.get("put_wall")
    rec["call_wall"] = _dist(cw, spot, rec.get("atr14"))
    rec["put_wall"] = _dist(pw, spot, rec.get("atr14"))
    rec["gamma_flip"] = _dist(first.get("gamma_flip"), spot, rec.get("atr14"))
    rec["net_gex"] = first.get("net_gex", rec.get("net_gex"))
    rec["regime"] = base.regime(spot, first.get("gamma_flip"), rec.get("atr14"))
    rec["confidence"] = first.get("confidence", rec.get("confidence", "LOW"))
    rec["quality_reasons"] = first.get("quality_reasons", rec.get("quality_reasons", []))
    rec["oi_basis"] = "provider_open_interest_update_time_unavailable"
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

    net = rec.get("net_gex")
    explain = base.explain(
        spot, cw, pw, first.get("gamma_flip"), float(net or 0.0),
        rec.get("atr14"), rec.get("regime"),
    )
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

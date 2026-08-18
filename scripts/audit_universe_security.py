#!/usr/bin/env python3
"""Warning-only audit for non-common securities and duplicate share classes.

No symbol is removed by this script.  It is deliberately diagnostic first so
we can inspect false positives before promoting the rule into universe build.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

TV_SCAN = "https://scanner.tradingview.com/america/scan"
EXCHANGES = ["NYSE", "NASDAQ", "AMEX"]
MIN_MCAP = 200_000_000
MIN_PRICE = 1


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def _ticker(x):
    return str(x or "").strip().upper()


def _read_universe(path):
    out = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            t = _ticker(row.get("シンボル") or row.get("ticker") or row.get("symbol"))
            if t:
                out[t] = row
    return out


def _read_picks(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return {_ticker(x) for x in obj.get("picks") or [] if _ticker(x)}
    except Exception:
        return set()


def _tv_scan_with_typespecs():
    """Ask TradingView for structured security type metadata.

    `typespecs` is preferred over company-name text.  If the endpoint rejects
    the column, the audit records that fact and falls back to ticker patterns;
    it never turns a metadata outage into a removal.
    """
    columns = [
        "name", "description", "close", "volume", "market_cap_basic",
        "exchange", "type", "typespecs",
    ]
    flt = [
        {"left": "type", "operation": "equal", "right": "stock"},
        {"left": "exchange", "operation": "in_range", "right": EXCHANGES},
        {"left": "market_cap_basic", "operation": "egreater", "right": MIN_MCAP},
        {"left": "close", "operation": "egreater", "right": MIN_PRICE},
    ]
    out = {}
    for start in range(0, 20000, 1000):
        body = {
            "filter": flt,
            "columns": columns,
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [start, start + 1000],
        }
        req = urllib.request.Request(
            TV_SCAN,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=40) as fh:
            obj = json.loads(fh.read().decode("utf-8"))
        data = obj.get("data") or []
        for item in data:
            vals = item.get("d") or []
            if len(vals) < len(columns):
                continue
            rec = dict(zip(columns, vals))
            t = _ticker(rec.get("name"))
            if t:
                out[t] = rec
        if len(data) < 1000:
            break
    return out


def _spec_tokens(value):
    if isinstance(value, (list, tuple)):
        parts = value
    elif value is None:
        parts = []
    else:
        parts = [value]
    out = []
    for part in parts:
        for token in re.split(r"[^A-Za-z0-9]+", str(part).lower()):
            if token:
                out.append(token)
    return out


def _subtype_flag(typespecs):
    toks = set(_spec_tokens(typespecs))
    if not toks:
        return None
    # Conservative vocabulary.  `common`/`ordinary` is explicitly allowed.
    bad = {
        "preferred", "preference", "warrant", "warrants", "unit", "units",
        "right", "rights",
    }
    hit = sorted(toks & bad)
    return hit[0] if hit else None


def _ticker_pattern(t):
    """Conservative symbol patterns only; no free-text company-name matching."""
    t = _ticker(t)
    rules = [
        (r"/P[A-Z0-9]*$", "preferred_slash"),
        (r"\.PR[A-Z0-9]*$", "preferred_dot_pr"),
        (r"-P[A-Z0-9]*$", "preferred_dash"),
        (r"[./-]U$", "unit_suffix"),
        (r"[./-](WT|WTS|WS)$", "warrant_suffix"),
        (r"[./-](RT|RTS)$", "rights_suffix"),
    ]
    for pattern, reason in rules:
        if re.search(pattern, t):
            return reason
    # Deliberately do NOT use raw endswith('WS'): ordinary ticker WS exists.
    return None


def _description_hint(desc):
    """Last-resort hint only.  Never contributes to conservative removal."""
    text = str(desc or "").lower()
    patterns = [
        (r"\bpreferred\b|\bpfd\b", "preferred_text"),
        (r"\bwarrant(s)?\b", "warrant_text"),
        (r"\bright(s)?\b", "rights_text"),
        (r"\bunit(s)?\b", "unit_text"),
    ]
    for p, reason in patterns:
        if re.search(p, text):
            return reason
    return None


def _issuer_key(name):
    """Loose duplicate-class grouping only; never used for security-type removal."""
    x = str(name or "").upper()
    x = re.sub(r"\bCLASS\s+[A-Z0-9]+\b", "", x)
    x = re.sub(r"\bCOMMON\s+STOCK\b", "", x)
    x = re.sub(r"\bORDINARY\s+SHARES?\b", "", x)
    x = re.sub(r"[^A-Z0-9]+", " ", x)
    return " ".join(x.split())


def main():
    universe = _read_universe("universe.csv")
    picks = _read_picks("state.json")
    tv = {}
    tv_error = None
    try:
        tv = _tv_scan_with_typespecs()
    except Exception as exc:
        tv_error = type(exc).__name__
        print(f"::warning::universe security audit: TradingView typespecs unavailable ({tv_error}); ticker-pattern audit only")

    flagged = []
    likely_common = []
    for t, row in universe.items():
        tvrow = tv.get(t, {})
        subtype = _subtype_flag(tvrow.get("typespecs"))
        pattern = _ticker_pattern(t)
        text_hint = _description_hint(row.get("名称") or tvrow.get("description"))
        conservative = subtype or pattern
        rec = {
            "ticker": t,
            "name": str(row.get("名称") or tvrow.get("description") or ""),
            "typespecs": tvrow.get("typespecs"),
            "subtype_flag": subtype,
            "ticker_pattern_flag": pattern,
            "description_hint_only": text_hint,
            "would_remove_conservative": bool(conservative),
            "reason": conservative,
            "in_core12": t in picks,
            "price": _num(row.get("価格")),
            "volume": _num(row.get("出来高, 1日")),
        }
        if conservative or text_hint:
            flagged.append(rec)
        if not conservative:
            likely_common.append(rec)

    # Duplicate share classes are a separate problem from security type.  Group
    # likely-common names, then nominate the highest dollar-volume representative.
    groups = {}
    for rec in likely_common:
        key = _issuer_key(rec["name"])
        if not key:
            continue
        groups.setdefault(key, []).append(rec)
    dup_groups = []
    duplicate_losers = set()
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # Require explicit class wording or class-style ticker punctuation to
        # avoid grouping unrelated similarly named operating companies.
        explicit = [m for m in members if re.search(r"\bClass\s+[A-Z0-9]+\b", m["name"], re.I) or "." in m["ticker"]]
        if len(explicit) < 2:
            continue
        ranked = sorted(
            members,
            key=lambda m: ((m["price"] or 0.0) * (m["volume"] or 0.0), m["ticker"]),
            reverse=True,
        )
        keep = ranked[0]["ticker"]
        losers = [m["ticker"] for m in ranked[1:]]
        duplicate_losers.update(losers)
        dup_groups.append({
            "issuer_key": key,
            "keep_by_dollar_volume": keep,
            "drop_if_enabled": losers,
            "members": [
                {
                    "ticker": m["ticker"],
                    "name": m["name"],
                    "dollar_volume": (m["price"] or 0.0) * (m["volume"] or 0.0),
                }
                for m in ranked
            ],
        })

    conservative_remove = {r["ticker"] for r in flagged if r["would_remove_conservative"]}
    affected = sorted(picks & (conservative_remove | duplicate_losers))

    payload = {
        "version": 1,
        "mode": "warning_only_no_universe_or_selection_effect",
        "tradingview_typespecs_available": bool(tv),
        "tradingview_typespecs_error": tv_error,
        "universe_count": len(universe),
        "conservative_security_removal_count": len(conservative_remove),
        "description_hint_only_count": sum(1 for r in flagged if r["description_hint_only"] and not r["would_remove_conservative"]),
        "duplicate_group_count": len(dup_groups),
        "core12_affected_if_enabled": affected,
        "flagged_securities": sorted(flagged, key=lambda r: r["ticker"]),
        "duplicate_share_classes": sorted(dup_groups, key=lambda r: r["issuer_key"]),
        "notes": [
            "description hints are diagnostic only and never cause removal",
            "raw endswith('WS') is intentionally not used because ordinary ticker WS exists",
            "all removals remain disabled in this audit stage",
        ],
    }
    Path("universe_security_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    for rec in sorted(flagged, key=lambda r: r["ticker"]):
        if rec["would_remove_conservative"]:
            print(f"::warning::universe security candidate {rec['ticker']}: {rec['reason']} (not removed)")
    for grp in dup_groups:
        print(
            "::warning::duplicate share-class candidate: "
            f"keep={grp['keep_by_dollar_volume']} drop={','.join(grp['drop_if_enabled'])} (not changed)"
        )
    print(
        f"[universe-audit] universe={len(universe)} noncommon={len(conservative_remove)} "
        f"duplicate_groups={len(dup_groups)} core12_affected={affected}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

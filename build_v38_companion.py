#!/usr/bin/env python3
"""Build the isolated V38 audited companion state.

The legacy ``command-center.html`` is read-only input and is never rewritten.
The generated companion deliberately reports unavailable research inputs as
DATA REQUIRED rather than substituting an approximate production rule.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from v38_rules import market_mode


def _embedded_json(source: str, name: str):
    match = re.search(rf"window\.{re.escape(name)}=(.*?);</script>", source, re.S)
    if not match:
        raise ValueError(f"window.{name} was not found")
    return json.loads(match.group(1))


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def build_state(legacy_html: Path) -> dict:
    source = legacy_html.read_text(encoding="utf-8")
    calc = _embedded_json(source, "CALC")
    details = _embedded_json(source, "DET")

    valid50 = [row for row in details.values() if _finite(row.get("v50"))]
    coverage = len(valid50) / len(details) if details else 0.0
    coverage_ok = len(valid50) >= 30 and coverage >= 0.45
    breadth50 = (100 * sum(float(row["v50"]) > 0 for row in valid50) / len(valid50)
                 if valid50 else None)
    mode = market_mode(calc.get("color"), breadth50, coverage_ok)

    candidates = []
    for ticker, row in details.items():
        eligible = (
            _finite(row.get("px")) and float(row["px"]) >= 5
            and _finite(row.get("dvol")) and float(row["dvol"]) >= 10
            and bool(row.get("ma5020"))
            and _finite(row.get("v200")) and float(row["v200"]) > 0
            and _finite(row.get("rs189")) and float(row["rs189"]) >= 85
            and _finite(row.get("rs")) and float(row["rs"]) >= 85
            and row.get("sth") != "臨床段階・中小型バイオ"
        )
        if not eligible:
            continue
        candidates.append({
            "ticker": ticker,
            "price": row.get("px"),
            "rs189": row.get("rs189"),
            "rs63": row.get("rs"),
            "peer_theme": row.get("sth"),
            "peer_theme_score": None,
            "theme_rs63": None,
            "theme_acceleration": None,
            "theme_breadth21": None,
            "final_rank": (row.get("rs189") if mode.name == "SELECTIVE" else None),
            "eligibility": "ELIGIBLE",
            "entry_status": "NEXT_OPEN_WHEN_CAPACITY",
        })
    # Selective can be ranked exactly from the static snapshot.  Attack needs
    # historical peer returns and LOO acceleration, which legacy DET lacks.
    candidates.sort(key=lambda row: float(row["rs189"]), reverse=True)
    if mode.name == "SELECTIVE":
        for rank, row in enumerate(candidates, 1):
            row["final_rank"] = rank

    return {
        "schema": "v38-live-state-1",
        "source": str(legacy_html.name),
        "asof": calc.get("asof"),
        "market": {
            "nqsar": calc.get("color"),
            "breadth50": round(breadth50, 2) if breadth50 is not None else None,
            "breadth_valid": len(valid50),
            "breadth_universe": len(details),
            "coverage": round(coverage, 4),
            "coverage_ok": coverage_ok,
            "mode": mode.name,
            "reason": mode.reason,
            "new_entry_limit": mode.new_entry_limit,
            "force_exit_next_open": mode.force_exit_next_open,
        },
        "normal_tqqq": {"status": "CURRENT30", "target_pct": 30},
        "panic_tqqq": {
            "status": "DATA REQUIRED",
            "target_pct_when_active": 80,
            "required_route": "tqqq-panic-state.json",
            "fields": ["vix_close", "qqq_sma50_atr_deviation", "qqq_drawdown10",
                       "seed_age_sessions", "rsi4h", "prior_rsi4h", "mc57",
                       "active", "held_sessions"],
        },
        "ranking": {
            "mode": "RS189_ONLY" if mode.name == "SELECTIVE" else "LOO_THEME30_DATA_REQUIRED",
            "note": ("Selective: Stock RS189 only" if mode.name == "SELECTIVE"
                     else "Attack requires peer-only Theme RS63, 20d rank acceleration, and Breadth21 history"),
        },
        "candidates": candidates[:50],
        "panic_reset": {"status": "MONITOR / NOT LIVE", "separate_sleeve": True},
        "gross_limit_pct": 100,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", default="command-center.html")
    parser.add_argument("--out", default="v38-live-state.json")
    args = parser.parse_args()
    state = build_state(Path(args.legacy))
    Path(args.out).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {state['market']['mode']} / {len(state['candidates'])} candidates")


if __name__ == "__main__":
    main()

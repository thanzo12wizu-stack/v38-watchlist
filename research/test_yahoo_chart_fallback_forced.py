from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from build_v38_tqqq_live import download_yahoo_chart

SYMBOLS = ("QQQ", "TQQQ", "SPY", "AAPL", "MSFT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--start", default="2024-01-01")
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for symbol in SYMBOLS:
        rec = {
            "symbol": symbol,
            "primary_forced_failure": True,
            "fallback_attempted": True,
            "fallback_recovered": False,
            "rows": 0,
            "last_date": None,
            "error": None,
        }
        try:
            frame = download_yahoo_chart(symbol, start=args.start)
            if frame is None or frame.empty:
                raise RuntimeError("empty_frame")
            required = {"Open", "High", "Low", "Close", "Volume"}
            missing = sorted(required - set(frame.columns))
            if missing:
                raise RuntimeError(f"missing_columns:{missing}")
            valid = frame[list(required)].apply(pd.to_numeric, errors="coerce").dropna(how="all")
            if valid.empty:
                raise RuntimeError("no_numeric_ohlcv")
            rec["fallback_recovered"] = True
            rec["rows"] = int(len(frame))
            rec["last_date"] = str(pd.Timestamp(frame.index[-1]).date())
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}:{exc}"
        rows.append(rec)
        print(f"FORCED_CHART_FALLBACK {symbol} recovered={rec['fallback_recovered']} rows={rec['rows']} error={rec['error']}", flush=True)

    recovered = sum(bool(x["fallback_recovered"]) for x in rows)
    ratio = recovered / len(rows)
    report = {
        "test_id": "YAHOO_CHART_FORCED_FALLBACK_20260909",
        "method": "Primary path is deliberately treated as failed for all symbols; only build_v38_tqqq_live.download_yahoo_chart is used.",
        "symbols": list(SYMBOLS),
        "recovered": recovered,
        "requested": len(rows),
        "recovery_ratio": ratio,
        "pass_threshold": 0.80,
        "passed": ratio >= 0.80,
        "quality_threshold_changed": False,
        "strategy_changed": False,
        "production_changed": False,
        "results": rows,
    }
    (out / "forced_yahoo_chart_fallback.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FORCED_CHART_FALLBACK_SUMMARY recovered={recovered}/{len(rows)} ratio={ratio:.3f} passed={report['passed']}", flush=True)


if __name__ == "__main__":
    main()

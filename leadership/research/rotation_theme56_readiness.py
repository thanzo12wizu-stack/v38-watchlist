from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import rotation_live_snapshot as live


# This adapter registry deliberately lists only provider contracts already implemented
# and used by the current Rotation research. Unknown providers are DATA_REQUIRED,
# never approximated with dollar volume or synthetic flow.
FLOW_READY = {
    **{ticker: "SSGA" for ticker in live.SECTORS + ["XBI", "XME"]},
    "SOXX": "ISHARES",
    "IGV": "ISHARES",
    "ICLN": "ISHARES",
}

# Current exact holdings can be fetched by the existing live engine for its 15 ETFs.
HOLDINGS_READY = set(live.MATRIX_ETFS)


def load_config(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError("theme56 config must be a JSON object")
    themes = obj.get("themes")
    if not isinstance(themes, list) or len(themes) != 56:
        raise RuntimeError(f"expected exactly 56 themes, got {0 if not isinstance(themes, list) else len(themes)}")
    tickers = [str(x.get("ticker") or "").upper().strip() for x in themes if isinstance(x, dict)]
    if len(tickers) != 56 or len(set(tickers)) != 56 or any(not x for x in tickers):
        raise RuntimeError("theme56 config contains duplicate or missing tickers")
    return obj


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit implementation readiness for the 56 ETF sector-temperature-map Rotation universe")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_readiness"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    rows: list[dict[str, Any]] = []
    for theme in cfg["themes"]:
        ticker = str(theme.get("ticker") or "").upper().strip()
        label = str(theme.get("label") or ticker)
        flow_provider = FLOW_READY.get(ticker)
        rows.append({
            "label": label,
            "ticker": ticker,
            "price_engine": "READY",
            "rs63_rs189": "READY",
            "exact_holdings": "READY" if ticker in HOLDINGS_READY else "ADAPTER_REQUIRED",
            "internals": "READY" if ticker in HOLDINGS_READY else "WAITING_FOR_EXACT_HOLDINGS",
            "exact_flow": "READY" if flow_provider else "ADAPTER_REQUIRED",
            "flow_provider": flow_provider,
            "state_v2": "READY_TO_RESEARCH" if ticker in HOLDINGS_READY and flow_provider else "DATA_REQUIRED",
        })

    df = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output / "theme56_readiness.csv", index=False)

    complete = df[(df["internals"] == "READY") & (df["exact_flow"] == "READY")]
    report = {
        "schema": 1,
        "research_only": True,
        "universe_count": int(len(df)),
        "price_ready": int((df["price_engine"] == "READY").sum()),
        "internals_ready": int((df["internals"] == "READY").sum()),
        "exact_flow_ready": int((df["exact_flow"] == "READY").sum()),
        "full_stack_ready": int(len(complete)),
        "full_stack_tickers": complete["ticker"].tolist(),
        "holdings_adapter_required": df.loc[df["exact_holdings"] != "READY", "ticker"].tolist(),
        "flow_adapter_required": df.loc[df["exact_flow"] != "READY", "ticker"].tolist(),
        "guardrails": [
            "Price/RS can be computed for all 56 ETFs once market price data is available.",
            "Internals are not computed without exact ETF holdings membership.",
            "Dollar Volume, OBV, CMF, or price-volume proxies are never labeled Fund Flow.",
            "Exact Flow is enabled only when an official NAV + shares-outstanding provider contract exists.",
            "Current 15-ETF state thresholds are not promoted to the 56-ETF universe without separate validation.",
            "No Command Center production files are modified by this research script.",
        ],
    }
    (args.output / "theme56_readiness.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

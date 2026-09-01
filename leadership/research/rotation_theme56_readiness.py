from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


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


def load_provider_qa(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker:
            out[ticker] = row
    return out


def load_price_status(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = obj.get("rows") if isinstance(obj, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker:
            out[ticker] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit implementation readiness for the 56 ETF sector-temperature-map Rotation universe")
    ap.add_argument("--config", type=Path, default=Path("leadership/research/rotation_theme56_config.json"))
    ap.add_argument("--provider-qa", type=Path, default=Path("leadership/research/rotation_theme56_provider_qa/theme56_provider_qa.csv"))
    ap.add_argument("--price-json", type=Path, default=Path("leadership/research/rotation_theme56_live/theme56_price.json"))
    ap.add_argument("--output", type=Path, default=Path("leadership/research/rotation_theme56_readiness"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    provider = load_provider_qa(args.provider_qa)
    price = load_price_status(args.price_json)

    rows: list[dict[str, Any]] = []
    for theme in cfg["themes"]:
        ticker = str(theme.get("ticker") or "").upper().strip()
        label = str(theme.get("label") or ticker)
        p = provider.get(ticker, {})
        px = price.get(ticker, {})
        holdings_ok = str(p.get("holdings_status") or "").upper() == "PASS"
        flow_ok = str(p.get("flow_status") or "").upper() == "PASS"
        price_ok = str(px.get("quality") or "").upper() == "MARKET_PRICE_SERIES"
        provider_name = None if pd.isna(p.get("provider")) else p.get("provider")
        rows.append({
            "label": label,
            "ticker": ticker,
            "price": "READY" if price_ok else "DATA_REQUIRED",
            "rs63_rs189": "READY" if price_ok else "DATA_REQUIRED",
            "exact_holdings": "READY" if holdings_ok else "ADAPTER_REQUIRED",
            "internals": "READY_TO_BUILD" if holdings_ok else "WAITING_FOR_EXACT_HOLDINGS",
            "exact_flow": "READY" if flow_ok else "ADAPTER_REQUIRED",
            "flow_provider": provider_name if flow_ok else None,
            "full_stack_data": "READY_TO_BUILD" if price_ok and holdings_ok and flow_ok else "DATA_REQUIRED",
            "state_v2": "VALIDATION_REQUIRED" if price_ok and holdings_ok and flow_ok else "DATA_REQUIRED",
        })

    df = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output / "theme56_readiness.csv", index=False)

    complete = df[df["full_stack_data"] == "READY_TO_BUILD"]
    report = {
        "schema": 2,
        "research_only": True,
        "universe_count": int(len(df)),
        "price_ready": int((df["price"] == "READY").sum()),
        "internals_membership_ready": int((df["exact_holdings"] == "READY").sum()),
        "exact_flow_ready": int((df["exact_flow"] == "READY").sum()),
        "full_stack_data_ready": int(len(complete)),
        "full_stack_tickers": complete["ticker"].tolist(),
        "price_data_required": df.loc[df["price"] != "READY", "ticker"].tolist(),
        "holdings_adapter_required": df.loc[df["exact_holdings"] != "READY", "ticker"].tolist(),
        "flow_adapter_required": df.loc[df["exact_flow"] != "READY", "ticker"].tolist(),
        "provider_qa_loaded": bool(provider),
        "price_snapshot_loaded": bool(price),
        "guardrails": [
            "Price/RS readiness is based on the actual Theme56 price snapshot, not a hardcoded assumption.",
            "Internals are not computed without exact ETF holdings membership.",
            "Dollar Volume, OBV, CMF, or price-volume proxies are never labeled Fund Flow.",
            "Exact Flow is enabled only after an official NAV + shares-outstanding provider QA passes.",
            "Current 15-ETF state thresholds are not promoted to the 56-ETF universe without separate validation.",
            "No Command Center production files are modified by this research script.",
        ],
    }
    (args.output / "theme56_readiness.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

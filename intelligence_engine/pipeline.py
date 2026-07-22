from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import EngineConfig
from .prices import compute_price_features, download_price_map, load_price_map
from .scoring import score_universe
from .sec import load_companyfacts
from .utils import atomic_write_json, finite_or_none


def _col(df: pd.DataFrame, names: tuple[str, ...]):
    mapping = {str(c).strip().lower(): c for c in df.columns}
    return next((mapping[n.lower()] for n in names if n.lower() in mapping), None)


def load_universe(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ticker_col = _col(df, ("ticker", "symbol", "シンボル", "ティッカー"))
    if ticker_col is None:
        raise ValueError("universe.csv requires ticker/symbol/シンボル")
    df = df.rename(columns={ticker_col: "ticker"})
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    aliases = {
        "sector": ("sector", "sector_name", "セクター"),
        "industry": ("industry", "industry_name", "業種", "産業"),
        "market_cap": ("market_cap", "marketcap", "market cap", "時価総額"),
    }
    for target, names in aliases.items():
        source = _col(df, names)
        if source is not None and source != target:
            df = df.rename(columns={source: target})
        if target not in df:
            df[target] = None
    df = df[df["ticker"].ne("") & df["ticker"].ne("NAN")]
    return df.drop_duplicates("ticker").set_index("ticker", drop=False)


def _load_or_download_prices(config: EngineConfig, tickers: list[str]):
    if config.price_cache.exists():
        return load_price_map(config.price_cache), {"source": "pickle", "path": str(config.price_cache)}
    requested = sorted(set(tickers) | {"QQQ"})
    return download_price_map(requested)


def build(config: EngineConfig) -> dict:
    asof = datetime.now(timezone.utc).date().isoformat()
    universe = load_universe(config.universe_csv)
    prices, price_diagnostics = _load_or_download_prices(config, universe["ticker"].tolist())
    qqq = prices.get("QQQ")
    benchmark = qqq["close"] if qqq is not None and "close" in qqq else None
    if benchmark is None:
        raise RuntimeError("QQQ benchmark history is required for relative-strength scoring")

    rows = []
    for ticker, meta in universe.iterrows():
        frame = prices.get(ticker)
        if frame is None:
            continue
        price_features = compute_price_features(frame, benchmark)
        if not price_features:
            continue
        sec_path = config.sec_cache_dir / f"{ticker}.json"
        fundamentals = asdict(load_companyfacts(sec_path)) if sec_path.exists() else {}
        rows.append(
            {
                "ticker": ticker,
                "sector": meta.get("sector"),
                "industry": meta.get("industry"),
                "market_cap": finite_or_none(pd.to_numeric(meta.get("market_cap"), errors="coerce")),
                **price_features,
                **fundamentals,
            }
        )

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise RuntimeError("no stocks built")
    eligible = raw[
        (pd.to_numeric(raw["price"], errors="coerce") >= config.min_price)
        & (pd.to_numeric(raw["dollar_volume_20d"], errors="coerce") >= config.min_dollar_volume)
    ].copy()
    scored = score_universe(eligible).sort_values(
        ["score_candidate", "score_confidence", "ticker"], ascending=[False, False, True]
    )
    candidate = scored.head(config.candidate_limit)
    detail = scored.head(config.detail_limit)
    stocks_dir = config.output_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "ticker", "sector", "industry", "price", "market_cap", "adr_pct", "dollar_volume_20d",
        "score_candidate", "score_emerging", "score_compounder", "score_breakout", "score_turnaround",
        "score_momentum", "score_fundamental", "score_improvement", "score_quality", "score_confidence",
        "latest_filing_date", "accounting_standard",
    ]
    fields += [f"pct_rs_raw_{w}" for w in config.rs_windows if f"pct_rs_raw_{w}" in candidate]
    records = candidate[[c for c in fields if c in candidate]].where(pd.notna(candidate), None).to_dict("records")
    for _, row in detail.iterrows():
        payload = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        payload.update(
            {
                "asof": asof,
                "schema_version": "1.0",
                "narrative": None,
                "institutional": None,
                "estimate_revision": None,
            }
        )
        atomic_write_json(stocks_dir / f"{row['ticker']}.json", payload)

    manifest = {
        "schema_version": "1.0",
        "asof": asof,
        "universe_count": len(universe),
        "price_covered_count": len(raw),
        "price_diagnostics": price_diagnostics,
        "eligible_count": len(eligible),
        "candidate_count": len(candidate),
        "detail_count": len(detail),
        "score_policy": "missing-aware weighted percentiles",
    }
    atomic_write_json(config.output_dir / "index.json", {"manifest": manifest, "stocks": records})
    atomic_write_json(config.output_dir / "manifest.json", manifest)
    atomic_write_json(config.history_dir / f"{asof}.json", {"manifest": manifest, "stocks": records})
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--sec-dir", default="data/sec_companyfacts")
    parser.add_argument("--output", default="data/intelligence")
    parser.add_argument("--candidate-limit", type=int, default=300)
    parser.add_argument("--detail-limit", type=int, default=100)
    args = parser.parse_args()
    cfg = EngineConfig(
        Path(args.universe), Path(args.prices), Path(args.output), Path(args.sec_dir),
        Path(args.output) / "history", args.candidate_limit, args.detail_limit,
    )
    print(json.dumps(build(cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

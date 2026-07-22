from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import EngineConfig
from .entry import ENTRY_POLICY_VERSION, add_entry_intelligence, build_entry_candidates
from .leadership import LEADER_POLICY_VERSION, add_leader_scores
from .market import MARKET_POLICY_VERSION, apply_market_gate, build_market_state
from .prices import compute_price_features, load_price_map
from .providers import get_price_provider
from .score_policy import SCORE_POLICY_VERSION
from .scoring import score_universe
from .sec import load_companyfacts
from .sector_rotation import SECTOR_ROTATION_POLICY_VERSION, build_sector_rotation
from .story import STORY_POLICY_VERSION, add_story_intelligence, apply_story_context, build_story_records
from .theme import THEME_POLICY_VERSION, apply_theme_context, attach_theme_context, build_theme_intelligence
from .utils import _json_safe, atomic_write_json, finite_or_none


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
    provider = get_price_provider()
    if config.price_cache.exists():
        return load_price_map(config.price_cache), {
            "source": "pickle",
            "path": str(config.price_cache),
            "provider": provider.name,
        }
    requested = sorted(set(tickers) | {"QQQ"})
    return provider.download(requested)


def _clean(value):
    """Normalize nested pandas/numpy values before strict JSON serialization."""
    return _json_safe(value)


def _index_record(row: pd.Series, rs_windows: tuple[int, ...]) -> dict:
    score_names = ("candidate", "emerging", "compounder", "breakout", "turnaround", "momentum", "fundamental", "improvement", "quality", "leader", "entry", "entry_technical", "entry_risk", "theme", "story")
    feature_names = [
        "price", "market_cap", "adr_pct", "dollar_volume_20d", "volume_ratio_20d", "distance_52w_high_pct",
        "leader_rank_pct", "entry_rank_pct", "setup", "pivot_20d", "distance_pivot_pct", "stop_ema21_low", "stop_sma10",
        "stop_risk_pct", "reward_risk_raw", "extension_atr", "hard_block", "theme", "theme_ja", "theme_phase",
        "themes", "themes_ja", "theme_phases", "story_phase", "story_rank_pct", "story_evidence_count",
    ]
    feature_names += [f"pct_rs_raw_{window}" for window in rs_windows]
    return {
        "ticker": str(row["ticker"]),
        "sector": _clean(row.get("sector")),
        "industry": _clean(row.get("industry")),
        "features": {name: _clean(row.get(name)) for name in feature_names if name in row.index},
        "scores": {name: _clean(row.get(f"score_{name}")) for name in score_names if f"score_{name}" in row.index},
        "confidence": _clean(float(row.get("score_confidence")) * 100 if pd.notna(row.get("score_confidence")) else None),
        "leader_confidence": _clean(float(row.get("score_leader_confidence")) * 100 if pd.notna(row.get("score_leader_confidence")) else None),
        "entry_confidence": _clean(float(row.get("score_entry_confidence")) * 100 if pd.notna(row.get("score_entry_confidence")) else None),
        "story_confidence": _clean(float(row.get("score_story_confidence")) * 100 if pd.notna(row.get("score_story_confidence")) else None),
        "fundamentals": {"latest_filing_date": _clean(row.get("latest_filing_date")), "accounting_standard": _clean(row.get("accounting_standard"))},
    }


def build(config: EngineConfig) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    asof = generated_at[:10]
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
        rows.append({"ticker": ticker, "sector": meta.get("sector"), "industry": meta.get("industry"), "market_cap": finite_or_none(pd.to_numeric(meta.get("market_cap"), errors="coerce")), **price_features, **fundamentals})

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise RuntimeError("no stocks built")
    eligible = raw[(pd.to_numeric(raw["price"], errors="coerce") >= config.min_price) & (pd.to_numeric(raw["dollar_volume_20d"], errors="coerce") >= config.min_dollar_volume)].copy()
    if eligible.empty:
        raise RuntimeError("no eligible stocks after price and liquidity filters")
    scored = add_story_intelligence(add_entry_intelligence(add_leader_scores(score_universe(eligible)))).sort_values(
        ["score_candidate", "score_confidence", "ticker"], ascending=[False, False, True]
    )
    story_records = build_story_records(scored)
    theme_intelligence = build_theme_intelligence(scored)
    scored = attach_theme_context(scored, theme_intelligence)
    sector_rotation = build_sector_rotation(scored)
    market_state = build_market_state(scored, qqq, sector_rotation)
    entry_candidates = apply_story_context(apply_theme_context(apply_market_gate(build_entry_candidates(scored), market_state), scored), scored)
    candidate = scored.head(config.candidate_limit)
    detail = scored.head(config.detail_limit)
    stocks_dir = config.output_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    records = [_index_record(row, config.rs_windows) for _, row in candidate.iterrows()]

    for _, row in detail.iterrows():
        payload = {k: _clean(v) for k, v in row.to_dict().items()}
        payload.update({"generated_at": generated_at, "schema_version": "1.0", "score_policy_version": SCORE_POLICY_VERSION, "leader_policy_version": LEADER_POLICY_VERSION, "entry_policy_version": ENTRY_POLICY_VERSION, "market_policy_version": MARKET_POLICY_VERSION, "theme_policy_version": THEME_POLICY_VERSION, "story_policy_version": STORY_POLICY_VERSION, "narrative": None, "institutional": None, "estimate_revision": None})
        atomic_write_json(stocks_dir / f"{row['ticker']}.json", payload)

    requested_count = int(price_diagnostics.get("requested_count", price_diagnostics.get("requested", len(universe) + 1)))
    downloaded_count = int(price_diagnostics.get("downloaded_count", price_diagnostics.get("received", len(prices))))
    coverage_ratio = downloaded_count / requested_count if requested_count else 0.0
    provider_name = str(price_diagnostics.get("provider") or price_diagnostics.get("source") or "unknown")
    manifest = {
        "schema_version": "1.0", "score_policy_version": SCORE_POLICY_VERSION, "leader_policy_version": LEADER_POLICY_VERSION,
        "sector_rotation_policy_version": SECTOR_ROTATION_POLICY_VERSION, "entry_policy_version": ENTRY_POLICY_VERSION,
        "market_policy_version": MARKET_POLICY_VERSION, "theme_policy_version": THEME_POLICY_VERSION, "story_policy_version": STORY_POLICY_VERSION,
        "generated_at": generated_at, "asof": asof, "universe_count": len(universe), "price_covered_count": len(raw),
        "price_download_coverage_ratio": coverage_ratio, "price_diagnostics": price_diagnostics, "price_provider": provider_name,
        "eligible_count": len(eligible), "candidate_count": len(candidate), "detail_count": len(detail), "sector_count": len(sector_rotation), "theme_count": len(theme_intelligence),
        "story_count": len(story_records), "entry_candidate_count": len(entry_candidates), "market_regime": market_state.get("regime"),
        "market_entry_gate": market_state.get("entry_gate"), "score_policy": "missing-aware weighted percentiles",
    }
    index = {
        "schema_version": "1.0", "score_policy_version": SCORE_POLICY_VERSION, "leader_policy_version": LEADER_POLICY_VERSION,
        "sector_rotation_policy_version": SECTOR_ROTATION_POLICY_VERSION, "entry_policy_version": ENTRY_POLICY_VERSION,
        "market_policy_version": MARKET_POLICY_VERSION, "theme_policy_version": THEME_POLICY_VERSION, "story_policy_version": STORY_POLICY_VERSION,
        "generated_at": generated_at, "manifest": manifest, "stocks": records, "sector_rotation": sector_rotation,
        "theme_intelligence": theme_intelligence, "story_intelligence": story_records, "market_state": market_state, "entry_candidates": entry_candidates,
    }
    atomic_write_json(config.output_dir / "index.json", index)
    atomic_write_json(config.output_dir / "sector_rotation.json", {"generated_at": generated_at, "sectors": sector_rotation})
    atomic_write_json(config.output_dir / "theme_intelligence.json", {"generated_at": generated_at, "themes": theme_intelligence})
    atomic_write_json(config.output_dir / "story_intelligence.json", {"generated_at": generated_at, "stories": story_records})
    atomic_write_json(config.output_dir / "market_state.json", {"generated_at": generated_at, **market_state})
    atomic_write_json(config.output_dir / "entry_candidates.json", {"generated_at": generated_at, "market_state": {"regime": market_state.get("regime"), "entry_gate": market_state.get("entry_gate")}, "candidates": entry_candidates})
    atomic_write_json(config.output_dir / "manifest.json", manifest)
    atomic_write_json(config.history_dir / f"{asof}.json", index)
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
    cfg = EngineConfig(Path(args.universe), Path(args.prices), Path(args.output), Path(args.sec_dir), Path(args.output) / "history", args.candidate_limit, args.detail_limit)
    print(json.dumps(build(cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

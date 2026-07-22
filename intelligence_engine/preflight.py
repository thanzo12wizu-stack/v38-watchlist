from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .pipeline import load_universe
from .prices import compute_price_features, load_price_map
from .scoring import score_universe
from .story import add_story_intelligence


def run(universe_path: Path, prices_path: Path) -> dict:
    universe = load_universe(universe_path)
    prices = load_price_map(prices_path)
    qqq = prices.get("QQQ")
    if qqq is None or "close" not in qqq:
        raise RuntimeError("QQQ missing during preflight")
    benchmark = qqq["close"]
    rows = []
    for ticker, meta in universe.head(25).iterrows():
        frame = prices.get(ticker)
        if frame is None:
            continue
        features = compute_price_features(frame, benchmark)
        if features:
            rows.append({"ticker": ticker, "sector": meta.get("sector"), "industry": meta.get("industry"), **features})
    if not rows:
        raise RuntimeError("no usable symbols during preflight")
    base = pd.DataFrame(rows)
    scored = score_universe(base)
    story = add_story_intelligence(scored)
    required = {"score_candidate", "score_story", "story_phase"}
    missing = sorted(required - set(story.columns))
    if missing:
        raise RuntimeError(f"preflight output missing columns: {missing}")
    return {"status": "OK", "symbols": len(story), "columns": len(story.columns)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="universe.csv")
    p.add_argument("--prices", default="prices.pkl")
    args = p.parse_args()
    print(json.dumps(run(Path(args.universe), Path(args.prices)), indent=2))


if __name__ == "__main__":
    main()

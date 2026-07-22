from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .dashboard_bridge import inject_panel
from .expectancy import EXPECTANCY_POLICY_VERSION, build_expectancy, calibrate_candidates
from .external_data import EXTERNAL_DATA_POLICY_VERSION, apply_external_context, build_external_records, load_external_layer
from .morning_brief import build_morning_brief
from .portfolio import build_portfolio_doctor, load_positions
from .prices import load_price_map
from .utils import atomic_write_json


def _scored_from_index(index: dict) -> pd.DataFrame:
    rows = []
    for stock in index.get("stocks", []):
        row = {"ticker": stock.get("ticker"), "sector": stock.get("sector"), "industry": stock.get("industry")}
        row.update(stock.get("features") or {})
        row.update({f"score_{k}": v for k, v in (stock.get("scores") or {}).items()})
        rows.append(row)
    return pd.DataFrame(rows)


def _discover_dashboard(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    preferred = [Path("command_center.html"), Path("dashboard.html"), Path("index.html")]
    for path in preferred:
        if path.exists(): return path
    candidates = [p for p in Path(".").glob("*.html") if p.is_file()]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None


def run(root: Path, prices_path: Path, portfolio_path: Path, dashboard_path: Path | None = None, external_root: Path | None = None) -> dict:
    index_path = root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    scored = _scored_from_index(index)
    prices = load_price_map(prices_path) if prices_path.exists() else {}

    expectancy = build_expectancy(prices)
    candidates = calibrate_candidates(index.get("entry_candidates") or [], expectancy)
    external_layer = load_external_layer(external_root or Path("data/external"))
    external_records = build_external_records(scored.get("ticker", pd.Series(dtype=str)).dropna().astype(str).tolist(), external_layer)
    candidates = apply_external_context(candidates, external_records)
    index["entry_candidates"] = candidates
    index["expectancy_rankings"] = expectancy
    index["external_data"] = external_records

    positions = load_positions(portfolio_path)
    doctor = build_portfolio_doctor(positions, scored, prices, index.get("market_state") or {})
    brief = build_morning_brief(index.get("market_state") or {}, index.get("sector_rotation") or [], index.get("theme_intelligence") or [], candidates, doctor)
    index["portfolio_doctor"] = doctor
    index["morning_brief"] = brief
    manifest=index.setdefault("manifest", {})
    manifest["portfolio_position_count"] = doctor.get("position_count", 0)
    manifest["dashboard_bridge_applied"] = False
    manifest["expectancy_policy_version"] = EXPECTANCY_POLICY_VERSION
    manifest["expectancy_sample_count"] = expectancy.get("sample_count", 0)
    manifest["external_data_policy_version"] = EXTERNAL_DATA_POLICY_VERSION
    manifest["external_data_covered_count"] = sum(any(r.get("coverage",{}).values()) for r in external_records)

    atomic_write_json(root / "expectancy_rankings.json", expectancy)
    atomic_write_json(root / "external_data.json", {"policy_version":EXTERNAL_DATA_POLICY_VERSION,"records":external_records})
    atomic_write_json(root / "entry_candidates.json", {"generated_at":index.get("generated_at"),"market_state":{"regime":(index.get("market_state") or {}).get("regime"),"entry_gate":(index.get("market_state") or {}).get("entry_gate")},"candidates":candidates})
    atomic_write_json(root / "portfolio_doctor.json", doctor)
    atomic_write_json(root / "morning_brief.json", brief)
    target = _discover_dashboard(dashboard_path)
    if target is not None:
        manifest["dashboard_bridge_applied"] = inject_panel(target, index)
        manifest["dashboard_target"] = str(target)
    atomic_write_json(index_path, index)
    if (root / "manifest.json").exists(): atomic_write_json(root / "manifest.json", manifest)
    return {"portfolio": doctor.get("status"), "brief": True, "expectancy":expectancy.get("status"),"external_covered":manifest["external_data_covered_count"],"dashboard": manifest.get("dashboard_bridge_applied", False), "dashboard_target": manifest.get("dashboard_target")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/intelligence")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--portfolio", default="portfolio.csv")
    parser.add_argument("--dashboard", default=None)
    parser.add_argument("--external-root", default="data/external")
    args = parser.parse_args()
    result = run(Path(args.root), Path(args.prices), Path(args.portfolio), Path(args.dashboard) if args.dashboard else None, Path(args.external_root))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

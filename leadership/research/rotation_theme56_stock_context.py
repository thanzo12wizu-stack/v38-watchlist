from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import rotation_theme_stock_context as base

LEADER_ROLES = {"PIONEER", "LEADER"}
LEADER_PHASES = {"EMERGING", "LEADING"}


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return obj


def normalize_holdings(path: Path | None, universe: set[str]) -> pd.DataFrame:
    cols = ["sector_etf", "symbol", "weight_pct", "name", "source_url"]
    if path is None or not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path)
    if not {"sector_etf", "symbol"}.issubset(df.columns):
        raise RuntimeError(f"holdings columns missing in {path}")
    out = df.copy()
    out["sector_etf"] = out["sector_etf"].astype(str).str.upper().str.strip()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out = out[out["sector_etf"].isin(universe)]
    out = out[~out["symbol"].isin({"", "NAN", "-", "--"})]
    for col in ("weight_pct", "name", "source_url"):
        if col not in out.columns:
            out[col] = None
    return out[cols].drop_duplicates(["sector_etf", "symbol"], keep="first")


def clean(v: Any) -> Any:
    if pd.isna(v):
        return None
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


def main() -> None:
    ap = argparse.ArgumentParser(description="Join Theme56 ready current ETF memberships to the existing full Leadership model")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--leadership", type=Path, required=True)
    ap.add_argument("--fullstack", type=Path, required=True)
    ap.add_argument("--holdings", type=Path, required=True)
    ap.add_argument("--holdings-expansion", type=Path, required=True)
    ap.add_argument("--holdings-fallback", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    cfg = load_json(args.config)
    themes = cfg.get("themes") if isinstance(cfg.get("themes"), list) else []
    if len(themes) != 56:
        raise RuntimeError("Theme56 config must contain 56 themes")
    ordered = [(str(x.get("ticker") or "").upper().strip(), str(x.get("label") or x.get("ticker") or "")) for x in themes]
    universe = {t for t, _ in ordered}
    if len(universe) != 56:
        raise RuntimeError("Theme56 ticker set is not unique")

    model = load_json(args.leadership)
    stock_index, group_rows = base.build_stock_index(model)
    fs = load_json(args.fullstack)
    fs_rows = fs.get("rows") if isinstance(fs.get("rows"), list) else []
    fs_by = {str(x.get("ticker") or "").upper(): x for x in fs_rows if isinstance(x, dict)}

    holdings = pd.concat([
        normalize_holdings(args.holdings, universe),
        normalize_holdings(args.holdings_expansion, universe),
        normalize_holdings(args.holdings_fallback, universe),
    ], ignore_index=True).drop_duplicates(["sector_etf", "symbol"], keep="first")

    contexts: list[dict[str, Any]] = []
    all_intersections: list[dict[str, Any]] = []
    for ticker, label in ordered:
        h = holdings[holdings["sector_etf"] == ticker].copy()
        intersections: list[dict[str, Any]] = []
        for holding_rank, hr in enumerate(h.to_dict("records"), start=1):
            sym = str(hr.get("symbol") or "").upper()
            lead = stock_index.get(sym)
            if not lead:
                continue
            rec = {
                "etf": ticker,
                "holding_rank": holding_rank,
                "holding_weight_pct": base.safe_num(hr.get("weight_pct")),
                **lead,
            }
            intersections.append(rec)
            all_intersections.append(rec)
        intersections.sort(key=lambda x: (int(x.get("group_rank") or 9999), int(x.get("stock_rank_within_group") or 9999), int(x.get("holding_rank") or 9999)))
        leaders = [x for x in intersections if str(x.get("role")) in LEADER_ROLES and str(x.get("group_phase")) in LEADER_PHASES]
        rotation = fs_by.get(ticker, {})
        holdings_quality = str(rotation.get("holdings_quality") or "DATA_REQUIRED")
        contexts.append({
            "etf": ticker,
            "label": label,
            "rotation": {
                "state": rotation.get("state"),
                "price_score": rotation.get("price_score_56"),
                "internal_score": rotation.get("internal_score_56"),
                "internal_delta20": rotation.get("internal_delta20_56"),
                "flow_20d_pct_aum": rotation.get("flow_20d_pct_aum"),
                "flow_provider": rotation.get("flow_provider"),
                "flow_quality": rotation.get("flow_quality"),
                "quality": rotation.get("quality"),
            },
            "membership_quality": holdings_quality if len(h) else "DATA_REQUIRED",
            "membership_rows": int(len(h)),
            "leadership_full_intersections": int(len(intersections)),
            "leadership_full_intersection_pct": (100.0 * len(intersections) / len(h)) if len(h) else None,
            "existing_emerging_or_leading_leaders_in_full_intersection": [{k: clean(v) for k, v in row.items()} for row in leaders[:30]],
            "existing_emerging_or_leading_leaders_in_top15_intersection": [{k: clean(v) for k, v in row.items()} for row in leaders[:30]],
            "guardrail": "Existing Leadership ordering only. No Rotation stock score, new stock ranking, entry signal, V38 gate, or exit is created.",
        })

    coverage = model.get("coverage") if isinstance(model.get("coverage"), dict) else {}
    with_membership = sum(1 for x in contexts if x["membership_rows"] > 0)
    issuer_exact = sum(1 for x in contexts if x["membership_rows"] > 0 and x["membership_quality"] == "ISSUER_EXACT_CURRENT")
    validated_fallback = sum(1 for x in contexts if x["membership_rows"] > 0 and x["membership_quality"] != "ISSUER_EXACT_CURRENT")
    with_leaders = sum(1 for x in contexts if x["existing_emerging_or_leading_leaders_in_full_intersection"])
    report = {
        "schema": 2,
        "research_only": True,
        "context_scope": "THEME56_READY_CURRENT_MEMBERSHIP_X_FULL_LEADERSHIP_EXPORT",
        "leadership_generated_at": model.get("generated_at"),
        "leadership_market": model.get("market"),
        "leadership_coverage": coverage,
        "theme_count": 56,
        "membership_ready_theme_count": with_membership,
        "issuer_exact_membership_theme_count": issuer_exact,
        "validated_fallback_membership_theme_count": validated_fallback,
        "themes_with_leaders": with_leaders,
        "formal_exception": "DRAM: post-launch history/membership data is not included in the completed 55-theme stack.",
        "industry_context": contexts,
        "guardrails": [
            "The existing Leadership model is reused unchanged; only its temporary full-stock export is joined to ETF memberships.",
            "Issuer-exact current ETF memberships are preferred; separately validated current fallback memberships are used only where the issuer path is unavailable.",
            "Validated fallback membership is never relabeled issuer-exact.",
            "Current memberships are not historical PIT holdings.",
            "Rotation does not create a second stock ranking or V38 entry/exit signal.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "rotation_theme56_stock_context.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(all_intersections).to_csv(args.output / "rotation_theme56_stock_context.csv", index=False)
    pd.DataFrame(group_rows).to_csv(args.output / "leadership_groups.csv", index=False)
    print(json.dumps({"themes": 56, "membership_ready_themes": with_membership, "issuer_exact": issuer_exact, "validated_fallback": validated_fallback, "themes_with_leaders": with_leaders, "intersections": len(all_intersections)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

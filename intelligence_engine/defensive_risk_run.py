from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .ab_stage_data import attach_group_features, attach_individual_stage, build_market_stage
from .defensive_risk import Holding, RiskPolicy, allocate_candidates, candidate_from_mapping, portfolio_heat
from .prices import load_price_map
from .research_engine import add_research_scores
from .research_storage import load_dataset


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _policy_payload(policy: RiskPolicy) -> dict[str, Any]:
    payload = asdict(policy)
    payload["market_heat_limits"] = {key.value: value for key, value in policy.market_heat_limits.items()}
    payload["market_multipliers"] = {key.value: value for key, value in policy.market_multipliers.items()}
    return payload


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _normalize_dimensions(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ("ticker", "sector", "industry", "theme", "subtheme"):
        if column not in out:
            out[column] = "UNKNOWN"
        out[column] = out[column].astype("string").fillna("UNKNOWN").replace({"": "UNKNOWN"})
    out["ticker"] = out["ticker"].str.upper()
    return out


def _recent_signal_panel(signals: pd.DataFrame, sessions: int = 35) -> pd.DataFrame:
    work = _normalize_dimensions(signals)
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work = work.dropna(subset=["date", "ticker"])
    dates = sorted(work["date"].dropna().unique())
    if not dates:
        return work.iloc[0:0].copy()
    return work[work["date"].isin(set(dates[-max(1, sessions):]))].copy()


def _load_portfolio(path: Path | None) -> tuple[list[Holding], dict[str, Any]]:
    if path is None or not path.exists():
        return [], {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    holdings: list[Holding] = []
    for item in payload.get("holdings", []):
        stop = float(item.get("stop_fraction", item.get("stop_pct", 0)) or 0)
        if stop > 1:
            stop /= 100.0
        holdings.append(Holding(
            ticker=str(item.get("ticker") or "").upper(),
            sector=str(item.get("sector") or "UNKNOWN"),
            theme=str(item.get("theme") or item.get("industry") or "UNKNOWN"),
            market_value_jpy=float(item.get("market_value_jpy") or 0),
            stop_fraction=max(0.0, stop),
            event_risk=bool(item.get("event_risk")),
        ))
    return holdings, payload


def _candidate_rows(latest: pd.DataFrame, available_cash: float | None) -> list[Any]:
    work = latest.copy()
    if "a_rank" in work:
        work["alpha_rank"] = pd.to_numeric(work["a_rank"], errors="coerce")
    elif "alpha_rank" not in work:
        work["alpha_rank"] = np.nan
    sort_columns = [column for column in ("base_composite", "leadership_quality", "entry_quality") if column in work]
    if sort_columns:
        work = work.sort_values(sort_columns + ["ticker"], ascending=[False] * len(sort_columns) + [True])
    work = work.drop_duplicates("ticker", keep="first")
    candidates = []
    for _, row in work.iterrows():
        payload = row.to_dict()
        # US equity close is USD; never divide a JPY budget by it. Share counts stay blank
        # unless an upstream portfolio adapter supplies price_jpy explicitly.
        payload["price"] = row.get("price_jpy")
        payload["available_cash_jpy"] = available_cash
        candidates.append(candidate_from_mapping(payload))
    return candidates


def _yen(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"¥{number:,.0f}" if math.isfinite(number) else "—"


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%" if math.isfinite(number) else "—"


def _report(*, as_of: pd.Timestamp, policy: RiskPolicy, holdings: list[Holding], recommendations: list[Any], alpha_available: bool) -> str:
    heat = portfolio_heat(holdings, policy.account_equity_jpy)
    counts: dict[str, int] = {}
    for result in recommendations:
        counts[result.decision.value] = counts.get(result.decision.value, 0) + 1
    lines = [
        "# Defensive Risk Engine",
        "",
        f"- 基準日: {as_of.date().isoformat()}",
        f"- 口座資産: {_yen(policy.account_equity_jpy)}",
        f"- 1トレード許容損失: {_pct(policy.risk_per_trade)} / {_yen(policy.account_equity_jpy * policy.risk_per_trade)}",
        f"- 建玉上限: {_pct(policy.max_position_fraction)}",
        f"- 最大ストップ幅: {_pct(policy.max_stop_fraction)}",
        f"- 最低損益比: {policy.min_reward_risk:.1f}R",
        f"- 現在のPortfolio Heat: {_pct(heat.total_fraction)}",
        f"- 現在のGross Exposure: {_pct(heat.gross_fraction)}",
        f"- Aランキング入力: {'利用' if alpha_available else '未提供（セクターRS・リーダー度で順位付け）'}",
        "- 判定構造: ハードゲート → 辞書式順位 → ステージ別縮小 → Heat制約 → 2分割",
        "",
        "## 判定件数",
        "",
        f"- 通常: {counts.get('NORMAL', 0)}",
        f"- 1回目のみ: {counts.get('FIRST_TRANCHE', 0)}",
        f"- 監視: {counts.get('WATCH', 0)}",
        f"- 見送り: {counts.get('REJECT', 0)}",
        "",
        "## 発注候補",
        "",
        "|順位|Ticker|判定|市場|個別Stage|全体建玉|1回目|2回目|予定損失|追加後Heat|見送り・警告|",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for index, result in enumerate(recommendations[:40], start=1):
        reasons = ", ".join((*result.hard_blocks, *result.warnings)) or "—"
        lines.append(
            f"|{index}|{result.ticker}|{result.decision.value}|{result.market_state.value}|{result.individual_stage}|"
            f"{_yen(result.recommended_position_jpy)}|{_yen(result.first_tranche_jpy)}|{_yen(result.second_tranche_jpy)}|"
            f"{_yen(result.planned_loss_full_jpy)}|{_pct(result.portfolio_heat_after_full)}|{reasons}|"
        )
    lines.extend([
        "",
        "## 固定ルール",
        "",
        "- 赤市場、Stage 4、ストップ6%超、3R未満、決算±3営業日、3ATR超は他条件で相殺しない。",
        "- 1日の新規は最大2銘柄。上位候補の全建玉分のHeatを予約してから次候補を判定する。",
        "- 2回目はブレイク定着・2nd Pivot・支持転換の確認後だけ。含み損への追加は禁止。",
        "- 3日進まなければ警戒、5日で+1R未達なら半減または撤退、10日で原則撤退。",
        "- この出力は発注補助であり、自動売買は行わない。",
        "",
    ])
    return "\n".join(lines)


def run(*, research_root: Path, prices_path: Path, output_dir: Path, account_equity_jpy: float, portfolio_path: Path | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_price_map(prices_path)
    signals = load_dataset(research_root, "signals")
    if signals.empty:
        raise RuntimeError("signals dataset is empty")
    recent = _recent_signal_panel(signals, sessions=35)
    staged = attach_individual_stage(recent, prices)
    if staged.empty:
        raise RuntimeError("stage enrichment produced no rows")
    enriched = attach_group_features(_normalize_dimensions(staged), build_market_stage(prices))
    enriched = enriched.loc[:, ~enriched.columns.duplicated()].copy()
    required_scores = {"base_composite", "leadership_quality", "entry_quality"}
    scored = enriched.copy() if required_scores.issubset(enriched.columns) else add_research_scores(enriched)
    scored = scored.loc[:, ~scored.columns.duplicated()].copy()
    as_of = pd.to_datetime(scored["date"], errors="coerce").max().normalize()
    latest = scored[pd.to_datetime(scored["date"], errors="coerce").dt.normalize() == as_of].copy()
    holdings, portfolio_payload = _load_portfolio(portfolio_path)
    equity = float(portfolio_payload.get("account_equity_jpy") or account_equity_jpy)
    available_cash = portfolio_payload.get("available_cash_jpy")
    available_cash = float(available_cash) if available_cash is not None else None
    policy = RiskPolicy(account_equity_jpy=equity)
    candidates = _candidate_rows(latest, available_cash)
    recommendations = allocate_candidates(candidates, holdings, policy=policy)
    decision_order = {"NORMAL": 0, "FIRST_TRANCHE": 0, "WATCH": 1, "REJECT": 2}
    recommendations = sorted(recommendations, key=lambda item: decision_order[item.decision.value])
    rows = [item.to_dict() for item in recommendations]
    pd.DataFrame(rows).to_csv(output_dir / "defensive_risk_recommendations.csv", index=False)
    alpha_available = any(candidate.alpha_rank is not None for candidate in candidates)
    (output_dir / "REPORT_JA.md").write_text(_report(
        as_of=as_of,
        policy=policy,
        holdings=holdings,
        recommendations=recommendations,
        alpha_available=alpha_available,
    ), encoding="utf-8")
    payload = {
        "as_of": as_of,
        "policy": _policy_payload(policy),
        "portfolio": {
            "holdings": [asdict(item) for item in holdings],
            "heat": asdict(portfolio_heat(holdings, equity)),
        },
        "alpha_rank_available": alpha_available,
        "candidate_count": len(candidates),
        "recommendations": rows,
    }
    _write_json(output_dir / "defensive_risk_recommendations.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", default="data/intelligence/research")
    parser.add_argument("--prices", default="prices.pkl")
    parser.add_argument("--output", default="artifacts/defensive-risk")
    parser.add_argument("--account-equity-jpy", type=float, default=8_000_000)
    parser.add_argument("--portfolio")
    args = parser.parse_args()
    result = run(
        research_root=Path(args.research_root),
        prices_path=Path(args.prices),
        output_dir=Path(args.output),
        account_equity_jpy=args.account_equity_jpy,
        portfolio_path=Path(args.portfolio) if args.portfolio else None,
    )
    print(json.dumps({"status": "PASS", "as_of": result["as_of"].isoformat(), "candidates": result["candidate_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

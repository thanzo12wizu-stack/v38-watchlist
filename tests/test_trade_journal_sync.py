import json
from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal_sync import sync_command_center


def _write_index(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-07-28T06:00:00+09:00",
        "market_state": {"regime": "GREEN", "vix": 18.5, "breadth": 0.61, "distribution_days": 3},
        "portfolio_doctor": {
            "gross_exposure": 0.64,
            "positions": [
                {
                    "ticker": "SNDK", "weight": 0.08, "price": 203.0, "cost_basis": 186.0,
                    "gain_pct": 9.14, "held_days": 12, "risk_contribution_pct": 0.42,
                    "sector": "Technology", "theme": "Memory", "stop": 194.0,
                    "entry_stage": 2, "strategy": "swing",
                }
            ],
        },
        "entry_candidates": [
            {"ticker": "MU", "rank": 1, "setup": "21EMA Pullback", "action": "BUYABLE", "sector": "Technology", "theme": "Memory"}
        ],
    }
    (root / "index.json").write_text(json.dumps(payload), encoding="utf-8")


def test_sync_command_center_writes_live_inputs(tmp_path: Path) -> None:
    root = tmp_path / "intelligence"
    output = tmp_path / "journal"
    _write_index(root)
    status = sync_command_center(intelligence_root=root, output_dir=output, account_equity_jpy=10_000_000)
    assert status["status"] == "CONNECTED"
    assert status["account_equity_source"] == "EXPLICIT_ACCOUNT_EQUITY"
    holdings = pd.read_csv(output / "holdings.csv")
    assert holdings.loc[0, "ticker"] == "SNDK"
    assert holdings.loc[0, "market_value_jpy"] == 800_000
    assert holdings.loc[0, "planned_loss_jpy"] == 42_000
    candidates = pd.read_csv(output / "candidates.csv")
    assert candidates.loc[0, "ticker"] == "MU"
    assert bool(candidates.loc[0, "selected"])
    context = pd.read_csv(output / "market_context.csv")
    assert context.loc[0, "nq_color"] == "GREEN"
    equity = pd.read_csv(output / "equity.csv")
    assert equity.loc[0, "equity_jpy"] == 10_000_000
    assert equity.loc[0, "cash_jpy"] == 3_600_000


def test_sync_is_partial_without_account_equity(tmp_path: Path) -> None:
    root = tmp_path / "intelligence"
    output = tmp_path / "journal"
    _write_index(root)
    status = sync_command_center(intelligence_root=root, output_dir=output)
    assert status["status"] == "PARTIAL"
    assert status["account_equity_source"] == "ACCOUNT_EQUITY_MISSING"
    assert not (output / "holdings.csv").exists()
    assert (output / "candidates.csv").exists()
    assert status["trade_history_source"] == "NOT_CONNECTED"

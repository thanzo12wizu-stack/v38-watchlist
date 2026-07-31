from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from intelligence_engine.trade_journal_data import build_equity_curve
from intelligence_engine.trade_journal_ingest import executions_to_trades, ingest_bundle


def _executions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "execution_id": "e1", "position_id": "p1", "ticker": "AAA", "side": "LONG",
                "action": "BUY", "executed_at": "2026-07-01 10:00", "price": 100,
                "quantity": 5, "fx_to_jpy": 150, "fees_jpy": 100, "stop_price": 95,
                "setup": "2nd Pivot", "nq_color": "GREEN",
            },
            {
                "execution_id": "e2", "position_id": "p1", "ticker": "AAA", "side": "LONG",
                "action": "BUY", "executed_at": "2026-07-02 10:00", "price": 110,
                "quantity": 5, "fx_to_jpy": 150, "fees_jpy": 100, "stop_price": 95,
                "setup": "2nd Pivot", "nq_color": "GREEN",
            },
            {
                "execution_id": "e3", "position_id": "p1", "ticker": "AAA", "side": "LONG",
                "action": "SELL", "executed_at": "2026-07-10 10:00", "price": 120,
                "quantity": 3, "fx_to_jpy": 150, "fees_jpy": 100, "taxes_jpy": 50,
                "exit_reason": "1R partial",
            },
            {
                "execution_id": "e4", "position_id": "p1", "ticker": "AAA", "side": "LONG",
                "action": "SELL", "executed_at": "2026-07-15 10:00", "price": 130,
                "quantity": 7, "fx_to_jpy": 150, "fees_jpy": 100, "taxes_jpy": 50,
                "exit_reason": "Trail",
            },
            {
                "execution_id": "e5", "position_id": "p2", "ticker": "BBB", "side": "LONG",
                "action": "BUY", "executed_at": "2026-07-20 10:00", "price": 50,
                "quantity": 10, "fx_to_jpy": 150, "fees_jpy": 50, "stop_price": 47,
            },
            {
                "execution_id": "e6", "position_id": "p2", "ticker": "BBB", "side": "LONG",
                "action": "SELL", "executed_at": "2026-07-22 10:00", "price": 55,
                "quantity": 4, "fx_to_jpy": 150, "fees_jpy": 50,
            },
        ]
    )


def test_execution_ledger_aggregates_entry_and_partial_exit_tranches() -> None:
    trades, status = executions_to_trades(_executions())

    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["trade_id"] == "EXEC-p1"
    assert trade["entry_price"] == 105
    assert trade["exit_tranches"] == 2
    assert bool(trade["partial_exit"])
    # FIFO: 3*(120-100) + 2*(130-100) + 5*(130-110), converted at 150.
    assert trade["gross_pnl_jpy"] == 33_000
    assert trade["net_pnl_jpy"] == 32_500
    assert status["closed_positions"] == 1
    assert status["open_positions"] == 1
    assert status["partial_exit_positions"] == 2
    assert status["open_partial_exit_positions"] == 1


def test_execution_side_is_propagated_from_entry_to_exit_rows() -> None:
    executions = _executions()
    executions.loc[executions["action"] == "SELL", "side"] = ""

    trades, status = executions_to_trades(executions)

    assert len(trades) == 1
    assert trades.iloc[0]["side"] == "LONG"
    assert status["open_positions"] == 1


def test_exit_inherits_entry_point_value_when_omitted() -> None:
    executions = pd.DataFrame(
        [
            {
                "execution_id": "future-entry",
                "position_id": "future-1",
                "ticker": "NQ",
                "side": "LONG",
                "action": "BUY",
                "executed_at": "2026-07-01 10:00",
                "price": 20_000,
                "quantity": 1,
                "point_value": 20,
                "fx_to_jpy": 1,
            },
            {
                "execution_id": "future-exit",
                "position_id": "future-1",
                "ticker": "NQ",
                "side": "",
                "action": "SELL",
                "executed_at": "2026-07-02 10:00",
                "price": 20_010,
                "quantity": 1,
            },
        ]
    )

    trades, _ = executions_to_trades(executions)

    assert trades.iloc[0]["gross_pnl_jpy"] == 200
    assert trades.iloc[0]["point_value"] == 20


def test_repository_account_history_handles_mixed_whitespace_and_private_override(tmp_path: Path) -> None:
    account_history = tmp_path / "equity.csv"
    account_history.write_text(
        "date\tequity\tus_pct\n"
        "2026-07-01\t1000000\t20.0\n"
        "2026-07-02 1010000 21.0\n",
        encoding="utf-8",
    )
    import_dir = tmp_path / "incoming"
    state_dir = tmp_path / "state"
    import_dir.mkdir()
    pd.DataFrame(
        [{"date": "2026-07-02", "equity_jpy": 1_020_000, "cash_jpy": 200_000}]
    ).to_csv(import_dir / "equity.csv", index=False)

    report = ingest_bundle(import_dir, state_dir, account_history)

    equity = pd.read_csv(state_dir / "equity.csv")
    assert report["imported_rows"]["account_history"] == 2
    assert len(equity) == 2
    assert equity.loc[equity["date"] == "2026-07-02", "equity_jpy"].iloc[0] == 1_020_000
    assert equity.loc[equity["date"] == "2026-07-02", "equity_source"].iloc[0] == "PRIVATE_IMPORT"


def test_ingestion_rejects_holding_without_ticker(tmp_path: Path) -> None:
    import_dir = tmp_path / "incoming"
    state_dir = tmp_path / "state"
    import_dir.mkdir()
    pd.DataFrame(
        [{"ticker": "", "quantity": 1, "entry_price": 100, "current_price": 110}]
    ).to_csv(import_dir / "holdings.csv", index=False)

    with pytest.raises(ValueError, match="required ticker"):
        ingest_bundle(import_dir, state_dir)


def test_ingestion_is_idempotent_and_cash_flows_do_not_double_count(tmp_path: Path) -> None:
    import_dir = tmp_path / "incoming"
    state_dir = tmp_path / "state"
    import_dir.mkdir()
    _executions().to_csv(import_dir / "executions.csv", index=False)
    pd.DataFrame(
        [
            {"date": "2026-07-01", "equity_jpy": 1_000_000, "cash_jpy": 1_000_000},
            {"date": "2026-07-15", "equity_jpy": 1_120_000, "cash_jpy": 400_000},
        ]
    ).to_csv(import_dir / "equity.csv", index=False)
    pd.DataFrame(
        [
            {
                "flow_id": "f1", "date": "2026-07-15", "type": "DEPOSIT",
                "amount_jpy": 100_000, "notes": "追加資金",
            }
        ]
    ).to_csv(import_dir / "cash_flows.csv", index=False)

    first = ingest_bundle(import_dir, state_dir)
    second = ingest_bundle(import_dir, state_dir)

    assert first["executions"]["closed_positions"] == 1
    assert second["state_rows"]["executions.csv"] == 6
    trades = pd.read_csv(state_dir / "trades.csv")
    assert len(trades) == 1
    equity = pd.read_csv(state_dir / "equity.csv")
    assert equity.loc[equity["date"] == "2026-07-15", "deposits_jpy"].iloc[0] == 100_000


def test_equity_returns_remove_cash_flows_before_compounding() -> None:
    equity = pd.DataFrame(
        [
            {"date": "2026-01-01", "equity_jpy": 1_000, "deposits_jpy": 0, "withdrawals_jpy": 0},
            {"date": "2026-01-02", "equity_jpy": 1_200, "deposits_jpy": 100, "withdrawals_jpy": 0},
            {"date": "2026-01-03", "equity_jpy": 1_320, "deposits_jpy": 0, "withdrawals_jpy": 0},
        ]
    )

    curve = build_equity_curve(equity, pd.DataFrame(), 0)

    assert curve.loc[1, "daily_return"] == pytest.approx(0.1)
    assert curve.loc[2, "daily_return"] == pytest.approx(0.1)
    assert round(curve.loc[2, "adjusted_equity_jpy"], 8) == 1_210


def test_cash_flow_without_same_day_snapshot_moves_to_next_equity_date(tmp_path: Path) -> None:
    import_dir = tmp_path / "incoming"
    state_dir = tmp_path / "state"
    import_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-07-03", "equity_jpy": 1_000_000},
            {"date": "2026-07-06", "equity_jpy": 1_110_000},
        ]
    ).to_csv(import_dir / "equity.csv", index=False)
    pd.DataFrame(
        [
            {
                "flow_id": "weekend-deposit",
                "date": "2026-07-04",
                "type": "DEPOSIT",
                "amount_jpy": 100_000,
            }
        ]
    ).to_csv(import_dir / "cash_flows.csv", index=False)

    report = ingest_bundle(import_dir, state_dir)

    equity = pd.read_csv(state_dir / "equity.csv")
    assert equity.loc[equity["date"] == "2026-07-06", "deposits_jpy"].iloc[0] == 100_000
    assert "2026-07-04->2026-07-06" in report["warnings"][0]
    curve = build_equity_curve(equity, pd.DataFrame(), 0)
    assert curve.loc[1, "daily_return"] == pytest.approx(0.01)

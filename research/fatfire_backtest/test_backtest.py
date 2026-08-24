import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fatfire_backtest", HERE / "backtest.py")
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_tax_model_has_fifteen_contributions_for_2011_2025():
    idx = pd.bdate_range("2011-01-03", "2025-12-31")
    returns = pd.Series(0.0, index=idx)
    result = mod.simulate_tax(returns)
    assert result.total_contributions == 15 * mod.ANNUAL_CONTRIBUTION
    assert abs(result.equity.iloc[-1] - (mod.START_CAPITAL + 15 * mod.ANNUAL_CONTRIBUTION)) < 1e-6
    assert result.total_tax == 0


def test_positive_gain_is_taxed_and_loss_can_carry():
    idx = pd.to_datetime(["2011-12-30", "2012-12-31", "2013-12-31"])
    returns = pd.Series([-0.10, 0.20, 0.20], index=idx)
    result = mod.simulate_tax(returns, start_capital=10_000_000, annual_contribution=0)
    assert result.yearly.loc[0, "tax_paid"] == 0
    assert result.yearly.loc[1, "loss_offset_used"] > 0
    assert result.total_tax >= 0


def test_strategy_weight_budgets_never_exceed_one():
    idx = pd.date_range("2020-01-01", periods=4, freq="B")
    state = pd.DataFrame(
        {
            "regime": ["BLUE", "GREEN", "YELLOW", "RED"],
            "recommended_exposure": [1.0, .75, .35, 0.0],
            "top3_sectors": ["XLK|SMH|XLI"] * 4,
            "reentry_stage": [3, 3, 3, 0],
        },
        index=idx,
    )
    for name in ["V38_regime_QQQ", "V38_regime_TQQQ", "V38_beta_rotation", "V38_beta_rotation_FTD"]:
        w = mod._weights_for_strategy(name, state)
        assert (w.sum(axis=1) <= 1.0000001).all()
        assert (w >= 0).all().all()

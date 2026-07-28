from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal_demo15 import build_demo15


def test_mobile_layout_and_fifteen_position_stress_case(tmp_path: Path) -> None:
    output = tmp_path / "out"
    build_demo15(7_300_000, output)
    html = (output / "index.html").read_text(encoding="utf-8")
    holdings = pd.read_csv(output / "holdings_normalized.csv")

    assert len(holdings) == 15
    assert holdings["ticker"].nunique() == 15
    assert "table.mobile-cards" in html
    assert "cell.dataset.label" in html
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in html
    assert "overflow-x:hidden" in html
    assert "min-width:760px" not in html
    assert html.count('class="tab" href="#') == 7
    assert '<button class="tab"' not in html
    assert output.joinpath("daily_card.png").stat().st_size > 0
    assert output.joinpath("portfolio_card.png").stat().st_size > 0

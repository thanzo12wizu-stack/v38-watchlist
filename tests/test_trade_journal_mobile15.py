from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal_demo15 import build_demo15


def test_mobile_almanac_and_fifteen_position_stress_case(tmp_path: Path) -> None:
    output = tmp_path / "out"
    build_demo15(7_300_000, output)
    html = (output / "index.html").read_text(encoding="utf-8")
    holdings = pd.read_csv(output / "holdings_normalized.csv")

    assert len(holdings) == 15
    assert holdings["ticker"].nunique() == 15
    assert html.count('<a class="tab" href="#') == 7
    assert '<button class="tab"' not in html
    assert "grid-template-columns:repeat(12,minmax(0,1fr))" in html
    assert ".tab:nth-child(-n+4){grid-column:span 3}" in html
    assert "overflow-x:hidden" in html
    assert "<details class=\"holding-card\"" in html
    assert 'id="holdings-more"' in html
    assert "残り${remaining}銘柄を表示" in html
    assert "Stop距離" in html
    assert "Stop逸脱" in html
    assert "相関調整Heat" in html
    assert 'id="copy-holdings"' in html
    assert 'id="sizing-calculator"' in html
    assert "@media(max-width:390px)" in html
    assert "ポートフォリオADR%" in html
    assert "さらに20件表示" in html
    assert "Setup × NQ" in html
    assert "入出金調整後の日次口座評価額" in html
    assert output.joinpath("daily_card.png").stat().st_size > 0
    assert output.joinpath("portfolio_card.png").stat().st_size > 0

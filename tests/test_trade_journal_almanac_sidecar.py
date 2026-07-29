from pathlib import Path

import pandas as pd

from intelligence_engine.trade_journal_almanac_demo15 import build_demo15
from intelligence_engine.trade_journal_almanac_run import run


def _assert_almanac(output: Path) -> None:
    html = (output / "index.html").read_text(encoding="utf-8")
    holdings = pd.read_csv(output / "holdings_normalized.csv")

    assert len(holdings) == 15
    assert holdings["ticker"].nunique() == 15
    assert "Trade Journal Almanac" in html
    assert "--bg:#f5f2ea" in html
    assert html.count('<a class="tab" href="#') == 7
    assert '<button class="tab"' not in html
    assert "grid-template-columns:repeat(12,minmax(0,1fr))" in html
    assert "overflow-x:hidden" in html
    assert '<details class="holding-card"' in html
    assert 'id="holdings-more"' in html
    assert "相関調整Heat" in html
    assert "入出金調整後の日次口座評価額" in html
    assert output.joinpath("daily_card.png").stat().st_size > 0
    assert output.joinpath("portfolio_card.png").stat().st_size > 0


def test_almanac_sidecar_does_not_touch_existing_output(tmp_path: Path) -> None:
    existing = tmp_path / "trade-journal"
    existing.mkdir()
    sentinel = existing / "index.html"
    sentinel.write_text("EXISTING-JOURNAL-MUST-NOT-CHANGE", encoding="utf-8")

    output = tmp_path / "trade-journal-almanac"
    summary = build_demo15(7_300_000, output)

    assert summary["variant"] == "almanac-sidecar"
    assert summary["output_dir"] == str(output)
    assert sentinel.read_text(encoding="utf-8") == "EXISTING-JOURNAL-MUST-NOT-CHANGE"
    _assert_almanac(output)


def test_almanac_runner_uses_only_explicit_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "standalone-almanac"
    summary = run(
        input_dir=tmp_path / "input",
        output_dir=output,
        starting_equity_jpy=7_300_000,
        demo=True,
    )

    assert summary["variant"] == "almanac-sidecar"
    assert output.joinpath("index.html").exists()
    assert not tmp_path.joinpath("artifacts", "trade-journal").exists()

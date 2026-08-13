import json
import sys
from pathlib import Path

import pandas as pd

from kaview.demo import build_demo15
from kaview.almanac_enhanced import _decision
import kaview.run as almanac_runner
from kaview.run import _log_safe_summary, run
from kaview.journal import JournalInput, analyse_journal


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
    assert "Drawdown Episodes" in html
    assert "候補選択の検証" in html
    assert "相関上位ペア" in html
    assert "ポートフォリオADR%" in html
    assert 'id="copy-holdings"' in html
    assert 'id="sizing-calculator"' in html
    assert 'id="sz-entry1"' in html
    assert 'id="sz-entry2"' in html
    assert "21EMA Low" in html
    assert "10MA" in html
    assert "+25%部分利確" in html
    assert "セリクラ待ち" in html
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
    saved = json.loads(output.joinpath("summary.json").read_text(encoding="utf-8"))
    assert saved["data_status"] == summary["data_status"]
    assert saved["readiness"] == summary["readiness"]


def test_live_runner_refuses_to_present_default_equity_as_real_data(tmp_path: Path) -> None:
    output = tmp_path / "live"
    summary = run(
        input_dir=tmp_path / "empty-input",
        output_dir=output,
        starting_equity_jpy=7_300_000,
        require_live_data=True,
    )

    html = (output / "index.html").read_text(encoding="utf-8")
    assert summary["data_status"] == "SETUP_REQUIRED"
    assert "実データ接続待ち" in html
    assert "7,300,000" not in html
    assert not (output / "daily_card.png").exists()


def test_live_runner_treats_empty_holdings_csv_as_zero_positions(tmp_path: Path) -> None:
    input_dir = tmp_path / "live-input"
    input_dir.mkdir()
    (input_dir / "holdings.csv").write_text("", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "date": pd.Timestamp.now(tz="Asia/Tokyo").date().isoformat(),
                "equity_jpy": 7_300_000,
            }
        ]
    ).to_csv(input_dir / "equity.csv", index=False)

    output = tmp_path / "live"
    summary = run(
        input_dir=input_dir,
        output_dir=output,
        starting_equity_jpy=0,
        require_live_data=True,
    )

    assert summary["data_status"] == "PARTIAL"
    assert summary["readiness"]["connected_rows"]["holdings"] == 0
    assert output.joinpath("index.html").exists()
    assert output.joinpath("summary.json").exists()


def test_actions_log_summary_excludes_private_financial_data() -> None:
    private_result = {
        "variant": "almanac-sidecar",
        "data_status": "PARTIAL",
        "account_equity_jpy": 7_654_321,
        "cash_jpy": 7_654_321,
        "kpis": {"net_pnl_jpy": 123_456},
        "holdings": [{"ticker": "PRIVATE"}],
        "readiness": {
            "account_equity_jpy": 7_654_321,
            "connected_rows": {"trades": 3, "holdings": 1},
            "equity_as_of": "2026-08-03",
            "equity_age_days": 1,
            "stale_equity": False,
        },
        "output_dir": "/tmp/trade-journal-almanac",
    }

    safe = _log_safe_summary(private_result)
    serialized = json.dumps(safe)

    assert safe["status"] == "PASS"
    assert safe["data_status"] == "PARTIAL"
    assert safe["equity_as_of"] == "2026-08-03"
    assert "7654321" not in serialized
    assert "123456" not in serialized
    assert "PRIVATE" not in serialized
    assert "connected_rows" not in safe


def test_cli_prints_only_log_safe_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    private_result = {
        "variant": "almanac-sidecar",
        "data_status": "PARTIAL",
        "account_equity_jpy": 8_765_432,
        "kpis": {"net_pnl_jpy": 234_567},
        "holdings": [{"ticker": "PRIVATE"}],
        "readiness": {
            "account_equity_jpy": 8_765_432,
            "connected_rows": {"trades": 3, "holdings": 1},
            "equity_as_of": "2026-08-03",
            "equity_age_days": 1,
            "stale_equity": False,
        },
        "output_dir": str(tmp_path),
    }
    monkeypatch.setattr(almanac_runner, "run", lambda **_: private_result)
    monkeypatch.setattr(sys, "argv", ["trade-journal-almanac", "--output", str(tmp_path)])

    almanac_runner.main()

    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload)
    assert payload["status"] == "PASS"
    assert payload["equity_as_of"] == "2026-08-03"
    assert "8765432" not in serialized
    assert "234567" not in serialized
    assert "PRIVATE" not in serialized


def test_stale_equity_blocks_open_decision() -> None:
    report = analyse_journal(
        JournalInput(
            equity=pd.DataFrame(
                [
                    {"date": "2026-07-01", "equity_jpy": 1_000},
                    {"date": "2026-07-02", "equity_jpy": 1_010},
                ]
            ),
            candidates=pd.DataFrame([{"date": "2026-07-20", "ticker": "AAA"}]),
            account_equity_jpy=1_010,
            nq_color="GREEN",
        )
    )

    tone, title, reason = _decision(report, breached=0, near=0, events=0)

    assert tone == "bad"
    assert title == "資産データ要更新"
    assert "18日経過" in reason

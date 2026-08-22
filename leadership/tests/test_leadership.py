import csv
import json
import tempfile
import unittest
from pathlib import Path

from leadership.build_leadership import build_model, entry_status, extract_symbol_metrics, market_permission


class LeadershipCommandTests(unittest.TestCase):
    def test_market_permission(self):
        self.assertEqual(market_permission({"mri": 72, "gate": "Green"})["status"], "GO")
        self.assertEqual(market_permission({"mri": 52, "gate": "Yellow"})["status"], "SELECTIVE")
        self.assertEqual(market_permission({"mri": 30, "gate": "Red"})["status"], "STOP")

    def test_metric_map_adapter(self):
        snap = {
            "rs63": {"AAA": 95, "BBB": 88, "CCC": 82},
            "rs21": {"AAA": 99, "BBB": 91, "CCC": 80},
            "ema21": {"AAA": 99, "BBB": 49, "CCC": 20},
        }
        metrics, diag = extract_symbol_metrics(snap)
        self.assertEqual(float(metrics["AAA"]["rs63"]), 95)
        self.assertEqual(float(metrics["BBB"]["rs21"]), 91)
        self.assertGreaterEqual(diag["symbols_extracted"], 3)

    def test_entry_never_invents_signal_without_inputs(self):
        status = entry_status({"strength": 99, "price": 100})
        self.assertEqual(status["status"], "NO_DATA")

    def test_entry_avoids_below_50sma(self):
        status = entry_status({"strength": 95, "price": 90, "sma50": 100, "ema21": 92})
        self.assertEqual(status["status"], "AVOID")

    def test_build_model_reads_live_metrics_but_existing_group_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leadership").mkdir()
            (root / "state.json").write_text(
                json.dumps({"date": "2026-08-21", "gate": "Green", "mri": 72.6}), encoding="utf-8"
            )
            symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
            sector_snapshot = {"s2i": {s: "Group A" if s < "DDD" else "Group B" for s in symbols}}
            (root / "sector_snapshot.json").write_text(json.dumps(sector_snapshot), encoding="utf-8")
            live = {
                "asof": "2026-08-21",
                "rs189": {"AAA": 90, "BBB": 86, "CCC": 81, "DDD": 70, "EEE": 66, "FFF": 60},
                "rs63": {"AAA": 96, "BBB": 90, "CCC": 84, "DDD": 72, "EEE": 68, "FFF": 63},
                "rs21": {"AAA": 99, "BBB": 95, "CCC": 88, "DDD": 75, "EEE": 70, "FFF": 62},
                "price": {"AAA": 101, "BBB": 52, "CCC": 31, "DDD": 40, "EEE": 28, "FFF": 22},
                "ema21": {"AAA": 100, "BBB": 51, "CCC": 30.5, "DDD": 39, "EEE": 27.5, "FFF": 21.5},
                "sma50": {"AAA": 95, "BBB": 48, "CCC": 28, "DDD": 36, "EEE": 25, "FFF": 20},
                "atr14": {s: 2 for s in symbols},
                "vwap63": {"AAA": 100, "BBB": 51, "CCC": 30, "DDD": 39, "EEE": 27, "FFF": 21},
                "pivot": {"AAA": 100, "BBB": 51, "CCC": 30, "DDD": 39, "EEE": 27, "FFF": 21},
                "pct_from_52w_high": {s: -5 for s in symbols},
                "volume_ratio": {s: 1.1 for s in symbols},
            }
            (root / "leadership" / "market_snapshot.json").write_text(json.dumps(live), encoding="utf-8")
            (root / "industry_map.json").write_text(
                json.dumps({"map": {s: ["Tech", "Test"] for s in symbols}}), encoding="utf-8"
            )
            (root / "earnings.json").write_text(
                json.dumps({"AAA": {"eps": {"trend": "ACCEL_PERSISTENT", "accel_streak": 3, "latest_yoy": 80}}}),
                encoding="utf-8",
            )
            with (root / "universe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["シンボル", "名称", "価格", "価格変動 %, 1日", "出来高, 1日", "時価総額", "セクター", "業種", "取引所", "証券種別"])
                for i, s in enumerate(symbols):
                    writer.writerow([s, s, 100 - i, i, 1000000, 1000000000, "Tech", "Test", "NASDAQ", "stock"])

            model, diagnostics = build_model(root)
            self.assertEqual(model["market"]["status"], "GO")
            self.assertEqual(model["coverage"]["metric_source"], "leadership/market_snapshot.json")
            self.assertEqual(model["groups"][0]["name"], "Group A")
            leaders = model["groups"][0]["stocks"]
            self.assertEqual(leaders[0]["symbol"], "AAA")
            self.assertIn(leaders[0]["role"], {"PIONEER", "LEADER"})
            self.assertEqual(leaders[0]["entry"]["status"], "ENTRY")
            self.assertGreaterEqual(diagnostics["coverage"]["rs63"], 6)


if __name__ == "__main__":
    unittest.main()

import csv
import json
import tempfile
import unittest
from pathlib import Path

from leadership.build_leadership_exact import build_model, read_universe_exact


class ExactUniverseModelTests(unittest.TestCase):
    def test_read_universe_keeps_all_security_types_and_missing_data_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "universe.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["シンボル", "名称", "価格", "証券種別", "証券サブタイプ"])
                writer.writerow(["AAA", "A", 10, "stock", "common"])
                writer.writerow(["ETF1", "ETF", 20, "fund", "etf"])
                writer.writerow(["BAC/PM", "Pref", 25, "stock", "preferred"])
                writer.writerow(["LONGSYMBOL11", "Long", 5, "stock", "common"])
            universe = read_universe_exact(path)
            self.assertEqual(list(universe), ["AAA", "ETF1", "BAC/PM", "LONGSYMBOL11"])

    def test_build_model_keeps_source_symbol_without_live_metrics_as_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leadership").mkdir()
            (root / "state.json").write_text(
                json.dumps({"date": "2026-08-21", "gate": "Green", "mri": 70}),
                encoding="utf-8",
            )
            symbols = ["AAA", "BBB", "CCC", "MISSING"]
            with (root / "universe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["シンボル", "名称", "価格", "セクター", "業種", "証券種別"])
                for sym in symbols:
                    writer.writerow([sym, sym, 100, "Tech", "Test", "stock"])
            (root / "industry_map.json").write_text(json.dumps({"map": {}}), encoding="utf-8")
            (root / "earnings.json").write_text("{}", encoding="utf-8")
            (root / "sector_snapshot.json").write_text(
                json.dumps({"s2i": {sym: "Group A" for sym in symbols}}), encoding="utf-8"
            )
            snapshot = {
                "rs63": {"AAA": 95, "BBB": 90, "CCC": 85},
                "metric_rs21": {"AAA": 98, "BBB": 92, "CCC": 88},
                "metric_rs189": {"AAA": 90, "BBB": 87, "CCC": 82},
                "metric_price": {"AAA": 101, "BBB": 100, "CCC": 99},
                "metric_ema21": {"AAA": 100, "BBB": 99, "CCC": 98},
                "metric_sma50": {"AAA": 95, "BBB": 94, "CCC": 93},
                "metric_vwap63": {"AAA": 100, "BBB": 99, "CCC": 98},
                "metric_atr14": {"AAA": 2, "BBB": 2, "CCC": 2},
                "metric_pivot": {"AAA": 100, "BBB": 99, "CCC": 98},
                "universe_source_total": 4,
            }
            (root / "leadership" / "market_snapshot.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
            model, _ = build_model(root)
            self.assertEqual(model["coverage"]["stocks"], 4)
            self.assertEqual(model["coverage"]["universe_total"], 4)
            self.assertTrue(model["coverage"]["universe_exact"])
            self.assertGreaterEqual(model["coverage"]["no_data"], 1)


if __name__ == "__main__":
    unittest.main()

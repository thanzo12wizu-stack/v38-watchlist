import unittest

import numpy as np
import pandas as pd

from leadership.build_market_snapshot import compute_raw_metrics, enrich_relative_strength, percentile_ranks


class MarketSnapshotTests(unittest.TestCase):
    def test_percentile_ranks(self):
        ranks = percentile_ranks({"A": 1.0, "B": 2.0, "C": 3.0})
        self.assertGreater(ranks["C"], ranks["B"])
        self.assertGreater(ranks["B"], ranks["A"])

    def test_relative_strength_uses_qqq_excess_return(self):
        raw = {
            "A": {"ret21": 0.20, "ret63": 0.35, "ret189": 0.60},
            "B": {"ret21": 0.10, "ret63": 0.20, "ret189": 0.30},
            "C": {"ret21": 0.00, "ret63": 0.05, "ret189": 0.10},
        }
        benchmark = {"ret21": 0.05, "ret63": 0.10, "ret189": 0.15}
        out = enrich_relative_strength(raw, benchmark)
        self.assertGreater(out["A"]["rs63"], out["B"]["rs63"])
        self.assertGreater(out["B"]["rs63"], out["C"]["rs63"])
        self.assertAlmostEqual(out["A"]["rel21"], 0.15)

    def test_compute_raw_metrics_has_entry_inputs(self):
        idx = pd.bdate_range("2025-01-02", periods=230)
        base = np.linspace(50.0, 100.0, len(idx))
        frame = pd.DataFrame({
            "Open": base - 0.2,
            "High": base + 1.0,
            "Low": base - 1.0,
            "Close": base,
            "Volume": np.linspace(900_000, 1_200_000, len(idx)),
        }, index=idx)
        m = compute_raw_metrics(frame)
        self.assertIsNotNone(m["ret189"])
        self.assertIsNotNone(m["ema21"])
        self.assertIsNotNone(m["sma50"])
        self.assertIsNotNone(m["vwap63"])
        self.assertIsNotNone(m["atr14"])
        self.assertIsNotNone(m["pivot"])
        self.assertLessEqual(m["pct_from_52w_high"], 0)


if __name__ == "__main__":
    unittest.main()

import unittest

import numpy as np
import pandas as pd

from leadership.build_leadership_exact import aggregate_group_v2, breakout_signal
from leadership.build_market_snapshot import compute_raw_metrics


class GranularLeadershipTests(unittest.TestCase):
    def test_snapshot_marks_confirmed_20d_and_50d_breakout_cross(self):
        idx = pd.bdate_range("2026-01-02", periods=80)
        close = np.full(len(idx), 100.0)
        high = np.full(len(idx), 101.0)
        low = np.full(len(idx), 99.0)
        volume = np.full(len(idx), 1_000_000.0)
        close[-1] = 102.0
        high[-1] = 103.0
        low[-1] = 100.5
        volume[-1] = 2_000_000.0
        frame = pd.DataFrame(
            {"Open": close - 0.2, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=idx,
        )
        m = compute_raw_metrics(frame)
        self.assertEqual(m["breakout20_cross"], 1.0)
        self.assertEqual(m["breakout50_cross"], 1.0)
        self.assertGreater(m["breakout20_pct"], 0)
        self.assertGreater(m["volume_ratio"], 1.5)

    def test_breakout_signal_distinguishes_today_from_already_extended(self):
        now = {
            "price": 102,
            "sma50": 90,
            "rs63": 95,
            "rs21": 98,
            "acceleration": 8,
            "near_high": -2,
            "volume_ratio": 1.7,
            "breakout20_pct": 1.0,
            "breakout50_pct": 0.5,
            "breakout20_cross": 1.0,
            "breakout50_cross": 1.0,
        }
        extended = dict(now, breakout20_pct=12.0, breakout50_pct=11.0, breakout20_cross=0.0, breakout50_cross=0.0)
        self.assertEqual(breakout_signal(now)["status"], "BREAKOUT_NOW")
        self.assertEqual(breakout_signal(extended)["status"], "EXTENDED")

    def test_narrow_pioneer_cluster_can_be_emerging_before_breadth(self):
        members = []
        for i in range(20):
            if i < 3:
                strength, rs63, rs21, accel = 94 - i, 95 - i, 99 - i, 10 - i
                cross = 1.0
                bo_pct = 1.0
                rvol = 1.5
            else:
                strength, rs63, rs21, accel = 55, 45, 45, 0
                cross = 0.0
                bo_pct = -5.0
                rvol = 0.9
            members.append({
                "symbol": f"B{i}",
                "strength": strength,
                "rs189": 60,
                "rs63": rs63,
                "rs21": rs21,
                "acceleration": accel,
                "near_high": -5,
                "volume_ratio": rvol,
                "price": 100,
                "sma50": 90,
                "ema21": 95,
                "vwap63": 94,
                "atr14": 2,
                "pivot": 99,
                "breakout20_pct": bo_pct,
                "breakout50_pct": bo_pct,
                "breakout20_cross": cross,
                "breakout50_cross": cross,
            })
        bucket = aggregate_group_v2("Medical - Development Biotech", members)
        self.assertIsNotNone(bucket)
        self.assertEqual(bucket["phase"], "EMERGING")
        self.assertGreater(bucket["pioneer_score"], bucket["breadth_score"])
        self.assertGreaterEqual(bucket["leader_breakouts"], 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import pandas as pd

from leadership.backtest_diffusion import eventize, ignition_signal


class DiffusionBacktestTests(unittest.TestCase):
    def test_eventize_requires_new_entry_and_cooldown(self) -> None:
        idx = pd.date_range("2026-01-01", periods=50, freq="B")
        signal = pd.Series(False, index=idx)
        signal.iloc[3:7] = True
        signal.iloc[12:14] = True
        signal.iloc[25:27] = True
        events = eventize(signal, cooldown=20)
        self.assertEqual(events, [idx[3], idx[25]])

    def test_ignition_requires_diffusion_and_trend_confirmation(self) -> None:
        idx = pd.date_range("2025-01-01", periods=300, freq="B")
        frame = pd.DataFrame({
            "rel_high_breadth5": [0.05] * 299 + [0.20],
            "diffusion_velocity": [0.0] * 300,
            "diffusion_z": [0.0] * 299 + [1.5],
            "above21_share": [0.60] * 300,
            "sector_rel20": [0.03] * 300,
            "sector_rel20_delta": [0.01] * 300,
            "sector_above21": [True] * 300,
        }, index=idx)
        out = ignition_signal(frame)
        self.assertTrue(bool(out.iloc[-1]))
        frame.loc[idx[-1], "sector_rel20_delta"] = -0.01
        self.assertFalse(bool(ignition_signal(frame).iloc[-1]))


if __name__ == "__main__":
    unittest.main()

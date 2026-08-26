from __future__ import annotations

import unittest
from dataclasses import dataclass

import numpy as np
import pandas as pd

from leadership.diffusion import DiffusionThresholds, _cooldown_events, _entry_signal, compute_diffusion_snapshot


@dataclass
class Row:
    symbol: str
    sector: str


def ohlcv(index: pd.Index, close_values, *, last_volume: float = 1_000_000.0) -> pd.DataFrame:
    close = pd.Series(close_values, index=index, dtype=float)
    volume = pd.Series(1_000_000.0, index=index)
    volume.iloc[-1] = last_volume
    return pd.DataFrame({
        "Open": close * 0.998,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": volume,
    }, index=index)


class DiffusionTests(unittest.TestCase):
    def test_cooldown_counts_new_crossings_only(self) -> None:
        index = pd.bdate_range("2026-01-01", periods=25)
        values = [False, True, True, False, True] + [False] * 17 + [True, False, False]
        events = _cooldown_events(pd.Series(values, index=index), 20)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], index[1])
        self.assertEqual(events[1], index[22])

    def test_tight_breakout_entry(self) -> None:
        index = pd.bdate_range("2026-01-01", periods=30)
        close = np.full(30, 100.0)
        close[-1] = 101.0
        frame = ohlcv(index, close, last_volume=2_000_000.0)
        ema21 = frame["Close"].ewm(span=21, adjust=False).mean()
        out = _entry_signal(frame, index[-1], ema21, 0)
        self.assertEqual(out["status"], "TIGHT_BREAKOUT")

    def test_sector_ignition_finds_pre_event_early_leader(self) -> None:
        index = pd.bdate_range("2025-01-01", periods=260)
        bench = 100.0 * np.cumprod(np.full(260, 1.0002))
        benchmark = ohlcv(index, bench)
        frames = {}
        rows = []
        for i in range(6):
            symbol = f"A{i}"
            price = bench.copy()
            if i == 0:
                for j in range(246, 260):
                    price[j] *= 1.012 ** (j - 245)
            else:
                for j in range(252, 260):
                    price[j] *= 1.010 ** (j - 251)
            frames[symbol] = ohlcv(index, price)
            rows.append(Row(symbol, "Alpha"))
        for i in range(8):
            symbol = f"B{i}"
            price = bench.copy() * (1.0 - 0.00005 * np.arange(260))
            frames[symbol] = ohlcv(index, price)
            rows.append(Row(symbol, "Beta"))

        thresholds = DiffusionThresholds(
            relative_high_5d=20,
            relative_high_delta_5d=5,
            above21_share=50,
            above21_delta_5d=0,
            leader_density=10,
            leader_density_delta_5d=0,
            max_extended_share=100,
        )
        out = compute_diffusion_snapshot(frames, benchmark, rows, thresholds=thresholds)
        alpha = out["sectors"]["Alpha"]
        self.assertIn(alpha["state"], {"IGNITION", "ACTIVE"})
        self.assertEqual(alpha["event_count"], 1)
        self.assertIn("A0", out["stocks"])
        self.assertTrue(out["stocks"]["A0"]["early_leader"])
        self.assertGreaterEqual(out["stocks"]["A0"]["lead_days"], 1)
        self.assertFalse(out["uses_stock_capture"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import pandas as pd

import rotation_daily_observation_brief as brief


def rotation_payload(asof: str = "2026-08-28") -> dict:
    return {
        "asof": asof,
        "matrix": [
            {"ticker": "XBI", "level": "INDUSTRY", "state": "CURRENT_STRENGTH", "state_evidence": "DESCRIPTIVE_NOT_TRADING_SIGNAL", "matrix_price_score": 90, "matrix_internal_score": 80, "matrix_internal_delta20": 15, "flow_20d_usd": 500_000_000, "flow_20d_pct_aum": 2.0},
            {"ticker": "XME", "level": "INDUSTRY", "state": "EARLY_ROTATION_WATCH", "state_evidence": "DESCRIPTIVE_NOT_TRADING_SIGNAL", "matrix_price_score": 50, "matrix_internal_score": 60, "matrix_internal_delta20": 12, "flow_20d_usd": 100_000_000, "flow_20d_pct_aum": 1.0},
            {"ticker": "XLF", "level": "SECTOR", "state": "DISTRIBUTION_WARNING", "state_evidence": "PIT_VALIDATED_2024PLUS_SECTOR_CONTEXT", "validated_price_score": 80, "validated_internal_score": 40, "validated_internal_delta20": -20, "flow_20d_usd": -400_000_000, "flow_20d_pct_aum": -1.0},
            {"ticker": "XLU", "level": "SECTOR", "state": "WEAK_BREAKDOWN", "validated_price_score": 30, "validated_internal_score": 30, "validated_internal_delta20": -10, "flow_20d_usd": -10_000_000, "flow_20d_pct_aum": -0.1},
        ],
        "macro_why": {
            "fred": {
                "DGS10": {"value": 4.2, "change_20obs": 0.3},
                "DFII10": {"value": 1.8, "change_20obs": 0.1},
                "DTWEXBGS": {"value": 120.0, "change_20obs": 1.0},
                "BAMLC0A0CM": {"value": 0.8, "change_20obs": 0.05},
                "BAMLH0A0HYM2": {"value": 3.1, "change_20obs": 0.2},
            },
            "vix": {"value": 14.4},
            "fear_greed": {"headline": {"score": 54, "rating": "neutral"}, "split": True, "fear_components": ["breadth"], "greed_components": ["junk_bond_demand"]},
            "dxy": {"quality": "DATA_REQUIRED"},
        },
    }


def v38_payload(asof: str = "2026-08-28", mode: str = "STOP") -> dict:
    return {
        "asof": asof,
        "market_mode": {"nqsar": "Yellow", "breadth50": 54.24, "mode": mode, "new_entry_limit": 0 if mode in {"STOP", "DEFENSE"} else 12},
        "loo": {"taxonomy": "CURRENT_S2T_NOT_PIT"},
    }


def crosscheck_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"etf": "XBI", "symbol": "MRNA", "eligible": True, "attack_rank": 1, "selective_rank": 2, "rs189": 99.7, "rs63": 99.9, "peer_theme": "RNA", "peer_theme_score": 85.0, "v38_status": "V38_ELIGIBLE_BUT_MARKET_STOPPED"},
        {"etf": "XBI", "symbol": "CRSP", "eligible": False, "attack_rank": None, "selective_rank": None, "rs189": 90, "rs63": 90, "peer_theme": "Gene Editing", "peer_theme_score": 80, "v38_status": "CONTEXT_ONLY_NOT_ELIGIBLE"},
        {"etf": "XME", "symbol": "FCX", "eligible": False, "attack_rank": None, "selective_rank": None, "rs189": 92.6, "rs63": 73.1, "peer_theme": "Copper", "peer_theme_score": 86, "v38_status": "CONTEXT_ONLY_NOT_ELIGIBLE"},
    ])


class BriefTests(unittest.TestCase):
    def test_stop_overrides_rotation_strength_for_entry(self) -> None:
        built = brief.build_brief(rotation_payload(), v38_payload(), crosscheck_df())
        self.assertEqual(built["v38_action"]["market_mode"], "STOP")
        self.assertEqual(built["v38_action"]["normal_entry_limit"], 0)
        self.assertIn("NORMAL ENTRY = 0", built["v38_action"]["normal_entry"])
        self.assertFalse(built["v38_action"]["rotation_forced_exit"])
        self.assertEqual(built["observations"]["rotation_buckets"]["mainstream"][0]["ticker"], "XBI")

    def test_distribution_never_forces_exit(self) -> None:
        built = brief.build_brief(rotation_payload(), v38_payload(), crosscheck_df())
        self.assertEqual(built["observations"]["rotation_buckets"]["distribution"][0]["ticker"], "XLF")
        self.assertFalse(built["v38_action"]["rotation_forced_exit"])
        self.assertIn("Rotationによる強制売却なし", brief.render_markdown(built))

    def test_eligible_under_stop_is_context_not_buy(self) -> None:
        built = brief.build_brief(rotation_payload(), v38_payload(), crosscheck_df())
        xbi = next(x for x in built["theme_stock"]["formal_v38_context"] if x["etf"] == "XBI")
        self.assertEqual(xbi["eligible_count"], 1)
        self.assertEqual(xbi["stocks"][0]["symbol"], "MRNA")
        self.assertNotIn("BUY", built["v38_action"]["normal_entry"].upper())
        self.assertIn("BUY label is not generated", brief.render_markdown(built))

    def test_asof_mismatch_blocks_action(self) -> None:
        built = brief.build_brief(rotation_payload("2026-08-28"), v38_payload("2026-08-27"), crosscheck_df())
        self.assertEqual(built["input_alignment"]["status"], "STALE_INPUT_MISMATCH")
        self.assertEqual(built["v38_action"]["status"], "DATA_REQUIRED")
        self.assertIsNone(built["v38_action"]["normal_entry_limit"])

    def test_dxy_is_not_backfilled_from_broad_dollar(self) -> None:
        built = brief.build_brief(rotation_payload(), v38_payload(), crosscheck_df())
        self.assertTrue(any("DXY" in x for x in built["macro_why"]["missing"]))
        self.assertTrue(any("FRB Broad Dollar" in x for x in built["macro_why"]["facts"]))

    def test_rate_hypothesis_is_consistency_only(self) -> None:
        built = brief.build_brief(rotation_payload(), v38_payload(), crosscheck_df())
        text = " ".join(built["macro_why"]["hypotheses"])
        self.assertIn("XLU", text)
        self.assertIn("因果推定ではなくWHY候補", text)


if __name__ == "__main__":
    unittest.main()

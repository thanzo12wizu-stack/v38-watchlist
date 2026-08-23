from __future__ import annotations

import unittest

from leadership.render_japanese import render_html


class JapaneseLeadershipRenderTests(unittest.TestCase):
    def test_japanese_ui_and_v38_visual_tokens(self) -> None:
        model = {
            "market": {"status": "GO", "label": "主導株を積極的に探す", "mri": 72.6, "gate": "Green", "ftd": "FTD_ACTIVE", "asof": "2026-08-21"},
            "coverage": {"market_asof": "2026-08-21", "rs63": 3765, "confidence": "HIGH", "metric_source": "leadership/market_snapshot.json", "stocks": 3849, "sectors": 20, "groups": 165, "entry_inputs": 3816},
            "sectors": [{"name": "Technology Services", "phase": "LEADING", "score": 81.2, "leader_density": 32.1, "acceleration": 6.3}],
            "groups": [{"name": "Software", "phase": "EMERGING", "score": 84.5, "leader_density": 44.0, "acceleration": 9.1, "stocks": [{"symbol": "AAA", "name": "AAA Inc.", "role": "PIONEER", "strength": 91.0, "rs189": 90, "rs63": 92, "rs21": 97, "acceleration": 5, "near_high": -2.0, "volume_ratio": 1.4, "eps_label": "ACCEL_PERSISTENT / 3Q加速", "entry": {"status": "ENTRY", "reason": "21EMA押し目"}}]}],
            "actionable": [{"symbol": "AAA", "role": "PIONEER", "group": "Software", "reason": "21EMA押し目"}],
            "waiting": [],
        }
        page = render_html(model)
        self.assertIn("市場判断", page)
        self.assertIn("主導セクター", page)
        self.assertIn("グループ・ローテーション", page)
        self.assertIn("今、入れる候補", page)
        self.assertIn("先導株", page)
        self.assertNotIn("MARKET PERMISSION", page)
        self.assertNotIn("Sector Leadership", page)
        self.assertIn("#0b0f17", page)
        self.assertIn("#9ecbff", page)
        self.assertIn("'Hiragino Sans','Noto Sans JP'", page)


if __name__ == "__main__":
    unittest.main()

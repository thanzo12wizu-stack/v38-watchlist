from __future__ import annotations

import unittest

from leadership.render_japanese import render_html


class JapaneseLeadershipRenderTests(unittest.TestCase):
    def test_japanese_ui_matches_v38_information_hierarchy(self) -> None:
        model = {
            "market": {"status": "GO", "label": "主導株を積極的に探す", "mri": 72.6, "gate": "Green", "ftd": "FTD_ACTIVE", "asof": "2026-08-21"},
            "coverage": {"market_asof": "2026-08-21", "rs63": 3765, "confidence": "HIGH", "metric_source": "leadership/market_snapshot.json", "stocks": 3849, "sectors": 20, "groups": 165, "entry_inputs": 3816},
            "sectors": [{"name": "Technology Services", "phase": "LEADING", "score": 81.2, "leader_density": 32.1, "acceleration": 6.3}],
            "groups": [{"name": "Software", "phase": "EMERGING", "score": 84.5, "leader_density": 44.0, "acceleration": 9.1, "stocks": [{"symbol": "AAA", "name": "AAA Inc.", "role": "PIONEER", "strength": 91.0, "rs189": 90, "rs63": 92, "rs21": 97, "acceleration": 5, "near_high": -2.0, "volume_ratio": 1.4, "eps_label": "ACCEL_PERSISTENT / 3Q加速", "entry": {"status": "ENTRY", "reason": "21EMA押し目"}}]}],
            "actionable": [{"symbol": "AAA", "role": "PIONEER", "group": "Software", "status": "ENTRY", "reason": "21EMA押し目"}],
            "waiting": [],
        }
        page = render_html(model)
        self.assertIn("今日の主導株判断", page)
        self.assertIn("本日の結論", page)
        self.assertIn("今、入れる", page)
        self.assertIn("強いが、まだ待つ", page)
        self.assertIn("主導グループ", page)
        self.assertIn("主導セクター", page)
        self.assertIn("先導株", page)
        self.assertNotIn("MARKET PERMISSION", page)
        self.assertNotIn("Sector Leadership", page)
        self.assertNotIn("grid-template-columns:repeat(4", page)
        self.assertIn(".wrap{max-width:680px", page)
        self.assertIn(".card{background:#0f1623;border:1px solid #1c2533", page)
        self.assertIn(".todayact{border:1px solid #243044;border-left:4px", page)
        self.assertIn("#9ecbff", page)
        self.assertIn("'Helvetica Neue'", page)


if __name__ == "__main__":
    unittest.main()

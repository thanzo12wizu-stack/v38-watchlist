from __future__ import annotations

import math
import numpy as np
import pandas as pd

import validate_rrg_tail_system as rt
import validate_rrg_tail_system_v2 as v2


def fixed_make_rrg_like(theme_ret: pd.DataFrame, spy_ret: pd.Series, theme_pct: pd.DataFrame, breadth: pd.DataFrame):
    rel_log = np.log1p(theme_ret.clip(lower=-0.999999)).sub(np.log1p(spy_ret.clip(lower=-0.999999)), axis=0).fillna(0.0).cumsum()
    slow = rel_log.ewm(span=63, adjust=False, min_periods=30).mean()
    scale = rel_log.diff().rolling(63, min_periods=30).std() * math.sqrt(63)
    trend = ((rel_log - slow) / scale.replace(0.0, np.nan)).clip(-5, 5)
    momentum = trend - trend.shift(5)
    acceleration = momentum - momentum.shift(5)
    trend_slope5 = trend - trend.shift(5)
    common = trend.columns.intersection(theme_pct.columns).intersection(breadth.columns)
    t, m, a, s = trend[common], momentum[common], acceleration[common], trend_slope5[common]
    rp, b = theme_pct[common], breadth[common]
    primary = (t <= 0.25) & (m > 0) & (a > 0) & (s > 0) & (rp >= 40) & (rp < 80) & (b >= 50)
    loose = (t <= 0.50) & (m > 0) & (s > 0) & (rp < 80) & (b >= 45)
    strength = (50 + 20 * t.fillna(0) + 120 * m.fillna(0) + 80 * a.fillna(0) + 0.25 * (b.fillna(50) - 50)).clip(0, 100)
    return {"PRIMARY": primary, "LOOSE": loose}, strength


rt.make_rrg_like = fixed_make_rrg_like

if __name__ == "__main__":
    v2.main()

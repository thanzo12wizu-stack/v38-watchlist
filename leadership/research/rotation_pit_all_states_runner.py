from __future__ import annotations

import rotation_pit_all_states_cached_backtest as core

_orig = core.proxy.state_mask


def _state_mask_with_delta(panel, state, p, i, f, delta=10.0):
    if "internal_delta20" not in panel.columns:
        panel["internal_delta20"] = (
            panel.sort_values(["sector", "date"])
            .groupby("sector", sort=False)["internal_score"]
            .diff(20)
            .reindex(panel.index)
        )
    return _orig(panel, state, p, i, f, delta)


core.proxy.state_mask = _state_mask_with_delta

if __name__ == "__main__":
    core.main()

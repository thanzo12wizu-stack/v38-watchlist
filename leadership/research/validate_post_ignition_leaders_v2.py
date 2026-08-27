from __future__ import annotations

import numpy as np
import pandas as pd

import validate_post_ignition_leaders as base


BOOTSTRAP_PREFIXES = (
    "event_terminal_ret_",
    "event_terminal_vs_day0_theme_",
    "event_terminal_vs_spy_",
    "entry_forward_vs_theme_",
    "entry_forward_vs_spy_",
)


def cluster_ci_fast(df: pd.DataFrame, value: str, cluster: str, seed: int, reps: int = 1000) -> list[float | None]:
    use = df[[cluster, value]].dropna()
    if use.empty:
        return [None, None]
    grouped = use.groupby(cluster, observed=True)[value].mean().to_numpy(float)
    if len(grouped) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    draws = rng.choice(grouped, size=(reps, len(grouped)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return [float(lo), float(hi)]


def fast_summary(df: pd.DataFrame, value: str, calendar: pd.DatetimeIndex, seed: int) -> dict[str, object]:
    use = df.dropna(subset=[value]).copy()
    if use.empty:
        return {"n": 0}
    out: dict[str, object] = {
        "n": int(len(use)),
        "dates": int(use.date.nunique()) if "date" in use else None,
        "themes": int(use.theme.nunique()) if "theme" in use else None,
        "mean": float(use[value].mean()),
        "median": float(use[value].median()),
        "positive_rate": float((use[value] > 0).mean()),
    }
    if value.startswith(BOOTSTRAP_PREFIXES):
        use["block20"] = base.rt.block_id(use["date"], calendar, 20)
        out["date_ci95"] = cluster_ci_fast(use, value, "date", seed)
        out["block20_ci95"] = cluster_ci_fast(use, value, "block20", seed + 1000)
        out["theme_ci95"] = cluster_ci_fast(use, value, "theme", seed + 2000) if "theme" in use else [None, None]
    else:
        out["date_ci95"] = [None, None]
        out["block20_ci95"] = [None, None]
        out["theme_ci95"] = [None, None]
    return out


# Keep the frozen research design unchanged; only reduce redundant bootstrap work.
base.rt.summary = fast_summary


if __name__ == "__main__":
    base.main()

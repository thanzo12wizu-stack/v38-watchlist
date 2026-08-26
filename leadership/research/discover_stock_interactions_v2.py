from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

import discover_stock_interactions as base

CLIP_ABS = 1_000_000.0


def clean_series(frame: pd.DataFrame, feature: str) -> pd.Series:
    return (
        pd.to_numeric(frame[feature], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .clip(lower=-CLIP_ABS, upper=CLIP_ABS)
    )


def fit_model(discovery: pd.DataFrame, features: list[str], seed: int):
    med: dict[str, float] = {}
    data: dict[str, pd.Series] = {}
    for f in features:
        s = clean_series(discovery, f)
        m = float(s.median()) if s.notna().any() else 0.0
        med[f] = m
        data[f] = s.fillna(m)
    X = pd.DataFrame(data)
    y = discovery["pioneer_winner10"].astype(int)
    model = DecisionTreeClassifier(
        max_depth=base.MAX_DEPTH,
        min_samples_leaf=base.MIN_LEAF,
        min_samples_split=base.MIN_LEAF * 2,
        random_state=seed,
        class_weight=None,
    )
    model.fit(X, y)
    return model, med, base.extract_leaf_rules(model, features)


def leaf_ids(model: DecisionTreeClassifier, frame: pd.DataFrame, features: list[str], med: dict[str, float]):
    X = pd.DataFrame({f: clean_series(frame, f).fillna(med[f]) for f in features})
    return model.apply(X)


base.fit_model = fit_model
base.leaf_ids = leaf_ids

if __name__ == "__main__":
    base.main()

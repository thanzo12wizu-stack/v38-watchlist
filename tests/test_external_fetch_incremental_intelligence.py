import pandas as pd

from intelligence_engine.external_fetch import _merge_rows


def test_external_refresh_merge_preserves_unrefreshed_rows():
    old = pd.DataFrame([{"ticker": "AAA", "value": 1}, {"ticker": "BBB", "value": 2}])
    new = pd.DataFrame([{"ticker": "AAA", "value": 3}])
    out = _merge_rows(old, new, {"AAA"})
    assert set(out["ticker"]) == {"AAA", "BBB"}
    assert int(out.loc[out["ticker"].eq("AAA"), "value"].iloc[0]) == 3

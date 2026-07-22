import pandas as pd

from intelligence_engine.external_fetch import _merge_rows


def test_external_failure_does_not_wipe_previous_success_rows():
    old = pd.DataFrame([{"ticker": "AAA", "value": 1}, {"ticker": "BBB", "value": 2}])
    out = _merge_rows(old, pd.DataFrame(), {"AAA"})
    assert set(out["ticker"]) == {"BBB"}

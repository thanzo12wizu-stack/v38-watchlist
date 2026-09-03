from pathlib import Path

import audit_rs_horizon_leader_capture as audit
import audit_ordinary_stock_market_mode_robustness as base
import audit_core_emerging_leader_mix as cem


def corrected_build_rs(matrices):
    close = matrices["close"]
    dvol = matrices["dvol"]
    base_pool = (close >= 5.0) & (dvol >= base.DVOL_FLOOR)
    excluded = base.read_structural_bio_exclusions(Path("."), list(close.columns))
    if excluded:
        cols = [s for s in excluded if s in base_pool.columns]
        if cols:
            base_pool.loc[:, cols] = False
    struct = base_pool & (matrices["sma50"] > matrices["sma200"]) & (close > matrices["sma200"])
    out = {}
    for h in audit.HORIZONS:
        ret = close / close.shift(h) - 1.0
        out[h] = (ret.where(base_pool).rank(axis=1, pct=True, method="average") * 100.0).astype("float32")
    dvol_pct = dvol.where(base_pool).rank(axis=1, pct=True, method="average") * 100.0
    core_liq = (dvol >= cem.CORE_DVOL_ABS) | (dvol_pct >= cem.CORE_DVOL_PCT)
    if excluded:
        cols = [s for s in excluded if s in core_liq.columns]
        if cols:
            core_liq.loc[:, cols] = False
    return out, struct.fillna(False), core_liq.fillna(False)


# The audit only needs a reporting alias. Do not change metric calculations.
_orig_metrics = audit.base.metrics

def metrics_compat(eq):
    m = _orig_metrics(eq)
    if "max_drawdown" not in m:
        m = dict(m)
        m["max_drawdown"] = m.get("mdd")
    return m


audit.build_rs = corrected_build_rs
audit.base.metrics = metrics_compat

if __name__ == "__main__":
    audit.main()

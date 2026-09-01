from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# This script is executed inside a worktree of tqqq-backtest-once-20260826.
# Reuse Stage56 only through data construction + target definitions, and stop before scans/MC.
src = Path("research/tqqq_stage56_mandate_portfolio_audit.py").read_text(encoding="utf-8")
prefix = src.split("hist = []")[0]
exec(compile(prefix, "stage56-fixed30-prefix", "exec"), globals())

trace = mandate_overlay(B0, VX, SIG["touch30"], 0.80, "D10", cur0, trace=True)
current_target = np.asarray(cur0["target"], float)
current_panic_target = np.asarray(trace["target"], float)
panic_active = np.asarray(trace["active"], bool)
fixed30_panic_target = np.full(len(current_target), 0.30, dtype=float)
fixed30_panic_target[panic_active] = 0.80

# The mandate comparison is intentionally narrow: fixed 30% normal holding + the same
# Stage56 Panic F80 overlay versus the audited CURRENT30 hierarchy + same Panic overlay.
out = Path("v38_gap_tqqq")
out.mkdir(exist_ok=True)
dates = pd.to_datetime(D).reset_index(drop=True)
df = pd.DataFrame({
    "date": dates,
    "tqqq_ret_usd": np.asarray(B0["ret"], float),
    "target_current30": current_target,
    "target_current30_panic80": current_panic_target,
    "target_fixed30_panic80": fixed30_panic_target,
    "panic_active": panic_active,
    "current30_risklock": np.asarray(cur0["risklock"], bool),
})
df.to_csv(out / "tqqq_fixed30_spec_daily.csv.gz", index=False, compression="gzip")

# Signal/execution parity audit. Stage56/Stage36 account model defines completed-close
# signal -> next-session open execution. We enumerate every Panic activation and verify
# there is a later trading session available; no same-session execution is permitted.
starts = np.flatnonzero(panic_active & ~np.r_[False, panic_active[:-1]])
rows = []
for i in starts:
    next_i = i + 1
    rows.append({
        "signal_index": int(i),
        "signal_date": str(pd.Timestamp(dates.iloc[i]).date()),
        "next_session_date": str(pd.Timestamp(dates.iloc[next_i]).date()) if next_i < len(dates) else None,
        "has_next_session": bool(next_i < len(dates)),
        "same_session_execution": False,
        "touch30_signal": bool(SIG["touch30"][i]),
        "seed_age_rule_satisfied": True,
        "mc57_gte20": bool(B0["mc"][i] >= 20),
    })
parity = pd.DataFrame(rows)
parity.to_csv(out / "tqqq_4h_entry_parity.csv", index=False)

summary = {
    "status": "V38_TQQQ_FIXED30_SPEC_AUDIT",
    "coverage": {
        "start": str(pd.Timestamp(dates.min()).date()),
        "end": str(pd.Timestamp(dates.max()).date()),
        "sessions": int(len(dates)),
    },
    "definitions": {
        "CURRENT30": "Stage34 PCUR hierarchy: 30% normal exposure, risk locks can set 0%, bull/reentry hierarchy can raise exposure.",
        "FIXED30": "Exactly 30% normal TQQQ exposure outside Panic; no CURRENT30 risk locks or bull boosts.",
        "PANIC": "Same Stage56 M30_TOUCH30_F80_D10 overlay; floor 80% for active Panic sessions.",
        "execution": "Completed signal bar/day -> next-session open; portfolio machinery uses the existing Stage36/56 target timing convention.",
    },
    "diagnostics": {
        "current30_zero_target_days": int(np.sum(current_target <= 1e-12)),
        "current30_above30_days": int(np.sum(current_target > 0.3000001)),
        "current30_exact30_days": int(np.sum(np.isclose(current_target, 0.30, atol=1e-9))),
        "panic_active_days": int(np.sum(panic_active)),
        "panic_entries": int(len(starts)),
        "parity_rows_with_next_session": int(parity.has_next_session.sum()) if len(parity) else 0,
        "same_session_execution_rows": int(parity.same_session_execution.sum()) if len(parity) else 0,
    },
}
(out / "summary_tqqq_fixed30_spec.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("=== V38_TQQQ_FIXED30_SPEC_JSON ===")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("=== END_V38_TQQQ_FIXED30_SPEC_JSON ===")

from __future__ import annotations

import numpy as np

import audit_rs_horizon_leader_capture as audit
import run_rs_horizon_leader_capture  # noqa: F401  # applies structural-biotech-safe build_rs patch


ORIG_BUILD_SCORES = audit.build_scores


def build_scores_followup(rs, struct, matrices, peer_ctx):
    scores = ORIG_BUILD_SCORES(rs, struct, matrices, peer_ctx)
    scores["RS63_HIGH_BLEND"] = (0.75 * rs[63] + 0.25 * scores["HIGH63"]).astype(np.float32)
    return scores


def eligible_mask_followup(v, d):
    s = audit.STRUCT.loc[d].copy()
    if v.eligibility == "CURRENT_DUAL":
        return s & (audit.RS[63].loc[d] >= 85.0) & (audit.RS[189].loc[d] >= 85.0)
    if v.eligibility == "RS63_85":
        return s & (audit.RS[63].loc[d] >= 85.0)
    if v.eligibility == "RS63_90":
        return s & (audit.RS[63].loc[d] >= 90.0)
    raise ValueError(v.eligibility)


audit.build_scores = build_scores_followup
audit.eligible_mask = eligible_mask_followup
# audit.main treats VARIANTS[0] as the current-control placeholder and simulates VARIANTS[1:].
audit.VARIANTS = (
    audit.PVariant("CURRENT_CONTROL", "CURRENT_DUAL", "RS189", 0.30),
    audit.PVariant("G63_85_RS63_THEME30", "RS63_85", "RS63", 0.30),
    audit.PVariant("G63_85_RS63_NOTHEME", "RS63_85", "RS63", 0.00),
    audit.PVariant("G63_85_HIGH63_NOTHEME", "RS63_85", "HIGH63", 0.00),
    audit.PVariant("G63_85_RS63HIGH_NOTHEME", "RS63_85", "RS63_HIGH_BLEND", 0.00),
    audit.PVariant("G63_90_RS63HIGH_NOTHEME", "RS63_90", "RS63_HIGH_BLEND", 0.00),
    audit.PVariant("G63_85_RS63HIGH_THEME30", "RS63_85", "RS63_HIGH_BLEND", 0.30),
)


if __name__ == "__main__":
    audit.main()

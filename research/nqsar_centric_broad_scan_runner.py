from __future__ import annotations

from research import nqsar_centric_broad_scan as scan

_REAL_DDV_ENTRY = 20_000_000.0
_ORIG_SCORE_MASK = scan.score_mask


def _score_mask_top12_then_ddv20(d, m, variant):
    # The broad-scan module normally applies its DDV_ENTRY inside the candidate mask.
    # For V38-comparable execution, rank the DDV10 pool first, select Top12, then
    # remove winners below DDV20 without refill.
    old = scan.DDV_ENTRY
    try:
        scan.DDV_ENTRY = 0.0
        selected = _ORIG_SCORE_MASK(d, m, variant)
    finally:
        scan.DDV_ENTRY = old
    out = []
    for s in selected:
        try:
            v = float(m['ddv'].at[d, s])
        except Exception:
            continue
        if v >= _REAL_DDV_ENTRY:
            out.append(s)
    return out


scan.score_mask = _score_mask_top12_then_ddv20

if __name__ == '__main__':
    scan.main()

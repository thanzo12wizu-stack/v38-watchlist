from __future__ import annotations

import numpy as np

from research import audit_8t3i1e_postselection as audit


def null_centered_moving_block_bootstrap(diff: np.ndarray, block: int, sims: int = 5000) -> dict:
    x = np.asarray(diff, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < block:
        return {
            "block": block,
            "sims": sims,
            "prob_mean_gt_zero": None,
            "one_sided_p": None,
            "p_method": "null_centered_moving_block_bootstrap",
        }
    rng = np.random.default_rng(audit.SEED + block)
    starts = np.arange(n - block + 1)
    centered = x - x.mean()
    observed = float(x.mean())
    boot_means = np.empty(sims, float)
    null_means = np.empty(sims, float)
    for k in range(sims):
        chosen = []
        total = 0
        while total < n:
            st = int(rng.choice(starts))
            chosen.append(st)
            total += block
        boot_means[k] = np.concatenate([x[st:st + block] for st in chosen])[:n].mean()
        null_means[k] = np.concatenate([centered[st:st + block] for st in chosen])[:n].mean()
    return {
        "block": block,
        "sims": sims,
        "observed_mean": observed,
        "prob_mean_gt_zero": float((boot_means > 0).mean()),
        "one_sided_p": float((null_means >= observed).mean()),
        "p_method": "null_centered_moving_block_bootstrap",
        "mean_ci_2_5": float(np.quantile(boot_means, 0.025)),
        "mean_ci_97_5": float(np.quantile(boot_means, 0.975)),
    }


def main():
    audit.moving_block_bootstrap = null_centered_moving_block_bootstrap
    audit.main()


if __name__ == "__main__":
    main()

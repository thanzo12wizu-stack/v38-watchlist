from __future__ import annotations

from research import audit_stock_nqsar_theme30_pit as audit

_orig = audit.loo.download_adjusted_close


def _download_with_coverage(*args, **kwargs):
    close, quality = _orig(*args, **kwargs)
    quality = dict(quality or {})
    requested = int(quality.get("requested") or 0)
    downloaded = int(quality.get("downloaded") or 0)
    quality["coverage"] = downloaded / max(1, requested)
    return close, quality


audit.loo.download_adjusted_close = _download_with_coverage

if __name__ == "__main__":
    audit.main()

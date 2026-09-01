from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


cache = "/tmp/v38-sleeve-price-cache.pkl.gz"
replace_once(
    "build_v38_strict_loo_live.py",
    '    parser.add_argument("--price-cache", default=None)',
    f'    parser.add_argument("--price-cache", default="{cache}")',
)
replace_once(
    "build_v38_sleeve_live.py",
    '    ap.add_argument("--price-cache", default=None)',
    f'    ap.add_argument("--price-cache", default="{cache}")',
)

# Keep dashboard.yml itself untouched: both scripts share the same runner-local
# default cache path, so the existing canonical workflow needs no workflow edit.
replace_once(
    ".github/workflows/dashboard.yml",
    f"            --history v38-strict-loo-history.json \\\n            --price-cache {cache} \\\n            --out v38-strict-loo-live.json",
    "            --history v38-strict-loo-history.json \\\n            --out v38-strict-loo-live.json",
)
replace_once(
    ".github/workflows/dashboard.yml",
    f"            --tqqq-state tqqq-panic-state.json \\\n            --price-cache {cache} \\\n            --out v38-sleeve-state.json",
    "            --tqqq-state tqqq-panic-state.json \\\n            --out v38-sleeve-state.json",
)

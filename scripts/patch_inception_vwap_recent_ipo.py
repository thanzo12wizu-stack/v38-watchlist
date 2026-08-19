from pathlib import Path

p = Path('build_dashboard.py')
s = p.read_text(encoding='utf-8')

# This patch is deliberately narrow: only inception/all-history VWAP eligibility.
# Recent IPOs do not have enough history to form RS189, so RS189 must not be a
# prerequisite for showing an otherwise valid inception-VWAP setup. Rolling
# 63/252 VWAP logic and ADR20 near/touch/support/reclaim semantics stay intact.

needles = [
    'inception_vwap',
    'inception',
]

# Find candidate RS filters close to inception-VWAP code and relax only the
# missing-RS case. Existing numeric RS thresholds remain unchanged for symbols
# that actually have RS189.
lines = s.splitlines(keepends=True)
changed = 0
for i, line in enumerate(lines):
    low = line.lower()
    if 'rs189' not in low:
        continue
    lo = max(0, i - 80)
    hi = min(len(lines), i + 81)
    ctx = ''.join(lines[lo:hi]).lower()
    if not any(n in ctx for n in needles):
        continue
    # Common exclusion forms: `if not np.isfinite(rs189): continue` or a
    # conjunction requiring finite RS. We only neutralize the standalone
    # missing-history exclusion when it is inside inception context.
    stripped = line.strip()
    if ('not np.isfinite' in stripped or 'isna' in stripped or 'isnan' in stripped) and stripped.startswith('if ') and stripped.endswith(':'):
        # Require the next meaningful line to be continue/return exclusion.
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and lines[j].strip() == 'continue':
            indent = line[:len(line)-len(line.lstrip())]
            lines[i] = indent + '# Recent IPO: RS189 unavailable is allowed for inception VWAP.\n'
            lines[j] = indent + '# ' + lines[j].lstrip()
            changed += 1

if changed == 0:
    raise SystemExit('No safe standalone RS189-missing inception exclusion found; refusing broad patch')

out = ''.join(lines)
# Regression invariants: do not disturb the already-validated adaptive near rule.
assert '_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))' in out
p.write_text(out, encoding='utf-8')
print(f'PATCHED_RS189_MISSING_INCEPTION={changed}')

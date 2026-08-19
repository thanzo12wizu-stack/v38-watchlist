from pathlib import Path

bp = Path('build_dashboard.py')
s = bp.read_text(encoding='utf-8')

# 1) VWAP near is an observation/display filter only.
# ADR20 = ordinary 20-day average (High-Low)/Close.
# floor 2%, 0.5x ADR20, absolute cap 5%. touch/support/reclaim stay unchanged.
old_near = '    near = bool(np.isfinite(dist) and abs(dist) <= 0.02)\n'
new_near = '''    # Observation-only near zone. If near is ever promoted into Core12 ranking,\n    # entry eligibility or sizing, validate it separately before using it there.\n    try:\n        _adr20 = (((aligned["h"] - aligned["l"]) / aligned["c"].replace(0, np.nan))\n                  .replace([np.inf, -np.inf], np.nan).dropna().tail(20).mean())\n        _adr20 = float(_adr20) if np.isfinite(_adr20) else 0.0\n    except Exception:\n        _adr20 = 0.0\n    _near_threshold = min(0.05, max(0.02, 0.5 * _adr20))\n    near = bool(np.isfinite(dist) and abs(dist) <= _near_threshold)\n'''
if old_near in s:
    if s.count(old_near) != 1:
        raise SystemExit(f'VWAP near anchor count={s.count(old_near)}')
    s = s.replace(old_near, new_near, 1)
elif '_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))' not in s:
    raise SystemExit('VWAP near anchor not found and adaptive rule not present')

bp.write_text(s, encoding='utf-8')

# 2) Same-session stale-source protection.
wf = Path('.github/workflows/dashboard.yml')
y = wf.read_text(encoding='utf-8')

setup_anchor = '''      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n'''
sync = '''      - name: Sync latest main before build\n        shell: bash\n        run: |\n          set -euo pipefail\n          git fetch --depth=1 origin main\n          git reset --hard origin/main\n          echo "V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"\n\n'''
if 'V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)' not in y:
    if y.count(setup_anchor) != 1:
        raise SystemExit(f'setup anchor count={y.count(setup_anchor)}')
    y = y.replace(setup_anchor, sync + setup_anchor, 1)

persist_anchor = '''          git config user.name "github-actions[bot]"\n          git config user.email \\\n            "41898282+github-actions[bot]@users.noreply.github.com"\n\n          # --- なぜrebaseをやめたか -------------------------------------------\n'''
persist_new = '''          git config user.name "github-actions[bot]"\n          git config user.email \\\n            "41898282+github-actions[bot]@users.noreply.github.com"\n          echo "source_drift=false" >> "$GITHUB_OUTPUT"\n\n          # Same-session stale-run guard. Artifact-only/options commits are harmless;\n          # generation/input changes mean this run was built from obsolete logic.\n          git fetch --depth=1 origin main\n          if [[ -n "${V38_BUILD_SOURCE_SHA:-}" ]] && \\\n             ! git diff --quiet "$V38_BUILD_SOURCE_SHA" origin/main -- \\\n               build_dashboard.py .github/workflows/dashboard.yml \\\n               scripts/export_public_site.py scripts/privacy_audit.py \\\n               sar_state.txt equity.csv; then\n            echo "::warning::source drift after build; skip persistence/public publish for stale same-session run"\n            echo "source_drift=true" >> "$GITHUB_OUTPUT"\n            echo "source_sha=$V38_BUILD_SOURCE_SHA" >> "$GITHUB_OUTPUT"\n            exit 0\n          fi\n\n          # --- なぜrebaseをやめたか -------------------------------------------\n'''
if 'source drift after build; skip persistence/public publish' not in y:
    if y.count(persist_anchor) != 1:
        raise SystemExit(f'persist anchor count={y.count(persist_anchor)}')
    y = y.replace(persist_anchor, persist_new, 1)

repls = [
    ("      - name: Audit public privacy boundary\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Audit public privacy boundary\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
    ("      - name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Export allowlisted public site\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
    ("      - name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true'",
     "      - name: Publish clean public mirror\n        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"),
]
for old, new in repls:
    if new not in y:
        if old not in y:
            raise SystemExit('downstream stale-guard anchor missing: ' + old.splitlines()[0])
        y = y.replace(old, new, 1)

# If the explicit failure reporter exists, do not report a deliberate stale-source skip as a publish failure.
old_fail = "if: steps.build.outputs.skipped != 'true' && steps.publish.outcome == 'failure'"
new_fail = "if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true' && steps.publish.outcome == 'failure'"
if old_fail in y and new_fail not in y:
    y = y.replace(old_fail, new_fail, 1)

wf.write_text(y, encoding='utf-8')

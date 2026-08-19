#!/usr/bin/env python3
from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# 1) VWAP near: observation/display filter only.
# ADR20 = ordinary 20-day mean (High-Low)/Close.
# threshold = min(5%, max(2%, 0.5 * ADR20)).
# Touch/support/reclaim are intentionally unchanged.
# If near later affects Core12, entry eligibility or sizing, validate before use.
# -----------------------------------------------------------------------------
build_path = Path("build_dashboard.py")
s = build_path.read_text(encoding="utf-8")
near_marker = "_near_threshold = min(0.05, max(0.02, 0.5 * _adr20))"
if near_marker not in s:
    old = "    near = bool(np.isfinite(dist) and abs(dist) <= 0.02)\n"
    new = (
        "    # Observation-only near zone. ADR20 = ordinary 20-day average range%.\n"
        "    # Keep touch/support/reclaim unchanged. If near later affects Core12 ranking,\n"
        "    # entry eligibility or position sizing, validate it before promotion.\n"
        "    try:\n"
        "        _adr20 = (((aligned[\"h\"] - aligned[\"l\"]) / aligned[\"c\"].replace(0, np.nan))\n"
        "                  .replace([np.inf, -np.inf], np.nan).dropna().tail(20).mean())\n"
        "        _adr20 = float(_adr20) if np.isfinite(_adr20) else 0.0\n"
        "    except Exception:\n"
        "        _adr20 = 0.0\n"
        "    _near_threshold = min(0.05, max(0.02, 0.5 * _adr20))\n"
        "    near = bool(np.isfinite(dist) and abs(dist) <= _near_threshold)\n"
    )
    s = replace_once(s, old, new, "VWAP near")
build_path.write_text(s, encoding="utf-8")


# -----------------------------------------------------------------------------
# 2) Same-session stale-source guard.
# Sync main before build, capture the exact build source SHA, and before persistence
# compare only generation logic / explicit inputs. Unrelated artifact/options commits
# must not invalidate the run.
# -----------------------------------------------------------------------------
workflow_path = Path(".github/workflows/dashboard.yml")
y = workflow_path.read_text(encoding="utf-8")

source_marker = "V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)"
if source_marker not in y:
    setup = (
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "\n"
    )
    sync = (
        "      - name: Sync latest main before build\n"
        "        shell: bash\n"
        "        run: |\n"
        "          set -euo pipefail\n"
        "          git fetch --depth=1 origin main\n"
        "          git reset --hard origin/main\n"
        "          echo \"V38_BUILD_SOURCE_SHA=$(git rev-parse HEAD)\" >> \"$GITHUB_ENV\"\n"
        "\n"
    )
    y = replace_once(y, setup, sync + setup, "dashboard setup")


drift_marker = "source drift after build; skip persistence/public publish for stale same-session run"
if drift_marker not in y:
    old_email = (
        "          git config user.name \"github-actions[bot]\"\n"
        "          git config user.email " + chr(92) + "\n"
        "            \"41898282+github-actions[bot]@users.noreply.github.com\"\n"
        "\n"
        "          # --- なぜrebaseをやめたか -------------------------------------------\n"
    )
    normalized_email = (
        "          git config user.name \"github-actions[bot]\"\n"
        "          git config user.email \"41898282+github-actions[bot]@users.noreply.github.com\"\n"
        "\n"
        "          # --- なぜrebaseをやめたか -------------------------------------------\n"
    )
    guarded = (
        "          git config user.name \"github-actions[bot]\"\n"
        "          git config user.email \"41898282+github-actions[bot]@users.noreply.github.com\"\n"
        "          echo \"source_drift=false\" >> \"$GITHUB_OUTPUT\"\n"
        "\n"
        "          # Same-session stale-source guard. Artifact/options commits are harmless;\n"
        "          # generation logic and explicit dashboard inputs are not.\n"
        "          git fetch --depth=1 origin main\n"
        "          if [[ -n \"${V38_BUILD_SOURCE_SHA:-}\" ]] && ! git diff --quiet \"$V38_BUILD_SOURCE_SHA\" origin/main -- build_dashboard.py .github/workflows/dashboard.yml requirements.txt scripts/export_public_site.py scripts/privacy_audit.py sar_state.txt equity.csv; then\n"
        "            echo \"::warning::source drift after build; skip persistence/public publish for stale same-session run\"\n"
        "            echo \"source_drift=true\" >> \"$GITHUB_OUTPUT\"\n"
        "            echo \"source_sha=$V38_BUILD_SOURCE_SHA\" >> \"$GITHUB_OUTPUT\"\n"
        "            exit 0\n"
        "          fi\n"
        "\n"
        "          # --- なぜrebaseをやめたか -------------------------------------------\n"
    )
    if old_email in y:
        y = replace_once(y, old_email, guarded, "dashboard persist")
    elif normalized_email in y:
        y = replace_once(y, normalized_email, guarded, "dashboard persist normalized")
    else:
        raise SystemExit("dashboard persist anchor missing")


for step_name in (
    "Audit public privacy boundary",
    "Export allowlisted public site",
    "Publish clean public mirror",
):
    old = (
        f"      - name: {step_name}\n"
        "        if: steps.build.outputs.skipped != 'true'"
    )
    new = (
        f"      - name: {step_name}\n"
        "        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift != 'true'"
    )
    if new not in y:
        y = replace_once(y, old, new, f"{step_name} condition")

old_failure = "if: steps.build.outputs.skipped != 'true' && steps.publish.outcome == 'failure'"
new_failure = (
    "if: steps.build.outputs.skipped != 'true' && "
    "steps.persist.outputs.source_drift != 'true' && steps.publish.outcome == 'failure'"
)
if new_failure not in y:
    y = replace_once(y, old_failure, new_failure, "publish failure condition")

if "name: Report skipped stale-source run" not in y:
    anchor = "      - name: Audit public privacy boundary\n"
    report = (
        "      - name: Report skipped stale-source run\n"
        "        if: steps.build.outputs.skipped != 'true' && steps.persist.outputs.source_drift == 'true'\n"
        "        shell: bash\n"
        "        run: |\n"
        "          {\n"
        "            echo \"### Dashboard build\"\n"
        "            echo \"- Status: skipped after build\"\n"
        "            echo \"- Reason: generation/input source changed while this run was executing\"\n"
        "            echo \"- Safety: stale same-session artifacts were not persisted or published\"\n"
        "          } >> \"$GITHUB_STEP_SUMMARY\"\n"
        "\n"
    )
    y = replace_once(y, anchor, report + anchor, "stale-source report")

workflow_path.write_text(y, encoding="utf-8")

print("PATCH_OK")
print("VWAP_NEAR_ADAPTIVE", near_marker in s)
print("STALE_SOURCE_GUARD", source_marker in y and drift_marker in y)

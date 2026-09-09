#!/usr/bin/env python3
"""Confirm that the locked upstream GitHub Pages deployment completed.

If GitHub Pages cancels a deployment because a newer commit superseded it,
follow the newer commit only when the repository still validates for the
original expected session. Any real failure or session drift remains fail-closed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any


PAGES_WORKFLOW_NAME = "pages build and deployment"


class ConfirmError(RuntimeError):
    pass


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def _gh_json(repo: str, sha: str) -> list[dict[str, Any]]:
    url = f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100"
    cp = _run(["gh", "api", url])
    payload = json.loads(cp.stdout)
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        raise ConfirmError(f"unexpected GitHub Actions response for sha={sha}")
    return [r for r in runs if isinstance(r, dict)]


def latest_pages_run(repo: str, sha: str) -> dict[str, Any] | None:
    for run in _gh_json(repo, sha):
        if run.get("name") == PAGES_WORKFLOW_NAME:
            return run
    return None


def refresh_main_and_validate(expected_session: str) -> str:
    _run(["git", "fetch", "--depth=1", "origin", "main"])
    cp = _run(["git", "rev-parse", "origin/main"])
    sha = cp.stdout.strip()
    if not sha:
        raise ConfirmError("origin/main SHA is empty")

    _run(["git", "reset", "--hard", "origin/main"])
    _run(
        [
            sys.executable,
            "tools/validate_options_release.py",
            "--mode",
            "upstream",
            "--expected-session",
            expected_session,
        ]
    )
    return sha


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str = ""


def decide(
    *,
    status: str,
    conclusion: str,
    current_sha: str,
    latest_sha: str | None = None,
    same_session_ok: bool | None = None,
    supersedes: int = 0,
    max_supersedes: int = 8,
) -> Decision:
    if status != "completed":
        return Decision("wait")

    if conclusion == "success":
        return Decision("pass")

    if conclusion != "cancelled":
        return Decision("fail", f"Pages deployment concluded {conclusion or 'unknown'}")

    if not latest_sha or latest_sha == current_sha:
        return Decision("fail", "Pages deployment was cancelled without a newer main SHA")

    if same_session_ok is not True:
        return Decision("fail", "newer main SHA does not validate for the locked session")

    if supersedes >= max_supersedes:
        return Decision("fail", f"Pages deployment superseded more than {max_supersedes} times")

    return Decision("follow", "cancelled deployment safely superseded by same-session main")


def confirm(
    *,
    repo: str,
    published_sha: str,
    expected_session: str,
    attempts: int = 180,
    sleep_seconds: float = 5.0,
    max_supersedes: int = 8,
) -> str:
    current_sha = published_sha
    supersedes = 0

    for _ in range(attempts):
        run = latest_pages_run(repo, current_sha)
        if run is None:
            time.sleep(sleep_seconds)
            continue

        run_id = run.get("id")
        status = str(run.get("status") or "")
        conclusion = str(run.get("conclusion") or "")
        print(
            f"Upstream Pages run_id={run_id} sha={current_sha} "
            f"status={status} conclusion={conclusion or '-'}",
            flush=True,
        )

        initial = decide(
            status=status,
            conclusion=conclusion,
            current_sha=current_sha,
            supersedes=supersedes,
            max_supersedes=max_supersedes,
        )
        if initial.action == "wait":
            time.sleep(sleep_seconds)
            continue
        if initial.action == "pass":
            return current_sha
        if conclusion != "cancelled":
            raise ConfirmError(initial.reason)

        try:
            latest_sha = refresh_main_and_validate(expected_session)
            same_session_ok = True
        except subprocess.CalledProcessError as exc:
            raise ConfirmError(
                "cancelled Pages deployment was followed by main that failed "
                f"same-session upstream validation for {expected_session}"
            ) from exc

        final = decide(
            status=status,
            conclusion=conclusion,
            current_sha=current_sha,
            latest_sha=latest_sha,
            same_session_ok=same_session_ok,
            supersedes=supersedes,
            max_supersedes=max_supersedes,
        )
        if final.action == "follow":
            supersedes += 1
            print(
                f"Pages deployment superseded safely: {current_sha} -> {latest_sha} "
                f"(session={expected_session}, count={supersedes})",
                flush=True,
            )
            current_sha = latest_sha
            continue
        raise ConfirmError(final.reason)

    raise ConfirmError(
        f"Pages deployment did not complete after {attempts} polls "
        f"(last_sha={current_sha}, session={expected_session})"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--published-sha", required=True)
    parser.add_argument("--expected-session", required=True)
    parser.add_argument("--attempts", type=int, default=180)
    parser.add_argument("--sleep-seconds", type=float, default=5.0)
    parser.add_argument("--max-supersedes", type=int, default=8)
    args = parser.parse_args()

    try:
        final_sha = confirm(
            repo=args.repo,
            published_sha=args.published_sha,
            expected_session=args.expected_session,
            attempts=args.attempts,
            sleep_seconds=args.sleep_seconds,
            max_supersedes=args.max_supersedes,
        )
    except (ConfirmError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"::error::UPSTREAM_PAGES_CONFIRM_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        f"UPSTREAM_PAGES_DEPLOYED session={args.expected_session} sha={final_sha}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_NAMES = (
    "rsi-reset-focused-robust-audit",
    "rsi-reset-portfolio-construction-audit",
    "rsi-strong-stock-threshold-interaction-audit",
    "market-wide-rs189-rsi-reset-audit",
    "rsi30-mc-nqsar-audit",
    "rsi30-vix-sequence-audit",
    "tqqq-stage56-mandate-fx-tax",
)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward GitHub bearer auth to Actions artifact storage hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = (urlparse(req.full_url).hostname or "").lower()
        new_host = (urlparse(newurl).hostname or "").lower()
        if old_host != new_host:
            redirected.remove_header("Authorization")
            redirected.remove_header("X-GitHub-Api-Version")
        return redirected


OPENER = urllib.request.build_opener(SafeRedirectHandler())


def api_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "v38-rulebook-audit",
        },
    )
    with OPENER.open(req, timeout=60) as response:
        return json.load(response)


def download(url: str, token: str, destination: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "v38-rulebook-audit",
        },
    )
    with OPENER.open(req, timeout=180) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", action="append", dest="names")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    wanted = tuple(args.names or DEFAULT_NAMES)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    found: dict[str, dict] = {}
    page = 1
    while page <= 20 and len(found) < len(wanted):
        payload = api_json(
            f"https://api.github.com/repos/{args.repo}/actions/artifacts?per_page=100&page={page}",
            token,
        )
        artifacts = payload.get("artifacts", [])
        if not artifacts:
            break
        for artifact in artifacts:
            name = artifact.get("name")
            if name in wanted and not artifact.get("expired") and name not in found:
                found[name] = artifact
        page += 1

    missing = [name for name in wanted if name not in found]
    if missing:
        raise RuntimeError(f"required non-expired artifacts not found: {missing}")

    manifest = {"repository": args.repo, "artifacts": {}}
    for name in wanted:
        artifact = found[name]
        target = output / name
        target.mkdir(parents=True, exist_ok=True)
        archive = output / f"{name}.zip"
        download(str(artifact["archive_download_url"]), token, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        archive.unlink()
        files = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
        manifest["artifacts"][name] = {
            "artifact_id": artifact.get("id"),
            "workflow_run_id": (artifact.get("workflow_run") or {}).get("id"),
            "created_at": artifact.get("created_at"),
            "updated_at": artifact.get("updated_at"),
            "files": files,
        }
        print(f"downloaded {name}: {len(files)} files", flush=True)

    (output / "artifact_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

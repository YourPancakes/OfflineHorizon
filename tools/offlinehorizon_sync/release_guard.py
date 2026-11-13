#!/usr/bin/env python3
"""Plan idempotent release dispatches after source synchronization.

Read-only GitHub API checks. A workflow performs any actual dispatch.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REQUIRED = {
    "offline-game.yml": {
        "horizon-linux-x86_64.tar.gz",
        "horizon-windows-x64.zip",
        "horizon-macos-arm64.zip",
        "horizon-macos-x64.zip",
        "horizon-server-linux-x86_64.tar.gz",
        "horizon-windows-arm64.zip",
        "horizon-launcher-linux-x86_64.tar.gz",
        "horizon-launcher-windows-x64.zip",
        "horizon-launcher-windows-arm64.zip",
        "horizon-launcher-macos-arm64.zip",
        "horizon-launcher-macos-x64.zip",
        "horizon-launcher-setup.exe",
        "horizon-launcher-setup-arm64.exe",
        "horizon-launcher-macos-arm64.dmg",
        "horizon-launcher-macos-x64.dmg",
        "SHA256SUMS",
    },
}
PREFIX = {"offline-game.yml": "v0.2."}
SHA = re.compile(r"^[a-f0-9]{40}$")
MAX_FAILURES = 3


class ReleaseGuardError(RuntimeError):
    pass


def api(path: str, token: str) -> dict | list:
    req = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "OfflineHorizon-release-guard",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ReleaseGuardError("GitHub release status unavailable") from exc


def collected(path: str, token: str, key: str) -> list:
    """Read complete paginated status; fail closed if too many pages."""
    values: list = []
    for page in range(1, 11):
        joiner = "&" if "?" in path else "?"
        payload = api(f"{path}{joiner}per_page=100&page={page}", token)
        items = payload.get(key) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ReleaseGuardError(f"Unexpected GitHub response for {key}")
        values.extend(items)
        if len(items) < 100:
            return values
    raise ReleaseGuardError("GitHub results exceed 1000 entries; refusing to guess")


def plan(kind: str, head: str, releases: list, runs: list) -> str:
    if kind not in REQUIRED or not SHA.fullmatch(head):
        raise ReleaseGuardError("Invalid workflow or source commit")
    previous = [
        release for release in releases
        if (release.get("target_commitish") == head
            or f"Build commit: {head}" in (release.get("body") or "").splitlines())
        and release.get("tag_name", "").startswith(PREFIX[kind])
        and not release.get("draft")
    ]
    if previous:
        for release in previous:
            assets = {
                item.get("name") for item in release.get("assets", [])
                if item.get("state") == "uploaded" and item.get("size", 0) > 0
            }
            if REQUIRED[kind].issubset(assets):
                return "published"
        return "incomplete_release"
    matching = [
        run for run in runs
        if run.get("head_sha") == head
        and run.get("head_branch") == "main"
        and run.get("event") in ("push", "workflow_dispatch")
    ]
    if any(run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested")
           for run in matching):
        return "running"
    if any(run.get("conclusion") == "success" for run in matching):
        return "successful_run_without_release"
    failures = sum(max(1, int(run.get("run_attempt") or 1))
                   for run in matching if run.get("status") == "completed")
    if failures >= MAX_FAILURES:
        return "retry_limit"
    return "dispatch"


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or repo != "YourPancakes/OfflineHorizon":
        raise ReleaseGuardError("Expected authenticated OfflineHorizon repository")
    ref = api(f"repos/{repo}/git/ref/heads/main", token)
    head = ref["object"]["sha"]
    if not SHA.fullmatch(head):
        raise ReleaseGuardError("GitHub main branch SHA invalid")
    releases = collected(f"repos/{repo}/releases", token, "releases")
    decisions = {}
    for workflow in REQUIRED:
        path = f"repos/{repo}/actions/workflows/{urllib.parse.quote(workflow)}/runs?head_sha={head}"
        runs = collected(path, token, "workflow_runs")
        decisions[workflow] = plan(workflow, head, releases, runs)
    print(json.dumps({"sha": head, "decisions": decisions}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseGuardError, KeyError, TypeError, IndexError) as error:
        print(f"release guard failed closed: {error}", file=sys.stderr)
        raise SystemExit(1)

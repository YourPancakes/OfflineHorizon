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


def _tree_entries(repo: str, tree: str, token: str) -> dict:
    """Read a complete, immutable Git tree; reject invalid/truncated results."""
    if not isinstance(tree, str) or not SHA.fullmatch(tree):
        raise ReleaseGuardError("Invalid Git tree SHA")
    payload = api(f"repos/{repo}/git/trees/{tree}", token)
    if not isinstance(payload, dict) or payload.get("truncated"):
        raise ReleaseGuardError("Cannot verify complete Git tree")
    rows = payload.get("tree")
    if not isinstance(rows, list):
        raise ReleaseGuardError("Git tree entries unavailable")
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ReleaseGuardError("Invalid Git tree entry")
        entry_sha = row.get("sha")
        if row["path"] in out or not isinstance(entry_sha, str) or not SHA.fullmatch(entry_sha):
            raise ReleaseGuardError("Duplicate or invalid Git tree entry")
        out[row["path"]] = (row.get("mode"), row.get("type"), entry_sha)
    return out


def _commit_entries(repo: str, sha: str, token: str) -> dict:
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ReleaseGuardError("Invalid source commit SHA")
    commit = api(f"repos/{repo}/git/commits/{sha}", token)
    tree = commit.get("tree") if isinstance(commit, dict) else None
    if not isinstance(tree, dict):
        raise ReleaseGuardError("Source commit tree unavailable")
    return _tree_entries(repo, tree.get("sha"), token)


def same_buildable_sources(repo: str, built: str, head: str, token: str) -> bool:
    """Exclude only CI workflows and the source-sync controller from build inputs."""
    if built == head:
        return True
    old, current = _commit_entries(repo, built, token), _commit_entries(repo, head, token)
    def main_entries(entries):
        return {p: e for p, e in entries.items() if p not in (".github", "tools")}
    if main_entries(old) != main_entries(current):
        return False
    original_tools, current_tools = old.get("tools"), current.get("tools")
    if original_tools == current_tools:
        return True
    if not original_tools or not current_tools:
        return False
    before = _tree_entries(repo, original_tools[2], token)
    after = _tree_entries(repo, current_tools[2], token)
    def build_tools(entries):
        return {p: e for p, e in entries.items() if p != "offlinehorizon_sync"}
    return build_tools(before) == build_tools(after)


def equivalent_published_release(head: str, releases: list, token: str) -> bool:
    """Avoid a new release when the same exact build inputs already shipped."""
    required = REQUIRED["offline-game.yml"]
    repo = "YourPancakes/OfflineHorizon"
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if not str(release.get("tag_name", "")).startswith(PREFIX["offline-game.yml"]):
            continue
        assets = {
            a["name"] for a in release.get("assets", [])
            if isinstance(a, dict) and isinstance(a.get("name"), str)
            and a.get("state") == "uploaded" and isinstance(a.get("size"), int)
            and a["size"] > 0 and isinstance(a.get("digest"), str)
            and re.fullmatch(r"sha256:[a-f0-9]{64}", a["digest"])
        }
        if not required.issubset(assets):
            continue
        found = re.search(r"Build commit:\s*([a-f0-9]{40})", release.get("body") or "")
        source = found.group(1) if found else release.get("target_commitish")
        if not isinstance(source, str) or not SHA.fullmatch(source):
            continue
        if same_buildable_sources(repo, source, head, token):
            return True
    return False


def main() -> int:
    args = sys.argv[1:]
    if args not in ([], ["--equivalent-release"]):
        raise ReleaseGuardError("Unknown release guard option")
    token = os.environ.get("GH_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or repo != "YourPancakes/OfflineHorizon":
        raise ReleaseGuardError("Expected authenticated OfflineHorizon repository")
    ref = api(f"repos/{repo}/git/ref/heads/main", token)
    head = ref["object"]["sha"]
    if not SHA.fullmatch(head):
        raise ReleaseGuardError("GitHub main branch SHA invalid")
    releases = collected(f"repos/{repo}/releases", token, "releases")
    equivalent = equivalent_published_release(head, releases, token)
    if args == ["--equivalent-release"]:
        print("true" if equivalent else "false")
        return 0
    decisions = {}
    for workflow in REQUIRED:
        path = f"repos/{repo}/actions/workflows/{urllib.parse.quote(workflow)}/runs?head_sha={head}"
        runs = collected(path, token, "workflow_runs")
        decisions[workflow] = (
            "published" if equivalent else plan(workflow, head, releases, runs)
        )
    print(json.dumps({"sha": head, "decisions": decisions}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseGuardError, KeyError, TypeError, IndexError) as error:
        print(f"release guard failed closed: {error}", file=sys.stderr)
        raise SystemExit(1)

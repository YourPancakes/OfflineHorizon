#!/usr/bin/env python3
"""Low-memory, fail-closed upstream source sync for an independent OfflineHorizon fork."""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TRACKER = ".offline-horizon-upstream-sha"
HERE = Path(__file__).resolve().parent
DEFAULT_UPSTREAM = "https://github.com/horizon-rust/horizon.git"
DEFAULT_FORK = "https://github.com/YourPancakes/OfflineHorizon.git"
SHA_RE = re.compile(r"^[a-f0-9]{40}$")


class SyncError(RuntimeError):
    pass


def sync_token() -> str:
    """Read the protected GitHub token without putting credentials in Compose."""
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    path = os.environ.get("TOKEN_FILE", "")
    if not path:
        return ""
    secret = Path(path)
    if secret.is_symlink():
        raise SyncError("TOKEN_FILE must not be a symlink")
    try:
        mode = secret.stat().st_mode
    except FileNotFoundError:
        return ""
    if mode & 0o077 or not secret.is_file():
        raise SyncError("TOKEN_FILE must be a regular file with permission 0600 or stricter")
    return secret.read_text(encoding="utf-8").strip()


def command(argv: list[str], *, cwd: Path | None = None, env: dict | None = None,
            timeout: int = 900) -> str:
    result = subprocess.run(
        argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout, check=False,
    )
    if result.returncode:
        tail = (result.stderr or result.stdout)[-4500:]
        raise SyncError(f"{argv[0]} {argv[1:4]} failed ({result.returncode}): {tail}")
    return result.stdout.strip()


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    return command(["git", "-c", "safe.directory=*", "-C", str(repo), *args], env=env)


def auth_env(token: str) -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        # Credentials never appear in remote URLs, .git/config, stderr, or command arguments.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
    return env


def manifest_paths(path: Path) -> list[str]:
    paths = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        p = PurePosixPath(line)
        if p.is_absolute() or ".." in p.parts or str(p) != line:
            raise SyncError(f"Invalid manifest path: {line!r}")
        paths.append(line)
    if not paths or len(paths) != len(set(paths)):
        raise SyncError("Manifest empty or contains duplicate paths")
    return paths


def git_tree_files(repo: Path, rev: str) -> dict[str, tuple[str, str]]:
    """Read exact file modes and blob hashes from an immutable Git tree."""
    out: dict[str, tuple[str, str]] = {}
    for row in git(repo, "ls-tree", "-r", "-z", rev).split("\0"):
        if not row:
            continue
        meta, sep, path = row.partition("\t")
        parts = meta.split()
        if not sep or not path or len(parts) != 3 or not SHA_RE.fullmatch(parts[2]):
            raise SyncError("Invalid Git tree entry during synchronization")
        if path in out:
            raise SyncError("Duplicate Git tree path during synchronization")
        out[path] = (parts[0], parts[2])
    return out


def upstream_sha(url: str) -> str:
    output = command(["git", "ls-remote", url, "refs/heads/main"], timeout=45)
    parts = output.split()
    if len(parts) != 2 or parts[1] != "refs/heads/main" or not SHA_RE.fullmatch(parts[0]):
        raise SyncError(f"Unexpected upstream main ref: {output[:200]!r}")
    return parts[0]


def github_api(path: str, token: str) -> dict:
    """Read GitHub Actions status; an API failure must never approve a source update."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OfflineHorizon-upstream-CI-gate",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"https://api.github.com/{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise SyncError(f"Upstream CI status unavailable (GitHub HTTP {error.code})") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise SyncError(f"Upstream CI status unavailable ({type(error).__name__})") from error
    if not isinstance(data, dict):
        raise SyncError("Unexpected GitHub Actions API response")
    return data


def upstream_ci_ready(sha: str, token: str) -> tuple[bool, str]:
    """Require all mandatory upstream main checks to pass on this *exact* SHA.

    'checks' runs verify and launcher tests; 'parity-main' runs vanilla parity.
    Workflow success alone is insufficient: skipped jobs must not count as green.
    """
    repo = "horizon-rust/horizon"
    for workflow, required_jobs in (
        ("ci.yml", ("verify", "launcher")),
        ("parity-main.yml", ("parity-main",)),
    ):
        query = urllib.parse.urlencode({
            "branch": "main", "event": "push", "head_sha": sha, "per_page": 100,
        })
        payload = github_api(f"repos/{repo}/actions/workflows/{workflow}/runs?{query}", token)
        runs = [
            run for run in payload.get("workflow_runs", [])
            if isinstance(run, dict) and run.get("head_sha") == sha
            and run.get("head_branch") == "main" and run.get("event") == "push"
        ]
        if not runs:
            return False, f"{workflow}: no main/push CI run for {sha[:12]}"
        run = max(runs, key=lambda r: (r.get("created_at", ""), r.get("run_attempt", 0),
                                       r.get("id", 0)))
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            return False, (f"{workflow}: {run.get('status') or 'unknown'} / "
                           f"{run.get('conclusion') or 'pending'}")
        run_id = run.get("id")
        if not isinstance(run_id, int) or run_id <= 0:
            raise SyncError(f"{workflow}: invalid run ID")
        jobs_payload = github_api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", token)
        jobs = jobs_payload.get("jobs")
        if not isinstance(jobs, list) or not isinstance(jobs_payload.get("total_count"), int):
            raise SyncError(f"{workflow}: invalid jobs response")
        if jobs_payload["total_count"] > len(jobs):
            return False, f"{workflow}: cannot verify every CI job (pagination)"
        for expected in required_jobs:
            matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == expected]
            if len(matches) != 1:
                return False, f"{workflow}: required job {expected} missing or ambiguous"
            job = matches[0]
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                return False, (f"{workflow}: job {expected}: {job.get('status') or 'unknown'} / "
                               f"{job.get('conclusion') or 'pending'}")
    return True, "checks/verify, checks/launcher and parity-main passed"


def latest_green_upstream_sha(token: str) -> tuple[str | None, str]:
    """Find the newest push on main with BOTH CI suites green, not merely HEAD.

    Query only successful parity-main runs, rather than scanning thousands
    of cancelled or pending runs. For each candidate SHA, also require a
    fully green checks workflow before it can be selected.
    """
    repo = "horizon-rust/horizon"
    pages = max(1, min(10, int(os.environ.get("UPSTREAM_CI_SCAN_PAGES", "5"))))
    seen: set[str] = set()
    examined = 0
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode({
            "branch": "main", "event": "push", "status": "success",
            "per_page": 100, "page": page,
        })
        response = github_api(
            f"repos/{repo}/actions/workflows/parity-main.yml/runs?{query}", token
        )
        runs = response.get("workflow_runs")
        if not isinstance(runs, list):
            raise SyncError("GitHub parity-main history has no workflow_runs list")
        # GitHub lists recent workflow runs first. Re-sort explicitly, so a
        # delayed completion cannot make an old green commit look newer.
        ordered = sorted(
            runs, key=lambda r: (r.get("created_at", ""), r.get("id", 0))
            if isinstance(r, dict) else ("", 0), reverse=True,
        )
        for run in ordered:
            if not isinstance(run, dict):
                raise SyncError("Invalid parity-main run in GitHub response")
            sha = run.get("head_sha")
            if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
                continue
            if run.get("head_branch") != "main" or run.get("event") != "push":
                continue
            if sha in seen:
                continue
            seen.add(sha)
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                continue
            examined += 1
            # Bound secondary API requests if many parity runs passed but
            # their other required checks failed. Retry next cycle safely.
            if examined > 15:
                return None, "More than 15 green-parity candidates need verification"
            approved, reason = upstream_ci_ready(sha, token)
            if approved:
                return sha, reason
        if len(runs) < 100:
            break
    return None, f"No fully green upstream commit found among {len(seen)} successful parity-main runs"


def upstream_is_descendant(older: str, newer: str, token: str) -> bool:
    """Prevent falling back to an older green SHA or adopting a divergent branch."""
    if older == newer:
        return True
    if not SHA_RE.fullmatch(older) or not SHA_RE.fullmatch(newer):
        raise SyncError("Invalid SHA in upstream ancestry check")
    response = github_api(
        f"repos/horizon-rust/horizon/compare/{older}...{newer}?per_page=1", token
    )
    status = response.get("status")
    if status not in ("ahead", "identical", "behind", "diverged"):
        raise SyncError("GitHub could not establish upstream commit ancestry")
    return status in ("ahead", "identical")


def safe_json_write(path: Path, data: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def merge_addresses(base: dict, fork: dict, upstream: dict) -> dict:
    """Three-way merge of the address registry; preserve upstream removals and fork additions."""
    missing = object()

    def merge_value(b, f, u):
        if f == b:
            return u
        if u == b or f == u:
            return f
        raise SyncError("Conflicting concurrent change in tools/addresses.json")

    merged = dict(upstream)
    for key in set(base) | set(fork) | set(upstream):
        b, f, u = base.get(key, missing), fork.get(key, missing), upstream.get(key, missing)
        if all(isinstance(v, dict) for v in (b, f, u)):
            result = dict(u)
            for entry in set(b) | set(f) | set(u):
                value = merge_value(
                    b.get(entry, missing), f.get(entry, missing), u.get(entry, missing)
                )
                if value is missing:
                    result.pop(entry, None)
                else:
                    result[entry] = value
            merged[key] = result
        elif all(isinstance(v, list) for v in (b, f, u)):
            # Entries are path+host strings, not ordered instructions.
            if not all(isinstance(x, str) for seq in (b, f, u) for x in seq):
                raise SyncError(f"Address registry list {key!r} is no longer a string list")
            bset, fset, uset = set(b), set(f), set(u)
            merged[key] = sorted((uset | (fset - bset)) - (bset - fset))
        else:
            result = merge_value(b, f, u)
            if result is missing:
                merged.pop(key, None)
            else:
                merged[key] = result
    return merged


def run_once(*, dry_run: bool = True, source: Path | None = None,
             work_root: Path | None = None, upstream: str | None = None,
             fork: str | None = None, base_sha: str | None = None,
             manifest: Path | None = None, force_sha: str | None = None) -> dict:
    source = source or Path(os.environ.get("SOURCE_PATH", str(HERE.parent / "Offline-Horizon")))
    work_root = work_root or Path(os.environ.get("WORK_ROOT", str(HERE / "work")))
    upstream = upstream or os.environ.get("UPSTREAM_URL", DEFAULT_UPSTREAM)
    fork = fork or os.environ.get("FORK_URL", DEFAULT_FORK)
    base_sha = base_sha or os.environ.get("BASE_SHA", "b880384691b88d317553067109d28e785990bda3")
    manifest = manifest or HERE / "manifest.txt"
    token = sync_token()
    if not dry_run and not token:
        raise SyncError("Refusing to publish: no authorized GitHub token configured")
    if not SHA_RE.fullmatch(base_sha):
        raise SyncError("BASE_SHA must be a full commit SHA")
    paths = manifest_paths(manifest)
    if not source.is_dir():
        raise SyncError(f"Local source checkout not found: {source}")

    work_root.mkdir(parents=True, exist_ok=True)
    with (work_root / ".sync.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        head = upstream_sha(upstream) if not force_sha else force_sha
        if not SHA_RE.fullmatch(head):
            raise SyncError("Invalid upstream main commit SHA")
        if force_sha:
            # Explicit SHA is for controlled manual tests; it too must be green.
            latest, reason = force_sha, ""
            approved, reason = upstream_ci_ready(latest, token)
            if not approved:
                return {"result": "waiting_upstream_ci", "upstream": latest,
                        "reason": reason, "pushed": False}
        else:
            latest, reason = latest_green_upstream_sha(token)
            if latest is None:
                return {"result": "waiting_upstream_ci", "upstream_head": head,
                        "reason": reason, "pushed": False}
            # Only a commit in the present main history is eligible.
            if not upstream_is_descendant(latest, head, token):
                return {"result": "upstream_history_changed", "upstream": latest,
                        "upstream_head": head, "pushed": False}
        # The fork overlay is based on BASE_SHA. Never transplant it onto
        # a successful but OLDER upstream commit: that is a downgrade with
        # unrelated API changes and can generate hundreds of merge conflicts.
        if not upstream_is_descendant(base_sha, latest, token):
            return {"result": "waiting_green_after_base",
                    "upstream_head": head, "last_green": latest,
                    "base": base_sha, "pushed": False}
        dry_state = work_root / ".last-dry-run.json"
        if dry_run and not force_sha and dry_state.is_file():
            previous = json.loads(dry_state.read_text(encoding="utf-8"))
            # Previous sync versions cached unverified main HEADs. Do not treat
            # those values as green baselines or block a historical green SHA.
            dry_sha = previous.get("upstream") if previous.get("selection") == "green" else None
            if dry_sha == latest:
                return {"result": "unchanged", "upstream": latest,
                        "upstream_head": head, "pushed": False}
            if isinstance(dry_sha, str) and SHA_RE.fullmatch(dry_sha):
                if not upstream_is_descendant(dry_sha, latest, token):
                    return {"result": "already_ahead", "upstream": latest,
                            "current": dry_sha, "pushed": False}
        staging = Path(tempfile.mkdtemp(prefix="sync-", dir=work_root))
        try:
            repo = staging / "fork"
            env = auth_env(token if not dry_run else "")
            if dry_run:
                command(["git", "-c", "safe.directory=*", "clone", "--quiet", "--no-local", str(source), str(repo)], env=env)
            else:
                command(["git", "clone", "--quiet", "--no-tags", "--single-branch",
                         "--branch", "main", "--filter=blob:none", fork, str(repo)], env=env)
            fork_head = git(repo, "rev-parse", "HEAD")
            fork_parent = fork_head
            old_sha = None
            try:
                old_sha = git(repo, "show", f"HEAD:{TRACKER}").strip()
            except SyncError:
                pass
            if old_sha and not SHA_RE.fullmatch(old_sha):
                raise SyncError("Fork's upstream marker is invalid")

            # Only the initial bootstrap needs the source checkout. Subsequent cycles use
            # the already-synchronized remote branch and keep its own Git history.
            if not dry_run and old_sha is None:
                source_head = git(source, "rev-parse", "HEAD")
                if source_head != fork_head:
                    git(repo, "fetch", "--quiet", "--no-tags", str(source),
                        "refs/heads/main", env=env)
                    if git(repo, "rev-parse", "FETCH_HEAD") != source_head:
                        raise SyncError("Local source main changed while being fetched")
                    # If GitHub received independent commits (e.g., by the connected
                    # GitHub app), use its current main as the parent and preserve
                    # the owner-reviewed overlay from the mounted checkout.
                    try:
                        git(repo, "merge-base", "--is-ancestor", fork_head, source_head)
                        fork_parent = source_head
                    except SyncError:
                        fork_parent = fork_head
            if old_sha == latest:
                return {"result": "unchanged", "upstream": latest,
                        "upstream_head": head, "pushed": False}
            if old_sha and not force_sha and not upstream_is_descendant(old_sha, latest, token):
                return {"result": "already_ahead", "upstream": latest,
                        "current": old_sha, "pushed": False}

            git(repo, "remote", "add", "upstream", upstream)
            # Fetch exactly two immutable snapshots, in ONE shallow operation.
            # Do not filter blobs: lazy blob downloads combined with a changing
            # shallow boundary caused Git's "shallow file has changed" failure.
            # This bounds network work instead of fetching all upstream history.
            snapshots = [latest, old_sha or base_sha]
            git(repo, "fetch", "--quiet", "--no-tags", "--depth=1",
                "upstream", *snapshots, env=env)
            for expected in snapshots:
                if git(repo, "cat-file", "-t", expected) != "commit":
                    raise SyncError("Fetched upstream commit is missing or invalid")
            patch = staging / "upstream.patch"

            if old_sha is None:
                # One-time adoption: take ALL official source files and apply ONLY reviewed
                # fork paths, including the current tracked working-tree edits.
                before = git(source, "status", "--porcelain")
                with patch.open("wb") as f:
                    cmd = ["git", "-c", "safe.directory=*", "-C", str(source),
                           "diff", "--binary", "--full-index", base_sha, "--", *paths]
                    proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=900)
                if proc.returncode:
                    raise SyncError("Cannot capture initial fork overlay: "
                                    + proc.stderr.decode(errors="replace")[-1800:])
                if before != git(source, "status", "--porcelain"):
                    raise SyncError("Local source changed while snapshotting; retry later")
                # The original base was fetched together with the green SHA.
                git(repo, "checkout", "--quiet", "--detach", latest, env=env)
                mode = "bootstrap"
            else:
                # Both snapshots are available from the combined fetch.
                # The fork is an independent snapshot; its non-owned files
                # need not match the recorded upstream tree byte-for-byte.
                # The reviewed manifest owns fork customizations. Converge
                # all other files to the exact green upstream snapshot.
                current_files = git_tree_files(repo, "HEAD")
                old_files = git_tree_files(repo, old_sha)
                new_files = git_tree_files(repo, latest)
                owned = set(paths)
                official_update = [
                    p for p in new_files
                    if p not in owned and new_files[p] != current_files.get(p)
                ]
                official_removal = [
                    p for p in current_files
                    if p not in owned and p in old_files and p not in new_files
                ]
                update_paths = sorted(set(official_update + official_removal))
                for start in range(0, len(update_paths), 100):
                    git(repo, "restore", f"--source={latest}", "--staged",
                        "--worktree", "--", *update_paths[start:start + 100], env=env)
                patch.write_bytes(b"")
                mode = "incremental"

            if patch.stat().st_size == 0 and mode == "bootstrap":
                raise SyncError("Initial fork overlay is empty; refusing to lose modifications")
            if mode == "bootstrap" and patch.stat().st_size:
                try:
                    git(repo, "apply", "--3way", "--whitespace=nowarn", str(patch), env=env)
                except SyncError:
                    # The first real bootstrap has two known, non-code conflicts:
                    # fork branding in README and the append-only address registry.
                    unmerged = {
                        line.split("\t")[-1] for line in git(repo, "ls-files", "-u").splitlines()
                        if "\t" in line
                    }
                    if mode != "bootstrap" or unmerged != {"README.md", "tools/addresses.json"}:
                        if unmerged:
                            raise SyncError(
                                "Unresolved upstream patch conflicts (nothing published): "
                                + ", ".join(sorted(unmerged))
                            ) from None
                        raise
                    shutil.copyfile(source / "README.md", repo / "README.md")
                    merged = merge_addresses(
                        json.loads(git(source, "show", f"{base_sha}:tools/addresses.json")),
                        json.loads((source / "tools" / "addresses.json").read_text(encoding="utf-8")),
                        json.loads(git(repo, "show", f"{latest}:tools/addresses.json")),
                    )
                    (repo / "tools" / "addresses.json").write_text(
                        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                    git(repo, "add", "--", "README.md", "tools/addresses.json", env=env)
            if mode == "bootstrap":
                # git diff does not include newly authored, as-yet-untracked files.
                # Add only explicitly reviewed regular files from the manifest.
                for relative in paths:
                    src = source / relative
                    if not src.is_file() or src.is_symlink():
                        continue
                    try:
                        git(source, "ls-files", "--error-unmatch", "--", relative)
                    except SyncError:
                        dst = repo / relative
                        if dst.exists():
                            raise SyncError(
                                f"Untracked fork overlay collides with upstream: {relative}"
                            )
                        if src.stat().st_size > 5_000_000:
                            raise SyncError(f"Untracked fork overlay too large: {relative}")
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(src, dst)
                if before != git(source, "status", "--porcelain"):
                    raise SyncError("Local source changed while copying extra patches")
            (repo / TRACKER).write_text(latest + "\n", encoding="ascii")

            # Minimal deterministic checks suitable for a 2 GB server; GitHub does all builds.
            for lang in ("ru", "fr", "pl", "hu"):
                json.loads((repo / "launcher" / "lang" / f"{lang}.json")
                           .read_text(encoding="utf-8"))
            backend = (repo / "launcher" / "src" / "backend.rs").read_text(encoding="utf-8")
            # The game Versions page must remain publicly reachable.
            # Only custom launcher releases belong to the private fork.
            if ('pub const REPO: &str = "horizon-rust/horizon"' not in backend
                    or 'pub const LAUNCHER_REPO: &str = "YourPancakes/OfflineHorizon"' not in backend):
                raise SyncError("Game releases must be public upstream; launcher releases use the fork")
            if not (repo / ".github" / "workflows" / "launcher.yml").is_file():
                raise SyncError("Cross-platform launcher workflow is missing")
            if not (repo / ".github" / "workflows" / "offline-game.yml").is_file():
                raise SyncError("GitHub-hosted game release workflow is missing")
            git(repo, "add", "--all", env=env)
            tree = git(repo, "write-tree", env=env)
            commit_env = dict(env, GIT_AUTHOR_NAME="OfflineHorizon sync",
                              GIT_AUTHOR_EMAIL="sync@users.noreply.github.com",
                              GIT_COMMITTER_NAME="OfflineHorizon sync",
                              GIT_COMMITTER_EMAIL="sync@users.noreply.github.com")
            commit = git(repo, "commit-tree", tree, "-p", fork_parent,
                         "-m", f"sync: upstream {latest[:12]} (keep OfflineHorizon changes)",
                         env=commit_env)
            changed = git(repo, "diff", "--shortstat", fork_parent, commit)
            outcome = {"result": "prepared" if dry_run else "pushed", "mode": mode,
                       "upstream": latest, "upstream_head": head,
                       "fork_parent": fork_parent, "commit": commit,
                       "patch_bytes": patch.stat().st_size,
                       "official_file_updates": len(update_paths) if mode == "incremental" else 0,
                       "summary": changed,
                       "pushed": not dry_run}
            if dry_run:
                # No user files, GitHub branches, or release assets changed.
                if not force_sha:
                    safe_json_write(dry_state, {"upstream": latest, "selection": "green"})
                return outcome

            # Fast-forward-only push: concurrent GitHub commits cause a safe failure.
            git(repo, "push", "--porcelain", "origin",
                f"{commit}:refs/heads/main", env=env)
            return outcome
        finally:
            shutil.rmtree(staging, ignore_errors=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one check")
    parser.add_argument("--dry-run", action="store_true", help="stage, never push")
    parser.add_argument("--upstream-sha", help="test a specific upstream SHA")
    args = parser.parse_args()
    dry_run = args.dry_run or os.environ.get("SYNC_PUBLISH") != "1"
    when = datetime.now(timezone.utc).isoformat()
    try:
        result = run_once(dry_run=dry_run, force_sha=args.upstream_sha)
        print(json.dumps({"at": when, **result}, ensure_ascii=False), flush=True)
        return 0
    except (SyncError, subprocess.TimeoutExpired, BlockingIOError, OSError, ValueError) as error:
        print(json.dumps({"at": when, "result": "failed",
                          "error": str(error)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

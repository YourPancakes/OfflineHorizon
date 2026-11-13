#!/usr/bin/env python3
"""OfflineHorizon release controller: GitHub Actions first, guarded server fallback.

This controller does NOT use a personal token committed to source control.
GitHub Actions produces platform binaries. If its release job cannot start
(billing/runner restriction), a very small server process can publish the
already-verified artifacts using GitHub's release REST API.

An OPTIONAL native Linux rebuild is available on machines large enough to
compile safely. It refuses to run on under-provisioned VPS hosts and cannot
build Windows/macOS binaries on Linux.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

from calendar_schedule import due_slot, mark_slot, read_slot

REPO = "YourPancakes/OfflineHorizon"
API = "https://api.github.com"
ASSET_NAMES = (
    "horizon-linux-x86_64.tar.gz",
    "horizon-server-linux-x86_64.tar.gz",
    "horizon-windows-x64.zip",
    "horizon-windows-arm64.zip",
    "horizon-macos-arm64.zip",
    "horizon-macos-x64.zip",
)
# The seven launcher files share the SAME vX.Y.Z release as the game.
# Never create a launcher@ tag or a second GitHub Release for them.
LAUNCHER_ASSET_NAMES = (
    "horizon-launcher-linux-x86_64.tar.gz",
    "horizon-launcher-windows-x64.zip",
    "horizon-launcher-windows-arm64.zip",
    "horizon-launcher-macos-arm64.zip",
    "horizon-launcher-macos-x64.zip",
    "horizon-launcher-setup.exe",
    "horizon-launcher-setup-arm64.exe",
)
OPTIONAL_LAUNCHER_ASSETS = (
    "horizon-launcher-macos-arm64.dmg",
    "horizon-launcher-macos-x64.dmg",
)
# These are the actual release archives, NOT their Actions artifact ZIP wrappers.
DEFAULT_TAG = "v0.2.9"
DEFAULT_SHA = "d2e75698121d9aef17d4547f702bd87ca7e65f6b"
DEFAULT_RUN = 43181646362


class ReleaseError(Exception):
    pass


def log(**fields):
    print(json.dumps(fields, ensure_ascii=False, sort_keys=True), flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0  # unknown memory is never accepted for builds


def require_safe_build_resources(directory: Path, source: Path):
    """Fail closed BEFORE starting Docker, cargo, or allocating disk.

    Minimums are intentionally higher than OfflineHorizon's existing 2 GB VPS.
    """
    mem = available_memory_bytes()
    disk = shutil.disk_usage(directory).free
    cpus = os.cpu_count() or 0
    problems = []
    if cpus < 2:
        problems.append(f"CPU cores {cpus} < 2")
    if mem < 6 * 1024**3:
        problems.append(f"available memory {mem // 1024**2} MiB < 6144 MiB")
    if disk < 18 * 1024**3:
        problems.append(f"free disk {disk // 1024**3} GiB < 18 GiB")
    if not source.is_dir():
        problems.append(f"source missing: {source}")
    if problems:
        raise ReleaseError("unsafe to compile on this server: " + "; ".join(problems))


def token_from_env_or_file(path: str) -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return token
    secret = Path(path)
    if secret.is_file():
        if secret.stat().st_mode & 0o077:
            raise ReleaseError("token file permissions must be 0600 or stricter")
        return secret.read_text(encoding="utf-8").strip()
    return ""


def api(token: str, method: str, path: str, payload=None, *, missing_ok=False) -> dict | None:
    if not token:
        raise ReleaseError("GitHub release token is missing; no publication attempted")
    url = API + path
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "OfflineHorizon-recovery-publisher",
    }
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(2_000_000)
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing_ok:
            return None
        # Do not print token-bearing headers or full remote bodies.
        raise ReleaseError(f"GitHub {method} {path.split('?')[0]}: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise ReleaseError(f"GitHub API request failed: {type(error).__name__}") from None


def verify_workflow(token: str, repo: str, run_id: int, sha: str) -> str:
    """Accept only artifacts from a checked successful source, tests and matrix."""
    run = api(token, "GET", f"/repos/{repo}/actions/runs/{run_id}")
    if run.get("head_sha") != sha or run.get("head_branch") != "main":
        raise ReleaseError("GitHub Actions run does not match the approved main commit")
    if run.get("name") != "OfflineHorizon game release":
        raise ReleaseError("Unexpected GitHub Actions workflow")
    rows = []
    attempts = int(run.get("run_attempt", 1))
    if attempts < 1 or attempts > 10:
        raise ReleaseError("Unexpected number of workflow run attempts")
    # GitHub's normal run/jobs endpoint shows the latest attempt only.
    # A failed-jobs rerun can omit already-green 'source' from that attempt.
    for attempt in range(1, attempts + 1):
        jobs = api(token, "GET",
                   f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        this_attempt = jobs.get("jobs", [])
        if len(this_attempt) >= 100:
            raise ReleaseError("Workflow jobs truncated; refusing incomplete verification")
        rows.extend(this_attempt)
    for required in ("source", "tests"):
        if not any(j.get("name") == required and j.get("conclusion") == "success" for j in rows):
            raise ReleaseError(f"Required job {required} is not green")
    for platform in ("linux-x64", "windows-x64", "macos-arm64", "macos-x64"):
        if not any(j.get("name", "").startswith("build (") and
                   f", {platform}," in j.get("name", "") and
                   j.get("conclusion") == "success" for j in rows):
            raise ReleaseError(f"Required build {platform} is not green")
    # Windows ARM64 is optional in GitHub CI, but publish only if its archive
    # is actually present and has a verified build, too.
    if not any(", windows-arm64," in j.get("name", "") and
               j.get("conclusion") == "success" for j in rows):
        raise ReleaseError("Windows ARM64 archive not verified by CI")
    statuses = [j.get("conclusion") for j in rows if j.get("name") == "release"]
    if "success" in statuses:
        return "already_published_by_actions"
    if not statuses or any(s not in ("failure", "cancelled", "skipped") for s in statuses):
        raise ReleaseError("GitHub release job not yet completed; avoid publishing concurrently")
    return "github_release_failed"


def load_expected_manifest(directory: Path, sha: str, run_id: int) -> dict:
    path = directory / "verified-artifacts.json"
    if not path.is_file():
        raise ReleaseError("Missing verified-artifacts.json provenance manifest")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("source_sha") != sha or obj.get("actions_run") != run_id:
        raise ReleaseError("Provenance manifest does not match approved run and source SHA")
    expected = obj.get("assets", {})
    asset_set = set(expected)
    game = set(ASSET_NAMES)
    combined = game | set(LAUNCHER_ASSET_NAMES)
    if asset_set not in (game, combined, combined | set(OPTIONAL_LAUNCHER_ASSETS)):
        raise ReleaseError("Provenance manifest must list exactly six game assets or all game and launcher assets")
    for name, digest in expected.items():
        if not isinstance(digest, str) or len(digest) != 64:
            raise ReleaseError(f"Invalid SHA256 for {name}")
    return expected


def validate_assets(directory: Path, expected: dict) -> dict:
    found = {}
    for name in expected:
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size < 1_000_000:
            raise ReleaseError(f"Missing or invalid release asset {name}")
        digest = sha256_file(path)
        if digest.lower() != expected[name].lower():
            raise ReleaseError(f"SHA256 mismatch for {name}")
        # A valid ZIP/TAR is required; never publish a corrupted archive.
        if name.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                if not z.namelist() or z.testzip() is not None:
                    raise ReleaseError(f"Corrupt ZIP file: {name}")
        elif name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as tar:
                if not tar.getmembers():
                    raise ReleaseError(f"Empty tarball: {name}")
        elif name.endswith(".exe") and path.open("rb").read(2) != b"MZ":
            raise ReleaseError(f"Invalid Windows executable: {name}")
        found[name] = {"sha256": digest, "size": path.stat().st_size}
    checksums = "".join(f"{found[n]['sha256']}  {n}\n" for n in expected)
    sums = directory / "SHA256SUMS"
    if not sums.is_file() or sums.read_text(encoding="ascii") != checksums:
        tmp = directory / "SHA256SUMS.partial"
        tmp.write_text(checksums, encoding="ascii")
        tmp.replace(sums)
    found["SHA256SUMS"] = {"sha256": sha256_file(sums), "size": sums.stat().st_size}
    return found


def get_release(token: str, repo: str, tag: str):
    encoded = urllib.parse.quote(tag, safe="")
    return api(token, "GET", f"/repos/{repo}/releases/tags/{encoded}", missing_ok=True)


def create_draft(token: str, repo: str, tag: str, sha: str, run_id: int):
    release = get_release(token, repo, tag)
    if release:
        return release
    # Release notes are intentionally blank: no internal CI, server or provenance text.
    body = ""
    return api(token, "POST", f"/repos/{repo}/releases", {
        "tag_name": tag,
        "target_commitish": sha,
        "name": f"OfflineHorizon {tag}",
        "body": body,
        "draft": True,
        "prerelease": False,
        "generate_release_notes": False,
    })


def send_asset(token: str, upload_url: str, path: Path):
    """Stream directly from disk; never buffer a 50 MB release asset in RAM."""
    raw = urllib.parse.urlsplit(upload_url.split("{", 1)[0])
    if raw.scheme != "https" or raw.hostname != "uploads.github.com":
        raise ReleaseError("Unexpected GitHub upload destination")
    query = urllib.parse.urlencode({"name": path.name})
    target = raw.path + "?" + query
    client = http.client.HTTPSConnection(raw.hostname, timeout=180)
    try:
        client.putrequest("POST", target)
        client.putheader("Authorization", "Bearer " + token)
        client.putheader("Accept", "application/vnd.github+json")
        client.putheader("Content-Type", "application/octet-stream")
        client.putheader("Content-Length", str(path.stat().st_size))
        client.putheader("User-Agent", "OfflineHorizon-recovery-publisher")
        client.endheaders()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                client.send(chunk)
        response = client.getresponse()
        raw_response = response.read(150_000)
        if response.status != 201:
            raise ReleaseError(f"GitHub asset upload failed: HTTP {response.status} ({path.name})")
        return json.loads(raw_response)
    except OSError as e:
        raise ReleaseError(f"Upload transport failed for {path.name}: {type(e).__name__}") from None
    finally:
        client.close()


def publish(token: str, directory: Path, repo: str, tag: str,
            sha: str, run_id: int, *, dry_run=False) -> dict:
    expected = load_expected_manifest(directory, sha, run_id)
    verified = validate_assets(directory, expected)
    release = get_release(token, repo, tag)
    # A finished public release is immutable: verify its full local archive
    # provenance and GitHub's uploaded SHA-256 digests. Workflow runs can be
    # deleted by retention/cleanup and must not be needed to read old releases.
    # Creating or completing an unpublished release still requires green CI.
    if release and not release.get("draft"):
        assets = {x.get("name"): x for x in release.get("assets", [])}
        for name, info in verified.items():
            x = assets.get(name)
            if (not x or x.get("size") != info["size"]
                    or x.get("state") != "uploaded"
                    or x.get("digest") != "sha256:" + info["sha256"].lower()):
                raise ReleaseError("Published release asset identity differs from verified source: " + name)
        # Old v0.2.9 release has a six-file local manifest, but already contains
        # all seven launcher files on GitHub. Require their uploaded digest too.
        for name in LAUNCHER_ASSET_NAMES:
            x = assets.get(name)
            if (not x or x.get("state") != "uploaded"
                    or not isinstance(x.get("size"), int) or x["size"] < 1_000_000
                    or not isinstance(x.get("digest"), str)
                    or not x["digest"].startswith("sha256:")
                    or len(x["digest"]) != 71):
                raise ReleaseError("Combined release missing verified launcher asset: " + name)
        return {"result": "already_published", "url": release.get("html_url"),
                "launcher_assets_verified": len(LAUNCHER_ASSET_NAMES)}
    if not set(LAUNCHER_ASSET_NAMES).issubset(expected):
        raise ReleaseError("Refusing game-only release: all launcher platforms must share the vX.Y.Z release")
    status = verify_workflow(token, repo, run_id, sha)
    if status == "already_published_by_actions" and release is None:
        raise ReleaseError("Workflow reports published, but release is missing")
    if dry_run:
        return {"result": "verified_ready", "assets": len(verified), "tag": tag}
    release = create_draft(token, repo, tag, sha, run_id)
    if not release.get("draft"):
        raise ReleaseError("Existing release is not a draft; refusing to modify")
    for name, info in verified.items():
        assets = {x.get("name"): x for x in release.get("assets", [])}
        existing = assets.get(name)
        if existing:
            if (existing.get("size") != info["size"]
                    or existing.get("state") != "uploaded"
                    or existing.get("digest") != "sha256:" + info["sha256"].lower()):
                raise ReleaseError(f"Existing GitHub asset mismatch: {name}")
            continue
        uploaded = send_asset(token, release["upload_url"], directory / name)
        if (uploaded.get("size") != info["size"]
                or uploaded.get("state") != "uploaded"
                or uploaded.get("digest") != "sha256:" + info["sha256"].lower()):
            raise ReleaseError(f"Upload digest or size mismatch: {name}")
        log(result="uploaded", name=name, size=info["size"])
        release = api(token, "GET", f"/repos/{repo}/releases/{release['id']}")
    release = api(token, "PATCH", f"/repos/{repo}/releases/{release['id']}", {
        "draft": False,
        "prerelease": False,
        "make_latest": "true",
    })
    names = {x.get("name") for x in release.get("assets", [])}
    if not set(verified).issubset(names) or release.get("draft"):
        raise ReleaseError("GitHub release verification failed")
    return {"result": "published", "url": release.get("html_url"),
            "assets": len(verified), "tag": tag}


def dispatch_github(token: str, repo: str):
    api(token, "POST", f"/repos/{repo}/actions/workflows/offline-game.yml/dispatches",
        {"ref": "main"})
    return {"result": "github_build_dispatched"}


def build_linux_guarded(directory: Path, source: Path, sha: str):
    """Optional server compilation; never start on today's 1-core/2-GB VPS."""
    require_safe_build_resources(directory, source)
    if not shutil.which("docker"):
        raise ReleaseError("Docker CLI missing on the build host")
    head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if head != sha or dirty:
        raise ReleaseError("Server source must be a CLEAN checkout of the exact release commit")
    image = "offlinehorizon-builder:rust-1.99"
    check = subprocess.run(["docker", "image", "inspect", image],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        raise ReleaseError("Prebuilt offlinehorizon-builder:rust-1.99 image missing")
    work = directory.parent / ".linux-build-work"
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    inner = " && ".join((
        "cargo build --release --locked -p horizon-official --bin horizon-official "
        "-p horizon-client-lib --bin horizon-ctl -p horizon-prepare --bin horizon-prepare "
        "-p horizon-server --bin horizon-server",
        "cargo build --release --locked -p horizon-client --no-default-features --bin horizon-client",
    ))
    cmd = ["docker", "run", "--rm", "--cpus=0.75", "--memory=4g",
           "--memory-swap=4g", "--pids-limit=160", "--oom-score-adj=500",
           "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", "CARGO_BUILD_JOBS=1", "-e", "CARGO_INCREMENTAL=0",
           "-e", "CARGO_TARGET_DIR=/build/target", "-e", "CARGO_HOME=/build/cargo",
           "-v", f"{source}:/src:ro", "-v", f"{work}:/build:rw",
           "-w", "/src", image, "sh", "-c", inner]
    subprocess.run(cmd, check=True)
    binary = work / "target" / "release"
    def fill(folder: Path, client: str, engine: bool):
        folder.mkdir(exist_ok=False)
        for tool in ("horizon-ctl", "horizon-prepare", "horizon-server"):
            if not engine or tool != "horizon-ctl":
                shutil.copy2(binary / tool, folder / tool)
        if engine:
            shutil.copy2(binary / "horizon-client", folder / "horizon-engine")
        else:
            shutil.copy2(binary / client, folder / "horizon-client")
        # Use only open source build inputs, never Minecraft files.
        paths = ["tools", "mods/horizon/src/test/java", "crates/horizon-prepare",
                 "research-lock.json", "LICENSE", "packaging/PLAY.txt"]
        archive = subprocess.Popen(["git", "-C", str(source), "archive", "HEAD", *paths],
                                   stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            for item in stream:
                if item.name.startswith("/") or ".." in Path(item.name).parts:
                    raise ReleaseError("Unsafe archive entry")
                stream.extract(item, folder, filter="data")
        if archive.wait() != 0:
            raise ReleaseError("git archive failed")
        shutil.copy2(folder / "packaging" / "PLAY.txt", folder / "PLAY.txt")
    for label, client, server in (
        ("horizon-linux-x86_64", "horizon-official", False),
        ("horizon-server-linux-x86_64", "horizon-client", True),
    ):
        folder = work / label
        if folder.exists():
            shutil.rmtree(folder)
        fill(folder, client, server)
        archive_name = label + ".tar.gz"
        with tarfile.open(directory / archive_name, "w:gz") as out:
            out.add(folder, arcname=label)
    return {"result": "linux_built", "archives": 2}



LAUNCHER_REQUIRED_ARCHIVES = (
    "horizon-launcher-windows-x64.zip",
    "horizon-launcher-windows-arm64.zip",
    "horizon-launcher-linux-x86_64.tar.gz",
    "horizon-launcher-macos-arm64.zip",
    "horizon-launcher-macos-x64.zip",
)
LAUNCHER_EXTRA_ASSETS = ("horizon-launcher-setup.exe", "horizon-launcher-setup-arm64.exe")


def verify_launcher_stage(directory: Path, tag: str) -> dict:
    """Audit locally compiled platform assets; NEVER publish an incomplete set."""
    if not re.fullmatch(r"launcher@[0-9]+[.][0-9]+[.][0-9]+", tag):
        raise ReleaseError("Invalid launcher tag")
    manifest = directory / "stage-manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        return {"result": "waiting_launcher_stage", "tag": tag}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ReleaseError("Malformed launcher stage manifest") from exc
    if payload.get("tag") != tag:
        raise ReleaseError("Launcher stage tag mismatch")
    sha = payload.get("source_git_head")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ReleaseError("Invalid launcher source commit hash")
    dirty = payload.get("source_tree_dirty")
    if not isinstance(dirty, bool):
        raise ReleaseError("Launcher source cleanliness not recorded")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise ReleaseError("Missing launcher asset manifest")
    allowed = set(LAUNCHER_REQUIRED_ARCHIVES + LAUNCHER_EXTRA_ASSETS)
    if not set(assets) <= allowed:
        raise ReleaseError("Unknown launcher archive name")
    verified = []
    for name, info in assets.items():
        digest = info.get("sha256") if isinstance(info, dict) else None
        size = info.get("size") if isinstance(info, dict) else None
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or not isinstance(size, int) or size < 1_000_000):
            raise ReleaseError("Invalid launcher asset metadata: " + name)
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
            raise ReleaseError("Missing or invalid staged file: " + name)
        if sha256_file(path) != digest:
            raise ReleaseError("Launcher SHA256 mismatch: " + name)
        if name.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as archive:
                members = archive.namelist()
                if not members or archive.testzip() is not None:
                    raise ReleaseError("Corrupt staged ZIP: " + name)
        elif name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                if not archive.getmembers():
                    raise ReleaseError("Empty staged tarball: " + name)
        verified.append(name)
    missing = [name for name in LAUNCHER_REQUIRED_ARCHIVES if name not in assets]
    if payload.get("missing_platform_archives") != missing:
        raise ReleaseError("Stage missing-platform list does not match files")
    return {
        "result": "waiting_platforms" if missing else (
            "waiting_clean_source" if dirty else "verified_complete_not_published"),
        "tag": tag,
        "source_git_head": sha,
        "source_tree_dirty": dirty,
        "assets_verified": len(verified),
        "missing": missing,
        "published": False,
    }


def execute(args):
    directory = Path(args.assets_dir).resolve()
    if not directory.is_dir():
        raise ReleaseError("Release staging directory missing")
    if args.method == "build-linux":
        return build_linux_guarded(directory, Path(args.source_dir).resolve(), args.sha)
    if args.method == "launcher-status":
        return verify_launcher_stage(directory, args.tag)
    token = token_from_env_or_file(args.token_file)
    if args.method == "status":
        expected = load_expected_manifest(directory, args.sha, args.run_id)
        return {"result": "combined_staged" if set(LAUNCHER_ASSET_NAMES).issubset(expected) else "legacy_game_staged",
                "assets": len(validate_assets(directory, expected)),
                "credentials_configured": bool(token), "tag": args.tag}
    if not token:
        return {"result": "waiting_credentials", "tag": args.tag,
                "message": "Install a NEW fine-grained token (Contents:write, Actions:read) in the server secret file"}
    if args.method == "github":
        return dispatch_github(token, args.repo)
    # auto always checks for an existing completed release and otherwise only
    # publishes verified, prebuilt assets; it never silently starts cargo.
    return publish(token, directory, args.repo, args.tag, args.sha,
                   args.run_id, dry_run=args.dry_run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=("github", "server", "auto", "status", "launcher-status", "build-linux"))
    parser.add_argument("--repo", default=os.environ.get("RELEASE_REPO", REPO))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG", DEFAULT_TAG))
    parser.add_argument("--sha", default=os.environ.get("RELEASE_SHA", DEFAULT_SHA))
    parser.add_argument("--run-id", type=int, default=int(os.environ.get("RELEASE_RUN_ID", DEFAULT_RUN)))
    parser.add_argument("--assets-dir", default=os.environ.get("RELEASE_DIR", "/releases/v0.2.9"))
    parser.add_argument("--source-dir", default=os.environ.get("SOURCE_DIR", "/source"))
    parser.add_argument("--token-file", default=os.environ.get("TOKEN_FILE", "/run/secrets/github_release_token"))
    parser.add_argument("--interval", type=int, default=0, help="Legacy periodic mode (not used by Docker)")
    parser.add_argument("--calendar", action="store_true", help="Run only on 1st and 15th at 03:00 UTC")
    parser.add_argument("--schedule-state", default="/releases/.last-publisher-slot")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.calendar and args.interval:
        parser.error("Use --calendar or --interval, not both")
    if args.interval and args.interval < 1800:
        parser.error("interval must be at least 1800 seconds")
    if args.calendar:
        log(result="calendar_configured", days=[1, 15], hour_utc=3)
    while True:
        try:
            if args.calendar:
                state = Path(args.schedule_state)
                slot = due_slot(datetime.now(timezone.utc), read_slot(state))
                if not slot:
                    time.sleep(60)
                    continue
                mark_slot(state, slot)
                log(result="calendar_due", slot=slot)
            result = execute(args)
            log(**result)
        except (ReleaseError, RuntimeError, OSError, ValueError, subprocess.CalledProcessError,
                tarfile.TarError, zipfile.BadZipFile) as e:
            log(result="blocked", error=str(e))
            if not (args.interval or args.calendar):
                return 1
        if not (args.interval or args.calendar):
            return 0
        time.sleep(60 if args.calendar else args.interval)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Attach verified existing launcher installers to the OfflineHorizon game release.

No launchers are rebuilt and no secrets are printed. Token remains on server.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import tarfile
import urllib.error
import urllib.request
import zipfile

from release_fallback import API, REPO, ReleaseError, api, send_asset, token_from_env_or_file

SOURCE_TAG = "launcher@0.2.0"
DEST_TAG = "v0.2.9"
ASSET_DIGESTS = {
    "horizon-launcher-setup.exe": "a35d5440bacbc4681c16bc463678ff2892a600798631dc42a191cc67beb3f6ae",
    "horizon-launcher-setup-arm64.exe": "ba216ad93b46066ae021b29ea9423ccac613dd9463ec679bc2fe33eb97cea095",
    "horizon-launcher-windows-x64.zip": "478538925daa4e624ccc2845c954a8f145c7f6c242d31046af2cecc7b3fb802a",
    "horizon-launcher-windows-arm64.zip": "52b29b6cb7e6a0682d0d4885a813a27a87f9369dc36447dc84d4636506e137f1",
    "horizon-launcher-macos-x64.zip": "45d0299503f61b027b5cf3365922f371b548030488d5db1030293fe4414ce6c8",
    "horizon-launcher-macos-arm64.zip": "5b629eaafbf054a991f682a1977dd0f050adbeac3bbea922f05dd0f2fd5a0350",
    "horizon-launcher-linux-x86_64.tar.gz": "3cedc9ab07eca0fd6a2b108725330e01b1dc9bbd4c7a76be7ea57a2eca4ccca4",
}


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def fetch_asset(token: str, item: dict, destination: Path, expected: str) -> None:
    url = item["url"]
    browser_url = item["browser_download_url"]
    if not url.startswith(API + f"/repos/{REPO}/releases/assets/"):
        raise ReleaseError("Unexpected source API address")
    if not browser_url.startswith(f"https://github.com/{REPO}/releases/download/"):
        raise ReleaseError("Unexpected source download address")
    tmp = destination.with_suffix(destination.suffix + ".partial")
    for source_url in (url, browser_url):
        try:
            headers = {
                "Accept": "application/octet-stream",
                "Authorization": "Bearer " + token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OfflineHorizon-launcher-transfer",
            }
            request = urllib.request.Request(source_url, headers=headers)
            with urllib.request.urlopen(request, timeout=180) as resp:
                if "json" in resp.headers.get("Content-Type", "").lower():
                    continue  # API metadata reply; try the actual download URL.
                h = hashlib.sha256()
                size = 0
                with tmp.open("wb") as output:
                    while True:
                        block = resp.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        h.update(block)
                        size += len(block)
            if size != item["size"] or h.hexdigest() != expected:
                raise ReleaseError(f"Downloaded bytes differ from verified launcher: {destination.name}")
            tmp.replace(destination)
            return
        except urllib.error.HTTPError as error:
            if source_url == url and error.code in (302, 403, 404):
                continue
            raise ReleaseError(f"Launcher download HTTP {error.code}: {destination.name}") from None
        finally:
            tmp.unlink(missing_ok=True)
    raise ReleaseError(f"Could not access launcher bytes for {destination.name}")


def verify_file(path: Path, expected_digest: str, expected_size: int) -> None:
    if path.stat().st_size != expected_size or checksum(path) != expected_digest:
        raise ReleaseError(f"Size or SHA256 mismatch: {path.name}")
    if path.name.endswith(".exe"):
        with path.open("rb") as f:
            if f.read(2) != b"MZ":
                raise ReleaseError(f"Missing PE executable header: {path.name}")
    elif path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise ReleaseError(f"Invalid launcher ZIP: {path.name}")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            if not archive.getmembers():
                raise ReleaseError("Empty launcher archive")


def main() -> None:
    token = token_from_env_or_file("/opt/OfflineHorizon-sync/secrets/github_release_token")
    if not token:
        raise ReleaseError("Server authorization is missing")
    src = api(token, "GET", f"/repos/{REPO}/releases/tags/launcher%400.2.0")
    dst = api(token, "GET", f"/repos/{REPO}/releases/tags/v0.2.9")
    if not src or src["tag_name"] != SOURCE_TAG:
        raise ReleaseError("Launcher source release not found")
    if not dst or dst["tag_name"] != DEST_TAG or dst.get("draft"):
        raise ReleaseError("Game release not published")
    source_assets = {a["name"]: a for a in src.get("assets", [])}
    directory = Path("/opt/OfflineHorizon-releases/v0.2.9/launchers")
    directory.mkdir(exist_ok=True, parents=True)
    for name, expected_sha in ASSET_DIGESTS.items():
        item = source_assets.get(name)
        if not item:
            raise ReleaseError(f"Source launcher missing: {name}")
        if item.get("digest") != "sha256:" + expected_sha or item.get("state") != "uploaded":
            raise ReleaseError(f"Unverified source asset: {name}")
        path = directory / name
        if path.exists():
            verify_file(path, expected_sha, item["size"])
        else:
            fetch_asset(token, item, path, expected_sha)
            verify_file(path, expected_sha, item["size"])
        current_assets = {a["name"]: a for a in dst.get("assets", [])}
        existing = current_assets.get(name)
        if existing is not None:
            if (existing["size"] != item["size"] or
                    existing.get("digest") not in (None, "sha256:" + expected_sha)):
                raise ReleaseError(f"Existing destination asset mismatch: {name}")
            print("verified existing", name, flush=True)
            continue
        result = send_asset(token, dst["upload_url"], path)
        if (result.get("size") != item["size"] or
                result.get("digest") not in (None, "sha256:" + expected_sha)):
            raise ReleaseError(f"Uploaded launcher digest mismatch: {name}")
        print("uploaded", name, result["size"], flush=True)
        dst = api(token, "GET", f"/repos/{REPO}/releases/{dst['id']}")
    # User explicitly requested removing internal build/provenance/fallback notes.
    dst = api(token, "PATCH", f"/repos/{REPO}/releases/{dst['id']}", {"body": ""})
    if dst.get("body") or dst.get("draft"):
        raise ReleaseError("Release description edit did not persist")
    final_assets = {a["name"]: a for a in dst.get("assets", [])}
    if not set(ASSET_DIGESTS).issubset(final_assets):
        raise ReleaseError("One or more launcher files are absent from release")
    print("complete", dst["html_url"], len(final_assets), "assets; empty description", flush=True)


if __name__ == "__main__":
    main()

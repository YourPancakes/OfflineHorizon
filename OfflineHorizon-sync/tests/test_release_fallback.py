#!/usr/bin/env python3
"""Regression tests for guarded GitHub/low-memory server release fallback."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock

S = Path(__file__).resolve().parents[1] / "release_fallback.py"
spec = importlib.util.spec_from_file_location("release_fallback", S)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(TestCase):
    def test_refuses_to_build_on_two_gb_one_cpu_vps(self):
        with TemporaryDirectory() as directory:
            with (mock.patch.object(release.os, "cpu_count", return_value=1),
                  mock.patch.object(release, "available_memory_bytes", return_value=1024**3),
                  mock.patch.object(release.shutil, "disk_usage", return_value=mock.Mock(free=9*1024**3)),
                  mock.patch.object(release.subprocess, "run") as run):
                with self.assertRaisesRegex(release.ReleaseError, "unsafe to compile"):
                    release.require_safe_build_resources(Path(directory), Path(directory))
                run.assert_not_called()

    def test_token_file_permission_guard(self):
        with TemporaryDirectory() as directory:
            p = Path(directory) / "secret"
            p.write_text("dummy-not-a-real-token")
            p.chmod(0o644)
            with mock.patch.dict(release.os.environ, {"GH_TOKEN": ""}):
                with self.assertRaisesRegex(release.ReleaseError, "0600"):
                    release.token_from_env_or_file(str(p))
                p.chmod(0o600)
                self.assertEqual(release.token_from_env_or_file(str(p)),
                                 "dummy-not-a-real-token")

    def test_verify_source_across_rerun_attempts(self):
        sha = release.DEFAULT_SHA
        # Build the previous-attempt list, as the GitHub API does when only
        # the failed release job was rerun.
        green = [{"name": "source", "conclusion": "success"},
                 {"name": "tests", "conclusion": "success"}]
        green += [{"name": f"build (ubuntu, {p}, asset)", "conclusion": "success"}
                  for p in ("linux-x64", "windows-x64", "windows-arm64", "macos-arm64", "macos-x64")]
        def response(token, method, path, payload=None, **kwargs):
            if path.endswith(f"/actions/runs/{release.DEFAULT_RUN}"):
                return {"head_sha": sha, "head_branch": "main",
                        "name": "OfflineHorizon game release", "run_attempt": 2}
            if "/attempts/1/jobs" in path:
                return {"jobs": green}
            if "/attempts/2/jobs" in path:
                return {"jobs": [{"name": "release", "conclusion": "failure"}]}
            raise AssertionError(path)
        with mock.patch.object(release, "api", side_effect=response):
            self.assertEqual(release.verify_workflow("secret", release.REPO,
                             release.DEFAULT_RUN, sha), "github_release_failed")

    def test_verify_rejects_missing_required_platform(self):
        def response(token, method, path, payload=None, **kwargs):
            if path.endswith(f"/actions/runs/{release.DEFAULT_RUN}"):
                return {"head_sha": release.DEFAULT_SHA, "head_branch": "main",
                        "name": "OfflineHorizon game release", "run_attempt": 1}
            return {"jobs": [{"name": "source", "conclusion": "success"},
                             {"name": "tests", "conclusion": "success"},
                             {"name": "release", "conclusion": "failure"}]}
        with mock.patch.object(release, "api", side_effect=response):
            with self.assertRaisesRegex(release.ReleaseError, "Required build"):
                release.verify_workflow("secret", release.REPO,
                                        release.DEFAULT_RUN, release.DEFAULT_SHA)

    def test_manifest_rejects_missing_asset(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "verified-artifacts.json"
            path.write_text(json.dumps({
                "actions_run": release.DEFAULT_RUN,
                "source_sha": release.DEFAULT_SHA,
                "assets": {"horizon-windows-x64.zip": "0" * 64},
            }))
            with self.assertRaisesRegex(release.ReleaseError, "six"):
                release.load_expected_manifest(Path(directory),
                    release.DEFAULT_SHA, release.DEFAULT_RUN)

    def test_published_release_requires_exact_asset_digest(self):
        expected = {name: "a" * 64 for name in release.ASSET_NAMES}
        verified = {name: {"size": 1000001, "sha256": "a" * 64} for name in release.ASSET_NAMES}
        verified["SHA256SUMS"] = {"size": 555, "sha256": "c" * 64}
        matching = {
            "draft": False,
            "html_url": "https://github.com/YourPancakes/OfflineHorizon/releases/tag/v0.2.9",
            "assets": [
                {"name": name, "size": 1000001, "state": "uploaded",
                 "digest": "sha256:" + ("b" * 64 if name == release.ASSET_NAMES[0] else "a" * 64)}
                for name in release.ASSET_NAMES
            ] + [{"name": "SHA256SUMS", "size": 555, "state": "uploaded",
                  "digest": "sha256:" + "c" * 64}] + [
                  {"name": name, "size": 1_000_001, "state": "uploaded",
                   "digest": "sha256:" + "d" * 64}
                  for name in release.LAUNCHER_ASSET_NAMES]
        }
        with (mock.patch.object(release, "load_expected_manifest", return_value=expected),
              mock.patch.object(release, "validate_assets", return_value=verified),
              mock.patch.object(release, "verify_workflow",
                                side_effect=AssertionError("existing published release does not need retained CI logs")),
              mock.patch.object(release, "get_release", return_value=matching)):
            with self.assertRaisesRegex(release.ReleaseError, "asset identity differs"):
                release.publish("dummy", Path("/unread"), release.REPO, release.DEFAULT_TAG,
                                release.DEFAULT_SHA, release.DEFAULT_RUN)
            matching["assets"][0]["digest"] = "sha256:" + "a" * 64
            self.assertEqual(release.publish(
                "dummy", Path("/unread"), release.REPO, release.DEFAULT_TAG,
                release.DEFAULT_SHA, release.DEFAULT_RUN)["result"], "already_published")

    def test_new_release_requires_green_ci_even_after_history_cleanup(self):
        expected = {name: "a" * 64 for name in (release.ASSET_NAMES + release.LAUNCHER_ASSET_NAMES)}
        verified = {name: {"size": 1000001, "sha256": "a" * 64}
                    for name in release.ASSET_NAMES}
        verified["SHA256SUMS"] = {"size": 555, "sha256": "c" * 64}
        with (mock.patch.object(release, "load_expected_manifest", return_value=expected),
              mock.patch.object(release, "validate_assets", return_value=verified),
              mock.patch.object(release, "get_release", return_value=None),
              mock.patch.object(release, "verify_workflow",
                                side_effect=release.ReleaseError("CI history missing")),
              mock.patch.object(release, "create_draft") as draft):
            with self.assertRaisesRegex(release.ReleaseError, "CI history missing"):
                release.publish("dummy", Path("/unread"), release.REPO, release.DEFAULT_TAG,
                                release.DEFAULT_SHA, release.DEFAULT_RUN)
            draft.assert_not_called()

    def test_launcher_stage_status_reports_missing_platforms_and_detects_tampering(self):
        import hashlib
        with TemporaryDirectory() as folder:
            path = Path(folder)
            artifact = path / "horizon-launcher-setup.exe"
            artifact.write_bytes(b"MZ" + b"z" * 1_000_100)
            required = release.LAUNCHER_REQUIRED_ARCHIVES
            contents = {
                "tag": "launcher@0.2.1",
                "source_git_head": "1" * 40,
                "source_tree_dirty": True,
                "assets": {
                    artifact.name: {
                        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        "size": artifact.stat().st_size,
                    }
                },
                "missing_platform_archives": list(required),
            }
            (path / "stage-manifest.json").write_text(json.dumps(contents))
            status = release.verify_launcher_stage(path, "launcher@0.2.1")
            self.assertEqual(status["result"], "waiting_platforms")
            self.assertEqual(status["assets_verified"], 1)
            self.assertEqual(status["missing"], list(required))
            self.assertFalse(status["published"])
            artifact.write_bytes(b"tampered")
            with self.assertRaisesRegex(release.ReleaseError, "invalid staged file"):
                release.verify_launcher_stage(path, "launcher@0.2.1")

    def test_launcher_stage_rejects_invalid_tag_and_manifest(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            self.assertEqual(release.verify_launcher_stage(path, "launcher@0.2.1")["result"],
                             "waiting_launcher_stage")
            with self.assertRaisesRegex(release.ReleaseError, "Invalid launcher tag"):
                release.verify_launcher_stage(path, "v0.2.1")
            (path / "stage-manifest.json").write_text("not-json")
            with self.assertRaisesRegex(release.ReleaseError, "Malformed launcher stage"):
                release.verify_launcher_stage(path, "launcher@0.2.1")

    def test_new_game_only_release_is_never_published(self):
        expected = {name: "a" * 64 for name in release.ASSET_NAMES}
        verified = {name: {"size": 1000001, "sha256": "a" * 64} for name in expected}
        verified["SHA256SUMS"] = {"size": 555, "sha256": "c" * 64}
        with (mock.patch.object(release, "load_expected_manifest", return_value=expected),
              mock.patch.object(release, "validate_assets", return_value=verified),
              mock.patch.object(release, "get_release", return_value=None),
              mock.patch.object(release, "create_draft") as draft):
            with self.assertRaisesRegex(release.ReleaseError, "game-only release"):
                release.publish("dummy", Path("/unread"), release.REPO,
                                "v0.2.10", release.DEFAULT_SHA, release.DEFAULT_RUN)
            draft.assert_not_called()

    def test_github_method_needs_credentials(self):
        with TemporaryDirectory() as directory:
            args = mock.Mock(method="github", assets_dir=directory,
                             token_file=str(Path(directory)/"missing"), tag="v0.2.9")
            with mock.patch.dict(release.os.environ, {"GH_TOKEN": ""}):
                self.assertEqual(release.execute(args)["result"], "waiting_credentials")


if __name__ == "__main__":
    main()

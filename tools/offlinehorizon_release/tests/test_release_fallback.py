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

    def test_github_method_needs_credentials(self):
        with TemporaryDirectory() as directory:
            args = mock.Mock(method="github", assets_dir=directory,
                             token_file=str(Path(directory)/"missing"), tag="v0.2.9")
            with mock.patch.dict(release.os.environ, {"GH_TOKEN": ""}):
                self.assertEqual(release.execute(args)["result"], "waiting_credentials")


if __name__ == "__main__":
    main()

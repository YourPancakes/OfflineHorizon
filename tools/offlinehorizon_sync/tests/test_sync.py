#!/usr/bin/env python3
"""OfflineHorizon sync tests use only disposable local Git repositories."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("offline_sync", Path(__file__).parents[1] / "sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


class ManifestPolicyTests(unittest.TestCase):
    def test_removed_graphics_and_relay_overlays_stay_excluded(self):
        manifest = sync.manifest_paths(sync.HERE / "manifest.txt")
        forbidden = {
            "crates/horizon-client/src/gfx.rs",
            "crates/horizon-client/src/gfx/binding_cache.rs",
            "crates/horizon-client/src/gfx/flat.rs",
            "crates/horizon-client/src/gfx/flat/cache_tests.rs",
            "crates/horizon-client/src/gfx/particle_batch.rs",
            "crates/horizon-client/src/gfx/particle_tests.rs",
            "crates/horizon-client/src/gfx/sky_tests.rs",
            "crates/horizon-client/src/gfx/weather.rs",
            "crates/horizon-client/src/mesher/sides.rs",
            "crates/horizon-client/src/mesher/optimization_ab_tests.rs",
            "crates/horizon-client/src/entity.wgsl",
            "crates/horizon-client/src/terrain.wgsl",
            "crates/horizon-client/src/particles.rs",
            "crates/horizon-client/src/sprites.rs",
            "crates/horizon-client/src/weather.rs",
            "crates/horizon-friends/src/direct.rs",
            "crates/horizon-friends/src/host.rs",
            "crates/horizon-friends/src/lib.rs",
            "crates/horizon-friends/src/reach.rs",
            "tools/particle_batch_bench.rs",
            "tools/render_hotpaths_test.rs",
        }
        self.assertFalse(forbidden.intersection(manifest), "Removed patches must stay upstream")
        unnecessary_tools = {
            "tests/test_parity_signals.py",
            "tools/cargo_validation.py",
            "tools/particle_batch_bench.rs",
            "tools/render_hotpaths_test.rs",
            "crates/horizon-client/tests/agent_perf_light_item_parity.rs",
            "xtask/src/autopatch.rs",
            "tools/autopatch.py",
        }
        self.assertFalse(unnecessary_tools.intersection(manifest),
                         "Removed development-only files must not be copied into the fork")
        for preserved in ("launcher/src/account.rs", "launcher/src/backend.rs",
                          "crates/horizon-client/src/light.rs",
                          "crates/horizon-client/src/streaming.rs"):
            self.assertIn(preserved, manifest)


class ServerTokenTests(unittest.TestCase):
    def test_token_reads_private_file_without_env_value(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "github_release_token"
            secret.write_text("test-private-token\n", encoding="utf-8")
            secret.chmod(0o600)
            with mock.patch.dict(os.environ, {"TOKEN_FILE": str(secret), "GH_TOKEN": ""}):
                self.assertEqual(sync.sync_token(), "test-private-token")

    def test_token_rejects_insecure_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "github_release_token"
            secret.write_text("dummy", encoding="utf-8")
            secret.chmod(0o644)
            with mock.patch.dict(os.environ, {"TOKEN_FILE": str(secret), "GH_TOKEN": ""}):
                with self.assertRaises(sync.SyncError):
                    sync.sync_token()
            secret.chmod(0o600)
            link = Path(root) / "link"
            link.symlink_to(secret)
            with mock.patch.dict(os.environ, {"TOKEN_FILE": str(link), "GH_TOKEN": ""}):
                with self.assertRaises(sync.SyncError):
                    sync.sync_token()


class MergeTests(unittest.TestCase):
    def test_address_keys_are_merged_and_official_removals_survive(self):
        base = {"allowed": ["old", "shared"], "vanilla": {"example": "v1"}}
        fork = {"allowed": ["old", "shared", "fork-only"],
                "vanilla": {"example": "v1", "new": "offline"}}
        latest = {"allowed": ["shared", "new-official"],
                  "vanilla": {"example": "v1"}}
        merged = sync.merge_addresses(base, fork, latest)
        self.assertEqual(merged["allowed"], ["fork-only", "new-official", "shared"])
        self.assertEqual(merged["vanilla"]["new"], "offline")

    def test_conflicting_address_edits_fail_closed(self):
        base = {"vanilla": {"example": "old"}}
        fork = {"vanilla": {"example": "custom"}}
        latest = {"vanilla": {"example": "official"}}
        with self.assertRaises(sync.SyncError):
            sync.merge_addresses(base, fork, latest)

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "manifest.txt"
            path.write_text("../outside\n", encoding="utf-8")
            with self.assertRaises(sync.SyncError):
                sync.manifest_paths(path)


class UpstreamCITests(unittest.TestCase):
    def setUp(self):
        self.sha = "a" * 40
        self.ci_runs = [{
            "id": 101, "head_sha": self.sha, "head_branch": "main", "event": "push",
            "created_at": "2026-11-12T10:00:00Z", "run_attempt": 1,
            "status": "completed", "conclusion": "success",
        }]
        self.parity_runs = [{
            "id": 202, "head_sha": self.sha, "head_branch": "main", "event": "push",
            "created_at": "2026-11-12T10:05:00Z", "run_attempt": 1,
            "status": "completed", "conclusion": "success",
        }]
        self.ci_jobs = [
            {"name": "verify", "status": "completed", "conclusion": "success"},
            {"name": "launcher", "status": "completed", "conclusion": "success"},
        ]
        self.parity_jobs = [{"name": "parity-main", "status": "completed",
                             "conclusion": "success"}]

    def fake_api(self, path, token):
        self.assertIn("head_sha=" + self.sha, path) if "/workflows/" in path else None
        if "/workflows/ci.yml/runs?" in path:
            return {"workflow_runs": self.ci_runs}
        if "/workflows/parity-main.yml/runs?" in path:
            return {"workflow_runs": self.parity_runs}
        if "/actions/runs/101/jobs?" in path:
            return {"total_count": len(self.ci_jobs), "jobs": self.ci_jobs}
        if "/actions/runs/202/jobs?" in path:
            return {"total_count": len(self.parity_jobs), "jobs": self.parity_jobs}
        self.fail(f"Unexpected GitHub API path: {path}")

    def ready(self):
        with mock.patch.object(sync, "github_api", side_effect=self.fake_api):
            return sync.upstream_ci_ready(self.sha, "")

    def test_all_required_ci_jobs_and_parity_pass(self):
        approved, details = self.ready()
        self.assertTrue(approved, details)
        self.assertIn("parity-main", details)

    def test_pending_or_failed_workflow_blocks_import(self):
        for status, conclusion in (("queued", None), ("in_progress", None),
                                   ("completed", "failure"), ("completed", "cancelled")):
            with self.subTest(status=status, conclusion=conclusion):
                self.ci_runs[0]["status"] = status
                self.ci_runs[0]["conclusion"] = conclusion
                approved, reason = self.ready()
                self.assertFalse(approved)
                self.assertIn("ci.yml", reason)

    def test_parity_missing_or_wrong_commit_blocks_import(self):
        self.parity_runs = []
        approved, reason = self.ready()
        self.assertFalse(approved)
        self.assertIn("parity-main.yml", reason)
        self.parity_runs = [{
            "id": 202, "head_sha": "b" * 40, "head_branch": "main",
            "event": "push", "status": "completed", "conclusion": "success",
        }]
        approved, _ = self.ready()
        self.assertFalse(approved)

    def test_skipped_mandatory_job_does_not_count_as_green(self):
        self.ci_jobs[1]["conclusion"] = "skipped"
        approved, reason = self.ready()
        self.assertFalse(approved)
        self.assertIn("launcher", reason)

    def test_missing_job_and_incomplete_job_listing_block(self):
        self.ci_jobs.pop()
        approved, reason = self.ready()
        self.assertFalse(approved)
        self.assertIn("launcher", reason)
        self.ci_jobs.append({"name": "launcher", "status": "completed",
                             "conclusion": "success"})
        with mock.patch.object(sync, "github_api", side_effect=lambda path, token:
                               {"total_count": 101, "jobs": self.ci_jobs}
                               if "/actions/runs/101/jobs?" in path
                               else self.fake_api(path, token)):
            approved, reason = sync.upstream_ci_ready(self.sha, "")
        self.assertFalse(approved)
        self.assertIn("pagination", reason)

    def test_newer_pending_run_blocks_older_success(self):
        self.ci_runs.append({
            "id": 103, "head_sha": self.sha, "head_branch": "main",
            "event": "push", "created_at": "2026-11-12T10:07:00Z",
            "run_attempt": 1, "status": "queued", "conclusion": None,
        })
        approved, reason = self.ready()
        self.assertFalse(approved)
        self.assertIn("queued", reason)

    def test_api_error_never_approves_import(self):
        with mock.patch.object(sync, "github_api",
                               side_effect=sync.SyncError("GitHub HTTP 403")):
            with self.assertRaises(sync.SyncError):
                sync.upstream_ci_ready(self.sha, "")


class GreenHistoryTests(unittest.TestCase):
    def setUp(self):
        self.commits = ["a" * 40, "b" * 40, "c" * 40, "d" * 40]
        self.runs = [
            {"id": i + 1, "head_sha": sha, "head_branch": "main",
             "event": "push", "created_at": f"2026-11-12T10:{i:02d}:00Z",
             "status": status, "conclusion": conclusion}
            for i, (sha, status, conclusion) in enumerate([
                (self.commits[0], "completed", "success"),
                (self.commits[1], "completed", "success"),
                (self.commits[2], "completed", "failure"),
                (self.commits[3], "in_progress", None),
            ])
        ]

    def test_last_green_in_history_skips_in_progress_and_failed_head(self):
        def filtered_api(path, token):
            self.assertIn("status=success", path)
            return {"workflow_runs": self.runs}
        with (mock.patch.object(sync, "github_api", side_effect=filtered_api),
              mock.patch.object(sync, "upstream_ci_ready",
                                side_effect=lambda sha, token: (
                                    (True, "all green") if sha == self.commits[1]
                                    else (False, "checks failed"))) as checked):
            chosen, why = sync.latest_green_upstream_sha("")
        self.assertEqual(chosen, self.commits[1])
        self.assertEqual(why, "all green")
        self.assertEqual(checked.call_args_list[0].args[0], self.commits[1])

    def test_latest_parity_green_but_ci_failed_takes_older_green(self):
        self.runs[-2]["status"] = "completed"
        self.runs[-2]["conclusion"] = "success"
        self.runs[-1]["status"] = "completed"
        self.runs[-1]["conclusion"] = "success"
        def approved(sha, token):
            return (sha == self.commits[0], "approved" if sha == self.commits[0] else "red checks")
        with (mock.patch.object(sync, "github_api", return_value={"workflow_runs": self.runs}),
              mock.patch.object(sync, "upstream_ci_ready", side_effect=approved)):
            chosen, _ = sync.latest_green_upstream_sha("")
        self.assertEqual(chosen, self.commits[0])

    def test_no_fully_green_commit_waits_without_guessing(self):
        with (mock.patch.object(sync, "github_api", return_value={"workflow_runs": self.runs}),
              mock.patch.object(sync, "upstream_ci_ready",
                                return_value=(False, "failed"))):
            chosen, why = sync.latest_green_upstream_sha("")
        self.assertIsNone(chosen)
        self.assertIn("No fully green", why)

    def test_untrusted_run_from_other_branch_is_not_candidate(self):
        self.runs[-1].update(status="completed", conclusion="success",
                             head_branch="other")
        with (mock.patch.object(sync, "github_api", return_value={"workflow_runs": self.runs}),
              mock.patch.object(sync, "upstream_ci_ready",
                                side_effect=lambda sha, token: (True, "green"))):
            chosen, _ = sync.latest_green_upstream_sha("")
        self.assertEqual(chosen, self.commits[1])

    def test_ancestry_accepts_forward_only(self):
        old, new = self.commits[:2]
        for status, expected in (("ahead", True), ("identical", True),
                                 ("behind", False), ("diverged", False)):
            with self.subTest(status=status), mock.patch.object(
                sync, "github_api", return_value={"status": status}
            ):
                self.assertEqual(sync.upstream_is_descendant(old, new, ""), expected)

    def test_history_api_outage_fails_closed(self):
        with mock.patch.object(sync, "github_api",
                               side_effect=sync.SyncError("GitHub HTTP 403")):
            with self.assertRaises(sync.SyncError):
                sync.latest_green_upstream_sha("")


class GitSynchronizationTests(unittest.TestCase):
    def setUp(self):
        # Local Git repositories have no GitHub Actions; tests approve CI explicitly.
        self.ci_patch = mock.patch.object(sync, "upstream_ci_ready", return_value=(True, "green"))
        self.ci_patch.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.upstream = self.root / "upstream"
        self.source = self.root / "source"
        self.work = self.root / "work"
        self.manifest = self.root / "manifest.txt"
        self.upstream.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        git(self.upstream, "config", "user.name", "Unit test")
        git(self.upstream, "config", "user.email", "test@example.invalid")
        for lang in ("ru", "fr", "pl", "hu"):
            path = self.upstream / "launcher" / "lang" / (lang + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        backend = self.upstream / "launcher" / "src" / "backend.rs"
        backend.parent.mkdir(parents=True, exist_ok=True)
        backend.write_text('pub const REPO: &str = "horizon-rust/horizon";\n'
                           'pub const LAUNCHER_REPO: &str = "YourPancakes/OfflineHorizon";\n',
                           encoding="utf-8")
        workflow = self.upstream / ".github" / "workflows" / "launcher.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("name: launcher\n", encoding="utf-8")
        (workflow.parent / "offline-game.yml").write_text(
            "name: OfflineHorizon game release\n", encoding="utf-8"
        )
        (self.upstream / "README.md").write_text("# Official\n", encoding="utf-8")
        (self.upstream / "official.txt").write_text("base\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "upstream base")
        self.base = git(self.upstream, "rev-parse", "HEAD")
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(self.source)], check=True)
        git(self.source, "config", "user.name", "Unit test")
        git(self.source, "config", "user.email", "test@example.invalid")
        (self.source / "fork.txt").write_text("offline customization\n", encoding="utf-8")
        (self.source / "README.md").write_text("# OfflineHorizon\n", encoding="utf-8")
        git(self.source, "add", ".")
        git(self.source, "commit", "-qm", "fork customization")
        self.manifest.write_text("README.md\nfork.txt\n", encoding="utf-8")
        self.green_patch = mock.patch.object(
            sync, "latest_green_upstream_sha",
            side_effect=lambda token: (git(self.upstream, "rev-parse", "HEAD"), "green"),
        )
        self.green_patch.start()
        self.ancestry_patch = mock.patch.object(
            sync, "upstream_is_descendant", return_value=True,
        )
        self.ancestry_patch.start()

    def tearDown(self):
        self.tmp.cleanup()
        self.ci_patch.stop()
        self.green_patch.stop()
        self.ancestry_patch.stop()

    def test_red_upstream_does_not_clone_or_publish(self):
        with mock.patch.object(sync, "upstream_ci_ready",
                               return_value=(False, "ci.yml: in_progress / pending")):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest, force_sha=self.base)
        self.assertEqual(result["result"], "waiting_upstream_ci")
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])
        self.assertFalse((self.work / ".last-dry-run.json").exists())

    def test_main_advances_but_last_green_commit_is_imported(self):
        (self.upstream / "official.txt").write_text("new HEAD not yet checked\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "new unverified head")
        moved = git(self.upstream, "rev-parse", "HEAD")
        with mock.patch.object(sync, "latest_green_upstream_sha",
                               return_value=(self.base, "all green")):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest)
        self.assertEqual(result["result"], "prepared")
        self.assertEqual(result["upstream"], self.base)
        self.assertEqual(result["upstream_head"], moved)
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_old_cache_with_unverified_sha_does_not_block_last_green(self):
        (self.upstream / "official.txt").write_text("new unverified HEAD\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "not green yet")
        unverified = git(self.upstream, "rev-parse", "HEAD")
        self.work.mkdir()
        sync.safe_json_write(self.work / ".last-dry-run.json", {"upstream": unverified})
        with mock.patch.object(sync, "latest_green_upstream_sha",
                               return_value=(self.base, "all green")):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest)
        self.assertEqual(result["result"], "prepared")
        self.assertEqual(result["upstream"], self.base)
        saved = json.loads((self.work / ".last-dry-run.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, {"upstream": self.base, "selection": "green"})

    def test_already_synced_last_green_does_not_rebuild(self):
        self.work.mkdir()
        sync.safe_json_write(self.work / ".last-dry-run.json",
                             {"upstream": self.base, "selection": "green"})
        (self.upstream / "official.txt").write_text("new HEAD not yet checked\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "new red head")
        with mock.patch.object(sync, "latest_green_upstream_sha",
                               return_value=(self.base, "all green")):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest)
        self.assertEqual(result["result"], "unchanged")
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_green_commit_older_than_patch_base_is_ignored(self):
        self.work.mkdir()
        with (mock.patch.object(sync, "latest_green_upstream_sha",
                                return_value=(self.base, "green")),
              mock.patch.object(sync, "upstream_is_descendant",
                                side_effect=[True, False])):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest)
        self.assertEqual(result["result"], "waiting_green_after_base")
        self.assertEqual(result["last_green"], self.base)
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_does_not_go_backward_to_older_green(self):
        self.work.mkdir()
        sync.safe_json_write(self.work / ".last-dry-run.json", {"upstream": self.base})
        (self.upstream / "official.txt").write_text("new HEAD\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "new head")
        with (mock.patch.object(sync, "latest_green_upstream_sha",
                                return_value=(git(self.upstream, "rev-parse", "HEAD"), "green")),
              mock.patch.object(sync, "upstream_is_descendant", return_value=False)):
            result = sync.run_once(dry_run=True, source=self.source,
                                   work_root=self.work, upstream=str(self.upstream),
                                   fork=str(self.source), base_sha=self.base,
                                   manifest=self.manifest)
        self.assertEqual(result["result"], "upstream_history_changed")
        self.assertFalse(result["pushed"])

    def test_initial_overlay_includes_reviewed_untracked_workflow(self):
        file = self.source / ".github" / "workflows" / "owner-release.yml"
        file.write_text("name: Custom OfflineHorizon game release\n", encoding="utf-8")
        self.manifest.write_text("README.md\nfork.txt\n.github/workflows/owner-release.yml\n",
                                 encoding="utf-8")
        result = sync.run_once(dry_run=True, source=self.source,
                               work_root=self.work, upstream=str(self.upstream),
                               fork=str(self.source), base_sha=self.base,
                               manifest=self.manifest, force_sha=self.base)
        self.assertEqual(result["result"], "prepared")
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_initial_overlay_and_clean_workdir(self):
        result = sync.run_once(dry_run=True, source=self.source, work_root=self.work,
                               upstream=str(self.upstream), fork=str(self.source),
                               base_sha=self.base, manifest=self.manifest,
                               force_sha=self.base)
        self.assertEqual(result["mode"], "bootstrap")
        self.assertGreater(result["patch_bytes"], 0)
        self.assertFalse(result["pushed"])
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_incremental_update_and_unchanged_sha(self):
        (self.source / sync.TRACKER).write_text(self.base + "\n", encoding="ascii")
        git(self.source, "add", ".")
        git(self.source, "commit", "-qm", "upstream marker")
        (self.upstream / "official.txt").write_text("base\nnew official change\n",
                                                    encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "new upstream source")
        latest = git(self.upstream, "rev-parse", "HEAD")
        update = sync.run_once(dry_run=True, source=self.source, work_root=self.work,
                               upstream=str(self.upstream), fork=str(self.source),
                               base_sha=self.base, manifest=self.manifest,
                               force_sha=latest)
        self.assertEqual(update["mode"], "incremental")
        self.assertFalse(update["pushed"])
        unchanged = sync.run_once(dry_run=True, source=self.source, work_root=self.work,
                                  upstream=str(self.upstream), fork=str(self.source),
                                  base_sha=self.base, manifest=self.manifest,
                                  force_sha=self.base)
        self.assertEqual(unchanged["result"], "unchanged")
        self.assertEqual(list(self.work.glob("sync-*")), [])

    def test_incremental_reconciles_stale_unowned_content_and_new_files(self):
        (self.source / sync.TRACKER).write_text(self.base + "\n", encoding="ascii")
        (self.source / "official.txt").write_text("fork older snapshot\n", encoding="utf-8")
        git(self.source, "add", ".")
        git(self.source, "commit", "-qm", "record stale snapshot")
        remote = self.root / "remote-stale.git"
        subprocess.run(["git", "clone", "--bare", "-q", str(self.source), str(remote)], check=True)
        (self.upstream / "official.txt").write_text("latest green official\n", encoding="utf-8")
        (self.upstream / "new-official.txt").write_text("new upstream file\n", encoding="utf-8")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-qm", "new green upstream")
        latest = git(self.upstream, "rev-parse", "HEAD")
        previous = os.environ.get("GH_TOKEN")
        os.environ["GH_TOKEN"] = "unit-test-placeholder-not-a-real-token"
        try:
            updated = sync.run_once(
                dry_run=False, source=self.source, work_root=self.work,
                upstream=str(self.upstream), fork=str(remote),
                base_sha=self.base, manifest=self.manifest, force_sha=latest)
            self.assertEqual(updated["mode"], "incremental")
            self.assertGreaterEqual(updated["official_file_updates"], 2)
            self.assertEqual(git(remote, "show", "main:official.txt"), "latest green official")
            self.assertEqual(git(remote, "show", "main:new-official.txt"), "new upstream file")
            self.assertEqual(git(remote, "show", "main:fork.txt"), "offline customization")
            self.assertEqual(git(remote, "show", f"main:{sync.TRACKER}"), latest)
        finally:
            if previous is None:
                os.environ.pop("GH_TOKEN", None)
            else:
                os.environ["GH_TOKEN"] = previous


    def test_local_commits_are_preserved_by_fast_forward_sync(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "clone", "--bare", "-q", str(self.upstream), str(remote)],
                       check=True)
        original_source = git(self.source, "rev-parse", "HEAD")
        previous_token = os.environ.get("GH_TOKEN")
        os.environ["GH_TOKEN"] = "unit-test-placeholder-not-a-real-token"
        try:
            initial = sync.run_once(
                dry_run=False, source=self.source, work_root=self.work,
                upstream=str(self.upstream), fork=str(remote),
                base_sha=self.base, manifest=self.manifest,
                force_sha=self.base,
            )
            self.assertEqual(initial["result"], "pushed")
            self.assertEqual(initial["fork_parent"], original_source)
            first = git(remote, "rev-parse", "refs/heads/main")
            self.assertEqual(git(remote, "show", "main:fork.txt"), "offline customization")
            self.assertEqual(git(remote, "show", f"main:{sync.TRACKER}"), self.base)
            self.assertEqual(git(remote, "rev-parse", "main^"), original_source)

            (self.upstream / "official.txt").write_text("base\nnew official change\n",
                                                        encoding="utf-8")
            git(self.upstream, "add", ".")
            git(self.upstream, "commit", "-qm", "upstream second commit")
            latest = git(self.upstream, "rev-parse", "HEAD")
            second = sync.run_once(
                dry_run=False, source=self.source, work_root=self.work,
                upstream=str(self.upstream), fork=str(remote),
                base_sha=self.base, manifest=self.manifest,
                force_sha=latest,
            )
            self.assertEqual(second["result"], "pushed")
            self.assertEqual(second["mode"], "incremental")
            self.assertEqual(second["fork_parent"], first)
            self.assertEqual(git(remote, "show", "main:official.txt"),
                             "base\nnew official change")
            self.assertEqual(git(remote, "show", "main:fork.txt"), "offline customization")
            self.assertEqual(git(remote, "show", f"main:{sync.TRACKER}"), latest)
            again = sync.run_once(
                dry_run=False, source=self.source, work_root=self.work,
                upstream=str(self.upstream), fork=str(remote),
                base_sha=self.base, manifest=self.manifest,
                force_sha=latest,
            )
            self.assertEqual(again["result"], "unchanged")
            self.assertEqual(list(self.work.glob("sync-*")), [])
        finally:
            if previous_token is None:
                os.environ.pop("GH_TOKEN", None)
            else:
                os.environ["GH_TOKEN"] = previous_token



if __name__ == "__main__":
    unittest.main()

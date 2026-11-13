#!/usr/bin/env python3
"""Release orchestration uses fabricated API responses, never a live release."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

module_path = Path(__file__).parents[1] / "release_guard.py"
spec = importlib.util.spec_from_file_location("offline_release_guard", module_path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

HEAD = "a" * 40


def release(kind, *, complete=True, sha=HEAD):
    assets = sorted(guard.REQUIRED[kind])
    if not complete:
        assets = assets[:-1]
    return {
        "tag_name": "v0.2.10",
        "target_commitish": sha,
        "draft": False,
        "assets": [{"name": name, "state": "uploaded", "size": 20} for name in assets],
    }


def run(status, conclusion=None, *, event="workflow_dispatch", attempts=1, sha=HEAD):
    return {
        "head_sha": sha,
        "head_branch": "main",
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempts,
    }


class ReleasePlanningTests(unittest.TestCase):
    def test_no_previous_release_or_run_dispatches_one_combined_release(self):
        for kind in guard.REQUIRED:
            self.assertEqual(guard.plan(kind, HEAD, [], []), "dispatch")

    def test_complete_release_never_rebuilds(self):
        for kind in guard.REQUIRED:
            self.assertEqual(
                guard.plan(kind, HEAD, [release(kind)],
                           [run("completed", "failure")]), "published"
            )

    def test_other_commits_are_not_considered_published(self):
        kind = "offline-game.yml"
        old = "b" * 40
        self.assertEqual(
            guard.plan(kind, HEAD, [release(kind, sha=old)],
                       [run("completed", "success", sha=old)]),
            "dispatch",
        )

    def test_rebuilt_release_records_its_source_when_the_tag_is_older(self):
        kind = "offline-game.yml"
        rebuilt = release(kind, sha="b" * 40)
        rebuilt["body"] = f"OfflineHorizon release\n\nBuild commit: {HEAD}\n"
        self.assertEqual(guard.plan(kind, HEAD, [rebuilt], []), "published")

    def test_partial_release_blocks_unsafe_overwrite(self):
        for kind in guard.REQUIRED:
            self.assertEqual(
                guard.plan(kind, HEAD, [release(kind, complete=False)], []),
                "incomplete_release",
            )

    def test_current_build_blocks_duplicate_dispatch(self):
        for status in ("queued", "in_progress", "waiting", "pending", "requested"):
            with self.subTest(status=status):
                self.assertEqual(
                    guard.plan("offline-game.yml", HEAD, [], [run(status)]), "running"
                )

    def test_success_without_release_requires_attention(self):
        self.assertEqual(
            guard.plan("offline-game.yml", HEAD, [], [run("completed", "success")]),
            "successful_run_without_release",
        )

    def test_failed_job_retries_up_to_three_attempts(self):
        kind = "offline-game.yml"
        self.assertEqual(
            guard.plan(kind, HEAD, [], [run("completed", "failure")]),
            "dispatch",
        )
        self.assertEqual(
            guard.plan(kind, HEAD, [], [run("completed", "failure", attempts=3)]),
            "retry_limit",
        )
        self.assertEqual(
            guard.plan(kind, HEAD, [],
                       [run("completed", "failure"), run("completed", "failure"),
                        run("completed", "cancelled")]),
            "retry_limit",
        )

    def test_reject_bad_sha_or_unknown_workflow(self):
        with self.assertRaises(guard.ReleaseGuardError):
            guard.plan("offline-game.yml", "wrong", [], [])
        with self.assertRaises(guard.ReleaseGuardError):
            guard.plan("other.yml", HEAD, [], [])



class ReleaseSourceTreeTests(unittest.TestCase):
    def setUp(self):
        self.old, self.head = "b" * 40, "a" * 40
        self.old_tree, self.new_tree = "1" * 40, "2" * 40
        self.old_tools, self.new_tools = "3" * 40, "4" * 40
        self.api_data = {
            f"repos/YourPancakes/OfflineHorizon/git/commits/{self.old}": {"tree": {"sha": self.old_tree}},
            f"repos/YourPancakes/OfflineHorizon/git/commits/{self.head}": {"tree": {"sha": self.new_tree}},
            f"repos/YourPancakes/OfflineHorizon/git/trees/{self.old_tree}": {
                "truncated": False, "tree": [
                    {"path": ".github", "mode": "040000", "type": "tree", "sha": "5" * 40},
                    {"path": "tools", "mode": "040000", "type": "tree", "sha": self.old_tools},
                    {"path": "launcher", "mode": "040000", "type": "tree", "sha": "7" * 40}]},
            f"repos/YourPancakes/OfflineHorizon/git/trees/{self.new_tree}": {
                "truncated": False, "tree": [
                    {"path": ".github", "mode": "040000", "type": "tree", "sha": "6" * 40},
                    {"path": "tools", "mode": "040000", "type": "tree", "sha": self.new_tools},
                    {"path": "launcher", "mode": "040000", "type": "tree", "sha": "7" * 40}]},
            f"repos/YourPancakes/OfflineHorizon/git/trees/{self.old_tools}": {
                "truncated": False, "tree": [
                    {"path": "offlinehorizon_sync", "mode": "040000", "type": "tree", "sha": "8" * 40},
                    {"path": "check_pe_arch.py", "mode": "100644", "type": "blob", "sha": "9" * 40}]},
            f"repos/YourPancakes/OfflineHorizon/git/trees/{self.new_tools}": {
                "truncated": False, "tree": [
                    {"path": "offlinehorizon_sync", "mode": "040000", "type": "tree", "sha": "a" * 40},
                    {"path": "check_pe_arch.py", "mode": "100644", "type": "blob", "sha": "9" * 40}]},
        }
        self.published = release("offline-game.yml", sha=self.old)
        self.published["body"] = "Build commit: " + self.old
        for a in self.published["assets"]:
            a["digest"] = "sha256:" + "d" * 64

    def ready(self):
        return guard.equivalent_published_release(self.head, [self.published], "test-token")

    def test_ci_only_changes_keep_published_release(self):
        with patch.object(guard, "api", side_effect=lambda path, _: self.api_data[path]):
            self.assertTrue(self.ready())

    def test_modified_launcher_requires_new_build(self):
        self.api_data[f"repos/YourPancakes/OfflineHorizon/git/trees/{self.new_tree}"]["tree"][2]["sha"] = "c" * 40
        with patch.object(guard, "api", side_effect=lambda path, _: self.api_data[path]):
            self.assertFalse(self.ready())

    def test_modified_build_helper_requires_new_build(self):
        self.api_data[f"repos/YourPancakes/OfflineHorizon/git/trees/{self.new_tools}"]["tree"][1]["sha"] = "c" * 40
        with patch.object(guard, "api", side_effect=lambda path, _: self.api_data[path]):
            self.assertFalse(self.ready())

    def test_missing_digest_never_counts_as_published(self):
        self.published["assets"][0]["digest"] = None
        with patch.object(guard, "api", side_effect=lambda path, _: self.api_data[path]):
            self.assertFalse(self.ready())

    def test_unavailable_git_tree_fails_closed(self):
        with patch.object(guard, "api", side_effect=guard.ReleaseGuardError("unavailable")):
            with self.assertRaises(guard.ReleaseGuardError):
                self.ready()


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Release orchestration uses fabricated API responses, never a live release."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()

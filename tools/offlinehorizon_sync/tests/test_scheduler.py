"""Regression tests for the official-green event watcher and fail-closed dispatch."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scheduler

GREEN_1 = "a" * 40
GREEN_2 = "b" * 40
FORK_MAIN = "c" * 40
CANDIDATE_1 = "d" * 40
CANDIDATE_2 = "e" * 40


def outcome(green: str, candidate: str) -> dict:
    return {
        "result": "candidate_pushed",
        "upstream": green,
        "branch": f"offlinehorizon/candidate/{green}-{FORK_MAIN[:12]}",
        "commit": candidate,
    }


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        state = Path(self.temp.name) / "watcher.json"
        self.path = mock.patch.object(scheduler, "STATE", state)
        self.path.start()
        self.addCleanup(self.path.stop)

    def test_green_candidate_dispatches_once_after_success(self):
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha", return_value=(GREEN_1, "green")),
            mock.patch.object(scheduler, "fork_main", return_value=FORK_MAIN),
            mock.patch.object(scheduler, "run_sync", return_value=outcome(GREEN_1, CANDIDATE_1)) as sync,
            mock.patch.object(scheduler, "existing_dispatch", return_value=False),
            mock.patch.object(scheduler, "dispatch") as dispatch,
        ):
            self.assertEqual(scheduler.cycle("fake-token"), "candidate_pushed")
            self.assertEqual(scheduler.cycle("fake-token"), "unchanged")
            sync.assert_called_once()
            dispatch.assert_called_once()
        state = json.loads(scheduler.STATE.read_text())
        self.assertEqual(state["candidate"], CANDIDATE_1)

    def test_multiple_updates_uses_new_latest_green_even_if_nightly_is_unchanged(self):
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha",
                              side_effect=[(GREEN_1, "green"), (GREEN_2, "green")]),
            mock.patch.object(scheduler, "fork_main", return_value=FORK_MAIN),
            mock.patch.object(scheduler, "run_sync", side_effect=[
                outcome(GREEN_1, CANDIDATE_1), outcome(GREEN_2, CANDIDATE_2),
            ]) as stage,
            mock.patch.object(scheduler, "existing_dispatch", return_value=False),
            mock.patch.object(scheduler, "dispatch") as dispatch,
        ):
            self.assertEqual(scheduler.cycle("token"), "candidate_pushed")
            self.assertEqual(scheduler.cycle("token"), "candidate_pushed")
        self.assertEqual(stage.call_count, 2)
        self.assertEqual(dispatch.call_count, 2)

    def test_dispatch_failure_does_not_advance_state(self):
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha",
                              return_value=(GREEN_1, "green")),
            mock.patch.object(scheduler, "fork_main", return_value=FORK_MAIN),
            mock.patch.object(scheduler, "run_sync", return_value=outcome(GREEN_1, CANDIDATE_1)),
            mock.patch.object(scheduler, "existing_dispatch", return_value=False),
            mock.patch.object(scheduler, "dispatch", side_effect=RuntimeError("403 forbidden")),
        ):
            with self.assertRaises(RuntimeError):
                scheduler.cycle("token")
        self.assertFalse(scheduler.STATE.exists())

    def test_red_official_revision_does_not_start_sync(self):
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha",
                              return_value=(None, "mandatory check pending")),
            mock.patch.object(scheduler, "run_sync") as stage,
        ):
            self.assertEqual(scheduler.cycle("token"), "waiting_upstream_ci")
            stage.assert_not_called()
        self.assertFalse(scheduler.STATE.exists())

    def test_invalid_candidate_ref_blocks_dispatch(self):
        bad = outcome(GREEN_1, CANDIDATE_1)
        bad["branch"] = "main"
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha",
                              return_value=(GREEN_1, "green")),
            mock.patch.object(scheduler, "fork_main", return_value=FORK_MAIN),
            mock.patch.object(scheduler, "run_sync", return_value=bad),
            mock.patch.object(scheduler, "dispatch") as dispatch,
        ):
            with self.assertRaises(ValueError):
                scheduler.cycle("token")
            dispatch.assert_not_called()
        self.assertFalse(scheduler.STATE.exists())

    def test_existing_dispatch_is_not_duplicate(self):
        ready = outcome(GREEN_1, CANDIDATE_1)
        ready["result"] = "candidate_exists"
        with (
            mock.patch.object(scheduler, "latest_green_upstream_sha",
                              return_value=(GREEN_1, "green")),
            mock.patch.object(scheduler, "fork_main", return_value=FORK_MAIN),
            mock.patch.object(scheduler, "run_sync", return_value=ready),
            mock.patch.object(scheduler, "existing_dispatch", return_value=True),
            mock.patch.object(scheduler, "dispatch") as dispatch,
        ):
            self.assertEqual(scheduler.cycle("token"), "candidate_exists")
            dispatch.assert_not_called()
        self.assertTrue(scheduler.STATE.exists())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression coverage for 1st/15th UTC synchronization and publication windows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest

p = Path(__file__).parents[1] / "calendar_schedule.py"
spec = importlib.util.spec_from_file_location("calendar_schedule", p)
calendar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calendar)


class CalendarScheduleTests(unittest.TestCase):
    def when(self, y: int, m: int, d: int, h=3, minute=0):
        return datetime(y, m, d, h, minute, tzinfo=timezone.utc)

    def test_only_first_and_fifteenth(self):
        for day in (1, 15):
            self.assertEqual(calendar.due_slot(self.when(2027, 1, day), ""), f"2027-01-{day:02d}")
            self.assertIsNone(calendar.due_slot(self.when(2027, 1, day, 2, 59), ""))
        for day in (2, 7, 14, 16, 28, 31):
            self.assertIsNone(calendar.due_slot(self.when(2027, 1, day), ""))

    def test_no_duplicate_after_restart_and_month_transition(self):
        with tempfile.TemporaryDirectory() as dirname:
            state = Path(dirname) / ".last-sync-slot"
            slot = calendar.due_slot(self.when(2027, 1, 1), calendar.read_slot(state))
            self.assertEqual(slot, "2027-01-01")
            calendar.mark_slot(state, slot)
            self.assertEqual(calendar.read_slot(state), slot)
            self.assertIsNone(calendar.due_slot(self.when(2027, 1, 1, 22), calendar.read_slot(state)))
            self.assertEqual(calendar.due_slot(self.when(2027, 1, 15), calendar.read_slot(state)), "2027-01-15")
            calendar.mark_slot(state, "2027-01-15")
            self.assertEqual(calendar.due_slot(self.when(2027, 2, 1), calendar.read_slot(state)), "2027-02-01")

    def test_utc_normalization(self):
        local = datetime(2027, 1, 15, 4, 10, tzinfo=timezone(timedelta(hours=1)))
        self.assertEqual(calendar.due_slot(local, ""), "2027-01-15")

    def test_reject_invalid_or_symlink_state(self):
        with tempfile.TemporaryDirectory() as dirname:
            state = Path(dirname) / "schedule"
            state.write_text("garbage", encoding="ascii")
            with self.assertRaises(RuntimeError):
                calendar.read_slot(state)
            state.unlink()
            state.symlink_to(Path(dirname) / "other")
            with self.assertRaises(RuntimeError):
                calendar.read_slot(state)
            with self.assertRaises(RuntimeError):
                calendar.mark_slot(state, "2027-01-15")

    def test_no_timezone_naive_date(self):
        with self.assertRaises(ValueError):
            calendar.due_slot(datetime(2027, 1, 1, 3), "")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Synchronize upstream source on the 1st and 15th at 03:00 UTC.

No immediate run on startup; no 4-hour checks. A persistent slot marker
prevents duplicate runs if Docker restarts during a scheduled day.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

from calendar_schedule import HOUR, DAYS, due_slot, mark_slot, read_slot

STATE = Path(os.environ.get("SYNC_SCHEDULE_STATE", "/work/.last-sync-slot"))


def main() -> None:
    print(f"Source sync scheduled for UTC days {DAYS} at {HOUR:02d}:00; state={STATE}", flush=True)
    while True:
        try:
            now = datetime.now(timezone.utc)
            slot = due_slot(now, read_slot(STATE))
            if slot:
                mark_slot(STATE, slot)
                print(f"[{now.isoformat()}] Checking approved Horizon upstream; slot={slot}", flush=True)
                try:
                    result = subprocess.run(
                        [sys.executable, "/app/sync.py", "--once"],
                        check=False,
                        timeout=3600,
                    )
                    if result.returncode:
                        print(f"Source synchronization failed (exit={result.returncode}). "
                              "No GitHub branch was overwritten.", flush=True)
                except subprocess.TimeoutExpired:
                    print("Synchronization timed out; no release was authorized.", flush=True)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Calendar schedule is blocked: {exc}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()

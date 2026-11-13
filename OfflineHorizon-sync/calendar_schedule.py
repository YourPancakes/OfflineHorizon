#!/usr/bin/env python3
"""UTC calendar gate for source synchronization and release verification.

Run at 03:00 UTC on the 1st and 15th of every month, at most once per
calendar slot. Attempts are durably recorded BEFORE running to prevent
duplicate operations across container restarts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile

DAYS = (1, 15)
HOUR = 3
SLOT_RE = re.compile(r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:01|15)$")


def due_slot(now: datetime, last: str) -> str | None:
    """Return the UTC run slot if it has started and has not been attempted."""
    if now.tzinfo is None:
        raise ValueError("Expected a timezone-aware UTC datetime")
    utc = now.astimezone(timezone.utc)
    if utc.day not in DAYS or utc.hour < HOUR:
        return None
    key = utc.strftime("%Y-%m-%d")
    return key if key != last else None


def read_slot(state: Path) -> str:
    if state.is_symlink():
        raise RuntimeError("Refusing symlink schedule state")
    try:
        saved = state.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return ""
    if not SLOT_RE.fullmatch(saved):
        raise RuntimeError("Invalid persisted schedule state; refusing duplicate run")
    return saved


def mark_slot(state: Path, slot: str) -> None:
    """Atomically persist the run slot before executing external code."""
    if not SLOT_RE.fullmatch(slot) or state.is_symlink():
        raise RuntimeError("Invalid schedule state path or slot")
    if not state.parent.is_dir():
        raise RuntimeError("Schedule state volume is not mounted")
    fd, temp = tempfile.mkstemp(prefix=".sync-slot-", dir=state.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(slot + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, state)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

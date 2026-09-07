"""Tracking the running pet: where it logs, and whether it's up.

Only needed because `meow` hands the terminal back rather than holding it. Once
the pet is off on its own, the terminal has no idea whether it is still alive,
so `meow status` and `meow stop` need a way to find it again.

Deliberately a pid file rather than anything cleverer: there is exactly one pet
per user, it is a desktop toy, and a stale file costs nothing because liveness
is always confirmed against the process table before it is believed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "meowsage"
PID_PATH = _SUPPORT_DIR / "meow.pid"

# Shared with the LaunchAgent on purpose. However the pet was started, its
# output belongs in one file, or "check the log" becomes a question of which.
LOG_PATH = Path.home() / "Library" / "Logs" / "meowsage.log"


def write_pid(pid: int) -> None:
    _SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{pid}\n")


def clear_pid() -> None:
    try:
        PID_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def running_pid() -> Optional[int]:
    """The live pet's pid, or None. Clears the pid file if it's stale."""
    try:
        pid = int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if _is_meowsage(pid):
        return pid
    clear_pid()
    return None


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # alive, just not ours to signal
    except OSError:
        return False
    return True


def _is_meowsage(pid: int) -> bool:
    """Guard against pid reuse: the pid is only ours if it's still our program.

    Between the pet exiting and someone reading the pid file, the number can be
    handed to something entirely unrelated — and `meow stop` must never kill a
    stranger's process on the strength of a leftover file.
    """
    if pid <= 0 or not _pid_exists(pid):
        return False
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    return "meowsage" in result.stdout

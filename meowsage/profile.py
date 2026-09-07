"""Persisted per-user pet profile (currently just a name).

Stored outside the repo/package so it survives reinstalls and upgrades, in
the OS-conventional per-user app-data directory:
- macOS:   ~/Library/Application Support/meowsage/profile.json
- Windows: %APPDATA%/meowsage/profile.json
- Linux:   $XDG_DATA_HOME/meowsage/profile.json (or ~/.local/share/...)
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


def _support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


_SUPPORT_DIR = _support_dir()
_PROFILE_DIR = _SUPPORT_DIR / "meowsage"
_PROFILE_PATH = _PROFILE_DIR / "profile.json"

# Where profiles lived when the app was called "Usage Pet" — a macOS-only
# path, since the rename predates any cross-platform support. Read once, on
# the first launch after the rename, so nobody's cat forgets its name — see
# _migrate_legacy_profile.
_LEGACY_PROFILE_PATH = (
    Path.home() / "Library" / "Application Support" / "usage-pet" / "profile.json"
)

DEFAULT_NAME = "Meowsage"
MAX_NAME_LENGTH = 32
NAME_TYPE_ERROR = "name must be text"
NAME_EMPTY_ERROR = "name can't be empty"
NAME_LENGTH_ERROR = f"name must be {MAX_NAME_LENGTH} characters or fewer"
NAME_CHARACTER_ERROR = "name must stay on one line and contain no control characters"


def validate_name(name: str) -> str:
    """Validate and normalize a user-supplied cat name."""
    if not isinstance(name, str):
        raise ValueError(NAME_TYPE_ERROR)
    if any(unicodedata.category(character) in {"Cc", "Cs", "Zl", "Zp"} for character in name):
        raise ValueError(NAME_CHARACTER_ERROR)
    normalized = name.strip()
    if not normalized:
        raise ValueError(NAME_EMPTY_ERROR)
    if len(normalized) > MAX_NAME_LENGTH:
        raise ValueError(NAME_LENGTH_ERROR)
    return normalized


@dataclass
class Profile:
    name: str = DEFAULT_NAME


def _load_profile(path: Path) -> Optional[Profile]:
    """Read and validate one persisted profile, without modifying it."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (ValueError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name", DEFAULT_NAME)
    try:
        return Profile(name=validate_name(name))
    except ValueError:
        return None


def load() -> Optional[Profile]:
    if _PROFILE_PATH.exists():
        return _load_profile(_PROFILE_PATH)
    return _migrate_legacy_profile()


def _migrate_legacy_profile() -> Optional[Profile]:
    """Adopt a pre-rename profile, if one is there.

    The old directory is left in place rather than moved: a failed migration
    should cost nothing, and an upgrade that the user later rolls back should
    still find its profile where it left it.
    """
    if not _LEGACY_PROFILE_PATH.exists():
        return None
    migrated = _load_profile(_LEGACY_PROFILE_PATH)
    if migrated is None:
        return None
    try:
        save(migrated)
    except OSError:
        # Not fatal — the name is still correct for this run, and the next
        # launch will simply try the migration again.
        pass
    return migrated


def save(profile: Profile) -> None:
    profile.name = validate_name(profile.name)
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(
        json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_or_run_setup() -> Profile:
    """Return the saved profile, running a first-run naming prompt if none exists.

    Never blocks on a question it has no way to ask. Double-clicking the app
    bundle, or starting at login, gives the process no terminal — asking there
    used to raise EOFError and kill the app before a window ever appeared, with
    nothing on screen to say why. A cat called Meowsage beats no cat at all.
    """
    existing = load()
    if existing is not None:
        return existing
    if not can_prompt():
        # Deliberately *not* saved. Leaving the profile absent means a later
        # launch from a terminal still gets to ask the question, instead of one
        # double-click silently committing the user to the default forever.
        return Profile()
    return _run_setup_wizard()


def can_prompt() -> bool:
    """Is there a terminal on the other end to answer a question?"""
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):    # detached or closed stdin
        return False


def _run_setup_wizard() -> Profile:
    print("Welcome to Meowsage!")
    while True:
        try:
            raw_name = input("What should we call your cat? [Meowsage]: ")
        except EOFError:
            # isatty() said yes and the read still ended. Whatever the cause,
            # the answer is the same: don't die over a name.
            print()
            return Profile()
        try:
            name = validate_name(raw_name)
        except ValueError as exc:
            if str(exc) == NAME_EMPTY_ERROR:
                name = DEFAULT_NAME
                break
            print(f"That {exc}.")
            continue
        break
    profile = Profile(name=name)
    save(profile)
    print(f"Nice to meet you, {name}! (Rename anytime with `meow rename`.)")
    return profile

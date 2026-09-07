"""Builds a Start Menu / Startup shortcut, so Windows shows the cat icon.

pipx and uv generate the `meow.exe` console-script launcher from a generic
stub, and Windows shows that stub's own baked-in icon wherever the exe itself
is referenced (Explorer, a pinned taskbar icon, a Start Menu search hit)
unless something else supplies one. Patching the icon resource inside that
launcher exe in place is possible in principle, but it is a binary owned by
pipx/uv that gets regenerated on every reinstall or upgrade, so anything
written into it would be silently lost.

Instead this builds a separate `.lnk` shortcut that points at `meow.exe` but
carries its own `IconLocation` — the same mechanism every Windows installer
uses to give a plain console-script exe a real-looking icon. It's built
through PowerShell's `WScript.Shell` COM object (`New-Object -ComObject
WScript.Shell`) rather than a Python COM library, so installing the pet on
Windows doesn't need an extra dependency beyond what pipx/uv already pull in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .artwork import app_icon_ico_path

APP_NAME = "Meowsage"

_START_MENU_DIR = (
    Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
)
_STARTUP_DIR = _START_MENU_DIR / "Startup"


class BuildError(RuntimeError):
    pass


def start_menu_shortcut_path() -> Path:
    return _START_MENU_DIR / f"{APP_NAME}.lnk"


def startup_shortcut_path() -> Path:
    return _STARTUP_DIR / f"{APP_NAME}.lnk"


def _powershell_quote(value: str) -> str:
    # Single-quoted PowerShell strings treat '' as a literal quote; that's the
    # only character in a filesystem path that would otherwise break out of
    # the string.
    return value.replace("'", "''")


def _write_shortcut(link_path: Path, target: Path, icon: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{_powershell_quote(str(link_path))}'); "
        f"$sc.TargetPath = '{_powershell_quote(str(target))}'; "
        f"$sc.IconLocation = '{_powershell_quote(str(icon))}'; "
        f"$sc.WorkingDirectory = '{_powershell_quote(str(target.parent))}'; "
        "$sc.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BuildError(f"powershell shortcut creation failed:\n{result.stderr.strip()}")


def _check_platform() -> None:
    if sys.platform != "win32":
        raise BuildError("Windows shortcuts can only be built on Windows.")


def build(meow_exe: Path) -> Path:
    """Create/replace the Start Menu shortcut. Returns its path."""
    _check_platform()
    icon = app_icon_ico_path()
    if not icon.exists():
        raise BuildError(f"icon not found at {icon}")
    link = start_menu_shortcut_path()
    _write_shortcut(link, meow_exe, icon)
    return link


def build_startup(meow_exe: Path) -> Path:
    """Create/replace the Startup-folder shortcut. Returns its path."""
    _check_platform()
    icon = app_icon_ico_path()
    if not icon.exists():
        raise BuildError(f"icon not found at {icon}")
    link = startup_shortcut_path()
    _write_shortcut(link, meow_exe, icon)
    return link


def remove_startup() -> bool:
    """Delete the Startup-folder shortcut, if one is there. True if it was."""
    link = startup_shortcut_path()
    if link.exists():
        link.unlink()
        return True
    return False

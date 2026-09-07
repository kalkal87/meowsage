"""Command-line entry point for the `meow` console script.

`meow` with no arguments launches the pet — that's the whole product, and it
hands the terminal straight back (see `_should_detach`). The remaining
subcommands manage it from outside: check on it (`status`), put it away
(`stop`), rename it, and give it a real app identity (`install-app`) and a
place at login (`enable-autostart`/`disable-autostart`), on whichever of macOS
(LaunchAgent, appbundle.py) or Windows (Start Menu/Startup shortcut,
winshortcut.py) is running.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from . import runtime

_LABEL = "com.meowsage.meow"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_LOG_PATH = runtime.LOG_PATH

# The label used before the app was renamed to Meowsage. An agent under the old
# label would go on launching at login forever, so both autostart commands clear
# it out — otherwise enabling autostart once post-rename leaves two agents.
_LEGACY_LABEL = "com.usagepet.meow"
_LEGACY_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LEGACY_LABEL}.plist"

_USAGE = """usage: meow [status|stop|rename|install-app|enable-autostart|disable-autostart]

  meow                    launch the pet
  meow status             is the cat out, and how is it doing?
  meow stop               put the cat away
  meow rename [name]      rename your cat (prompts if no name given)
  meow install-app        macOS: build Meowsage.app, so the Dock says "Meowsage"
                           Windows: add a Start Menu shortcut with the cat icon
  meow enable-autostart   start meow automatically at login
  meow disable-autostart  stop starting meow automatically at login
  meow version            print the installed version

  meow --foreground       launch and hold the terminal (for development)
"""


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _launch()
    elif args[0] in ("-h", "--help", "help"):
        print(_USAGE)
    elif args[0] in ("-V", "--version", "version"):
        _version()
    elif args[0] in ("-f", "--foreground"):
        _launch(foreground=True)
    elif args[0] == "status":
        _status()
    elif args[0] == "stop":
        _stop()
    elif args[0] == "rename":
        _rename(args[1:])
    elif args[0] == "install-app":
        _install_app()
    elif args[0] == "enable-autostart":
        _enable_autostart()
    elif args[0] == "disable-autostart":
        _disable_autostart()
    else:
        print(f"meow: unknown argument '{args[0]}'\n")
        print(_USAGE)
        sys.exit(1)


def _version() -> None:
    from . import __version__

    print(f"meowsage {__version__}")


# ---------------------------------------------------------------------------
# Launching
# ---------------------------------------------------------------------------


def _launch(foreground: bool = False) -> None:
    from . import banner
    from . import profile as profile_store

    # Printed before .app is imported: that import pulls in PySide6, which takes
    # long enough to look like a hang without something on screen first.
    banner.show()

    # Naming happens here, in the parent, while a terminal is still attached —
    # the detached child inherits a profile that already exists.
    is_first_run = profile_store.load() is None
    active_profile = profile_store.load_or_run_setup()
    # A profile now existing means the wizard actually ran, rather than being
    # skipped for want of a terminal — i.e. someone is sitting at a prompt.
    if is_first_run and profile_store.load() is not None:
        _offer_app_install()

    if not foreground and _should_detach():
        _launch_detached(active_profile.name)
        return

    runtime.write_pid(os.getpid())
    try:
        from .app import main as run_app

        run_app(pet_name=active_profile.name)
    finally:
        runtime.clear_pid()


def _offer_app_install() -> None:
    """Offer to build the app bundle, once, at the end of first-run setup.

    `install-app` is the difference between "a Python process in a terminal"
    and something macOS calls Meowsage and gives its own icon — and it was the
    third line of a help screen most people never open. First run is the one
    moment we reliably have both a terminal and the user's attention.

    Offered rather than done quietly: it compiles a launcher and writes into
    ~/Applications, which is not something to do to someone by surprise. And it
    never blocks the cat — every failure path here falls through to a running
    pet, because a missing Dock label is a far smaller problem than no pet.
    """
    if sys.platform != "darwin" or _installed_app() is not None:
        return

    from . import appbundle

    print()
    print('One more thing: started from a terminal, macOS labels the pet')
    print('"Python" in the Dock and the Cmd-Tab switcher. Installing it as a')
    print("real app in ~/Applications is what makes it say Meowsage.")
    try:
        answer = input("Set that up now? [Y/n]: ").strip().lower()
    except EOFError:
        return
    if answer and not answer.startswith("y"):
        print("No problem — `meow install-app` does it any time.")
        return

    print("Building (this takes a few seconds)...")
    try:
        app = appbundle.build()
    except appbundle.BuildError as exc:
        print(f"meow: {exc}")
        print("      The cat still works — `meow install-app` retries this.")
        return
    print(f"meow: built {app}")
    print("      Launch it from Spotlight or the Finder next time.")


def _should_detach() -> bool:
    """Only background the pet when there is a terminal worth handing back.

    Launched from the .app bundle or the LaunchAgent there is no terminal, and
    detaching there is actively wrong: the bundle's process *is* the app as far
    as macOS is concerned, so exiting it immediately would drop the Dock name
    that `install-app` exists to provide, and launchd would see the job die.
    A tty is what distinguishes the two cases, and it needs no flag passed
    through from a bundle that may have been built by an older version.
    """
    return sys.stdout.isatty() and sys.stdin.isatty()


def _launch_detached(pet_name: str) -> None:
    existing = runtime.running_pid()
    if existing is not None:
        print(f"meow: {pet_name} is already out (pid {existing}).")
        print("      `meow status` to check on it, `meow stop` to put it away.")
        return

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = open(_LOG_PATH, "a")
    try:
        # Re-entering through `-m meowsage --foreground` rather than forking:
        # Qt has not been imported yet in this process, and starting it in a
        # child that was forked out from under a half-initialised interpreter is
        # a class of problem worth not having. sys.executable is the interpreter
        # that owns this install, so it can always import meowsage.
        proc = subprocess.Popen(
            [sys.executable, "-m", "meowsage", "--foreground"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,   # survives this terminal closing
        )
    finally:
        log.close()

    runtime.write_pid(proc.pid)
    print(f"\nmeow: {pet_name} is out (pid {proc.pid}).")
    print("      `meow status` to check on it, `meow stop` to put it away.")
    print(f"      Logs: {_LOG_PATH}")


def _stop() -> None:
    pid = runtime.running_pid()
    if pid is None:
        print("meow: the cat isn't out.")
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"meow: couldn't stop the cat (pid {pid}): {exc}")
        sys.exit(1)
    runtime.clear_pid()
    print(f"meow: cat put away (pid {pid}).")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _status() -> None:
    """What the cat is doing, without starting one.

    Reads the session logs directly rather than asking the running pet, which
    keeps this instant: the whole scoring path is plain file parsing, so status
    never imports Qt and answers in well under a second even when the pet is
    not running at all.
    """
    from . import profile as profile_store
    from .config import DEFAULT_CONFIG
    from .usage import make_default_usage_source

    active_profile = profile_store.load()
    name = active_profile.name if active_profile else profile_store.DEFAULT_NAME

    pid = runtime.running_pid()
    state = f"out and about (pid {pid})" if pid else "not running"

    source = make_default_usage_source()
    usage = source.get()
    mood_line = f"{usage.mood.value} — {_mood_explanation(usage, DEFAULT_CONFIG)}"

    rows = [
        ("cat", name),
        ("status", state),
        ("sources", _source_names(source)),
        ("mood", mood_line),
        ("autostart", "on" if _PLIST_PATH.exists() else "off"),
        ("app bundle", str(_installed_app() or "not built (`meow install-app`)")),
        ("log", str(_LOG_PATH)),
    ]
    width = max(len(label) for label, _ in rows)
    print()
    for label, value in rows:
        print(f"  {label.ljust(width)}   {value}")
    print()
    if os.environ.get("MEOWSAGE_STUB") is not None:
        print("  note: MEOWSAGE_STUB is set in this shell, so a pet launched from")
        print("        here shows a fake mood. The mood above is the real one.\n")


def _mood_explanation(usage, cfg) -> str:
    """Say *why* the cat is in this mood, in the same order _classify_mood does."""
    if usage.foreground_tokens <= 0:
        return f"nothing in the last {cfg.foreground_window_seconds}s"
    if usage.baseline_active_minutes < cfg.cold_start_min_active_minutes:
        return "just getting started, not enough history to compare against yet"
    return (
        f"busier than {usage.percentile_of_baseline:.0f}% of your last "
        f"{usage.baseline_active_minutes} active minutes"
    )


_READER_NAMES = {
    "ClaudeCodeReader": "Claude Code",
    "CodexReader": "Codex",
}


def _source_names(source) -> str:
    """Which tools' logs `status` is actually reading — the "did detection do
    the right thing" line. A stub source (MEOWSAGE_STUB set) reads nothing."""
    from .usage import StubUsageSource

    if isinstance(source, StubUsageSource):
        return "stub (MEOWSAGE_STUB is set)"
    readers = getattr(source, "readers", ())
    if not readers:
        return "none found (no ~/.claude/projects or ~/.codex/sessions)"
    return ", ".join(_READER_NAMES.get(type(r).__name__, type(r).__name__) for r in readers)


def _rename(rest: list) -> None:
    from . import profile as profile_store

    if rest:
        try:
            new_name = profile_store.validate_name(" ".join(rest))
        except ValueError as exc:
            print(f"meow: {exc}, nothing changed.")
            return
    elif not profile_store.can_prompt():
        print("meow: no terminal to ask in — try `meow rename <name>`.")
        sys.exit(1)
    else:
        while True:
            try:
                raw_name = input("New name for your cat: ")
            except EOFError:
                print()
                print("meow: name can't be empty, nothing changed.")
                return
            try:
                new_name = profile_store.validate_name(raw_name)
            except ValueError as exc:
                if str(exc) == profile_store.NAME_EMPTY_ERROR:
                    print("meow: name can't be empty, nothing changed.")
                    return
                print(f"meow: {exc}; try again.")
                continue
            break
    active_profile = profile_store.load() or profile_store.Profile()
    active_profile.name = new_name
    profile_store.save(active_profile)
    print(f"meow: renamed to {new_name}.")


def _install_app() -> None:
    if sys.platform == "darwin":
        _install_app_macos()
    elif sys.platform == "win32":
        _install_app_windows()
    else:
        print("meow: install-app is only supported on macOS and Windows.")
        sys.exit(1)


def _install_app_macos() -> None:
    from . import appbundle

    try:
        app = appbundle.build()
    except appbundle.BuildError as exc:
        print(f"meow: {exc}")
        sys.exit(1)

    print(f"meow: built {app}")
    print("Launch it from Spotlight or the Finder and the Dock will say Meowsage.")
    print("Running `meow` from a terminal still shows Python — that's the same")
    print("interpreter without the bundle around it.")


def _install_app_windows() -> None:
    from . import winshortcut

    meow_exe = _find_meow_executable()
    try:
        link = winshortcut.build(meow_exe)
    except winshortcut.BuildError as exc:
        print(f"meow: {exc}")
        sys.exit(1)

    print(f"meow: created {link}")
    print("Launch Meowsage from the Start Menu (or pin that shortcut to the")
    print("taskbar) and it'll show the cat icon. Running `meow` directly from a")
    print("terminal still carries Python's icon on the console window itself —")
    print("that's the terminal's icon, not the pet's, and is unrelated.")


def _installed_app() -> Path | None:
    """The bundle built by install-app, if it is still there."""
    from . import appbundle

    app = appbundle.DEFAULT_DEST / f"{appbundle.APP_NAME}.app"
    return app if app.exists() else None


def _find_meow_executable() -> Path:
    # console_scripts wrappers live next to the interpreter that owns them
    # (true for pipx and uv tool venvs), so check there before falling back
    # to a PATH lookup. Windows names the wrapper meow.exe, not meow.
    exe_name = "meow.exe" if sys.platform == "win32" else "meow"
    candidate = Path(sys.executable).parent / exe_name
    if candidate.exists():
        return candidate
    found = shutil.which("meow")
    if found:
        return Path(found)
    print("meow: couldn't locate the installed 'meow' executable on PATH.")
    sys.exit(1)


def _enable_autostart() -> None:
    if sys.platform == "darwin":
        _enable_autostart_macos()
    elif sys.platform == "win32":
        _enable_autostart_windows()
    else:
        print("meow: autostart is only supported on macOS and Windows right now.")
        sys.exit(1)


def _enable_autostart_windows() -> None:
    from . import winshortcut

    meow_exe = _find_meow_executable()
    try:
        link = winshortcut.build_startup(meow_exe)
    except winshortcut.BuildError as exc:
        print(f"meow: {exc}")
        sys.exit(1)

    print("meow will now start automatically at login.")
    print(f"Shortcut: {link}")


def _enable_autostart_macos() -> None:
    _remove_legacy_agent()
    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Prefer the bundle when one has been built. Going through `open` hands the
    # launch to LaunchServices, which is the only way the login-started copy
    # gets named Meowsage rather than Python — starting the bundle's binary
    # directly from launchd would skip that and lose the name.
    app = _installed_app()
    if app is not None:
        program_args = ["/usr/bin/open", "-a", str(app)]
    else:
        program_args = [str(_find_meow_executable())]

    arg_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{arg_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{_LOG_PATH}</string>
</dict>
</plist>
"""
    _PLIST_PATH.write_text(plist)

    # Unload first so re-running enable-autostart is idempotent; a failure
    # here just means it wasn't loaded yet, which is fine.
    subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], capture_output=True)
    result = subprocess.run(
        ["launchctl", "load", "-w", str(_PLIST_PATH)], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"meow: wrote {_PLIST_PATH} but launchctl load failed:\n{result.stderr}")
        sys.exit(1)

    print("meow will now start automatically at login (and has just been started now).")
    print(f"Logs: {_LOG_PATH}")


def _disable_autostart() -> None:
    if sys.platform == "darwin":
        _disable_autostart_macos()
    elif sys.platform == "win32":
        _disable_autostart_windows()
    else:
        print("meow: autostart is only supported on macOS and Windows right now.")
        sys.exit(1)


def _disable_autostart_windows() -> None:
    from . import winshortcut

    removed = winshortcut.remove_startup()
    print("meow: autostart disabled." if removed else "meow: autostart isn't enabled.")


def _disable_autostart_macos() -> None:
    had_legacy = _remove_legacy_agent()

    if not _PLIST_PATH.exists():
        if not had_legacy:
            print("meow: autostart isn't enabled.")
        else:
            print("meow: autostart disabled.")
        return

    subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], capture_output=True)
    _PLIST_PATH.unlink()
    print("meow: autostart disabled.")


def _remove_legacy_agent() -> bool:
    """Unload and delete the pre-rename LaunchAgent. True if one was there."""
    if not _LEGACY_PLIST_PATH.exists():
        return False
    subprocess.run(["launchctl", "unload", str(_LEGACY_PLIST_PATH)], capture_output=True)
    _LEGACY_PLIST_PATH.unlink(missing_ok=True)
    return True

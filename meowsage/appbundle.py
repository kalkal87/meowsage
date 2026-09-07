"""Builds Meowsage.app, so macOS calls the pet by its name.

Run as a console script, the pet's process *is* the Python interpreter, and
macOS labels the Dock and the Cmd-Tab switcher after the running executable —
so it reads "Python". Nothing inside Qt changes that: setApplicationName,
setApplicationDisplayName, patching CFBundleName through the ObjC runtime and
exec'ing via a renamed interpreter symlink were all tried, and the label only
moves once the app is launched from a real bundle.

Three constraints shaped what is here, each found by testing rather than
reasoning, and each non-obvious enough to be worth writing down:

- The bundle's executable cannot be a shell script. Modern macOS refuses to
  launch one as CFBundleExecutable (LaunchServices error -10669); it has to be
  a Mach-O binary, so a small C stub is compiled at install time.
- macOS names the app after the *executable that ends up running*, not after
  CFBundleName. A stub that execs `…/pipx/venvs/meowsage/bin/python` therefore
  produces an app called "Python" no matter what the plist says.
- Worse, a framework build of CPython re-execs itself through the framework's
  own `Python.app` stub to get access to the window server. That stub is an app
  bundle in its own right, so the process ends up owned by *its* identity and
  the label is "Python" again.

The way through all three: copy the framework's `Python.app` binary into this
bundle under the name Meowsage, and have the stub exec that copy instead. The
interpreter then runs from inside our bundle, so the identity is ours, and it
does not re-exec a second time because `__PYVENV_LAUNCHER__` is already set —
which is exactly the variable the framework's own launcher uses, and it also
tells Python which venv it belongs to. The copied binary is ~33KB and links to
the framework by absolute path, so it keeps working from its new home.

Building needs `clang` (Xcode Command Line Tools). That is checked up front and
reported as a fixable message rather than a traceback.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "Meowsage"
BUNDLE_ID = "com.meowsage.app"
DEFAULT_DEST = Path.home() / "Applications"

# The compiled stub, which macOS launches. It cannot also be called Meowsage:
# that name is taken by the interpreter copy it execs, and that copy is the one
# whose filename becomes the visible app name.
LAUNCHER_NAME = "launcher"

# Sizes macOS expects in an .iconset, as (pixel size, filename) pairs. The @2x
# entries are the same pixels as the next size up under a different name.
_ICON_SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

_STUB_C = """\
#include <unistd.h>
#include <stdlib.h>

/* Launched by macOS as the bundle executable, then replaced by the interpreter
   sitting beside it. argv is dropped on purpose: the only thing macOS passes is
   an occasional -psn_… process serial number, which Python would reject.

   __PYVENV_LAUNCHER__ does two jobs. It tells the interpreter which venv it
   belongs to, so meowsage and PySide6 are importable; and it suppresses the
   framework re-exec that would otherwise hand the process to Python.app and
   with it the name in the Dock. */
int main(void) {
    setenv("__PYVENV_LAUNCHER__", "%(venv_python)s", 1);
    char *interpreter = "%(interpreter)s";
    char *args[] = {interpreter, "-m", "meowsage", 0};
    execv(interpreter, args);
    return 1;
}
"""

# Asks the target interpreter where its framework's Python.app stub lives. Run
# against that interpreter rather than computed here, because the answer
# depends on how *it* was built, not on whatever is running this code.
_FIND_STUB = """
import sys, sysconfig, os
name = sysconfig.get_config_var("PYTHONFRAMEWORK")
if name:
    path = os.path.join(sys.base_prefix, "Resources",
                        name + ".app", "Contents", "MacOS", name)
    print(path if os.path.exists(path) else "")
else:
    print("")
"""


class BuildError(RuntimeError):
    """A build step failed for a reason worth showing the user verbatim."""


def _c_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run(cmd: list, what: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BuildError(f"{what} failed:\n{detail}")


def _build_icns(target: Path) -> bool:
    """Convert the PNG badge into the .icns the Finder wants. Best-effort."""
    # Imported here, not at module scope: artwork pulls in Qt, and `meow status`
    # reaches into this module for the bundle path. Status is meant to answer
    # without loading a GUI toolkit it has no use for.
    from .artwork import app_icon_path

    source = app_icon_path()
    if not source.exists() or not shutil.which("iconutil") or not shutil.which("sips"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{APP_NAME}.iconset"
        iconset.mkdir()
        for size, name in _ICON_SIZES:
            _run(
                ["sips", "-z", str(size), str(size), str(source), "--out",
                 str(iconset / name)],
                f"resizing the icon to {size}px",
            )
        _run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)],
             "building the .icns")
    return True


def _framework_stub(python: Path) -> Path | None:
    """The framework's Python.app binary for this interpreter, if it has one."""
    result = subprocess.run(
        [str(python), "-c", _FIND_STUB], capture_output=True, text=True
    )
    found = result.stdout.strip()
    return Path(found) if found else None


def _info_plist(has_icon: bool) -> str:
    icon_entry = (
        f"  <key>CFBundleIconFile</key><string>{APP_NAME}</string>\n"
        if has_icon
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>{APP_NAME}</string>
  <key>CFBundleExecutable</key><string>{LAUNCHER_NAME}</string>
  <key>CFBundleIdentifier</key><string>{BUNDLE_ID}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
{icon_entry}  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"""


def build(dest_dir: Path = DEFAULT_DEST, interpreter: Path | None = None) -> Path:
    """Create <dest_dir>/Meowsage.app and return its path."""
    if sys.platform != "darwin":
        raise BuildError("app bundles are a macOS thing.")
    if not shutil.which("clang"):
        raise BuildError(
            "clang is needed to build the bundle's launcher and isn't installed.\n"
            "Install the Xcode Command Line Tools with:  xcode-select --install"
        )

    # Deliberately not resolve()d. A venv's bin/python is a symlink to the base
    # interpreter, and following it lands outside the venv — the bundle would
    # then run a Python that has never heard of meowsage. Python works out its
    # own prefix from the path it was invoked by, so the symlink is the point.
    python = Path(interpreter or sys.executable)
    # The bundle launches with no working directory to speak of, so importing
    # meowsage has to work from anywhere — i.e. it must be installed into this
    # interpreter, not merely sitting in the current directory. Checking now
    # turns a bundle that dies silently on double-click into a message.
    probe = subprocess.run(
        [str(python), "-c", "import meowsage"],
        capture_output=True,
        text=True,
        cwd="/",
    )
    if probe.returncode != 0:
        raise BuildError(
            f"{python} cannot import meowsage, so the bundle would not start.\n"
            "Install the package into that interpreter first (pipx install .)."
        )

    app = Path(dest_dir).expanduser() / f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"

    # Replace wholesale: a half-updated bundle is worse than no bundle, and
    # macOS caches aggressively enough that editing one in place is unreliable.
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    has_icon = _build_icns(resources / f"{APP_NAME}.icns")
    (app / "Contents" / "Info.plist").write_text(_info_plist(has_icon))

    # The interpreter the stub will exec. Copying the framework's Python.app
    # binary in under our own name is what makes the Dock say Meowsage; without
    # a framework stub to copy we exec the venv's python where it stands, which
    # still runs but is labelled after that binary. See the module docstring.
    stub_source = _framework_stub(python)
    if stub_source is not None:
        interpreter = macos / APP_NAME
        shutil.copy2(stub_source, interpreter)
    else:
        interpreter = python

    with tempfile.TemporaryDirectory() as tmp:
        stub_c = Path(tmp) / "stub.c"
        stub_c.write_text(
            _STUB_C
            % {
                "venv_python": _c_string(str(python)),
                "interpreter": _c_string(str(interpreter)),
            }
        )
        _run(["clang", "-O2", "-o", str(macos / LAUNCHER_NAME), str(stub_c)],
             "compiling the launcher")

    # Ad-hoc signatures. Unsigned bundles still launch, but macOS re-prompts for
    # permissions every time a binary changes; a stable signature settles it.
    # The nested binaries are signed before the bundle, which is what --deep
    # does and is the form Apple has not deprecated.
    for binary in sorted(macos.iterdir()):
        _run(["codesign", "--force", "--sign", "-", str(binary)],
             f"signing {binary.name}")
    _run(["codesign", "--force", "--sign", "-", str(app)], "signing the bundle")
    return app

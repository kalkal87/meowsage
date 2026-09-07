"""The ASCII logo printed when Meowsage starts.

Kept apart from cli.py because the art is data, not control flow, and because
`meow` prints it before importing any of Qt — the banner is the only feedback
the terminal gets during the second or so it takes PySide6 to load.

Deliberately pure ASCII: box-drawing and emoji cats look wrong in any terminal
that falls back to a different glyph width, and this has to survive being piped
into a log file by the LaunchAgent.
"""

from __future__ import annotations

import os
import sys

_CAT = r"""
    |\---/|
    | o_o |
     \_^_/
   _/     \_
  (___________)
"""

_WORDMARK = "M E O W S A G E"
_TAGLINE = "your AI coding activity, as a cat"

# Everything is centred on the widest line in the whole banner, tagline
# included — centring on the art alone leaves the wordmark visibly off-axis
# whenever the tagline is the longer of the two.
_WIDTH = max(
    max(len(line) for line in _CAT.splitlines()),
    len(_WORDMARK),
    len(_TAGLINE),
)

_DIM = "\033[2m"
_RESET = "\033[0m"


def _colour_enabled(stream) -> bool:
    """Standard opt-outs, plus: never emit escapes into a redirected log."""
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def render(colour: bool = True) -> str:
    """The banner as a string, so it can be tested without capturing stdout."""
    art_offset = max(0, (_WIDTH - max(len(l) for l in _CAT.splitlines())) // 2)
    lines = [" " * art_offset + line for line in _CAT.strip("\n").splitlines()]
    lines.append("")
    lines.append(_WORDMARK.center(_WIDTH).rstrip())
    tagline = _TAGLINE.center(_WIDTH).rstrip()
    lines.append(f"{_DIM}{tagline}{_RESET}" if colour else tagline)
    return "\n".join(lines) + "\n"


def show(stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    stream.write(render(colour=_colour_enabled(stream)))
    stream.flush()

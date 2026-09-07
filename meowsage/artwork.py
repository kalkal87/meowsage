"""Sprite loading, background stripping, mood tinting, and the pose registry."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap

from .moods import Mood

_ASSETS_DIR = Path(__file__).parent / "assets"

TARGET_WIDTH = 200         # displayed sprite width; heights vary per pose
WHITE_THRESHOLD = 240      # any RGB channel above this counts as background


class Pose(Enum):
    """A specific sprite the cat can be drawn as."""
    STANDING = "standing"       # cat_base.png — eyes open
    WALKING_A = "walking_a"     # cat_base.png — walk-cycle frame 1
    WALKING_B = "walking_b"     # walking.png  — walk-cycle frame 2
    BLINK = "blink"             # blinking.png — eyes closed
    SITTING = "sitting"         # Sitting.png
    SLEEPING = "sleeping"       # sleeping.png
    YAWN = "yawn"               # yawn.png
    LOAF = "loaf"               # loaf.png       — paws tucked, eyes open
    LOAF_BLINK = "loaf_blink"   # loaf_blink.png — same framing, eyes closed
    RELAXED = "relaxed"         # relaxed.png       — sphinx pose, eyes open
    RELAXED_BLINK = "relaxed_blink"  # relaxed_blink.png — same, eyes closed
    # Trusting's roll: on the side, then rolled over, then settled belly-up.
    TRUSTING_ROLL_A = "trusting_roll_a"  # trusting_roll_a.png — on side, legs lifting
    TRUSTING_ROLL_B = "trusting_roll_b"  # trusting_roll_b.png — rolled, face away
    TRUSTING_BACK = "trusting_back"      # trusting_back.png   — belly-up, eyes open
    TRUSTING_BACK_BLINK = "trusting_back_blink"  # same, eyes closed (slow blink)
    # Zoomies run cycle — a faster, longer-strided gait than WALKING_A/B.
    RUN_A = "run_a"             # run_a.png — full extension, legs splayed
    RUN_B = "run_b"             # run_b.png — gathered, legs under the body
    RUN_C = "run_c"             # run_c.png — push-off, half extended
    # Stalking. The two creep frames alternate; the freeze is held between them.
    HUNT_CREEP_A = "hunt_creep_a"   # hunt_creep_a.png — foreleg reaching
    HUNT_CREEP_B = "hunt_creep_b"   # hunt_creep_b.png — gathered under
    HUNT_FREEZE = "hunt_freeze"     # hunt_freeze.png  — flattest, dead still


_POSE_FILES: Dict[Pose, str] = {
    Pose.STANDING: "cat_base.png",
    Pose.WALKING_A: "cat_base.png",
    Pose.WALKING_B: "walking.png",
    Pose.BLINK: "blinking.png",
    Pose.SITTING: "Sitting.png",
    Pose.SLEEPING: "sleeping.png",
    Pose.YAWN: "yawn.png",
    Pose.LOAF: "loaf.png",
    Pose.LOAF_BLINK: "loaf_blink.png",
    Pose.RELAXED: "relaxed.png",
    Pose.RELAXED_BLINK: "relaxed_blink.png",
    Pose.TRUSTING_ROLL_A: "trusting_roll_a.png",
    Pose.TRUSTING_ROLL_B: "trusting_roll_b.png",
    Pose.TRUSTING_BACK: "trusting_back.png",
    Pose.TRUSTING_BACK_BLINK: "trusting_back_blink.png",
    Pose.RUN_A: "run_a.png",
    Pose.RUN_B: "run_b.png",
    Pose.RUN_C: "run_c.png",
    Pose.HUNT_CREEP_A: "hunt_creep_a.png",
    Pose.HUNT_CREEP_B: "hunt_creep_b.png",
    Pose.HUNT_FREEZE: "hunt_freeze.png",
}


# Very light per-mood color overlay so mood still reads visually.
_MOOD_TINTS: Dict[Mood, Optional[tuple]] = {
    # Warmest and brightest in the set — it sits above HAPPY, and the zoomies
    # only last a few seconds, so it can afford to be the loudest.
    Mood.PLAYFUL: (255, 225, 150, 45),
    Mood.HAPPY: (255, 235, 180, 35),
    # A hair warmer than CONTENT's bare sprite and cooler than HAPPY's, so the
    # rung between them still reads as a step up rather than a repeat.
    Mood.TRUSTING: (255, 240, 210, 20),
    Mood.CONTENT: None,
    # Deliberately lighter than TIRED: RELAXED's lying-down pose is close in
    # silhouette to LOAFING's, so the tint is doing extra work to separate them.
    Mood.RELAXED: (150, 160, 190, 28),
    Mood.TIRED: (110, 110, 150, 45),
    Mood.LOAFING: (95, 100, 140, 55),
    Mood.SLEEPY: (60, 70, 120, 75),
}


# Per-pose render scale, applied on top of TARGET_WIDTH.
#
# Normally a pose is sized purely by how much of its 504px source canvas the
# cat occupies, since every canvas is scaled to TARGET_WIDTH. That breaks down
# once a pose fills its canvas: RELAXED is a sphinx pose with the tail extended
# straight back, so it already spans 499 of 504px and cannot be made any bigger
# by renormalising the art (the ceiling is 200px rendered, +1%). Scaling here
# instead. Keep the two RELAXED frames identical or the blink will jitter.
#
# The TRUSTING frames hit the same ceiling harder: a cat on its back is the
# widest silhouette in the set (tail out one side, head the other, legs up), so
# the belly-up frame already spans 500 of 504px. All four share one value —
# they animate into each other, so any difference would pump the cat's size
# mid-roll.
_POSE_SCALE: Dict[Pose, float] = {
    Pose.RELAXED: 1.035,
    Pose.RELAXED_BLINK: 1.035,
    Pose.TRUSTING_ROLL_A: 1.105,
    Pose.TRUSTING_ROLL_B: 1.105,
    Pose.TRUSTING_BACK: 1.105,
    Pose.TRUSTING_BACK_BLINK: 1.105,
    # The run frames are drawn with a bigger head relative to the body than the
    # standing cat, so sizing them by how much cat is in the picture makes the
    # head visibly too large. Scaled to match the standing cat's head instead —
    # the head is what reads as "same character". One value across the cycle,
    # or the cat would grow and shrink as it ran.
    Pose.RUN_A: 1.05,
    Pose.RUN_B: 1.05,
    Pose.RUN_C: 1.05,
    # The HUNT_* poses deliberately have no entry: they sit at 1.0. That was
    # measured, not skipped. Like the run frames they are drawn with a bigger
    # head than the standing cat, and the distance between the eyes — which
    # tracks skull width and, unlike a bounding box, does not change with the
    # pose — puts them within half a pixel of the run cycle at this size.
}


_source_cache: Dict[Pose, QImage] = {}
_pixmap_cache: Dict[Tuple[Pose, Mood], QPixmap] = {}


def _load_source(pose: Pose) -> QImage:
    if pose in _source_cache:
        return _source_cache[pose]
    path = _ASSETS_DIR / _POSE_FILES[pose]
    img = QImage(str(path))
    if img.isNull():
        raise RuntimeError(f"Could not load sprite: {path}")
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    _strip_white_background(img)
    _source_cache[pose] = img
    return img


def _strip_white_background(img: QImage) -> None:
    """Make near-white pixels transparent, in place."""
    transparent = QColor(0, 0, 0, 0)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 10:
                continue
            if (
                c.red() > WHITE_THRESHOLD
                and c.green() > WHITE_THRESHOLD
                and c.blue() > WHITE_THRESHOLD
            ):
                img.setPixelColor(x, y, transparent)


def _tinted(img: QImage, tint: Optional[tuple]) -> QImage:
    if tint is None:
        return img.copy()
    out = img.copy()
    r, g, b, a = tint
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    p.fillRect(out.rect(), QColor(r, g, b, a))
    p.end()
    return out


def pixmap_for(pose: Pose, mood: Mood = Mood.CONTENT) -> QPixmap:
    key = (pose, mood)
    if key in _pixmap_cache:
        return _pixmap_cache[key]
    tinted = _tinted(_load_source(pose), _MOOD_TINTS.get(mood))
    width = int(round(TARGET_WIDTH * _POSE_SCALE.get(pose, 1.0)))
    pm = QPixmap.fromImage(tinted).scaledToWidth(
        width, Qt.TransformationMode.FastTransformation
    )
    _pixmap_cache[key] = pm
    return pm


def app_icon_path() -> Path:
    """The Dock/taskbar icon.

    Not a `Pose` — it is never drawn as the cat, so it stays out of the pose
    registry and out of `prewarm`. It lives in assets/ because that is what
    pyproject ships as package data.
    """
    return _ASSETS_DIR / "app_icon.png"


def app_icon_ico_path() -> Path:
    """The Windows-format multi-resolution icon, for shortcuts (`.lnk`).

    A `.png` works fine as a Qt window icon, but Windows' own shortcut
    IconLocation wants a real `.ico`. Generated once from app_icon.png at
    16/32/48/64/128/256px — see the sizes baked into the file itself.
    """
    return _ASSETS_DIR / "app_icon.ico"


def prewarm() -> None:
    """Load and tint every pose × mood so the first paints don't stutter."""
    for pose in Pose:
        for mood in Mood:
            pixmap_for(pose, mood)


def max_sprite_size() -> Tuple[int, int]:
    """Return the largest (w, h) across all poses — used to size the window."""
    prewarm()
    w = max(pm.width() for pm in _pixmap_cache.values())
    h = max(pm.height() for pm in _pixmap_cache.values())
    return w, h


def draw_zzz(painter: QPainter, origin_x: int, origin_y: int, sprite_w: int, sprite_h: int) -> None:
    """Little floating 'z's above a sleeping cat."""
    font = QFont("Menlo", 14, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor(120, 145, 200))
    bx = origin_x + int(sprite_w * 0.78)
    by = origin_y + int(sprite_h * 0.18)
    painter.drawText(bx, by, "z")
    painter.drawText(bx + 12, by - 12, "z")
    painter.drawText(bx + 24, by - 24, "z")

#!/usr/bin/env python3
"""Render the images the README uses, straight from the app's own sprites.

The point of generating these rather than screenshotting them is that they
cannot drift: they load poses through `artwork.pixmap_for`, so they show the
same background stripping, mood tint and per-pose scale the running app shows.
Change a sprite or a tint and re-running this updates the docs to match.

Two images, written to docs/media/:

  mood-ladder.png   every rung of the mood ladder with its signature pose and
                    its real mood tint, low activity to high, plus Hunting,
                    which is an overlay rather than a rung.
  animations.png    the three multi-frame sequences as frame strips, in the
                    order the animator plays them.

Usage:  python scripts/render_showcase.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from meowsage import artwork  # noqa: E402
from meowsage.artwork import Pose  # noqa: E402
from meowsage.moods import Mood  # noqa: E402
from meowsage.pet import WINDOW_PADDING  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "media"

BG = QColor(250, 250, 251)
INK = QColor(38, 40, 48)
MUTED = QColor(120, 126, 140)
RULE = QColor(226, 229, 236)

# One representative pose per rung. These are the poses each mood actually
# spends most of its time in — see _POSE_WEIGHTS in animation.py.
LADDER = [
    (Mood.SLEEPY, Pose.SLEEPING, "idle"),
    (Mood.LOAFING, Pose.LOAF, "barely ticking over"),
    (Mood.TIRED, Pose.SITTING, "winding down"),
    (Mood.RELAXED, Pose.RELAXED, "resting, not tired"),
    (Mood.CONTENT, Pose.STANDING, "comfortable"),
    (Mood.TRUSTING, Pose.TRUSTING_BACK, "belly up"),
    (Mood.HAPPY, Pose.WALKING_B, "busy"),
    (Mood.PLAYFUL, Pose.RUN_C, "zoomies"),
]

SEQUENCES = [
    ("Trusting — the flop", Mood.TRUSTING,
     [Pose.TRUSTING_ROLL_A, Pose.TRUSTING_ROLL_B, Pose.TRUSTING_BACK,
      Pose.TRUSTING_BACK_BLINK]),
    ("Playful — the gallop", Mood.PLAYFUL,
     [Pose.RUN_B, Pose.RUN_C, Pose.RUN_A, Pose.RUN_C]),
    ("Hunting — the stalk", Mood.CONTENT,
     [Pose.HUNT_CREEP_A, Pose.HUNT_CREEP_B, Pose.HUNT_FREEZE]),
]


def cell_size() -> tuple:
    """The pet window's size — the frame every pose is composed inside."""
    sw, sh = artwork.max_sprite_size()
    return sw + WINDOW_PADDING * 2, sh + WINDOW_PADDING * 2


def draw_pose(painter: QPainter, pose: Pose, mood: Mood, ox: int, oy: int,
              cell_w: int, cell_h: int) -> None:
    """Place a pose exactly where PetWindow.paintEvent would place it."""
    pm = artwork.pixmap_for(pose, mood)
    painter.drawPixmap(ox + (cell_w - pm.width()) // 2,
                       oy + (cell_h - pm.height()) // 2, pm)


def vertical_extent(poses) -> tuple:
    """Topmost and bottommost opaque rows across poses, in cell coordinates.

    Used to crop the dead space out of the window-sized cells without
    disturbing the shared ground line that makes the poses comparable.
    """
    cell_w, cell_h = cell_size()
    top, bottom = cell_h, 0
    for pose, mood in poses:
        im = artwork.pixmap_for(pose, mood).toImage()
        oy = (cell_h - im.height()) // 2
        for y in range(im.height()):
            if any(im.pixelColor(x, y).alpha() >= 10 for x in range(im.width())):
                top = min(top, oy + y)
                break
        for y in range(im.height() - 1, -1, -1):
            if any(im.pixelColor(x, y).alpha() >= 10 for x in range(im.width())):
                bottom = max(bottom, oy + y)
                break
    return top, bottom


def render_ladder(path: Path) -> None:
    cell_w, cell_h = cell_size()
    pairs = [(pose, mood) for mood, pose, _ in LADDER]
    pairs.append((Pose.HUNT_FREEZE, Mood.CONTENT))
    top, bottom = vertical_extent(pairs)
    pad_top, label_h = 46, 64
    art_h = bottom - top + 1
    cols = len(LADDER) + 1
    w, h = cell_w * cols, pad_top + art_h + label_h

    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

    p.setPen(INK)
    p.setFont(QFont("Helvetica", 17, QFont.Weight.Bold))
    p.drawText(20, 30, "The mood ladder — driven by your recent Claude Code activity")
    p.setFont(QFont("Helvetica", 12))
    p.setPen(MUTED)
    # Right-aligned to the end of the ladder, not the image: Hunting occupies
    # the last column and is not part of the progression this arrow describes.
    p.drawText(0, 14, len(LADDER) * cell_w - 16, 20,
               int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
               "less busy  →  more busy")

    for i, (mood, pose, blurb) in enumerate(LADDER):
        ox = i * cell_w
        p.save()
        p.setClipRect(ox, pad_top, cell_w, art_h)
        draw_pose(p, pose, mood, ox, pad_top - top, cell_w, cell_h)
        p.restore()
        p.setPen(INK)
        p.setFont(QFont("Helvetica", 13, QFont.Weight.Bold))
        p.drawText(ox, pad_top + art_h + 22, cell_w, 18,
                   int(Qt.AlignmentFlag.AlignHCenter), mood.value.upper())
        p.setPen(MUTED)
        p.setFont(QFont("Helvetica", 11))
        p.drawText(ox, pad_top + art_h + 40, cell_w, 16,
                   int(Qt.AlignmentFlag.AlignHCenter), blurb)

    # Hunting sits outside the ladder, so it gets a rule and its own caption.
    ox = len(LADDER) * cell_w
    p.setPen(RULE)
    p.drawLine(ox, pad_top - 8, ox, pad_top + art_h + 46)
    p.save()
    p.setClipRect(ox, pad_top, cell_w, art_h)
    draw_pose(p, Pose.HUNT_FREEZE, Mood.CONTENT, ox, pad_top - top, cell_w, cell_h)
    p.restore()
    p.setPen(INK)
    p.setFont(QFont("Helvetica", 13, QFont.Weight.Bold))
    p.drawText(ox, pad_top + art_h + 22, cell_w, 18,
               int(Qt.AlignmentFlag.AlignHCenter), "HUNTING")
    p.setPen(MUTED)
    p.setFont(QFont("Helvetica", 11))
    p.drawText(ox, pad_top + art_h + 40, cell_w, 16,
               int(Qt.AlignmentFlag.AlignHCenter), "overlay — watches your cursor")
    p.end()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.save(str(path))
    print(f"{path.relative_to(OUT_DIR.parent.parent)}: {w}x{h}")


def render_animations(path: Path) -> None:
    cell_w, cell_h = cell_size()
    pairs = [(pose, mood) for _, mood, poses in SEQUENCES for pose in poses]
    top, bottom = vertical_extent(pairs)
    art_h = bottom - top + 1
    head_h, row_gap = 40, 26
    widest = max(len(poses) for _, _, poses in SEQUENCES)
    w = cell_w * widest
    h = sum(head_h + art_h + row_gap for _ in SEQUENCES) + 34

    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(BG)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

    p.setPen(INK)
    p.setFont(QFont("Helvetica", 17, QFont.Weight.Bold))
    p.drawText(20, 30, "Multi-frame sequences, in play order")

    y = 34
    for title, mood, poses in SEQUENCES:
        p.setPen(INK)
        p.setFont(QFont("Helvetica", 13, QFont.Weight.Bold))
        p.drawText(20, y + 26, title)
        y += head_h
        for i, pose in enumerate(poses):
            ox = i * cell_w
            p.save()
            p.setClipRect(ox, y, cell_w, art_h)
            draw_pose(p, pose, mood, ox, y - top, cell_w, cell_h)
            p.restore()
            p.setPen(MUTED)
            p.setFont(QFont("Helvetica", 10))
            p.drawText(ox, y + art_h + 2, cell_w, 14,
                       int(Qt.AlignmentFlag.AlignHCenter), f"{i + 1}")
        y += art_h + row_gap
    p.end()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.save(str(path))
    print(f"{path.relative_to(OUT_DIR.parent.parent)}: {w}x{h}")


if __name__ == "__main__":
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    render_ladder(OUT_DIR / "mood-ladder.png")
    render_animations(OUT_DIR / "animations.png")

#!/usr/bin/env python3
"""Render the looping demo GIF the root README opens with.

Runs the real `PetWindow` headlessly against `StubUsageSource`, driving it
through a handful of rungs on the mood ladder, and grabs a real paintEvent
every frame — the same technique the README's "testing without a display"
section describes for verifying behaviour, just with the frames kept instead
of thrown away. That means the GIF can't drift from the app the way a
hand-recorded screen capture could: change a sprite, a tint or a timing
constant and re-running this picks it up.

The pet window itself is transparent (no desktop to float over, offscreen),
so each grabbed frame is composited onto a plain gradient backdrop with a
mood-label caption, entirely in Qt, before handoff to Pillow — the one piece
Qt genuinely can't do itself. Its `QImageWriter` can encode a single WebP or
PNG but silently produces a one-frame file if you feed it multiple images
(verified empirically; there is no multi-frame writer plugin here), so an
external encoder is unavoidable for an animated result. Pillow is installed
for this script alone (`pip install pillow`); nothing under `meowsage/`
imports it.

Usage:  python scripts/render_demo_gif.py
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Zoomies/trusting-roll durations (leg count, roll cycles, belly-up hold) are
# randomised — pinned so the same script always renders the same GIF.
random.seed(7)

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from meowsage.moods import Mood  # noqa: E402
from meowsage.pet import PetWindow  # noqa: E402
from meowsage.usage import StubUsageSource  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "media" / "demo.gif"

FPS = 12
FRAME_MS = round(1000 / FPS)
MARGIN = 36
LABEL_H = 34

TOP = QColor(232, 238, 248)
BOTTOM = QColor(248, 245, 240)
INK = QColor(64, 68, 80)

# (activity level, seconds to hold it, caption) — chosen to hit the ladder's
# two flashiest multi-frame chains (zoomies, the trusting flop) alongside a
# calm start and end, rather than dwelling on every rung. Levels are picked
# from moods.mood_for_activity's real cutoffs, not the round numbers a
# glance at the README's stub examples might suggest (0.85 lands in HAPPY,
# not TRUSTING — TRUSTING is the narrow 0.78-0.85 band just under it).
#
# Hold times are sized to let whatever one-shot animation a transition
# triggers finish *before* the next transition fires — the wake-up chain
# (yawn 1.4s + stretch 0.9s) and the trusting flop (up to 3 roll cycles at
# 150ms/frame, then a random 1.5-3.5s belly-up hold) both run unconditionally
# on entering their mood, and firing another mood change mid-chain cuts them
# off. Cutting off the wake-up chain early was the failure mode that first
# gave this away: the zoomies triggered right after used to die in under
# 100ms because the still-running stretch-end timer clobbered it moments
# later.
SCRIPT = [
    (0.05, 2.2, "SLEEPY"),
    (0.90, 2.8, "HAPPY"),
    (0.97, 2.6, "PLAYFUL"),
    (0.80, 5.6, "TRUSTING"),
    (0.05, 2.4, "SLEEPY"),
]


def main() -> None:
    source = StubUsageSource(initial_activity=SCRIPT[0][0])
    window = PetWindow(source, pet_name="Meowsage")
    # Comfortably clear of every screen edge: zoomies dashes that hit a wall
    # bounce straight into the next leg *synchronously* (see _run_step), so a
    # window pinned at (0, 0) collapses a whole burst into a couple of
    # milliseconds instead of the ~2s it's meant to run for. WANDER_MAX_DIST_PX
    # (300, the widest a dash can be pulled from home) fits inside offscreen's
    # 800x800 virtual screen from here in every direction.
    home = QPoint(300, 300)
    window.move(home)
    window._home_pos = home
    window.show()

    canvas_w = window.width() + MARGIN * 2
    canvas_h = window.height() + MARGIN * 2 + LABEL_H

    state = {"caption": SCRIPT[0][2]}
    frames: list[QImage] = []

    def capture() -> None:
        out = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        grad = QLinearGradient(0, 0, 0, canvas_h)
        grad.setColorAt(0.0, TOP)
        grad.setColorAt(1.0, BOTTOM)
        p.fillRect(out.rect(), grad)

        pet_grab = window.grab().toImage()
        p.drawImage(MARGIN, MARGIN, pet_grab)

        p.setPen(INK)
        p.setFont(QFont("Menlo", 12, QFont.Weight.Bold))
        p.drawText(
            out.rect().adjusted(0, canvas_h - LABEL_H, 0, -10),
            int(Qt.AlignmentFlag.AlignHCenter),
            state["caption"],
        )
        p.end()
        frames.append(out.copy())

    capture_timer = QTimer()
    capture_timer.timeout.connect(capture)
    capture_timer.start(FRAME_MS)

    t_ms = 0
    for level, hold_s, caption in SCRIPT:
        def apply(level=level, caption=caption) -> None:
            source.set_activity(level)
            window._refresh_mood()
            state["caption"] = caption

        QTimer.singleShot(t_ms, apply)
        t_ms += round(hold_s * 1000)

    QTimer.singleShot(t_ms, app.quit)
    app.exec()
    capture_timer.stop()

    if not frames:
        raise SystemExit("captured no frames")

    save_gif(frames)
    print(f"{OUT_PATH.relative_to(OUT_PATH.parent.parent.parent)}: "
          f"{len(frames)} frames, {canvas_w}x{canvas_h}, {FPS}fps")


def save_gif(frames: list[QImage]) -> None:
    from PIL import Image

    def to_pil(qimg: QImage) -> "Image.Image":
        qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
        buf = bytes(qimg.constBits())
        return Image.frombuffer(
            "RGBA", (qimg.width(), qimg.height()), buf, "raw", "RGBA", 0, 1
        ).convert("RGB")

    pil_frames = [to_pil(f) for f in frames]

    # One shared palette, built from every mood tint the sequence visits
    # rather than a single frame, keeps colour stable across the whole GIF —
    # quantizing each frame independently makes flat pixel-art fields
    # flicker as the palette shifts frame to frame.
    sample_count = 12
    step = max(1, len(pil_frames) // sample_count)
    samples = pil_frames[::step]
    strip = Image.new("RGB", (samples[0].width * len(samples), samples[0].height))
    for i, s in enumerate(samples):
        strip.paste(s, (i * s.width, 0))
    reference = strip.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=reference, dither=Image.Dither.NONE) for f in pil_frames]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        OUT_PATH,
        save_all=True,
        append_images=quantized[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=2,
        optimize=True,
    )


if __name__ == "__main__":
    main()

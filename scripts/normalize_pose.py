#!/usr/bin/env python3
"""Turn raw generated cat art into project-standard sprites.

Generated art arrives as a big image with the cat somewhere in the middle on a
white background. The app needs something much stricter: a 504x495 transparent
canvas with the cat at a known size, horizontally centred, standing on the same
ground line as every other pose. This script does that conversion.

Per frame it:

  1. Finds the cat as the largest connected blob of non-background pixels, so a
     stray export artifact (a border stripe, a lone speck) can't blow out the
     crop. One of the supplied sources has a 1px grey column down its right edge
     that a naive bounding box would happily include.
  2. Rescues near-white pixels *enclosed* by the cat — eye whites, mostly — by
     nudging them to just under the strip threshold. artwork.py makes anything
     above WHITE_THRESHOLD transparent at load time, which would otherwise punch
     holes straight through the eyes.
  3. Strips the surrounding white background to transparent.
  4. Crops to the cat, scales it to the requested size, and pastes it onto the
     canvas with its feet on the requested ground line.

Both frames of a blink pair are normalised in a single run, sharing one set of
geometry arguments. That is the point of doing them together: if the two frames
are scaled or placed even slightly differently, the cat visibly shifts every
time it blinks. Passing the numbers twice by hand is exactly how that goes
wrong, so the script takes them once and applies them to both.

Sizing note: a pose's on-screen size is set by how much of the canvas width the
cat occupies, because artwork.py scales the whole canvas to a fixed width. A
pose that fills its canvas cannot be enlarged any further here — it needs a
_POSE_SCALE entry in artwork.py instead, and then its ground line must be
raised to cancel the scale. See the RELAXED entry there.

Examples
--------
Normalise a blink pair (how the current RELAXED sprites were produced)::

    python scripts/normalize_pose.py \\
        --width 499 --height 326 --ground 456 \\
        --open  "meowsage/assets/relaxed_new_eyes_open.png" meowsage/assets/relaxed.png \\
        --closed "meowsage/assets/relaxed (eyes closed).png" meowsage/assets/relaxed_blink.png

Normalise a single pose with no blink frame, letting the height follow the
source's aspect ratio::

    python scripts/normalize_pose.py --width 390 --ground 465 \\
        --open raw_sitting.png meowsage/assets/sitting.png
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

# Must match artwork.py's WHITE_THRESHOLD. Anything above this is treated as
# background both here and at load time.
WHITE = 240
# Just under the threshold, so rescued eye whites survive the runtime strip.
EYE_WHITE = QColor(236, 236, 236)
# The canvas every normalised pose shares, matching the existing sprite family.
CANVAS_W, CANVAS_H = 504, 495


def _is_bg(img: QImage, x: int, y: int) -> bool:
    c = img.pixelColor(x, y)
    if c.alpha() < 10:
        return True
    return c.red() > WHITE and c.green() > WHITE and c.blue() > WHITE


def largest_component_bbox(img: QImage) -> Tuple[int, int, int, int, int]:
    """Bounding box of the biggest blob of non-background pixels.

    Using the largest component rather than a plain bounding box makes the crop
    immune to specks and edge artifacts elsewhere in the frame.
    """
    w, h = img.width(), img.height()
    seen = bytearray(w * h)
    best = None
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or _is_bg(img, sx, sy):
                continue
            q = deque([(sx, sy)])
            seen[sy * w + sx] = 1
            x0 = x1 = sx
            y0 = y1 = sy
            n = 0
            while q:
                x, y = q.popleft()
                n += 1
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]
                            and not _is_bg(img, nx, ny)):
                        seen[ny * w + nx] = 1
                        q.append((nx, ny))
            if best is None or n > best[0]:
                best = (n, x0, y0, x1, y1)
    if best is None:
        raise SystemExit("no subject found — the image looks entirely blank")
    return best


def rescue_enclosed_whites(img: QImage, x0: int, y0: int, x1: int, y1: int) -> int:
    """Recolour near-white pixels enclosed by the subject, e.g. eye whites.

    Flood-fills the background inward from the frame edges; any near-white pixel
    inside the subject's box that the flood never reached must be enclosed by
    the cat, so it is detail rather than background.
    """
    w, h = img.width(), img.height()
    seen = bytearray(w * h)
    q: deque = deque()

    def push(x: int, y: int) -> None:
        if not seen[y * w + x] and _is_bg(img, x, y):
            seen[y * w + x] = 1
            q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                push(nx, ny)

    rescued = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if not seen[y * w + x] and _is_bg(img, x, y):
                img.setPixelColor(x, y, EYE_WHITE)
                rescued += 1
    return rescued


def normalize(src: str, out: str, width: int, height: Optional[int],
              ground_y: int) -> int:
    """Normalise one frame. Returns the height used, so a pair can share it."""
    img = QImage(src)
    if img.isNull():
        raise SystemExit(f"could not read {src}")
    img = img.convertToFormat(QImage.Format.Format_ARGB32)

    n, x0, y0, x1, y1 = largest_component_bbox(img)
    rescued = rescue_enclosed_whites(img, x0, y0, x1, y1)

    # Strip *after* rescuing, then crop — anything outside the main component is
    # discarded by the crop regardless.
    transparent = QColor(0, 0, 0, 0)
    for y in range(img.height()):
        for x in range(img.width()):
            if _is_bg(img, x, y) and img.pixelColor(x, y).alpha() >= 10:
                img.setPixelColor(x, y, transparent)

    cat = img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    if height is None:
        height = max(1, round(cat.height() * (width / cat.width())))
    cat = cat.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.FastTransformation)

    canvas = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(0, 0, 0, 0))
    px = (CANVAS_W - width) // 2
    py = ground_y - height
    if px < 0 or py < 0 or px + width > CANVAS_W or py + height > CANVAS_H:
        raise SystemExit(
            f"{width}x{height} at ground {ground_y} does not fit the "
            f"{CANVAS_W}x{CANVAS_H} canvas — the sprite would be clipped. "
            "A pose that already fills the canvas needs a _POSE_SCALE entry "
            "in artwork.py rather than a bigger target here."
        )
    p = QPainter(canvas)
    p.drawImage(px, py, cat)
    p.end()
    if not canvas.save(out):
        raise SystemExit(f"could not write {out}")

    print(f"{out}: subject {n}px, bbox [{x1-x0+1}x{y1-y0+1}], "
          f"rescued {rescued} enclosed px -> {width}x{height} at ({px},{py})")
    return height


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Normalise generated cat art into project-standard sprites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--width", type=int, required=True,
                    help="cat width on the 504px canvas")
    ap.add_argument("--height", type=int, default=None,
                    help="cat height; defaults to the source's aspect ratio")
    ap.add_argument("--ground", type=int, required=True,
                    help="y of the cat's ground line, shared across poses")
    ap.add_argument("--open", nargs=2, required=True, metavar=("SRC", "OUT"),
                    help="eyes-open source and output path")
    ap.add_argument("--closed", nargs=2, metavar=("SRC", "OUT"),
                    help="eyes-closed source and output path, if the pose blinks")
    args = ap.parse_args(argv)

    app = QGuiApplication(sys.argv[:1])  # noqa: F841 — Qt needs an instance

    # The open frame goes first and its height is reused for the closed frame,
    # so both land at identical geometry and the blink doesn't shift the cat.
    height = normalize(args.open[0], args.open[1], args.width, args.height,
                       args.ground)
    if args.closed:
        normalize(args.closed[0], args.closed[1], args.width, height,
                  args.ground)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

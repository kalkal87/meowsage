#!/usr/bin/env python3
"""Check that every pose is drawn at a consistent size and sits on the floor.

Run this after adding or resizing a pose. It measures the sprites exactly as
the app loads them — after background stripping, tinting and scaling — so it
reflects what actually reaches the screen rather than what the source art says.

Three tables, answering three questions:

  1. Size and visual mass — is the pose in the right ballpark overall?
     Bounding box is a poor guide on its own: a pose with the tail and legs
     stretched out has a wide box but little cat in it. Opaque pixel count
     ("visual mass") tracks how big the cat actually reads.

  2. Head width — is the pose at the right scale?
     The cat's head is the one part that should be the same size in every
     pose, so it is the best scale invariant available. Measured in fixed
     bands down from the top of the silhouette, so a flatter pose can't bias
     the result. Only the grounded poses (sitting, loaf, relaxed) compare
     directly; the standing poses carry a raised tail through the top bands,
     so their numbers are tail plus head.

  3. Window placement — does the cat stand on the same floor line, and does
     it fit? A pose given a _POSE_SCALE entry in artwork.py grows the window,
     and because each sprite is centred in that window, the feet can drift.
     That is the trap the lying-down pose fell into: the fix is to raise the
     pose's ground line in the art until the feet line up again.

Usage:  python scripts/check_sizing.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from meowsage import artwork  # noqa: E402
from meowsage.artwork import Pose  # noqa: E402
from meowsage.moods import Mood  # noqa: E402
from meowsage.pet import WINDOW_PADDING  # noqa: E402

BANDS = (10, 15, 20, 25, 30)
BASELINE = Pose.STANDING
# A trailing tail shows up as an abrupt widening: the rows it occupies alone
# hold a fraction of the pixels of the first row of actual body. Scanning up
# from the bottom, a jump of at least this ratio marks where the body starts.
# Poses that simply taper to the floor (loaf, relaxed) never jump this hard and
# so are measured at their lowest pixel, exactly as before.
BODY_JUMP_RATIO = 2.0
# Only look for that jump in the bottom slice of the silhouette, so a waistline
# higher up the body can't be mistaken for it.
BODY_SCAN_FRACTION = 0.25
# A row counts as torso once it holds this share of the pose's widest row.
TORSO_ROW_FRACTION = 0.5
# Poses low enough that the top bands catch head only, not a raised tail —
# these compare directly on head width, which is the scale check. The TRUSTING
# poses are deliberately absent: the cat is on its back, so the top of the
# silhouette is paws, and the head band would measure a leg. They are scale-
# checked by visual mass and by eye instead.
GROUNDED = {Pose.SITTING, Pose.LOAF, Pose.LOAF_BLINK, Pose.RELAXED,
            Pose.RELAXED_BLINK}
# Lying poses, which must share a ground line because they swap with each
# other. Sitting and standing legitimately sit at their own heights.
LYING = {Pose.LOAF, Pose.LOAF_BLINK, Pose.RELAXED, Pose.RELAXED_BLINK,
         Pose.TRUSTING_ROLL_A, Pose.TRUSTING_ROLL_B, Pose.TRUSTING_BACK,
         Pose.TRUSTING_BACK_BLINK}
# The run cycle is judged on its own. A galloping cat's paws genuinely leave
# the floor, so the frames cannot share a paw line with the standing poses and
# should not be forced to — what has to hold is that the *body* stays level
# across the cycle, or the cat pogos as it runs. The cycle is placed so its
# paws straddle the standing floor line on average.
RUNNING = {Pose.RUN_A, Pose.RUN_B, Pose.RUN_C}
# The stalk. Same reasoning as the run cycle for a different reason: a creeping
# cat keeps its head and body gliding at a constant height while the paws step,
# so the torso is what must stay level. The freeze is included because it is
# held mid-sequence and any step up or down into it would read as a flinch.
STALKING = {Pose.HUNT_CREEP_A, Pose.HUNT_CREEP_B, Pose.HUNT_FREEZE}


def measure(pose: Pose) -> dict:
    im = artwork.pixmap_for(pose, Mood.CONTENT).toImage()
    pts = [(x, y)
           for y in range(im.height())
           for x in range(im.width())
           if im.pixelColor(x, y).alpha() >= 10]
    if not pts:
        raise SystemExit(f"{pose.name}: sprite is entirely transparent")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    top = min(ys)

    # Lowest row holding body, as opposed to the lowest row holding anything.
    # In the belly-up poses the tail is drawn trailing below the body's contact
    # with the floor — by 9px in one frame — so the bounding box bottom is not
    # where the cat looks like it is resting, and aligning on it would make the
    # body bob through the roll.
    per_row: dict = {}
    for _, y in pts:
        per_row[y] = per_row.get(y, 0) + 1
    bottom = max(ys)
    scan_to = bottom - int((bottom - top) * BODY_SCAN_FRACTION)
    body_maxy = bottom
    for y in range(bottom, scan_to, -1):
        here, above = per_row.get(y, 0), per_row.get(y - 1, 0)
        if here and above >= here * BODY_JUMP_RATIO:
            body_maxy = y - 1
            break

    # Underside of the torso, ignoring legs entirely: the lowest row still
    # holding half the pose's widest row. For a gallop this is the line that
    # must stay level — the paws are supposed to move, the body is not.
    torso_maxy = max(y for y, n in per_row.items()
                     if n >= TORSO_ROW_FRACTION * max(per_row.values()))

    out = {
        "pm_w": im.width(), "pm_h": im.height(),
        "minx": min(xs), "maxx": max(xs), "maxy": max(ys),
        "body_maxy": body_maxy,
        "torso_maxy": torso_maxy,
        "w": max(xs) - min(xs) + 1,
        "h": max(ys) - min(ys) + 1,
        "mass": len(pts),
    }
    for b in BANDS:
        bx = [x for x, y in pts if y <= top + b]
        out[b] = (max(bx) - min(bx) + 1) if bx else 0
    return out


m = {pose: measure(pose) for pose in Pose}
base_mass = m[BASELINE]["mass"]

print("1. SIZE AND VISUAL MASS")
print(f"{'pose':<16}{'w':>6}{'h':>6}{'mass':>9}{'vs standing':>13}")
print("-" * 50)
for pose in Pose:
    d = m[pose]
    print(f"{pose.name:<16}{d['w']:>6}{d['h']:>6}{d['mass']:>9}"
          f"{100 * d['mass'] / base_mass:>12.0f}%")

print("\n2. HEAD WIDTH (fixed bands from the top of the silhouette)")
print(f"{'pose':<16}" + "".join(f"{'top' + str(b):>8}" for b in BANDS))
print("-" * (16 + 8 * len(BANDS)))
for pose in Pose:
    marker = "" if pose in GROUNDED else "   (tail in band)"
    print(f"{pose.name:<16}" + "".join(f"{m[pose][b]:>8}" for b in BANDS) + marker)

grounded_15 = {p.name: m[p][15] for p in Pose if p in GROUNDED}
lo, hi = min(grounded_15.values()), max(grounded_15.values())
print(f"\n   grounded poses at top15: {grounded_15}")
print(f"   spread {hi - lo}px "
      f"({'consistent' if hi - lo <= 2 else 'INCONSISTENT — check scale'})")

print("\n3. WINDOW PLACEMENT")
sw, sh = artwork.max_sprite_size()
win_w, win_h = sw + WINDOW_PADDING * 2, sh + WINDOW_PADDING * 2
print(f"   largest sprite {sw}x{sh} -> window {win_w}x{win_h}")
print(f"\n{'pose':<20}{'sprite':>10}{'body y':>8}{'lowest':>8}"
      f"{'left':>7}{'right':>7}{'clipped':>9}")
print("-" * 69)
feet = {}
for pose in Pose:
    d = m[pose]
    cx = (win_w - d["pm_w"]) // 2
    cy = (win_h - d["pm_h"]) // 2
    left, right = cx + d["minx"], cx + d["maxx"]
    feet[pose.name] = cy + d["body_maxy"]
    lowest = cy + d["maxy"]
    clipped = "YES" if left < 0 or right > win_w - 1 else "-"
    sprite = "{}x{}".format(d["pm_w"], d["pm_h"])
    print(f"{pose.name:<20}{sprite:>10}"
          f"{feet[pose.name]:>8}{lowest:>8}{left:>7}{win_w - 1 - right:>7}"
          f"{clipped:>9}")

print("\n   'body y' is the ground line that matters — the lowest row with real")
print("   cat in it. 'lowest' includes a trailing tail, which legitimately")
print("   hangs below the body and differs from frame to frame.")

ground = {p.name: feet[p.name] for p in Pose if p in LYING}
lo, hi = min(ground.values()), max(ground.values())
print(f"\n   lying poses' body line: {ground}")
print(f"   spread {hi - lo}px "
      f"({'aligned' if hi - lo <= 1 else 'MISALIGNED — adjust the ground line'})")

run_torso = {p.name: (win_h - m[p]["pm_h"]) // 2 + m[p]["torso_maxy"]
             for p in Pose if p in RUNNING}
lo, hi = min(run_torso.values()), max(run_torso.values())
print(f"\n   run cycle's torso line: {run_torso}")
print(f"   spread {hi - lo}px "
      f"({'level' if hi - lo <= 2 else 'BOBBING — the cat will pogo as it runs'})")
run_paws = {p.name: (win_h - m[p]["pm_h"]) // 2 + m[p]["maxy"]
            for p in Pose if p in RUNNING}
mean_paw = sum(run_paws.values()) / len(run_paws)
stand_floor = feet[Pose.STANDING.name]
print(f"   run cycle's paws: {run_paws}  (they should differ — it's a gallop)")
print(f"   mean paw {mean_paw:.0f} vs standing floor {stand_floor} "
      f"({'on the same ground' if abs(mean_paw - stand_floor) <= 3 else 'DRIFTING — it will look like it runs above or below the floor'})")

stalk_torso = {p.name: (win_h - m[p]["pm_h"]) // 2 + m[p]["torso_maxy"]
               for p in Pose if p in STALKING}
lo, hi = min(stalk_torso.values()), max(stalk_torso.values())
print(f"\n   stalk's torso line: {stalk_torso}")
print(f"   spread {hi - lo}px "
      f"({'level' if hi - lo <= 2 else 'BOBBING — a stalking cat glides, it does not bob'})")
stalk_paws = {p.name: (win_h - m[p]["pm_h"]) // 2 + m[p]["maxy"]
              for p in Pose if p in STALKING}
mean_paw = sum(stalk_paws.values()) / len(stalk_paws)
print(f"   stalk's paws: {stalk_paws}")
print(f"   mean paw {mean_paw:.0f} vs standing floor {stand_floor} "
      f"({'on the same ground' if abs(mean_paw - stand_floor) <= 3 else 'DRIFTING — adjust the ground line'})")
print(f"\n   For reference, sitting's feet are at {feet[Pose.SITTING.name]} and")
print(f"   standing's at {feet[Pose.STANDING.name]}. Those poses sit at their own")
print("   heights by design — only the lying poses share a ground line, since")
print("   they swap directly with one another.")

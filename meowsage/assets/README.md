# `assets/` — the sprites

34 PNGs: 20 sprites the app loads, 13 originals kept so any pose can be rebuilt
at a different size without going back for new art, and the app icon.

The sprites are generated pixel art of one grey shorthair cat, always drawn
facing right. The app mirrors it for the other direction, so there is no
left-facing art.

## Not a sprite

`app_icon.png` — the Dock icon, 1024×1024 with transparent corners. It never
gets drawn as the cat, so it is deliberately absent from the `Pose` registry and
from `prewarm()`; `artwork.app_icon_path()` is the only thing that reaches for
it. It lives here because `pyproject.toml` ships `assets/*.png` as package data,
so anything in this folder travels with a `pipx install`.

## What the app loads

Registered in `_POSE_FILES` in [`../artwork.py`](../artwork.py). Each is a
504×495 transparent canvas with the cat placed at a known size on a shared
ground line.

| Sprite | Used for |
|---|---|
| `cat_base.png` | Standing, and the first walk-cycle frame |
| `walking.png` | The second walk-cycle frame |
| `blinking.png` | Standing with eyes closed |
| `Sitting.png` | Sitting idle |
| `sleeping.png` | Asleep (the app draws the `z`s procedurally) |
| `yawn.png` | The transition into and out of sleep |
| `loaf.png`, `loaf_blink.png` | Loafing, paws tucked |
| `relaxed.png`, `relaxed_blink.png` | The sphinx pose |
| `trusting_roll_a/b.png`, `trusting_back.png`, `trusting_back_blink.png` | Rolling over and lying belly-up |
| `run_a/b/c.png` | The gallop, for zoomies |
| `hunt_creep_a/b.png`, `hunt_freeze.png` | Stalking and freezing |

## The originals

Kept deliberately, per the note in [`../../scripts/README.md`](../../scripts/README.md):
resizing a pose means re-running the normaliser on its source, not editing the
finished sprite.

`realxed (eyes open).png`, `relaxed (eyes closed).png`,
`relaxed_new_eyes_open.png`, `trusting_frame_1/2/3.png`,
`trusting_frame_3(closed eye for blinking).png`, `playfull_1/2/3.png`,
`hunting_1/2/3.png`.

The spelling of some of those filenames is as they arrived. They are inputs to a
manual step, never referenced by code, so they were left alone rather than
renamed for tidiness.

## Conventions a new sprite must follow

Produced by [`scripts/normalize_pose.py`](../../scripts/normalize_pose.py) — do
not hand-crop these. It exists because all four of the following are easy to get
subtly wrong and hard to spot by eye:

- **Canvas**: 504×495, transparent, cat horizontally centred.
- **Ground line**: shared across poses that swap with each other, so the cat
  does not hop when it changes pose. Which line depends on the family — see
  below.
- **No near-white pixels inside the cat**. `artwork.py` strips anything above
  RGB 240 to transparent at load time, which would punch holes through the eyes.
  The normaliser darkens enclosed whites to survive it.
- **Size by the head, not by area.** How much cat is in the picture varies with
  the pose, and these art batches were not drawn with a consistent head-to-body
  ratio. The head is what reads as "the same cat".

### Three different ground-line rules

Not every group aligns the same way, and using the wrong rule is the main way a
new pose looks wrong:

| Family | Aligned on | Why |
|---|---|---|
| Standing, walking, sitting | Paws | The obvious case — feet are on the floor |
| Loaf, sphinx, belly-up | Lowest drawn pixel | They swap directly with each other |
| Gallop | Torso | A galloping cat's paws leave the ground; the body is what must stay level |
| Stalk | Torso | Paws stay down, but a creeping cat's body glides at a constant height |

Two poses also carry a `_POSE_SCALE` entry in `artwork.py` because they fill
their canvas and cannot be enlarged further by the normaliser: the sphinx pose
and the belly-up roll.

After adding anything, run
[`scripts/check_sizing.py`](../../scripts/check_sizing.py). It measures every
pose as the app actually loads it and states plainly whether the sizes and floor
lines agree — the lying pose once shipped noticeably too small, and it took
measurement rather than looking to catch it.

## Known issue

`relaxed.png` and `relaxed_blink.png` came from two different generation runs,
so their dither and edge pixels do not line up and a blink changes more of the
sprite than just the eyes. Both source frames are committed; the fix is to
regenerate the closed-eye frame from `relaxed_new_eyes_open.png` and normalise
the pair together in a single run.

Every set generated after that one — Trusting, Playful, Hunting — was produced
in a single run per pose family specifically to avoid repeating it.

# `scripts/` — the art pipeline

Developer tools that support the pet's artwork. Nothing here runs as part of
the app — these are used by hand when adding or changing a cat pose, and the
app has no dependency on them.

| Script | What it's for |
|---|---|
| `normalize_pose.py` | Turn raw generated art into a finished sprite |
| `check_sizing.py` | Verify every pose is the right size and on the right floor |
| `render_showcase.py` | Regenerate the still images the root README uses |
| `render_demo_gif.py` | Regenerate the looping demo GIF the root README opens with |

## Why this folder exists

The cat's poses start life as generated images: a big picture of a cat on a
white background. The app can't use those directly. It needs every pose
delivered to the same specification — same canvas, same size relative to the
other poses, feet on the same invisible floor line — or the cat visibly jumps,
grows, or shrinks as it changes pose.

Getting that conversion right by hand is fiddly and easy to get subtly wrong.
These scripts do it consistently.

---

## `normalize_pose.py`

**What it does:** converts raw generated cat art into a finished sprite the app
can load.

**When you'd run it:** whenever a new pose is added, or existing pose art is
resized or regenerated.

It handles four things that are easy to get wrong manually:

- **Finds the cat reliably.** It picks out the largest connected shape in the
  image rather than trusting the image's edges, so a stray speck or a thin
  artifact along one side can't throw the sizing off. One of our source images
  has exactly that problem — a one-pixel grey stripe down its right edge.
- **Protects the eyes.** The app treats near-white pixels as background and
  makes them see-through when it loads a sprite. Left alone, that punches holes
  straight through the whites of the cat's eyes. The script spots white areas
  that are enclosed by the cat and darkens them just enough to survive.
- **Places the cat on the floor line.** Every pose shares a ground line, so the
  cat doesn't hover or sink when it switches between sitting, loafing and lying
  down.
- **Keeps blink frames in lockstep.** Poses that blink have two frames — eyes
  open and eyes closed. If the two are sized or positioned even slightly
  differently, the cat twitches every time it blinks. The script takes both
  frames in a single run and applies one set of measurements to both, so they
  can't drift apart. This is the main reason to use it rather than converting
  frames one at a time.

**Example** — how the current lying-down (Relaxed) pose was produced:

```bash
python scripts/normalize_pose.py \
    --width 499 --height 326 --ground 456 \
    --open   "meowsage/assets/relaxed_new_eyes_open.png"  meowsage/assets/relaxed.png \
    --closed "meowsage/assets/relaxed (eyes closed).png"  meowsage/assets/relaxed_blink.png
```

For a pose with no blink, drop the `--closed` line and let `--height` default to
the source image's own proportions.

### Poses with more than two frames

The script pairs an eyes-open frame with an eyes-closed one. A longer sequence —
the belly-up roll is three frames plus a blink — is run once per frame, which is
safe **only if you pass `--width` and `--height` explicitly every time**, worked
out from a single scale factor rather than letting each frame follow its own
proportions. Letting `--height` default would size each frame independently and
the cat would pump as the animation played.

Two further things caught the roll frames out, both worth checking on any new
sequence:

- **Align on the body, not the bounding box.** The script plants the lowest
  drawn pixel on the ground line. That is the same thing as the floor contact
  for every pose the app had before — but the rolling cat's tail trails below
  the body it belongs to, by a different amount in each frame. Aligned on the
  bounding box, the body bobbed about 7px through the roll. Measure how far the
  tail overhangs in each frame and add that to that frame's `--ground`.
- **Check the frames against each other, not just against the other poses.**
  A wobble within a sequence reads far worse than a sequence that sits a few
  pixels off from a pose it never animates into.
- **Not every sequence has a floor line.** The run cycle is the case: a
  galloping cat's paws leave the ground, so its frames genuinely sit at
  different heights and must not be forced onto one paw line. There, the thing
  to keep level is the torso, with the paws straddling the standing poses'
  floor on average. The stalk frames are aligned the same way for the opposite
  reason — the paws stay down, but a creeping cat's body has to glide at a
  constant height while they step.
- **Size a new pose by the cat's head.** How much cat is in the picture varies
  with the pose and, as the run frames showed, generated art does not always
  keep the head-to-body ratio fixed. Sizing the run cycle by visual mass made
  its head about 40% too big. The head is what reads as "the same cat".

The original generated images live alongside the finished sprites in
`meowsage/assets/` and are kept in the repository on purpose, so any pose can
be rebuilt at a different size later without going back for new art.

### One sizing limit worth knowing

How big a pose looks on screen is decided by how much of the canvas width the
cat takes up. That means there's a ceiling: once a pose fills its canvas, this
script can't make it any bigger, and it will refuse rather than quietly crop the
cat. Poses with limbs or a tail stretched out hit that ceiling soonest.

Going beyond it needs a per-pose adjustment in the app itself
(`_POSE_SCALE` in `meowsage/artwork.py`). If you do that, the pose's ground
line has to be raised to compensate, or the cat will sit lower than the others.
The lying-down pose is the worked example — see the comments in `artwork.py`.

---

## `check_sizing.py`

**What it does:** measures every pose and reports whether they're all drawn at
a consistent size and standing on the same floor.

**When you'd run it:** after adding or resizing a pose, before deciding it's
finished. Takes no arguments:

```bash
python scripts/check_sizing.py
```

This is the counterpart to the normaliser: one makes the art, this one checks
it. It exists because a pose being subtly the wrong size is genuinely hard to
spot by eye — the lying-down pose shipped noticeably too small, and it took
measurement rather than looking to confirm it and to know how much to correct
by.

It prints three tables:

- **Size and visual mass.** How much cat is actually in the picture. A pose
  with the tail and legs stretched out has a wide outline but not much cat, so
  outline size alone is misleading — this counts the cat itself.
- **Head width.** The head should be the same size in every pose, which makes
  it the most reliable way to tell whether a pose is at the right scale. The
  script calls out whether the comparable poses agree.
- **Window placement.** Whether the poses that lie down share a floor line, and
  whether anything is being cut off at the window edge. This is the check that
  catches the ground-line problem described above. It reports two floor
  numbers: `body y`, the line the cat actually rests on, and `lowest`, the
  bottom of the drawing. They differ only for poses with a trailing tail, and
  the verdict uses `body y`.

Each table ends with a plain verdict — "consistent" / "aligned", or a warning
naming what to adjust — so you don't have to interpret the numbers yourself.

Sitting and standing deliberately sit at their own heights and are reported for
reference only; the script doesn't treat them as errors.

---

## `render_showcase.py`

**What it does:** regenerates the two images the root README uses — the mood
ladder, and the multi-frame sequences — writing them to `docs/media/`.

**When you'd run it:** after adding a pose, changing a mood tint, or changing
anything else that alters how the cat looks on screen.

```bash
python scripts/render_showcase.py
```

It loads poses through the app's own `artwork.pixmap_for`, so the images show
the same background stripping, mood tint and per-pose scale the running app
shows. That is the point of generating them rather than taking screenshots:
documentation that is rebuilt from the source of truth can't quietly drift out
of date, and a reviewer looking at the README is looking at the real sprites.

---

## `render_demo_gif.py`

**What it does:** drives a real, headless `PetWindow` through sleepy → happy →
playful zoomies → trusting flop → sleepy, capturing a real `paintEvent` every
frame, and assembles the result into `docs/media/demo.gif` — the looping GIF
at the top of the root README.

**When you'd run it:** after changing a sprite, a mood tint, or any animation
timing constant that would make the existing GIF look stale.

```bash
pip install -e ".[docs]"   # adds Pillow, used only by this script
python scripts/render_demo_gif.py
```

It's the same headless technique the root README's "testing without a
display" section describes — a real `QApplication` and `PetWindow` under
`QT_QPA_PLATFORM=offscreen`, with `.grab()` forcing genuine paint events —
just with the frames kept instead of thrown away. `random.seed()` is pinned
before driving it, since the zoomies burst length and the trusting flop's
roll-cycle count and belly-up hold are all randomised; without a fixed seed
the same script could render a shorter or longer GIF on every run.

Two things worth knowing if you're changing the mood/timing script inside it:

- **Give a triggered animation time to finish before the next mood change.**
  Waking up from `SLEEPY` plays yawn (1.4s) then stretch (0.9s) unconditionally,
  and entering `PLAYFUL`/`TRUSTING` unconditionally starts zoomies/the flop the
  same way — firing another mood change mid-chain lets the old chain's own
  end-timer clobber the new one when it fires moments later. A zoomies burst
  that dies in under 100ms almost always means the previous hold was too
  short.
- **Keep the window well clear of the screen edge.** A zoomies dash that hits
  the edge ends *and* immediately tries the next leg synchronously (see
  `_run_step` in `animation.py`), so a window pinned at `(0, 0)` can collapse
  an entire burst into a couple of milliseconds instead of the ~2s it's meant
  to run for. The script homes the window at `(300, 300)`, clear of
  `WANDER_MAX_DIST_PX` in every direction inside the offscreen platform's
  800x800 virtual screen.

Qt itself can't produce the animated GIF: its `QImageWriter` happily reports
WebP as supporting animation, but repeated `write()` calls to it (even with
the same open `QFile`) silently keep only the last frame — verified by
writing then reading a multi-frame file back and finding `imageCount() == 1`.
Pillow is the one dependency here that earns its place for exactly that
reason, and it's scoped to `docs`, not `dev` or the app's own dependencies:
nothing under `meowsage/` imports it.

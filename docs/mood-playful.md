# Mood: Playful

**Cost tag**: 🟠 Medium-high — build Sat (with Hunting)

**Status: shipped.** Built as specced — three run frames, no leap frame, the
existing walk machinery run hot. Two things the spec didn't anticipate are
noted inline: how the run frames had to be sized and planted, and a
screen-edge bug this state exposed in the movement code.

## Vibe

The "zoomies" — cat runs in circles / darts around energetically. Cat
equivalent of a burst of pure excitement. Only happens at the very top of
the usage-activity range, above Happy.

## Trigger

Very high band, above Happy's current threshold. Placeholder: `>= 0.95` (a
narrow slice at the very top, so it reads as a rare, special burst rather
than a common state — matches the "really high" framing from the original
ask).

## Art requirements

- **Run-cycle frames**: distinct from the existing walk cycle
  (`walking.png` + `cat_base.png` swap) — faster gait, more energy. 2-3
  frames is enough for a convincing run cycle at this sprite scale, same
  fidelity approach as the existing walk animation.
- Optional stretch: a leap/jump frame, if the "jumping around" half of the
  original description is worth the extra asset. Not required for a
  believable zoomies effect — running alone reads fine.

**Shipped**: three frames (`run_a` full extension, `run_b` gathered, `run_c`
push-off), no leap frame — running alone did read fine. Cycled as
B → C → A → C, using the half-extended frame as the in-between in both
directions.

Two things about the art that the other poses hadn't raised:

- **Size them by the head, not by how much cat is in the picture.** These
  frames are drawn with a noticeably bigger head relative to the body than the
  standing cat, so matching visual mass — which is how the lying poses were
  sized — made the head about 40% too large and the cat read as a different,
  chibi-ish character. `_POSE_SCALE` is set so the head matches `cat_base.png`
  instead.
- **A gallop has no single floor line.** The paws genuinely leave the ground,
  so the frames cannot share a paw line with the standing poses and must not be
  forced to. What has to stay level is the *torso*, or the cat pogos as it
  runs. The cycle is planted so its torso is level across all three frames and
  its paws straddle the standing floor line on average. `check_sizing.py` now
  measures and judges exactly that.

## Timing / state machine — reuses existing movement, doesn't invent new

This is the one place where leaning on existing code saves real time:
`animation.py` already has a full walk-to-target movement system
(`_start_walk`/`_walk_step`/`move_to` signal, wandering within
`WANDER_MAX_DIST_PX` of the home position). Playful should **extend that
mechanism**, not build new movement logic:

- On entering Playful, fire off a quick sequence of several short
  wander targets in succession (instead of walking's usual single target),
  with a shorter step interval (`WALK_STEP_MS`) and/or larger step size
  (`WALK_SPEED_PX`) than normal walking, so it visually reads as running
  rather than strolling.
- A true circular path is not necessary — several quick zigzag/short-hop
  targets in a tight radius around home reads as "zoomies" without needing
  any new geometry/pathing code.
- After a fixed burst duration (e.g. a few seconds) or a fixed number of
  target-reaches, fall back to whatever `Behavior` the underlying mood
  (Happy, since Playful is the top rung) would normally show.

## Speech lines (draft)

- "ZOOMIES"
- "*sprints for no reason*"
- "gotta go fast"
- "can't stop won't stop"
- "the floor is lava (it's not, I just felt like running)"

## Interaction with existing systems

- New `Behavior.PLAYFUL` (or similar), entered as a one-shot burst like
  yawn, but internally driving several walk-style movement legs instead of
  one.
- Update `_MOOD_RANK` to slot above Happy.
- No new subsystem required — this is the "extend, don't invent" state,
  which is why it's cheaper than Hunting despite both being scheduled for
  Saturday.

**Shipped**: 3-5 dashes of 90-240px each at three times the walk's step size
and half its interval, turning back toward home past 60% of the wander radius.
`_walk_target` is shared with walking rather than duplicated, since only one of
the two can be active at a time.

The one thing that wasn't free: **nothing stopped the pet walking off the edge
of the screen.** That was already true at walking speed — it starts in the
bottom-right corner and wanders up to 300px either way — but the zoomies made
it constant rather than occasional. `PetWindow._move_within_screen` now clamps
horizontally, which in turn exposed a second problem: with the window clamped,
a target beyond the edge can never be reached, the distance never shrinks, and
the cat sprints on the spot against the edge indefinitely. Both step functions
now treat "asked the window to move and it didn't" as arrival.

## Open questions

- Exact burst duration / number of legs — tune by feel once it's running;
  starting guess is 3-4 short legs, a few seconds total.
- Should Playful ever interrupt itself if usage drops mid-burst? Recommend
  no, same reasoning as Trusting — let it finish once triggered.

# Mood: Hunting / Slithering

**Cost tag**: 🔴 High — build Sat (with Playful); first to cut if the week runs short

**Status: shipped.** It did not get cut. Built as specced — cursor dwell
trigger, creep-and-freeze in place, no creeping movement — with the geometry
questions this doc left open answered below, plus one rule the spec was
missing that would have made the feature unpleasant to live with.

## Vibe

Cat drops low to the ground and moves in a sneaky, stalking fashion,
periodically stopping to inspect. Cat behavior in "prey detected" mode.
Unlike every other state in this doc set, this one isn't purely
usage-driven — it's triggered by user interaction (cursor position).

## Trigger — the one new subsystem

Fires when **the cursor stays within the pet's "line of sight" and doesn't
move for 5 seconds**, gated so it can only trigger when the underlying
usage-mood ladder position is **Content or above** (per the scoping
decision to only allow hunting at moderate-to-high usage, not e.g. while
Sleepy). Nothing in the codebase tracks cursor position today — everything
else is driven purely by the `activity_level` number, so this is genuinely
new ground, not an extension of an existing mechanism like the other 4
states are.

Rough shape of the mechanism:

- Poll `QCursor.pos()` (global screen coordinates) on a timer — every
  250-500ms is plenty; no need for per-frame precision.
- Compare against the pet window's geometry to decide "in line of sight."
  Simplest definition: cursor's Y coordinate falls within some vertical
  band around the pet's Y position, and it's within some horizontal
  distance (not necessarily touching the pet). Exact zone is a tuning
  decision, not a design one — start generous, narrow if it triggers too
  often.
- Track how long the cursor has stayed roughly stationary (e.g. hasn't
  moved more than a few pixels between polls) while inside that zone. At
  5 seconds of stillness-in-zone, trigger Hunting.
- On trigger: **override** whatever pose is currently showing, regardless
  of which ladder rung produced it (as long as the gate condition holds).
  On exit (cursor moves, or after some hunting-behavior duration), fall
  back to whatever the ladder says underneath — same "interrupt over a
  base state" relationship the yawn transition has, but keyed on a
  different signal.

## Art requirements

- **Creep pose(s)**: low-to-ground, sneaking posture. 2 frames is enough
  for a creeping animation (mirrors the walk cycle's 2-frame swap
  approach).
- **1 "stop and inspect" pose**: alert, still, focused — held briefly
  during the pauses described in the original ask.

## Timing / state machine

1. Gate check passes + 5s cursor stillness detected → enter Hunting,
   overriding current pose.
2. Creep animation plays, optionally with slow movement toward the cursor
   position (reusing the walk-step movement primitive at a slower speed,
   same "extend, don't invent" approach as Playful) — or, simpler for v1,
   no actual movement at all, just the creep animation playing in place.
   Recommend starting with **no movement** (cheapest version that still
   sells the vibe) and only adding creep-toward-cursor motion if time
   allows.
3. Periodically switch to the "stop and inspect" pose for a beat, then
   back to creeping — alternate a couple of times.
4. Exit condition: cursor moves (breaks the stillness), or a max duration
   elapses. Either way, fall back to the underlying ladder `Behavior`.

## Speech lines (draft)

- "..."
- "*eyes narrow*"
- "I see you"
- "stalking mode: engaged"
- "don't move"

## Interaction with existing systems

- Needs a new timer in `Animator` (or wherever cursor polling is wired up)
  independent of the existing `POSE_TICK_MS` re-roll cycle — this is
  parallel infrastructure, not a slot in `_POSE_WEIGHTS`.
- The override relationship (Hunting can pre-empt any Content-or-above
  ladder state) means it needs to interact with whatever transition logic
  governs entering/exiting one-shots — worth deciding whether an
  in-progress Hunting sequence can itself be interrupted by, say, usage
  crossing back below the gate threshold, or whether (like Trusting and
  Playful) it should always finish once started. Recommend the latter for
  consistency with the other one-shots, unless it turns out to look odd in
  practice.

## What shipped

All the tuning lives in `Animator` as `STALK_*` constants, next to the rest of
the animation tuning rather than in `config.py` — that module is deliberately
about the usage model, and none of this is usage.

- **Line of sight**: cursor between 60 and 500px horizontally from the cat's
  centre, within a 130px vertical band of it. The near bound stops the cat
  stalking a pointer resting on its own face; the far bound stops it stalking
  something on the other side of a wide display.
- **Stillness**: 4px of jitter still counts as stopped, sampled every 300ms,
  for 5s.
- **The sequence**: 2-3 beats of (4 creep frames at 380ms, then a 1200ms
  freeze), so 5.4-8.1s in total. It re-aims at the cursor at the start of each
  creep run rather than every step, so a drifting cursor cannot make it
  jitter; the idle gaze check stands down for the duration.
- **It closes on the cursor.** This doc recommended skipping movement for v1
  and that is what shipped first, but creeping in place read as a cat
  pretending to stalk. It now advances 1px per 40ms tick — half the walk's
  speed — during the creep beats only, and stands still during the freezes.
  It stops 70px short rather than climbing onto the cursor, and gives up
  advancing at a screen edge instead of grinding against it. This reuses the
  walk's `move_to` step primitive exactly as the doc anticipated.
- **Hunting is a flag, not a `Behavior`.** It overlays whatever the ladder was
  showing and hands it straight back, so there is no behavior to save and
  restore. `_tick_pose` stands down while it runs, and the blink is suppressed
  — a stalking cat holds the stare, and there is no eyes-closed creep art.
- **Right-click → "Hunt now"** skips the 5s wait but still honours the mood
  gate, so it exercises the real entry condition rather than a back door.

### The rule the spec was missing

As written, the trigger would re-arm against a cursor that had never moved —
which is exactly what happens when you walk away from the desk. The cat would
stalk an abandoned pointer indefinitely, five seconds at a time, forever. So
after a hunt the trigger **disarms**, and the cursor must travel at least 60px
before it can count again. There is a 20s cooldown on top.

Moving the cursor also breaks an active hunt, which is a deliberate departure
from this doc's recommendation that one-shots always finish: the entire
premise is that the cat is watching something that has stopped moving, so
continuing to stalk empty space reads as broken rather than as charming. The
break is applied at the next beat boundary, never mid-creep.

## Open questions — the real risk in this state

- **Exact geometry for "line of sight"** isn't specified beyond "direct
  line of sight" in the original ask — needs an actual definition before
  it can be built. The vertical-band-plus-horizontal-distance approach
  above is a reasonable default, but confirm it matches the intended feel
  once you're looking at the pet on screen.
- **Multi-monitor / cursor far from pet**: what counts as "in line of
  sight" if the cursor is on a different display? Simplest v1 answer:
  restrict the check to the same screen the pet lives on, treat other
  screens as "not in sight." Not addressed further here — flag if it comes
  up.

  **Shipped**: handled implicitly rather than explicitly. The distance bounds
  are in global screen coordinates, so a cursor on another display is almost
  always outside the 500px reach or the 130px band and fails the check anyway.
  A second display butted directly against the pet's, with the cursor just
  over the seam, would still qualify — which is arguably correct, and is
  untested since there is only one display here.
- This is the state most likely to get cut per the v1 cutline rule. If
  Saturday's block runs out before this is solid, it rolls to backlog —
  that's the plan working as intended, not a failure.

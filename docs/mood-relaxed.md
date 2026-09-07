# Mood: Relaxed

**Cost tag**: 🟢 Low — build first (Tue)

## Vibe

Cat lies down with its head up and alert (not sleeping) — see reference
photo shared during scoping: paws tucked forward, upright head, calm gaze.
Blinks and/or closes its eyes periodically while in this position. The
"resting but aware" middle state between Tired's fatigue and Content's
active idling.

## Trigger

Mid band of the usage-activity axis, between Tired and Content on the
ladder. Placeholder range: roughly `0.45–0.60` (currently the upper part of
Tired's range and lower part of Content's — exact split to be tuned once
on screen).

## Art requirements

- **1 new static pose**: lying down, head up, eyes open — matching the
  reference photo's composition.
- **1 optional companion pose**: same position, eyes closed — needed only
  if you want blinking to actually render (see timing section). If skipped,
  the cat simply doesn't blink while Relaxed for v1, which is an acceptable
  cut if time is tight.

## Timing / state machine

Enters via the same weighted re-roll mechanism as other idle behaviors
(`_POSE_WEIGHTS` for whichever `Mood` covers this band) — no one-shot
transition needed, it's a steady-state idle pose like `IDLE_SITTING` today.

For blinking: the existing blink system
(`_start_blink`/`_end_blink` in `animation.py`) is currently gated to only
fire during `IDLE_STANDING`/`WALKING`, with a comment explicitly noting
that popping into a blink from sitting/sleeping would look wrong — because
today there's only one "eyes closed" sprite, matched to the standing pose.
To support blinking in Relaxed, that gate needs to widen to include the new
Relaxed behavior, **and** the eyes-closed companion pose above needs to
exist so the blink renders correctly for this pose. If that's more than
the low-cost budget allows, cut blinking for this state — it'll just be a
still, calm pose, which still reads fine.

## Speech lines (draft)

- "just resting my eyes... sort of"
- "*settles in*"
- "watching the world go by"
- "comfy right here"
- "mmm, nice and calm"

## Interaction with existing systems

- New `Behavior` entry (e.g. `Behavior.RELAXED`) with a weight in this
  band's `_POSE_WEIGHTS` row.
- Update `_MOOD_RANK` to slot this `Mood` between Tired and Content.
- Blink-gate change (see above) is the only piece of shared-code surgery
  this state requires; everything else is additive.

## Open questions

- Is the eyes-closed companion pose worth generating now (AI art is fast
  per the earlier scoping call), or does it get deferred? Given the art
  pipeline is cheap, leaning toward "generate it" — but this doc's cost
  tag assumes it might not happen, so don't let it block Tuesday's session
  if it turns out fiddlier than expected.

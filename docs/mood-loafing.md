# Mood: Loafing

**Cost tag**: 🟢 Low — build first (Tue)

## Vibe

Cat is seated in a tight "loaf" position — paws tucked under the body,
compact, still. The low-usage equivalent of Content's "just chillin'": not
distressed like Tired/Sleepy, just settled and unbothered.

## Trigger

Low band of the usage-activity axis, between Sleepy and Tired on the
ladder. Placeholder range: roughly `0.12–0.28` (i.e. carving out a slice
that currently falls inside what's Sleepy/Tired today — exact split to be
tuned once it's on screen next to the existing thresholds).

## Art requirements

- **1 new static pose**: the loaf position. No motion within the pose is
  required for v1 — a single sprite is enough, matching the fidelity of
  existing poses like `Sitting.png`.
- Optional stretch (not required): an eyes-closed variant, if there's time
  left after the core 5 states — see "Open questions" below.

## Timing / state machine

The cat enters Loafing, holds for **a couple of seconds**, then gets up.
Two ways to implement, in order of preference:

1. **Simplest**: add `Behavior.LOAFING` as a new entry in
   `_POSE_WEIGHTS` for whatever `Mood` covers this band, same as
   `IDLE_SITTING` today. The existing 6-second pose-tick (`POSE_TICK_MS`)
   naturally gives it a multi-second hold before the next re-roll. This
   doesn't exactly match "a couple of seconds" (it's closer to "up to 6s"),
   but costs nothing new to build.
2. **If the shorter, more deliberate hold matters**: implement as a
   one-shot like yawn — enter Loafing, start a ~2-3s single-shot timer,
   then transition to `IDLE_STANDING` (or re-roll) when it fires. More
   faithful to the spec, marginally more code.

Recommendation: start with option 1 for Tuesday's session; only upgrade to
option 2 if it visibly doesn't read as "a couple of seconds" once you see
it running.

## Speech lines (draft)

- "loaf mode activated"
- "*tucks paws*"
- "just a lil loaf"
- "nothing to see here"
- "compact and content"

## Interaction with existing systems

- Slots into `_POSE_WEIGHTS` the same way `IDLE_SITTING`/`IDLE_STANDING`
  do today for its `Mood` band — no new transition logic needed beyond
  whatever mood-rank ordering falls out of inserting a new rung (update
  `_MOOD_RANK` accordingly).
- No blink support needed for v1 (loaf pose can just not participate in
  the blink-eligible behavior set, same as `IDLE_SITTING`/`SLEEPING`
  already don't).

## Open questions

- Does Loafing get its own `Mood` enum value, or does it share a `Mood`
  with an adjacted state and differ only by `Behavior`? (The ladder implies
  each named state is its own `Mood`, which is the cleaner mental model and
  what these docs assume — but worth confirming before touching
  `_MOOD_RANK`.)
- Eyes-closed variant: worth the extra asset, or is the static loaf pose
  enough? Default to "enough" unless it looks incomplete once built.

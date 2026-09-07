# Mood: Trusting

**Cost tag**: 🟡 Medium — build Wed

**Status: shipped.** What landed matches this spec with three changes, noted
inline below: a fourth sprite and a slow-blink behavior were added, the hold is
1.5-3.5s rather than 0.2-3s, and the flop yields to a mood-change transition
instead of always finishing.

## Vibe

Cat rolls onto its back, exposing its stomach — a real trust display in cat
body language. Rolls around 2-3 times, looking relaxed, then stays lying on
its back for a random duration before getting back up. The "high trust,
high usage" state, sitting between Content and Happy on the ladder.

## Trigger

High band of the usage-activity axis, between Content and Happy.
Placeholder range: roughly `0.78–0.85` (a slice carved out of what's
currently the top of Content's range — exact split to be tuned once on
screen next to Happy's existing `>= 0.85` threshold).

## Art requirements

- **Roll sequence**: 2-3 frames capturing the rolling motion (e.g.
  side → back-tilted → fully on-back). Doesn't need to be a smooth
  many-frame animation — a quick 2-3 frame cycle read as "rolling" is
  enough, similar fidelity to the existing walk cycle's 2-frame swap.
- **1 resting pose**: fully on its back, belly exposed, relaxed — this is
  what's held during the random-duration pause.

**Shipped**: three frames as specced (`trusting_roll_a`, `trusting_roll_b`,
`trusting_back`) plus a fourth that wasn't — `trusting_back_blink`, the resting
pose with its eyes closed, which buys the slow blink described under Timing.
All four were generated in one run, so unlike the Relaxed pair their frames
share a dither and the blink moves only the eyes.

The belly-up silhouette is the widest in the set and fills 500 of the canvas's
504px, so all four carry a `_POSE_SCALE` of 1.105 — see `artwork.py`. They are
also the first poses whose lowest pixel is *not* their floor contact: the tail
trails below the body by a different amount in each frame, so they are aligned
on the body line, and `check_sizing.py` learned to measure that.

## Timing / state machine

This is a one-shot transition, same pattern as `_play_yawn`/`_end_yawn`:

1. Enter Trusting → play the roll sequence (2-3 frame cycle, repeated ~2-3
   times per the original spec — "rolls around 2-3 times").
2. Land on the resting on-back pose.
3. Hold for a **random duration between 0.2 and 3 seconds** (this is new:
   existing one-shot timers like yawn use a fixed duration —
   `YAWN_DURATION_MS` — so this needs `random.uniform(200, 3000)` or
   similar instead of a constant).
4. Transition out to a follow-up `Behavior` (standing or sitting — either
   is fine; sitting might read as a more natural "getting up" beat).

**Shipped**: the hold is **1.5-3.5s** (`BELLY_HOLD_MIN_MS`/`MAX_MS`). The
spec's lower bound of 0.2s is shorter than a single roll frame and read as a
glitch rather than a pause — the cat appeared to bounce off its own back.

The hold is also no longer dead time: it plays a **slow blink** on a ~1.1s
cadence (`SLOW_BLINK_INTERVAL_MS`), with the eyes shut for 650ms against the
normal 140ms. A slow blink is the same trust signal in cat body language that
the belly is, so it belongs here more than anywhere else in the app. It is
driven off its own timer rather than the idle 3-6s blink timer, which would
miss a hold this short more often than it caught it.

Exit is `IDLE_SITTING`, the "getting up" beat.

## Speech lines (draft)

- "belly's out, don't judge me"
- "*rolls over*"
- "I trust you, human"
- "vulnerable but vibing"
- "flop"

## Interaction with existing systems

- New `Behavior` values for the roll-in-progress state and the on-back
  resting state (or one `Behavior.TRUSTING` covering both, with the
  animator tracking a sub-phase — whichever fits the existing code's
  style better; `_is_yawning`-style boolean flags are the precedent).
- Follows the yawn pattern for entry/exit, but needs a randomized hold
  timer rather than a fixed one — the one genuinely new piece of timing
  logic in this state.
- Update `_MOOD_RANK` to slot between Content and Happy.

## Open questions

- What triggers the *exit* pose — always stand, always sit, or a coin
  flip? Original spec just says "sitting up or standing up," implying
  either is acceptable. Recommend picking whichever is visually simpler to
  wire up first (probably standing, since it's the more common idle
  fallback elsewhere in the code) and only add the second option if there's
  slack.
- Should Trusting be interruptible (e.g. if usage suddenly drops
  mid-roll)? Recommend no for v1 — let the one-shot always finish once
  started, same as yawn does today. Simpler and avoids a half-finished
  animation looking broken.

  **Shipped**: uninterruptible, with one exception. A mood change that plays
  its own transition — dropping to Tired, Loafing or Sleepy, all of which
  yawn — cancels the flop first. The two animations are not mutually
  exclusive in the renderer, so leaving the roll running would have drawn a
  yawning cat over a body still rolling underneath. A mood change to a band
  with no transition of its own (Content, Relaxed) still lets the flop play
  out, which is the case the "don't interrupt" rule was really about.

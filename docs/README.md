# `docs/` — behaviour specs

One document per behaviour, each written **before** the behaviour was built and
then annotated afterwards with what actually shipped.

They are kept in that shape on purpose. The interesting content is usually the
gap between the two: what the spec assumed, what turned out to be wrong once it
was on screen, and why. Several of those gaps were only findable by building the
thing.

## The specs

| Behaviour | Where it sits | Spec |
|---|---|---|
| Loafing | Bottom quartile of your recent activity | [mood-loafing.md](./mood-loafing.md) |
| Relaxed | Just below your median | [mood-relaxed.md](./mood-relaxed.md) |
| Trusting | Above the 65th percentile | [mood-trusting.md](./mood-trusting.md) |
| Playful | Above the 90th percentile | [mood-playful.md](./mood-playful.md) |
| Hunting | Overlay, gated to Content or above | [mood-hunting.md](./mood-hunting.md) |

These five were added on top of the four the app shipped with (`SLEEPY`,
`TIRED`, `CONTENT`, `HAPPY`), giving the ladder in the
[root README](../README.md):

```
SLEEPY → LOAFING → TIRED → RELAXED → CONTENT → TRUSTING → HAPPY → PLAYFUL
```

Hunting is not on that ladder. It's a cursor-triggered interrupt that overrides
whatever the ladder is showing and then hands control straight back.

## Where the specs turned out to be wrong

Worth reading for anyone judging how the project was actually run, since each of
these was a decision made against the written plan rather than in the absence of
one:

- **Trusting** specced a 0.2–3s hold on the belly-up pose. 0.2s is shorter than
  a single roll frame and read as the cat bouncing off its own back. Shipped at
  1.5–3.5s.
- **Playful** was specced to keep the cat's paws on one floor line like every
  earlier pose. A galloping cat's paws leave the ground; forcing them onto one
  line made the body pogo. The torso is what stays level.
- **Hunting** specced no movement for v1 and, as first built, had none. Creeping
  in place read as a cat pretending to stalk, so it now closes on the cursor.
  Its trigger also needed a rule the spec never mentioned: without disarming
  after each hunt, the cat stalks an abandoned cursor indefinitely.

## Not a behaviour

- [codex-support.md](./codex-support.md) — reading OpenAI Codex's session logs
  alongside Claude Code's, so one cat is driven by both. Same spec-first shape
  as the behaviour docs above, but it's a data-source change: no new moods, no
  new art. **Shipped**, with the token-based path mostly dormant — the current
  Codex release logs no token usage, so it runs on the turns-per-minute
  fallback the spec anticipated.

## Also here

- [`media/`](./media) — the images the root README uses. Generated from the real
  sprites by [`scripts/render_showcase.py`](../scripts/render_showcase.py), so
  they cannot drift out of sync with the app.

## Related

- [`../meowsage/README.md`](../meowsage/README.md) — how the code implements
  all of this.

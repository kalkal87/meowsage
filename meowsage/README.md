# `meowsage/` — the application

Everything the installed app runs: about 2,450 lines of Python across ten
modules plus two entry-point shims, with one dependency (PySide6) and no build
step.

## The shape of it

Data flows one way. Nothing downstream ever calls back upstream:

```
usage.py  ──▶  pet.py  ──▶  animation.py  ──▶  artwork.py  ──▶  paintEvent
 what the      when to       what the cat       which sprite      pixels
 numbers say   ask, and      is doing and       that is
               the window    where it is
```

That direction is the main design constraint worth preserving. `usage.py` knows
nothing about cats; `artwork.py` knows nothing about token counts.

## Modules

| Module | Responsibility |
|---|---|
| `cli.py` | The `meow` command: launch, rename, macOS autostart via LaunchAgent |
| `banner.py` | The ASCII logo printed at launch, before the slow PySide6 import |
| `appbundle.py` | Builds `Meowsage.app`, the only way macOS labels the app by name |
| `app.py` | Creates the `QApplication`, places the window bottom-right, runs the loop |
| `profile.py` | The cat's name, stored as JSON in Application Support |
| `usage.py` | Reads Claude Code and/or Codex logs, scores activity, produces a `Usage` snapshot |
| `config.py` | Every tunable of the usage model, in one dataclass |
| `moods.py` | The `Mood` enum, the activity→mood thresholds, and the speech lines |
| `pet.py` | `PetWindow` — the frameless always-on-top widget, input, painting |
| `animation.py` | `Animator` — all motion state, behind a set of `QTimer`s |
| `artwork.py` | Sprite loading, background stripping, mood tinting, pose registry |
| `speech.py` | The speech bubble, as its own click-through overlay window |

### `usage.py` — where the signal comes from

Sources behind one interface, chosen by `make_default_usage_source()`:

- **`LogUsageSource`** scores one or more *readers* — `ClaudeCodeReader`
  (`~/.claude/projects/*/*.jsonl`) and `CodexReader`
  (`~/.codex/sessions/YYYY/MM/DD/*.jsonl`) — each against its own last hour by
  minute, weighting tokens by type. When more than one reader is active it
  reports whichever currently ranks busier; a tool doesn't need to weight
  tokens the same way as the other, since each is only ever compared against
  its own recent history. Which readers run is auto-detected from which log
  directories exist, or forced via `MEOWSAGE_SOURCES`.
  `ClaudeCodeUsageSource` is kept as a Claude-Code-only alias for anyone
  importing it directly. See `docs/codex-support.md` for the design
  rationale, including why Codex needs a token-less fallback.
- **`StubUsageSource`** just returns whatever activity level you set. Driven by
  the `MEOWSAGE_STUB` environment variable, and the reason developing this is
  not agonising — you can be in any mood in one second rather than by generating
  real load.

`config.py` holds the tunables and is deliberately import-free from the rest of
the package, so it can be read standalone.

### `animation.py` — the part that grew

`Animator` owns every piece of motion state and exposes two signals
(`update_needed`, `move_to`) plus `current_render()`. `PetWindow` never reaches
inside it.

Two concepts that are easy to confuse:

- **`Mood`** is what the usage says — one of eight rungs.
- **`Behavior`** is what the cat is *doing* — walking, loafing, mid-zoomies.
  Chosen by weighted random draw from `_POSE_WEIGHTS[mood]`, re-rolled every six
  seconds.
- **`Pose`** (in `artwork.py`) is which literal sprite is on screen this frame.

Multi-frame sequences — the belly-up flop, the zoomies, the stalk — all follow
one pattern: they run themselves through their own timers to a settled
behaviour, and `_tick_pose` stands down while they do. Each holds the invariant
that its `Behavior` is only ever set while its timers are running, so the cat
can never be stranded mid-animation.

Some animation is procedural rather than drawn: the stretch is a
`QPainter.scale()` on the standing sprite, the perk-up is a sine bounce, the
breathing is a sine offset. That was a deliberate trade — motion that needs no
new art is motion that can be added in an afternoon.

Hunting is the exception to the whole structure. It's an overlay driven by
cursor position rather than usage, so it's a flag rather than a `Behavior` and
has no row in `_POSE_WEIGHTS`.

### `artwork.py` — two things that will bite you

1. **Near-white is transparent.** Any pixel with all RGB channels above
   `WHITE_THRESHOLD` (240) is stripped at load. That includes the whites of the
   cat's eyes, which is why the normaliser darkens enclosed white regions before
   the app ever sees them.
2. **Poses share a ground line.** Sprites are scaled to a fixed width and
   anchored at the pixmap's bottom edge, so a new pose that doesn't match the
   canvas and floor conventions makes the cat visibly jump when it swaps in.

Both are covered in [`assets/README.md`](assets/README.md) and the
[art pipeline](../scripts/README.md).

## Adding a mood

The thresholds live in two places and both must be updated, because the demo
path and the real path express the ladder differently:

1. `moods.py` — the `Mood` member, its cutoff in `mood_for_activity()`, and its
   speech lines.
2. `config.py` + `usage.py` — its percentile cutoff and a branch in
   `_classify_mood`.
3. `animation.py` — a row in `_POSE_WEIGHTS`, a slot in `_MOOD_RANK`, and any
   transition in `_on_mood_changed`.
4. `artwork.py` — a `_MOOD_TINTS` entry, plus `Pose` entries for new art.
5. `pet.py` — an anchor value in the dev "Force mood" menu.

A missed table is the most common way to break this, and it fails at runtime
rather than at import — worth a sweep asserting every enum member appears in
every table keyed by it.

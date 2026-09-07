# Codex support — one cat, both signals

**Cost tag**: 🟡 Medium — one new reader plus a small refactor. No new art, no
new moods, no animation work.

**Status: shipped**, in `meowsage/usage.py` and `meowsage/moods.py`. Written
before implementation, in the shape of the behaviour specs in this folder;
this version is annotated with what actually shipped and where the plan
turned out to be wrong. The original pre-build text follows below that.

## What shipped, and where the spec was wrong

- **Step 0 came back negative, confirmed harder than the spec's single
  sample.** Two more current-version (0.147.0) sessions were checked (Aug 8
  and Aug 10, 2026): both show zero `token_count` events in the rollout and
  `tokens_used = 0` in `state_5.sqlite`'s `threads` table, same as the
  original one-session finding. The fallback path — turns/minute instead of
  tokens/minute — is what's built for the current Codex. `CodexReader` still
  prefers real per-category tokens when a session's rollout has them (older
  versions, 0.118–0.120, do), so the token-based path isn't dead code; it's
  just not what fires today.
- **A finding the spec missed: `token_count.info` can be `null`.** Not every
  `token_count` event carries a `total_token_usage` — some are rate-limit-only
  pings with `"info": null`. Treating that as a real zero reading (rather than
  skipping it outright) resets the running per-category totals, which makes
  the *next* real event look like it just produced a whole fresh session's
  worth of tokens. Found by cross-checking a diffed raw total against the
  weighted one on a real fixture (`rollout-2026-04-06T10-15-26-...jsonl`) — the
  event counts didn't match until this was fixed. `_parse_codex_jsonl` now
  skips these without touching `prev`.
- **Combining strategy: separate baselines, take the higher mood** — the
  spec's second option, not the first. Each reader is scored independently
  against its own history; `LogUsageSource` reports whichever reader's mood
  currently ranks higher on the ladder (`moods.mood_rank`). The spec's
  alternative (scale Codex's nominal per-turn weight to match Claude's
  observed median) was passed over as an explicit choice — it's harder to get
  right and has nothing to calibrate against while Codex's token-less
  fallback is what's actually running.
- **The nominal per-turn weight for the token-less fallback turned out to be
  arbitrary, not something to calibrate at all.** Because moods (not raw
  magnitudes) are compared across sources under the "separate baselines"
  strategy, any positive constant produces identical behaviour — a fact the
  original spec didn't need to reach because it was written under the
  scale-to-match strategy, where the constant's value mattered.
- **CLI surface not built.** The spec assumed a `meow status` command to hang
  a `sources` row off; no such command exists in this codebase. Out of scope
  for this pass — worth adding if `meow status` is ever built.
- **File scanning optimisation shipped as specced**: `CodexReader` walks only
  the dated directories the baseline window can reach, rather than the whole
  session history, every refresh.
- **`MEOWSAGE_SOURCES` override shipped as specced**, including warn-and-ignore
  on an unrecognised name.
- **Still open**: sub-agent thread rollout files aren't specifically counted
  or excluded — see [Open questions](#open-questions) below, unchanged from
  the original spec.

---

## Original spec (pre-build)

**Status: specced, not built.** Written before implementation, in the shape of
the behaviour specs in this folder. Annotate it afterwards with what actually
shipped and where this document was wrong.

**Blocked on a verification step** — see [Step 0](#step-0-before-writing-any-code).

### Goal

Someone who uses Codex instead of Claude Code gets the same pet, working the
same way. Someone who uses both gets **one cat driven by both**, because the
product is "how hard are *you* working", not "how hard is this particular tool
working". Which tool you happen to have open should not change the cat.

Explicitly **not** in scope: a Codex cat and a Claude cat as separate modes, a
per-tool breakdown in the UI, or any change to the mood ladder.

---

### Step 0 — before writing any code

**Confirm that the current Codex still records token usage.** If it does not,
most of this document is wrong and the fallback in
[No tokens?](#fallback--what-if-current-codex-records-no-tokens) is the design
instead. Do this first; it is cheap and it gates everything else.

What the investigation found on this machine (Aug 2026):

| Codex version | Sessions | `token_count` in rollout | `threads.tokens_used` |
|---|---|---|---|
| 0.118–0.120 (Dec 2025 – May 2026) | 74 | present in 74/74 | populated (millions) |
| **0.147.0 (Aug 2026, current)** | 1 | **absent** | **0** |

Two independent places that previously recorded tokens both read zero on the
current version. That is one short session, so it is suggestive rather than
conclusive — but it is the single biggest risk in this feature, and it is not
worth designing around an assumption when a five-minute check settles it.

**How to verify:**

1. Run a real Codex session that does meaningful work (a few turns, some file
   edits — not a one-line "hello").
2. Find the newest rollout file:
   ```bash
   find ~/.codex/sessions -name '*.jsonl' -print0 | xargs -0 ls -t | head -1
   ```
3. Check for token records:
   ```bash
   grep -c '"token_count"' "$THAT_FILE"
   ```
4. Cross-check the database:
   ```bash
   sqlite3 ~/.codex/state_5.sqlite \
     'select cli_version, tokens_used, datetime(updated_at,"unixepoch") \
      from threads order by updated_at desc limit 5;'
   ```

**If (3) returns a non-zero count**, build as specced below.
**If (3) is zero but (4) shows a non-zero `tokens_used`**, the data moved to the
database — same design, different reader, and the spec below still holds apart
from the parsing section.
**If both are zero**, go to the fallback section.

---

### What Codex writes (verified)

Sessions live in dated files, one per session:

```
~/.codex/sessions/YYYY/MM/DD/rollout-<ISO8601>-<uuid>.jsonl
```

Structurally the same deal as Claude Code's `~/.claude/projects/*/*.jsonl` —
line-delimited JSON, one record per line, every record timestamped. Usage
arrives in records shaped like this:

```json
{
  "type": "event_msg",
  "timestamp": "2026-04-06T14:15:48.372Z",
  "payload": {
    "type": "token_count",
    "info": {
      "last_token_usage":  {"input_tokens": 23181, "cached_input_tokens": 5504,
                            "output_tokens": 495, "reasoning_output_tokens": 376,
                            "total_tokens": 23676},
      "total_token_usage": {"...same shape, cumulative for the session..."},
      "model_context_window": 258400
    },
    "rate_limits": {"...ignore..."}
  }
}
```

Select on `type == "event_msg"` **and** `payload.type == "token_count"`.

#### Two findings that are not guessable

Both were established by measurement, and both will produce a plausible-looking
but wrong cat if ignored.

**1. Do not sum `last_token_usage`. Diff `total_token_usage` instead.**

`last_token_usage` looks like a clean per-turn delta, and for the first several
turns it is exactly that. But Codex sometimes emits the same `token_count`
event twice in a row. Over one real 106-event session, summing
`last_token_usage` gave 13,751,696 tokens against a true total of 12,768,061 —
**an 8% overcount**, entirely from 7 duplicated events.

`total_token_usage` is monotonic within a session (verified: zero decreases
across the sample). Diffing consecutive values gave 12,768,061 — exact.

```python
prev = 0
for event in token_count_events_in_file_order:
    total = event["info"]["total_token_usage"]["total_tokens"]
    delta = total - prev if total >= prev else total   # decrease ⇒ treat as reset
    prev = total
```

Per file, in file order. Never carry `prev` across files — each session
counts from zero.

**2. The fields nest. `cached_input_tokens` is part of `input_tokens`, and
`reasoning_output_tokens` is part of `output_tokens`.**

Verified across 3,765 events: `input_tokens + output_tokens == total_tokens`
holds in 3,762 of them. So adding the four fields up double-counts cache reads
and reasoning tokens — and reasoning is heavy on Codex, so the error is large
and biased toward making an idle session look frantic.

```
fresh_input  = input_tokens - cached_input_tokens
cached_input = cached_input_tokens
output       = output_tokens          # reasoning already included
```

The 3 anomalous events had all four components zero with a non-zero total.
Skip any event whose components sum to zero rather than trying to rescue it.

---

### Architecture — where this goes

**Not a folder per tool.** A `claude/` and a `codex/` directory implies each
tool gets its own copy of the machinery, which is how you end up maintaining two
cats. Everything except log parsing is tool-agnostic: the weighting, the
bucketing, the percentile comparison, the mood ladder, every animation.

**Not a CLI setup question either.** "Which tool do you use?" is a question the
machine can answer by looking at the disk, and asking it gets the wrong answer
for anyone who uses both or who switches later. Detect; let the CLI *override*.

The seam already exists in `usage.py`. The app talks to a "usage source" — an
object with `get() -> Usage`. It has two today (`StubUsageSource`,
`ClaudeCodeUsageSource`) and the rest of the app cannot tell them apart. What is
missing is one layer lower: the split between *reading a log format* and
*scoring what was read*.

```
ClaudeCodeReader ─┐
                  ├─→ [ shared: weight → bucket → percentile → Mood ] → Usage → cat
CodexReader      ─┘
```

#### The refactor

Small, and it is most of the work. In `usage.py`:

1. **Extract a reader.** A reader has one job:
   ```python
   def events_since(self, horizon: datetime) -> List[TokenEvent]: ...
   ```
   Move `ClaudeCodeUsageSource._collect_events_since` and `_parse_jsonl` into a
   `ClaudeCodeReader` unchanged. No behaviour change.

2. **Make the scoring take readers.** `ClaudeCodeUsageSource` keeps
   `_compute`, `_classify_mood`, and the module-level `_bucketize` /
   `_percentile_rank` exactly as they are, but sources its events from a list of
   readers instead of a hardcoded directory. Rename it `LogUsageSource`.

3. **Keep `ClaudeCodeUsageSource` as an alias** for `LogUsageSource([ClaudeCodeReader()])`.
   `cli._status` imports it by name, and there is no reason to break that.

4. **Add `CodexReader`**, per the parsing rules above.

5. **Teach `make_default_usage_source()` to detect.** Include a reader for each
   tool whose directory exists; combine them into one `LogUsageSource`.

Combining is genuinely just concatenating the two event lists before bucketing.
No per-source weighting, no normalisation, no reconciliation.

#### Why combining is safe

Worth stating because it is the reason this feature is cheap. Meowsage never
compares against an absolute number — it compares your last 60 seconds against
your own last hour. So Codex and Claude Code do **not** need to count tokens
comparably. As long as each is internally consistent over time, the ratio holds
and the ladder still spans its full range. The self-normalising design chosen to
avoid depending on plan limits is what makes multi-tool support nearly free.

The one thing that does need care is the weight table, below.

---

### Weighting

`_TOKEN_WEIGHTS` in `usage.py` exists because tokens are not equal — output is
the best proxy for real work, cache reads are cheap and enormous. Codex's
categories map onto it like this, **after** un-nesting per finding 2:

| Codex field | Maps to | Weight | Note |
|---|---|---|---|
| `input_tokens - cached_input_tokens` | `input` | 1.0 | fresh input only |
| `cached_input_tokens` | `cache_read` | 0.1 | |
| `output_tokens` | `output` | 5.0 | reasoning already inside this |
| — | `cache_creation` | 1.25 | no Codex equivalent; contributes 0 |

Start here and leave it. The percentile machinery is comparing you to yourself,
so a weighting that is merely *consistent* produces a sensible cat even if it is
not perfectly calibrated against Claude Code's. Tune only if real use shows the
cat behaving differently depending on which tool is driving.

An open question worth a look during implementation: whether
`reasoning_output_tokens` deserves separating out and weighting *above* ordinary
output. Reasoning is the most "the model is working hard" signal available, and
Claude Code has no equivalent. Not worth blocking on.

---

### CLI surface

Two small additions, in keeping with the CLI work already done:

**`meow status` gains a `sources` row**, so it is visible which logs are being
read and whether detection did the right thing:

```
  cat          Sprite
  status       out and about (pid 4471)
  sources      Claude Code, Codex
  mood         relaxed — busier than 44% of your last 9 active minutes
```

Show a tool only when its directory exists. When neither does, say so plainly —
that is the "cat sleeps forever and the user has no idea why" case, and it
should be diagnosable from `meow status` alone.

**An override**, for when detection is wrong or someone wants one tool only.
Follow the existing `MEOWSAGE_STUB` precedent rather than inventing a config
file:

```bash
MEOWSAGE_SOURCES=codex meow          # Codex only
MEOWSAGE_SOURCES=claude,codex meow   # both, explicitly
```

Unrecognised names should warn and be ignored, not crash.

---

### Fallback — what if current Codex records no tokens?

If Step 0 shows the current Codex writes no usage anywhere, the feature does not
die — it gets a cruder signal, and the architecture above is unchanged.

The scoring path does not actually care that the numbers are *tokens*. It cares
that events have timestamps and a weight. So a `CodexReader` can emit one
`TokenEvent` per assistant turn with a fixed nominal weight, derived from
records that definitely do exist in the rollout files:

- `event_msg` / `task_started` and `task_complete`
- `response_item` / `message`

That gives "turns per minute" instead of "tokens per minute". It is a worse
proxy — it cannot tell a one-line reply from a twenty-file refactor — but
percentile-ranked against the user's own baseline it still moves the cat up and
down the ladder correctly, which is the whole job.

**Do not mix the two in one baseline.** If Claude Code contributes real weighted
tokens and Codex contributes flat per-turn weights, whichever has the larger
numbers dominates the combined signal and the other tool effectively stops
moving the cat. If it comes to this, either scale Codex's nominal weight to
roughly match the user's observed median token weight per Claude Code turn, or
keep the two baselines separate and take the higher resulting mood. Decide when
you know whether it is needed; do not build it speculatively.

---

### Acceptance criteria

- [x] Step 0 verified and its answer recorded in this document.
- [x] A Codex-only user gets a cat that moves across the full ladder (via
      turn-counting on the current Codex; via real tokens on older versions).
- [x] A Claude-Code-only user sees **no behaviour change whatsoever**. This is
      the main regression risk of the refactor.
- [x] A both-tools user gets one cat, and working hard in either tool alone is
      enough to wake it up — via the separate-baselines/higher-mood strategy,
      not the merged-timeline one originally specced.
- [ ] `meow status` names the active sources and stays under ~100ms. It must not
      import Qt — that property is load-bearing and easy to lose by adding an
      import at the top of the wrong module. **Not built — no `meow status`
      command exists yet.**
- [x] Missing `~/.codex` or `~/.claude` is a normal condition, never an error.
- [x] A malformed or half-written rollout line is skipped, not fatal. Codex is
      appending to these files while the cat reads them.

#### How to verify without waiting for real usage

There is no test suite; the house method is driving the real thing headlessly.
For this feature specifically, the reader is pure file parsing and needs no
display at all:

```python
CodexReader(sessions_dir=Path("test_fixtures/")).events_since(horizon)
```

Point it at a directory of hand-written rollout files and assert the events.
Copy a couple of real sessions out of `~/.codex/sessions/` as fixtures, and
include one with the duplicated `token_count` event that produced the 8%
overcount — that is the regression most likely to come back.

---

### Open questions

- **Does the current Codex log tokens at all?** Step 0. Everything else is
  downstream of this. **Resolved: no, as of 0.147.0.**
- **Sub-agent threads.** Codex spawns sub-agent threads that write their own
  rollout files with their own token counts (visible in `threads.source` as
  `{"subagent": ...}`). Counting them is probably right — the work is real and
  the user is waiting on it — but it means a single Codex turn can produce
  several files' worth of tokens at once, which will spike the foreground
  window. Worth watching for a cat that gets the zoomies unreasonably often.
  **Still open** — not specifically handled or excluded by the shipped code.
- **File scanning cost.** `ClaudeCodeUsageSource` skips files by mtime before
  opening them. Codex's dated directory layout allows something better: only
  descend into today's and yesterday's directories. Worth doing — this runs
  every 15 seconds, forever. **Shipped**, generalised to descend into every
  dated directory the baseline window can reach rather than hardcoding "today
  and yesterday".
- **Timestamp format.** Codex writes `...Z`; the existing `_parse_jsonl` already
  handles that via `.replace("Z", "+00:00")`. Reuse it rather than rewriting it.
  **Shipped as specced.**

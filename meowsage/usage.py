"""Sources of activity data.

- `StubUsageSource` — dev helper, dial the activity level up and down by hand.
- `LogUsageSource` — reads one or more coding-tool session logs and derives
  the cat's mood from your *recent* activity in them. Not tied to any plan
  limit: high activity = happy cat, idle = sleepy cat. See mood computation
  in `_classify_mood` below.

`LogUsageSource` is a scorer over readers, one per tool:

- `ClaudeCodeReader` — parses `~/.claude/projects/*/*.jsonl`.
- `CodexReader` — parses `~/.codex/sessions/YYYY/MM/DD/*.jsonl`.

Each reader is scored against its *own* recent baseline independently, then
`LogUsageSource` takes whichever mood currently reads as more active. This is
safe specifically because the mood ladder compares you against your own
recent history rather than an absolute token count — two tools never need to
weight tokens comparably, so nothing is lost by not merging their events into
one timeline. Working hard in *either* tool is enough to wake the cat.

`ClaudeCodeUsageSource` is kept as a thin single-reader alias for anyone
importing it directly.

Pick a source via `make_default_usage_source()`, which honours the
`MEOWSAGE_STUB` and `MEOWSAGE_SOURCES` env vars so it's easy to demo or
override without touching real data. See docs/codex-support.md for the design
rationale, including why Codex needs a fallback (turns/minute rather than
tokens/minute): the current Codex release logs no token usage at all.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import DEFAULT_CONFIG, PetConfig
from .moods import Mood, mood_for_activity, mood_rank

# Weights per Claude Code token bucket. See config.py notes; kept as a proxy
# for how hard Claude is actually working (cache reads are cheap, output is
# dear).
_CLAUDE_WEIGHTS = {
    "input": 1.0,
    "cache_creation": 1.25,
    "cache_read": 0.1,
    "output": 5.0,
}

# The raw JSON field names _CLAUDE_WEIGHTS above maps from. If Anthropic
# ever renames one of these in Claude Code's log format, `usage.get(key, 0)`
# below would quietly default every occurrence to 0 forever — the exact
# same "silently stops counting, nothing tells you" failure shape as the
# fast-path bug this file's tests caught, just one layer deeper (field
# names instead of line formatting). See _parse_claude_jsonl.
_CLAUDE_USAGE_KEYS = {
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
}

# Weights for Codex's real per-category token usage, on the rare Codex
# version that still logs it (see CodexReader). Same shape as
# `_CLAUDE_WEIGHTS`, minus a cache-creation equivalent Codex doesn't have.
_CODEX_TOKEN_WEIGHTS = {
    "input": 1.0,
    "cache_read": 0.1,
    "output": 5.0,
}

# Nominal per-turn weight for Codex's token-less fallback (see CodexReader).
# Its absolute value is arbitrary: this reader is scored against its own
# baseline independently, and only the resulting *mood* — not the raw
# magnitude — is compared against other sources, so any positive constant
# produces identical behaviour.
_CODEX_TURN_WEIGHT = 1.0


@dataclass
class Usage:
    """Snapshot of the pet's current activity signal."""

    mood: Mood
    activity_level: float          # 0.0 (idle) → 1.0 (very active), for display
    foreground_tokens: int = 0     # weighted tokens in the recent foreground window
    baseline_active_minutes: int = 0
    percentile_of_baseline: float = 0.0


# ---------------------------------------------------------------------------
# Stub source (dev)
# ---------------------------------------------------------------------------


class StubUsageSource:
    """Manual activity source. Up/Down keys in the pet drive `bump()`.

    Semantics are inverted from earlier versions: higher = more active =
    happier cat. Start at 0.95 so the demo cat is energized.
    """

    def __init__(self, initial_activity: float = 0.95):
        self._activity = _clamp(initial_activity)

    def get(self) -> Usage:
        return Usage(
            mood=mood_for_activity(self._activity),
            activity_level=self._activity,
        )

    def set_activity(self, level: float) -> None:
        self._activity = _clamp(level)

    def bump(self, delta: float) -> None:
        self.set_activity(self._activity + delta)


# ---------------------------------------------------------------------------
# Real sources: reads coding-tool session logs
# ---------------------------------------------------------------------------


@dataclass
class _TokenEvent:
    timestamp: datetime
    weighted: float


# Representative activity_level per mood — only used to populate the
# `activity_level` field of Usage for display consistency with the stub.
_MOOD_TO_ACTIVITY = {
    Mood.SLEEPY: 0.05,
    Mood.LOAFING: 0.20,
    Mood.TIRED: 0.36,
    Mood.RELAXED: 0.52,
    Mood.CONTENT: 0.72,
    Mood.TRUSTING: 0.81,
    Mood.HAPPY: 0.90,
    Mood.PLAYFUL: 0.98,
}


class ClaudeCodeReader:
    """Reads `~/.claude/projects/*/*.jsonl` for weighted token events."""

    def __init__(self, projects_dir: Optional[Path] = None):
        self._projects_dir = projects_dir or (Path.home() / ".claude" / "projects")

    def exists(self) -> bool:
        return self._projects_dir.exists()

    def events_since(self, horizon: datetime) -> List[_TokenEvent]:
        if not self._projects_dir.exists():
            return []
        cutoff_epoch = horizon.timestamp()
        events: List[_TokenEvent] = []
        for project_dir in self._projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl in project_dir.glob("*.jsonl"):
                try:
                    if jsonl.stat().st_mtime < cutoff_epoch:
                        continue
                except OSError:
                    continue
                events.extend(_parse_claude_jsonl(jsonl, horizon))
        events.sort(key=lambda e: e.timestamp)
        return events


class CodexReader:
    """Reads `~/.codex/sessions/YYYY/MM/DD/*.jsonl` for weighted activity.

    Prefers real per-category token usage when a session logs it (older
    Codex versions did). Falls back to a flat per-turn weight when it
    doesn't — the current version (0.147.0, as of Aug 2026) logs no usage at
    all, confirmed against both the rollout files and `state_*.sqlite`'s
    `threads.tokens_used`. See docs/codex-support.md Step 0.
    """

    def __init__(self, sessions_dir: Optional[Path] = None):
        self._sessions_dir = sessions_dir or (Path.home() / ".codex" / "sessions")

    def exists(self) -> bool:
        return self._sessions_dir.exists()

    def events_since(self, horizon: datetime) -> List[_TokenEvent]:
        if not self._sessions_dir.exists():
            return []
        events: List[_TokenEvent] = []
        for jsonl in self._iter_recent_files(horizon):
            events.extend(_parse_codex_jsonl(jsonl, horizon))
        events.sort(key=lambda e: e.timestamp)
        return events

    def _iter_recent_files(self, horizon: datetime) -> List[Path]:
        # Codex's dated directory layout lets us skip everything but the
        # days the baseline window can actually reach, rather than walking
        # the whole session history on every ~15s refresh.
        files: List[Path] = []
        day = horizon.date()
        last = datetime.now(timezone.utc).date()
        while day <= last:
            day_dir = self._sessions_dir / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
            if day_dir.is_dir():
                files.extend(day_dir.glob("*.jsonl"))
            day += timedelta(days=1)
        return files


class LogUsageSource:
    """Derive mood from tokens/minute (or turns/minute) vs your own recent
    baseline, across one or more readers.

    Each reader is scored independently against its own history; the mood
    reported is whichever reader currently reads as more active. No-ops for
    `set_activity`/`bump` so PetWindow's dev shortcuts don't crash — real
    activity can't be faked by pressing a key, it comes from session logs.
    """

    def __init__(self, readers: Iterable, config: Optional[PetConfig] = None):
        self._readers = list(readers)
        self.config = config or DEFAULT_CONFIG
        self._cached: Optional[Usage] = None
        self._cached_at: float = 0.0

    def set_activity(self, level: float) -> None:
        pass

    def bump(self, delta: float) -> None:
        pass

    def get(self) -> Usage:
        now = time.monotonic()
        if self._cached is not None and (
            now - self._cached_at
        ) < self.config.refresh_interval_seconds:
            return self._cached
        usage = self._compute()
        self._cached = usage
        self._cached_at = now
        return usage

    @property
    def readers(self) -> tuple:
        """The readers this source scores, for callers like `meow status`
        that want to say which tools' logs are actually being read."""
        return tuple(self._readers)

    # --- computation --------------------------------------------------------

    def _compute(self) -> Usage:
        cfg = self.config
        now = datetime.now(timezone.utc)
        horizon = now - timedelta(minutes=cfg.baseline_window_minutes + 1)

        best: Optional[Usage] = None
        best_rank = mood_rank(Mood.SLEEPY) + 1
        for reader in self._readers:
            usage = _score(reader.events_since(horizon), now, cfg)
            rank = mood_rank(usage.mood)
            if rank < best_rank:
                best = usage
                best_rank = rank

        return best if best is not None else _score([], now, cfg)


class ClaudeCodeUsageSource(LogUsageSource):
    """Claude-Code-only usage source. Kept for anyone importing it by name."""

    def __init__(
        self,
        config: Optional[PetConfig] = None,
        projects_dir: Optional[Path] = None,
    ):
        super().__init__([ClaudeCodeReader(projects_dir)], config)


# ---------------------------------------------------------------------------
# Scoring — shared by every reader
# ---------------------------------------------------------------------------


def _score(events: List[_TokenEvent], now: datetime, cfg: PetConfig) -> Usage:
    # Foreground: weighted tokens in the last `foreground_window_seconds`.
    fg_start = now - timedelta(seconds=cfg.foreground_window_seconds)
    foreground_tokens = int(sum(e.weighted for e in events if e.timestamp >= fg_start))

    # Baseline: bucket the last baseline_window_minutes into per-bucket
    # totals of the same size as the foreground window, so foreground and
    # baseline samples are directly comparable.
    buckets = _bucketize(events, now, cfg)
    active_buckets = [b for b in buckets if b > 0]

    mood = _classify_mood(foreground_tokens, active_buckets, cfg)
    pct = _percentile_rank(foreground_tokens, active_buckets)

    return Usage(
        mood=mood,
        activity_level=_MOOD_TO_ACTIVITY[mood],
        foreground_tokens=foreground_tokens,
        baseline_active_minutes=len(active_buckets),
        percentile_of_baseline=pct,
    )


def _classify_mood(
    foreground: float,
    active_buckets: List[float],
    cfg: PetConfig,
) -> Mood:
    # 1) Truly idle right now → SLEEPY. Overrides everything else.
    if foreground <= 0:
        return Mood.SLEEPY
    # 2) Not enough baseline yet (fresh session / long idle) → HAPPY.
    #    Any current activity in a mostly-quiet history should feel like
    #    the cat perking up.
    if len(active_buckets) < cfg.cold_start_min_active_minutes:
        return Mood.HAPPY
    # 3) Percentile against your own recent active minutes.
    pct = _percentile_rank(foreground, active_buckets)
    if pct >= cfg.percentile_playful:
        return Mood.PLAYFUL
    if pct >= cfg.percentile_happy:
        return Mood.HAPPY
    if pct >= cfg.percentile_trusting:
        return Mood.TRUSTING
    if pct >= cfg.percentile_content:
        return Mood.CONTENT
    if pct >= cfg.percentile_relaxed:
        return Mood.RELAXED
    if pct >= cfg.percentile_tired:
        return Mood.TIRED
    return Mood.LOAFING


# ---------------------------------------------------------------------------
# Parsing — one function per log format
# ---------------------------------------------------------------------------


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _parse_claude_jsonl(path: Path, cutoff: datetime) -> List[_TokenEvent]:
    """Extract weighted assistant token events newer than `cutoff` from one
    Claude Code session file."""
    events: List[_TokenEvent] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # Cheap pre-filter before the expensive json.loads below:
                # skip lines that can't possibly be an assistant message.
                # Checks only the quoted *value* ("assistant"), not the key
                # spacing around it, so it holds regardless of whether
                # Claude Code writes compact or spaced JSON — a spacing
                # change is exactly what broke the old, stricter version of
                # this check (caught by this module's tests).
                if '"assistant"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                if obj.get("type") != "assistant":
                    continue
                ts_str = obj.get("timestamp")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not usage:
                    continue
                if not (_CLAUDE_USAGE_KEYS & usage.keys()):
                    # `usage` exists but none of the token fields we know
                    # how to weight are present — every event from here on
                    # would silently score as 0 rather than actually being
                    # wrong, which just reads as "the cat went idle and
                    # never woke up again." Fail loudly instead: this means
                    # Claude Code's usage schema changed and _CLAUDE_WEIGHTS
                    # needs updating.
                    raise ValueError(
                        f"meowsage: {path} has an assistant message with a "
                        f"'usage' object but none of the expected token "
                        f"fields ({sorted(_CLAUDE_USAGE_KEYS)}); found "
                        f"{sorted(usage.keys())} instead. Claude Code's "
                        f"usage format may have changed."
                    )
                weighted = (
                    int(usage.get("input_tokens", 0) or 0) * _CLAUDE_WEIGHTS["input"]
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                    * _CLAUDE_WEIGHTS["cache_creation"]
                    + int(usage.get("cache_read_input_tokens", 0) or 0)
                    * _CLAUDE_WEIGHTS["cache_read"]
                    + int(usage.get("output_tokens", 0) or 0) * _CLAUDE_WEIGHTS["output"]
                )
                events.append(_TokenEvent(timestamp=ts, weighted=weighted))
    except OSError:
        pass
    return events


def _parse_codex_jsonl(path: Path, cutoff: datetime) -> List[_TokenEvent]:
    """Extract weighted activity events newer than `cutoff` from one Codex
    rollout file.

    Two things learned by measurement, not guessing (docs/codex-support.md):
    within a session, `total_token_usage` is cumulative, so diffing
    consecutive values is required — summing `last_token_usage` directly
    overcounts by ~8% on real sessions because Codex sometimes emits the
    same `token_count` event twice. And `cached_input_tokens` /
    `reasoning_output_tokens` nest *inside* `input_tokens` / `output_tokens`
    rather than sitting alongside them, so naively adding every field
    double-counts.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []

    has_tokens = any('"token_count"' in line for line in lines)
    events: List[_TokenEvent] = []
    prev: Dict[str, int] = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
    }

    for line in lines:
        try:
            obj = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload") or {}
        ts_str = obj.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if has_tokens:
            if payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            # `info` is sometimes null — a rate-limit-only ping with no token
            # totals attached. Skip it without touching `prev`: treating its
            # absence as a real zero reading would reset the running totals
            # and make the next real event look like a fresh session's worth
            # of tokens.
            if not info or not info.get("total_token_usage"):
                continue
            usage = info["total_token_usage"]
            cur = {
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
            }
            deltas = {}
            for key, value in cur.items():
                d = value - prev[key]
                # A decrease means a new session's counter, not a real drop.
                deltas[key] = d if d >= 0 else value
            prev = cur
            if ts < cutoff:
                continue
            fresh_input = max(0, deltas["input_tokens"] - deltas["cached_input_tokens"])
            weighted = (
                fresh_input * _CODEX_TOKEN_WEIGHTS["input"]
                + deltas["cached_input_tokens"] * _CODEX_TOKEN_WEIGHTS["cache_read"]
                + deltas["output_tokens"] * _CODEX_TOKEN_WEIGHTS["output"]
            )
            if weighted <= 0:
                continue
            events.append(_TokenEvent(timestamp=ts, weighted=weighted))
        else:
            if payload.get("type") != "agent_message" or ts < cutoff:
                continue
            events.append(_TokenEvent(timestamp=ts, weighted=_CODEX_TURN_WEIGHT))

    return events


def _bucketize(
    events: List[_TokenEvent], end: datetime, cfg: PetConfig
) -> List[float]:
    """Bucket events into fixed-width slots ending at `end`.

    Each bucket is `foreground_window_seconds` wide, and we cover
    `baseline_window_minutes` back from `end`. Result: baseline distribution
    made of samples the same size as the foreground metric.
    """
    bucket_seconds = cfg.foreground_window_seconds
    total_seconds = cfg.baseline_window_minutes * 60
    n = total_seconds // bucket_seconds
    buckets = [0.0] * n
    start = end - timedelta(seconds=total_seconds)
    for e in events:
        if e.timestamp < start or e.timestamp >= end:
            continue
        offset = (e.timestamp - start).total_seconds()
        idx = int(offset // bucket_seconds)
        if 0 <= idx < n:
            buckets[idx] += e.weighted
    return buckets


def _percentile_rank(value: float, samples: List[float]) -> float:
    """Return 0-100 percentile of `value` within `samples`.

    Uses the "mean" convention: (below + 0.5*equal) / n * 100. Handles ties
    gracefully so bursty distributions don't misclassify.
    """
    if not samples:
        return 50.0
    below = sum(1 for s in samples if s < value)
    equal = sum(1 for s in samples if s == value)
    return 100.0 * (below + 0.5 * equal) / len(samples)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_AVAILABLE_READERS = {
    "claude": ClaudeCodeReader,
    "codex": CodexReader,
}


def make_default_usage_source():
    """Return a usage source based on environment.

    - `MEOWSAGE_STUB=<0.0-1.0>` → StubUsageSource at that activity level.
    - `MEOWSAGE_SOURCES=claude,codex` → LogUsageSource with exactly those
      readers, regardless of whether their log directories exist yet.
      Unrecognised names are warned about and ignored, not fatal.
    - Otherwise, LogUsageSource auto-detects: one reader per tool whose log
      directory exists. Missing `~/.claude/projects` or `~/.codex/sessions`
      is a normal condition, not an error — a brand-new install, or someone
      who only has one of the two tools.
    """
    stub_val = os.environ.get("MEOWSAGE_STUB")
    if stub_val is not None:
        try:
            level = float(stub_val)
        except ValueError:
            level = 0.95
        return StubUsageSource(initial_activity=level)

    override = os.environ.get("MEOWSAGE_SOURCES")
    if override is not None:
        readers = []
        for name in (n.strip().lower() for n in override.split(",")):
            if not name:
                continue
            reader_cls = _AVAILABLE_READERS.get(name)
            if reader_cls is None:
                print(f"meowsage: unknown source '{name}' in MEOWSAGE_SOURCES, ignoring")
                continue
            readers.append(reader_cls())
        return LogUsageSource(readers)

    readers = [cls() for cls in _AVAILABLE_READERS.values()]
    return LogUsageSource([r for r in readers if r.exists()])

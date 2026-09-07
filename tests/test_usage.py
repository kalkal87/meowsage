"""Tests for meowsage/usage.py — the scoring logic behind "grades you
against yourself" (see README).

Three things get exercised here, each pure/data-in-data-out so none of it
needs a real Claude Code or Codex install on disk:

1. _percentile_rank  — where does one value sit inside a list of samples?
2. _classify_mood    — turn a percentile (plus edge cases like "idle" and
                        "not enough history yet") into a Mood.
3. _parse_claude_jsonl — turn one line of a real Claude Code log file into
                          a weighted number, using the token-type weights
                          from the README's table.

Private (underscore-prefixed) functions are imported directly. That's a
deliberate choice for this module: they're the actual decision logic, and
testing them directly gives a precise failure message ("percentile math is
wrong") instead of a vague one ("mood was wrong, could be anything").
"""

from datetime import datetime, timedelta, timezone

import pytest

from meowsage.config import DEFAULT_CONFIG
from meowsage.moods import Mood
from meowsage.usage import (
    LogUsageSource,
    StubUsageSource,
    _bucketize,
    _classify_mood,
    _parse_claude_jsonl,
    _percentile_rank,
    _TokenEvent,
    _CLAUDE_WEIGHTS,
)


# ---------------------------------------------------------------------------
# _percentile_rank
# ---------------------------------------------------------------------------


def test_percentile_rank_worked_example():
    # samples = [1, 2, 3, 4]; value = 1 is the smallest, tied with itself,
    # nothing below it: pct = 100 * (0 below + 0.5 * 1 equal) / 4 = 12.5
    assert _percentile_rank(1, [1, 2, 3, 4]) == 12.5
    # value = 4 is the largest: 3 below it, 1 equal to it:
    # pct = 100 * (3 + 0.5) / 4 = 87.5
    assert _percentile_rank(4, [1, 2, 3, 4]) == 87.5


def test_percentile_rank_handles_ties():
    # Every sample equals the value being ranked: nothing is strictly below,
    # everything is tied, so it should land dead center (50th percentile) —
    # this is the "mean" convention the docstring promises.
    assert _percentile_rank(5, [5, 5, 5, 5]) == 50.0


def test_percentile_rank_with_no_samples_defaults_to_middle():
    # No baseline history yet (e.g. very first minute of a new install).
    # Defaulting to 50 (median) rather than crashing or returning 0/100
    # avoids an artificial mood swing before there's any real signal.
    assert _percentile_rank(10, []) == 50.0


# ---------------------------------------------------------------------------
# _classify_mood: the edge cases first (these are "if" branches at the top
# of the function, so they're the ones most likely to get short-circuited
# wrong by a future edit), then the percentile ladder itself.
# ---------------------------------------------------------------------------


def test_classify_mood_zero_foreground_is_always_sleepy():
    # Even with a baseline suggesting the user is usually very active,
    # zero activity *right now* overrides everything else.
    assert _classify_mood(0, [100.0] * 20, DEFAULT_CONFIG) == Mood.SLEEPY


def test_classify_mood_cold_start_is_happy():
    # Fewer active buckets than cfg.cold_start_min_active_minutes (5) means
    # there isn't enough history to compute a meaningful percentile yet —
    # e.g. a session that only just started. Current behavior treats that
    # as HAPPY, so a freshly-opened pet perks up rather than sleeping
    # through its own first few active minutes.
    few_buckets = [1.0, 2.0, 3.0]  # only 3, below the cold-start floor of 5
    assert _classify_mood(1, few_buckets, DEFAULT_CONFIG) == Mood.HAPPY


@pytest.mark.parametrize(
    "foreground, expected_mood",
    [
        (25, Mood.LOAFING),    # pct 24.5 — just under the 25 (tired) cutoff
        (26, Mood.TIRED),      # pct 25.5 — just over it
        (38, Mood.TIRED),      # pct 37.5 — just under the 38 (relaxed) cutoff
        (39, Mood.RELAXED),    # pct 38.5 — just over it
        (50, Mood.RELAXED),    # pct 49.5 — just under the 50 (content) cutoff
        (51, Mood.CONTENT),    # pct 50.5 — just over it
        (65, Mood.CONTENT),    # pct 64.5 — just under the 65 (trusting) cutoff
        (66, Mood.TRUSTING),   # pct 65.5 — just over it
        (75, Mood.TRUSTING),   # pct 74.5 — just under the 75 (happy) cutoff
        (76, Mood.HAPPY),      # pct 75.5 — just over it
        (90, Mood.HAPPY),      # pct 89.5 — just under the 90 (playful) cutoff
        (91, Mood.PLAYFUL),    # pct 90.5 — just over it
    ],
)
def test_classify_mood_matches_configured_percentile_cutoffs(foreground, expected_mood):
    # 100 evenly-spaced baseline samples (1..100) makes the percentile of
    # any one of them land at (value - 0.5), which is exactly cfg's cutoff
    # values one point off in each direction — a clean way to test every
    # boundary in config.py against the real DEFAULT_CONFIG thresholds,
    # rather than hand-picked numbers that might drift from config.py.
    samples = [float(v) for v in range(1, 101)]
    assert _classify_mood(foreground, samples, DEFAULT_CONFIG) == expected_mood


# ---------------------------------------------------------------------------
# _bucketize: turns a raw event list into fixed-width time buckets. This is
# what feeds _percentile_rank's "samples" argument in real use, so an
# off-by-one here silently corrupts every mood decision.
# ---------------------------------------------------------------------------


def test_bucketize_puts_events_in_the_right_bucket_and_sums_them():
    end = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    start = end - timedelta(minutes=DEFAULT_CONFIG.baseline_window_minutes)
    events = [
        _TokenEvent(timestamp=start, weighted=10.0),                    # bucket 0
        _TokenEvent(timestamp=start + timedelta(seconds=5), weighted=5.0),  # bucket 0 too
        _TokenEvent(timestamp=end - timedelta(seconds=1), weighted=7.0),    # last bucket
    ]
    buckets = _bucketize(events, end, DEFAULT_CONFIG)

    assert len(buckets) == 60  # 60 min / 60s buckets = 60
    assert buckets[0] == 15.0  # the two events at the start summed together
    assert buckets[-1] == 7.0


def test_bucketize_excludes_events_outside_the_window():
    end = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _TokenEvent(timestamp=end - timedelta(minutes=61), weighted=99.0),  # too old
        _TokenEvent(timestamp=end, weighted=99.0),  # not "< end", excluded
    ]
    buckets = _bucketize(events, end, DEFAULT_CONFIG)
    assert sum(buckets) == 0.0


# ---------------------------------------------------------------------------
# _parse_claude_jsonl: the token-weighting table from the README, applied to
# something that looks like a real ~/.claude/projects/*/*.jsonl line.
# ---------------------------------------------------------------------------


def test_claude_jsonl_weights_tokens_by_type(tmp_path):
    log = tmp_path / "session.jsonl"
    now = datetime.now(timezone.utc)
    raw_usage = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 40,
        "cache_read_input_tokens": 1000,  # deliberately huge and cheap
        "output_tokens": 20,              # deliberately small and dear
    }
    line = {
        "type": "assistant",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "message": {"usage": raw_usage},
    }
    log.write_text(json_line(line))

    cutoff = now - timedelta(minutes=1)
    events = _parse_claude_jsonl(log, cutoff)

    assert len(events) == 1
    expected = (
        raw_usage["input_tokens"] * _CLAUDE_WEIGHTS["input"]
        + raw_usage["cache_creation_input_tokens"] * _CLAUDE_WEIGHTS["cache_creation"]
        + raw_usage["cache_read_input_tokens"] * _CLAUDE_WEIGHTS["cache_read"]
        + raw_usage["output_tokens"] * _CLAUDE_WEIGHTS["output"]
    )
    assert events[0].weighted == expected

    # Sanity check on *why* the weighting exists at all. Unweighted, the
    # 1000 cache-read tokens would utterly swamp the 20 output tokens
    # (1000 vs 20 — 98% of the "activity" would be one cheap cache hit).
    # Weighted, output's *share* of the total should be far bigger than its
    # share of the raw count, because it's the thing the weighting exists
    # to foreground.
    raw_total = sum(raw_usage.values())
    raw_output_share = raw_usage["output_tokens"] / raw_total
    weighted_output_share = (
        raw_usage["output_tokens"] * _CLAUDE_WEIGHTS["output"]
    ) / expected
    assert weighted_output_share > raw_output_share


def test_claude_jsonl_skips_events_before_cutoff(tmp_path):
    log = tmp_path / "session.jsonl"
    old_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    line = {
        "type": "assistant",
        "timestamp": old_ts.isoformat().replace("+00:00", "Z"),
        "message": {"usage": {"output_tokens": 500}},
    }
    log.write_text(json_line(line))

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert _parse_claude_jsonl(log, cutoff) == []


def test_claude_jsonl_ignores_non_assistant_lines(tmp_path):
    log = tmp_path / "session.jsonl"
    line = {
        "type": "user",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": {"usage": {"output_tokens": 500}},
    }
    log.write_text(json_line(line))

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert _parse_claude_jsonl(log, cutoff) == []


def test_claude_jsonl_tolerates_default_json_spacing(tmp_path):
    # Regression test for the exact bug the tests above found: an earlier
    # version of _parse_claude_jsonl's fast pre-filter checked for the
    # literal substring '"type":"assistant"' with no space after the colon
    # — which matches real Claude Code log lines (written compact) but not
    # plain json.dumps() output (which inserts a space). That made the
    # parser silently return zero events for anything not in the exact
    # compact format. The pre-filter now only checks for the quoted value
    # '"assistant"', which holds regardless of spacing — this test writes
    # with Python's *default*, spaced json.dumps() (deliberately not using
    # the json_line() helper below) to prove that.
    import json

    log = tmp_path / "session.jsonl"
    now = datetime.now(timezone.utc)
    line = {
        "type": "assistant",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "message": {"usage": {"output_tokens": 20}},
    }
    log.write_text(json.dumps(line) + "\n")  # default spacing, e.g. "type": "assistant"

    events = _parse_claude_jsonl(log, now - timedelta(minutes=1))
    assert len(events) == 1
    assert events[0].weighted == 20 * _CLAUDE_WEIGHTS["output"]


def test_claude_jsonl_raises_on_unrecognized_usage_shape(tmp_path):
    # If Claude Code ever renamed a token field (e.g. output_tokens ->
    # output_token_count), `usage.get("output_tokens", 0)` would silently
    # default to 0 forever instead of erroring — the cat would just look
    # permanently idle, with nothing pointing at why. This is the "proper
    # error propagation" fix: when none of the expected token fields are
    # present at all, fail loudly instead of quietly scoring everything as
    # zero activity.
    log = tmp_path / "session.jsonl"
    now = datetime.now(timezone.utc)
    line = {
        "type": "assistant",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        # None of these match any key in _CLAUDE_USAGE_KEYS.
        "message": {"usage": {"totally_new_field_name": 500}},
    }
    log.write_text(json_line(line))

    with pytest.raises(ValueError, match="usage format may have changed"):
        _parse_claude_jsonl(log, now - timedelta(minutes=1))


def json_line(obj) -> str:
    import json

    # Compact separators (no space after `:` or `,`), matching how real
    # Claude Code log lines are written — kept as the default shape for
    # these tests since it's what production data actually looks like.
    return json.dumps(obj, separators=(",", ":")) + "\n"


# ---------------------------------------------------------------------------
# StubUsageSource: the dev/demo source (Up/Down keys). Small, but it's the
# one piece of usage.py a contributor is likely to touch casually while
# adding a UI feature, so a cheap regression net is worth having.
# ---------------------------------------------------------------------------


def test_stub_usage_source_clamps_to_valid_range():
    source = StubUsageSource(initial_activity=0.5)
    source.bump(10.0)  # way past 1.0
    assert source.get().activity_level == 1.0

    source.bump(-10.0)  # way past 0.0
    assert source.get().activity_level == 0.0


def test_stub_usage_source_mood_tracks_activity():
    source = StubUsageSource(initial_activity=0.0)
    assert source.get().mood == Mood.SLEEPY
    source.set_activity(1.0)
    assert source.get().mood == Mood.PLAYFUL


# ---------------------------------------------------------------------------
# LogUsageSource: with two readers (Claude + Codex), the pet should react
# to whichever tool the user is *currently* busier in, not always prefer
# one. This is the multi-tool logic described in the usage.py module
# docstring ("takes whichever mood currently reads as more active").
# ---------------------------------------------------------------------------


class _FakeReader:
    """A stand-in for ClaudeCodeReader/CodexReader: anything with an
    events_since(horizon) method works, since LogUsageSource never checks
    the reader's type — only what it returns."""

    def __init__(self, events):
        self._events = events

    def events_since(self, horizon):
        return self._events


def test_log_usage_source_prefers_the_busier_reader():
    now = datetime.now(timezone.utc)
    busy_reader = _FakeReader([_TokenEvent(timestamp=now, weighted=50.0)])
    idle_reader = _FakeReader([])  # no events at all -> SLEEPY

    source = LogUsageSource([idle_reader, busy_reader])
    usage = source.get()

    # idle_reader alone would report SLEEPY; busy_reader (cold-start, since
    # it only has one active bucket) reports HAPPY. The combined source
    # should surface the more active of the two, not the first in the list.
    assert usage.mood == Mood.HAPPY


def test_log_usage_source_with_no_readers_is_sleepy():
    source = LogUsageSource([])
    assert source.get().mood == Mood.SLEEPY

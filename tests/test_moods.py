"""Tests for meowsage/moods.py — the activity-to-mood mapping.

Nothing here touches Qt or the filesystem: mood_for_activity() and
mood_rank() are plain functions (float/enum in, enum/int out), so these
tests run in milliseconds and never need a real display.
"""

from meowsage.moods import Mood, MOOD_LINES, mood_for_activity, mood_rank


# ---------------------------------------------------------------------------
# mood_for_activity: does each activity level land on the mood the README
# and config.py promise?
# ---------------------------------------------------------------------------


def test_zero_activity_is_sleepy():
    assert mood_for_activity(0.0) == Mood.SLEEPY


def test_max_activity_is_playful():
    assert mood_for_activity(1.0) == Mood.PLAYFUL


def test_boundaries_are_inclusive_on_the_upper_side():
    # mood_for_activity() uses `<` cutoffs, so the cutoff value itself
    # belongs to the *next* (more active) mood, not the one below it.
    # These are exactly the values a copy-paste or off-by-one edit to the
    # cutoff table in moods.py would get wrong.
    assert mood_for_activity(0.11) == Mood.SLEEPY
    assert mood_for_activity(0.12) == Mood.LOAFING
    assert mood_for_activity(0.94) == Mood.HAPPY
    assert mood_for_activity(0.95) == Mood.PLAYFUL


def test_activity_out_of_range_does_not_crash():
    # Callers are expected to clamp to 0-1 (see usage._clamp), but the
    # function itself shouldn't blow up on a stray out-of-range value —
    # it should just fall off the end of the ladder sensibly.
    assert mood_for_activity(-1.0) == Mood.SLEEPY
    assert mood_for_activity(2.0) == Mood.PLAYFUL


# ---------------------------------------------------------------------------
# mood_rank: this is what usage.LogUsageSource uses to compare two tools'
# moods and pick the "more active" one, so the ladder order it returns has
# to exactly match Mood's declaration order.
# ---------------------------------------------------------------------------


def test_rank_matches_ladder_order():
    assert mood_rank(Mood.PLAYFUL) == 0
    assert mood_rank(Mood.SLEEPY) == 7


def test_rank_is_monotonic_along_the_ladder():
    # Every mood should rank strictly more "active" (lower number) than the
    # one below it — this is the property LogUsageSource actually relies on
    # when it does `if rank < best_rank`.
    ladder = [
        Mood.PLAYFUL,
        Mood.HAPPY,
        Mood.TRUSTING,
        Mood.CONTENT,
        Mood.RELAXED,
        Mood.TIRED,
        Mood.LOAFING,
        Mood.SLEEPY,
    ]
    ranks = [mood_rank(m) for m in ladder]
    assert ranks == sorted(ranks)


# ---------------------------------------------------------------------------
# Data completeness: every Mood needs flavor text, or the speech bubble
# KeyErrors the first time that mood is hit at runtime.
# ---------------------------------------------------------------------------


def test_every_mood_has_speech_lines():
    for mood in Mood:
        assert mood in MOOD_LINES, f"{mood} has no MOOD_LINES entry"
        assert len(MOOD_LINES[mood]) > 0

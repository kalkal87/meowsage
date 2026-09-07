"""Mood model: usage percent maps to a discrete mood the pet can express."""

from __future__ import annotations

from enum import Enum


class Mood(Enum):
    PLAYFUL = "playful"    # zoomies — a rare burst at the very top
    HAPPY = "happy"        # ample tokens left
    TRUSTING = "trusting"  # belly-up — comfortable enough to be vulnerable
    CONTENT = "content"    # comfortable
    RELAXED = "relaxed"    # lying down but alert — resting, not tired
    TIRED = "tired"        # getting low
    LOAFING = "loafing"    # settled and unbothered, barely ticking over
    SLEEPY = "sleepy"      # almost out


# Declaration order above is the ladder, best (most active) to worst.
_MOOD_ORDER: list[Mood] = list(Mood)


def mood_rank(mood: Mood) -> int:
    """Position on the ladder: 0 = PLAYFUL (most active) ... 7 = SLEEPY.

    Lets code compare two moods without duplicating the ladder order — used
    to pick the more-active of several usage sources' moods (see
    `LogUsageSource` in usage.py).
    """
    return _MOOD_ORDER.index(mood)


def mood_for_activity(activity_level: float) -> Mood:
    """Map a 0-1 recent-activity score to a mood.

    Semantics are inverted from the old `mood_for_usage`: higher activity
    means a more energized cat. Idle → sleepy; bursty → happy.

    Ordered low → high along the mood ladder; LOAFING carves its band out of
    what used to be the top of SLEEPY and the bottom of TIRED, RELAXED out of
    the top of TIRED and the bottom of CONTENT, and TRUSTING out of the top of
    CONTENT, just under HAPPY. PLAYFUL sits above everything, in a narrow slice
    at the very top, so the zoomies read as a rare event rather than a state.
    """
    if activity_level < 0.12:
        return Mood.SLEEPY
    if activity_level < 0.28:
        return Mood.LOAFING
    if activity_level < 0.45:
        return Mood.TIRED
    if activity_level < 0.60:
        return Mood.RELAXED
    if activity_level < 0.78:
        return Mood.CONTENT
    if activity_level < 0.85:
        return Mood.TRUSTING
    if activity_level < 0.95:
        return Mood.HAPPY
    return Mood.PLAYFUL


MOOD_LINES: dict[Mood, list[str]] = {
    Mood.PLAYFUL: [
        "ZOOMIES",
        "*sprints for no reason*",
        "gotta go fast",
        "can't stop won't stop",
        "the floor is lava (it's not, I just felt like running)",
    ],
    Mood.HAPPY: [
        "purr~",
        "meow!",
        "let's goooo",
        "so much energy!",
        "type type type",
    ],
    Mood.TRUSTING: [
        "belly's out, don't judge me",
        "*rolls over*",
        "I trust you, human",
        "vulnerable but vibing",
        "flop",
    ],
    Mood.CONTENT: [
        "nyaa~",
        "just chillin'",
        "*blep*",
        "hmm, what next?",
        "prrrp",
    ],
    Mood.RELAXED: [
        "just resting my eyes... sort of",
        "*settles in*",
        "watching the world go by",
        "comfy right here",
        "mmm, nice and calm",
    ],
    Mood.TIRED: [
        "yaawn...",
        "getting tired...",
        "maybe a nap?",
        "meow..?",
        "slow down, human",
    ],
    Mood.LOAFING: [
        "loaf mode activated",
        "*tucks paws*",
        "just a lil loaf",
        "nothing to see here",
        "compact and content",
    ],
    Mood.SLEEPY: [
        "zzz...",
        "*snores*",
        "so sleepy...",
        "just... five more mins",
        "tokens... gone...",
    ],
}

# Said when the pet locks onto a stationary cursor. Like PERK_LINES this is
# keyed to an event rather than a mood — hunting is an overlay on the ladder,
# not a rung of it, so it has no entry in MOOD_LINES.
HUNT_LINES: list[str] = [
    "...",
    "*eyes narrow*",
    "I see you",
    "stalking mode: engaged",
    "don't move",
]

# Said when the pet "perks up" reacting to activity resuming after a lull —
# independent of mood, since this is about noticing the burst, not the level.
PERK_LINES: list[str] = [
    "ooh!",
    "*ears perk up*",
    "oh, something's happening!",
    "back to work!",
    "there you are!",
]

"""Tunable pet parameters.

Everything the user might reasonably want to tweak lives here. Later this
will be surfaced via a right-click config menu; for now, edit values and
restart. Keep this file free of imports from the rest of the app so it can
be loaded standalone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PetConfig:
    # ---- how often we re-read Claude Code's session logs -----------------
    refresh_interval_seconds: int = 15

    # ---- rate-based mood engine ------------------------------------------
    # "Foreground" = the recent activity level we classify.
    # "Baseline"   = the personal distribution we compare it against.
    foreground_window_seconds: int = 60
    baseline_window_minutes: int = 60

    # Percentile cutoffs: where the foreground rate must land within the
    # baseline distribution (of active minutes) to hit each mood.
    # Deliberately steep: the zoomies should be a rare reward, not a state you
    # sit in, so it takes a minute busier than 9 in 10 of your recent ones.
    percentile_playful: float = 90.0
    percentile_happy: float = 75.0     # top quartile of your recent activity
    percentile_trusting: float = 65.0  # busy, but short of your top quartile
    percentile_content: float = 50.0   # above your recent median
    percentile_relaxed: float = 38.0   # a touch below your recent median
    percentile_tired: float = 25.0     # above your recent bottom quartile
    # Anything below `percentile_tired` (but > 0) is LOAFING. Zero = SLEEPY.

    # Cold-start: too few active minutes to compute a meaningful percentile.
    # usage._classify_mood defaults to HAPPY in this case, so a freshly-
    # opened pet reacting to activity reads as a perk-up, not a sleeper.
    cold_start_min_active_minutes: int = 5


DEFAULT_CONFIG = PetConfig()

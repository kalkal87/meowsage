"""Animation controller.

Owns all the pet's motion state: current pose, blink cycle, breathing bob,
walking, mood-transition one-shots. The `PetWindow` treats this as a black
box: it hooks up the `update_needed` and `move_to` signals, and reads
`current_render()` each paint.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor

from .artwork import Pose
from .moods import Mood


class Behavior(Enum):
    """What the cat is 'doing' right now (pose category, not raw sprite)."""

    IDLE_STANDING = "idle_standing"
    IDLE_SITTING = "idle_sitting"
    WALKING = "walking"
    SLEEPING = "sleeping"
    LOAFING = "loafing"
    RELAXED = "relaxed"
    # Two behaviors rather than one with a sub-phase, so that the roll (which
    # has no eyes-closed art) and the belly-up hold (which does) fall out of
    # _BLINK_POSES correctly without special-casing.
    TRUSTING_ROLL = "trusting_roll"
    TRUSTING_BACK = "trusting_back"
    ZOOMIES = "zoomies"


# Probability weights for random pose selection per mood.
#
# TRUSTING_BACK is 0 everywhere on purpose: the belly-up hold is only ever
# reached by finishing the roll, never picked cold, or the cat would blink into
# existence already on its back.
_POSE_WEIGHTS = {
    # Zoomies are most of what this mood is for, but a burst is over in a few
    # seconds and the cat has to be somewhere in between.
    Mood.PLAYFUL: {
        Behavior.IDLE_STANDING: 25,
        Behavior.IDLE_SITTING: 5,
        Behavior.WALKING: 15,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 55,
    },
    Mood.HAPPY: {
        Behavior.IDLE_STANDING: 30,
        Behavior.IDLE_SITTING: 10,
        Behavior.WALKING: 60,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    # The flop is the signature move, but it is a ~4s one-shot that lands back
    # in a normal idle, so a weight near half still leaves plenty of ordinary
    # cat between flops rather than a cat that only ever rolls.
    Mood.TRUSTING: {
        Behavior.IDLE_STANDING: 20,
        Behavior.IDLE_SITTING: 15,
        Behavior.WALKING: 20,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 45,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    Mood.CONTENT: {
        Behavior.IDLE_STANDING: 40,
        Behavior.IDLE_SITTING: 30,
        Behavior.WALKING: 30,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    # Steady-state lying-down idle, same shape as LOAFING's row one rung down.
    Mood.RELAXED: {
        Behavior.IDLE_STANDING: 15,
        Behavior.IDLE_SITTING: 15,
        Behavior.WALKING: 10,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 60,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    Mood.TIRED: {
        Behavior.IDLE_STANDING: 30,
        Behavior.IDLE_SITTING: 50,
        Behavior.WALKING: 10,
        Behavior.SLEEPING: 5,
        Behavior.LOAFING: 5,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    # Mostly settled in the loaf, with the occasional get-up-and-resettle so
    # it doesn't read as a frozen sprite.
    Mood.LOAFING: {
        Behavior.IDLE_STANDING: 10,
        Behavior.IDLE_SITTING: 15,
        Behavior.WALKING: 5,
        Behavior.SLEEPING: 0,
        Behavior.LOAFING: 70,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
    Mood.SLEEPY: {
        Behavior.IDLE_STANDING: 0,
        Behavior.IDLE_SITTING: 0,
        Behavior.WALKING: 0,
        Behavior.SLEEPING: 100,
        Behavior.LOAFING: 0,
        Behavior.RELAXED: 0,
        Behavior.TRUSTING_ROLL: 0,
        Behavior.TRUSTING_BACK: 0,
        Behavior.ZOOMIES: 0,
    },
}

# LOAFING, RELAXED and the belly-up poses are deliberately kept out of each
# other's rows (and out of neighbouring moods') — the lying-down silhouettes
# are similar enough that bleeding them across bands would make the ladder
# harder to read.


# Ladder order, low rank = more energetic. LOAFING sits between TIRED and
# SLEEPY, RELAXED between CONTENT and TIRED, and TRUSTING between HAPPY and
# CONTENT, so "going down" the ladder still means an increasing rank.
_MOOD_RANK = {
    Mood.PLAYFUL: 0,
    Mood.HAPPY: 1,
    Mood.TRUSTING: 2,
    Mood.CONTENT: 3,
    Mood.RELAXED: 4,
    Mood.TIRED: 5,
    Mood.LOAFING: 6,
    Mood.SLEEPY: 7,
}


# A blink swaps in an eyes-closed sprite, so it can only play for behaviors
# that have one drawn in the *same* body pose — otherwise the cat would pop
# into a different posture just to blink. Membership here is what gates
# blinking (see `_start_blink`), so adding a pose with its own closed-eyes
# art is a one-line change.
_BLINK_POSES = {
    Behavior.IDLE_STANDING: Pose.BLINK,
    Behavior.WALKING: Pose.BLINK,
    Behavior.LOAFING: Pose.LOAF_BLINK,
    Behavior.RELAXED: Pose.RELAXED_BLINK,
    Behavior.TRUSTING_BACK: Pose.TRUSTING_BACK_BLINK,
}


# The roll itself. Read as a rock back and forth rather than a single flip:
# the cat goes over, comes part-way back, and goes over again, which sells
# "rolling around" from three frames the way the 2-frame walk cycle sells a
# walk. The cycle always ends on the belly-up frame it settles into.
_ROLL_CYCLE = (
    Pose.TRUSTING_ROLL_A,
    Pose.TRUSTING_ROLL_B,
    Pose.TRUSTING_BACK,
    Pose.TRUSTING_ROLL_B,
)


# The gallop. RUN_C is the half-extended frame, so it reads as the in-between
# in both directions: gather, push off, full extension, recover, gather again.
_RUN_CYCLE = (
    Pose.RUN_B,
    Pose.RUN_C,
    Pose.RUN_A,
    Pose.RUN_C,
)


# Where a mood "comes to rest" after a wake-up transition. Moods absent here
# settle into the generic standing idle.
_RESTING_BEHAVIOR = {
    Mood.LOAFING: Behavior.LOAFING,
    Mood.RELAXED: Behavior.RELAXED,
}


def _resting_behavior(mood: Mood) -> Behavior:
    return _RESTING_BEHAVIOR.get(mood, Behavior.IDLE_STANDING)


def _dist(a: QPoint, b: QPoint) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


@dataclass
class RenderState:
    """Everything paintEvent needs for the current frame."""

    pose: Pose
    facing_left: bool
    y_offset: int
    scale_x: float = 1.0
    scale_y: float = 1.0


class Animator(QObject):
    """Ticks all animation state and tells PetWindow when to repaint/move."""

    update_needed = Signal()
    move_to = Signal(QPoint)  # absolute screen coord for the pet window
    hunt_started = Signal()   # so PetWindow can have the cat say something

    # --- tuning constants ---
    POSE_TICK_MS = 6000            # decide next behavior every 6s
    BLINK_INTERVAL_MIN_MS = 3000
    BLINK_INTERVAL_MAX_MS = 6000
    BLINK_DURATION_MS = 140
    SLOW_BLINK_DURATION_MS = 650   # belly-up: the cat's real "I trust you" cue
    SLOW_BLINK_INTERVAL_MS = 1100  # cadence while belly-up, see _enter_belly_up
    WALK_FRAME_MS = 240            # walk-cycle frame swap
    WALK_STEP_MS = 40              # window-move tick
    WALK_SPEED_PX = 2              # pixels per step
    WANDER_MAX_DIST_PX = 300       # radius from home position
    YAWN_DURATION_MS = 1400
    BREATH_TICK_MS = 80            # ~12fps refresh for the sine bob
    BREATH_PERIOD_MS = 3000
    BREATH_AMPLITUDE_PX = 2
    SLEEP_BREATH_AMPLITUDE_PX = 1
    GAZE_TICK_MS = 1000            # how often to re-check cursor direction
    GAZE_DEAD_ZONE_PX = 50         # ignore cursor if it's roughly over the cat
    STRETCH_DURATION_MS = 900
    STRETCH_SCALE_X = 0.15         # peak widen, as a fraction
    STRETCH_SCALE_Y = 0.12         # peak squash, as a fraction
    STRETCH_FIDGET_CHANCE = 0.15   # per pose-tick, while idle
    PERK_DURATION_MS = 350
    PERK_BOUNCE_PX = 6
    ROLL_FRAME_MS = 150            # roll-cycle frame swap, quicker than a walk
    ROLL_CYCLES_MIN = 2            # "rolls around 2-3 times"
    ROLL_CYCLES_MAX = 3
    # Unlike every other one-shot here, the belly-up hold is a random length.
    # A fixed one makes repeat flops feel metronomic.
    BELLY_HOLD_MIN_MS = 1500
    BELLY_HOLD_MAX_MS = 3500
    # Zoomies: the walk's own numbers, run hot. Three times the step size at
    # half the step interval is what separates a sprint from a stroll.
    RUN_FRAME_MS = 90              # gallop frame swap, vs 240 for the walk
    RUN_STEP_MS = 20               # window-move tick, vs 40
    RUN_SPEED_PX = 6               # pixels per step, vs 2
    ZOOMIES_LEGS_MIN = 3           # dashes per burst
    ZOOMIES_LEGS_MAX = 5
    ZOOMIES_LEG_MIN_PX = 90        # how far one dash covers
    ZOOMIES_LEG_MAX_PX = 240
    # Hunting. The only behavior driven by the user rather than by usage, so
    # these are the numbers to reach for when it triggers too eagerly or never.
    # They live here with the rest of the animation tuning rather than in
    # config.py, which is deliberately about the usage model only.
    STALK_TICK_MS = 300            # cursor poll; dwell is counted in ticks
    STALK_DWELL_MS = 5000          # stillness required before the cat commits
    STALK_STILL_PX = 4             # jitter this small still counts as "stopped"
    STALK_ZONE_NEAR_PX = 60        # nearer than this is "on top of the cat"
    STALK_ZONE_FAR_PX = 500        # beyond this it isn't worth stalking
    STALK_ZONE_BAND_PX = 130       # vertical half-band around the cat
    STALK_BREAK_PX = 30            # cursor moving this far breaks the spell
    STALK_REARM_PX = 60            # ...and must move this far to re-arm
    STALK_COOLDOWN_S = 20.0        # floor on how often a hunt can happen
    STALK_CREEP_FRAME_MS = 380     # slow, deliberate paw placement
    STALK_CREEP_FRAMES = 4         # frames per creep run, before freezing
    STALK_FREEZE_MS = 1200         # how long it holds dead still
    STALK_BEATS_MIN = 2            # creep-then-freeze repetitions
    STALK_BEATS_MAX = 3
    # Closing the distance. Half the walk's speed at the same tick, and only
    # while creeping — a cat that keeps sliding during the freeze isn't frozen.
    STALK_STEP_MS = 40             # window-move tick, same as the walk
    STALK_SPEED_PX = 1             # half the walk's 2px, so it reads as stalking
    STALK_STOP_PX = 70             # stops short of the cursor rather than onto it

    def __init__(
        self,
        initial_mood: Mood,
        get_pet_pos: Callable[[], QPoint],
        get_home_pos: Callable[[], QPoint],
        get_pet_center: Callable[[], QPoint],
    ):
        super().__init__()
        self.mood = initial_mood
        self.behavior = (
            Behavior.SLEEPING if initial_mood == Mood.SLEEPY else Behavior.IDLE_STANDING
        )
        self.facing_left = False

        self._get_pet_pos = get_pet_pos
        self._get_home_pos = get_home_pos
        self._get_pet_center = get_pet_center

        self._is_blinking = False
        self._is_yawning = False
        self._yawn_after: Optional[Behavior] = None
        self._yawn_then_stretch = False

        self._is_stretching = False
        self._stretch_start_time = 0.0
        self._stretch_after: Optional[Behavior] = None

        self._is_perking = False
        self._perk_start_time = 0.0

        self._walk_target: Optional[QPoint] = None
        self._walk_frame_b = False

        self._roll_step = 0
        self._roll_steps_total = 0
        self._trusting_after: Optional[Behavior] = None

        self._run_frame = 0
        self._legs_left = 0

        # Hunting is a flag rather than a Behavior on purpose: it is an overlay
        # that borrows the screen for a few seconds and hands it straight back,
        # so the ladder behavior underneath stays untouched and needs neither
        # saving nor restoring.
        self._is_hunting = False
        self._hunt_frame = 0
        self._hunt_beats_left = 0
        self._hunt_frozen = False
        self._hunt_break = False
        self._stalk_anchor: Optional[QPoint] = None
        self._stalk_still_ms = 0
        self._stalk_armed = True
        # None, not 0.0: time.monotonic()'s epoch is arbitrary and on some
        # platforms counts from process start, so a zero here would read as
        # "a hunt just happened" and ban hunting for the first cooldown of
        # every session.
        self._last_hunt_end: Optional[float] = None

        self._paused = False
        self._start_time = time.monotonic()

        # --- timers ---
        self._pose_timer = self._make_timer(self._tick_pose, self.POSE_TICK_MS)
        self._blink_timer = self._make_timer(
            self._start_blink, self._next_blink_delay(), single_shot=True
        )
        self._blink_end_timer = self._make_timer(
            self._end_blink, self.BLINK_DURATION_MS, single_shot=True, autostart=False
        )
        self._walk_frame_timer = self._make_timer(
            self._toggle_walk_frame, self.WALK_FRAME_MS, autostart=False
        )
        self._walk_step_timer = self._make_timer(
            self._walk_step, self.WALK_STEP_MS, autostart=False
        )
        self._yawn_end_timer = self._make_timer(
            self._end_yawn, self.YAWN_DURATION_MS, single_shot=True, autostart=False
        )
        self._gaze_timer = self._make_timer(self._update_gaze, self.GAZE_TICK_MS)
        self._stretch_end_timer = self._make_timer(
            self._end_stretch, self.STRETCH_DURATION_MS, single_shot=True, autostart=False
        )
        self._perk_end_timer = self._make_timer(
            self._end_perk, self.PERK_DURATION_MS, single_shot=True, autostart=False
        )
        self._roll_frame_timer = self._make_timer(
            self._advance_roll, self.ROLL_FRAME_MS, autostart=False
        )
        self._belly_end_timer = self._make_timer(
            self._end_belly_up, self.BELLY_HOLD_MIN_MS, single_shot=True,
            autostart=False,
        )
        self._slow_blink_timer = self._make_timer(
            self._start_blink, self.SLOW_BLINK_INTERVAL_MS, autostart=False
        )
        self._run_frame_timer = self._make_timer(
            self._advance_run_frame, self.RUN_FRAME_MS, autostart=False
        )
        self._run_step_timer = self._make_timer(
            self._run_step, self.RUN_STEP_MS, autostart=False
        )
        self._stalk_timer = self._make_timer(self._check_stalk, self.STALK_TICK_MS)
        self._hunt_frame_timer = self._make_timer(
            self._advance_hunt_frame, self.STALK_CREEP_FRAME_MS, autostart=False
        )
        self._hunt_freeze_timer = self._make_timer(
            self._end_freeze, self.STALK_FREEZE_MS, single_shot=True, autostart=False
        )
        self._stalk_step_timer = self._make_timer(
            self._stalk_step, self.STALK_STEP_MS, autostart=False
        )
        # Breathing repaint tick — cheap, runs always.
        self._breath_timer = self._make_timer(
            self.update_needed.emit, self.BREATH_TICK_MS
        )

    def _make_timer(
        self,
        slot,
        interval_ms: int,
        single_shot: bool = False,
        autostart: bool = True,
    ) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(single_shot)
        t.timeout.connect(slot)
        if autostart:
            t.start(interval_ms)
        else:
            t.setInterval(interval_ms)
        return t

    # ------------------------------------------------------------------
    # External hooks
    # ------------------------------------------------------------------

    def set_mood(self, new_mood: Mood) -> None:
        if new_mood == self.mood:
            return
        old = self.mood
        self.mood = new_mood
        self._on_mood_changed(old, new_mood)

    def pause(self) -> None:
        """User is dragging — freeze motion, keep breathing/blinking."""
        self._paused = True
        self._walk_step_timer.stop()
        self._run_step_timer.stop()
        self._stalk_step_timer.stop()

    def resume(self) -> None:
        self._paused = False
        # A stalk in progress owns its own movement and has no walk target.
        if self._is_hunting:
            if not self._hunt_frozen:
                self._stalk_step_timer.start(self.STALK_STEP_MS)
            return
        if self._walk_target is None:
            return
        if self.behavior == Behavior.WALKING:
            self._walk_step_timer.start(self.WALK_STEP_MS)
        elif self.behavior == Behavior.ZOOMIES:
            self._run_step_timer.start(self.RUN_STEP_MS)

    def poke(self) -> None:
        """User double-clicked or interacted — trigger a blink now."""
        if not self._is_blinking and self.behavior != Behavior.SLEEPING:
            self._start_blink()

    def perk_up(self) -> None:
        """A fresh burst of activity just started — quick startled-happy bounce."""
        if (
            self.behavior == Behavior.SLEEPING
            or self._is_yawning
            or self._is_stretching
            or self._is_perking
        ):
            return
        self._is_perking = True
        self._perk_start_time = time.monotonic()
        self.update_needed.emit()
        self._perk_end_timer.start(self.PERK_DURATION_MS)

    def _end_perk(self) -> None:
        self._is_perking = False
        self.update_needed.emit()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def current_render(self) -> RenderState:
        if self._is_hunting:
            # The interrupt: whatever the ladder was showing is overridden for
            # the few seconds this lasts, then handed straight back.
            if self._hunt_frozen:
                pose = Pose.HUNT_FREEZE
            else:
                pose = (Pose.HUNT_CREEP_B if self._hunt_frame % 2
                        else Pose.HUNT_CREEP_A)
        elif self._is_yawning:
            pose = Pose.YAWN
        elif self._is_stretching:
            pose = Pose.STANDING
        elif self._is_blinking and self.behavior in _BLINK_POSES:
            # Each blinkable behavior needs its own eyes-closed sprite, or the
            # cat would pop into a different body pose just to blink. A blink
            # that outlives the behavior it started in — the slow one held
            # belly-up can outlast the hold itself — just opens its eyes here
            # rather than drawing a standing cat over a sitting one.
            pose = _BLINK_POSES[self.behavior]
        elif self.behavior == Behavior.ZOOMIES:
            pose = _RUN_CYCLE[self._run_frame % len(_RUN_CYCLE)]
        elif self.behavior == Behavior.TRUSTING_ROLL:
            pose = _ROLL_CYCLE[self._roll_step % len(_ROLL_CYCLE)]
        elif self.behavior == Behavior.TRUSTING_BACK:
            pose = Pose.TRUSTING_BACK
        elif self.behavior == Behavior.WALKING:
            pose = Pose.WALKING_B if self._walk_frame_b else Pose.WALKING_A
        elif self.behavior == Behavior.SLEEPING:
            pose = Pose.SLEEPING
        elif self.behavior == Behavior.IDLE_SITTING:
            pose = Pose.SITTING
        elif self.behavior == Behavior.LOAFING:
            pose = Pose.LOAF
        elif self.behavior == Behavior.RELAXED:
            pose = Pose.RELAXED
        else:
            pose = Pose.STANDING

        # Breathing sine wave.
        amp = (
            self.SLEEP_BREATH_AMPLITUDE_PX
            if self.behavior == Behavior.SLEEPING
            else self.BREATH_AMPLITUDE_PX
        )
        elapsed_ms = (time.monotonic() - self._start_time) * 1000
        phase = (elapsed_ms % self.BREATH_PERIOD_MS) / self.BREATH_PERIOD_MS
        y_offset = int(round(math.sin(phase * 2 * math.pi) * amp))

        # Squash-and-stretch: procedural scale on the standing sprite, no
        # dedicated art needed. Anchored at the feet in paintEvent.
        scale_x = scale_y = 1.0
        if self._is_stretching:
            t = min(
                1.0,
                (time.monotonic() - self._stretch_start_time)
                * 1000
                / self.STRETCH_DURATION_MS,
            )
            stretch_factor = math.sin(t * math.pi)
            scale_x = 1.0 + self.STRETCH_SCALE_X * stretch_factor
            scale_y = 1.0 - self.STRETCH_SCALE_Y * stretch_factor

        if self._is_perking:
            t = min(
                1.0,
                (time.monotonic() - self._perk_start_time) * 1000 / self.PERK_DURATION_MS,
            )
            y_offset -= int(round(math.sin(t * math.pi) * self.PERK_BOUNCE_PX))

        return RenderState(
            pose=pose,
            facing_left=self.facing_left,
            y_offset=y_offset,
            scale_x=scale_x,
            scale_y=scale_y,
        )

    # ------------------------------------------------------------------
    # Pose selection
    # ------------------------------------------------------------------

    def _tick_pose(self) -> None:
        if self._is_yawning or self._is_stretching or self._paused:
            return
        # A hunt overrides the pose entirely; re-rolling underneath it would
        # change what the cat drops back into halfway through the stalk.
        if self._is_hunting:
            return
        # A flop or a zoomies burst drives its own timers through to a settled
        # behavior; re-rolling mid-way would strand it half over or mid-stride.
        if self.behavior in (Behavior.TRUSTING_ROLL, Behavior.TRUSTING_BACK,
                             Behavior.ZOOMIES):
            return
        # Sleepy mood is locked into sleeping.
        if self.mood == Mood.SLEEPY:
            if self.behavior != Behavior.SLEEPING:
                self._enter_behavior(Behavior.SLEEPING)
            return
        # Occasional idle fidget: stand up and stretch, then settle back.
        if self.behavior in (Behavior.IDLE_STANDING, Behavior.IDLE_SITTING):
            if random.random() < self.STRETCH_FIDGET_CHANCE:
                self._play_stretch(after=self.behavior)
                return
        weights = _POSE_WEIGHTS[self.mood]
        chosen = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
        if chosen != self.behavior:
            self._enter_behavior(chosen)

    def _enter_behavior(self, new: Behavior) -> None:
        self._stop_walking()
        self._stop_trusting()
        self._stop_zoomies()
        if new == Behavior.TRUSTING_ROLL:
            # Not a resting state: the flop runs itself through the roll and
            # the belly-up hold, then settles into a normal idle.
            self._play_trusting_roll(after=Behavior.IDLE_SITTING)
            return
        if new == Behavior.ZOOMIES:
            self._play_zoomies()
            return
        self.behavior = new
        if new == Behavior.WALKING:
            self._start_walk()
        self.update_needed.emit()

    # ------------------------------------------------------------------
    # Blink
    # ------------------------------------------------------------------

    def _next_blink_delay(self) -> int:
        return random.randint(self.BLINK_INTERVAL_MIN_MS, self.BLINK_INTERVAL_MAX_MS)

    def _blink_duration(self) -> int:
        """How long the eyes stay shut — deliberately languid when belly-up."""
        if self.behavior == Behavior.TRUSTING_BACK:
            return self.SLOW_BLINK_DURATION_MS
        return self.BLINK_DURATION_MS

    def _start_blink(self) -> None:
        # Only behaviors with a matching eyes-closed sprite may blink. A
        # stalking cat holds the stare, and has no eyes-closed art anyway.
        if (self.behavior not in _BLINK_POSES or self._is_yawning
                or self._is_hunting):
            self._blink_timer.start(self._next_blink_delay())
            return
        if self._is_blinking:
            # Already mid-blink — usually the idle timer landing on top of a
            # slow blink. _end_blink re-arms the idle timer, so just drop this.
            return
        self._is_blinking = True
        self.update_needed.emit()
        self._blink_end_timer.start(self._blink_duration())

    def _end_blink(self) -> None:
        self._is_blinking = False
        self.update_needed.emit()
        self._blink_timer.start(self._next_blink_delay())

    # ------------------------------------------------------------------
    # Walking / wander
    # ------------------------------------------------------------------

    def _start_walk(self) -> None:
        home = self._get_home_pos()
        current = self._get_pet_pos()
        target_x = home.x() + random.randint(
            -self.WANDER_MAX_DIST_PX, self.WANDER_MAX_DIST_PX
        )
        self._walk_target = QPoint(target_x, current.y())
        self.facing_left = target_x < current.x()
        self._walk_frame_b = False
        self._walk_frame_timer.start(self.WALK_FRAME_MS)
        if not self._paused:
            self._walk_step_timer.start(self.WALK_STEP_MS)

    def _toggle_walk_frame(self) -> None:
        self._walk_frame_b = not self._walk_frame_b
        self.update_needed.emit()

    def _walk_step(self) -> None:
        if self._walk_target is None:
            self._walk_step_timer.stop()
            return
        current = self._get_pet_pos()
        dx = self._walk_target.x() - current.x()
        if abs(dx) <= self.WALK_SPEED_PX:
            self.move_to.emit(self._walk_target)
            self._stop_walking()
            self.behavior = Behavior.IDLE_STANDING
            self.update_needed.emit()
            return
        step = self.WALK_SPEED_PX if dx > 0 else -self.WALK_SPEED_PX
        self.move_to.emit(QPoint(current.x() + step, current.y()))
        if self._blocked(current.x()):
            self._stop_walking()
            self.behavior = Behavior.IDLE_STANDING
            self.update_needed.emit()

    def _blocked(self, previous_x: int) -> bool:
        """Did the last move_to actually move the pet?

        The window clamps itself to the screen, so a target beyond the edge is
        unreachable: the distance to it never shrinks and the leg would never
        finish, leaving the cat sprinting on the spot against the edge forever.
        Treating "asked to move and didn't" as arrival is what ends it.
        """
        return self._get_pet_pos().x() == previous_x

    def _stop_walking(self) -> None:
        self._walk_frame_timer.stop()
        self._walk_step_timer.stop()
        self._walk_target = None
        self._walk_frame_b = False

    # ------------------------------------------------------------------
    # Mood transitions (one-shot animations)
    # ------------------------------------------------------------------

    def _on_mood_changed(self, old: Mood, new: Mood) -> None:
        going_down = _MOOD_RANK[new] > _MOOD_RANK[old]
        waking_up = old == Mood.SLEEPY and _MOOD_RANK[new] < _MOOD_RANK[old]

        if new == Mood.SLEEPY:
            # Yawn, then fall asleep.
            self._play_yawn(after=Behavior.SLEEPING)
        elif going_down and new == Mood.TIRED:
            # Yawn but stay standing.
            self._play_yawn(after=Behavior.IDLE_STANDING)
        elif going_down and new == Mood.LOAFING:
            # Yawn, then settle down into the loaf.
            self._play_yawn(after=Behavior.LOAFING)
        elif waking_up:
            # Yawn "wake-up", stretch it out, then resume normal life — which
            # for the lying-down moods means settling straight back down.
            self._play_yawn(after=_resting_behavior(new), then_stretch=True)
        elif new == Mood.PLAYFUL:
            # Straight into a burst — hitting this band at all is the event.
            self._play_zoomies()
        elif new == Mood.TRUSTING:
            # Flop straight away rather than waiting on the next pose re-roll —
            # arriving in this band is the moment worth reacting to. Fires in
            # both directions: settling down out of HAPPY reads as well as
            # warming up out of CONTENT.
            self._play_trusting_roll(after=Behavior.IDLE_SITTING)
        else:
            # RELAXED lands here: it's a steady-state idle pose, so it just
            # gets picked up by the next weighted pose re-roll rather than
            # needing its own transition animation.
            self.update_needed.emit()

    def _play_yawn(self, after: Optional[Behavior], then_stretch: bool = False) -> None:
        self._stop_walking()
        # A yawn only starts on a mood change, which is exactly when a flop
        # should give way — the spec's "let the one-shot finish" is about not
        # interrupting it for nothing, and leaving the roll timers running
        # would draw a yawn over a cat that is still rolling underneath.
        self._stop_trusting()
        self._stop_zoomies()
        self._stop_hunting()
        self._is_yawning = True
        self._yawn_after = after
        self._yawn_then_stretch = then_stretch
        self.update_needed.emit()
        self._yawn_end_timer.start(self.YAWN_DURATION_MS)

    def _end_yawn(self) -> None:
        self._is_yawning = False
        after = self._yawn_after
        self._yawn_after = None
        if self._yawn_then_stretch:
            self._yawn_then_stretch = False
            self._play_stretch(after=after)
        else:
            if after is not None:
                self.behavior = after
            self.update_needed.emit()

    # ------------------------------------------------------------------
    # Hunting — the one behavior driven by the user, not by usage
    # ------------------------------------------------------------------

    def _stalk_zone_holds(self, cursor: QPoint) -> bool:
        """Is the cursor somewhere worth stalking?

        A horizontal reach either side of the cat, within a vertical band of
        its own height. Not a true line of sight — the cat is a 2D sprite on a
        desktop — but it reads as one, and it keeps the cat from stalking
        something three monitors away or the pointer resting on its own face.
        """
        center = self._get_pet_center()
        if abs(cursor.y() - center.y()) > self.STALK_ZONE_BAND_PX:
            return False
        dx = abs(cursor.x() - center.x())
        return self.STALK_ZONE_NEAR_PX <= dx <= self.STALK_ZONE_FAR_PX

    def _may_hunt(self) -> bool:
        """Gate: busy enough, settled enough, and not already mid-something."""
        if _MOOD_RANK[self.mood] > _MOOD_RANK[Mood.CONTENT]:
            return False        # a tired cat does not stalk
        if self._paused or self._is_hunting:
            return False
        if self._is_yawning or self._is_stretching or self._is_perking:
            return False
        if self.behavior in (Behavior.SLEEPING, Behavior.ZOOMIES,
                             Behavior.TRUSTING_ROLL, Behavior.TRUSTING_BACK):
            return False        # let the other one-shots finish undisturbed
        if self._last_hunt_end is None:
            return True     # nothing to cool down from yet
        return time.monotonic() - self._last_hunt_end >= self.STALK_COOLDOWN_S

    def _check_stalk(self) -> None:
        """Watch the cursor for five seconds of stillness in the zone."""
        cursor = QCursor.pos()

        if self._is_hunting:
            # Already stalking: the only question is whether the prey moved.
            if (self._stalk_anchor is not None
                    and _dist(cursor, self._stalk_anchor) > self.STALK_BREAK_PX):
                self._hunt_break = True
            return

        # After a hunt the cursor is, by definition, still sitting exactly
        # where the cat was staring. Without this the dwell timer would refill
        # against an abandoned mouse and the cat would stalk it all afternoon.
        if not self._stalk_armed:
            if (self._stalk_anchor is None
                    or _dist(cursor, self._stalk_anchor) > self.STALK_REARM_PX):
                self._stalk_armed = True
                self._stalk_anchor = None
                self._stalk_still_ms = 0
            return

        if not self._stalk_zone_holds(cursor) or not self._may_hunt():
            self._stalk_anchor = None
            self._stalk_still_ms = 0
            return

        if (self._stalk_anchor is None
                or _dist(cursor, self._stalk_anchor) > self.STALK_STILL_PX):
            self._stalk_anchor = QPoint(cursor)
            self._stalk_still_ms = 0
            return

        self._stalk_still_ms += self.STALK_TICK_MS
        if self._stalk_still_ms >= self.STALK_DWELL_MS:
            self._start_hunt()

    def _start_hunt(self) -> None:
        self._stop_walking()
        self._stop_trusting()
        self._stop_zoomies()
        if self.behavior == Behavior.WALKING:
            # The walk is over; without this the cat would pop back into a
            # mid-stride frame when the hunt ends.
            self.behavior = Behavior.IDLE_STANDING
        self._is_hunting = True
        self._hunt_break = False
        self._hunt_frame = 0
        self._hunt_beats_left = random.randint(self.STALK_BEATS_MIN,
                                               self.STALK_BEATS_MAX)
        cursor = QCursor.pos()
        self._stalk_anchor = QPoint(cursor)
        self.facing_left = cursor.x() < self._get_pet_center().x()
        self.hunt_started.emit()
        self._begin_creep()

    def _begin_creep(self) -> None:
        self._hunt_frozen = False
        self._hunt_frame = 0
        # Re-aim at the start of each creep run rather than every step, so the
        # cat commits to a direction for the length of a beat instead of
        # jittering if the cursor drifts a pixel.
        cursor = QCursor.pos()
        self.facing_left = cursor.x() < self._get_pet_center().x()
        self.update_needed.emit()
        self._hunt_frame_timer.start(self.STALK_CREEP_FRAME_MS)
        if not self._paused:
            self._stalk_step_timer.start(self.STALK_STEP_MS)

    def _stalk_step(self) -> None:
        """Close on the cursor, a pixel at a time, while creeping."""
        cursor = QCursor.pos()
        current = self._get_pet_pos()
        dx = cursor.x() - self._get_pet_center().x()
        if abs(dx) <= self.STALK_STOP_PX:
            self._stalk_step_timer.stop()   # close enough; hold position
            return
        step = self.STALK_SPEED_PX if dx > 0 else -self.STALK_SPEED_PX
        self.move_to.emit(QPoint(current.x() + step, current.y()))
        if self._blocked(current.x()):
            self._stalk_step_timer.stop()   # screen edge; stalk in place

    def _advance_hunt_frame(self) -> None:
        self._hunt_frame += 1
        if self._hunt_frame >= self.STALK_CREEP_FRAMES:
            self._hunt_frame_timer.stop()
            self._begin_freeze()
            return
        self.update_needed.emit()

    def _begin_freeze(self) -> None:
        self._stalk_step_timer.stop()       # stop moving first: frozen is frozen
        self._hunt_frozen = True
        self.update_needed.emit()
        self._hunt_freeze_timer.start(self.STALK_FREEZE_MS)

    def _end_freeze(self) -> None:
        self._hunt_beats_left -= 1
        # Break only here, at a beat boundary. Cutting mid-creep would snap the
        # cat upright halfway through a paw placement.
        if self._hunt_beats_left <= 0 or self._hunt_break:
            self._end_hunt()
            return
        self._begin_creep()

    def _end_hunt(self) -> None:
        self._stop_hunting()
        self._last_hunt_end = time.monotonic()
        self._stalk_armed = False        # cursor must move away before another
        self.update_needed.emit()

    def _stop_hunting(self) -> None:
        self._hunt_frame_timer.stop()
        self._hunt_freeze_timer.stop()
        self._stalk_step_timer.stop()
        self._is_hunting = False
        self._hunt_frozen = False
        self._hunt_break = False
        self._hunt_frame = 0
        self._hunt_beats_left = 0
        self._stalk_still_ms = 0

    # ------------------------------------------------------------------
    # Playful — the zoomies: several fast dashes, then settle
    # ------------------------------------------------------------------

    def _play_zoomies(self) -> None:
        """Sprint back and forth a few times, then go back to normal.

        Deliberately built on the walk's own target-and-step machinery rather
        than new pathing: a burst is just several short walk legs taken with a
        bigger step and a faster tick. What sells it as running instead of
        walking is the gallop cycle and the speed, not the route.
        """
        self._stop_walking()
        self._stop_hunting()
        self._legs_left = random.randint(self.ZOOMIES_LEGS_MIN,
                                         self.ZOOMIES_LEGS_MAX)
        self._run_frame = 0
        self.behavior = Behavior.ZOOMIES
        self._run_frame_timer.start(self.RUN_FRAME_MS)
        self._next_zoomies_leg()

    def _next_zoomies_leg(self) -> None:
        if self._legs_left <= 0:
            self._end_zoomies()
            return
        self._legs_left -= 1
        current = self._get_pet_pos()
        home = self._get_home_pos()
        dist = random.randint(self.ZOOMIES_LEG_MIN_PX, self.ZOOMIES_LEG_MAX_PX)
        # Turn back toward home when a dash would take it beyond the wander
        # radius, so a burst paces around home instead of drifting off in one
        # direction. Screen edges are handled separately, by the window.
        if abs(current.x() - home.x()) > self.WANDER_MAX_DIST_PX * 0.6:
            direction = 1 if current.x() < home.x() else -1
        else:
            direction = random.choice((-1, 1))
        target_x = current.x() + direction * dist
        self._walk_target = QPoint(target_x, current.y())
        self.facing_left = direction < 0
        self.update_needed.emit()
        if not self._paused:
            self._run_step_timer.start(self.RUN_STEP_MS)

    def _advance_run_frame(self) -> None:
        self._run_frame += 1
        self.update_needed.emit()

    def _run_step(self) -> None:
        if self._walk_target is None:
            self._run_step_timer.stop()
            return
        current = self._get_pet_pos()
        dx = self._walk_target.x() - current.x()
        if abs(dx) <= self.RUN_SPEED_PX:
            self.move_to.emit(self._walk_target)
            self._run_step_timer.stop()
            self._walk_target = None
            self._next_zoomies_leg()
            return
        step = self.RUN_SPEED_PX if dx > 0 else -self.RUN_SPEED_PX
        self.move_to.emit(QPoint(current.x() + step, current.y()))
        if self._blocked(current.x()):
            # Hit a screen edge. End this dash and let the next one pick a new
            # direction — which will be back toward home, since being pinned at
            # an edge puts the cat outside the turn-around radius.
            self._run_step_timer.stop()
            self._walk_target = None
            self._next_zoomies_leg()

    def _end_zoomies(self) -> None:
        self._stop_zoomies()
        self.behavior = Behavior.IDLE_STANDING
        self.update_needed.emit()

    def _stop_zoomies(self) -> None:
        """Abandon a burst. Callers then set the behavior they want."""
        self._run_frame_timer.stop()
        self._run_step_timer.stop()
        self._walk_target = None
        self._run_frame = 0
        self._legs_left = 0
        if self.behavior == Behavior.ZOOMIES:
            # Same invariant as the flop: never leave the behavior standing
            # with no timer driving it, or _tick_pose will refuse to move on.
            self.behavior = Behavior.IDLE_STANDING

    # ------------------------------------------------------------------
    # Trusting — roll onto the back, hold belly-up, get up again
    # ------------------------------------------------------------------

    def _play_trusting_roll(self, after: Optional[Behavior]) -> None:
        """Roll over a few times, settle belly-up, then land in `after`.

        Same one-shot shape as `_play_yawn`, with one extra beat: the hold at
        the end runs for a random length rather than a fixed one.
        """
        self._stop_walking()
        self._stop_hunting()
        self._trusting_after = after
        self._roll_step = 0
        cycles = random.randint(self.ROLL_CYCLES_MIN, self.ROLL_CYCLES_MAX)
        # Land on the belly-up frame that ends the last cycle, not on the
        # part-way-back frame that would otherwise follow it.
        self._roll_steps_total = cycles * len(_ROLL_CYCLE) - 1
        self.behavior = Behavior.TRUSTING_ROLL
        self.update_needed.emit()
        self._roll_frame_timer.start(self.ROLL_FRAME_MS)

    def _advance_roll(self) -> None:
        self._roll_step += 1
        if self._roll_step >= self._roll_steps_total:
            self._roll_frame_timer.stop()
            self._enter_belly_up()
            return
        self.update_needed.emit()

    def _enter_belly_up(self) -> None:
        self.behavior = Behavior.TRUSTING_BACK
        self.update_needed.emit()
        # Drive the slow blinks on their own cadence instead of leaving them to
        # the 3-6s idle blink timer, which would miss this hold entirely more
        # often than not.
        self._slow_blink_timer.start(self.SLOW_BLINK_INTERVAL_MS)
        self._belly_end_timer.start(
            random.randint(self.BELLY_HOLD_MIN_MS, self.BELLY_HOLD_MAX_MS)
        )

    def _end_belly_up(self) -> None:
        self._slow_blink_timer.stop()
        after = self._trusting_after
        self._trusting_after = None
        self.behavior = after if after is not None else Behavior.IDLE_STANDING
        self.update_needed.emit()

    def _stop_trusting(self) -> None:
        """Abandon a flop in progress. Callers then set the behavior they want."""
        self._roll_frame_timer.stop()
        self._belly_end_timer.stop()
        self._slow_blink_timer.stop()
        self._roll_step = 0
        self._roll_steps_total = 0
        self._trusting_after = None
        if self.behavior in (Behavior.TRUSTING_ROLL, Behavior.TRUSTING_BACK):
            # Never leave a flop behavior standing with no timer driving it:
            # _tick_pose declines to re-roll those, so the cat would hold a
            # single roll frame indefinitely. This keeps the invariant that
            # those two behaviors are only ever set while the flop is running.
            self.behavior = Behavior.IDLE_STANDING

    # ------------------------------------------------------------------
    # Stretch (squash-and-stretch, procedural — no dedicated sprite)
    # ------------------------------------------------------------------

    def _play_stretch(self, after: Optional[Behavior]) -> None:
        self._is_stretching = True
        self._stretch_start_time = time.monotonic()
        self._stretch_after = after
        self.update_needed.emit()
        self._stretch_end_timer.start(self.STRETCH_DURATION_MS)

    def _end_stretch(self) -> None:
        self._is_stretching = False
        if self._stretch_after is not None:
            self.behavior = self._stretch_after
            self._stretch_after = None
        self.update_needed.emit()

    # ------------------------------------------------------------------
    # Gaze — glance toward the mouse cursor while idle
    # ------------------------------------------------------------------

    def _update_gaze(self) -> None:
        if self._paused or self._is_yawning or self._is_stretching:
            return
        # A hunt aims the cat itself, on its own schedule.
        if self._is_hunting:
            return
        if self.behavior not in (Behavior.IDLE_STANDING, Behavior.IDLE_SITTING):
            return
        cursor = QCursor.pos()
        center = self._get_pet_center()
        dx = cursor.x() - center.x()
        if abs(dx) < self.GAZE_DEAD_ZONE_PX:
            return
        looking_left = dx < 0
        if looking_left != self.facing_left:
            self.facing_left = looking_left
            self.update_needed.emit()

"""The pet window: hosts the animator and paints whatever it says to paint."""

from __future__ import annotations

import random
import time
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .animation import Animator, Behavior
from .artwork import Pose, draw_zzz, max_sprite_size, pixmap_for
from .moods import HUNT_LINES, MOOD_LINES, PERK_LINES, Mood
from .speech import SpeechBubble
from .usage import StubUsageSource

# Extra padding around the largest sprite so breathing bob + zzz text fit.
WINDOW_PADDING = 20


class PetWindow(QWidget):
    mood_changed = Signal(Mood)

    # Minimum gap between "perk up" reactions, so flickering activity around
    # zero doesn't cause a bounce every poll.
    PERK_COOLDOWN_S = 15.0

    def __init__(self, usage_source, pet_name: str = "Meowsage"):
        super().__init__()
        self.usage_source = usage_source
        self.pet_name = pet_name
        self.current_mood = usage_source.get().mood

        # No Qt.Tool on macOS — it would hide the window when we lose focus.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(pet_name)

        sw, sh = max_sprite_size()
        self.resize(sw + WINDOW_PADDING * 2, sh + WINDOW_PADDING * 2)

        # Home position is set once the window is placed by app.py, then
        # updated any time the user drags the pet (that becomes the new home).
        self._home_pos: QPoint = QPoint(0, 0)

        self.animator = Animator(
            initial_mood=self.current_mood,
            get_pet_pos=lambda: self.pos(),
            get_home_pos=lambda: self._home_pos,
            get_pet_center=lambda: self.geometry().center(),
        )
        self.animator.update_needed.connect(self.update)
        self.animator.move_to.connect(self._move_within_screen)
        self.animator.hunt_started.connect(
            lambda: self._say_something(reset_timer=True, lines=HUNT_LINES)
        )

        self.bubble = SpeechBubble(self)

        self._drag_offset: Optional[QPoint] = None

        # Edge-detection state for the "perk up" reaction (see _maybe_perk_up).
        self._last_foreground_tokens = 0
        # None rather than 0.0 — time.monotonic()'s epoch is arbitrary and can
        # count from process start, in which case a zero reads as "just perked"
        # and swallows the first reaction of the session.
        self._last_perk_time: Optional[float] = None

        # Usage polling — mood recomputed every 2s; animator handles transitions.
        self._mood_timer = QTimer(self)
        self._mood_timer.timeout.connect(self._refresh_mood)
        self._mood_timer.start(2000)

        # Speech timer (random 12-25s cadence).
        self._speech_timer = QTimer(self)
        self._speech_timer.setSingleShot(True)
        self._speech_timer.timeout.connect(self._say_something)
        self._schedule_next_speech()

        # Dev shortcuts.
        QShortcut(QKeySequence("Up"), self, activated=lambda: self._bump_usage(0.1))
        QShortcut(QKeySequence("Down"), self, activated=lambda: self._bump_usage(-0.1))
        QShortcut(QKeySequence("Q"), self, activated=self.close)

    def _move_within_screen(self, pos: QPoint) -> None:
        """Move, but never off the side of the screen.

        Nothing used to stop the pet wandering past the edge — it starts in the
        bottom-right corner and wanders up to WANDER_MAX_DIST_PX either way, so
        a walk to the right could already take half the cat off-screen. The
        zoomies made it happen constantly rather than occasionally, which is
        what turned it from a curiosity into a bug worth fixing here, where
        both walking and running go through one place.

        Only the horizontal axis is constrained: nothing moves the pet
        vertically today.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            lo = area.left()
            hi = area.right() - self.width() + 1
            if hi >= lo:
                pos = QPoint(max(lo, min(hi, pos.x())), pos.y())
        self.move(pos)

    def place_at(self, pos: QPoint) -> None:
        """Called by app.py after the window is created, to set the home spot."""
        self.move(pos)
        self._home_pos = pos

    def greet(self) -> None:
        """Called once by app.py shortly after the window is shown."""
        from . import profile as profile_store

        # No saved profile means the naming question was skipped for want of a
        # terminal — the pet was double-clicked or started at login (see
        # profile.load_or_run_setup). This bubble is then the only hint that the
        # name is changeable at all, so it carries the command. Kept short
        # enough that the bubble isn't clamped against the screen edge, which
        # would leave its tail pointing away from the cat.
        if profile_store.load() is None:
            message = f"Hi, I'm {self.pet_name} — try 'meow rename'"
        else:
            message = f"Hi, I'm {self.pet_name}!"
        self.bubble.show_message(message, self.geometry())

    # --- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        state = self.animator.current_render()
        pm: QPixmap = pixmap_for(state.pose, self.current_mood)

        # Centered inside the widget, with breathing y-offset.
        cx = (self.width() - pm.width()) // 2
        cy = (self.height() - pm.height()) // 2 + state.y_offset

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # Single transform: anchor at the sprite's feet (bottom-center) so
        # squash/stretch grows from the ground, and flip for facing direction.
        # With scale_x == scale_y == 1 and facing_left == False this reduces
        # to plain drawPixmap(cx, cy, pm).
        painter.save()
        anchor_x = cx + pm.width() / 2
        anchor_y = cy + pm.height()
        painter.translate(anchor_x, anchor_y)
        flip = -1 if state.facing_left else 1
        painter.scale(flip * state.scale_x, state.scale_y)
        painter.translate(-pm.width() / 2, -pm.height())
        painter.drawPixmap(0, 0, pm)
        painter.restore()

        if state.pose == Pose.SLEEPING:
            draw_zzz(painter, cx, cy, pm.width(), pm.height())

    # --- mouse ------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self.animator.pause()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            if self.bubble.isVisible():
                self.bubble.reposition_over(self.geometry())
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            # Dragged position becomes the new home for future wandering.
            self._home_pos = self.pos()
        self._drag_offset = None
        self.animator.resume()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.animator.poke()
            self._say_something(reset_timer=True)

    def moveEvent(self, event) -> None:
        # Keep the speech bubble anchored above the pet as it moves.
        super().moveEvent(event)
        if hasattr(self, "bubble") and self.bubble.isVisible():
            self.bubble.reposition_over(self.geometry())

    # --- mood / speech ----------------------------------------------------

    def _refresh_mood(self) -> None:
        usage = self.usage_source.get()
        self._maybe_perk_up(usage)
        new_mood = usage.mood
        if new_mood != self.current_mood:
            self.current_mood = new_mood
            self.animator.set_mood(new_mood)
            self.mood_changed.emit(new_mood)
            self.update()

    def _maybe_perk_up(self, usage) -> None:
        """React immediately when activity resumes, not just on mood change.

        Edge-detects the foreground token rate going from idle (0) to active,
        rather than firing continuously while already busy, so a burst gets
        one bounce instead of one every 2s poll.
        """
        was_idle = self._last_foreground_tokens <= 0
        self._last_foreground_tokens = usage.foreground_tokens
        if not (was_idle and usage.foreground_tokens > 0):
            return
        now = time.monotonic()
        if (self._last_perk_time is not None
                and now - self._last_perk_time < self.PERK_COOLDOWN_S):
            return
        self._last_perk_time = now
        self.animator.perk_up()
        self._say_something(reset_timer=True, lines=PERK_LINES)

    def _bump_usage(self, delta: float) -> None:
        # Only affects StubUsageSource; real source treats bump() as a no-op.
        self.usage_source.bump(delta)
        self._refresh_mood()

    def _schedule_next_speech(self) -> None:
        self._speech_timer.start(random.randint(12_000, 25_000))

    def _say_something(
        self, reset_timer: bool = False, lines: Optional[list[str]] = None
    ) -> None:
        # Sleeping cat says only sleepy things (usually zzz).
        pool = lines if lines is not None else MOOD_LINES[self.current_mood]
        line = random.choice(pool)
        self.bubble.show_message(line, self.geometry())
        if reset_timer:
            self._speech_timer.stop()
        self._schedule_next_speech()

    # --- context menu -----------------------------------------------------

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        force_menu = menu.addMenu("Force mood")
        for mood in Mood:
            act = QAction(mood.value.capitalize(), self)
            act.triggered.connect(lambda checked=False, m=mood: self._force_mood(m))
            force_menu.addAction(act)
        menu.addSeparator()
        say_action = QAction("Say something", self)
        say_action.triggered.connect(lambda: self._say_something(reset_timer=True))
        menu.addAction(say_action)
        wander_action = QAction("Wander now", self)
        wander_action.triggered.connect(self._force_wander)
        menu.addAction(wander_action)
        # Hunting normally needs the cursor held still for 5s in the right
        # spot, which is tedious to reproduce on purpose while tuning it.
        hunt_action = QAction("Hunt now", self)
        hunt_action.triggered.connect(self._force_hunt)
        menu.addAction(hunt_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        menu.exec(global_pos)

    def _force_mood(self, mood: Mood) -> None:
        # Anchors reflect the new activity semantic: high activity = HAPPY.
        anchors = {
            Mood.SLEEPY: 0.05,
            Mood.LOAFING: 0.20,
            Mood.TIRED: 0.36,
            Mood.RELAXED: 0.52,
            Mood.CONTENT: 0.72,
            Mood.TRUSTING: 0.81,
            Mood.HAPPY: 0.90,
            Mood.PLAYFUL: 0.98,
        }
        # set_activity on stub source; no-op on real source (menu is dev-only).
        if hasattr(self.usage_source, "set_activity"):
            self.usage_source.set_activity(anchors[mood])
        self._refresh_mood()

    def _force_wander(self) -> None:
        # Skip if sleeping.
        if self.animator.behavior == Behavior.SLEEPING:
            return
        self.animator._enter_behavior(Behavior.WALKING)

    def _force_hunt(self) -> None:
        """Start a hunt now, bypassing the dwell wait but not the mood gate.

        Deliberately still refuses when the cat is too idle to hunt, so this
        exercises the real entry condition rather than a private back door.
        """
        if not self.animator._may_hunt():
            self._say_something(reset_timer=True,
                                lines=["not in the mood to hunt"])
            return
        self.animator._start_hunt()

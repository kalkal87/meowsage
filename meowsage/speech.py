"""Floating speech bubble drawn above the pet."""

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget


class SpeechBubble(QWidget):
    """A little top-level window that appears above the pet."""

    TAIL_HEIGHT = 10

    def __init__(self, pet_window: QWidget):
        super().__init__(None)  # top-level, independent of pet's coordinate space
        self.pet_window = pet_window
        # Qt.Tool: prevents macOS from treating the bubble as a real key
        # window (which was yanking focus away from whatever app the user
        # was in every time the cat spoke). The bubble is short-lived, so
        # the "Tool hides on app deactivate" downside doesn't matter here.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput  # click passes through
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Make macOS treat this as a non-activating overlay panel.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._text = ""
        self._font = QFont("Helvetica", 12)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(
        self, text: str, pet_geometry: QRect, duration_ms: int = 3500
    ) -> None:
        self._text = text
        fm = QFontMetrics(self._font)
        text_w = fm.horizontalAdvance(text) + 26
        text_h = fm.height() + 16
        self.resize(text_w, text_h + self.TAIL_HEIGHT)
        self.reposition_over(pet_geometry)
        # Deliberately NOT calling raise_(): on macOS it can re-activate the
        # owning app and steal focus from whatever the user was doing. The
        # Qt.WindowStaysOnTopHint flag already keeps the bubble above other
        # windows, so raise_() is redundant here.
        self.show()
        self._hide_timer.start(duration_ms)

    def reposition_over(self, pet_geometry: QRect) -> None:
        x = pet_geometry.center().x() - self.width() // 2
        y = pet_geometry.top() - self.height() + 12
        # Keep it on screen. The bubble is sized to its text and the pet starts
        # in the bottom-right corner, so a long line hangs off the right edge —
        # the longest existing one already did, by a few pixels. Same clamp
        # PetWindow._move_within_screen applies to the cat, for the same reason.
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            lo = area.left()
            hi = area.right() - self.width() + 1
            if hi >= lo:
                x = max(lo, min(hi, x))
        self.move(x, y)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(self._font)

        body_rect = QRect(0, 0, self.width() - 1, self.height() - self.TAIL_HEIGHT - 1)
        cx = self.width() // 2

        # Build a single path: rounded rect + triangle tail merged
        rect_path = QPainterPath()
        rect_path.addRoundedRect(body_rect, 12, 12)
        tail_path = QPainterPath()
        tail_path.moveTo(cx - 8, body_rect.bottom())
        tail_path.lineTo(cx, self.height() - 1)
        tail_path.lineTo(cx + 8, body_rect.bottom())
        tail_path.closeSubpath()
        combined = rect_path.united(tail_path)

        p.setBrush(QBrush(QColor(255, 255, 255, 240)))
        p.setPen(QPen(QColor(60, 60, 70), 1.5))
        p.drawPath(combined)

        p.setPen(QPen(QColor(30, 30, 40)))
        p.drawText(body_rect, Qt.AlignmentFlag.AlignCenter, self._text)

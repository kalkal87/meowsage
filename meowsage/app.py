"""Application entry point."""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .artwork import app_icon_path
from .pet import PetWindow
from .usage import make_default_usage_source


def _claim_windows_app_id() -> None:
    # Without an explicit AppUserModelID, Windows groups a python.exe-launched
    # process under the interpreter's own taskbar identity and icon, so the
    # taskbar/Alt-Tab entry shows the Python logo no matter what QIcon we set
    # below. Must run before QApplication() creates any window.
    if sys.platform.startswith("win"):
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Meowsage.Meowsage")
        except OSError:
            pass


def main(pet_name: str = "Meowsage") -> None:
    _claim_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Meowsage")
    app.setApplicationDisplayName("Meowsage")
    # Note this does *not* rename the app in the Dock or the Cmd-Tab switcher.
    # macOS takes that label from the running executable, so a plain `meow` from
    # the terminal is labelled "Python" however Qt is configured. `meow
    # install-app` builds the bundle that fixes it — see appbundle.py. Qt's own
    # name is still worth setting: it is what QSettings and any dialog we ever
    # show will identify themselves as.
    app.setQuitOnLastWindowClosed(True)
    # Without this the Dock shows the Python interpreter's own rocket icon,
    # since the pet runs as a plain console script rather than a bundled .app.
    icon_path = app_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    usage = make_default_usage_source()
    pet = PetWindow(usage, pet_name=pet_name)

    from PySide6.QtCore import QPoint, QTimer

    screen_geo = app.primaryScreen().availableGeometry()
    home = QPoint(
        screen_geo.right() - pet.width() - 40,
        screen_geo.bottom() - pet.height() - 40,
    )
    pet.place_at(home)
    pet.show()
    QTimer.singleShot(400, pet.greet)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

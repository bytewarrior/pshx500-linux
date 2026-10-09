"""GUI entry point."""
from __future__ import annotations

import sys


def main() -> int:
    from pathlib import Path
    from PySide6 import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication(sys.argv)

    # Standard dialogs (file chooser etc.) follow the system locale: qtbase_<locale>
    # translates Qt's own buttons ("Save"/"Cancel"); without a translation Qt's English
    # default stays. Only affects the non-native Qt dialog, hence DontUseNativeDialog
    # in the main window. Keep a reference on app (no GC).
    app._translator = QtCore.QTranslator(app)
    tpath = QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath)
    if app._translator.load(QtCore.QLocale.system(), "qtbase", "_", tpath):
        app.installTranslator(app._translator)

    from .mainwindow import MainWindow
    icon = Path(__file__).resolve().parent.parent / "app_icon.png"
    if icon.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon)))
    win = MainWindow()
    win.resize(600, 340)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

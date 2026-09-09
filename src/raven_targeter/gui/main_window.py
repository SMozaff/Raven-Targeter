"""Main window entry point.

M0 STUB: this only proves the app can start end-to-end (settings -> logging
-> Qt event loop -> window). The real navigation (Dashboard/Search/Results/
Settings pages) is built in Milestone 4 and will replace `run_app` below.
"""

from __future__ import annotations

import sys

from raven_targeter.config.settings import Settings


def run_app(settings: Settings) -> int:
    """Create the QApplication and show the (currently stub) main window."""
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    app = QApplication.instance() or QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("Raven-Targeter (M0 bootstrap)")
    window.resize(800, 600)
    label = QLabel(
        "Raven-Targeter\n\n"
        f"Targets: {', '.join(settings.targets)}\n"
        f"Lookback: {settings.lookback_days} days\n"
        f"GitHub token configured: {settings.has_github_token}\n\n"
        "Full navigation (Dashboard / Search / Results / Settings) "
        "arrives in Milestone 4."
    )
    label.setContentsMargins(24, 24, 24, 24)
    window.setCentralWidget(label)
    window.show()

    return app.exec()

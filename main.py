"""Desktop entry point: live pit wall lite (sprint S-5; the full UI_DESIGN app comes later).

    python main.py

Setup screen (track, Rule Set, Our Car, seed, Pause on alert, Test mode), then the
live race window.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from pitwall_sim.live.session import LiveSession
from pitwall_sim.track.openf1 import OpenF1Error
from pitwall_sim.ui.pitwall_lite import PitWallWindow
from pitwall_sim.ui.setup_screen import SetupScreen


def main() -> int:
    """Show the setup screen, then run the race."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv)
    setup = SetupScreen()
    if setup.exec() != SetupScreen.DialogCode.Accepted:
        return 0
    try:
        session = LiveSession(setup.choice())
    except OpenF1Error as exc:  # E3 real race moment: no network and nothing cached
        QMessageBox.critical(None, "Real race moment", f"OpenF1 data unavailable: {exc}")
        return 1
    window = PitWallWindow(session)
    window.resize(1480, 900)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())

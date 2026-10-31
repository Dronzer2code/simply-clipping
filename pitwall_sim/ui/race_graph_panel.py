"""Race graph panel on the Reveal tab (Graphify track step 3).

At the chequered flag a :class:`GraphWorker` writes the race graph and dashboard
(``pitwall_sim.graph``) in a background thread; the panel's buttons open them in
the browser once they exist. The worker runs again when the decision costs are in,
so the graph carries them. "Ask the pit wall" answers preset questions from the
race record and, when the graphify CLI is installed, free questions through
``graphify query`` (an :class:`AskWorker`, never on the UI thread). Without graphify
the graph page and the dashboard still work (they are our own pages).

The UI never sees the race state here: the workers get the finished session and
hand back file paths and text (HR-02); nothing is built before the flag.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pitwall_sim.graph.ask import ask, graphify_available, preset_questions
from pitwall_sim.graph.race import OUT_ROOT, graph_session
from pitwall_sim.graph.record import RaceRecord
from pitwall_sim.live.session import LiveSession

PANEL, TEXT, TEXT_DIM, CLIP = "#181B1F", "#E6E8EB", "#8A9099", "#FF4D4F"
__all__ = ["OUT_ROOT", "AskWorker", "GraphWorker", "RaceGraphPanel"]
NO_GRAPHIFY = "Presets work as they are; free questions need graphify (pip install graphifyy)."


class GraphWorker(QThread):
    """Writes the race graph and dashboard of a finished session, off the UI thread."""

    ready = Signal(str, str, str, str, str)
    """(graph.html, dashboard.html, graph.json, race_record.json, status text)"""
    failed = Signal(str)

    def __init__(self, session: LiveSession, out_root: Path = OUT_ROOT,
                 parent: QObject | None = None) -> None:  # fmt: skip
        """Build for ``session`` into ``out_root/<run_id>``."""
        super().__init__(parent)
        self.session = session
        self.out_root = out_root

    def run(self) -> None:
        """Build the graph (seconds at most); report the files or the error."""
        try:
            paths = graph_session(self.session, self.out_root)
        except Exception as exc:  # noqa: BLE001 (show it on the panel, keep the app alive)
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        calls, costed = len(self.session.call_log), len(self.session.costs)
        status = f"Race graph ready: {paths.folder.name}"
        if calls:
            status += f" ({costed} of {calls} call costs in)"
        self.ready.emit(str(paths.graph_html), str(paths.dashboard), str(paths.graph_json),
                        str(paths.record), status)  # fmt: skip


class AskWorker(QThread):
    """Answers one question about the race (``graphify query`` can take seconds)."""

    done = Signal(str)

    def __init__(self, record: Path, graph_json: Path, question: str,
                 parent: QObject | None = None) -> None:  # fmt: skip
        """Answer ``question`` from the race record / graph."""
        super().__init__(parent)
        self.record, self.graph_json, self.question = record, graph_json, question

    def run(self) -> None:
        """Answer (never raises into Qt)."""
        try:
            text = ask(RaceRecord.load(self.record), self.graph_json, self.question)
        except Exception as exc:  # noqa: BLE001 (show it in the answer box)
            text = f"Could not answer: {type(exc).__name__}: {exc}"
        self.done.emit(text)


class RaceGraphPanel(QWidget):
    """Open race graph / dashboard buttons and the "Ask the pit wall" box."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Start disabled ("building..."): :meth:`set_ready` enables the buttons."""
        super().__init__(parent)
        self.setStyleSheet(
            f"QWidget {{ color:{TEXT}; }} QPushButton:disabled {{ color:{TEXT_DIM}; }} "
            f"QPlainTextEdit, QComboBox {{ background:{PANEL}; }}"
        )
        self.paths: dict[str, Path] = {}
        self._ask: AskWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        row = QHBoxLayout()
        self.status = QLabel("Race graph: building after the flag...")
        self.status.setStyleSheet(f"color:{TEXT_DIM};")
        self.open_graph = QPushButton("Open race graph")
        self.open_dashboard = QPushButton("Open race dashboard")
        for button, key in ((self.open_graph, "graph"), (self.open_dashboard, "dashboard")):
            button.setEnabled(False)
            button.clicked.connect(lambda _=False, k=key: self.open(k))
            row.addWidget(button)
        row.addWidget(self.status, 1)
        layout.addLayout(row)
        ask_row = QHBoxLayout()
        ask_row.addWidget(QLabel("Ask the pit wall:"))
        self.question = QComboBox()
        self.question.setEditable(True)
        self.question.setMinimumWidth(360)
        line = self.question.lineEdit()
        if line is not None:
            line.setPlaceholderText("Who did I race most?")
            line.returnPressed.connect(self.ask)
        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self.ask)
        for w in (self.question, self.ask_button):
            w.setEnabled(False)
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.ask_button)
        layout.addLayout(ask_row)
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMaximumHeight(130)
        hint = "Answers come from the race graph."
        self.answer.setPlaceholderText(hint if graphify_available() else f"{hint} {NO_GRAPHIFY}")
        layout.addWidget(self.answer)

    def set_ready(self, graph_html: str, dashboard_html: str, graph_json: str, record: str,
                  status: str) -> None:  # fmt: skip
        """Enable the buttons and the questions: the graph exists."""
        first = not self.paths
        self.paths = {"graph": Path(graph_html), "dashboard": Path(dashboard_html),
                      "json": Path(graph_json), "record": Path(record)}  # fmt: skip
        self.status.setText(status)
        self.status.setStyleSheet(f"color:{TEXT_DIM};")
        for w in (self.open_graph, self.open_dashboard, self.question, self.ask_button):
            w.setEnabled(True)
        if first:
            try:
                presets = preset_questions(RaceRecord.load(self.paths["record"]))
            except (OSError, ValueError, KeyError):
                presets = []
            self.question.addItems(presets)
            self.question.setCurrentIndex(-1)

    def set_failed(self, message: str) -> None:
        """Say why the graph could not be built (the rest of the Reveal still works)."""
        self.status.setText(f"Race graph failed: {message}")
        self.status.setStyleSheet(f"color:{CLIP};")

    def open(self, key: str) -> bool:
        """Open the race graph or the dashboard in the browser."""
        path = self.paths.get(key)
        return path is not None and QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def ask(self) -> None:
        """Answer the question in the box, in the background."""
        text = self.question.currentText().strip()
        if not text or not self.paths or (self._ask is not None and self._ask.isRunning()):
            return
        self.answer.setPlainText("Thinking...")
        self._ask = AskWorker(self.paths["record"], self.paths["json"], text, self)
        self._ask.done.connect(self.answer.setPlainText)
        self._ask.start()

    def stop(self) -> None:
        """Wait for a running question (the dialog is closing)."""
        if self._ask is not None:
            self._ask.wait(35000)

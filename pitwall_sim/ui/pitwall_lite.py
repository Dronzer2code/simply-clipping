"""Live pit wall lite (sprint S-5 + A-3): the race engineer's window.

Reads only :class:`~pitwall_sim.live.session.Frame` (an EngineerView, the
alerts from the provider, the radio log; plus the Rivals' TRUE battery when the
setup chose Test mode, labelled as such). Panels: track map, timing tower, Our
Car status, Rival radar (car ahead / behind), battery trace, alert feed with
call options (F1 / F2 / F3 answer the newest alert), radio log, clock
(PAUSE / 1x / 4x / 16x) and command buttons. The race runs in :class:`SimThread`;
every tick is simulated (HR-08): if the machine falls behind, the sim clock lags.
Colours: docs/spec/UI_DESIGN.md COLOURS.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsItem,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pitwall_sim.debrief.scorer import engineer_score
from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.engineer.records import CallCost
from pitwall_sim.live.reveal import OFF_MJ, RevealData
from pitwall_sim.live.session import Frame, LiveSession
from pitwall_sim.observe.alerts import Alert
from pitwall_sim.radio import stt
from pitwall_sim.radio.voice import DriverVoice, available
from pitwall_sim.ui.telemetry_plot import TelemetryPlot

#: docs/spec/UI_DESIGN.md COLOURS.
BG, PANEL, TEXT, TEXT_DIM = "#101214", "#181B1F", "#E6E8EB", "#8A9099"
OUR_CAR, DEPLOY, DEFEND, CLIP = "#3D8BFF", "#2ECC71", "#F5A623", "#FF4D4F"
HARVEST, LIFT = "#00B8D9", "#B37FEB"
BEHIND_WINDOW_S = 2.0
"""Wall seconds over which the achieved sim speed is measured (H6)."""
BEHIND_SHARE = 0.85
"""Below this share of the chosen speed the top bar shows SIM BEHIND (HR-08: no skipped steps)."""
AERO_LABELS = {"STRAIGHT_MODE": "Straight Mode", "CORNER_MODE": "Corner Mode"}
"""2026 active aero terms (never DRS)."""
#: Track status banner text (UI_DESIGN UI STATES: full-width banner in ``defend``).
TRACK_STATUS_TEXT = {
    "VSC": "VIRTUAL SAFETY CAR - no overtaking, delta speed",
    "SC": "SAFETY CAR - no overtaking, field bunching",
    "SC_IN_THIS_LAP": "SAFETY CAR IN THIS LAP - restart at the line",
}
ALERT_COLOURS = {"ATTACK": DEPLOY, "DEFEND": DEFEND, "REPASS_RISK": CLIP,
                 "CLOSING_SPEED_RISK": CLIP}  # fmt: skip
STATE_COLOURS = {"DEPLOY": DEPLOY, "CLIP": CLIP, "HARVEST": HARVEST, "LIFT": LIFT,
                 "CRUISE": TEXT_DIM}  # fmt: skip
SPEEDS = {"PAUSE": 0.0, "1x": 1.0, "4x": 4.0, "16x": 16.0}
EMIT_HZ = 30.0
TABLE_EVERY_S = 0.25
TRACE_WINDOW_S = 300.0
FRESH_FRAME_S = 1.5
T = CommandType


class SimThread(QThread):
    """Advances the session by wall time x speed; emits frames for the UI."""

    frame_ready = Signal(object)

    def __init__(self, session: LiveSession, parent: QObject | None = None) -> None:
        """Start paused at 1x."""
        super().__init__(parent)
        self.session = session
        self.speed = 0.0
        self._stop = False
        self.achieved = 0.0
        self._target = 0.0
        """Sim time the chosen speed has asked for so far (whole ticks overshoot it a little)."""
        """Sim seconds per wall second over the last ``BEHIND_WINDOW_S`` (H6 sim behind)."""
        self._window: deque[tuple[float, float]] = deque()

    def stop(self) -> None:
        """Ask the loop to end."""
        self._stop = True

    def run(self) -> None:
        """Loop: advance, emit at ``EMIT_HZ``."""
        last = time.perf_counter()
        last_emit = 0.0
        while not self._stop:
            now = time.perf_counter()
            dt, last = now - last, now
            if self.speed > 0.0:
                # Advance only what the speed owes: the engine runs whole ticks, so a fast
                # loop would otherwise run ahead of the chosen speed. At most 1 s of sim per
                # step keeps the UI live; if the machine is slow the sim lags (HR-08) and the
                # debt is capped, it is never made up by skipping steps.
                self._target += dt * self.speed
                owed = self._target - self.session.t_s
                if owed > 0.0:
                    self.session.advance(min(owed, 1.0))
                self._target = min(self._target, self.session.t_s + 1.0)
            else:
                self._target = self.session.t_s
            self._window.append((now, self.session.t_s))
            while now - self._window[0][0] > BEHIND_WINDOW_S:
                self._window.popleft()
            span = now - self._window[0][0]
            self.achieved = (self.session.t_s - self._window[0][1]) / span if span > 0.5 else 0.0
            if now - last_emit >= 1.0 / EMIT_HZ:
                self.frame_ready.emit(self.session.frame())
                last_emit = now
            self.msleep(4)


def _label(text: str = "", size: int = 9, bold: bool = False, color: str = TEXT) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSize(size)
    font.setBold(bold)
    label.setFont(font)
    label.setStyleSheet(f"color:{color};")
    return label


#: Radar states in plain words (pitch UI: viewers do not know DEPLOY / CLIP).
STATE_WORDS = {"DEPLOY": "deploying", "CLIP": "clipping", "HARVEST": "harvesting",
               "LIFT": "lifting", "CRUISE": "cruising"}  # fmt: skip
MISSED_SHOW_S = 6.0
"""Wall seconds an unanswered alert stays on screen, greyed (at 16x it lives 0.5 s)."""
MAX_CARDS = 4


def _sure(confidence: float) -> str:
    """Confidence as a word plus percent: 'high (82%)'."""
    word = "high" if confidence >= 0.7 else "medium" if confidence >= 0.4 else "low"
    return f"{word} ({confidence:.0%})"


def _panel(title: str, inner: QWidget | None = None, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Build a titled panel; ``hint`` is one plain-language line for people new to F1."""
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:6px; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 6, 8, 6)
    head = _label(title.upper(), 10, True, TEXT)
    layout.addWidget(head)
    if hint:
        layout.addWidget(_label(hint, 9, False, TEXT_DIM))
    if inner is not None:
        layout.addWidget(inner)
    return frame, layout


class AlertCard(QFrame):
    """One alert: headline, confidence, expiry bar, option buttons, evidence on click."""

    def __init__(self, window: PitWallWindow, alert: Alert, headline: str) -> None:
        """Build the card for ``alert``."""
        super().__init__()
        self.alert = alert
        self.ended_wall: float | None = None
        colour = ALERT_COLOURS[alert.type]
        dim = alert.confidence < window.low_confidence
        text_colour = TEXT_DIM if dim else TEXT
        self.setStyleSheet(
            f"QFrame {{ background:{BG}; border-left:4px solid {colour}; }}"
            f" QLabel {{ border:none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        top = QHBoxLayout()
        top.addWidget(_label(alert.type.replace("_", " "), 9, True, TEXT_DIM if dim else colour))
        top.addStretch()
        self.status = _label(f"sure: {_sure(alert.confidence)}", 9, color=TEXT_DIM)
        top.addWidget(self.status)
        layout.addLayout(top)
        layout.addWidget(_label(headline, 10, False, text_colour))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setRange(0, 1000)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background:{PANEL}; border:none; }}"
            f" QProgressBar::chunk {{ background:{colour}; }}"
        )
        layout.addWidget(self.bar)
        ev = alert.evidence
        bits = [f"why: {ev.branch}"] if ev.branch else []
        bits.append(f"our {ev.our_mj:.2f} MJ")
        if ev.need_mj is not None:
            bits.append(f"straight needs {ev.need_mj:.2f} MJ")
        if ev.rival_mj is not None:
            basis = f" ({ev.rival_basis})" if ev.rival_basis else ""
            bits.append(f"{alert.rival} est {ev.rival_mj:.2f} MJ{basis}")
        if ev.detection_share is not None:
            bits.append(f"clip seen in {ev.detection_share:.0%} of feed samples")
        truth = window.truth_mj.get(alert.rival) if window.truth_mj else None
        if truth is not None:
            bits.append(f"TRUE {truth:.2f} MJ (test mode)")
        if ev.dv_kmh is not None:
            bits.append(f"dv {ev.dv_kmh:+.0f} km/h")
        if ev.gap_s is not None:
            bits.append(f"gap {ev.gap_s:+.2f} s")
        if ev.rival_state:
            bits.append(f"radar {ev.rival_state}")
        if ev.last_clip_s_m is not None:
            bits.append(f"last clip at {ev.last_clip_s_m:.0f} m")
        self.evidence = _label("  |  ".join(bits), 8, False, TEXT_DIM)
        self.evidence.setWordWrap(True)
        self.evidence.setVisible(False)
        layout.addWidget(self.evidence)
        row = QHBoxLayout()
        self.buttons: dict[int, QPushButton] = {}
        for option in window.frame_options.get(alert.alert_id, []):
            button = QPushButton(f"F{option.key}  {option.label}")
            button.setStyleSheet(f"background:{PANEL}; color:{TEXT}; padding:3px 6px;")
            button.clicked.connect(
                lambda _=False, key=option.key: window.answer(alert.alert_id, key)
            )
            self.buttons[option.key] = button
            row.addWidget(button)
        layout.addLayout(row)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 (Qt)
        """Show / hide the evidence."""
        self.evidence.setVisible(not self.evidence.isVisible())
        super().mousePressEvent(event)

    def set_remaining(self, t_s: float) -> None:
        """Update the expiry countdown."""
        a = self.alert
        span = max(a.expires_t - a.created_t, 1e-6)
        self.bar.setValue(int(1000 * max(a.expires_t - t_s, 0.0) / span))

    def mark_missed(self) -> None:
        """Grey out an alert that ended unanswered; it stays a moment (16x is fast)."""
        self.ended_wall = time.perf_counter()
        self.status.setText("missed - no call made")
        self.bar.setValue(0)
        for button in self.buttons.values():
            button.setEnabled(False)
        self.setStyleSheet(
            f"QFrame {{ background:{BG}; border-left:4px solid {TEXT_DIM}; }}"
            f" QLabel {{ border:none; color:{TEXT_DIM}; }}"
        )


class SummaryDialog(QDialog):
    """End-of-race call summary (A-4): every alert, the call, what followed."""

    def __init__(self, session: LiveSession, parent: QWidget | None = None) -> None:
        """Fill the table from the session's call records."""
        super().__init__(parent)
        summary = session.summary()
        test = summary.correct is not None
        self.setWindowTitle("Call summary")
        self.setStyleSheet(f"background:{BG}; color:{TEXT};")
        heads = ["time s", "lap", "type", "rival", "conf", "call", "next 2 laps"]
        if test:
            heads += ["true diff MJ (test)", "alert right? (test)"]
        self.table = QTableWidget(len(summary.records), len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(f"background:{PANEL}; gridline-color:{BG};")
        codes = session.drivers
        for row, r in enumerate(summary.records):
            a = r.alert
            cells = [f"{r.t_s:.0f}", str(a.lap), a.type.replace("_", " "),
                     codes[a.rival]["code"], f"{a.confidence:.2f}", r.option,
                     r.outcome or "(2 laps not run yet)"]  # fmt: skip
            if test:
                cells += ["-" if r.true_diff_mj is None else f"{r.true_diff_mj:+.2f}",
                          "-" if r.correct is None else ("yes" if r.correct else "NO")]  # fmt: skip
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 2:
                    item.setForeground(QColor(ALERT_COLOURS[a.type]))
                if test and col == len(cells) - 1 and text == "NO":
                    item.setForeground(QColor(CLIP))
                self.table.setItem(row, col, item)
        totals = (
            f"Alerts {summary.alerts}   calls made {summary.calls_made}   "
            f"successful attacks {summary.successful_attacks}   "
            f"successful defends {summary.successful_defends}"
        )
        if test:
            totals += f"   alerts right per Ground Truth {summary.correct}/{summary.judged} (test)"
        calls = QWidget()
        calls_layout = QVBoxLayout(calls)
        calls_layout.addWidget(_label(totals, 10))
        calls_layout.addWidget(self.table)
        self.tabs = QTabWidget()
        self.tabs.addTab(calls, "Calls")
        reveal = session.reveal()
        self.reveal_tab: RevealTab | None = None
        self.cost_worker: CostWorker | None = None
        if reveal is not None:  # only after the flag (truth allowed then)
            self.reveal_tab = RevealTab(reveal, session.drivers)
            self.tabs.addTab(self.reveal_tab, "Reveal")
            self.reveal_tab.enable_score(  # E2: engineer score from the decision costs
                session.engine.app.debrief.score_scale_s, lambda: list(session.costs.values())
            )
            if session.call_log:  # H1: decision costs in the background
                self.cost_worker = CostWorker(session, self)
                self.cost_worker.done.connect(self.reveal_tab.set_cost)
                self.cost_worker.start()
        layout = QVBoxLayout(self)
        layout.addWidget(_label("CALL SUMMARY", 11, True))
        layout.addWidget(self.tabs)
        self.resize(1300, 820)
        if self.reveal_tab is not None:
            self.tabs.setCurrentWidget(self.reveal_tab)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 (Qt)
        """Stop the cost worker."""
        if self.cost_worker is not None:
            self.cost_worker.stop()
            self.cost_worker.wait(30000)
        super().closeEvent(event)


class CostWorker(QThread):
    """Computes every call's decision cost after the flag (H1), one call at a time."""

    done = Signal(int, str)
    """(call index, text)"""

    def __init__(self, session: LiveSession, parent: QObject | None = None) -> None:
        """Work through ``session.call_log``."""
        super().__init__(parent)
        self.session = session
        self._stop = False

    def stop(self) -> None:
        """Stop after the call in progress."""
        self._stop = True

    def run(self) -> None:
        """Compute the costs in call order."""
        for index in range(len(self.session.call_log)):
            if self._stop:
                return
            try:
                text = self.session.compute_cost(index)
            except Exception as exc:  # noqa: BLE001 (show it, keep going)
                text = f"cost failed: {exc}"
            self.done.emit(index, text)


class RevealTab(QWidget):
    """Post-race Reveal (H1): Radar Estimate vs TRUE battery, and every call in context."""

    #: Half-width of the confidence band at confidence 0 (display convention, MJ).
    BAND_MJ = 2.0

    def __init__(self, reveal: RevealData, drivers: dict[str, dict[str, str]]) -> None:
        """Build the plots for the Rivals Our Car raced most, then the calls table."""
        super().__init__()
        layout = QVBoxLayout(self)
        n_calls = len(reveal.calls)
        layout.addWidget(_label(
            f"Our radar was off by {reveal.radar_mae_mj:.2f} MJ on average "
            "(the battery holds 4 MJ)."
            f"     Calls made on a guess off by more than {OFF_MJ:.0f} MJ: "
            f"{reveal.calls_off} of {n_calls}", 11, True,
        ))  # fmt: skip
        layout.addWidget(_label(
            "Solid: the Rival's TRUE battery (revealed after the flag). Dashed: what the "
            "Radar estimated, with its confidence band. Vertical lines: your calls.", 9,
            color=TEXT_DIM,
        ))  # fmt: skip
        plots = QHBoxLayout()
        self.plots: list[pg.PlotWidget] = []
        call_laps = []
        for c in reveal.calls:
            series = reveal.rivals[0] if reveal.rivals else None
            lap = float(np.interp(c.record.t_s, series.t_s, series.lap)) if series else 0.0
            call_laps.append((lap, c))
        for s in reveal.rivals:
            plot = pg.PlotWidget()
            code = drivers[s.driver_id]["code"]
            plot.setTitle(f"{code}  (raced {s.battle_s:.0f} s)", color=TEXT)
            plot.setLabel("bottom", "lap")
            plot.setLabel("left", "MJ")
            plot.setYRange(-0.2, 4.2)
            band = self.BAND_MJ * (1.0 - s.confidence)
            low = plot.plot(s.lap, np.clip(s.estimate_mj - band, 0.0, 4.0), pen=pg.mkPen(None))
            high = plot.plot(s.lap, np.clip(s.estimate_mj + band, 0.0, 4.0), pen=pg.mkPen(None))
            fill = pg.FillBetweenItem(low, high, brush=pg.mkBrush(245, 166, 35, 50))
            plot.addItem(fill)
            plot.plot(s.lap, s.estimate_mj,
                      pen=pg.mkPen(DEFEND, width=2, style=Qt.PenStyle.DashLine))  # fmt: skip
            plot.plot(s.lap, s.truth_mj, pen=pg.mkPen(CLIP, width=2))
            for lap, c in call_laps:
                mine = c.rival == s.driver_id
                pen = pg.mkPen(OUR_CAR if mine else TEXT_DIM, width=2 if mine else 1)
                plot.addItem(pg.InfiniteLine(pos=lap, angle=90, pen=pen))
            self.plots.append(plot)
            plots.addWidget(plot)
        layout.addLayout(plots, 1)
        self.progress = QProgressBar()  # decision costs (H1), filled by the CostWorker
        self.progress.setRange(0, max(n_calls, 1))
        self.progress.setValue(sum(c.cost != "computing…" for c in reveal.calls))
        self.progress.setFormat("decision costs: %v / %m calls (paired forks, 5 seeds each)")
        self.progress.setVisible(n_calls > 0)
        layout.addWidget(self.progress)
        heads = ["time s", "lap", "call", "about", "estimate MJ", "TRUE MJ", "error MJ",
                 "position / gap before", f"{2} laps later", "cost"]  # fmt: skip
        self.table = QTableWidget(n_calls, len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(heads) - 1, QHeaderView.ResizeMode.Stretch)  # the cost
        self.table.setStyleSheet(f"background:{PANEL}; gridline-color:{BG};")

        def place(position: int | None, gap: float | None) -> str:
            if position is None:
                return "-"
            return f"P{position}" + ("" if gap is None else f"  +{gap:.2f} s")

        def mj(x: float | None) -> str:
            return "-" if x is None else f"{x:.2f}"

        for row, c in enumerate(reveal.calls):
            error = c.error_mj
            cells = [
                f"{c.record.t_s:.0f}", str(c.record.lap), c.record.option_label,
                drivers[c.rival]["code"] if c.rival else "-", mj(c.estimate_mj), mj(c.truth_mj),
                "-" if error is None else f"{error:+.2f}",
                place(c.position_before, c.gap_before_s), place(c.position_after, c.gap_after_s),
                c.cost,
            ]  # fmt: skip
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 6 and error is not None and abs(error) > OFF_MJ:
                    item.setForeground(QColor(CLIP))
                if col == len(cells) - 1:
                    item.setForeground(QColor(TEXT_DIM))
                self.table.setItem(row, col, item)
        layout.addWidget(self.table, 1)

    def set_cost(self, row: int, text: str) -> None:
        """Show one call's cost (from the CostWorker)."""
        item = QTableWidgetItem(text)
        good = text == "best call"
        item.setForeground(QColor(DEPLOY if good else (CLIP if "+" in text else TEXT_DIM)))
        self.table.setItem(row, self.table.columnCount() - 1, item)
        self.progress.setValue(self.progress.value() + 1)
        self._update_score()

    def enable_score(self, scale_s: object, costs: Callable[[], list[CallCost]]) -> None:
        """Show the engineer score (E2) once every call's cost is in."""
        self.score_scale_s = scale_s
        self._score_costs = costs
        self.score_label = _label("", 11, True)
        self.score_line = _label("", 9, color=TEXT_DIM)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        at = layout.indexOf(self.progress) + 1
        layout.insertWidget(at, self.score_label)
        layout.insertWidget(at + 1, self.score_line)
        self._update_score()

    def _update_score(self) -> None:
        costs = getattr(self, "_score_costs", None)
        if costs is None:
            return
        n_calls, done = self.table.rowCount(), self.progress.value()
        scale = self.score_scale_s
        if n_calls == 0:
            self.score_label.setText("Engineer score: - (no calls made)")
            self.score_line.setText("make calls in the race to be scored (TRD DEBRIEF AND SCORING)")
            return
        if not isinstance(scale, (int, float)):
            self.score_label.setText(f"Engineer score: - (debrief.score_scale_s is {scale})")
            return
        if done < n_calls:
            self.score_label.setText(f"Engineer score: computing... ({done} / {n_calls} costs)")
            self.score_line.setText("")
            return
        got = costs()
        score = engineer_score(got, float(scale))
        colour = DEPLOY if score.score >= 80 else (DEFEND if score.score >= 50 else CLIP)
        self.score_label.setText(f"Engineer score: {score.score:.0f} / 100")
        self.score_label.setStyleSheet(f"color:{colour};")
        failed = n_calls - len(got)
        self.score_line.setText(score.breakdown() + (f"   ({failed} cost(s) failed, not scored)"
                                                     if failed > 0 else ""))  # fmt: skip


class PitWallWindow(QMainWindow):
    """The live race window."""

    def __init__(self, session: LiveSession, start_speed: str = "1x") -> None:
        """Build the panels and start the sim thread."""
        super().__init__()
        self.session = session
        self.drivers = session.drivers
        self.our = session.setup.our_driver_id
        self.test_mode = session.setup.test_mode
        self.low_confidence = session.engine.app.alerts.low_confidence
        self.frame_options: dict[str, Any] = {}
        self.truth_mj: dict[str, float] | None = None
        self.selected_rival: str | None = None
        self.frame_times: list[float] = []
        self._last_table = 0.0
        self._cards: dict[str, AlertCard] = {}
        self._radio_count = 0
        self._last_frame: Frame | None = None
        self._summary_shown = False
        self.summary_dialog: SummaryDialog | None = None
        self._history: deque[tuple[float, float, dict[str, float], dict[str, float]]] = deque()
        setup = session.setup
        title = (f"We Are Racing, Not Testing - {setup.track_id} {setup.rule_set_id} seed "
                 f"{setup.seed} - Our Car {self.drivers[self.our]['code']}")  # fmt: skip
        if self.test_mode:
            title += "  [TEST MODE: Rivals' TRUE battery shown]"
        self.setWindowTitle(title)
        self.setStyleSheet(f"QMainWindow, QWidget {{ background:{BG}; color:{TEXT}; }}")
        pg.setConfigOptions(antialias=True, background=PANEL, foreground=TEXT)

        self._build_map()
        self._build_tower()
        self._build_status()
        self._build_radar()
        self._build_strategy()
        self._build_trace()
        self._build_telemetry()
        self._build_alerts()
        self._build_radio()
        self._build_controls()

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.map_panel)
        left.addWidget(self.trace_tabs)  # battery trace + telemetry (H6)
        left.setSizes([470, 290])  # H6: room for the three telemetry plots
        middle = QWidget()
        mid = QVBoxLayout(middle)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(self.status_panel)
        mid.addWidget(self.radar_panel)
        mid.addWidget(self.strategy_panel)
        mid.addWidget(self.alert_panel, 1)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.tower_panel)
        right.addWidget(self.radio_panel)
        right.setSizes([460, 280])
        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(left)
        body.addWidget(middle)
        body.addWidget(right)
        body.setSizes([620, 380, 380])
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.controls)
        layout.addWidget(self.track_banner)  # SC / VSC, full width under the top bar (H4)
        layout.addWidget(body, 1)
        layout.addWidget(self.commands)
        self.setCentralWidget(root)
        for key, number in ((Qt.Key.Key_F1, 1), (Qt.Key.Key_F2, 2), (Qt.Key.Key_F3, 3)):
            QShortcut(QKeySequence(key), self, lambda n=number: self.answer_newest(n))
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_pause)

        self.thread_ = SimThread(session, self)
        self.thread_.frame_ready.connect(self.on_frame)
        self.thread_.start()
        self.set_speed(start_speed)
        # Draw the first frame right away (before the thread's first emit).
        QTimer.singleShot(0, lambda: self.on_frame(session.frame()))

    # ------------------------------------------------------------------ #
    # Panels
    # ------------------------------------------------------------------ #
    def _build_map(self) -> None:
        self.map = pg.PlotWidget()
        self.map.setAspectLocked(True)
        self.map.hideAxis("left")
        self.map.hideAxis("bottom")
        self.map.setMouseEnabled(False, False)
        x, y = self.session.outline
        step = max(x.size // 600, 1)
        outline = self.map.plot(np.append(x[::step], x[0]), np.append(y[::step], y[0]),
                                pen=pg.mkPen(TEXT_DIM, width=5))  # fmt: skip
        outline.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.dots = pg.ScatterPlotItem(size=12, pen=pg.mkPen(BG, width=1))
        self.map.addItem(self.dots)
        self.brushes = {d: pg.mkBrush(v["color"]) for d, v in self.drivers.items()}
        font = QFont()
        font.setPointSize(7)
        self.labels: dict[str, pg.TextItem] = {}
        for d, v in self.drivers.items():
            label = pg.TextItem(v["code"], color=OUR_CAR if d == self.our else TEXT,
                                anchor=(0.5, 1.3))  # fmt: skip
            label.setFont(font)
            self.map.addItem(label)
            self.labels[d] = label
        self.map_panel, _ = _panel("Track - Suzuka", self.map)

    def _build_tower(self) -> None:
        self.tower = QTableWidget(len(self.drivers), 6)
        self.tower.setHorizontalHeaderLabels(["Pos", "Driver", "Gap", "Ahead", "Tyre", "Stops"])
        self.tower.verticalHeader().setVisible(False)
        self.tower.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tower.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tower.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tower.setStyleSheet(f"background:{PANEL}; gridline-color:{BG};")
        self.tower.cellClicked.connect(self._tower_clicked)
        self._row_driver: list[str] = []
        self.tower_panel, _ = _panel("Race order", self.tower)

    def _build_status(self) -> None:
        self.status_panel, layout = _panel("Our car")
        self.battery_caption = _label("BATTERY", 9, True, TEXT_DIM)
        layout.addWidget(self.battery_caption)
        self.battery = _label("-", 24, True, DEPLOY)
        self.battery_bar = QProgressBar()
        self.battery_bar.setRange(0, 400)
        self.battery_bar.setTextVisible(False)
        self.battery_bar.setFixedHeight(8)
        self.battery_bar.setStyleSheet(f"QProgressBar::chunk {{ background:{DEPLOY}; }}")
        self.status_line = _label("", 9)
        layout.addWidget(self.battery)
        layout.addWidget(self.battery_bar)
        layout.addWidget(self.status_line)
        self.weather_line = _label("", 9, False, TEXT_DIM)  # H6: public weather and forecast
        layout.addWidget(self.weather_line)

    def _build_radar(self) -> None:
        self.radar_panel, layout = _panel(
            "Rival battery radar",
        )
        grid = QGridLayout()
        heads = ["", "car", "gap (s)", "battery (estimate)", "how sure", "doing now"]
        if self.test_mode:
            heads.append("TRUE MJ (test)")
        for c, h in enumerate(heads):
            grid.addWidget(_label(h, 8, True, CLIP if "TRUE" in h else TEXT_DIM), 0, c)
        self.radar_cells: dict[str, list[QLabel]] = {}
        for r, which in enumerate(("ahead", "behind"), start=1):
            cells = [_label(which, 9, True, TEXT_DIM)] + [_label("-", 10) for _ in heads[1:]]
            for c, cell in enumerate(cells):
                grid.addWidget(cell, r, c)
            self.radar_cells[which] = cells
        layout.addLayout(grid)

    def _build_trace(self) -> None:
        self.trace = pg.PlotWidget()
        self.trace.setYRange(0.0, 4.2)
        self.trace.setLabel("left", "MJ")
        self.trace.setLabel("bottom", "race time", units="s")
        self.trace.setMouseEnabled(False, False)
        self.trace.addLegend(offset=(-5, -5))  # bottom right: off the lines at the top
        self.our_curve = self.trace.plot(pen=pg.mkPen(OUR_CAR, width=2), name="our battery")
        self.rival_curve = self.trace.plot(
            pen=pg.mkPen(DEFEND, width=2, style=Qt.PenStyle.DashLine),
            name="rival estimate",
            connect="finite",  # gaps where the estimate is unknown
        )
        self.truth_curve = self.trace.plot(
            pen=pg.mkPen(CLIP, width=1, style=Qt.PenStyle.DotLine),
            name="rival TRUE (test mode)" if self.test_mode else None,
        )
        self.trace_panel, layout = _panel("Battery", self.trace)
        self.trace_title = _label("", 8, color=TEXT_DIM)
        layout.insertWidget(1, self.trace_title)

    def _build_telemetry(self) -> None:
        """H6: Our Car's speed / throttle / battery vs lap distance, previous-lap ghost."""
        self.telemetry = TelemetryPlot(float(self.session.engine.trk.length_m))
        self.telemetry_panel = QFrame()  # no panel header: the widget has its own title line
        self.telemetry_panel.setStyleSheet(f"QFrame {{ background:{PANEL}; border-radius:4px; }}")
        box = QVBoxLayout(self.telemetry_panel)
        box.setContentsMargins(6, 4, 6, 4)
        box.addWidget(self.telemetry)
        self.trace_tabs = QTabWidget()
        self.trace_tabs.addTab(self.trace_panel, "Battery")
        self.trace_tabs.addTab(self.telemetry_panel, "Telemetry")
        self.trace_tabs.currentChanged.connect(lambda _: self.telemetry.redraw(force=True))

    def _build_alerts(self) -> None:
        self.alert_box = QWidget()
        self.alert_layout = QVBoxLayout(self.alert_box)
        self.alert_layout.setContentsMargins(0, 0, 0, 0)
        self.alert_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.alert_box)
        self.alert_panel, layout = _panel("Alerts", scroll)
        self.alert_empty = _label(
            "No alert right now.", 10, False, TEXT_DIM,
        )  # fmt: skip
        self.alert_empty.setWordWrap(True)
        layout.insertWidget(1, self.alert_empty)
        self.pause_banner = _label("PAUSED ON ALERT - answer it, or press Resume", 10, True, DEFEND)
        self.track_banner = _label("", 12, True, BG)  # SC / VSC (H4)
        self.track_banner.setStyleSheet(f"background:{DEFEND}; color:{BG}; padding:4px;")
        self.track_banner.setVisible(False)
        self.pause_banner.setVisible(False)
        layout.insertWidget(1, self.pause_banner)

    def _build_strategy(self) -> None:
        """Strategy panel (H5): pit plans from Radar Estimates and public tyres only."""
        self.strategy_panel, layout = _panel(
            "Pit stop strategy",
        )
        top = QHBoxLayout()
        self.strategy_note = _label("waiting for the first lap", 8, False, TEXT_DIM)
        top.addWidget(self.strategy_note, 1)  # refreshes itself every lap (no button)
        layout.addLayout(top)
        self.strategy_table = QTableWidget(5, 4)
        self.strategy_table.setHorizontalHeaderLabels(
            ["plan", "tyre", "expected place", "vs car ahead"]
        )
        self.strategy_table.verticalHeader().setVisible(False)
        self.strategy_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.strategy_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.strategy_table.setStyleSheet(f"background:{PANEL}; gridline-color:{BG};")
        self.strategy_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strategy_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rows_h = 5 * self.strategy_table.verticalHeader().defaultSectionSize()
        head_h = self.strategy_table.horizontalHeader().sizeHint().height()
        self.strategy_table.setFixedHeight(rows_h + head_h + 4)  # all 5 plans, no scroll bar
        layout.addWidget(self.strategy_table)
        self._strategy_shown: object = None

    def _draw_strategy(self, frame: Frame) -> None:
        plans = frame.view.strategy
        busy = self.session.strategy_busy
        lap = self.session.strategy_lap
        first = "working out pit options (first result in about 30 s)"
        note = first if busy and plans is None else (
            f"from lap {lap}; green = best plan" + ("  (updating)" if busy else "")
            if plans is not None else "starts after the first lap")  # fmt: skip
        self.strategy_note.setText(note)
        if plans is None or plans is self._strategy_shown:
            return
        self._strategy_shown = plans
        rows = [p for p in plans if p.plan == "STAY_OUT"]
        for timing in ("BOX_NOW", "BOX_+1", "BOX_+2", "BOX_+3"):
            options = [p for p in plans if p.plan == timing]
            if options:
                rows.append(min(options, key=lambda p: p.expected_position))
        best = min(rows, key=lambda p: p.expected_position) if rows else None
        ahead = rows[0].car_ahead if rows else None
        code = self.drivers[ahead]["code"] if ahead in self.drivers else "car ahead"
        self.strategy_table.setHorizontalHeaderItem(3, QTableWidgetItem(f"vs {code} (s)"))
        for r, p in enumerate(rows[:5]):
            g = p.gain_vs_ahead_s
            gain = "-" if g is None else f"{g:+.1f} " + ("undercut" if g > 0 else "overcut")
            cells = [p.plan.replace("_", " "), (p.compound or "-").title(),
                     f"P{p.expected_position:.1f}", gain]  # fmt: skip
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(DEPLOY if p is best else TEXT))
                self.strategy_table.setItem(r, c, item)

    def _build_radio(self) -> None:
        self.radio_list = QListWidget()
        self.radio_list.setStyleSheet(f"background:{PANEL};")
        self.radio_input = QLineEdit()  # H2: talk to the driver (keyword parser, offline)
        self.radio_input.setPlaceholderText(
            "Radio: e.g. save this lap, attack into T1 next lap  (Enter to send)"
        )
        self.radio_input.setStyleSheet(f"background:{BG}; border:1px solid {TEXT_DIM};")
        self.radio_input.returnPressed.connect(self.send_radio)
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.radio_list, 1)
        col.addWidget(self.radio_input)
        col.addWidget(self._build_voice_input())
        self.radio_panel, _ = _panel("Team radio", box)

    def _build_voice_input(self) -> QWidget:
        """H2: push-to-talk (local speech-to-text) and which path understood the message."""
        cfg = self.session.engine.app.voice_input
        ok, why = stt.status() if cfg.enabled else (False, "Voice input is off in app.yaml")
        self.talk_key = cfg.key
        self.talk_button = QPushButton(f"Hold to talk  [{cfg.key}]")
        self.talk_button.setEnabled(ok)
        self.talk_button.setToolTip(why)
        self.radio_via = _label("", 8, True, TEXT_DIM)
        self._radio_via_shown = ""
        self.radio_via.setToolTip("Which path understood the last message: LLM, keyword parser")
        self.ptt: stt.PushToTalk | None = None
        if ok:
            model_dir = Path(cfg.model_dir)
            if not model_dir.is_absolute():
                model_dir = Path(self.session.config_dir).resolve().parent / model_dir
            names = [n for c in self.session.engine.track.corners for n in (c.name, *c.aliases)]
            prompt = stt.RADIO_WORDS + "Corners: " + ", ".join(names) + "."
            self.voice_bridge = VoiceBridge()
            self.voice_bridge.text.connect(self.voice_text)
            self.voice_bridge.error.connect(self.voice_error)
            self.ptt = stt.PushToTalk(
                stt.WhisperTranscriber(cfg.model, model_dir, cfg.compute_type, prompt),
                stt.SoundDeviceRecorder(cfg.max_record_s),
                self.voice_bridge.text.emit, self.voice_bridge.error.emit,
            )  # fmt: skip
            self.talk_button.pressed.connect(self.talk_down)
            self.talk_button.released.connect(self.talk_up)
            self.radio_input.installEventFilter(self)  # the key also works while typing
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.talk_button)
        line.addWidget(self.radio_via, 1)
        return row

    def talk_down(self) -> None:
        """Start recording the engineer (push-to-talk held)."""
        if self.ptt is not None and self.ptt.press():
            self.ptt.preload()
            self.talk_button.setText("Listening...")

    def talk_up(self) -> None:
        """Stop recording; the words are transcribed in the background."""
        if self.ptt is not None and self.ptt.recording:
            self.ptt.release()
            self.talk_button.setText("Transcribing...")

    def voice_text(self, text: str) -> None:
        """Transcribed words: into the same pipeline as typed radio (UI thread)."""
        self.talk_button.setText(f"Hold to talk  [{self.talk_key}]")
        self.session.radio_send(text, "VOICE")

    def voice_error(self, message: str) -> None:
        """Voice failed: say so; typing stays."""
        self.talk_button.setText(f"Hold to talk  [{self.talk_key}]")
        self.radio_via.setText(f"VOICE: {message}")

    def _talk_key(self, event: Any) -> bool:
        """Hold-to-talk key press / release; return whether the event was ours."""
        if self.ptt is None or event.text() != self.talk_key:
            return False
        if event.isAutoRepeat():
            return True
        if event.type() == event.Type.KeyPress:
            self.talk_down()
        else:
            self.talk_up()
        return True

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 (Qt)
        """Catch the talk key inside the radio box (it would otherwise be typed)."""
        if event.type() in (event.Type.KeyPress, event.Type.KeyRelease) and self._talk_key(event):
            return True
        return bool(super().eventFilter(watched, event))

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 (Qt)
        """Hold the talk key anywhere in the window."""
        if not self._talk_key(event):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: Any) -> None:  # noqa: N802 (Qt)
        """Release the talk key: transcribe."""
        if not self._talk_key(event):
            super().keyReleaseEvent(event)

    def send_radio(self) -> None:
        """Send the typed radio message to the driver (H2)."""
        text = self.radio_input.text().strip()
        if text:
            self.session.radio_send(text)  # LLM (worker) -> keyword parser -> "Say again?"
            self.radio_input.clear()

    def _build_controls(self) -> None:
        self.controls = QWidget()
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.speed_buttons: dict[str, QPushButton] = {}
        for name in SPEEDS:
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, n=name: self.set_speed(n))
            self.speed_buttons[name] = button
            row.addWidget(button)
        self.summary_button = QPushButton("Call summary")
        self.summary_button.clicked.connect(self.show_summary)
        row.addWidget(self.summary_button)
        self.resume_button = QPushButton("Resume")
        self.resume_button.clicked.connect(self.resume)
        self.resume_button.setVisible(False)
        row.addWidget(self.resume_button)
        self.clock = _label("", 14, True)
        row.addWidget(self.clock)
        self.behind = _label("", 10, True, CLIP)  # H6: the sim cannot keep up with the speed
        row.addWidget(self.behind)
        row.addStretch()
        self.voice = DriverVoice()  # H3: the driver's lines spoken, team-radio filtered
        self.voice_box = QCheckBox("Driver voice")
        self.voice_box.setChecked(False)  # muted by default
        self.voice_box.setEnabled(available())
        self.voice_box.setToolTip("Offline speech (Windows) through a team-radio filter")
        self.voice_box.toggled.connect(lambda on: setattr(self.voice, "enabled", on))
        row.addWidget(self.voice_box)
        if self.test_mode:
            row.addWidget(_label("TEST MODE - Rivals' TRUE battery shown", 10, True, CLIP))

        self.commands = QWidget()
        cmd = QHBoxLayout(self.commands)
        cmd.setContentsMargins(0, 0, 0, 0)
        cmd.addWidget(_label("Energy", 8, True, TEXT_DIM))
        for mode in ("PUSH", "BALANCED", "HARVEST"):
            button = QPushButton(mode)
            button.clicked.connect(lambda _=False, m=mode: self.send(
                T.SET_ENERGY_MODE, {"mode": m}, f"Mode {m.lower()}."))  # fmt: skip
            cmd.addWidget(button)
        self.overtake_box = QCheckBox("Overtake mode allowed")
        self.overtake_box.setChecked(True)
        self.overtake_box.toggled.connect(lambda on: self.send(
            T.SET_OVERTAKE_PERMISSION, {"allowed": on},
            "Overtake mode allowed." if on else "No Overtake mode."))  # fmt: skip
        cmd.addWidget(self.overtake_box)
        self.lift_box = QCheckBox("Lift && coast")
        self.lift_box.toggled.connect(lambda on: self.send(
            T.SET_LIFT_COAST, {"enabled": on},
            "Lift and coast." if on else "Stop lifting."))  # fmt: skip
        cmd.addWidget(self.lift_box)
        self.compound = QComboBox()
        self.compound.addItems(["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"])
        self.compound.setCurrentText("HARD")
        cmd.addWidget(self.compound)
        box = QPushButton("BOX")
        box.clicked.connect(self.box)
        cmd.addWidget(box)
        cancel = QPushButton("CANCEL BOX")
        cancel.clicked.connect(lambda: self.send(T.CANCEL_BOX, {}, "Stay out, stay out."))
        cmd.addWidget(cancel)
        for name, kind, say in (("DEFEND", T.DEFEND, "Defend."), ("ATTACK", T.ATTACK, "Attack."),
                                ("HOLD", T.HOLD_POSITION, "Hold position.")):  # fmt: skip
            button = QPushButton(name)
            button.clicked.connect(lambda _=False, k=kind, s=say: self.send(k, {}, s))
            cmd.addWidget(button)
        push_lap = QPushButton("PUSH LAP")
        push_lap.clicked.connect(lambda: self.send(T.PUSH_LAP, {"laps": 1}, "Push lap, push lap."))
        cmd.addWidget(push_lap)
        self.tyres_box = QCheckBox("Manage tyres")
        self.tyres_box.toggled.connect(
            lambda on: self.send(
                T.MANAGE_TYRES, {"enabled": on}, "Manage the tyres." if on else "Stop managing."
            )
        )
        cmd.addWidget(self.tyres_box)
        cmd.addStretch()

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def set_speed(self, name: str) -> None:
        """PAUSE / 1x / 4x / 16x."""
        self.thread_.speed = SPEEDS[name]
        for n, button in self.speed_buttons.items():
            button.setChecked(n == name)
        self._speed_name = name

    def toggle_pause(self) -> None:
        """Space: pause / back to the last speed."""
        if self.thread_.speed > 0:
            self._resume_speed = self._speed_name
            self.set_speed("PAUSE")
        else:
            self.set_speed(getattr(self, "_resume_speed", "1x"))

    def resume(self) -> None:
        """Continue after a pause on alert without answering."""
        self.session.resume()

    def send(self, kind: CommandType, params: dict[str, Any], say: str) -> None:
        """Send one command from a button (validated by the session)."""
        self.session.command(kind, params, say)

    def box(self) -> None:
        """BOX this lap for the chosen compound."""
        lap = self._last_frame.view.our_car.lap + 1 if self._last_frame else 1
        compound = self.compound.currentText()
        self.send(T.BOX, {"lap": lap, "compound": compound}, f"Box, box. {compound.title()}s.")

    def show_summary(self) -> None:
        """Open the call summary (A-4); complete once the race is over."""
        self.summary_dialog = SummaryDialog(self.session, self)
        self.summary_dialog.show()

    def answer(self, alert_id: str, key: int) -> None:
        """Answer an alert with option ``key``."""
        self.session.call(alert_id, key)
        card = self._cards.pop(alert_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()

    def answer_newest(self, key: int) -> None:
        """F1 / F2 / F3 on the newest alert."""
        if self._last_frame and self._last_frame.alerts:
            alert = self._last_frame.alerts[0]
            if any(o.key == key for o in self._last_frame.options.get(alert.alert_id, [])):
                self.answer(alert.alert_id, key)

    def _tower_clicked(self, row: int, _col: int) -> None:
        if row < len(self._row_driver) and self._row_driver[row] != self.our:
            self.selected_rival = self._row_driver[row]

    # ------------------------------------------------------------------ #
    # Frame
    # ------------------------------------------------------------------ #
    def on_frame(self, frame: Frame) -> None:
        """Draw one frame (UI thread)."""
        start = time.perf_counter()
        self._last_frame = frame
        self.frame_options = frame.options
        self.truth_mj = frame.truth_mj
        view = frame.view
        self._draw_map(frame)
        self._remember(frame)
        self.telemetry.add(view)  # H6: append only; drawn at the table rate below
        self._draw_status(frame)
        self._draw_alerts(frame)
        self._draw_radio(frame)
        now = time.perf_counter()
        if now - self._last_table >= TABLE_EVERY_S:
            self._draw_tower(frame)
            self._draw_radar(frame)
            self._draw_strategy(frame)
            self._draw_trace(frame)
            self.telemetry.redraw()
            self._last_table = now
        state = "FINISHED" if frame.finished else (
            "PAUSED ON ALERT" if frame.paused_on_alert else self._speed_name)  # fmt: skip
        order = view.timing.order
        place = f"P{order.index(self.our) + 1}" if self.our in order else "-"
        self.clock.setText(
            f"  {self.drivers[self.our]['code']} {place}    LAP {min(frame.lap, frame.laps)}"
            f"/{frame.laps}    {view.t_s:6.0f} s    {state}"
        )
        self.pause_banner.setVisible(frame.paused_on_alert)
        wanted = self.thread_.speed
        behind = (
            wanted > 0
            and not frame.finished
            and not frame.paused_on_alert
            and (self.thread_.achieved < BEHIND_SHARE * wanted and self.thread_.achieved > 0)
        )
        self.behind.setText(f"SIM BEHIND ({self.thread_.achieved:.0f}x of {wanted:.0f}x)"
                            if behind else "")  # fmt: skip
        banner = TRACK_STATUS_TEXT.get(view.track_status.status)
        if banner and view.track_status.sc_laps_remaining is not None:
            banner += f"   ({view.track_status.sc_laps_remaining} to go)"
        self.track_banner.setText(banner or "")
        self.track_banner.setVisible(banner is not None)
        self.resume_button.setVisible(frame.paused_on_alert)
        if frame.finished and not self._summary_shown:  # A-4: at the flag
            self._summary_shown = True
            self.show_summary()
        self.frame_times.append(time.perf_counter() - start)

    def _rival_xy(self, frame: Frame) -> dict[str, tuple[float, float]]:
        out = {}
        for rival, frames in frame.view.rival_feed.items():
            if frames and frame.view.t_s - frames[-1].t_s <= FRESH_FRAME_S:
                out[rival] = (frames[-1].x_m, frames[-1].y_m)
        return out

    def _draw_map(self, frame: Frame) -> None:
        pos = self._rival_xy(frame)
        if frame.view.our_car.status in ("RUNNING", "PIT"):
            pos[self.our] = self.session.xy_at(frame.view.our_car.s_m)
        names = list(pos)
        xs = [pos[d][0] for d in names]
        ys = [pos[d][1] for d in names]
        sizes = [18 if d == self.our else 12 for d in names]
        self.dots.setData(xs, ys, size=sizes, brush=[self.brushes[d] for d in names])
        for d, label in self.labels.items():
            label.setVisible(d in pos)
            if d in pos:
                label.setPos(*pos[d])

    def _remember(self, frame: Frame) -> None:
        view = frame.view
        if self._history and view.t_s <= self._history[-1][0]:
            return
        est = {d: r.energy_mj if r.confidence > 0.0 else np.nan for d, r in view.radar.items()}
        self._history.append((view.t_s, view.our_car.battery_mj, est, frame.truth_mj or {}))
        while self._history and self._history[0][0] < view.t_s - TRACE_WINDOW_S:
            self._history.popleft()

    def _neighbours(self, frame: Frame) -> tuple[str | None, str | None]:
        order = frame.view.timing.order
        if self.our not in order:
            return None, None
        k = order.index(self.our)
        return (order[k - 1] if k > 0 else None,
                order[k + 1] if k + 1 < len(order) else None)  # fmt: skip

    def _draw_status(self, frame: Frame) -> None:
        me = frame.view.our_car
        self.battery.setText(f"{me.battery_mj:.2f} MJ   ({me.battery_mj / 4.0:.0%})")
        self.battery_bar.setValue(int(me.battery_mj * 100))
        self.status_line.setText(
            f"{me.energy_mode}   {me.compound.value} ({me.tyre_age_laps} laps, wear "
            f"{me.tyre_wear:.0%})   fuel {me.fuel_kg:.1f} kg   {me.v_ms * 3.6:.0f} km/h"
            f"   {AERO_LABELS.get(me.aero_mode, me.aero_mode)}"
            f"   Overtake mode {'ready' if me.overtake_available else '-'}   {me.status}"
        )
        weather = frame.view.weather_public
        rain = weather.rain_forecast_p
        self.weather_line.setText(
            f"Weather (public): {weather.condition.title()}   rain in the next 10 min: "
            + ("-" if rain is None else f"{rain:.0%}")
        )

    def _draw_radar(self, frame: Frame) -> None:
        view = frame.view
        ahead, behind = self._neighbours(frame)
        for which, rival in (("ahead", ahead), ("behind", behind)):
            cells = self.radar_cells[which]
            est = view.radar.get(rival) if rival else None
            if rival is None or est is None:
                for cell in cells[1:]:
                    cell.setText("-")
                continue
            gap = view.timing.interval_s.get(self.our if which == "ahead" else rival)
            dim = est.confidence < self.low_confidence
            cells[1].setText(self.drivers[rival]["code"])
            cells[1].setStyleSheet(f"color:{self.drivers[rival]['color']};")
            cells[2].setText(f"{gap:.2f}" if gap is not None else "-")
            known = est.confidence > 0.0  # before its first anchor a Radar knows nothing
            cells[3].setText(f"~{max(est.energy_mj, 0.0):.1f} MJ" if known else "unknown yet")
            cells[3].setStyleSheet(f"color:{TEXT_DIM if dim else TEXT};")
            cells[4].setText(_sure(est.confidence) if known else "-")
            cells[4].setStyleSheet(f"color:{TEXT_DIM if dim else TEXT};")
            cells[5].setText(STATE_WORDS.get(est.state, est.state))
            cells[5].setStyleSheet(f"color:{STATE_COLOURS.get(est.state, TEXT)};")
            if self.test_mode and frame.truth_mj is not None:
                cells[6].setText(f"{frame.truth_mj.get(rival, float('nan')):.2f}")
                cells[6].setStyleSheet(f"color:{CLIP};")

    def _draw_tower(self, frame: Frame) -> None:
        timing = frame.view.timing
        self._row_driver = list(timing.order)
        for row, d in enumerate(timing.order):
            gap = timing.gap_to_leader_s.get(d)
            interval = timing.interval_s.get(d)
            comp = timing.compound.get(d)
            cells = [
                str(row + 1), self.drivers[d]["code"],
                "LEADER" if row == 0 else (f"+{gap:.1f}" if gap is not None else "-"),
                "" if row == 0 else (f"+{interval:.2f}" if interval is not None else "-"),
                f"{comp.value[0] if comp else '?'} {timing.tyre_age_laps.get(d, 0)}",
                str(timing.pit_stops.get(d, 0)),
            ]  # fmt: skip
            for col, text in enumerate(cells):
                item = self.tower.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.tower.setItem(row, col, item)
                item.setText(text)
                item.setForeground(
                    QColor(self.drivers[d]["color"] if col == 1 and d != self.our else TEXT)
                )
                item.setBackground(QColor("#2A5BA8" if d == self.our else PANEL))
                font = item.font()
                font.setBold(d == self.our)
                item.setFont(font)
                if col == 0 and frame.view.track_status.status != "GREEN":
                    item.setBackground(QColor(DEFEND))  # SC / VSC: the position column in amber
                    item.setForeground(QColor(BG))

    def _draw_trace(self, frame: Frame) -> None:
        if not self._history:
            return
        ahead, behind = self._neighbours(frame)
        rival = self.selected_rival or ahead or behind  # leading: compare with the car behind
        t = np.array([h[0] for h in self._history])
        self.our_curve.setData(t, [h[1] for h in self._history])
        if rival:
            self.rival_curve.setData(t, [h[2].get(rival, np.nan) for h in self._history])
            if self.test_mode:
                self.truth_curve.setData(t, [h[3].get(rival, np.nan) for h in self._history])
            name = self.drivers[rival]["code"]
            pick = "(click a car in the timing tower to change)"
            self.trace_title.setText(f"our battery vs {name}'s Radar Estimate {pick}")
        self.trace.setXRange(float(t[-1]) - TRACE_WINDOW_S, float(t[-1]), padding=0)

    def _draw_alerts(self, frame: Frame) -> None:
        live = {a.alert_id for a in frame.alerts}
        now = time.perf_counter()
        for alert_id, card in list(self._cards.items()):
            if alert_id in live:
                continue
            if card.ended_wall is None:  # ended unanswered: grey it, keep it a moment
                card.mark_missed()
            elif now - card.ended_wall > MISSED_SHOW_S or len(self._cards) > MAX_CARDS:
                self._cards.pop(alert_id)
                card.setParent(None)
                card.deleteLater()
        for alert in reversed(frame.alerts):  # oldest first: each new one goes on top
            if alert.alert_id not in self._cards:
                card = AlertCard(self, alert, self.session.headline(alert))
                self.alert_layout.insertWidget(0, card)
                self._cards[alert.alert_id] = card
        for alert_id in live & self._cards.keys():
            self._cards[alert_id].set_remaining(frame.view.t_s)
        self.alert_empty.setVisible(not self._cards)

    def _draw_radio(self, frame: Frame) -> None:
        via = self.session.radio_path
        if via != self._radio_via_shown:
            self._radio_via_shown = via
            llm = self.session.radio_ai.name
            self.radio_via.setText(f"Understood by: {via}" + (f"  ({llm})" if "LLM" in via else ""))
        lines = frame.radio
        if len(lines) == self._radio_count:
            return
        for line in lines[self._radio_count :]:
            if line.sender == "DRIVER":
                self.voice.say(line.text)
            item = QListWidgetItem(f"{line.t_s:7.1f}  {line.sender:8s} {line.text}")
            colour = CLIP if line.rejected else (OUR_CAR if line.sender == "DRIVER" else TEXT)
            item.setForeground(QColor(colour))
            self.radio_list.insertItem(0, item)
        self._radio_count = len(lines)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 (Qt)
        """Stop the sim thread, the decision-cost thread and the strategy processes."""
        if self.summary_dialog is not None:  # a running QThread destroyed with it aborts Qt
            self.summary_dialog.close()
        self.thread_.stop()
        self.thread_.wait(2000)
        self.session.close()
        super().closeEvent(event)


class VoiceBridge(QObject):
    """Hands push-to-talk results from the speech worker to the UI thread (H2)."""

    text = Signal(str)
    error = Signal(str)

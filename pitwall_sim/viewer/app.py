"""Replay viewer window (sprint S-2): track map, timing tower, battery trace.

Plays a recorded race (:mod:`pitwall_sim.viewer.record`): cars move on the
track map in team colours with driver codes, the timing tower shows position,
gap and tyre, and the battery trace of the selected car shows the true battery
(solid) against the built-in Radar Estimate (dashed). Play / pause, 1x / 4x /
16x, a lap slider, and a "Truth" toggle. Colours: docs/spec/UI_DESIGN.md COLOURS.
"""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGraphicsItem,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pitwall_sim.viewer.record import Replay

#: docs/spec/UI_DESIGN.md COLOURS.
BG, PANEL, TEXT, TEXT_DIM = "#101214", "#181B1F", "#E6E8EB", "#8A9099"
OUR_CAR, DEPLOY, DEFEND, CLIP = "#3D8BFF", "#2ECC71", "#F5A623", "#FF4D4F"
TYRE_COLOURS = {"SOFT": "#FF4D4F", "MEDIUM": "#F5D90A", "HARD": "#E6E8EB",
                "INTERMEDIATE": "#2ECC71", "WET": "#3D8BFF"}  # fmt: skip
SPEEDS = (1, 4, 16)
FRAME_MS = 40  # 25 fps target
TRACE_LAPS_BEFORE, TRACE_LAPS_AFTER = 3.0, 1.0  # battery trace window around now
TRACK_POINTS = 600  # points of the drawn track outline
TOWER_EVERY_S = 0.2  # tower refresh (wall clock)


class ReplayWindow(QMainWindow):
    """Main window of the replay viewer."""

    def __init__(self, replay: Replay) -> None:
        """Build the panels for ``replay``; playback starts paused at the start."""
        super().__init__()
        self.r = replay
        self.drivers = replay.meta["drivers"]
        self.k = 0  # current tick
        self.t = float(replay.t_s[0])
        self.speed = 4
        self.playing = False
        self.selected = 0
        self._last_wall = time.perf_counter()
        self._last_tower = 0.0
        self.frames = 0
        meta = replay.meta
        self.setWindowTitle(
            f"pitwall_sim replay - {meta['track_id']} {meta['rule_set_id']} seed {meta['seed']}"
        )
        self.setStyleSheet(f"background:{BG}; color:{TEXT};")
        pg.setConfigOptions(antialias=True, background=PANEL, foreground=TEXT)

        # Track map.
        self.map = pg.PlotWidget()
        self.map.setAspectLocked(True)
        self.map.hideAxis("left")
        self.map.hideAxis("bottom")
        self.map.setMouseEnabled(False, False)
        x, y = replay.track_x, replay.track_y
        step = max(len(x) // TRACK_POINTS, 1)  # the outline needs no 1 m detail
        outline = self.map.plot(
            np.append(x[::step], x[0]), np.append(y[::step], y[0]), pen=pg.mkPen(TEXT_DIM, width=5)
        )
        # The map never pans: draw the track once into a pixmap, not at every frame.
        outline.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.brushes = [pg.mkBrush(d["color"]) for d in self.drivers]
        self.dots = pg.ScatterPlotItem(size=13, pen=pg.mkPen(BG, width=1))
        self.map.addItem(self.dots)
        font = QFont()
        font.setPointSize(7)
        self.labels = []
        for d in self.drivers:
            label = pg.TextItem(d["code"], color=TEXT, anchor=(0.5, 1.3))
            label.setFont(font)
            self.map.addItem(label)
            self.labels.append(label)

        # Timing tower.
        self.tower = QTableWidget(len(self.drivers), 5)
        self.tower.setHorizontalHeaderLabels(["P", "Driver", "Gap", "Tyre", "Lap"])
        self.tower.verticalHeader().setVisible(False)
        self.tower.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tower.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tower.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tower.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tower.setStyleSheet(f"background:{PANEL}; gridline-color:{BG};")
        self.tower.cellClicked.connect(self._tower_clicked)
        self._row_driver = list(range(len(self.drivers)))

        # Battery trace.
        self.trace = pg.PlotWidget()
        self.trace.setLabel("left", "battery", units="MJ")
        self.trace.setLabel("bottom", "lap")
        self.trace.setYRange(0.0, 4.2)
        self.trace.addLegend(offset=(10, 5))
        self.truth_curve = self.trace.plot(pen=pg.mkPen(DEPLOY, width=2), name="true battery")
        self.radar_curve = self.trace.plot(
            pen=pg.mkPen(DEFEND, width=2, style=Qt.PenStyle.DashLine),
            name="Radar Estimate",
            connect="finite",  # gaps where the estimate is unknown
        )
        for curve in (self.truth_curve, self.radar_curve):  # draw only the visible window
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method="peak")
        self.trace.setMouseEnabled(x=False, y=False)
        self.now_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(TEXT_DIM))
        self.trace.addItem(self.now_line)
        self.trace_title = QLabel()

        # Controls.
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.speed_box = QComboBox()
        self.speed_box.addItems([f"{s}x" for s in SPEEDS])
        self.speed_box.setCurrentText(f"{self.speed}x")
        self.speed_box.currentTextChanged.connect(lambda text: self.set_speed(int(text[:-1])))
        self.truth_box = QCheckBox("Truth")
        self.truth_box.setChecked(True)
        self.truth_box.toggled.connect(self._truth_toggled)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, int(replay.meta["laps"]))
        self.slider.sliderMoved.connect(self.seek_lap)
        self.clock = QLabel()

        controls = QHBoxLayout()
        for w in (self.play_button, self.speed_box, self.truth_box, QLabel("lap"), self.slider,
                  self.clock):  # fmt: skip
            controls.addWidget(w)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.map)
        top.addWidget(self.tower)
        top.setSizes([800, 360])
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.trace_title)
        bl.addWidget(self.trace)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(bottom)
        main.setSizes([560, 260])
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(main)
        layout.addLayout(controls)
        self.setCentralWidget(root)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.frame)
        self.timer.start(FRAME_MS)
        self.select(0)
        self.render_tick(force_tower=True)

    # ------------------------------------------------------------------ #
    def toggle_play(self) -> None:
        """Play or pause."""
        self.playing = not self.playing
        self.play_button.setText("Pause" if self.playing else "Play")
        self._last_wall = time.perf_counter()

    def set_speed(self, speed: int) -> None:
        """Set the playback speed (1, 4 or 16)."""
        self.speed = speed

    def seek_lap(self, lap: int) -> None:
        """Jump to the start of the leader's lap ``lap``."""
        k = int(np.searchsorted(self.r.leader_lap, lap))
        self.k = min(k, self.r.t_s.size - 1)
        self.t = float(self.r.t_s[self.k])
        self.render_tick(force_tower=True)

    def select(self, car: int) -> None:
        """Show car ``car``'s battery trace."""
        self.selected = car
        r, d = self.r, self.drivers[car]
        laps = self._lap_axis(car)
        self.truth_curve.setData(laps, r.battery_mj[:, car])
        self.radar_curve.setData(laps, r.radar_mj[:, car])
        self.trace_title.setText(
            f"  {d['code']}  #{d['number']}  {d['team']}  - battery: true (solid) vs "
            "Radar Estimate (dashed)"
        )
        self._truth_toggled(self.truth_box.isChecked())

    def _lap_axis(self, car: int) -> np.ndarray:
        """Fractional lap of ``car`` at each tick (x axis of the trace)."""
        length = float(self.r.meta["length_m"])
        return np.asarray(self.r.lap[:, car] + 1 + self.r.s_m[:, car] / length, dtype=np.float64)

    def _truth_toggled(self, on: bool) -> None:
        self.truth_curve.setVisible(on)

    def _tower_clicked(self, row: int, _column: int) -> None:
        self.select(self._row_driver[row])

    # ------------------------------------------------------------------ #
    def frame(self) -> None:
        """Advance the clock by the wall time since the last frame x speed, then draw."""
        now = time.perf_counter()
        if self.playing:
            self.t += (now - self._last_wall) * self.speed
            if self.t >= self.r.t_s[-1]:
                self.t = float(self.r.t_s[-1])
                self.toggle_play()
            self.k = int(np.searchsorted(self.r.t_s, self.t, side="right")) - 1
        self._last_wall = now
        self.render_tick(force_tower=now - self._last_tower >= TOWER_EVERY_S)
        self.frames += 1

    def render_tick(self, force_tower: bool = False) -> None:
        """Draw the cars, the clock and (if due) the timing tower at the current tick."""
        r, k = self.r, max(self.k, 0)
        x, y = r.xy(k)
        shown = r.status[k] != r.meta["status"].index("DNF")
        sizes = np.where(np.arange(r.n_cars) == self.selected, 18, 12)
        self.dots.setData(x[shown], y[shown], size=sizes[shown],
                          brush=[self.brushes[i] for i in np.flatnonzero(shown)])  # fmt: skip
        for i, label in enumerate(self.labels):
            label.setVisible(bool(shown[i]))
            label.setPos(float(x[i]), float(y[i]))
        lap = int(r.leader_lap[k])
        self.clock.setText(f"lap {min(lap, r.meta['laps'])}/{r.meta['laps']}  "
                           f"t {r.t_s[k]:7.1f} s  {self.speed}x")  # fmt: skip
        if not self.slider.isSliderDown():
            self.slider.setValue(min(lap, int(r.meta["laps"])))
        sel_lap = float(self._lap_axis(self.selected)[k])
        self.now_line.setPos(sel_lap)
        self.trace.setXRange(sel_lap - TRACE_LAPS_BEFORE, sel_lap + TRACE_LAPS_AFTER, padding=0)
        if force_tower:
            self._fill_tower(k)
            self._last_tower = time.perf_counter()

    def _fill_tower(self, k: int) -> None:
        r = self.r
        order = np.argsort(r.position[k])
        self._row_driver = [int(i) for i in order]
        dnf = r.meta["status"].index("DNF")
        for row, i in enumerate(order):
            d = self.drivers[i]
            gap = "LEADER" if row == 0 else f"+{r.gap_s[k, i]:.1f}"
            if r.status[k, i] == dnf:
                gap = "DNF"
            elif r.in_pit[k, i]:
                gap = "PIT"
            tyre = r.meta["compounds"][r.compound[k, i]]
            cells = [str(row + 1), d["code"], gap, tyre[0], str(int(r.lap[k, i]) + 1)]
            for col, text in enumerate(cells):
                item = self.tower.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.tower.setItem(row, col, item)
                item.setText(text)
                if col == 1:
                    item.setForeground(QColor(d["color"]))
                if col == 3:
                    item.setForeground(QColor(TYRE_COLOURS.get(tyre, TEXT)))
                bold = item.font()
                bold.setBold(bool(i == self.selected))
                item.setFont(bold)

"""F15 telemetry traces, lite (hackathon H6, from T-075): Our Car against lap distance.

Three stacked plots sharing the x axis (distance in lap, m): speed (km/h),
throttle (%) and battery (MJ). The current lap is a solid Our Car blue line, the
previous lap the same line as a ghost at 30 % opacity (docs/spec/UI_DESIGN.md
Telemetry traces). Data: Our Car's own exact values from the EngineerView
(``our_car``: ``s_m``, ``v_ms``, ``throttle``, ``battery_mj``); no Rival data, so
nothing crosses the information barrier (HR-02 / HR-03).

Cheap at 16x: :class:`LapBuffer` keeps preallocated NumPy arrays (no per-frame
allocation), :meth:`TelemetryPlot.add` is called every frame and only appends,
:meth:`TelemetryPlot.redraw` runs at the table rate and calls ``setData`` on the
existing curves (never recreates plot items), and skips work when hidden or
unchanged.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pitwall_sim.observe.engineer_view import EngineerView

OUR_CAR, TEXT, TEXT_DIM = "#3D8BFF", "#E6E8EB", "#8A9099"
"""docs/spec/UI_DESIGN.md COLOURS."""
GHOST_ALPHA = 0.30
"""Previous-lap ghost opacity (UI_DESIGN Telemetry traces)."""
CAPACITY = 8192
"""Samples kept per lap (30 Hz frames at 1x for a ~95 s lap are ~2900)."""
MIN_GHOST_SHARE = 0.5
"""A finished lap becomes the ghost only if its samples cover this share of the lap
(the partial lap from the grid to the line is not a ghost)."""
#: (channel, axis label, y range) in display units
CHANNELS = (
    ("speed", "km/h", (0.0, 360.0)),
    ("throttle", "%", (-5.0, 105.0)),
    ("battery", "MJ", (-0.2, 4.2)),
)


class LapBuffer:
    """One lap of Our Car samples in preallocated arrays."""

    def __init__(self, capacity: int = CAPACITY) -> None:
        """Allocate ``capacity`` samples per channel."""
        self.s_m = np.zeros(capacity)
        self.data = {name: np.zeros(capacity) for name, *_ in CHANNELS}
        self.n = 0
        self.lap: int | None = None

    def clear(self, lap: int | None) -> None:
        """Start lap ``lap`` (the arrays are reused)."""
        self.n = 0
        self.lap = lap

    def append(self, s_m: float, speed_kmh: float, throttle_pct: float, battery_mj: float) -> None:
        """Add one sample (dropped once the buffer is full)."""
        k = self.n
        if k >= self.s_m.size:
            return
        self.s_m[k] = s_m
        self.data["speed"][k] = speed_kmh
        self.data["throttle"][k] = throttle_pct
        self.data["battery"][k] = battery_mj
        self.n = k + 1

    def x(self) -> npt.NDArray[np.float64]:
        """Return the lap distances so far (a view, no copy)."""
        return self.s_m[: self.n]

    def y(self, name: str) -> npt.NDArray[np.float64]:
        """Return channel ``name`` so far (a view, no copy)."""
        return self.data[name][: self.n]

    def coverage_m(self) -> float:
        """Return the lap distance the samples span."""
        if self.n < 2:
            return 0.0
        return float(self.s_m[self.n - 1] - self.s_m[0])


class LapTelemetry:
    """Current lap and previous lap (the ghost) of Our Car; no Qt."""

    def __init__(self, lap_length_m: float, capacity: int = CAPACITY) -> None:
        """Track laps of ``lap_length_m``."""
        self.lap_length_m = lap_length_m
        self.current = LapBuffer(capacity)
        self.ghost = LapBuffer(capacity)
        self.has_ghost = False
        self._last_t: float | None = None
        self.version = 0
        """Bumped on every change, so a redraw can skip an unchanged buffer."""

    def add(self, view: EngineerView) -> None:
        """Add Our Car from ``view`` (repeated frames while paused are ignored)."""
        car = view.our_car
        if car.status not in ("RUNNING", "PIT"):
            return
        self.add_sample(view.t_s, car.lap, car.s_m, car.v_ms, car.throttle, car.battery_mj)

    def add_sample(self, t_s: float, lap: int, s_m: float, v_ms: float, throttle: float,
                   battery_mj: float) -> None:  # fmt: skip
        """Add one sample in SI / CarState units (m, m/s, 0..1, MJ)."""
        if self._last_t is not None and t_s <= self._last_t:
            return
        self._last_t = t_s
        if self.current.lap is None:
            self.current.clear(lap)
        elif lap != self.current.lap:
            self._roll(lap)
        self.current.append(s_m, v_ms * 3.6, throttle * 100.0, battery_mj)
        self.version += 1

    def _roll(self, lap: int) -> None:
        complete = self.current.coverage_m() >= MIN_GHOST_SHARE * self.lap_length_m
        if complete:
            self.current, self.ghost = self.ghost, self.current  # swap: no allocation
            self.has_ghost = True
        self.current.clear(lap)


class TelemetryPlot(QWidget):
    """Speed, throttle and battery against lap distance, with the previous-lap ghost."""

    def __init__(self, lap_length_m: float, parent: QWidget | None = None) -> None:
        """Build the three linked plots and their (persistent) curves."""
        super().__init__(parent)
        self.telemetry = LapTelemetry(lap_length_m)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.title = QLabel("waiting for the first lap")
        self.title.setStyleSheet(f"color:{TEXT_DIM}; font-size:8pt;")
        layout.addWidget(self.title)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.graphics.ci.layout.setSpacing(0)
        self.graphics.setMinimumHeight(150)
        layout.addWidget(self.graphics, 1)
        ghost_colour = QColor(OUR_CAR)
        ghost_colour.setAlphaF(GHOST_ALPHA)
        self.plots: dict[str, pg.PlotItem] = {}
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.ghosts: dict[str, pg.PlotDataItem] = {}
        first: pg.PlotItem | None = None
        for row, (name, unit, (low, high)) in enumerate(CHANNELS):
            plot = self.graphics.addPlot(row=row, col=0)
            plot.setMouseEnabled(False, False)
            plot.hideButtons()
            plot.setMenuEnabled(False)
            plot.setXRange(0.0, lap_length_m, padding=0)
            plot.setYRange(low, high, padding=0)
            plot.setLabel("left", unit)
            plot.getAxis("left").setWidth(42)
            plot.layout.setContentsMargins(0, 2, 4, 0)
            plot.showGrid(x=True, y=False, alpha=0.15)
            plot.setClipToView(True)
            last = row == len(CHANNELS) - 1
            if last:
                plot.setLabel("bottom", "distance in lap", units="m")
            else:
                plot.hideAxis("bottom")  # shared x axis: only the bottom plot shows it
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            self.ghosts[name] = plot.plot(pen=pg.mkPen(ghost_colour, width=2))
            self.curves[name] = plot.plot(pen=pg.mkPen(OUR_CAR, width=2))
            self.plots[name] = plot
        self._drawn = -1

    def add(self, view: EngineerView) -> None:
        """Record Our Car from the view (call every frame; cheap)."""
        self.telemetry.add(view)

    def redraw(self, force: bool = False) -> bool:
        """Push the buffers to the curves; skipped when hidden or unchanged (returns drawn)."""
        tel = self.telemetry
        if not force and (not self.isVisible() or tel.version == self._drawn):
            return False
        self._drawn = tel.version
        x = tel.current.x()
        gx = tel.ghost.x() if tel.has_ghost else x[:0]
        for name, *_ in CHANNELS:
            self.curves[name].setData(x, tel.current.y(name))
            self.ghosts[name].setData(gx, tel.ghost.y(name) if tel.has_ghost else x[:0])
        lap = tel.current.lap
        if lap is not None and lap >= 0:
            g = tel.ghost.lap
            ghost = (
                f"lap {g + 1} ghost (faint)" if tel.has_ghost and g is not None else "no ghost yet"
            )
            self.title.setText(f"Our car: lap {lap + 1} (solid) vs {ghost}")
        return True

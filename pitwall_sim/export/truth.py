"""Ground Truth of a race at a fixed rate, plus laps and gaps at the line (sprint S-1).

The engine runs as usual; its kernel stage is split into single physics steps
(the same steps, so the race is identical) and every car is sampled each
``1 / truth_hz`` seconds. Lap and gap rows are taken when a car crosses the
timing line.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall_sim.observe.alerts import Alert, make_provider
from pitwall_sim.observe.engineer_view import EngineerViewBuilder
from pitwall_sim.race import step_kernel as K
from pitwall_sim.race.engine import RaceEngine
from pitwall_sim.race.pit import PitPhase

FIELDS: dict[str, Any] = {
    "s_m": np.float32, "lap": np.int16, "v_ms": np.float32, "battery_j": np.float32,
    "power_w": np.float32, "p_k_w": np.float32, "p_harvest_w": np.float32,
    "superclip": np.bool_, "taper_limited": np.bool_, "throttle": np.float32,
    "brake": np.float32, "overtake_active": np.bool_, "aero_mode": np.int8,
    "fuel_kg": np.float32, "running": np.bool_, "in_pit": np.bool_, "ahead_idx": np.int16,
    "gap_ahead_m": np.float32, "mode": np.int8,
}  # fmt: skip
"""Recorded per sample and car."""


@dataclass
class TruthRun:
    """A recorded race: ``data[name]`` is (samples, cars), ``t_s`` (samples,)."""

    engine: RaceEngine
    t_s: npt.NDArray[np.float64]
    data: dict[str, npt.NDArray[Any]]
    laps: list[dict[str, Any]] = field(default_factory=list)
    """One row per completed lap (timing line crossing)."""
    alerts: list[Alert] = field(default_factory=list)
    """The built-in alert provider's alerts for the point-of-view car (baseline)."""


class _Recorder:
    def __init__(self, engine: RaceEngine, hz: float) -> None:
        self.engine = engine
        self.every = max(1, round(1.0 / (hz * engine.dt)))
        rows = int(engine.laps * 130.0 * hz) + 16
        self.t = np.empty(rows)
        self.data = {k: np.empty((rows, engine.n), dtype=v) for k, v in FIELDS.items()}
        self.n = 0
        self.done_laps = [0] * engine.n
        self.laps: list[dict[str, Any]] = []
        self.lap_start = np.zeros(engine.n)

    def kernel(self) -> None:
        """Run the engine's kernel stage one physics step at a time, sampling as it goes."""
        e = self.engine
        e._mark("kernel")
        e._s_before[:] = e.st.s_m
        for _ in range(e.chunk_steps):
            e.t = K.advance(1, e.dt, e.t, e.plans, e.trk, e.glb, e.cars, e.ctl, e.st)
            e.steps += 1
            if e.steps % self.every == 0:
                self.sample()

    def sample(self) -> None:
        e, st, ctl = self.engine, self.engine.st, self.engine.ctl
        if self.n == self.t.size:  # longer than planned: grow
            self.t = np.concatenate((self.t, np.empty(self.t.size)))
            self.data = {k: np.concatenate((v, np.empty_like(v))) for k, v in self.data.items()}
        k = self.n
        self.t[k] = e.t
        values = {
            "s_m": st.s_m, "lap": st.lap, "v_ms": st.v_ms, "battery_j": st.battery_j,
            "power_w": st.power_w, "p_k_w": st.p_k_w, "p_harvest_w": st.p_harvest_w,
            "superclip": st.superclip_on, "taper_limited": st.taper_limited,
            "throttle": ctl.throttle, "brake": ctl.brake, "overtake_active": ctl.overtake_active,
            "aero_mode": st.aero_mode, "fuel_kg": st.fuel_kg, "running": st.running,
            "in_pit": st.in_pit, "ahead_idx": st.ahead_idx, "gap_ahead_m": st.gap_ahead_m,
            "mode": e._instruction_arrays.mode,
        }  # fmt: skip
        for name, value in values.items():
            self.data[name][k] = value
        self.n += 1

    def line_rows(self) -> None:
        """Lap rows for every car that completed a lap since the last tick."""
        e, tm = self.engine, self.engine.timing
        for i in range(e.n):
            done = len(tm.lap_times[i])
            while self.done_laps[i] < done:
                lap = self.done_laps[i] + 1
                self.done_laps[i] = lap
                start = float(self.lap_start[i])
                end = start + tm.lap_times[i][lap - 1]
                self.lap_start[i] = end
                stops = [p for p in e.pit.events if p.car == i and start <= p.t_s < end]
                pit_in = next((p.t_s for p in stops if p.phase == PitPhase.PIT_LANE_IN), None)
                pit_out = next((p.t_s for p in stops if p.phase == PitPhase.RUNNING), None)
                self.laps.append({
                    "car": i, "lap": lap, "lap_time_s": tm.lap_times[i][lap - 1],
                    "sectors_s": tuple(float(x) for x in tm.sectors[i]), "start_s": start,
                    "position": int(e._rank[i]) + 1, "compound": str(e.compounds[i]),
                    "tyre_life": int(e.tyre_laps[i]), "pit_in_s": pit_in, "pit_out_s": pit_out,
                    "gap_to_leader_s": float(tm.gap_s[i]), "interval_s": float(tm.interval_s[i]),
                })  # fmt: skip


def record(
    engine: RaceEngine, hz: float, alert_pov: str | None = None,
    on_tick: Callable[[RaceEngine], None] | None = None,
) -> TruthRun:  # fmt: skip
    """Run ``engine`` to the flag, sampling every car at ``hz``.

    ``alert_pov``: also run the built-in alert provider for this car, as its pit
    wall would (EngineerView only), and keep each alert when it fires.
    ``on_tick``: called after every tick (scenario upkeep).
    """
    rec = _Recorder(engine, hz)
    engine._kernel = types.MethodType(lambda self: rec.kernel(), engine)  # type: ignore[method-assign]
    engine.auto_snapshot = False
    builder = EngineerViewBuilder(engine, alert_pov) if alert_pov else None
    provider = make_provider(
        engine.app.alerts, engine.track, engine.rules.power, engine.app.feed.rate_hz
    )
    alerts: dict[str, Alert] = {}
    while not engine.finished and engine.t < engine.max_t_s:
        engine.tick()
        rec.line_rows()
        if on_tick is not None:
            on_tick(engine)
        if builder is not None:
            for alert in provider.update(builder.build()):
                alerts.setdefault(alert.alert_id, alert)
    data = {k: v[: rec.n].copy() for k, v in rec.data.items()}
    found = sorted(alerts.values(), key=lambda a: a.created_t)
    return TruthRun(engine, rec.t[: rec.n].copy(), data, rec.laps, found)

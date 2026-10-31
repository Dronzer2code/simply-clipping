"""F05 pit lane state machine (T-035; TRD PIT LANE, PF-12).

::

    RUNNING --BOX--> BOX_PENDING --pit entry--> PIT_LANE_IN --box--> STATIONARY
       ^                 | CANCEL_BOX                                     | stop time
       |                 v                                                v
       +------------ RUNNING  <--pit exit (new tyres)--  PIT_LANE_OUT  <--+

The pit lane runs along the track's ``s`` from ``pit.entry_s_m`` to
``pit.exit_s_m`` (it may cross the timing line, so laps count as usual). In it
the kernel limits the car to ``pit.lane_speed_kmh`` and the car neither blocks
nor is blocked by cars on track (``KernelState.in_pit``). At the box
(``app.yaml pit.box_fraction`` of the way along) the car stops for
``Normal(stop_mean_s, stop_sd_s)`` clipped at ``stop_min_s``, plus
``slow_stop_extra_s`` with probability ``slow_stop_p`` (RNG stream ``pit``,
HR-04); while stationary it is not ``running`` in the kernel. Passing the exit
it rejoins with the new compound, wear 0 and tyre age 0 (the engine fits the
tyres). The time lost is not a constant: it emerges from the drive through
the lane (TRD PIT LANE; under SC/VSC too).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import Compound, PitConfig, PitStopConfig
from pitwall_sim.race import step_kernel as K
from pitwall_sim.race.overtake import crossed

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]


class PitPhase(StrEnum):
    """PF-12 states."""

    RUNNING = "RUNNING"
    BOX_PENDING = "BOX_PENDING"
    PIT_LANE_IN = "PIT_LANE_IN"
    STATIONARY = "STATIONARY"
    PIT_LANE_OUT = "PIT_LANE_OUT"


@dataclass(frozen=True)
class PitEvent:
    """One PF-12 transition."""

    t_s: float
    car: int
    phase: PitPhase
    """The state entered."""
    compound: Compound | None = None
    stationary_s: float | None = None


class PitLane:
    """Pit stops for every car of one race."""

    def __init__(
        self,
        track_pit: PitConfig,
        stops: PitStopConfig,
        n_cars: int,
        length_m: float,
        rng: np.random.Generator,
    ) -> None:
        """Pit lane geometry from the track config, stop times from ``app.yaml``."""
        self.entry_s_m = track_pit.entry_s_m
        self.exit_s_m = track_pit.exit_s_m
        lane_m = (self.exit_s_m - self.entry_s_m) % length_m
        self.box_s_m = (self.entry_s_m + stops.box_fraction * lane_m) % length_m
        self.cfg = stops
        self.rng = rng
        self.phase = [PitPhase.RUNNING] * n_cars
        self.next_compound: list[Compound | None] = [None] * n_cars
        self.release_t = np.full(n_cars, np.inf)
        self.events: list[PitEvent] = []

    def request_box(self, i: int, compound: Compound, t_s: float = 0.0) -> bool:
        """Call car ``i`` in for ``compound`` (RUNNING -> BOX_PENDING; False otherwise)."""
        if self.phase[i] != PitPhase.RUNNING:
            return False
        self.phase[i] = PitPhase.BOX_PENDING
        self.next_compound[i] = compound
        self.events.append(PitEvent(t_s, i, PitPhase.BOX_PENDING, compound))
        return True

    def cancel_box(self, i: int, t_s: float = 0.0) -> bool:
        """Cancel before the pit entry (BOX_PENDING -> RUNNING; False otherwise)."""
        if self.phase[i] != PitPhase.BOX_PENDING:
            return False
        self.phase[i] = PitPhase.RUNNING
        self.next_compound[i] = None
        self.events.append(PitEvent(t_s, i, PitPhase.RUNNING))
        return True

    def stationary_time_s(self) -> float:
        """Draw one stop time (RNG stream ``pit``)."""
        cfg = self.cfg
        t = max(float(self.rng.normal(cfg.stop_mean_s, cfg.stop_sd_s)), cfg.stop_min_s)
        if self.rng.random() < cfg.slow_stop_p:
            t += cfg.slow_stop_extra_s
        return t

    def step(self, t_s: float, s_before: FloatArray, st: K.KernelState) -> list[PitEvent]:
        """Advance every car's pit state over the interval that ended at ``t_s``."""
        new: list[PitEvent] = []
        for i, phase in enumerate(self.phase):
            if phase == PitPhase.RUNNING:
                continue
            moved = (float(s_before[i]), float(st.s_m[i]))
            if phase == PitPhase.BOX_PENDING and crossed(*moved, self.entry_s_m):
                self.phase[i] = PitPhase.PIT_LANE_IN
                st.in_pit[i] = True
                new.append(PitEvent(t_s, i, PitPhase.PIT_LANE_IN))
                phase = self.phase[i]
            if phase == PitPhase.PIT_LANE_IN and crossed(*moved, self.box_s_m):
                stop = self.stationary_time_s()
                self.phase[i] = PitPhase.STATIONARY
                self.release_t[i] = t_s + stop
                st.running[i] = False
                st.v_ms[i] = 0.0
                new.append(PitEvent(t_s, i, PitPhase.STATIONARY, stationary_s=stop))
            elif phase == PitPhase.STATIONARY and t_s >= self.release_t[i]:
                self.phase[i] = PitPhase.PIT_LANE_OUT
                self.release_t[i] = np.inf
                st.running[i] = True
                new.append(PitEvent(t_s, i, PitPhase.PIT_LANE_OUT))
            elif phase == PitPhase.PIT_LANE_OUT and crossed(*moved, self.exit_s_m):
                self.phase[i] = PitPhase.RUNNING
                st.in_pit[i] = False
                compound = self.next_compound[i]
                self.next_compound[i] = None
                new.append(PitEvent(t_s, i, PitPhase.RUNNING, compound=compound))
        self.events.extend(new)
        return new

    def in_lane(self, i: int) -> bool:
        """Car ``i`` is between pit entry and exit."""
        return self.phase[i] in (PitPhase.PIT_LANE_IN, PitPhase.STATIONARY, PitPhase.PIT_LANE_OUT)

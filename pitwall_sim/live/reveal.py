"""Post-race Reveal (hackathon H1, part 1): Radar Estimate vs truth, and every call in context.

:class:`RevealRecorder` runs inside the live session while the race runs. Every
``SAMPLE_S`` of race time it stores each Rival's Radar Estimate and confidence (what
the pit wall saw) next to that Rival's TRUE battery, and counts how long Our Car
raced each Rival (directly ahead or behind within ``BATTLE_GAP_S``, public
timing). For every :class:`CallRecord` it keeps Our Car's position and gap at the
call and ``AFTER_LAPS`` laps later, and the estimate error of the Rival the call
was about.

The true batteries never reach the in-race view (HR-03): :meth:`reveal` returns
nothing until the chequered flag. After it, truth is allowed (owner, H1).

For the race graphs (``pitwall_sim.graph``) it also keeps, per sample, the public
running order and intervals of all cars, every car's TRUE speed and, per alert, the
Rival's TRUE battery and ours when it fired; :meth:`samples` hands them over after
the flag, like :meth:`reveal`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from pitwall_sim.engineer.records import CallRecord
from pitwall_sim.observe.engineer_view import EngineerView

SAMPLE_S = 1.0
"""Race seconds between samples (STRUCTURAL)."""
BATTLE_GAP_S = 1.0
"""A Rival directly ahead / behind within this public interval is "raced" (battles.within_s)."""
AFTER_LAPS = 2
"""Our Car's laps after a call at which its outcome is read (A-4 uses the same)."""
OFF_MJ = 1.0
"""A call "made on a wrong estimate": the Rival's estimate was off by more than this."""
TOP_RIVALS = 3
Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class RivalSeries:
    """One Rival over the race: estimate, its confidence and the truth (MJ)."""

    driver_id: str
    battle_s: float
    """Race seconds Our Car spent directly ahead of / behind it within 1 s."""
    lap: Array
    """Our Car's race progress in laps (1.0 = the start of lap 1)."""
    t_s: Array
    estimate_mj: Array
    confidence: Array
    truth_mj: Array


@dataclass
class CallContext:
    """One call with what surrounded it."""

    record: CallRecord
    rival: str | None
    """The Rival the call was about (the alert's, else the car ahead, else behind)."""
    estimate_mj: float | None
    truth_mj: float | None
    position_before: int
    gap_before_s: float | None
    """Public interval to the car ahead (None: leading)."""
    position_after: int | None = None
    gap_after_s: float | None = None
    cost: str = "computing…"
    """Filled by the decision-cost forks (H1 part 2)."""

    @property
    def error_mj(self) -> float | None:
        """Estimate minus truth for the Rival the call was about."""
        if self.estimate_mj is None or self.truth_mj is None:
            return None
        return self.estimate_mj - self.truth_mj


@dataclass(frozen=True)
class RevealData:
    """What the Reveal tab shows after the flag."""

    rivals: list[RivalSeries]
    """The Rivals Our Car raced most, most first."""
    calls: list[CallContext]
    radar_mae_mj: float
    """Mean |estimate - truth| over every Rival and sample with confidence > 0."""
    calls_off: int
    """Calls made on an estimate off by more than ``OFF_MJ``."""


@dataclass(frozen=True)
class RevealSamples:
    """Everything the recorder sampled, for the race graphs (after the flag only)."""

    rivals: tuple[str, ...]
    t_s: Array
    lap: Array
    """Our Car's race progress in laps, as :attr:`RivalSeries.lap`."""
    order: list[list[str]]
    """Public running order at each sample."""
    interval_s: list[dict[str, float]]
    """Public interval to the car ahead at each sample."""
    estimate_mj: Array
    """(samples, rivals) Radar Estimates."""
    confidence: Array
    truth_mj: Array
    """(samples, rivals) TRUE batteries."""
    speed_kmh: dict[str, Array]
    """Every car's TRUE speed at each sample (Our Car included)."""
    alert_truth: dict[str, tuple[float, float]]
    """alert_id -> (the Rival's TRUE battery, Our Car's battery) when it fired (MJ)."""
    battle_s: dict[str, float]
    """Rival -> race seconds Our Car raced it (as :attr:`RivalSeries.battle_s`)."""


@dataclass
class RevealRecorder:
    """Collects the Reveal while the race runs (truth kept here, never in the view)."""

    our: str
    rivals: tuple[str, ...]
    lap_m: float
    _t: list[float] = field(default_factory=list)
    _lap: list[float] = field(default_factory=list)
    _est: list[Array] = field(default_factory=list)
    _conf: list[Array] = field(default_factory=list)
    _truth: list[Array] = field(default_factory=list)
    _battle: dict[str, float] = field(default_factory=dict)
    _next_t: float = 0.0
    calls: list[CallContext] = field(default_factory=list)
    _due_lap: list[int] = field(default_factory=list)
    _order: list[list[str]] = field(default_factory=list)
    _interval: list[dict[str, float]] = field(default_factory=list)
    _speed: list[dict[str, float]] = field(default_factory=list)
    _alert_truth: dict[str, tuple[float, float]] = field(default_factory=dict)

    def sample(self, view: EngineerView, truth_mj: dict[str, float],
               speed_kmh: dict[str, float] | None = None) -> None:  # fmt: skip
        """Store one sample if ``SAMPLE_S`` has passed (call every tick).

        ``speed_kmh``: every car's TRUE speed (race graphs, released after the flag).
        """
        if view.t_s < self._next_t:
            return
        self._next_t = view.t_s + SAMPLE_S
        self._t.append(view.t_s)
        oc = view.our_car
        self._lap.append(max(oc.lap, 0) + oc.s_m / self.lap_m + (1.0 if oc.lap >= 0 else 0.0))
        self._est.append(np.array([view.radar[d].energy_mj for d in self.rivals]))
        self._conf.append(np.array([view.radar[d].confidence for d in self.rivals]))
        self._truth.append(np.array([truth_mj[d] for d in self.rivals]))
        order, interval = view.timing.order, view.timing.interval_s
        self._order.append(list(order))
        self._interval.append(dict(interval))
        self._speed.append(dict(speed_kmh or {}))
        if self.our in order:
            k = order.index(self.our)
            if k > 0 and (interval.get(self.our) or 99.0) <= BATTLE_GAP_S:
                self._battle[order[k - 1]] = self._battle.get(order[k - 1], 0.0) + SAMPLE_S
            if k + 1 < len(order) and (interval.get(order[k + 1]) or 99.0) <= BATTLE_GAP_S:
                self._battle[order[k + 1]] = self._battle.get(order[k + 1], 0.0) + SAMPLE_S

    def on_alert(self, alert_id: str, rival_truth_mj: float, our_mj: float) -> None:
        """Keep the Rival's TRUE battery and ours when an alert fired (graphs, after the flag)."""
        self._alert_truth[alert_id] = (rival_truth_mj, our_mj)

    def on_call(self, record: CallRecord, rival: str | None, view: EngineerView,
                truth_mj: dict[str, float]) -> None:  # fmt: skip
        """Remember a call with its context (``rival`` None: the car ahead, else behind)."""
        position, gap, ahead, behind = _place(view, self.our)
        about = rival or ahead or behind
        est = view.radar[about].energy_mj if about in view.radar else None
        self.calls.append(
            CallContext(record, about, est, truth_mj.get(about) if about else None, position, gap)
        )
        self._due_lap.append(record.lap + AFTER_LAPS)

    def after(self, view: EngineerView, finished: bool) -> None:
        """Fill the outcomes ``AFTER_LAPS`` laps after each call (or at the flag)."""
        lap = max(view.our_car.lap, 0) + 1
        for context, due in zip(self.calls, self._due_lap, strict=True):
            if context.position_after is None and (lap >= due or finished):
                context.position_after, context.gap_after_s, _, _ = _place(view, self.our)

    def reveal(self) -> RevealData:
        """Return the Reveal (call only after the flag)."""
        est, conf, truth = (np.array(x) for x in (self._est, self._conf, self._truth))
        known = conf > 0.0
        mae = float(np.abs(est - truth)[known].mean()) if known.any() else float("nan")
        top = sorted(self._battle, key=lambda d: -self._battle[d])[:TOP_RIVALS]
        series = []
        for d in top:
            k = self.rivals.index(d)
            series.append(RivalSeries(d, self._battle[d], np.array(self._lap), np.array(self._t),
                                      est[:, k], conf[:, k], truth[:, k]))  # fmt: skip
        off = sum(c.error_mj is not None and abs(c.error_mj) > OFF_MJ for c in self.calls)
        return RevealData(series, list(self.calls), mae, off)

    def samples(self) -> RevealSamples:
        """Return every sample (call only after the flag)."""
        cars = (self.our, *self.rivals)
        speed = {d: np.array([s.get(d, np.nan) for s in self._speed]) for d in cars}
        n_rivals = len(self.rivals)

        def table(rows: list[Array]) -> Array:
            return np.array(rows) if rows else np.zeros((0, n_rivals))

        return RevealSamples(
            self.rivals, np.array(self._t), np.array(self._lap), list(self._order),
            list(self._interval), table(self._est), table(self._conf), table(self._truth),
            speed, dict(self._alert_truth), dict(self._battle),
        )  # fmt: skip


def _place(view: EngineerView, our: str) -> tuple[int, float | None, str | None, str | None]:
    """Our position, gap to the car ahead, and the cars ahead and behind (public timing)."""
    order = view.timing.order
    k = order.index(our) if our in order else len(order) - 1
    gap = view.timing.interval_s.get(our) if k > 0 else None
    ahead = order[k - 1] if k > 0 else None
    behind = order[k + 1] if k + 1 < len(order) else None
    return k + 1, gap, ahead, behind

"""Live plug-in for the pit wall: ``create(cfg, track)`` -> provider (bridge section 2).

The pit wall calls ``provider.update(view)`` a few times a second with ``t_s``,
``our_car`` (exact), ``timing``, ``rival_feed`` (the last 120 s of frames per
car) and ``radar`` (the sim's own estimates: never used here). The provider is
incremental: each rival's :class:`~simply_clipping.energy.CarTracker` gets only
the frames it has not seen, and the rule :class:`~simply_clipping.alerts.Engine`
is evaluated on the same tick grid as the bench, up to ``alerts.latency_s``
before now, so the bench and the pit wall give the same alerts on the same data.

Alerts are plain objects with the fields of the sim's ``Alert`` /
``AlertEvidence``; this package never imports the sim (SC-R01).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from simply_clipping.alerts import AlertRow, Engine, OwnTrack, ticks
from simply_clipping.battles import History
from simply_clipping.energy import CarTracker, calibrated
from simply_clipping.loader import Config, Track, const, load_config


@dataclass(frozen=True)
class LiveEvidence:
    """The fields of the sim's ``AlertEvidence``."""

    our_mj: float
    rival_mj: float | None
    dv_kmh: float | None
    gap_s: float | None
    rival_state: str | None
    last_clip_s_m: float | None
    branch: str | None = None
    detection_share: float | None = None
    need_mj: float | None = None
    rival_basis: str | None = None


@dataclass(frozen=True)
class LiveAlert:
    """The fields of the sim's ``Alert``."""

    alert_id: str
    type: str
    rival: str
    lap: int
    corner_id: str | None
    evidence: LiveEvidence
    confidence: float
    created_t: float
    expires_t: float


def to_live(row: AlertRow, cfg: Config) -> LiveAlert:
    """Return an alert row as the pit wall shows it."""
    ev = LiveEvidence(
        row.our_mj,
        row.rival_mj,
        row.dv_kmh,
        row.gap_s,
        row.rival_state,
        row.last_clip_s_m,
        row.branch,
        row.detection_share,
        row.need_mj,
    )
    expires = row.time_s + float(const(cfg, "alerts.expires_s"))
    return LiveAlert(
        f"SC-{row.type}-{row.car_b}-{row.time_s:.1f}",
        row.type,
        row.car_b,
        row.lap,
        row.corner_id,
        ev,
        row.confidence,
        row.time_s,
        expires,
    )


def track_from(track: Any) -> Track:
    """Return a :class:`Track` from the layout dict, a Track, or the pit wall's track object."""
    if isinstance(track, Track):
        return track
    if isinstance(track, dict):
        return Track.from_layout(track)
    return Track.from_layout(
        {
            "track_id": getattr(track, "track_id", ""),
            "length_m": track.official_length_m,
            "zones": [
                {
                    "zone_id": z.zone_id,
                    "s_start_m": z.s_start_m,
                    "s_end_m": z.s_end_m,
                    "tags": list(z.tags),
                }
                for z in track.zones
            ],
            "corners": [{"corner_id": c.corner_id, "s_m": c.s_m} for c in track.corners],
        }
    )


class Provider:
    """Simply Clipping on the live pit wall."""

    def __init__(self, sim_cfg: Any, track: Any, cfg: Config | None = None) -> None:
        """``sim_cfg``: the pit wall's alert settings (unused: ours are in config.yaml)."""
        self.cfg = cfg if cfg is not None else load_config()
        self.track = track_from(track)
        keep = float(const(self.cfg, "alerts.history_s"))
        self.trackers: dict[str, CarTracker] = {}
        self.histories: dict[str, History] = {}
        self._lap: dict[str, tuple[int, float, float]] = {}  # lap, last lap distance, last t
        self.own = OwnTrack(self.cfg, self.track.length_m, keep)
        self.engine: Engine | None = None
        self._next_tick: float | None = None
        self.active: list[AlertRow] = []
        self._pending: dict[str, list[tuple[float, float, float, bool, float]]] = {}
        self._last_push = -np.inf

    def update(self, view: Any) -> list[LiveAlert]:
        """Feed the new data, evaluate the ticks now due, return the alerts active now."""
        now, oc = float(view.t_s), view.our_car
        if self.engine is None:
            self.engine = Engine(str(oc.driver_id), self.track, self.cfg)
        self.own.add(
            now,
            int(oc.lap),
            float(oc.s_m),
            float(oc.v_ms),
            float(oc.battery_mj),
            100.0 * float(oc.throttle),
            float(oc.brake) > 0.5,
        )
        for driver, frames in view.rival_feed.items():
            if driver != oc.driver_id and frames:
                self._read(str(driver), frames, int(oc.lap), float(oc.s_m))
        if now - self._last_push >= float(const(self.cfg, "alerts.feed_batch_s")):
            self._push_all()  # few larger pushes: the trackers are chunk-invariant
            self._last_push = now
        due = now - float(const(self.cfg, "alerts.latency_s"))
        if self._next_tick is None:  # the first tick is the first one at or after the first update
            self._next_tick = float(
                ticks(now, now + float(const(self.cfg, "alerts.tick_s")), self.cfg)[0]
            )
        for t in ticks(self._next_tick, due, self.cfg):
            us = self.own.at(float(t))
            if us is not None:
                self.active += self.engine.evaluate(us, self.histories)
            self._next_tick = float(t) + float(const(self.cfg, "alerts.tick_s"))
        expires = float(const(self.cfg, "alerts.expires_s"))
        self.active = [r for r in self.active if now < r.time_s + expires]
        return [to_live(r, self.cfg) for r in self.active]

    def _read(self, driver: str, frames: list[Any], our_lap: int, our_s: float) -> None:
        """Queue the frames not seen yet, with race progress from the counted laps."""
        lap_m = self.track.length_m
        if driver not in self.trackers:
            self.trackers[driver] = CarTracker(driver, "", self.track, self.cfg)
            self.histories[driver] = History(float(const(self.cfg, "alerts.history_s")))
            d0 = float(frames[0].distance_m)
            lap = (
                our_lap
                - (1 if d0 - our_s > lap_m / 2 else 0)
                + (1 if our_s - d0 > lap_m / 2 else 0)
            )
            self._lap[driver] = (lap, d0, -np.inf)
        lap, last_d, last_t = self._lap[driver]
        first_new = len(frames)
        while first_new > 0 and frames[first_new - 1].t_s > last_t:  # frames are time ordered
            first_new -= 1
        rows = []
        for f in frames[first_new:]:
            d = float(f.distance_m)
            if d < last_d - lap_m / 2:
                lap += 1
            last_d, last_t = d, float(f.t_s)
            rows.append(
                (
                    last_t,
                    float(f.speed_kmh),
                    float(f.throttle_pct),
                    bool(f.brake),
                    (lap - 1) * lap_m + d,
                )
            )
        self._lap[driver] = (lap, last_d, last_t)
        self._pending.setdefault(driver, []).extend(rows)

    def _push_all(self) -> None:
        for driver, rows in self._pending.items():
            if not rows:
                continue
            t, v, thr, brk, prog = (np.array(c) for c in zip(*rows, strict=True))
            est = self.trackers[driver].push(t, v, thr, brk.astype(bool), prog)
            self.histories[driver].append(est, calibrated(est.raw_confidence, self.cfg))
            rows.clear()


def create(cfg: Any, track: Any) -> Provider:
    """Return the provider; the pit wall calls this once (``external:simply_clipping``)."""
    return Provider(cfg, track)

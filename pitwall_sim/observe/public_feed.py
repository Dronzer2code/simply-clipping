"""F10 Public Feed: noisy 4 Hz Rival telemetry plus public timing (T-050).

Each feed interval (``1 / feed.rate_hz``; the race engine's tick) every running
car on track emits one frame unless it is dropped (``feed.drop_p``). Noise, all
on RNG stream ``feed_noise`` (HR-04), follows TRD PUBLIC FEED:

- ``speed_kmh``: Gaussian, sigma ``feed.speed_noise_kmh``;
- ``throttle_pct``: Gaussian, sigma ``feed.throttle_noise_pct``, quantised to 1 %,
  clipped to 0-100;
- ``brake`` (on/off) and ``gear`` exact; gears are not simulated, so the gear is
  the band of ``feed.gear_upshift_kmh`` the true speed falls in;
- ``x_m``, ``y_m``: the car's centre-line point plus Gaussian noise, sigma
  ``feed.position_noise_m`` per axis;
- ``distance_m``: lap distance derived from that noisy position (the noise along
  the track adds to the true ``s``).

Frames are kept column-wise per tick for the last ``feed.window_s`` seconds and
turned into :class:`PublicFeedFrame` objects only when read (EngineerView,
Radar), so a headless race pays little for the feed. Our Car is not in the feed
(the engineer sees its Ground Truth).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import FeedConfig
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.race import step_kernel as K

__all__ = ["PublicFeed", "PublicFeedFrame"]

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]

MS_TO_KMH = 3.6


@dataclass
class _Tick:
    """One emission: the kept cars' true values and their drawn noise.

    The noisy, quantised and derived fields are computed on first read
    (``columns``); emitting stays cheap for headless races.
    """

    t_s: float
    car: npt.NDArray[np.int64]
    v_ms: FloatArray
    throttle: FloatArray
    brake: BoolArray
    s_m: FloatArray
    noise: FloatArray
    """(4, cars): speed km/h, throttle %, x m, y m."""
    decoded: dict[str, npt.NDArray[np.generic]] | None = None
    frames: list[PublicFeedFrame] | None = None
    """The emission as frames, built on first read (EngineerViews reuse them)."""


#: Emissions' worth of random draws taken from the ``feed_noise`` stream at once.
FEED_BLOCK = 256


class PublicFeed:
    """Emits and buffers the Public Feed for one race."""

    def __init__(
        self,
        cfg: FeedConfig,
        rng: np.random.Generator,
        driver_ids: tuple[str, ...],
        centre_x_m: FloatArray,
        centre_y_m: FloatArray,
        heading_rad: FloatArray,
        length_m: float,
        hidden: tuple[str, ...] = (),
    ) -> None:
        """Set up the feed; ``hidden`` drivers (Our Car) never appear in it."""
        self.cfg = cfg
        self.rng = rng
        self.driver_ids = driver_ids
        self.x, self.y, self.heading = centre_x_m, centre_y_m, heading_rad
        self.length_m = length_m
        self.ds_m = length_m / centre_x_m.size
        self.public = np.array([d not in hidden for d in driver_ids], dtype=np.bool_)
        self.gear_bounds_ms = np.asarray(cfg.gear_upshift_kmh, dtype=np.float64) / MS_TO_KMH
        self.ticks: deque[_Tick] = deque()
        """Emissions of the last ``feed.window_s`` seconds, oldest first."""
        self._sigmas = np.array(
            [[cfg.speed_noise_kmh], [cfg.throttle_noise_pct], [cfg.position_noise_m],
             [cfg.position_noise_m]]
        )  # fmt: skip
        self.emitted = 0
        self.dropped = 0
        # Draws come in blocks (one RNG call per FEED_BLOCK emissions, not two per emission).
        self._uniform = np.empty(0)
        self._normal = np.empty((4, 0))

    def gear(self, v_ms: FloatArray) -> npt.NDArray[np.int64]:
        """Gear for each speed: 1 + the number of upshift speeds below it."""
        return (1 + np.searchsorted(self.gear_bounds_ms, v_ms, side="right")).astype(np.int64)

    def emit(self, t_s: float, st: K.KernelState, ctl: K.KernelControls) -> int:
        """Emit this interval's frames; return how many were kept (not dropped)."""
        cars = np.flatnonzero(self.public & st.running & ~st.in_pit)
        n = cars.size
        if n == 0:
            return 0
        if self._uniform.size < n:
            size = FEED_BLOCK * self.public.size
            self._uniform = self.rng.random(size)
            self._normal = self.rng.standard_normal((4, size))
        keep = self._uniform[:n] >= self.cfg.drop_p
        noise = self._normal[:, :n] * self._sigmas  # speed, throttle, x, y
        self._uniform, self._normal = self._uniform[n:], self._normal[:, n:]
        kept = cars[keep]
        self.dropped += n - kept.size
        if kept.size:
            self.ticks.append(
                _Tick(t_s, kept, st.v_ms[kept], ctl.throttle[kept], ctl.brake[kept] > 0.0,
                      st.s_m[kept], noise[:, keep])
            )  # fmt: skip
            self.emitted += kept.size
        while self.ticks and self.ticks[0].t_s <= t_s - self.cfg.window_s:
            self.ticks.popleft()
        return int(kept.size)

    def columns(self, tick: _Tick) -> dict[str, npt.NDArray[np.generic]]:
        """Compute (once) the published noisy, quantised and derived values of an emission."""
        if tick.decoded is None:
            k = (tick.s_m / self.ds_m).astype(np.int64) % self.x.size
            nx, ny = tick.noise[2], tick.noise[3]
            h = self.heading[k]
            tick.decoded = {
                "speed_kmh": tick.v_ms * MS_TO_KMH + tick.noise[0],
                "throttle_pct": np.clip(np.round(tick.throttle * 100.0 + tick.noise[1]), 0, 100),
                "brake": tick.brake,
                "gear": self.gear(tick.v_ms),
                "x_m": self.x[k] + nx,
                "y_m": self.y[k] + ny,
                "distance_m": (tick.s_m + nx * np.cos(h) + ny * np.sin(h)) % self.length_m,
            }
        return tick.decoded

    def frames(self, driver_id: str, since_s: float = -np.inf) -> list[PublicFeedFrame]:
        """One driver's frames still in the window, after ``since_s``, oldest first."""
        return self.recent(since_s).get(driver_id, [])

    def recent(self, since_s: float = -np.inf) -> dict[str, list[PublicFeedFrame]]:
        """Every public driver's frames in the window (EngineerView ``rival_feed``)."""
        out: dict[str, list[PublicFeedFrame]] = {
            d: [] for d, shown in zip(self.driver_ids, self.public, strict=True) if shown
        }
        for tick in self.ticks:
            if tick.t_s <= since_s:
                continue
            for frame in self._frames(tick):
                out[frame.driver_id].append(frame)
        return out

    def _frames(self, tick: _Tick) -> list[PublicFeedFrame]:
        """Decode an emission into frames once (frames are immutable)."""
        if tick.frames is None:
            c = self.columns(tick)
            tick.frames = [
                PublicFeedFrame(
                    t_s=tick.t_s,
                    driver_id=self.driver_ids[car],
                    speed_kmh=float(c["speed_kmh"][r]),
                    throttle_pct=float(c["throttle_pct"][r]),
                    brake=bool(c["brake"][r]),
                    gear=int(c["gear"][r]),
                    x_m=float(c["x_m"][r]),
                    y_m=float(c["y_m"][r]),
                    distance_m=float(c["distance_m"][r]),
                )
                for r, car in enumerate(tick.car.tolist())
            ]
        return tick.frames

"""F11 Radar, pure-Python reference implementation (T-051; owner round 15).

The live Radar (``energy.py``) is compiled with Numba; this is the readable
version it is tested against. Same algorithm, same constants.

Original description:

:class:`RadarEstimator` follows one Rival from its Public Feed frames,
incrementally (``update`` with the new frames; the live worker) or in one go
(:func:`estimate_batch`; headless runs). Per 10 Hz resampled point:

4. ``CdA`` per aero mode, fitted online by least squares on full-throttle
   samples in ``fit_min_speed_kmh .. fit_max_speed_kmh`` assuming full
   deployment there (``P_ICE + P_elec_max``). Until a mode has
   ``fit_min_samples`` the other mode's fit is used; until either has, the
   estimate waits (confidence 0).
5. State: HARVEST braking; LIFT throttle under ``lift_throttle_pct``; DEPLOY
   ``P_elec`` above ``state_threshold_kw``; CLIP full throttle without that
   (energy gone, or super-clipping); CRUISE otherwise.
6. Energy: minus ``P_elec`` while deploying, plus the braking power the MGU-K can
   take (up to ``p_elec_max``) while braking; clamped to ``[0, e_max]``.
7. Re-anchor to 0 after ``anchor_min_s`` of CLIP inside a Straight Mode zone
   (a long straight).
8. Confidence: halves every ``confidence_half_life_s`` since the last anchor (or
   the car's first frame, while the battery is taken as ``start_energy_mj`` with
   weight ``start_prior_confidence``), times the share of feed frames received
   over the last ``missing_window_s``.

Only feed values, the public Straight Mode zones and ``radar.*`` constants are
used (TRD: never the simulator's true values).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from pitwall_sim.config.models import RadarConfig
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.observe.radar.energy import RadarEstimate, RadarState
from pitwall_sim.observe.radar.physics import (
    KMH_TO_MS,
    electric_power_w,
    savgol_coefficients,
    wheel_power_w,
)

MJ = 1e6


@dataclass
class _ModeFit:
    """Online least squares ``y = CdA * x`` for one aero mode."""

    sxx: float = 0.0
    sxy: float = 0.0
    n: int = 0

    def add(self, x: float, y: float) -> None:
        self.sxx += x * x
        self.sxy += x * y
        self.n += 1

    def cda(self) -> float:
        return self.sxy / self.sxx if self.sxx > 0.0 else math.nan


@dataclass
class ReferenceRadarEstimator:
    """One Rival's battery estimate, updated frame by frame."""

    driver_id: str
    cfg: RadarConfig
    straight_mode_zones: list[tuple[float, float]]
    """Public Straight Mode zones ``(s_start, s_end)``; may cross s = 0."""
    lap_length_m: float
    feed_rate_hz: float
    """Public: lap length and the feed's nominal rate."""
    energy_j: float = field(init=False)
    state: RadarState = field(init=False, default="CRUISE")
    anchor_t_s: float = field(init=False, default=math.nan)
    weight: float = field(init=False, default=1.0)
    """Confidence weight: the start prior's until the first anchor."""
    last_clip_s_m: float | None = field(init=False, default=None)
    fits: dict[bool, _ModeFit] = field(init=False)
    """Per aero mode: True = Straight Mode."""

    def __post_init__(self) -> None:
        """Smoothing weights, fits and buffers."""
        cfg = self.cfg
        self.dt = 1.0 / cfg.resample_hz
        self.smooth = savgol_coefficients(cfg.savgol_window, cfg.savgol_order, 0, self.dt)
        self.deriv = savgol_coefficients(cfg.savgol_window, cfg.savgol_order, 1, self.dt)
        self.energy_j = cfg.start_energy_mj * MJ
        self.weight = cfg.start_prior_confidence
        self.fits = {True: _ModeFit(), False: _ModeFit()}
        self._raw: deque[PublicFeedFrame] = deque(maxlen=64)
        self._grid_t: float | None = None
        self._window: deque[tuple[float, float, float, bool, float]] = deque(
            maxlen=cfg.savgol_window
        )  # (t, v_ms, throttle_pct, brake, distance_m) on the resampled grid
        self._frame_times: deque[float] = deque()
        self._clip_since: float | None = None
        self._t = 0.0

    # ------------------------------------------------------------------ #

    def update(self, frames: list[PublicFeedFrame]) -> RadarEstimate:
        """Take the frames received since the last call; return the estimate now."""
        for frame in frames:
            self._frame_times.append(frame.t_s)
            if not self._raw and math.isnan(self.anchor_t_s) and self.weight > 0.0:
                self.anchor_t_s = frame.t_s  # the prior starts with the first frame
            if self._raw and frame.t_s <= self._raw[-1].t_s:
                continue
            self._raw.append(frame)
            self._resample_to(frame.t_s)
        return self.estimate()

    def estimate(self) -> RadarEstimate:
        """Return the current estimate."""
        return RadarEstimate(
            t_s=self._t,
            driver_id=self.driver_id,
            energy_mj=self.energy_j / MJ,
            state=self.state,
            confidence=self.confidence(self._t),
            last_clip_s_m=self.last_clip_s_m,
            prior=self.weight < 1.0,
        )

    def confidence(self, t_s: float) -> float:
        """Step 8: decay since the last anchor times the share of frames received."""
        cfg = self.cfg
        if math.isnan(self._cda(True)) and math.isnan(self._cda(False)):
            return 0.0  # no CdA fit yet
        if math.isnan(self.anchor_t_s):
            return 0.0  # no anchor (and no prior) yet: unknown
        decay = self.weight * float(
            0.5 ** (max(t_s - self.anchor_t_s, 0.0) / cfg.confidence_half_life_s)
        )
        while self._frame_times and self._frame_times[0] < t_s - cfg.missing_window_s:
            self._frame_times.popleft()
        expected = cfg.missing_window_s * self.feed_rate_hz
        received = min(len(self._frame_times) / expected, 1.0) if expected > 0 else 1.0
        return decay * received

    # ------------------------------------------------------------------ #

    def _resample_to(self, t_end: float) -> None:
        """Step 1: put new 10 Hz grid points up to ``t_end`` through the smoother."""
        raw = self._raw
        if len(raw) < 2:
            self._grid_t = raw[0].t_s if raw else None
            return
        assert self._grid_t is not None
        t = np.array([f.t_s for f in raw])
        grid = np.arange(self._grid_t, t_end + 1e-9, self.dt)
        if grid.size == 0:
            return
        v = np.interp(grid, t, [f.speed_kmh * KMH_TO_MS for f in raw])
        thr = np.interp(grid, t, [f.throttle_pct for f in raw])
        brk = np.interp(grid, t, [1.0 if f.brake else 0.0 for f in raw]) >= 0.5
        dist = np.interp(grid, t, np.unwrap([f.distance_m for f in raw], period=self.lap_length_m))
        for k in range(grid.size):
            self._window.append(
                (float(grid[k]), float(v[k]), float(thr[k]), bool(brk[k]), float(dist[k]))
            )
            if len(self._window) == self.cfg.savgol_window:
                self._process()
        self._grid_t = float(grid[-1] + self.dt)

    def _cda(self, straight: bool) -> float:
        own, other = self.fits[straight], self.fits[not straight]
        if own.n >= self.cfg.fit_min_samples:
            return float(own.cda())
        if other.n >= self.cfg.fit_min_samples:
            return float(other.cda())
        return math.nan

    def _in_straight_mode(self, s_m: float) -> bool:
        s = s_m % self.lap_length_m
        for start, end in self.straight_mode_zones:
            if (start <= s < end) if start <= end else (s >= start or s < end):
                return True
        return False

    def _process(self) -> None:
        """Run steps 2-7 for the window's centre sample."""
        cfg = self.cfg
        window = np.array([(w[1]) for w in self._window])
        v = float(self.smooth @ window)
        a = float(self.deriv @ window)
        t, _, throttle, brake, distance = self._window[cfg.savgol_window // 2]
        dt = self.dt
        self._t = t
        straight = self._in_straight_mode(distance)
        mass, rho, c_rr, eta = cfg.mass_kg, cfg.rho, cfg.c_rr, cfg.eta
        p_ice, p_elec_max = cfg.p_ice_kw * 1e3, cfg.p_elec_max_kw * 1e3
        full = throttle >= cfg.full_throttle_pct and not brake

        # Step 4: CdA from full-throttle straight-start samples (full deployment).
        fit_window = cfg.fit_min_speed_kmh * KMH_TO_MS <= v <= cfg.fit_max_speed_kmh * KMH_TO_MS
        if full and straight and fit_window:  # straight starts only (TRD step 4)
            x = 0.5 * rho * v**3
            y = eta * (p_ice + p_elec_max) - mass * a * v - c_rr * mass * 9.80665 * v
            self.fits[straight].add(x, y)
        cda = self._cda(straight)
        if math.isnan(cda):  # no fit yet: nothing to integrate
            return

        p_wheel = float(wheel_power_w(v, a, cda, mass, rho, c_rr))
        p_elec = electric_power_w(p_wheel, eta, p_ice)
        # Step 5: state.
        if brake:
            state: RadarState = "HARVEST"
        elif throttle < cfg.lift_throttle_pct:
            state = "LIFT"
        elif p_elec > cfg.state_threshold_kw * 1e3:
            state = "DEPLOY"
        elif full:
            state = "CLIP"
        else:
            state = "CRUISE"
        self.state = state

        # Step 6: energy.
        if state == "DEPLOY":
            self.energy_j -= min(p_elec, p_elec_max) * dt
        elif state == "HARVEST":
            self.energy_j += min(max(-p_wheel, 0.0), p_elec_max) * dt
        self.energy_j = min(max(self.energy_j, 0.0), cfg.e_max_mj * MJ)

        # Step 7: re-anchor at a sustained clip on a long straight.
        if state == "CLIP" and straight:
            if self._clip_since is None:
                self._clip_since = t
            elif t - self._clip_since >= cfg.anchor_min_s:
                self.energy_j = 0.0
                self.anchor_t_s = t
                self.weight = 1.0
                self.last_clip_s_m = distance % self.lap_length_m
        else:
            self._clip_since = None


def reference_estimate_batch(
    driver_id: str,
    frames: list[PublicFeedFrame],
    cfg: RadarConfig,
    straight_mode_zones: list[tuple[float, float]],
    lap_length_m: float,
    feed_rate_hz: float,
) -> RadarEstimate:
    """Run one Rival's frames through a fresh estimator (headless batch mode)."""
    estimator = ReferenceRadarEstimator(
        driver_id, cfg, straight_mode_zones, lap_length_m, feed_rate_hz
    )
    return estimator.update(frames)

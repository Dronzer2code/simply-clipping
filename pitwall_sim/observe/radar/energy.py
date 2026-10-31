"""F11 Radar energy model: state, energy, anchors, confidence (T-051, TRD steps 4-8).

Compiled with Numba (owner round 15): :class:`RadarBank` holds the Radar state of
many cars in arrays and takes each feed frame as it arrives (the race engine
pushes every feed tick for all cars in one call, NFR-02); :class:`RadarEstimator`
is one Rival (a bank of one) with the frame-list API the EngineerView and tests
use. ``reference.py`` is the readable pure-Python version this one is tested
against. Per 10 Hz resampled point:

4. ``CdA`` per aero mode, fitted online by least squares on full-throttle
   samples in Straight Mode zones between ``fit_min_speed_kmh`` and
   ``fit_max_speed_kmh`` assuming full deployment (``P_ICE + P_elec_max``). Until
   a mode has ``fit_min_samples`` the other mode's fit is used; until either
   has, the estimate waits (confidence 0).
5. State: HARVEST braking; LIFT throttle under ``lift_throttle_pct``; DEPLOY
   ``P_elec`` above ``state_threshold_kw``; CLIP full throttle without that
   (energy gone, or super-clipping); CRUISE otherwise.
6. Energy: minus ``P_elec`` while deploying, plus the braking power the MGU-K can
   take (up to ``p_elec_max``) while braking; clamped to ``[0, e_max]``.
7. Re-anchor to 0 after ``anchor_min_s`` of CLIP inside a Straight Mode zone
   (a long straight).
8. Confidence: halves every ``confidence_half_life_s`` since the last anchor,
   times the share of feed frames received over the last ``missing_window_s``.
   Before a car's first anchor the estimate is the race-start prior (owner,
   sprint day 5): the battery assumed full (``start_energy_mj``) with
   confidence ``start_prior_confidence``, decaying with the same half-life from
   the car's first feed frame; the first anchor replaces it. With
   ``start_prior_confidence`` 0 the estimate is unknown until that anchor.

Only feed values, the public Straight Mode zones and ``radar.*`` constants are
used (TRD: never the simulator's true values).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.config.models import RadarConfig
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.observe.radar.physics import KMH_TO_MS, savgol_coefficients

type RadarState = Literal["DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE"]
type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]
MJ = 1e6
G_MS2 = 9.80665
STATES: tuple[RadarState, ...] = ("DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE")
DEPLOY, CLIP, HARVEST, LIFT, CRUISE = range(5)
#: State vector columns per car (_WEIGHT: confidence weight, the prior's until an anchor).
_ENERGY, _ANCHOR_T, _CLIP_SINCE, _LAST_CLIP_S, _T, _STATE, _WEIGHT = range(7)
#: Frame-time ring per car (frames over ``missing_window_s`` plus margin).
FRAME_RING = 256


@dataclass(frozen=True)
class RadarEstimate:
    """Estimated Rival battery (TRD DATA CONTRACTS)."""

    t_s: float
    driver_id: str
    energy_mj: float
    state: RadarState
    confidence: float
    last_clip_s_m: float | None
    prior: bool = False
    """The estimate still rests on the race-start prior (assumed full at start)."""


@njit(cache=True)
def _in_zones(s: float, starts: FloatArray, ends: FloatArray) -> bool:
    for k in range(starts.size):
        a, b = starts[k], ends[k]
        if (a <= s < b) if a <= b else (s >= a or s < b):
            return True
    return False


@njit(cache=True)
def _cda(fits: FloatArray, c: int, straight: int, min_samples: float) -> float:
    """CdA of one aero mode, the other mode's until it has enough samples, else NaN."""
    if fits[c, straight, 2] >= min_samples:
        return fits[c, straight, 1] / fits[c, straight, 0] if fits[c, straight, 0] > 0 else math.nan
    other = 1 - straight
    if fits[c, other, 2] >= min_samples:
        return fits[c, other, 1] / fits[c, other, 0] if fits[c, other, 0] > 0 else math.nan
    return math.nan


@njit(cache=True)
def _process(
    c: int,
    tail: FloatArray,
    state: FloatArray,
    fits: FloatArray,
    k: FloatArray,
    zone_starts: FloatArray,
    zone_ends: FloatArray,
    lap_length_m: float,
    smooth: FloatArray,
    deriv: FloatArray,
) -> None:
    """Run steps 1-7 for the centre of car ``c``'s full window (``tail[c]``: t, v, thr, brk, dist).

    ``k``: dt, mass, rho, c_rr, eta, p_ice_w, p_elec_max_w, e_max_j,
    full_throttle_pct, lift_throttle_pct, state_threshold_w, fit_min_ms,
    fit_max_ms, fit_min_samples, anchor_min_s.
    """
    window = smooth.size
    vs = 0.0
    acc = 0.0
    for j in range(window):
        vs += smooth[j] * tail[c, j, 1]
        acc += deriv[j] * tail[c, j, 1]
    centre = window // 2
    tc, thr, d = tail[c, centre, 0], tail[c, centre, 2], tail[c, centre, 4]
    brk = tail[c, centre, 3] >= 0.5
    dt, mass, rho, c_rr, eta, p_ice, p_elec_max, e_max = (
        k[0],
        k[1],
        k[2],
        k[3],
        k[4],
        k[5],
        k[6],
        k[7],
    )
    state[c, _T] = tc
    s_lap = d % lap_length_m
    straight = 1 if _in_zones(s_lap, zone_starts, zone_ends) else 0
    full = thr >= k[8] and not brk
    if full and straight == 1 and k[11] <= vs <= k[12]:  # step 4
        x = 0.5 * rho * vs**3
        y = eta * (p_ice + p_elec_max) - mass * acc * vs - c_rr * mass * G_MS2 * vs
        fits[c, straight, 0] += x * x
        fits[c, straight, 1] += x * y
        fits[c, straight, 2] += 1.0
    cda = _cda(fits, c, straight, k[13])
    if math.isnan(cda):
        return
    p_wheel = mass * acc * vs + 0.5 * rho * cda * vs**3 + c_rr * mass * G_MS2 * vs
    p_elec = p_wheel / eta - p_ice
    if brk:  # step 5
        code = HARVEST
    elif thr < k[9]:
        code = LIFT
    elif p_elec > k[10]:
        code = DEPLOY
    elif full:
        code = CLIP
    else:
        code = CRUISE
    state[c, _STATE] = code
    energy = state[c, _ENERGY]  # step 6
    if code == DEPLOY:
        energy -= min(p_elec, p_elec_max) * dt
    elif code == HARVEST:
        energy += min(max(-p_wheel, 0.0), p_elec_max) * dt
    state[c, _ENERGY] = min(max(energy, 0.0), e_max)
    if code == CLIP and straight == 1:  # step 7
        if math.isnan(state[c, _CLIP_SINCE]):
            state[c, _CLIP_SINCE] = tc
        elif tc - state[c, _CLIP_SINCE] >= k[14]:
            state[c, _ENERGY] = 0.0
            state[c, _ANCHOR_T] = tc
            state[c, _WEIGHT] = 1.0
            state[c, _LAST_CLIP_S] = s_lap
    else:
        state[c, _CLIP_SINCE] = math.nan


@njit(cache=True)
def _push(
    cars: IntArray,
    t: FloatArray,
    speed_kmh: FloatArray,
    throttle: FloatArray,
    brake: FloatArray,
    dist: FloatArray,
    state: FloatArray,
    fits: FloatArray,
    raw: FloatArray,
    grid: FloatArray,
    tail: FloatArray,
    tail_n: IntArray,
    frame_t: FloatArray,
    frame_n: IntArray,
    k: FloatArray,
    zone_starts: FloatArray,
    zone_ends: FloatArray,
    lap_length_m: float,
    smooth: FloatArray,
    deriv: FloatArray,
) -> None:
    """Take feed frames (any cars, in time order): resample each car to the grid, process."""
    window = smooth.size
    dt = k[0]
    half_lap = 0.5 * lap_length_m
    for f in range(cars.size):
        c = cars[f]
        tf = t[f]
        frame_t[c, frame_n[c] % FRAME_RING] = tf
        frame_n[c] += 1
        v = speed_kmh[f] * KMH_TO_MS
        if math.isnan(raw[c, 0]):  # the car's first frame starts its grid (and the prior)
            if math.isnan(state[c, _ANCHOR_T]) and state[c, _WEIGHT] > 0.0:
                state[c, _ANCHOR_T] = tf
            raw[c, 0], raw[c, 1], raw[c, 2], raw[c, 3], raw[c, 4] = (
                tf,
                v,
                throttle[f],
                brake[f],
                dist[f],
            )
            grid[c] = tf
            continue
        t0 = raw[c, 0]
        if tf <= t0:
            continue
        # np.unwrap(period = lap length) against the previous frame.
        dd = dist[f] - raw[c, 4]
        dd_mod = (dd + half_lap) % lap_length_m - half_lap
        if dd_mod == -half_lap and dd > 0.0:
            dd_mod = half_lap
        d1 = raw[c, 4] + (dd_mod if abs(dd) >= half_lap else dd)
        n_new = 0
        g = grid[c]
        while g <= tf + 1e-9:
            w = max((g - t0) / (tf - t0), 0.0)
            sample = (
                g,
                raw[c, 1] + w * (v - raw[c, 1]),
                raw[c, 2] + w * (throttle[f] - raw[c, 2]),
                raw[c, 3] + w * (brake[f] - raw[c, 3]),
                raw[c, 4] + w * (d1 - raw[c, 4]),
            )
            if tail_n[c] < window:
                pos = tail_n[c]
                tail_n[c] += 1
            else:
                for j in range(window - 1):
                    for q in range(5):
                        tail[c, j, q] = tail[c, j + 1, q]
                pos = window - 1
            for q in range(5):
                tail[c, pos, q] = sample[q]
            if tail_n[c] == window:
                _process(
                    c, tail, state, fits, k, zone_starts, zone_ends, lap_length_m, smooth, deriv
                )
            n_new += 1
            g = grid[c] + n_new * dt
        if n_new > 0:
            grid[c] = grid[c] + (n_new - 1) * dt + dt
        raw[c, 0], raw[c, 1], raw[c, 2], raw[c, 3], raw[c, 4] = tf, v, throttle[f], brake[f], d1


@njit(cache=True)
def _decode_feed(
    v_ms: FloatArray,
    throttle: FloatArray,
    s_m: FloatArray,
    noise: FloatArray,
    heading: FloatArray,
    lap_length_m: float,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Compute the published speed, throttle and lap distance (the Public Feed's formulas)."""
    n_pts = heading.size
    ds = lap_length_m / n_pts
    speed = v_ms * 3.6 + noise[0]
    thr = np.minimum(np.maximum(np.round(throttle * 100.0 + noise[1]), 0.0), 100.0)
    dist = np.empty(s_m.size)
    for i in range(s_m.size):
        h = heading[int(s_m[i] / ds) % n_pts]
        dist[i] = (s_m[i] + noise[2, i] * math.cos(h) + noise[3, i] * math.sin(h)) % lap_length_m
    return speed, thr, dist


@njit(cache=True)
def _energies(
    state: FloatArray, fits: FloatArray, frame_t: FloatArray, min_samples: float,
    half_life_s: float, missing_window_s: float, expected: float, with_prior: bool = True,
) -> tuple[FloatArray, FloatArray]:  # fmt: skip
    """Energy (MJ) and step-8 confidence of every car at its own latest frame time."""
    n = state.shape[0]
    energy = state[:, _ENERGY] / MJ
    confidence = np.zeros(n)
    for c in range(n):
        if math.isnan(_cda(fits, c, 1, min_samples)) and math.isnan(_cda(fits, c, 0, min_samples)):
            continue  # no CdA fit yet
        if math.isnan(state[c, _ANCHOR_T]):
            continue  # no anchor (and no prior) yet: unknown
        if not with_prior and state[c, _WEIGHT] < 1.0:
            continue  # still on the start prior: unknown to this reader
        t = state[c, _T]
        decay = state[c, _WEIGHT] * 0.5 ** (max(t - state[c, _ANCHOR_T], 0.0) / half_life_s)
        received = 0
        for x in frame_t[c]:
            if x >= t - missing_window_s:
                received += 1
        confidence[c] = decay * (min(received / expected, 1.0) if expected > 0 else 1.0)
    return energy, confidence


class RadarBank:
    """Compiled Radar state for ``n_cars`` cars (the race engine runs one per race)."""

    def __init__(
        self,
        n_cars: int,
        cfg: RadarConfig,
        straight_mode_zones: list[tuple[float, float]],
        lap_length_m: float,
        feed_rate_hz: float,
    ) -> None:
        """Every car starts with the battery at ``start_energy_mj`` (the prior) and no CdA fit."""
        self.cfg = cfg
        self.lap_length_m = lap_length_m
        self.feed_rate_hz = feed_rate_hz
        dt = 1.0 / cfg.resample_hz
        self.smooth = savgol_coefficients(cfg.savgol_window, cfg.savgol_order, 0, dt)
        self.deriv = savgol_coefficients(cfg.savgol_window, cfg.savgol_order, 1, dt)
        self.state = np.zeros((n_cars, 7))
        self.state[:, _ENERGY] = cfg.start_energy_mj * MJ
        self.state[:, _ANCHOR_T] = np.nan  # set to the first frame's time while a prior applies
        self.state[:, _WEIGHT] = cfg.start_prior_confidence
        self.state[:, _CLIP_SINCE] = np.nan
        self.state[:, _LAST_CLIP_S] = np.nan
        self.state[:, _STATE] = CRUISE
        self.fits = np.zeros((n_cars, 2, 3))
        self.raw = np.full((n_cars, 5), np.nan)
        self.grid = np.full(n_cars, np.nan)
        self.tail = np.zeros((n_cars, cfg.savgol_window, 5))
        self.tail_n = np.zeros(n_cars, dtype=np.int64)
        self.frame_t = np.full((n_cars, FRAME_RING), -np.inf)
        self.frame_n = np.zeros(n_cars, dtype=np.int64)
        self.consts = np.array([
            dt, cfg.mass_kg, cfg.rho, cfg.c_rr, cfg.eta, cfg.p_ice_kw * 1e3,
            cfg.p_elec_max_kw * 1e3, cfg.e_max_mj * MJ, cfg.full_throttle_pct,
            cfg.lift_throttle_pct, cfg.state_threshold_kw * 1e3,
            cfg.fit_min_speed_kmh * KMH_TO_MS, cfg.fit_max_speed_kmh * KMH_TO_MS,
            float(cfg.fit_min_samples), cfg.anchor_min_s,
        ])  # fmt: skip
        self.zone_starts = np.array([z[0] for z in straight_mode_zones], dtype=np.float64)
        self.zone_ends = np.array([z[1] for z in straight_mode_zones], dtype=np.float64)

    def push(
        self, cars: npt.ArrayLike, t: npt.ArrayLike, speed_kmh: npt.ArrayLike,
        throttle_pct: npt.ArrayLike, brake: npt.ArrayLike, distance_m: npt.ArrayLike,
    ) -> None:  # fmt: skip
        """Take feed frames as columns, in time order (``brake`` 0 / 1)."""
        _push(
            np.ascontiguousarray(cars, dtype=np.int64), np.ascontiguousarray(t, dtype=np.float64),
            np.ascontiguousarray(speed_kmh, dtype=np.float64),
            np.ascontiguousarray(throttle_pct, dtype=np.float64),
            np.ascontiguousarray(brake, dtype=np.float64),
            np.ascontiguousarray(distance_m, dtype=np.float64),
            self.state, self.fits, self.raw, self.grid, self.tail, self.tail_n, self.frame_t,
            self.frame_n, self.consts, self.zone_starts, self.zone_ends, self.lap_length_m,
            self.smooth, self.deriv,
        )  # fmt: skip

    def push_feed(
        self, cars: IntArray, t: FloatArray, v_ms: FloatArray, throttle: FloatArray,
        brake: npt.NDArray[np.bool_], s_m: FloatArray, noise: FloatArray, heading: FloatArray,
    ) -> None:  # fmt: skip
        """Take raw feed emissions (true values + drawn noise) and publish them first."""
        speed, thr, dist = _decode_feed(v_ms, throttle, s_m, noise, heading, self.lap_length_m)
        self.push(cars, t, speed, thr, brake.astype(np.float64), dist)

    def confidence(self, c: int, t_s: float) -> float:
        """Step 8 for car ``c`` at ``t_s``."""
        cfg = self.cfg
        min_n = float(cfg.fit_min_samples)
        if math.isnan(_cda(self.fits, c, 1, min_n)) and math.isnan(_cda(self.fits, c, 0, min_n)):
            return 0.0  # no CdA fit yet
        if math.isnan(self.state[c, _ANCHOR_T]):
            return 0.0  # no anchor (and no prior) yet: unknown
        decay = float(
            self.state[c, _WEIGHT]
            * 0.5 ** (max(t_s - self.state[c, _ANCHOR_T], 0.0) / cfg.confidence_half_life_s)
        )
        received = int(np.count_nonzero(self.frame_t[c] >= t_s - cfg.missing_window_s))
        expected = cfg.missing_window_s * self.feed_rate_hz
        return decay * (min(received / expected, 1.0) if expected > 0 else 1.0)

    def energies(self, with_prior: bool = True) -> tuple[FloatArray, FloatArray]:
        """Every car's estimated energy (MJ) and confidence, as :meth:`estimate` gives them.

        ``with_prior=False``: confidence 0 while a car's estimate still rests on the
        race-start prior (the Rival Strategy AI reads it so).
        """
        cfg = self.cfg
        return _energies(
            self.state, self.fits, self.frame_t, float(cfg.fit_min_samples),
            cfg.confidence_half_life_s, cfg.missing_window_s,
            cfg.missing_window_s * self.feed_rate_hz, with_prior,
        )  # fmt: skip

    def estimate(self, c: int, driver_id: str) -> RadarEstimate:
        """Car ``c``'s estimate now (read at the Rival Strategy decision tick)."""
        t = float(self.state[c, _T])
        last = float(self.state[c, _LAST_CLIP_S])
        return RadarEstimate(
            t_s=t,
            driver_id=driver_id,
            energy_mj=float(self.state[c, _ENERGY]) / MJ,
            state=STATES[int(self.state[c, _STATE])],
            confidence=self.confidence(c, t),
            last_clip_s_m=None if math.isnan(last) else last,
            prior=bool(self.state[c, _WEIGHT] < 1.0),
        )


class RadarEstimator:
    """One Rival's battery estimate from its Public Feed frames (a bank of one)."""

    def __init__(
        self,
        driver_id: str,
        cfg: RadarConfig,
        straight_mode_zones: list[tuple[float, float]],
        lap_length_m: float,
        feed_rate_hz: float,
    ) -> None:
        """Start the estimate with the battery at ``start_energy_mj``."""
        self.driver_id = driver_id
        self.cfg = cfg
        self.bank = RadarBank(1, cfg, straight_mode_zones, lap_length_m, feed_rate_hz)

    def update(self, frames: list[PublicFeedFrame]) -> RadarEstimate:
        """Take the frames received since the last call; return the estimate now."""
        if frames:
            self.bank.push(
                np.zeros(len(frames), dtype=np.int64),
                np.array([f.t_s for f in frames]),
                np.array([f.speed_kmh for f in frames]),
                np.array([f.throttle_pct for f in frames]),
                np.array([f.brake for f in frames], dtype=np.float64),
                np.array([f.distance_m for f in frames]),
            )
        return self.estimate()

    def estimate(self) -> RadarEstimate:
        """Return the current estimate."""
        return self.bank.estimate(0, self.driver_id)

    @property
    def energy_j(self) -> float:
        """Estimated battery energy, J."""
        return float(self.bank.state[0, _ENERGY])

    @property
    def anchor_t_s(self) -> float:
        """Time of the last re-anchor (the first frame's while on the prior; NaN before)."""
        return float(self.bank.state[0, _ANCHOR_T])

    @property
    def anchored(self) -> bool:
        """A real anchor (sustained CLIP on a long straight) has replaced the prior."""
        return bool(self.bank.state[0, _WEIGHT] >= 1.0)

    @property
    def state(self) -> RadarState:
        """The latest classified state."""
        return STATES[int(self.bank.state[0, _STATE])]

    def cda(self, straight: bool) -> float:
        """Fitted CdA of an aero mode (NaN before a fit)."""
        return float(_cda(self.bank.fits, 0, int(straight), float(self.cfg.fit_min_samples)))

    def confidence(self, t_s: float) -> float:
        """Step 8 at ``t_s``."""
        return self.bank.confidence(0, t_s)


def estimate_batch(
    driver_id: str,
    frames: list[PublicFeedFrame],
    cfg: RadarConfig,
    straight_mode_zones: list[tuple[float, float]],
    lap_length_m: float,
    feed_rate_hz: float,
) -> RadarEstimate:
    """Run one Rival's frames through a fresh estimator (headless batch mode)."""
    estimator = RadarEstimator(driver_id, cfg, straight_mode_zones, lap_length_m, feed_rate_hz)
    return estimator.update(frames)

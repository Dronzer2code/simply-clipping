"""P6-P7 energy: states, deploy level, integration, anchors, confidence (SC-2).

One :class:`CarTracker` per car turns raw samples into per-point estimates. It is
streaming and causal: the bench pushes a whole race at once, the live pit wall a
few frames at a time, and both get the same numbers (``Stream`` is
chunk-invariant; CdA and ICE power are refitted only when the car crosses the
line, from the runs that closed before it).

Per 10 Hz point::

    P_wheel = m*a*v + 0.5*rho*CdA*v^3 + Crr*m*g*v     (CdA of the aero mode)
    P_elec  = P_wheel / eta - throttle * P_ICE
    deploy  = full throttle on a straight, at a speed where power shows in the speed
              trace: clip(P_elec, 0, MGU-K limit)              partial deploy (L-c)
              full throttle in a fast corner: P_elec if it clearly shows
              deploy (corner_seen_kw), else 0
              full throttle where power does not show (a slow exit, a slow
              corner: the tyres, not the power, limit the car): the car's own
              recent straight-line deploy level; in a slow corner the corner
              cap times the share of fast-corner points that showed deploy
              part throttle: clip(P_elec, 0, limit) * cruise_deploy_scale
    harvest = braking:  min(brake_share * braking power, harvest cap)
              lifting:  lift_harvest_kw
              super-clip (full throttle on a straight at speed, P_elec well below 0):
                        min(-P_elec, harvest cap)
              nothing else: full throttle in a corner reads as negative P_elec
              (cornering losses the model leaves out), not as harvest
    E      += (harvest - deploy) * dt, within the lap's harvest limit, clamped

States (spec STATES): HARVEST on the brake; LIFT below ``lift_throttle_pct``; at
full throttle DEPLOY above ``deploy_min_kw``, CLIP below ``clip_max_kw`` with the
speed flat or falling, CRUISE otherwise. Lesson L-b: in the regulated taper band
the MGU-K limit falls with speed, so a power drop the taper explains is not CLIP
(CLIP needs ``taper_margin_kw`` less than the taper allows).

Anchors: the race starts at ``anchor.start_mj`` (about full). The EMPTY anchor
(lesson L-a) fires only on the pattern of a battery that ran out: at full
throttle on a long straight (``anchor.min_straight_m``) the car neither deploys
(P_elec below ``anchor.no_deploy_kw``, more than the taper explains) nor
harvests (P_elec above ``anchor.superclip_kw``), from the first
``anchor.max_start_frac`` of the straight for ``anchor.min_clip_s``. An empty
car still accelerates there, so this is not the CLIP state (flat speed). A
super-clip near the straight end harvests (P_elec strongly negative) and is
integrated as harvest.

Confidence (L-e): the hit rate measured on seeds 1-5 (estimate within
``confidence.right_tol_mj`` of the truth) for the estimate's band and the time
since the last anchor (``confidence.table``), lowered by recent missing data.
Fitted, not assumed: on the tune set an estimate at a clamp (empty or full) or
just after an EMPTY anchor is right ~85 % of the time, a mid-range one early in
a stint ~20 %; accuracy grows, not falls, with time since the start.
"""

from __future__ import annotations

from dataclasses import dataclass

import numba
import numpy as np
import numpy.typing as npt
import pandas as pd

from simply_clipping.loader import Config, Track, const
from simply_clipping.physics import (
    KMH,
    CdaFit,
    Points,
    Run,
    RunBuilder,
    Stream,
    aero_modes,
    electric_power_kw,
    mass_kg,
    p_ice_kw,
    wheel_power_kw,
)

STATES = ("DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE")
DEPLOY, CLIP, HARVEST, LIFT, CRUISE = range(5)
ESTIMATE_COLUMNS = ("driver", "time_s", "energy_mj", "state", "confidence")
Array = npt.NDArray[np.float64]

# Integrator state vector slots (carried between pushes).
E_MJ, LAP_HARVEST_MJ, ANCHOR_T, MISS_S, LAST_T, CLIP_T0, CLIP_FRAC0, CLIP_ZONE = range(8)
CLIP_DONE, LEVEL_KW, CORNER_DEPLOY = 8, 9, 10
N_STATE = 11


@dataclass
class Estimates:
    """Per-point estimates of one car."""

    t_s: Array
    energy_mj: Array
    state: npt.NDArray[np.int8]
    raw_confidence: Array
    since_anchor_s: Array
    p_elec_kw: Array
    v_ms: Array
    progress_m: Array
    throttle_pct: Array
    brake: npt.NDArray[np.bool_]

    @classmethod
    def concat(cls, parts: list[Estimates]) -> Estimates:
        """Join blocks in order."""
        names = list(cls.__dataclass_fields__)
        if not parts:
            kinds = {"state": np.int8, "brake": bool}
            return cls(*(np.zeros(0, dtype=kinds.get(n, np.float64)) for n in names))
        return cls(*(np.concatenate([getattr(p, n) for p in parts]) for n in names))

    def __len__(self) -> int:
        """Return the number of points."""
        return int(self.t_s.size)


def taper_limit_kw(v_ms: Array, cfg: Config) -> Array:
    """MGU-K limit at each speed under the regulated taper (linear from start to end)."""
    lo, hi = (float(const(cfg, k)) / KMH for k in ("taper.start_kmh", "taper.end_kmh"))
    share = np.clip((hi - v_ms) / (hi - lo), 0.0, 1.0)
    return np.asarray(float(const(cfg, "car.p_elec_max_kw")) * share, dtype=np.float64)


def steady_full(pts: Points, cfg: Config) -> npt.NDArray[np.bool_]:
    """Full throttle over the whole filter window, no brake in it.

    At the end of a straight the smoothed acceleration already mixes in the braking
    that follows; such a point would read as a big negative P_elec (a false CLIP and
    a false super-clip harvest). Only steady points count as full throttle.
    """
    thr = float(const(cfg, "states.full_throttle_pct"))
    return np.asarray((pts.window_throttle_pct >= thr) & ~pts.window_brake)


def classify_states(
    p_elec_kw: Array, v_ms: Array, a_ms2: Array, throttle_pct: Array, brake: npt.NDArray[np.bool_],
    cfg: Config, full: npt.NDArray[np.bool_] | None = None,
) -> npt.NDArray[np.int8]:  # fmt: skip
    """Per point state from throttle, brake, estimated P_elec and acceleration (L-b).

    ``full``: steady full throttle (:func:`steady_full`); default: throttle alone.
    """
    if full is None:
        full = throttle_pct >= float(const(cfg, "states.full_throttle_pct"))
    limit = taper_limit_kw(v_ms, cfg)
    clip_below = np.minimum(float(const(cfg, "states.clip_max_kw")),
                            limit - float(const(cfg, "states.taper_margin_kw")))  # fmt: skip
    flat = a_ms2 <= float(const(cfg, "states.clip_max_accel_ms2"))
    out = np.full(p_elec_kw.size, CRUISE, dtype=np.int8)
    out[full & (p_elec_kw > float(const(cfg, "states.deploy_min_kw")))] = DEPLOY
    out[full & (p_elec_kw < clip_below) & flat] = CLIP
    out[throttle_pct < float(const(cfg, "states.lift_throttle_pct"))] = LIFT
    out[brake] = HARVEST
    return out


def flows_kw(
    p_wheel_kw: Array, p_elec_kw: Array, v_ms: Array, state: npt.NDArray[np.int8],
    full: npt.NDArray[np.bool_], straight: npt.NDArray[np.bool_], cfg: Config,
) -> tuple[Array, npt.NDArray[np.bool_]]:  # fmt: skip
    """Harvest power per point (kW), and where the car shows "empty" (L-a)."""
    limit = taper_limit_kw(v_ms, cfg)
    cap = float(const(cfg, "energy.harvest_cap_kw"))
    brake = np.minimum(float(const(cfg, "energy.brake_share")) * np.clip(-p_wheel_kw, 0.0, None),
                       cap)  # fmt: skip
    fast = v_ms * KMH >= float(const(cfg, "energy.superclip_min_kmh"))
    superclip = full & straight & fast & (p_elec_kw < float(const(cfg, "anchor.superclip_kw")))
    harvest = np.where(state == HARVEST, brake, 0.0)
    harvest = np.where(state == LIFT, float(const(cfg, "energy.lift_harvest_kw")), harvest)
    harvest = np.where(superclip, np.minimum(-p_elec_kw, cap), harvest)
    margin = float(const(cfg, "states.taper_margin_kw"))
    empty = (full & straight & (p_elec_kw < float(const(cfg, "anchor.no_deploy_kw")))
             & (p_elec_kw > float(const(cfg, "anchor.superclip_kw")))
             & (p_elec_kw < limit - margin))  # fmt: skip
    return np.asarray(harvest), np.asarray(empty)


@numba.njit(cache=True)
def _integrate(
    t: Array, p_elec: Array, limit: Array, v_kmh: Array, full: npt.NDArray[np.bool_],
    straight: npt.NDArray[np.bool_], brake: npt.NDArray[np.bool_], harvest: Array,
    empty: npt.NDArray[np.bool_], new_lap: Array, zone: npt.NDArray[np.int64], frac: Array,
    params: Array, st: Array,
) -> tuple[Array, Array, Array, Array]:  # fmt: skip
    """Sequential energy integration with anchors; ``st`` is updated in place."""
    (e_min, e_max, lap_limit, miss_tau, min_clip_s, max_frac, empty_mj, step_s, v_obs_lo,
     v_obs_hi, level_tau, corner_v_min, corner_kw, corner_tau, corner_cap,
     cruise_scale) = params  # fmt: skip
    n = t.size
    energy, since, miss_out, deploy_out = np.empty(n), np.empty(n), np.empty(n), np.empty(n)
    for i in range(n):
        dt = t[i] - st[LAST_T] if st[LAST_T] > -1e17 else 0.0
        if dt > step_s:  # missing data: no integration over the gap, remember it
            st[MISS_S] += dt
            dt_int = 0.0
        else:
            dt_int = dt
        st[MISS_S] *= np.exp(-dt / miss_tau)
        if new_lap[i] > 0.5:
            st[LAP_HARVEST_MJ] = 0.0
        # Deploy (L-c): seen where power shows in the speed trace, carried over where it does not.
        p = p_elec[i]
        if brake[i]:
            dep = 0.0
        elif full[i] and straight[i]:
            if v_obs_lo <= v_kmh[i] < v_obs_hi:
                dep = min(max(p, 0.0), limit[i])
                w = min(dt_int / level_tau, 1.0)
                st[LEVEL_KW] += w * (dep - st[LEVEL_KW])
            elif v_kmh[i] < v_obs_lo:
                dep = min(st[LEVEL_KW], limit[i])
            else:
                dep = min(max(p, 0.0), limit[i])
        elif full[i]:
            if v_kmh[i] >= corner_v_min:  # a fast corner shows whether the car deploys there
                seen = p > corner_kw
                w = min(dt_int / corner_tau, 1.0)
                st[CORNER_DEPLOY] += w * ((1.0 if seen else 0.0) - st[CORNER_DEPLOY])
                dep = min(max(p, 0.0), corner_cap, limit[i]) if seen else 0.0
            else:  # a slow corner does not: expected value from the fast ones
                dep = min(corner_cap, limit[i]) * st[CORNER_DEPLOY]
        else:
            dep = min(max(p, 0.0), limit[i]) * cruise_scale
        room = max(lap_limit - st[LAP_HARVEST_MJ], 0.0)
        if st[E_MJ] >= e_max:
            room = 0.0  # a full battery cannot take more
        gain = min(harvest[i] * dt_int / 1e3, room)
        st[LAP_HARVEST_MJ] += gain
        st[E_MJ] = min(max(st[E_MJ] + gain - dep * dt_int / 1e3, e_min), e_max)
        deploy_out[i] = dep
        # EMPTY anchor: neither deploying nor harvesting at full throttle, early on a long straight.
        if empty[i] and zone[i] >= 0:
            if st[CLIP_ZONE] != zone[i] or dt > step_s:
                st[CLIP_ZONE] = zone[i]
                st[CLIP_T0] = t[i]
                st[CLIP_FRAC0] = frac[i]
                st[CLIP_DONE] = 0.0
            if (st[CLIP_DONE] < 0.5 and t[i] - st[CLIP_T0] >= min_clip_s
                    and st[CLIP_FRAC0] <= max_frac):  # fmt: skip
                st[E_MJ] = empty_mj
                st[ANCHOR_T] = t[i]
                st[CLIP_DONE] = 1.0
        else:
            st[CLIP_ZONE] = -1.0
        st[LAST_T] = t[i]
        energy[i] = st[E_MJ]
        since[i] = t[i] - st[ANCHOR_T]
        miss_out[i] = st[MISS_S]
    return energy, since, miss_out, deploy_out


class CarTracker:
    """One car: raw public samples in, per-point estimates out (streaming, causal)."""

    def __init__(self, driver: str, team: str, track: Track, cfg: Config) -> None:
        """Start at the race-start prior."""
        self.driver, self.team, self.track, self.cfg = driver, team, track, cfg
        self.stream = Stream(cfg)
        self.runs = RunBuilder(cfg)
        self.fit = CdaFit(cfg)
        self._pending: list[Run] = []  # runs closed but not yet in the fit (they wait for the line)
        self._lap = -1.0
        self.modes = aero_modes(cfg)
        self.cda = {m: self.fit.value(m) for m in self.modes}
        self.p_ice = p_ice_kw(team, cfg)
        self.state = np.zeros(N_STATE)
        self.state[E_MJ] = float(const(cfg, "anchor.start_mj"))
        self.state[ANCHOR_T] = 0.0
        self.state[LAST_T] = -1e18
        self.state[CLIP_ZONE] = -1.0
        long_m = float(const(cfg, "anchor.min_straight_m"))
        self.long_zones = [z for z in track.tagged("acceleration_zone")
                           if z.length_m(track.length_m) >= long_m]  # fmt: skip
        self.params = np.array([
            float(const(cfg, "energy.e_min_mj")), float(const(cfg, "energy.e_max_mj")),
            float(const(cfg, "energy.harvest_max_mj_per_lap")),
            float(const(cfg, "confidence.missing_tau_s")),
            float(const(cfg, "anchor.min_clip_s")), float(const(cfg, "anchor.max_start_frac")),
            float(const(cfg, "anchor.empty_mj")), 1.5 / float(const(cfg, "signal.resample_hz")),
            float(const(cfg, "deploy.observed_kmh.min")),
            float(const(cfg, "deploy.observed_kmh.max")),
            float(const(cfg, "deploy.level_tau_s")), float(const(cfg, "deploy.corner_min_kmh")),
            float(const(cfg, "deploy.corner_seen_kw")), float(const(cfg, "deploy.corner_tau_s")),
            float(const(cfg, "deploy.corner_cap_kw")), float(const(cfg, "deploy.cruise_scale")),
        ])  # fmt: skip
        self.state[LEVEL_KW] = float(const(cfg, "deploy.start_level_kw"))

    def push(
        self, t_s: Array, speed_kmh: Array, throttle_pct: Array, brake: npt.NDArray[np.bool_],
        progress_m: Array,
    ) -> Estimates:  # fmt: skip
        """Add raw samples; return the estimates of the points that became final."""
        return self._process(self.stream.push(t_s, speed_kmh, throttle_pct, brake, progress_m))

    def flush(self) -> Estimates:
        """End of data: process the last points."""
        out = self._process(self.stream.flush())
        self.fit_runs(self.runs.close(), np.inf)
        return out

    def fit_runs(self, runs: list[Run], upto_t: float) -> None:
        """Add the runs closed by ``upto_t`` to the fit; refresh CdA and ICE power."""
        self._pending += runs
        ready = [r for r in self._pending if r.closed_t <= upto_t]
        self._pending = [r for r in self._pending if r.closed_t > upto_t]
        for run in ready:
            self.fit.add(self.modes[run.mode], run.points.v_ms, run.points.a_ms2, run.m_kg,
                         run.accel_zone)  # fmt: skip
        self.cda = {m: self.fit.value(m) for m in self.modes}
        self.p_ice = self._p_ice()

    def _p_ice(self) -> float:
        """ICE power from the strongest acceleration-zone runs (L-d), within the config spread."""
        base = p_ice_kw(self.team, self.cfg)
        if not bool(const(self.cfg, "car.p_ice_from_runs")):
            return base
        powers = []
        for mode in self.modes:
            c = self.cda[mode]
            powers += [(r.mean_y + c * r.mean_x) / 1e3 for r in self.fit.runs[mode] if r.accel_zone]
        if len(powers) < int(const(self.cfg, "car.p_ice_min_runs")):
            return base
        full = float(np.quantile(powers, float(const(self.cfg, "car.p_ice_quantile"))))
        est = full / float(const(self.cfg, "car.eta")) - float(const(self.cfg, "car.p_elec_max_kw"))
        spread = float(const(self.cfg, "car.p_ice_spread_pct")) / 100.0
        return float(np.clip(est, base * (1.0 - spread), base * (1.0 + spread)))

    def _process(self, pts: Points) -> Estimates:
        if len(pts) == 0:
            return Estimates.concat([])
        lap_m = self.track.length_m
        s = pts.progress_m % lap_m
        lap = np.floor(pts.progress_m / lap_m) + 1.0
        sm = self.track.zone_index(s, "straight_mode_allowed") >= 0
        acc = self.track.zone_index(s, "acceleration_zone")
        m = mass_kg(lap, self.cfg)
        self._pending += self.runs.feed(pts, np.where(sm, 0, 1).astype(np.int64), acc, m)
        zone = np.full(len(pts), -1, dtype=np.int64)
        frac = np.full(len(pts), -1.0)
        for k, z in enumerate(self.long_zones):
            inside = z.contains(s, lap_m)
            zone[inside] = k
            frac[inside] = ((s[inside] - z.s_start_m) % lap_m) / z.length_m(lap_m)
        full = steady_full(pts, self.cfg)
        new_lap = np.diff(np.concatenate(([self._lap], lap))) > 0.0
        cuts = [0, *(int(i) for i in np.flatnonzero(new_lap)), len(pts)]
        parts = []
        for a, b in zip(cuts[:-1], cuts[1:], strict=True):
            if b <= a:
                continue
            if new_lap[a]:
                self.fit_runs([], float(pts.t_s[a]))
            cda = np.where(sm[a:b] & full[a:b], self.cda[self.modes[0]], self.cda[self.modes[1]])
            p_wheel = wheel_power_kw(pts.v_ms[a:b], pts.a_ms2[a:b], m[a:b], cda, self.cfg)
            p_elec = electric_power_kw(p_wheel, pts.throttle_pct[a:b], self.p_ice, self.cfg)
            state = classify_states(p_elec, pts.v_ms[a:b], pts.a_ms2[a:b], pts.throttle_pct[a:b],
                                    pts.brake[a:b], self.cfg, full[a:b])  # fmt: skip
            harvest, empty = flows_kw(p_wheel, p_elec, pts.v_ms[a:b], state, full[a:b],
                                      acc[a:b] >= 0, self.cfg)  # fmt: skip
            energy, since, miss, _ = _integrate(
                pts.t_s[a:b], p_elec, taper_limit_kw(pts.v_ms[a:b], self.cfg),
                pts.v_ms[a:b] * KMH, full[a:b], acc[a:b] >= 0, pts.brake[a:b], harvest, empty,
                new_lap[a:b].astype(np.float64), zone[a:b], frac[a:b], self.params, self.state,
            )  # fmt: skip
            parts.append(Estimates(pts.t_s[a:b], energy, state, self._raw_conf(energy, since, miss),
                                   since,
                                   p_elec, pts.v_ms[a:b], pts.progress_m[a:b],
                                   pts.throttle_pct[a:b], pts.brake[a:b]))  # fmt: skip
        self._lap = float(lap[-1])
        return Estimates.concat(parts)

    def _raw_conf(self, energy_mj: Array, since_anchor_s: Array, miss_s: Array) -> Array:
        scale = float(const(self.cfg, "confidence.missing_scale_s"))
        return confidence_table(energy_mj, since_anchor_s, self.cfg) * np.exp(-miss_s / scale)


def confidence_table(energy_mj: Array, since_anchor_s: Array, cfg: Config) -> Array:
    """Return the tune-set hit rate for each estimate's band and time since anchor (L-e)."""
    e_edges = np.asarray(const(cfg, "confidence.table.energy_edges_mj"), dtype=np.float64)
    s_edges = np.asarray(const(cfg, "confidence.table.since_anchor_edges_s"), dtype=np.float64)
    rates = np.asarray(const(cfg, "confidence.table.hit_rate"), dtype=np.float64)
    i = np.clip(np.searchsorted(e_edges, energy_mj, side="right") - 1, 0, rates.shape[0] - 1)
    j = np.clip(np.searchsorted(s_edges, since_anchor_s, side="right") - 1, 0, rates.shape[1] - 1)
    return np.asarray(rates[i, j], dtype=np.float64)


def calibrated(raw: Array, cfg: Config) -> Array:
    """Stated confidence: the raw score is already the calibrated hit rate."""
    return np.asarray(np.clip(raw, 0.0, 1.0), dtype=np.float64)


def estimates_frame(driver: str, est: Estimates, cfg: Config) -> pd.DataFrame:
    """Return the bridge ``estimates.parquet`` rows of one car, ``output.estimates_hz``."""
    hz = float(const(cfg, "output.estimates_hz"))
    tick = np.floor(est.t_s * hz)
    first = np.flatnonzero(np.diff(np.concatenate(([-1.0], tick))) > 0)
    return pd.DataFrame({
        "driver": driver,
        "time_s": est.t_s[first],
        "energy_mj": est.energy_mj[first],
        "state": np.array(STATES)[est.state[first]],
        "confidence": calibrated(est.raw_confidence[first], cfg),
        "since_anchor_s": est.since_anchor_s[first],
        "raw_confidence": est.raw_confidence[first],
    })  # fmt: skip

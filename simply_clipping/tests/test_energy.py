"""SC-2: states, integration, anchors on synthetic laps with a known battery."""

from __future__ import annotations

import numpy as np
import pytest

from simply_clipping.energy import CLIP, DEPLOY, CarTracker, Estimates, taper_limit_kw
from simply_clipping.loader import Track, Zone, const, load_config
from simply_clipping.physics import mass_kg

CFG = load_config()
LAP_M = 3000.0
ZONE = Zone("SM", 1000.0, 2200.0, ("straight_mode_allowed", "acceleration_zone"))
TRACK = Track("synthetic", LAP_M, (ZONE,), (("T1", 2300.0),))
KMH = 3.6


def _c(key: str) -> float:
    return float(const(CFG, key))


def drive(laps: list[str], e_start: float, v_corner_kmh: float = 150.0) -> dict[str, np.ndarray]:
    """Simulate laps (one straight each) at 100 Hz; the battery follows the estimator's rules.

    Lap kinds: ``deploy`` (350 kW, tapered, until empty, then no deploy), ``superclip``
    (deploy, then harvest 350 kW over the last 30 % of the straight).
    """
    rho, crr, g, eta = _c("car.rho_kg_m3"), _c("car.crr"), _c("car.g_ms2"), _c("car.eta")
    p_ice, cap = _c("car.p_ice_kw") * 1e3, _c("energy.harvest_cap_kw") * 1e3
    share = _c("energy.brake_share")
    cda_s, cda_c = _c("cda_fit.prior_m2.straight"), _c("cda_fit.prior_m2.corner")
    dt, v, s, e = 0.01, v_corner_kmh / KMH, 0.0, e_start
    out: dict[str, list[float]] = {k: [] for k in ("t", "v", "thr", "brk", "p", "e", "kind")}
    t = 0.0
    for lap_no, kind in enumerate(laps, start=1):
        m = float(mass_kg(np.array([float(lap_no)]), CFG)[0])
        lap_end = lap_no * LAP_M
        while s < lap_end:
            s_lap = s - (lap_no - 1) * LAP_M

            def drag(cda: float, v: float = v, m: float = m) -> float:
                return float(0.5 * rho * cda * v**3 + crr * m * g * v)

            if ZONE.s_start_m <= s_lap < ZONE.s_end_m:  # full throttle on the straight
                frac = (s_lap - ZONE.s_start_m) / (ZONE.s_end_m - ZONE.s_start_m)
                limit = float(taper_limit_kw(np.array([v]), CFG)[0]) * 1e3
                p_k = limit if e > 0.0 else 0.0
                if kind == "superclip" and frac >= 0.7:
                    p_k = -cap
                p_wheel = eta * (p_ice + p_k)
                thr, brk = 100.0, False
                e = min(e - p_k * dt / 1e6, _c("energy.e_max_mj"))
                e = max(e, 0.0)
                a = (p_wheel - drag(cda_s)) / (m * v)
            elif v > v_corner_kmh / KMH + 0.05:  # brake for the corner, harvesting
                a = -30.0
                f_b = m * -a - drag(cda_c) / v
                e = min(e + min(share * f_b * v, cap) * dt / 1e6, _c("energy.e_max_mj"))
                thr, brk = 0.0, True
            else:  # cruise at P_elec = 0
                a = 0.0
                v = v_corner_kmh / KMH
                thr, brk = 100.0 * drag(cda_c) / (eta * p_ice), False
            for k, val in (("t", t), ("v", v), ("thr", thr), ("brk", brk), ("e", e)):
                out[k].append(float(val))
            out["p"].append(s)
            out["kind"].append(float(ZONE.contains(np.array([s % LAP_M]), LAP_M)[0]))
            v += a * dt
            s += v * dt
            t += dt
    return {k: np.asarray(val) for k, val in out.items()}


def estimate(run: dict[str, np.ndarray], rng: np.random.Generator) -> Estimates:
    """Sample at 4 Hz with jitter and 0.5 km/h noise, as the feed does, and track."""
    idx = np.arange(0, run["t"].size, 25) + rng.integers(-3, 4, run["t"][::25].size)
    idx = np.clip(idx, 0, run["t"].size - 1)
    idx = np.unique(idx)
    tracker = CarTracker("SYN", "", TRACK, CFG)
    v = run["v"][idx] * KMH + rng.normal(0.0, 0.5, idx.size)
    first = tracker.push(run["t"][idx], v, np.round(run["thr"][idx]), run["brk"][idx] > 0.5,
                         run["p"][idx])  # fmt: skip
    return Estimates.concat([first, tracker.flush()])


def _true_at(run: dict[str, np.ndarray], t: np.ndarray) -> np.ndarray:
    return np.asarray(np.interp(t, run["t"], run["e"]))


def test_full_then_clip_anchors_to_empty_and_stays_close() -> None:
    run = drive(["deploy", "deploy", "deploy"], e_start=_c("anchor.start_mj"))
    est = estimate(run, np.random.default_rng(42))
    err = np.abs(est.energy_mj - _true_at(run, est.t_s))
    assert err.max() < 0.5, err.max()
    empty = _true_at(run, est.t_s) <= 0.0
    straight = ZONE.contains(est.progress_m % LAP_M, LAP_M)
    assert not (est.state[empty & straight] == DEPLOY).any()  # no deploy from an empty battery
    assert (est.since_anchor_s < est.t_s - 1.0).any()  # the EMPTY anchor fired


def test_superclip_with_energy_is_harvest_not_empty() -> None:
    run = drive(["superclip", "superclip"], e_start=_c("anchor.start_mj"))
    est = estimate(run, np.random.default_rng(7))
    err = np.abs(est.energy_mj - _true_at(run, est.t_s))
    assert err.max() < 0.5, err.max()
    s_lap = est.progress_m % LAP_M
    late = ZONE.contains(s_lap, LAP_M) & ((s_lap - ZONE.s_start_m) / 1200.0 > 0.75)
    assert (est.state[late] == CLIP).mean() > 0.8  # a super-clip is CLIP ...
    assert (est.since_anchor_s == est.t_s).all()  # ... but never an EMPTY anchor (L-a)


@pytest.mark.parametrize("seed", [1, 2])
def test_taper_limited_straight_is_not_clip(seed: int) -> None:
    run = drive(["deploy", "deploy"], e_start=4.0, v_corner_kmh=250.0)
    est = estimate(run, np.random.default_rng(seed))
    in_taper = est.v_ms * KMH >= _c("taper.start_kmh")
    assert in_taper.sum() > 20  # the car reaches the taper band
    straight = ZONE.contains(est.progress_m % LAP_M, LAP_M)
    battery = _true_at(run, est.t_s) > 0.5
    assert not (est.state[in_taper & straight & battery] == CLIP).any()  # lesson L-b
    err = np.abs(est.energy_mj - _true_at(run, est.t_s))
    assert err.max() < 0.5, err.max()


def test_tracker_is_chunk_invariant() -> None:
    """The bench (one push) and the live pit wall (many pushes) get the same estimates."""
    run = drive(["deploy", "superclip", "deploy"], e_start=4.0)
    rng = np.random.default_rng(3)
    jitter = rng.integers(-3, 4, run["t"][::25].size)
    idx = np.unique(np.clip(np.arange(0, run["t"].size, 25) + jitter, 0, run["t"].size - 1))
    raw = (run["t"][idx], run["v"][idx] * KMH, np.round(run["thr"][idx]), run["brk"][idx] > 0.5,
           run["p"][idx])  # fmt: skip
    one = CarTracker("SYN", "", TRACK, CFG)
    whole = Estimates.concat([one.push(*raw), one.flush()])
    many = CarTracker("SYN", "", TRACK, CFG)
    cuts = np.sort(rng.choice(np.arange(1, idx.size), 40, replace=False))
    parts = [many.push(*(r[a:b] for r in raw)) for a, b in
             zip(np.r_[0, cuts], np.r_[cuts, idx.size], strict=True)]  # fmt: skip
    chunked = Estimates.concat([*parts, many.flush()])
    for name in ("t_s", "energy_mj", "state", "raw_confidence"):
        assert np.array_equal(getattr(whole, name), getattr(chunked, name)), name

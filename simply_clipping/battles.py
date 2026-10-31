"""P8 battles: where every car is at a moment, who is ahead and behind, and the gaps.

Positions come from public data only: each rival's race progress (lap-start
pinned distance offline, lap distance plus counted laps live) from its own
:class:`History` of estimates; Our Car's from our exact own data. The gap to a
car is the distance between us divided by the following car's speed, so a
battle (``battles.within_s``) is rebuilt from positions, as on a timing screen.

:func:`straight_pass` answers "was this rival seen in a long CLIP on this
straight last lap?" (ATTACK branch b, DEFEND branch b) from the rival's last
complete pass of the straight, with the share of feed samples present on it
(detection confidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from simply_clipping.energy import CLIP, Estimates
from simply_clipping.loader import Config, Track, Zone, const

Array = npt.NDArray[np.float64]
HISTORY_FIELDS = (
    "t_s",
    "energy_mj",
    "state",
    "confidence",
    "progress_m",
    "v_ms",
    "p_elec_kw",
    "throttle_pct",
)


@dataclass
class History:
    """One car's per-point estimates over time (amortised append, trimmed to ``keep_s``)."""

    keep_s: float = np.inf
    _cols: dict[str, np.ndarray] = field(default_factory=dict)
    _n: int = 0
    _pass_cache: dict[tuple[int, int], StraightPass | None] = field(default_factory=dict)

    def append(self, est: Estimates, confidence: Array) -> None:
        """Add estimates (time ordered) with their stated confidence."""
        if len(est) == 0:
            return
        new: dict[str, np.ndarray] = {
            "t_s": est.t_s,
            "energy_mj": est.energy_mj,
            "state": est.state,
            "confidence": confidence,
            "progress_m": est.progress_m,
            "v_ms": est.v_ms,
            "p_elec_kw": est.p_elec_kw,
            "throttle_pct": est.throttle_pct,
        }
        if not self._cols:
            self._cols = {
                k: np.empty(max(1024, 2 * len(est)), dtype=v.dtype) for k, v in new.items()
            }
        cap = next(iter(self._cols.values())).size
        if self._n + len(est) > cap:
            size = max(2 * cap, self._n + len(est))
            for k, col in self._cols.items():
                grown = np.empty(size, dtype=col.dtype)
                grown[: self._n] = col[: self._n]
                self._cols[k] = grown
        for k, v in new.items():
            self._cols[k][self._n : self._n + len(est)] = v
        self._n += len(est)
        if np.isfinite(self.keep_s):
            self._trim(float(est.t_s[-1]) - self.keep_s)

    def _trim(self, before_t: float) -> None:
        k = int(np.searchsorted(self.col("t_s"), before_t))
        if k > self._n // 2 and k > 0:  # shift only now and then
            for col in self._cols.values():
                col[: self._n - k] = col[k : self._n].copy()
            self._n -= k

    def col(self, name: str) -> np.ndarray:
        """Return a column, oldest first."""
        return self._cols[name][: self._n] if self._cols else np.zeros(0)

    def at(self, t_s: float, stale_s: float) -> int:
        """Index of the last point at or before ``t_s`` (-1: none, or older than ``stale_s``)."""
        t = self.col("t_s")
        k = int(np.searchsorted(t, t_s, side="right")) - 1
        if k < 0 or t_s - t[k] > stale_s:
            return -1
        return k


@dataclass(frozen=True)
class StraightPass:
    """A car's complete pass of one straight."""

    lap_start_progress_m: float
    longest_clip_s: float
    clip_start_s_m: float | None
    """Lap distance where the longest CLIP began."""
    detection_share: float
    """Share of the 10 Hz points present on the pass (feed samples seen)."""


def zone_ahead(track: Track, s_m: float) -> Zone | None:
    """Return the acceleration zone we are in, or the next one ahead."""
    zones = track.tagged("acceleration_zone")
    if not zones:
        return None
    lap = track.length_m
    inside = [z for z in zones if z.contains(np.array([s_m]), lap)[0]]
    if inside:
        return inside[0]
    return min(zones, key=lambda z: (z.s_start_m - s_m) % lap)


def straight_pass(
    hist: History, zone: Zone, before_progress_m: float, track: Track, cfg: Config
) -> StraightPass | None:
    """Return the car's last complete pass of ``zone`` that ended before ``before_progress_m``."""
    lap = track.length_m
    zlen = zone.length_m(lap)
    k = np.floor((before_progress_m - zone.s_start_m - zlen) / lap)  # passes fully behind
    start = zone.s_start_m + k * lap
    zone_no = int(round(zone.s_start_m))
    key = (zone_no, int(k))
    if key in hist._pass_cache:
        return hist._pass_cache[key]
    prog = hist.col("progress_m")
    a, b = np.searchsorted(prog, start), np.searchsorted(prog, start + zlen)
    if b - a < 2:
        hist._pass_cache[key] = None
        return None
    t = hist.col("t_s")[a:b]
    v = hist.col("v_ms")[a:b]
    state = hist.col("state")[a:b]
    hz = float(const(cfg, "signal.resample_hz"))
    expected = zlen / max(float(np.mean(v)), 1.0) * hz
    share = float(min(1.0, (b - a) / max(expected, 1.0)))
    clip = state == CLIP
    contiguous = np.diff(t, prepend=t[0]) <= 1.5 / hz
    best, best_start = 0.0, None
    run_t0, run_i0 = None, 0
    for i in range(t.size):
        if not clip[i]:
            run_t0 = None
            continue
        if run_t0 is None or not contiguous[i]:
            run_t0, run_i0 = float(t[i]), i
        if t[i] - run_t0 > best:
            best = float(t[i] - run_t0)
            best_start = float(prog[a + run_i0] % lap)
    out = StraightPass(float(start), best, best_start, share)
    hist._pass_cache[key] = out
    return out


@dataclass(frozen=True)
class Neighbour:
    """A rival near us at one moment."""

    driver: str
    gap_s: float
    """Positive: the rival is ahead of us."""
    distance_m: float
    v_ms: float
    energy_mj: float
    confidence: float
    state: int
    no_deploy: bool = False
    """Full throttle without deploy (``anchor.no_deploy_kw``): an empty car still accelerating."""


def neighbours(
    us_progress_m: float,
    us_v_ms: float,
    t_s: float,
    cars: dict[str, History],
    cfg: Config,
    lap_m: float,
) -> list[Neighbour]:
    """Every rival with a fresh estimate within half a lap of us, nearest first."""
    stale = float(const(cfg, "battles.stale_s"))
    full_pct = float(const(cfg, "states.full_throttle_pct"))
    no_deploy_kw = float(const(cfg, "anchor.no_deploy_kw"))
    v_min = float(const(cfg, "battles.min_speed_kmh")) / 3.6
    out = []
    for driver, hist in cars.items():
        k = hist.at(t_s, stale)
        if k < 0:
            continue
        d = float(hist.col("progress_m")[k]) - us_progress_m
        if abs(d) > lap_m / 2.0:
            continue
        v = float(hist.col("v_ms")[k])
        follower_v = us_v_ms if d > 0 else v
        no_deploy = bool(
            hist.col("throttle_pct")[k] >= full_pct and hist.col("p_elec_kw")[k] < no_deploy_kw
        )
        out.append(
            Neighbour(
                driver,
                d / max(follower_v, v_min),
                d,
                v,
                float(hist.col("energy_mj")[k]),
                float(hist.col("confidence")[k]),
                int(hist.col("state")[k]),
                no_deploy,
            )
        )
    return sorted(out, key=lambda n: abs(n.distance_m))


def battles(nbrs: list[Neighbour], cfg: Config) -> tuple[Neighbour | None, Neighbour | None]:
    """Return the car directly ahead and directly behind, if within ``battles.within_s``."""
    within = float(const(cfg, "battles.within_s"))
    ahead = min((n for n in nbrs if n.distance_m > 0), key=lambda n: n.distance_m, default=None)
    behind = max((n for n in nbrs if n.distance_m <= 0), key=lambda n: n.distance_m, default=None)
    return (
        ahead if ahead is not None and ahead.gap_s <= within else None,
        behind if behind is not None and -behind.gap_s <= within else None,
    )

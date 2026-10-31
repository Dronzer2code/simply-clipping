"""P2-P5 physics: 10 Hz resample, smoothing, acceleration, wheel and electric power, CdA fit.

Radar spec (docs/spec/SIMPLY_CLIPPING_SPEC.md PIPELINE)::

    resample to 10 Hz, Savitzky-Golay (7, 2), acceleration
    P_wheel = m*a*v + 0.5*rho*CdA*v^3 + Crr*m*g*v
    P_elec  = P_wheel / eta - P_ICE

:class:`Stream` turns one car's raw samples into smoothed 10 Hz points. It is
streaming and chunk-invariant: pushing a race at once or a frame at a time gives
the same points, bit for bit, so the bench and the live pit wall agree (SC-3).
Grid points sit at ``k / resample_hz``; nothing is interpolated across a gap
longer than ``signal.max_gap_s``; a segment shorter than one filter window is
dropped.

:class:`CdaFit` fits CdA per car per aero mode (lesson L-c: no full-deploy
assumption). Each full-throttle run below the taper (``cda_fit.v_max_kmh``)
gives one slope: within a run the propulsive power is taken as constant but
unknown (any deploy level), so ``m*a*v + Crr*m*g*v = P_run - CdA * 0.5*rho*v^3``
is fitted on the run's deviations from its own mean, outliers trimmed. The car's
CdA is the weighted median of its runs' slopes, so runs that break the
constant-power assumption (a clip mid-run, a tow) are outvoted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy.signal import savgol_coeffs

from simply_clipping.loader import CarInput, Config, Track, const

Array = npt.NDArray[np.float64]
Bools = npt.NDArray[np.bool_]
KMH = 3.6
KW = 1e3


@dataclass
class Points:
    """Smoothed 10 Hz points of one car."""

    t_s: Array
    v_ms: Array
    a_ms2: Array
    throttle_pct: Array
    brake: Bools
    progress_m: Array
    segment: npt.NDArray[np.int64]
    """Stream segment number (a new one after every long gap)."""

    @classmethod
    def empty(cls) -> Points:
        """No points."""
        f = np.zeros(0)
        return cls(f, f, f, f, np.zeros(0, dtype=bool), f, np.zeros(0, dtype=np.int64))

    def __len__(self) -> int:
        """Return the number of points."""
        return int(self.t_s.size)

    @classmethod
    def concat(cls, parts: list[Points]) -> Points:
        """Join point blocks in order."""
        if not parts:
            return cls.empty()
        return cls(*(np.concatenate([getattr(p, f) for p in parts]) for f in FIELDS))

    def take(self, idx: npt.NDArray[np.int64] | slice | Bools) -> Points:
        """Return the points at ``idx``."""
        return Points(*(getattr(self, f)[idx] for f in FIELDS))


FIELDS = ("t_s", "v_ms", "a_ms2", "throttle_pct", "brake", "progress_m", "segment")


def _dot(coef: Array, windows: list[Array]) -> Array:
    """Sum of coef[q] * windows[q], always in the same order (bitwise chunk-invariant)."""
    out = coef[0] * windows[0]
    for q in range(1, coef.size):
        out = out + coef[q] * windows[q]
    return np.asarray(out, dtype=np.float64)


@dataclass
class _Segment:
    """Grid points of the open segment that are not yet emitted, plus filter context."""

    number: int
    base: int = 0
    """Segment index of the first stored point."""
    emitted: int = 0
    """Points of this segment already emitted."""
    t: list[Array] = field(default_factory=list)
    v: list[Array] = field(default_factory=list)
    thr: list[Array] = field(default_factory=list)
    brk: list[Bools] = field(default_factory=list)
    prog: list[Array] = field(default_factory=list)


class Stream:
    """One car: raw samples in, smoothed 10 Hz :class:`Points` out (P2-P3)."""

    def __init__(self, cfg: Config) -> None:
        """Filter coefficients from ``signal.*``."""
        self.dt = 1.0 / float(const(cfg, "signal.resample_hz"))
        self.max_gap_s = float(const(cfg, "signal.max_gap_s"))
        self.window = int(const(cfg, "signal.savgol_window"))
        order = int(const(cfg, "signal.savgol_order"))
        self.half = self.window // 2
        self.smooth = [np.asarray(savgol_coeffs(self.window, order, pos=p, use="dot"))
                       for p in range(self.window)]  # fmt: skip
        self.deriv = [
            np.asarray(savgol_coeffs(self.window, order, deriv=1, delta=self.dt, pos=p, use="dot"))
            for p in range(self.window)
        ]
        self._last: tuple[float, float, float, bool, float] | None = None
        self._k_next = 0
        self._seg: _Segment | None = None
        self._segments = -1

    def push(
        self, t_s: Array, speed_kmh: Array, throttle_pct: Array, brake: Bools, progress_m: Array
    ) -> Points:
        """Add raw samples (time ordered, after the last pushed); return the new points."""
        out: list[Points] = []
        keep = t_s > (self._last[0] if self._last is not None else -np.inf)
        t_s, speed_kmh, throttle_pct = t_s[keep], speed_kmh[keep], throttle_pct[keep]
        brake, progress_m = brake[keep], progress_m[keep]
        if t_s.size == 0:
            return Points.empty()
        prev_t = self._last[0] if self._last is not None else -np.inf
        breaks = np.flatnonzero(np.diff(np.concatenate(([prev_t], t_s))) > self.max_gap_s)
        bounds = [int(b) for b in breaks] + [int(t_s.size)]
        start = 0
        for stop in bounds:
            if stop > start:
                self._grid(t_s[start:stop], speed_kmh[start:stop], throttle_pct[start:stop],
                           brake[start:stop], progress_m[start:stop])  # fmt: skip
                out.append(self._emit(final=False))
            if stop < t_s.size:  # a long gap before sample ``stop``: close, restart there
                out.append(self._emit(final=True))
                self._seg = None
                self._last = None
            start = stop
        return Points.concat(out)

    def flush(self) -> Points:
        """Close the open segment (end of the data); return its last points."""
        out = self._emit(final=True)
        self._seg = None
        self._last = None
        return out

    def _grid(self, t: Array, v_kmh: Array, thr: Array, brk: Bools, prog: Array) -> None:
        """Interpolate grid points between the last sample and the new ones (one segment)."""
        if self._last is None:
            self._segments += 1
            self._seg = _Segment(self._segments)
            self._k_next = int(np.ceil(t[0] / self.dt - 1e-9))
        else:
            lt, lv, lthr, lbrk, lprog = self._last
            t = np.concatenate(([lt], t))
            v_kmh = np.concatenate(([lv], v_kmh))
            thr = np.concatenate(([lthr], thr))
            brk = np.concatenate(([lbrk], brk))
            prog = np.concatenate(([lprog], prog))
        self._last = (float(t[-1]), float(v_kmh[-1]), float(thr[-1]), bool(brk[-1]),
                      float(prog[-1]))  # fmt: skip
        k_last = int(np.floor(t[-1] / self.dt + 1e-9))
        if k_last < self._k_next:
            return
        gt = np.arange(self._k_next, k_last + 1, dtype=np.float64) * self.dt
        self._k_next = k_last + 1
        seg = self._seg
        assert seg is not None
        seg.t.append(gt)
        seg.v.append(np.interp(gt, t, v_kmh) / KMH)
        seg.thr.append(np.interp(gt, t, thr))
        seg.brk.append(brk[np.clip(np.searchsorted(t, gt, side="right") - 1, 0, t.size - 1)])
        seg.prog.append(np.interp(gt, t, prog))

    def _emit(self, final: bool) -> Points:
        """Smooth and emit the points whose filter window is complete (all, if ``final``)."""
        seg = self._seg
        if seg is None or not seg.t:
            return Points.empty()
        t, v = np.concatenate(seg.t), np.concatenate(seg.v)
        thr, brk, prog = np.concatenate(seg.thr), np.concatenate(seg.brk), np.concatenate(seg.prog)
        n_total = seg.base + t.size
        w, h = self.window, self.half
        if n_total < w:
            if final:
                seg.t.clear()  # too short to filter: dropped
            return Points.empty()
        stop = n_total if final else n_total - h  # segment indices [seg.emitted, stop)
        idx = np.arange(seg.emitted, stop)
        if idx.size == 0:
            return Points.empty()
        local = idx - seg.base
        vs, acc = np.empty(idx.size), np.empty(idx.size)
        interior = (idx >= h) & (idx < n_total - h)
        if interior.any():
            li = local[interior]
            windows = [v[li - h + q] for q in range(w)]
            vs[interior] = _dot(self.smooth[h], windows)
            acc[interior] = _dot(self.deriv[h], windows)
        for edge in np.flatnonzero(~interior):
            j = int(idx[edge])
            first = 0 if j < h else n_total - w  # the window the polynomial is fitted on
            win = [v[np.array([first - seg.base + q])] for q in range(w)]
            vs[edge] = _dot(self.smooth[j - first], win)[0]
            acc[edge] = _dot(self.deriv[j - first], win)[0]
        pts = Points(t[local], vs, acc, thr[local], brk[local], prog[local],
                     np.full(idx.size, seg.number, dtype=np.int64))  # fmt: skip
        seg.emitted = stop
        drop = max(0, min(seg.emitted - w, t.size + seg.base - w) - seg.base)
        if drop > 0 and not final:  # keep one window of context
            seg.t, seg.v, seg.thr = [t[drop:]], [v[drop:]], [thr[drop:]]
            seg.brk, seg.prog = [brk[drop:]], [prog[drop:]]
            seg.base += drop
        return pts


def mass_kg(lap: Array, cfg: Config) -> Array:
    """Car mass with the fuel left at the start of each lap (lesson L-d)."""
    start = const(cfg, "fuel.start_kg")
    burn = const(cfg, "fuel.burn_kg_per_lap")
    fuel = np.zeros_like(lap) if start is None or burn is None else (
        np.clip(float(start) - float(burn) * (lap - 1.0), 0.0, float(start)))  # fmt: skip
    return float(const(cfg, "car.mass_kg")) + fuel


def p_ice_kw(team_id: str, cfg: Config) -> float:
    """ICE power of the team's maker (lesson L-d), default ``car.p_ice_kw``."""
    by_team: dict[str, float] = const(cfg, "car.p_ice_kw_by_team") or {}
    return float(by_team.get(team_id, const(cfg, "car.p_ice_kw")))


def resistance_w(v_ms: Array, m_kg: Array, cda_m2: Array | float, cfg: Config) -> Array:
    """Drag plus rolling resistance power, W."""
    rho, crr, g = (float(const(cfg, k)) for k in ("car.rho_kg_m3", "car.crr", "car.g_ms2"))
    return np.asarray(0.5 * rho * cda_m2 * v_ms**3 + crr * m_kg * g * v_ms, dtype=np.float64)


def wheel_power_kw(
    v_ms: Array, a_ms2: Array, m_kg: Array, cda_m2: Array | float, cfg: Config
) -> Array:
    """P_wheel = m*a*v + 0.5*rho*CdA*v^3 + Crr*m*g*v, in kW."""
    return (m_kg * a_ms2 * v_ms + resistance_w(v_ms, m_kg, cda_m2, cfg)) / KW


def electric_power_kw(
    p_wheel_kw: Array, throttle_pct: Array, p_ice: float | Array, cfg: Config
) -> Array:
    """P_elec = P_wheel / eta - P_ICE, the ICE at the throttle's share of its power, in kW."""
    eta = float(const(cfg, "car.eta"))
    return np.asarray(p_wheel_kw / eta - np.clip(throttle_pct, 0.0, 100.0) / 100.0 * p_ice)


def aero_modes(cfg: Config) -> tuple[str, ...]:
    """Return the aero modes a CdA is fitted for."""
    return tuple(str(m) for m in const(cfg, "cda_fit.aero_modes"))


@dataclass(frozen=True)
class RunFit:
    """One full-throttle run's CdA slope."""

    cda_m2: float
    weight: float
    mean_x: float
    """Mean of 0.5*rho*v^3 (W per m^2 of CdA)."""
    mean_y: float
    """Mean of m*a*v + Crr*m*g*v (W)."""
    accel_zone: bool


def fit_run(
    v_ms: Array, a_ms2: Array, m_kg: Array, cfg: Config
) -> tuple[float, float, float, float] | None:
    """Slope fit of one run: (CdA, weight, mean x, mean y), or None when it says too little."""
    if v_ms.size < int(const(cfg, "cda_fit.min_points")):
        return None
    if (v_ms.max() - v_ms.min()) * KMH < float(const(cfg, "cda_fit.min_dv_kmh")):
        return None
    rho, crr, g = (float(const(cfg, k)) for k in ("car.rho_kg_m3", "car.crr", "car.g_ms2"))
    x = 0.5 * rho * v_ms**3
    y = m_kg * a_ms2 * v_ms + crr * m_kg * g * v_ms
    keep = np.ones(x.size, dtype=bool)
    trim = float(const(cfg, "cda_fit.trim_mad"))
    cda = float("nan")
    resid = np.zeros(x.size)
    for _ in range(int(const(cfg, "cda_fit.trim_rounds")) + 1):
        dx, dy = x[keep] - x[keep].mean(), y[keep] - y[keep].mean()
        sxx = float(dx @ dx)
        if keep.sum() < int(const(cfg, "cda_fit.min_points")) or sxx <= 0.0:
            return None
        cda = -float(dx @ dy) / sxx
        resid = (y - y[keep].mean()) + cda * (x - x[keep].mean())
        mad = float(np.median(np.abs(resid[keep] - np.median(resid[keep]))))
        if mad <= 0.0:
            break
        new = np.abs(resid - np.median(resid[keep])) <= trim * 1.4826 * mad
        if (new == keep).all():
            break
        keep = new
    lo, hi = (float(const(cfg, f"cda_fit.cda_bounds_m2.{k}")) for k in ("min", "max"))
    if not lo <= cda <= hi:
        return None
    dx = x[keep] - x[keep].mean()
    floor_w = float(const(cfg, "cda_fit.resid_floor_kw")) * KW
    var = max(float(np.var(resid[keep])), floor_w**2)  # no run outvotes the rest on a lucky fit
    return cda, float(dx @ dx) / var, float(x[keep].mean()), float(y[keep].mean())


class CdaFit:
    """One car's CdA per aero mode from its full-throttle runs (lesson L-c)."""

    def __init__(self, cfg: Config) -> None:
        """Start from the prior ``cda_fit.prior_m2``."""
        self.cfg = cfg
        self.runs: dict[str, list[RunFit]] = {m: [] for m in aero_modes(cfg)}

    def add(self, mode: str, v_ms: Array, a_ms2: Array, m_kg: Array, accel_zone: bool) -> None:
        """Add one closed run."""
        fit = fit_run(v_ms, a_ms2, m_kg, self.cfg)
        if fit is not None and np.isfinite(fit[0]):
            self.runs[mode].append(RunFit(fit[0], fit[1], fit[2], fit[3], accel_zone))

    def value(self, mode: str) -> float:
        """Weighted median of the runs' slopes; the prior until ``cda_fit.min_runs`` runs."""
        runs = self.runs[mode]
        if len(runs) < int(const(self.cfg, "cda_fit.min_runs")):
            return float(const(self.cfg, f"cda_fit.prior_m2.{mode}"))
        c = np.array([r.cda_m2 for r in runs])
        w = np.array([r.weight for r in runs])
        order = np.argsort(c, kind="stable")
        cum = np.cumsum(w[order])
        return float(c[order][int(np.searchsorted(cum, 0.5 * cum[-1]))])

    def fitted(self, mode: str) -> float | None:
        """Return the fitted value, or None while still on the prior."""
        return self.value(mode) if len(self.runs[mode]) >= int(
            const(self.cfg, "cda_fit.min_runs")) else None  # fmt: skip


class RunBuilder:
    """Cuts a car's points into full-throttle runs for :class:`CdaFit` (chunk-invariant).

    A run is a stretch of contiguous points at full throttle, off the brake, between
    ``cda_fit.v_min_kmh`` and ``cda_fit.v_max_kmh`` (below the taper), in one aero
    mode and one zone. It closes at the first point that does not continue it.
    """

    def __init__(self, cfg: Config) -> None:
        """Run limits from ``cda_fit.*`` and ``states.full_throttle_pct``."""
        self.v_min = (
            np.array([float(const(cfg, f"cda_fit.v_min_kmh.{m}")) for m in aero_modes(cfg)]) / KMH
        )
        self.v_max = float(const(cfg, "cda_fit.v_max_kmh")) / KMH
        self.thr_min = float(const(cfg, "states.full_throttle_pct"))
        self.step_s = 1.5 / float(const(cfg, "signal.resample_hz"))
        self._key = -1
        self._mode = self._zone = -1
        self._parts: list[Points] = []
        self._mass: list[Array] = []
        self._last_t = -np.inf

    def feed(
        self, pts: Points, mode_idx: npt.NDArray[np.int64], zone_idx: npt.NDArray[np.int64],
        m_kg: Array,
    ) -> list[Run]:  # fmt: skip
        """Add points; return the runs that closed."""
        closed: list[Run] = []
        n = len(pts)
        if n == 0:
            return closed
        fast = (pts.v_ms >= self.v_min[mode_idx]) & (pts.v_ms < self.v_max)
        ok = (pts.throttle_pct >= self.thr_min) & ~pts.brake & fast
        key = np.where(ok, (mode_idx + 1) * 1_000_000 + (zone_idx + 1) * 1000 + pts.segment % 1000,
                       -1)  # fmt: skip
        jump = np.diff(np.concatenate(([self._last_t], pts.t_s))) > self.step_s
        prev = np.concatenate(([self._key], key[:-1]))
        starts = np.flatnonzero((key != prev) | jump)
        bounds = [int(s) for s in starts] + [n]
        if not starts.size or starts[0] != 0:
            bounds = [0, *bounds]
        for a, b in zip(bounds[:-1], bounds[1:], strict=True):
            if a in starts:  # a new run (or none) begins here
                self._close(closed)
                if key[a] >= 0:
                    self._key, self._mode, self._zone = (
                        int(key[a]),
                        int(mode_idx[a]),
                        int(zone_idx[a]),
                    )
            if key[a] >= 0:
                self._parts.append(pts.take(slice(a, b)))
                self._mass.append(m_kg[a:b])
        self._last_t = float(pts.t_s[-1])
        return closed

    def close(self) -> list[Run]:
        """End of data: close the open run."""
        closed: list[Run] = []
        self._close(closed)
        return closed

    def _close(self, closed: list[Run]) -> None:
        if self._parts:
            closed.append(Run(self._mode, Points.concat(self._parts), np.concatenate(self._mass),
                              self._zone >= 0))  # fmt: skip
        self._parts, self._mass = [], []
        self._key = self._mode = self._zone = -1


@dataclass(frozen=True)
class Run:
    """One closed full-throttle run."""

    mode: int
    """Index into ``cda_fit.aero_modes``."""
    points: Points
    m_kg: Array
    accel_zone: bool


def stream_car(car: CarInput, cfg: Config) -> Points:
    """All of one car's smoothed 10 Hz points (P2-P3), as the live stream would give them."""
    stream = Stream(cfg)
    first = stream.push(car.t_s, car.speed_kmh, car.throttle_pct, car.brake, car.progress_m)
    return Points.concat([first, stream.flush()])


def lap_of(progress_m: Array, track: Track) -> Array:
    """Lap number (1-based) from race progress."""
    return np.floor(progress_m / track.length_m) + 1.0


def mode_index(pts: Points, track: Track) -> npt.NDArray[np.int64]:
    """Aero mode per point: 0 = straight (a Straight Mode zone), 1 = corner."""
    s = pts.progress_m % track.length_m
    return np.where(track.zone_index(s, "straight_mode_allowed") >= 0, 0, 1).astype(np.int64)


def fit_cda(pts: Points, track: Track, cfg: Config) -> CdaFit:
    """CdA per aero mode from a car's points (P5)."""
    fit = CdaFit(cfg)
    builder = RunBuilder(cfg)
    modes = aero_modes(cfg)
    zone = track.zone_index(pts.progress_m % track.length_m, "acceleration_zone")
    runs = builder.feed(pts, mode_index(pts, track), zone, mass_kg(lap_of(pts.progress_m, track),
                                                                   cfg))  # fmt: skip
    for run in runs + builder.close():
        fit.add(modes[run.mode], run.points.v_ms, run.points.a_ms2, run.m_kg, run.accel_zone)
    return fit

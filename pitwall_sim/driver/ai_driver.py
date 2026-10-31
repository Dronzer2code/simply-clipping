"""F04 AI Driver: speed tracking, Energy Modes, lines, attack and defend (T-031).

The driver works at two rates:

- **Per lap** (or when its instructions change) :func:`plan_lap` makes the
  car's per-point plan for the step kernel (``step_kernel.KernelPlans``): the
  reference speed (T-024 speed profile at the driver's grip margin), the MGU-K
  deploy fraction, super-clip, part-throttle harvest and the throttle cap (lift
  and coast). The deploy fraction comes from one **deploy level** in [0, 2]:
  0 → 1 fills the acceleration zones, 1 → 2 the rest of the lap (TRD: deploy
  prioritised in acceleration zones). The level is the highest whose predicted
  lap (the step kernel, one car) ends with the battery at the Energy Mode's
  target: PUSH spends down to the boost reserve, BALANCED ends level, HARVEST
  gains ``harvest_target``. :class:`EnergyBalance` corrects the next lap's
  target by the last lap's miss (traffic, boost, Overtake).
- **Per decision tick** :func:`decide` picks the racing line, Overtake mode and
  boost from the car's situation (gaps, zone, battery, commands).

Speed tracking itself is the kernel's ``track_speed`` (TRD: P-controller on
``v_ref(s) - v`` with braking points from the backward pass). Boost follows the
owner's rules (round 7). Mistakes are T-037.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import numpy.typing as npt

from pitwall_sim.car.deploy_allocation import allocate, profile_full_throttle
from pitwall_sim.car.speed_profile import ProfileParams, speed_profile
from pitwall_sim.config.models import (
    AiDriverConfig,
    EnergyMode,
    MistakeKind,
    MistakesConfig,
    TrackConfig,
)
from pitwall_sim.race import step_kernel as K
from pitwall_sim.track.zones import zone_ids_mask

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]

MS_TO_KMH = 3.6
MJ = 1e6
MAX_LEVEL = 2.0
LEVEL_ITERATIONS = 10
"""Sets the level resolution 2 / 2**10 ≈ 0.002 (the solver takes at most twice this many steps)."""
LEVEL_TOLERANCE = 2.0 / 2**LEVEL_ITERATIONS
LEVEL_TOLERANCE_J = 2e3
"""The solve stops once the predicted lap end is this close above the target."""
SLOPE_STEP = 0.1
"""Deploy-level step for the local battery slope."""

#: Lines (TRD: 0 racing line, 1 defending / inside, 2 overtaking / outside).
RACING_LINE, DEFEND_LINE, OVERTAKE_LINE = 0, 1, 2


@dataclass(frozen=True)
class DriverInstructions:
    """What the engineer (Our Car) or the Rival Strategy AI asks of the driver."""

    mode: EnergyMode = EnergyMode.BALANCED
    attack: bool = False
    defend: bool = False
    hold_position: bool = False
    let_teammate_by: bool = False
    push_lap: bool = False
    manage_tyres: bool = False
    lift_coast: bool = False
    overtake_permitted: bool = True
    lift_zones: tuple[str, ...] | None = None
    """SET_LIFT_COAST zone_ids: lift only inside these zones (``None``: everywhere)."""
    follow_close: bool = False
    """The engineer's ATTACK call (sprint day 5): use all the grip (the PUSH_LAP
    margin) to stay in the tow through the corners and close into attempt range."""
    keep_deploy: bool = False
    """The engineer's DEFEND call (sprint day 5, TRD AI DRIVER DEFEND): deploy only in
    the acceleration zones, the rest is kept for the next straight."""


@dataclass(frozen=True)
class CarPlan:
    """One car's per-point plan (rows of ``step_kernel.KernelPlans``)."""

    v_ref: FloatArray
    deploy: FloatArray
    superclip: BoolArray
    throttle_cap: FloatArray
    part_harvest: BoolArray
    accel_zone: BoolArray
    deploy_level: float
    yield_straights: bool
    lap_time_s: float
    """Reference lap time of the plan's speed profile (energy-unlimited)."""
    level_slope_j: float = 0.0
    """Predicted change of the lap-end battery per unit deploy level (J, < 0)."""
    priority: FloatArray | None = None
    """PUSH: each point's place in the energy-spreading order (owner round 14); the
    deploy level fills that order instead of the acceleration-zones-first one."""
    reserve_straights: bool = False
    """``keep_deploy``: deploy only in the acceleration zones."""

    def with_level(self, level: float) -> CarPlan:
        """Return the same plan at another deploy level."""
        level = min(max(level, 0.0), MAX_LEVEL)
        if self.priority is not None:
            deploy = (self.priority < level / MAX_LEVEL).astype(np.float64)
        else:
            deploy = deploy_fractions(level, self.accel_zone, self.yield_straights)
        if self.reserve_straights:
            deploy = np.where(self.accel_zone, deploy, 0.0)
        return replace(self, deploy=deploy, deploy_level=level)

    def relevel(self, more_end_battery_j: float) -> CarPlan:
        """Move the deploy level so the lap ends ``more_end_battery_j`` higher (linear).

        Between full re-plans the engine retunes energy this way each lap; the
        slope comes from the last :func:`solve_deploy_level`.
        """
        if self.level_slope_j >= 0.0:
            return self
        return self.with_level(self.deploy_level + more_end_battery_j / self.level_slope_j)


@dataclass(frozen=True)
class LapPredictor:
    """Step-kernel inputs for predicting one car's lap (one-car ``KernelCars``)."""

    dt_s: float
    trk: K.KernelTrack
    glb: K.KernelGlobals
    car: K.KernelCars

    @classmethod
    def for_car(
        cls, dt_s: float, trk: K.KernelTrack, glb: K.KernelGlobals, cars: K.KernelCars, i: int
    ) -> LapPredictor:
        """Predictor for car ``i`` of a field's ``KernelCars``."""
        row = K.KernelCars(*(np.ascontiguousarray(a[i : i + 1]) for a in cars))
        return cls(dt_s, trk, glb, row)

    def lap(
        self, plan: CarPlan, battery_j: float, fuel_kg: float, tyre_wear: float = 0.0
    ) -> tuple[float, float]:
        """Drive one flying lap from the line; return (lap time s, battery at the line J)."""
        plans = kernel_plans([plan])
        st = K.initial_state(
            1, [0.0], [float(plan.v_ref[0])], [battery_j], [fuel_kg], self.trk.loops_m
        )
        st.tyre_wear[0] = tyre_wear
        max_steps = int(20 * self.trk.length_m / (plan.v_ref.mean() * self.dt_s)) + 1
        K.advance(
            max_steps, self.dt_s, 0.0, plans, self.trk, self.glb, self.car,
            K.default_controls(1), st, 1,
        )  # fmt: skip
        return float(st.line_time_s[0]), float(st.battery_j[0])


@dataclass
class EnergyBalance:
    """Per-car correction so laps end near the Energy Mode's battery target.

    After each lap the next lap's target moves by ``gain`` x the last lap's
    miss (ended low → aim higher), so steady losses (traffic, boost, Overtake)
    stop draining or overfilling the battery.
    """

    gain: float
    offset_j: float = 0.0
    history: list[float] = field(default_factory=list)

    def update(self, battery_change_j: float, target_change_j: float) -> float:
        """Record one lap's battery change; return the new target offset (J)."""
        self.history.append(battery_change_j)
        self.offset_j += self.gain * (target_change_j - battery_change_j)
        return self.offset_j


@dataclass(frozen=True)
class Situation:
    """The car's situation at a decision tick (from the engine)."""

    battery_j: float
    in_acceleration_zone: bool
    gap_ahead_s: float = float("inf")
    gap_behind_s: float = float("inf")
    overtake_available: bool = False


@dataclass(frozen=True)
class Decision:
    """The driver's choices for the next decision tick."""

    line: int
    overtake_active: bool
    boost_active: bool


# --------------------------------------------------------------------------- #
# Per-lap plan
# --------------------------------------------------------------------------- #


def deploy_fractions(level: float, accel_zone: BoolArray, yield_straights: bool) -> FloatArray:
    """Deploy fraction per point for a deploy level in [0, 2] (acceleration zones first)."""
    inside = 0.0 if yield_straights else min(max(level, 0.0), 1.0)
    outside = min(max(level - 1.0, 0.0), 1.0)
    return np.where(accel_zone, inside, outside).astype(np.float64)


def kernel_plans(plans: list[CarPlan]) -> K.KernelPlans:
    """Stack per-car plans into the kernel's (cars, points) arrays."""
    return K.KernelPlans(
        v_ref=np.stack([p.v_ref for p in plans]),
        deploy=np.stack([p.deploy for p in plans]),
        superclip=np.stack([p.superclip for p in plans]),
        throttle_cap=np.stack([p.throttle_cap for p in plans]),
        part_harvest=np.stack([p.part_harvest for p in plans]),
    )


def _zone_ends_mask(
    track: TrackConfig, s_m: FloatArray, length_m: float, metres: float
) -> BoolArray:
    """Points within ``metres`` before the end of each acceleration zone (wrap-aware)."""
    mask = np.zeros(s_m.size, dtype=np.bool_)
    if metres <= 0.0:
        return mask
    for zone in track.zones:
        if "acceleration_zone" not in zone.tags:
            continue
        start = (zone.s_end_m - metres) % length_m
        if start <= zone.s_end_m:
            mask |= (s_m >= start) & (s_m < zone.s_end_m)
        else:
            mask |= (s_m >= start) | (s_m < zone.s_end_m)
    return mask


def _lift_mask(
    v_ref: FloatArray, braking: BoolArray, ds_m: float, lift_m: float, min_drop_ms: float
) -> BoolArray:
    """Points ``lift_m`` before each braking zone whose speed drop is at least ``min_drop_ms``."""
    n = v_ref.size
    mask = np.zeros(n, dtype=np.bool_)
    lift_pts = int(round(lift_m / ds_m))
    if lift_pts <= 0 or braking.all():
        return mask
    for start in np.flatnonzero(braking & ~np.roll(braking, 1)):
        end = start
        while braking[(end + 1) % n]:
            end += 1
        v_end = v_ref[end % n]
        before = (start - np.arange(1, lift_pts + 1)) % n
        # Lift only on the fast approach, never back into the previous corner.
        mask[before[(v_ref[before] - v_end >= min_drop_ms) & ~braking[before]]] = True
    return mask


def shape_plan(
    trk: K.KernelTrack,
    s_m: FloatArray,
    track: TrackConfig,
    prof: ProfileParams,
    instructions: DriverInstructions,
    cfg: AiDriverConfig,
    deploy_level: float = MAX_LEVEL,
) -> CarPlan:
    """Shape the plan for the instructions, at a given deploy level (TRD AI DRIVER).

    Reference speed at the grip margin (PUSH_LAP and an engineer's ATTACK
    higher, MANAGE_TYRES lower); an engineer's DEFEND deploys only in the
    acceleration zones; HARVEST super-clips the last ``superclip_zone_m`` of each acceleration zone
    and lifts and coasts; SET_LIFT_COAST lifts in any mode. Part-throttle and
    coasting harvest are on in every mode (not a voluntary super-clip).
    """
    margin = (
        cfg.push_lap_grip_margin
        if instructions.push_lap or instructions.follow_close
        else cfg.manage_tyres_grip_margin
        if instructions.manage_tyres
        else cfg.grip_margin
    )
    driven = prof._replace(mu_lat=prof.mu_lat * margin, mu_long=prof.mu_long * margin)
    profile = speed_profile(s_m, trk.kappa, trk.straight_mode, trk.accel_zone, trk.length_m, driven)
    harvest = instructions.mode == EnergyMode.HARVEST
    clip = (
        _zone_ends_mask(track, s_m, trk.length_m, cfg.superclip_zone_m)
        if harvest
        else np.zeros(s_m.size, dtype=np.bool_)
    )
    throttle_cap = np.ones(s_m.size)
    if harvest or instructions.lift_coast:
        braking = profile.v_brake_ms < profile.v_accel_ms - 1e-6
        lift = _lift_mask(
            profile.v_ref_ms, braking, trk.ds_m, cfg.lift_coast_m,
            cfg.lift_coast_min_drop_kmh / MS_TO_KMH,
        )  # fmt: skip
        if instructions.lift_zones is not None and not harvest:
            lift &= zone_ids_mask(track, s_m, instructions.lift_zones)
        throttle_cap[lift] = 0.0
    yield_straights = instructions.let_teammate_by
    priority = None
    if instructions.mode == EnergyMode.PUSH and not yield_straights:
        # Owner round 14: PUSH spreads its energy like the calibration policy,
        # slowest exits first (car.deploy_allocation).
        full = profile_full_throttle(profile.v_accel_ms, profile.v_brake_ms, profile.v_corner_ms)
        priority = allocate(
            profile.v_ref_ms, full, trk.accel_zone, trk.ds_m, prof.powertrain, 1.0
        ).priority
    plan = CarPlan(
        v_ref=profile.v_ref_ms,
        deploy=deploy_fractions(deploy_level, trk.accel_zone, yield_straights),
        superclip=clip,
        throttle_cap=throttle_cap,
        part_harvest=np.ones(s_m.size, dtype=np.bool_),
        accel_zone=trk.accel_zone,
        deploy_level=deploy_level,
        yield_straights=yield_straights,
        lap_time_s=profile.lap_time_s,
        priority=priority,
        reserve_straights=instructions.keep_deploy,
    )
    return plan.with_level(deploy_level)


def lap_target_change_j(
    mode: EnergyMode, battery_j: float, cfg: AiDriverConfig, e_max_j: float = math.inf
) -> float:
    """Battery change over a lap the Energy Mode aims for (J).

    PUSH spends down to the boost reserve; HARVEST gains ``harvest_target``;
    BALANCED holds the battery (net 0), but never above ``balanced_headroom_mj``
    below full: a full battery throws harvest away.
    """
    if mode == EnergyMode.PUSH:
        return min(cfg.boost_reserve_mj * MJ - battery_j, 0.0)
    if mode == EnergyMode.HARVEST:
        return cfg.harvest_target_mj_per_lap * MJ
    return min(0.0, e_max_j - cfg.balanced_headroom_mj * MJ - battery_j)


def solve_deploy_level(
    predictor: LapPredictor,
    plan: CarPlan,
    target_end_j: float,
    battery_j: float,
    fuel_kg: float,
    tyre_wear: float = 0.0,
) -> CarPlan:
    """Highest deploy level whose predicted lap ends with at least ``target_end_j``.

    The target is capped at what the battery can reach (a full battery cannot
    end higher); if even level 0 ends short, level 0 (harvest as much as the
    plan allows).
    """
    e_max = float(predictor.car.e_usable_max_j[0])
    target = min(target_end_j, e_max - 1.0)

    def end_j(level: float) -> float:
        return predictor.lap(plan.with_level(level), battery_j, fuel_kg, tyre_wear)[1]

    end_max, end_zero = end_j(MAX_LEVEL), end_j(0.0)
    slope = (end_max - end_zero) / MAX_LEVEL
    if end_max >= target:
        return replace(plan.with_level(MAX_LEVEL), level_slope_j=slope)
    if end_zero < target:
        return replace(plan.with_level(0.0), level_slope_j=slope)
    # Illinois (regula falsi): the lap end is close to linear in the level, so a
    # few predictions reach the bisection's resolution. ``lo`` always meets the target.
    lo, hi, f_lo, f_hi = 0.0, MAX_LEVEL, end_zero - target, end_max - target
    margin, side = f_lo, 0  # margin: lo's true lap end above the target
    for _ in range(2 * LEVEL_ITERATIONS):  # kinks (PUSH fills runs in turn) may need more
        if hi - lo <= LEVEL_TOLERANCE or margin <= LEVEL_TOLERANCE_J:
            break
        mid = min(max((lo * f_hi - hi * f_lo) / (f_hi - f_lo), lo), hi)
        f_mid = end_j(mid) - target
        if f_mid >= 0.0:
            lo, f_lo, margin = mid, f_mid, f_mid
            f_hi = 0.5 * f_hi if side == 1 else f_hi
            side = 1
        else:
            hi, f_hi = mid, f_mid
            f_lo = 0.5 * f_lo if side == -1 else f_lo
            side = -1
    # Local slope for the engine's lap-by-lap retuning (relevel).
    a, b = max(lo - SLOPE_STEP, 0.0), min(lo + SLOPE_STEP, MAX_LEVEL)
    local = (end_j(b) - end_j(a)) / (b - a)
    return replace(plan.with_level(lo), level_slope_j=local if local < 0.0 else slope)


def plan_lap(
    predictor: LapPredictor,
    s_m: FloatArray,
    track: TrackConfig,
    prof: ProfileParams,
    instructions: DriverInstructions,
    cfg: AiDriverConfig,
    battery_j: float,
    fuel_kg: float,
    tyre_wear: float = 0.0,
    balance: EnergyBalance | None = None,
) -> CarPlan:
    """Plan the next lap: shape for the instructions, deploy level for the energy target."""
    plan = shape_plan(predictor.trk, s_m, track, prof, instructions, cfg)
    e_max = float(predictor.car.e_usable_max_j[0])
    change = lap_target_change_j(instructions.mode, battery_j, cfg, e_max)
    # PUSH spends down to the reserve whatever happened last lap.
    offset = 0.0 if balance is None or instructions.mode == EnergyMode.PUSH else balance.offset_j
    return solve_deploy_level(
        predictor, plan, battery_j + change + offset, battery_j, fuel_kg, tyre_wear
    )


def mgmt_factor(instructions: DriverInstructions, cfg: AiDriverConfig) -> float:
    """Tyre-wear multiplier for the instructions (PUSH_LAP up, MANAGE_TYRES down)."""
    if instructions.push_lap:
        return cfg.push_lap_mgmt_factor
    if instructions.manage_tyres:
        return cfg.manage_tyres_mgmt_factor
    return 1.0


# --------------------------------------------------------------------------- #
# Per decision tick
# --------------------------------------------------------------------------- #


def decide(sit: Situation, instructions: DriverInstructions, cfg: AiDriverConfig) -> Decision:
    """Line, Overtake mode and boost for the next decision tick.

    Lines: overtaking line when within ``boost_gap_s`` of the car ahead and
    allowed to attack; defending line when the car behind is that close, under
    a DEFEND instruction (inside line into every braking zone) and when letting
    a teammate by. Overtake mode when available, permitted and
    attacking. Boost (owner round 7): never below the battery reserve, only in
    acceleration zones; PUSH always; BALANCED only when attacking or defending
    within ``boost_gap_s``; HARVEST never; ATTACK / DEFEND force it.
    HOLD_POSITION and LET_TEAMMATE_BY never attack.
    """
    may_attack = not (instructions.hold_position or instructions.let_teammate_by)
    attacking = may_attack and sit.gap_ahead_s <= cfg.boost_gap_s
    defending = sit.gap_behind_s <= cfg.boost_gap_s

    if instructions.let_teammate_by:
        line = DEFEND_LINE
    elif attacking:
        line = OVERTAKE_LINE
    elif defending or instructions.defend:
        line = DEFEND_LINE
    else:
        line = RACING_LINE

    overtake = sit.overtake_available and instructions.overtake_permitted and attacking

    boost = False
    if (
        sit.battery_j >= cfg.boost_reserve_mj * MJ
        and sit.in_acceleration_zone
        and not instructions.let_teammate_by
    ):
        if (instructions.attack and may_attack) or instructions.defend:
            boost = True
        elif instructions.mode == EnergyMode.PUSH:
            boost = True
        elif instructions.mode == EnergyMode.BALANCED:
            boost = attacking or defending
    return Decision(line=line, overtake_active=overtake, boost_active=boost)


# --------------------------------------------------------------------------- #
# Vectorised decision tick (the engine; same rules as :func:`decide`)
# --------------------------------------------------------------------------- #

MODE_CODES = {EnergyMode.PUSH: 0, EnergyMode.BALANCED: 1, EnergyMode.HARVEST: 2}


# --------------------------------------------------------------------------- #
# Mistakes (T-037)
# --------------------------------------------------------------------------- #


def mistake_probability(
    cfg: MistakesConfig, skill_consistency: float, tyre_wear: float, wetness: float
) -> float:
    """Probability of a mistake at the corner a car is passing (TRD AI DRIVER).

    ``base x (1 + consistency_gain (1 - skill)) x (1 + wear_gain wear) x
    (1 + wet_gain wetness)``, at most 1 (inputs clipped to 0..1).
    """
    p = (
        cfg.base_p_per_corner
        * (1.0 + cfg.consistency_gain * (1.0 - min(max(skill_consistency, 0.0), 1.0)))
        * (1.0 + cfg.wear_gain * min(max(tyre_wear, 0.0), 1.0))
        * (1.0 + cfg.wet_gain * min(max(wetness, 0.0), 1.0))
    )
    return min(p, 1.0)


def draw_mistake(cfg: MistakesConfig, p: float, rng: np.random.Generator) -> MistakeKind | None:
    """One corner passed: no mistake, or its outcome by ``kind_shares`` (RNG ``mistakes``)."""
    if rng.random() >= p:
        return None
    u = rng.random()
    total = 0.0
    kinds = list(cfg.kind_shares)
    for kind in kinds:
        total += cfg.kind_shares[kind]
        if u < total:
            return kind
    return kinds[-1]


@dataclass(frozen=True)
class InstructionArrays:
    """Every car's instructions as arrays (rebuilt when instructions change)."""

    mode: npt.NDArray[np.int8]
    attack: BoolArray
    defend: BoolArray
    hold_position: BoolArray
    let_teammate_by: BoolArray
    overtake_permitted: BoolArray
    mgmt_factor: FloatArray


def instruction_arrays(
    instructions: list[DriverInstructions], cfg: AiDriverConfig
) -> InstructionArrays:
    """Pack per-car instructions for :func:`decide_all`."""

    def flags(name: str) -> BoolArray:
        return np.array([getattr(i, name) for i in instructions], dtype=np.bool_)

    return InstructionArrays(
        mode=np.array([MODE_CODES[i.mode] for i in instructions], dtype=np.int8),
        attack=flags("attack"),
        defend=flags("defend"),
        hold_position=flags("hold_position"),
        let_teammate_by=flags("let_teammate_by"),
        overtake_permitted=flags("overtake_permitted"),
        mgmt_factor=np.array([mgmt_factor(i, cfg) for i in instructions], dtype=np.float64),
    )


def set_instruction_row(
    ins: InstructionArrays, i: int, instructions: DriverInstructions, cfg: AiDriverConfig
) -> None:
    """Update car ``i``'s row of the packed instructions in place."""
    ins.mode[i] = MODE_CODES[instructions.mode]
    ins.attack[i] = instructions.attack
    ins.defend[i] = instructions.defend
    ins.hold_position[i] = instructions.hold_position
    ins.let_teammate_by[i] = instructions.let_teammate_by
    ins.overtake_permitted[i] = instructions.overtake_permitted
    ins.mgmt_factor[i] = mgmt_factor(instructions, cfg)


def decide_all(
    battery_j: FloatArray,
    in_acceleration_zone: BoolArray,
    gap_ahead_s: FloatArray,
    gap_behind_s: FloatArray,
    overtake_available: BoolArray,
    ins: InstructionArrays,
    cfg: AiDriverConfig,
) -> tuple[npt.NDArray[np.int64], BoolArray, BoolArray]:
    """``(line, overtake_active, boost_active)`` for every car; :func:`decide` per element."""
    may_attack = ~(ins.hold_position | ins.let_teammate_by)
    attacking = may_attack & (gap_ahead_s <= cfg.boost_gap_s)
    defending = gap_behind_s <= cfg.boost_gap_s
    line = np.where(
        ins.let_teammate_by,
        DEFEND_LINE,
        np.where(
            attacking, OVERTAKE_LINE, np.where(defending | ins.defend, DEFEND_LINE, RACING_LINE)
        ),
    ).astype(np.int64)
    overtake = overtake_available & ins.overtake_permitted & attacking
    allowed = (battery_j >= cfg.boost_reserve_mj * MJ) & in_acceleration_zone & ~ins.let_teammate_by
    forced = (ins.attack & may_attack) | ins.defend
    by_mode = (ins.mode == MODE_CODES[EnergyMode.PUSH]) | (
        (ins.mode == MODE_CODES[EnergyMode.BALANCED]) & (attacking | defending)
    )
    return line, overtake, allowed & (forced | by_mode)

"""F08 Rival Strategy AI (T-041; TRD RIVAL STRATEGY AI, PF-10).

Every Rival car follows a :class:`RivalPlan` (planned stop, tyres, energy rules)
and, at each decision tick, decides from a :class:`RivalView`: its own Ground
Truth plus public information about the others. HR-03: the view holds no other
car's Ground Truth; the opponents' energy comes only from their Radar Estimates
(the Public Feed). Decisions per tick (PF-10):

- energy: in a battle (car ahead or behind within ``battle_gap_s``) compare own
  battery with the opponent's Radar Estimate: ATTACK when the margin is big
  enough (bigger margins for cautious teams), else HOLD; DEFEND unless the
  attacker looks clearly stronger. Energy Mode: BALANCED; HARVEST once the
  battery at the line is below ``low_battery_mj``, until it is back to
  ``recover_battery_mj`` at the line (the battery swings by MJs within a lap,
  so the line value decides: at most one change per lap); PUSH in the last laps.
- pit: inside the stop window box once the tyre is worn past ``wear_threshold``,
  the planned lap is reached or the car behind threatens an undercut; at
  ``critical_wear`` box at any time; never in the last laps. SC / VSC (T-038)
  and weather (T-039) reactions come with those tasks (T-062).

Plans are made at the start: one stop at ``stop_fraction[strategy_style]`` of
the race (teammates ``teammate_offset_laps`` apart, jitter on RNG stream
``rival_strategy``, HR-04), MEDIUM -> HARD (HARD -> MEDIUM if starting on HARD).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.config.models import Compound, EnergyMode, RivalStrategyConfig
from pitwall_sim.driver.ai_driver import MODE_CODES, DriverInstructions

MJ = 1e6


@dataclass
class RivalPlan:
    """One Rival car's strategy (TRD ``RivalPlan``)."""

    driver_id: str
    stop_lap: int
    """Completed laps at which the planned stop is due."""
    next_compound: Compound
    aggression: float
    """0 cautious .. 1 aggressive (team value)."""
    stops_done: int = 0
    harvesting: bool = False


@dataclass(frozen=True)
class OpponentEstimate:
    """What a Rival knows about another car's energy: its Radar Estimate."""

    driver_id: str
    energy_mj: float
    confidence: float


@dataclass(frozen=True)
class RivalView:
    """A Rival car's inputs at a decision tick: own Ground Truth + public data only."""

    driver_id: str
    laps_done: int
    race_laps: int
    battery_mj: float
    """Own battery (own Ground Truth)."""
    line_battery_mj: float
    """Own battery at the last line crossing (own Ground Truth)."""
    tyre_wear: float
    """Own tyre wear (own Ground Truth)."""
    in_pit_lane: bool
    gap_ahead_s: float
    gap_behind_s: float
    ahead: OpponentEstimate | None
    behind: OpponentEstimate | None


@dataclass(frozen=True)
class RivalDecision:
    """New instructions, and a pit call if any."""

    instructions: DriverInstructions
    box_for: Compound | None = None


def make_plans(
    driver_ids: tuple[str, ...],
    team_ids: tuple[str, ...],
    styles: dict[str, str],
    aggression: dict[str, float],
    race_laps: int,
    start_compound: Compound,
    cfg: RivalStrategyConfig,
    rng: np.random.Generator,
) -> dict[str, RivalPlan]:
    """One plan per car: stop lap by team style, teammates apart, jittered."""
    plans: dict[str, RivalPlan] = {}
    seen: dict[str, int] = {}
    second = Compound.HARD if start_compound != Compound.HARD else Compound.MEDIUM
    for driver, team in zip(driver_ids, team_ids, strict=True):
        style = styles.get(team, "BALANCED")
        fraction = cfg.stop_fraction.get(style, cfg.stop_fraction["BALANCED"])  # type: ignore[call-overload]
        order = seen.get(team, 0)
        seen[team] = order + 1
        jitter = int(rng.integers(-cfg.stop_jitter_laps, cfg.stop_jitter_laps + 1))
        lap = round(race_laps * fraction) + order * cfg.teammate_offset_laps + jitter
        last = race_laps - cfg.no_stop_last_laps - 1
        # A race too short for a stop window: no planned stop (beyond reach).
        lap = int(min(max(lap, 1), last)) if last >= 1 else race_laps + cfg.window_laps + 1
        plans[driver] = RivalPlan(driver, lap, second, aggression.get(team, 0.5))
    return plans


def _energy_flags(
    view: RivalView, plan: RivalPlan, cfg: RivalStrategyConfig
) -> tuple[bool, bool, bool]:
    """``(attack, defend, hold)`` from own battery vs the opponents' Radar Estimates."""
    attack = defend = hold = False
    if view.ahead is not None and view.gap_ahead_s <= cfg.battle_gap_s:
        margin = cfg.attack_margin_mj * (1.5 - plan.aggression)
        rival = view.ahead.energy_mj if view.ahead.confidence > 0.0 else view.battery_mj
        attack = view.battery_mj - rival >= margin
        hold = not attack
    if view.behind is not None and view.gap_behind_s <= cfg.battle_gap_s:
        margin = cfg.defend_margin_mj * (0.5 + plan.aggression)
        rival = view.behind.energy_mj if view.behind.confidence > 0.0 else view.battery_mj
        defend = rival - view.battery_mj <= margin
    return attack, defend, hold


def _mode(view: RivalView, plan: RivalPlan, cfg: RivalStrategyConfig) -> EnergyMode:
    if plan.harvesting and view.line_battery_mj >= cfg.recover_battery_mj:
        plan.harvesting = False
    elif view.line_battery_mj < cfg.low_battery_mj:
        plan.harvesting = True
    if plan.harvesting:
        return EnergyMode.HARVEST
    if view.race_laps - view.laps_done <= cfg.push_final_laps:
        return EnergyMode.PUSH
    return EnergyMode.BALANCED


def _box(view: RivalView, plan: RivalPlan, cfg: RivalStrategyConfig) -> bool:
    laps_left = view.race_laps - view.laps_done
    if view.in_pit_lane or laps_left <= cfg.no_stop_last_laps:
        return False
    if view.tyre_wear >= cfg.critical_wear:
        return True
    if plan.stops_done > 0 or view.laps_done < plan.stop_lap - cfg.window_laps:
        return False
    undercut = view.gap_behind_s <= cfg.undercut_gap_s
    return view.laps_done >= plan.stop_lap or view.tyre_wear >= cfg.wear_threshold or undercut


def decide(
    view: RivalView, plan: RivalPlan, current: DriverInstructions, cfg: RivalStrategyConfig
) -> RivalDecision:
    """One Rival car's decision for this tick (PF-10)."""
    attack, defend, hold = _energy_flags(view, plan, cfg)
    mode = _mode(view, plan, cfg)
    unchanged = (mode, attack, defend, hold) == (
        current.mode,
        current.attack,
        current.defend,
        current.hold_position,
    )
    instructions = (
        current
        if unchanged
        else replace(current, mode=mode, attack=attack, defend=defend, hold_position=hold)
    )
    return RivalDecision(instructions, plan.next_compound if _box(view, plan, cfg) else None)


# --------------------------------------------------------------------------- #
# Compiled decision tick (the race engine; same rules as :func:`decide`)
# --------------------------------------------------------------------------- #

MODE_ORDER: tuple[EnergyMode, ...] = tuple(sorted(MODE_CODES, key=MODE_CODES.__getitem__))
"""Energy Modes by code (the AI Driver's packed instruction codes)."""
PUSH, BALANCED, HARVEST = (MODE_CODES[m] for m in MODE_ORDER)

type BoolArray = npt.NDArray[np.bool_]
type Decisions = tuple[npt.NDArray[np.int64], BoolArray, BoolArray, BoolArray, BoolArray]
"""``(mode, attack, defend, hold, box)`` per Rival row."""


@dataclass
class RivalBook:
    """Every Rival's plan state as arrays, row ``k`` = car ``index[k]``."""

    index: npt.NDArray[np.int64]
    driver_ids: tuple[str, ...]
    stop_lap: npt.NDArray[np.int64]
    aggression: npt.NDArray[np.float64]
    next_compound: tuple[Compound, ...]
    stops_done: npt.NDArray[np.int64]
    harvesting: npt.NDArray[np.bool_]

    @classmethod
    def from_plans(cls, plans: dict[str, RivalPlan], driver_ids: tuple[str, ...]) -> RivalBook:
        """Pack plans (any order) into rows in grid order."""
        rows = [(i, plans[d]) for i, d in enumerate(driver_ids) if d in plans]
        return cls(
            index=np.array([i for i, _ in rows], dtype=np.int64),
            driver_ids=tuple(p.driver_id for _, p in rows),
            stop_lap=np.array([p.stop_lap for _, p in rows], dtype=np.int64),
            aggression=np.array([p.aggression for _, p in rows], dtype=np.float64),
            next_compound=tuple(p.next_compound for _, p in rows),
            stops_done=np.array([p.stops_done for _, p in rows], dtype=np.int64),
            harvesting=np.array([p.harvesting for _, p in rows], dtype=np.bool_),
        )

    def plan(self, driver_id: str) -> RivalPlan:
        """One car's plan as it stands (a copy)."""
        k = self.driver_ids.index(driver_id)
        return RivalPlan(
            driver_id, int(self.stop_lap[k]), self.next_compound[k], float(self.aggression[k]),
            int(self.stops_done[k]), bool(self.harvesting[k]),
        )  # fmt: skip


def decide_book(
    book: RivalBook,
    battery_mj: npt.NDArray[np.float64],
    line_battery_mj: npt.NDArray[np.float64],
    tyre_wear: npt.NDArray[np.float64],
    laps_done: npt.NDArray[np.int64],
    race_laps: int,
    in_pit_lane: npt.NDArray[np.bool_],
    gap_ahead_s: npt.NDArray[np.float64],
    gap_behind_s: npt.NDArray[np.float64],
    ahead_energy_mj: npt.NDArray[np.float64],
    behind_energy_mj: npt.NDArray[np.float64],
    cfg: RivalStrategyConfig,
) -> Decisions:  # fmt: skip
    """``(mode, attack, defend, hold, box)`` per row; :func:`decide` per element.

    Opponent energies are their Radar Estimates, already replaced by the car's
    own battery where the estimate has no confidence (or there is no opponent,
    see :func:`battle_inputs`); ``book.harvesting`` is updated in place.
    """
    params = np.array([
        cfg.battle_gap_s, cfg.attack_margin_mj, cfg.defend_margin_mj, cfg.low_battery_mj,
        cfg.recover_battery_mj, cfg.push_final_laps, cfg.no_stop_last_laps, cfg.window_laps,
        cfg.wear_threshold, cfg.critical_wear, cfg.undercut_gap_s,
    ], dtype=np.float64)  # fmt: skip
    return _decide_rows(
        book.stop_lap, book.aggression, book.stops_done, book.harvesting,
        np.ascontiguousarray(battery_mj, dtype=np.float64),
        np.ascontiguousarray(line_battery_mj, dtype=np.float64),
        np.ascontiguousarray(tyre_wear, dtype=np.float64),
        np.ascontiguousarray(laps_done, dtype=np.int64), race_laps,
        np.ascontiguousarray(in_pit_lane, dtype=np.bool_),
        np.ascontiguousarray(gap_ahead_s, dtype=np.float64),
        np.ascontiguousarray(gap_behind_s, dtype=np.float64),
        np.ascontiguousarray(ahead_energy_mj, dtype=np.float64),
        np.ascontiguousarray(behind_energy_mj, dtype=np.float64), params,
    )  # fmt: skip


@njit(cache=True)
def _decide_rows(
    stop_lap: npt.NDArray[np.int64], aggression: npt.NDArray[np.float64],
    stops_done: npt.NDArray[np.int64], harvesting: npt.NDArray[np.bool_],
    battery: npt.NDArray[np.float64], line_battery: npt.NDArray[np.float64],
    wear: npt.NDArray[np.float64], laps_done: npt.NDArray[np.int64], race_laps: int,
    in_pit: npt.NDArray[np.bool_], gap_ahead: npt.NDArray[np.float64],
    gap_behind: npt.NDArray[np.float64], ahead_e: npt.NDArray[np.float64],
    behind_e: npt.NDArray[np.float64], p: npt.NDArray[np.float64],
) -> Decisions:  # fmt: skip
    battle_gap, attack_m, defend_m, low, recover = p[0], p[1], p[2], p[3], p[4]
    push_laps, no_stop, window, wear_thr, critical, undercut = p[5], p[6], p[7], p[8], p[9], p[10]
    n = stop_lap.size
    mode = np.empty(n, dtype=np.int64)
    attack = np.zeros(n, dtype=np.bool_)
    defend = np.zeros(n, dtype=np.bool_)
    hold = np.zeros(n, dtype=np.bool_)
    box = np.zeros(n, dtype=np.bool_)
    for k in range(n):
        if gap_ahead[k] <= battle_gap:
            attack[k] = battery[k] - ahead_e[k] >= attack_m * (1.5 - aggression[k])
            hold[k] = not attack[k]
        if gap_behind[k] <= battle_gap:
            defend[k] = behind_e[k] - battery[k] <= defend_m * (0.5 + aggression[k])
        if harvesting[k]:
            harvesting[k] = line_battery[k] < recover
        else:
            harvesting[k] = line_battery[k] < low
        laps_left = race_laps - laps_done[k]
        if harvesting[k]:
            mode[k] = HARVEST
        elif laps_left <= push_laps:
            mode[k] = PUSH
        else:
            mode[k] = BALANCED
        if in_pit[k] or laps_left <= no_stop:
            continue
        planned = (
            stops_done[k] == 0
            and laps_done[k] >= stop_lap[k] - window
            and (laps_done[k] >= stop_lap[k] or wear[k] >= wear_thr or gap_behind[k] <= undercut)
        )
        box[k] = wear[k] >= critical or planned
    return mode, attack, defend, hold, box


@njit(cache=True)
def battle_inputs(
    index: npt.NDArray[np.int64], s_m: npt.NDArray[np.float64],
    on_track: npt.NDArray[np.bool_], ahead_idx: npt.NDArray[np.int64],
    gap_ahead_m: npt.NDArray[np.float64], v_ms: npt.NDArray[np.float64],
    own_mj: npt.NDArray[np.float64], radar_mj: npt.NDArray[np.float64],
    radar_confidence: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64],
           npt.NDArray[np.float64]]:  # fmt: skip
    """Per row of ``index``: ``(gap_ahead_s, gap_behind_s, ahead_mj, behind_mj)``.

    Public data only (HR-03): positions and gaps, and the opponents' Radar
    Estimates (``radar_*``, all cars); an opponent that is missing or whose
    estimate has no confidence counts as level with the car's own battery.
    """
    n = s_m.size
    gap_s = gap_ahead_m / np.maximum(v_ms, 1.0)
    behind = np.full(n, -1, dtype=np.int64)
    cars = np.flatnonzero(on_track)
    if cars.size > 1:
        by_s = cars[np.argsort(s_m[cars])]
        for j in range(by_s.size):
            behind[by_s[(j + 1) % by_s.size]] = by_s[j]
    rows = index.size
    gap_ahead_s = np.full(rows, np.inf)
    gap_behind_s = np.full(rows, np.inf)
    ahead_mj = own_mj.copy()
    behind_mj = own_mj.copy()
    for k in range(rows):
        i = index[k]
        a, b = ahead_idx[i], behind[i]
        if a >= 0:
            gap_ahead_s[k] = gap_s[i]
            if radar_confidence[a] > 0.0:
                ahead_mj[k] = radar_mj[a]
        if b >= 0:
            gap_behind_s[k] = gap_s[b]
            if radar_confidence[b] > 0.0:
                behind_mj[k] = radar_mj[b]
    return gap_ahead_s, gap_behind_s, ahead_mj, behind_mj

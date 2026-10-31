"""Real race moment (hackathon E3, light PF-18): start the sim from a real 2026 lap.

"You are on the pit wall at lap 30, what do you do?" The 2026 Japanese GP
(OpenF1 session 11253) gives, at the moment the leader starts lap N:

- running order, each car's completed laps and where it is on its lap (from the
  lap start times: the share of its current lap already driven), its gap to the
  leader and interval (time to the line the leader just crossed);
- tyre compound and tyre age (OpenF1 ``stints``), pit stops made (``pit``);
- retired cars (``session_result`` DNF with no lap started after the moment).

:func:`start_state` turns that into a race-side :class:`StartState`;
:func:`race_setup` into a :class:`RaceSetup` the engine starts from: the cars at
their real places (flying start), lap counting from the real lap (the race ends at
the real race distance), real tyres and stops. Hidden values real timing cannot
give are the documented ``real_race`` defaults in ``config/app.yaml`` (HR-09):
battery = the race-start prior, tyre wear = tyre age x the compound's wear per
lap, fuel = laps to go x fuel per lap + margin. Randomness is only the engine's
named streams (HR-04); ids only (HR-06): OpenF1 driver numbers / acronyms map to
the grid's ``driver_id``.

OpenF1 responses are cached under ``paths.openf1_cache`` (gitignored), so a second
run needs no network. Tests use a trimmed JSON fixture (:meth:`RealRaceData.load`).

    python -m pitwall_sim.replay.real_race --lap 30 --our NOR --seed 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, ConfigError, load_app, load_grid
from pitwall_sim.config.models import AppConfig, Compound, GridConfig, RealRaceConfig
from pitwall_sim.race.engine import RaceEngine, RaceResult, RaceSetup
from pitwall_sim.race.state import StartCar, StartState
from pitwall_sim.track.openf1 import OpenF1Client, OpenF1Error

logger = logging.getLogger(__name__)

type Rows = list[dict[str, Any]]

#: OpenF1 endpoints the moment needs (all filtered by ``session_key``).
ENDPOINTS = ("drivers", "laps", "stints", "pit", "session_result")
#: A scripted Safety Car lap no race reaches (the demo lap is already behind the moment).
NO_SC_LAP = 10**9
#: Lap-row fields kept in a trimmed fixture.
LAP_FIELDS = ("driver_number", "lap_number", "date_start", "lap_duration")


@dataclass(frozen=True)
class RealRaceData:
    """The OpenF1 rows of one race the moment is built from."""

    session_key: int
    drivers: Rows
    laps: Rows
    stints: Rows
    pit: Rows
    session_result: Rows

    @classmethod
    def fetch(cls, session_key: int, client: OpenF1Client) -> RealRaceData:
        """Fetch (or read from the cache) every endpoint for ``session_key``.

        Raises:
            OpenF1Error: OpenF1 is unreachable and nothing is cached, or has no data.

        """
        rows = {e: client.get(e, [("session_key=", str(session_key))]) for e in ENDPOINTS}
        if not rows["laps"] or not rows["drivers"]:
            raise OpenF1Error(f"OpenF1 has no laps / drivers for session {session_key}")
        return cls(session_key, **rows)

    @classmethod
    def load(cls, path: Path) -> RealRaceData:
        """Read a JSON file written by :meth:`save` (the test fixture)."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(int(data["session_key"]), *(data[e] for e in ENDPOINTS))

    def save(self, path: Path) -> None:
        """Write the rows as one JSON file (one row per line)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        parts = [f'"session_key": {self.session_key}']
        for name, rows in asdict(self).items():
            if name != "session_key":
                body = ",\n  ".join(json.dumps(r, separators=(",", ":")) for r in rows)
                parts.append(f'"{name}": [\n  {body}\n ]')
        path.write_text("{\n " + ",\n ".join(parts) + "\n}\n", encoding="utf-8", newline="\n")

    def trimmed(self, laps: Sequence[int]) -> RealRaceData:
        """Keep the lap rows of ``laps`` (fields :data:`LAP_FIELDS`) and the small tables."""
        keep = set(laps)
        lap_rows = [
            {k: r.get(k) for k in LAP_FIELDS} for r in self.laps if int(r["lap_number"]) in keep
        ]
        drivers = [{k: d.get(k) for k in ("driver_number", "name_acronym")} for d in self.drivers]
        return replace(self, laps=lap_rows, drivers=drivers)


@dataclass(frozen=True)
class RealCar:
    """One car at the moment, from real timing."""

    driver_id: str
    number: int
    position: int
    """Running order, 1 = leader; retired cars after the running ones."""
    laps_done: int
    lap_fraction: float
    lap_elapsed_s: float
    gap_s: float
    interval_s: float
    compound: Compound
    tyre_age_laps: int
    pit_stops: int
    retired: bool


@dataclass(frozen=True)
class RealMoment:
    """The real race when the leader starts lap ``lap``."""

    session_key: int
    lap: int
    race_laps: int
    cars: tuple[RealCar, ...]
    """Running order, retired cars last."""

    @property
    def laps_to_go(self) -> int:
        """Laps left to race including lap ``lap`` (race laps - lap after this one)."""
        return self.race_laps - self.lap + 1

    @property
    def order(self) -> tuple[str, ...]:
        """driver_ids, leader first (retired last)."""
        return tuple(c.driver_id for c in self.cars)

    @property
    def retired(self) -> tuple[str, ...]:
        """driver_ids of the cars out before the moment."""
        return tuple(c.driver_id for c in self.cars if c.retired)


def _time(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def driver_ids(data: RealRaceData, grid: GridConfig) -> dict[int, str]:
    """OpenF1 driver number -> the grid's ``driver_id`` (by race number, then acronym).

    Raises:
        ConfigError: A car of the real race is not on the grid.

    """
    by_number = {d.number: d.driver_id for t in grid.teams for d in t.drivers}
    by_code = {d.code: d.driver_id for t in grid.teams for d in t.drivers}
    out: dict[int, str] = {}
    for row in data.drivers:
        number = int(row["driver_number"])
        driver = by_number.get(number) or by_code.get(str(row.get("name_acronym")))
        if driver is None:
            raise ConfigError(f"OpenF1 car {number} {row.get('name_acronym')} is not on the grid")
        out[number] = driver
    return out


def race_laps(data: RealRaceData) -> int:
    """Return the real race distance: the winner's laps (else the most laps started)."""
    winner = [r for r in data.session_result if r.get("position") == 1]
    if winner and winner[0].get("number_of_laps"):
        return int(winner[0]["number_of_laps"])
    return max(int(r["lap_number"]) for r in data.laps)


def _tyres(data: RealRaceData, number: int, lap: int) -> tuple[Compound, int]:
    """Compound and tyre age (laps done on the set) at the start of ``lap``."""
    stints = [
        s
        for s in data.stints
        if int(s["driver_number"]) == number and s.get("lap_start") is not None
        if int(s["lap_start"]) <= lap
    ]
    if not stints:
        return Compound.MEDIUM, max(lap - 1, 0)
    stint = max(stints, key=lambda s: (int(s["lap_start"]), int(s["stint_number"])))
    try:
        compound = Compound(str(stint.get("compound")).upper())
    except ValueError:
        compound = Compound.MEDIUM
    age = int(stint.get("tyre_age_at_start") or 0) + lap - int(stint["lap_start"])
    return compound, max(age, 0)


def moment(data: RealRaceData, lap: int, grid: GridConfig) -> RealMoment:
    """Build the real race at the moment the leader starts ``lap`` (2 .. race laps).

    Each car's place: its last line crossing before the moment (lap ``k`` started)
    and the next one; the share of that lap already driven = time since / lap time.
    Gap = time until the car reaches the line the leader just crossed.

    Raises:
        ValueError: ``lap`` is outside 2 .. race laps, or no car started it.
        ConfigError: A car of the real race is not on the grid.

    """
    total = race_laps(data)
    if not 2 <= lap <= total:
        raise ValueError(f"lap {lap} is outside 2 .. {total}")
    ids = driver_ids(data, grid)
    starts: dict[int, dict[int, float]] = {n: {} for n in ids}
    durations: dict[int, list[float]] = {n: [] for n in ids}
    for row in data.laps:
        n = int(row["driver_number"])
        if n not in starts:
            continue
        if row.get("date_start"):
            starts[n][int(row["lap_number"])] = _time(str(row["date_start"]))
        if row.get("lap_duration"):
            durations[n].append(float(row["lap_duration"]))
    leaders = {n: s[lap] for n, s in starts.items() if lap in s}
    if not leaders:
        raise ValueError(f"no car started lap {lap}")
    t0 = min(leaders.values())
    out = {int(r["driver_number"]): bool(r.get("dnf") or r.get("dns")) for r in data.session_result}
    pits = [
        (int(p["driver_number"]), int(p["lap_number"])) for p in data.pit if p.get("lap_number")
    ]

    rows: list[dict[str, Any]] = []
    for n, s in starts.items():
        before = [k for k, t in s.items() if t <= t0]
        after = [k for k, t in s.items() if t > t0]
        k = max(before) if before else 1
        t_k = s.get(k, t0)
        typical = sorted(durations[n])[len(durations[n]) // 2] if durations[n] else 100.0
        retired = not after and out.get(n, False)
        if after:
            nxt = min(after)
            per_lap = (s[nxt] - t_k) / (nxt - k)
        else:  # no later lap start: retired, or a gap in the data (extrapolate)
            nxt, per_lap = k + 1, typical
        progress = (k - 1) + (t0 - t_k) / per_lap
        if retired:
            progress = float(k - 1)
        laps_done = int(progress)
        fraction = progress - laps_done
        gap = s[lap] - t0 if lap in s else (lap - 1 - progress) * per_lap
        if retired:
            gap = 0.0  # out of the race: no gap in the timing
        current = laps_done + 1
        compound, age = _tyres(data, n, current)
        rows.append(
            {
                "n": n,
                "progress": progress,
                "laps_done": laps_done,
                "fraction": fraction,
                "elapsed": fraction * per_lap,
                "gap": max(gap, 0.0),
                "compound": compound,
                "age": age,
                "stops": sum(1 for car, pit_lap in pits if car == n and pit_lap < current),
                "retired": retired,
            }
        )
    rows.sort(key=lambda r: (r["retired"], -r["progress"], r["gap"]))
    cars = []
    ahead_gap = 0.0
    for pos, r in enumerate(rows, start=1):
        cars.append(
            RealCar(
                driver_id=ids[r["n"]], number=r["n"], position=pos, laps_done=r["laps_done"],
                lap_fraction=r["fraction"], lap_elapsed_s=r["elapsed"], gap_s=r["gap"],
                interval_s=0.0 if r["retired"] else max(r["gap"] - ahead_gap, 0.0),
                compound=r["compound"],
                tyre_age_laps=r["age"], pit_stops=r["stops"], retired=r["retired"],
            )
        )  # fmt: skip
        ahead_gap = r["gap"]
    return RealMoment(data.session_key, lap, total, tuple(cars))


def start_state(real: RealMoment, cfg: RealRaceConfig) -> StartState:
    """Race-side start state; hidden values from the ``real_race`` defaults (HR-09)."""
    cars = tuple(
        StartCar(
            driver_id=c.driver_id,
            laps_done=c.laps_done,
            lap_fraction=c.lap_fraction,
            lap_elapsed_s=c.lap_elapsed_s,
            gap_s=c.gap_s,
            interval_s=c.interval_s,
            compound=c.compound,
            tyre_age_laps=c.tyre_age_laps,
            tyre_wear=min(c.tyre_age_laps * cfg.wear_per_lap.get(c.compound, 0.0), 1.0),
            pit_stops=c.pit_stops,
            retired=c.retired,
        )  # fmt: skip
        for c in real.cars
    )
    return StartState(cars, cfg.battery_fraction, cfg.min_spacing_m)


def race_setup(base: RaceSetup, real: RealMoment, app: AppConfig) -> RaceSetup:
    """Return ``base`` (seed, Rule Set, Our Car, ...) started from the real moment.

    Laps count from the real lap to the real race distance; fuel for the laps to
    go (+ margin); the real race was dry; a demo Safety Car lap already behind the
    moment is dropped (it would fire at once).
    """
    cfg = app.real_race
    sc_lap = base.scripted_sc_lap
    if sc_lap is None:
        sc_lap = app.demo.scripted_sc_lap
    return replace(
        base,
        laps=real.race_laps,
        grid_order=real.order,
        fuel_kg=real.laps_to_go * cfg.fuel_per_lap_kg + cfg.fuel_margin_kg,
        rain="dry",
        scripted_sc_lap=sc_lap if sc_lap is None or sc_lap > real.lap else NO_SC_LAP,
        start=start_state(real, cfg),
    )


def load_data(
    app: AppConfig, config_dir: Path = DEFAULT_CONFIG_DIR, session_key: int | None = None
) -> RealRaceData:
    """Load the real race's OpenF1 rows from the cache under ``paths.openf1_cache`` or the API."""
    cache = Path(app.paths.openf1_cache)
    if not cache.is_absolute():
        cache = config_dir.resolve().parent / cache
    key = app.real_race.session_key if session_key is None else session_key
    return RealRaceData.fetch(key, OpenF1Client(app.openf1, cache))


def real_setup(
    base: RaceSetup,
    lap: int,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    data: RealRaceData | None = None,
) -> RaceSetup:
    """Return ``base`` started at the real race's lap ``lap`` (data from OpenF1 unless given)."""
    app = load_app(config_dir)
    rows = load_data(app, config_dir) if data is None else data
    real = moment(rows, lap, load_grid(base.grid_id, config_dir))
    return race_setup(base, real, app)


# --------------------------------------------------------------------------- #
# Headless CLI
# --------------------------------------------------------------------------- #


def format_moment(real: RealMoment) -> list[str]:
    """Format the starting grid at the moment as table rows."""
    lines = [
        f"Real race moment: session {real.session_key}, start of lap {real.lap}/{real.race_laps}"
        f" ({real.laps_to_go} laps to race)",
        f"{'pos':>3} {'car':<4} {'laps':>4} {'gap s':>7} {'int s':>6} {'tyre':<6} {'age':>3}"
        f" {'stops':>5}",
    ]
    for c in real.cars:
        status = "  OUT" if c.retired else ""
        lines.append(
            f"{c.position:>3} {c.driver_id:<4} {c.laps_done:>4} {c.gap_s:>7.3f} "
            f"{c.interval_s:>6.3f} {c.compound.value:<6} {c.tyre_age_laps:>3} {c.pit_stops:>5}"
            f"{status}"
        )
    return lines


def real_classification(data: RealRaceData, grid: GridConfig) -> list[str]:
    """Return the real race's classification (driver_ids), classified cars first."""
    ids = driver_ids(data, grid)
    rows = sorted(
        data.session_result,
        key=lambda r: (r.get("position") is None, r.get("position") or 0,
                       -(r.get("number_of_laps") or 0)),
    )  # fmt: skip
    return [ids[int(r["driver_number"])] for r in rows if int(r["driver_number"]) in ids]


def format_result(
    result: RaceResult, real_order: list[str], real_finishers: int, our: str | None
) -> list[str]:
    """Sim classification beside the real one (``real_finishers`` classified, then DNF)."""

    def name(driver: str, retired: bool) -> str:
        return driver + ("*" if driver == our else "") + (" DNF" if retired else "")

    lines = [f"{'pos':>3} {'sim':<10} {'real':<10}   (* Our Car)"]
    for k in range(max(len(result.classification), len(real_order))):
        sim = result.classification[k] if k < len(result.classification) else ""
        real = real_order[k] if k < len(real_order) else ""
        sim_name = name(sim, sim in result.retired) if sim else ""
        real_name = name(real, k >= real_finishers) if real else ""
        lines.append(f"{k + 1:>3} {sim_name:<10} {real_name:<10}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Start a race at a real lap, run it headless to the flag, print grid and result."""
    parser = argparse.ArgumentParser(description="Start the sim from a real 2026 Suzuka lap")
    parser.add_argument("--lap", type=int, default=None, help="real lap to start (default 30)")
    parser.add_argument("--our", default=None, help="Our Car's driver_id, e.g. NOR")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rules", default="2026_post_miami")
    parser.add_argument("--fixture", type=Path, default=None, help="OpenF1 rows JSON (offline)")
    parser.add_argument("--save-fixture", type=Path, default=None,
                        help="write the rows around the lap as a trimmed fixture")  # fmt: skip
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app = load_app(args.config_dir)
    lap = app.real_race.default_lap if args.lap is None else int(args.lap)
    try:
        data = (
            load_data(app, args.config_dir)
            if args.fixture is None
            else RealRaceData.load(args.fixture)
        )
    except OpenF1Error as exc:
        print(f"OpenF1 unavailable: {exc}", file=sys.stderr)
        return 2
    base = RaceSetup(rule_set_id=args.rules, seed=args.seed, our_driver_id=args.our)
    grid = load_grid(base.grid_id, args.config_dir)
    try:
        real = moment(data, lap, grid)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.save_fixture is not None:
        keep = [
            1,
            *range(max(lap - 12, 2), lap + 4),
            *range(real.race_laps - 7, real.race_laps + 1),
        ]
        data.trimmed(keep).save(args.save_fixture)
    print("\n".join(format_moment(real)))
    engine = RaceEngine(race_setup(base, real, app), args.config_dir)
    result = engine.run()
    print(f"\nSim from lap {lap} to the flag (seed {args.seed}): {result.t_s:.0f} s race time")
    real_order = real_classification(data, grid)
    finishers = sum(1 for r in data.session_result if r.get("position") is not None)
    print("\n".join(format_result(result, real_order, finishers, args.our)))
    return 0 if result.finished else 3


if __name__ == "__main__":
    sys.exit(main())

"""Decision costs (hackathon H1, part 2): what each call cost against its alternatives.

After the flag, every :class:`CallRecord` is replayed from the snapshot taken just
before it: the call as made and its main alternatives, each with ``N_SEEDS``
paired seeds (the overtake and mistake streams reseeded identically in every
variant, common random numbers, as ``engineer/call_outcome``; analysis forks
only, never a race). Outcome: the race time Our Car needs to cover the next
``HORIZON_LAPS`` laps from the call (or to the flag). Truth is allowed here: the
race is over (owner, H1).

Alternatives: an alert's other options (Ignore included); a command's "not sent"
plus one or two sensible others (:func:`alternatives`). Results are cached on
disk by the snapshot's state hash (``cache_dir``): rehearsing the demo race with
the same calls fills the cache, so the costs show at once on stage.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pitwall_sim.engineer.calls import CallOption, CallRunner, CallStep, When
from pitwall_sim.engineer.commands import CommandType, EngineerCommand, make_command
from pitwall_sim.engineer.records import CallCost, CallRecord
from pitwall_sim.observe.engineer_view import EngineerView, EngineerViewBuilder
from pitwall_sim.race.engine import RaceEngine
from pitwall_sim.race.snapshot import Snapshot

logger = logging.getLogger(__name__)
T = CommandType
N_SEEDS = 5
HORIZON_LAPS = 2
BEST_TIE_S = 0.05
"""Within this of the best option the call counts as the best one."""
Command = tuple[CommandType, dict[str, Any]]
MODES = ("PUSH", "BALANCED", "HARVEST")


@dataclass(frozen=True)
class CallSpec:
    """What a call was, so it and its alternatives can be replayed."""

    options: tuple[CallOption, ...] | None
    """An alert's options (None for a button / radio command)."""
    commands: tuple[Command, ...]
    """A button / radio command's commands."""
    when: When
    view: EngineerView
    """The pit wall's view at the call (next-lap steps count laps from it)."""


def _option(label: str, when: When, commands: tuple[Command, ...]) -> CallOption:
    steps = (CallStep(when, commands),) if commands else ()
    return CallOption(0, label, steps, "", "")


def alternatives(record: CallRecord, spec: CallSpec) -> list[CallOption]:
    """Return the call as made first, then its alternatives (labels unique)."""
    if spec.options is not None:
        chosen = [o for o in spec.options if o.label == record.option_label]
        others = [o for o in spec.options if o.label != record.option_label]
        return chosen + others
    made = _option(record.option_label, spec.when, spec.commands)
    out = [made, _option("not sent", spec.when, ())]
    kind, params = spec.commands[0]
    if kind == T.SET_ENERGY_MODE:
        current = str(spec.view.our_car.energy_mode)
        for mode in MODES:
            if mode not in (params.get("mode"), current):
                out.append(_option(f"mode {mode}", spec.when, ((kind, {"mode": mode}),)))
    elif kind == T.BOX:
        later = dict(params, lap=int(params["lap"]) + 1)
        out.append(_option("BOX +1 lap", spec.when, ((kind, later),)))
    elif kind == T.ATTACK:
        out.append(_option("HOLD", spec.when, ((T.HOLD_POSITION, {}),)))
    elif kind == T.HOLD_POSITION:
        out.append(_option("ATTACK", spec.when, ((T.ATTACK, {}),)))
    elif kind == T.PUSH_LAP:
        out.append(_option("mode PUSH", spec.when, ((T.SET_ENERGY_MODE, {"mode": "PUSH"}),)))
    return out


def _issuer(engine: RaceEngine) -> Callable[[CommandType, dict[str, Any]], str | None]:
    def issue(kind: CommandType, params: dict[str, Any]) -> str | None:
        cmd = make_command(kind, params, engine.command_context(), engine.app.engineer,
                           engine.t, engine.app.radio.radio_latency_s)  # fmt: skip
        if isinstance(cmd, EngineerCommand):
            engine.submit(cmd)
            return None
        return cmd.reason

    return issue


def run_variant(snap: Snapshot, our: str, option: CallOption, view: EngineerView,
                seed_key: int, k: int) -> float:  # fmt: skip
    """Race seconds Our Car needs from the call to ``HORIZON_LAPS`` laps on (or the flag)."""
    fork = RaceEngine.from_snapshot(snap)
    fork.overtake.rng = np.random.default_rng([seed_key, k, 1])  # paired across variants
    fork.rngs["mistakes"] = np.random.default_rng([seed_key, k, 2])
    i = fork.driver_ids.index(our)
    length = fork.trk.length_m
    start = float(fork.st.lap[i]) * length + float(fork.st.s_m[i])
    goal = min(start + HORIZON_LAPS * length, fork.laps * length)
    runner = CallRunner(_issuer(fork))
    runner.start(option, view)
    builder = EngineerViewBuilder(fork, our) if runner.pending else None
    limit = snap.t + 1200.0
    while fork.t < limit:
        fork.tick()
        if builder is not None and runner.pending:
            runner.update(builder.build())
        if fork.status[i] == "FINISHED":
            return float(fork.timing.finish_t[i]) - snap.t
        if fork.status[i] == "DNF":
            return limit - snap.t
        if float(fork.st.lap[i]) * length + float(fork.st.s_m[i]) >= goal:
            return fork.t - snap.t
    return fork.t - snap.t


def _key(record: CallRecord, snap: Snapshot, labels: list[str], our: str) -> str:
    text = json.dumps([snap.race_state.hash(), labels, our, N_SEEDS, HORIZON_LAPS,
                       record.option_label])  # fmt: skip
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def call_cost(record: CallRecord, index: int, spec: CallSpec, snap: Snapshot, our: str,
              cache_dir: Path | None = None) -> CallCost:  # fmt: skip
    """Cost of one call against its alternatives (cached by snapshot)."""
    options = alternatives(record, spec)
    labels = [o.label for o in options]
    call_id = f"{record.snapshot_id}#{index}"
    path = None
    if cache_dir is not None:
        path = cache_dir / f"{_key(record, snap, labels, our)}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return CallCost(call_id, **data)
    seed_key = int(snap.race_state.hash()[:8], 16)
    means = {o.label: float(np.mean([run_variant(snap, our, o, spec.view, seed_key, k)
                                     for k in range(N_SEEDS)])) for o in options}  # fmt: skip
    yours = means[options[0].label]
    best = min(means, key=lambda label: means[label])
    data = {
        "your_outcome_s": yours, "best_option_label": best, "best_outcome_s": means[best],
        "delta_s": yours - means[best], "n_seeds": N_SEEDS,
    }  # fmt: skip
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return CallCost(call_id, **data)


def describe(cost: CallCost) -> str:
    """One line for the Reveal: your call's cost against the best option."""
    if cost.delta_s <= BEST_TIE_S:
        return "best call"
    return f"your call: +{cost.delta_s:.1f} s vs best option ({cost.best_option_label})"

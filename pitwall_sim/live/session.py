"""Live race session for the pit wall (sprint S-5): engine + EngineerView + alerts + calls.

Owns one :class:`RaceEngine` and gives the UI only what the race engineer sees:
an :class:`EngineerView` per frame, the alerts of the configured provider
(``observe/alerts``, fed with the view only), the radio log, and command / call
entry points that validate Engineer Commands against public facts. Test mode adds
the Rivals' TRUE battery for checking alerts by eye; it is off unless the setup
asks for it, and the UI labels it.

Thread safety: every public method takes the session lock, so a UI thread can
call ``command`` / ``call`` / ``frame`` while a worker thread calls ``advance``.
No Qt here: the session runs headless in tests.

Hackathon (H1, H2): every engineer call (an alert option, including Ignore; a
button command) is logged as a :class:`CallRecord` with a race snapshot taken just
before it (``call_log``, ``snapshots``), and engineer / driver radio lines reach
the view as :class:`RadioEvent`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_grid
from pitwall_sim.engineer.calls import CallOption, CallRunner, CallStep, alert_line, options
from pitwall_sim.engineer.commands import CommandType, EngineerCommand, make_command
from pitwall_sim.engineer.radio_parser import SAY_AGAIN, ParseResult, corner_names, parse
from pitwall_sim.engineer.records import CallCost, CallRecord, RadioEvent, RadioSource
from pitwall_sim.live import presets
from pitwall_sim.live.costs import CallSpec, call_cost, describe
from pitwall_sim.live.driver_radio import DriverRadio
from pitwall_sim.live.presets import Preset
from pitwall_sim.live.radio_ai import RadioAI
from pitwall_sim.live.reveal import RevealData, RevealRecorder
from pitwall_sim.live.strategy import PublicInfo, StrategyWorker, plans_for
from pitwall_sim.observe.alerts import Alert, make_provider
from pitwall_sim.observe.engineer_view import EngineerView, EngineerViewBuilder
from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.snapshot import Snapshot
from pitwall_sim.radio import llm_commands
from pitwall_sim.radio.hosted_llm import make_provider as make_llm_provider
from pitwall_sim.radio.llm_replies import reply_facts, write_reply

MJ = 1e6
#: Driver radio when the track status changes (H4, templates).
TRACK_STATUS_LINES = {
    "SC": "Safety car, safety car. Box or stay out?",
    "VSC": "VSC, VSC. Slowing down.",
    "SC_IN_THIS_LAP": "Safety car in this lap.",
    "GREEN_FROM_SC_IN_THIS_LAP": "Green flag, we're racing.",
    "GREEN_FROM_SC": "Green flag, we're racing.",
    "GREEN_FROM_VSC": "VSC ending, green flag.",
}


@dataclass(frozen=True)
class LiveSetup:
    """What the setup screen chose."""

    our_driver_id: str
    rule_set_id: str = "2026_post_miami"
    seed: int = 42
    track_id: str = "suzuka"
    pause_on_alert: bool = False
    test_mode: bool = False
    preset: Preset = "none"
    fuel_kg: float = 110.0
    """Start fuel (110 kg until T-02B calibrates ``fuel_start_kg``)."""
    laps: int | None = None
    scripted_sc_lap: int | None = None
    """Force a Safety Car on this lap (demo); ``None`` = ``demo.scripted_sc_lap``."""
    strategy: bool = False
    """Run the strategy panel's background forks (H5); the pit wall turns it on."""


@dataclass(frozen=True)
class RadioLine:
    """One radio log entry."""

    t_s: float
    sender: Literal["ENGINEER", "DRIVER", "SYSTEM"]
    text: str
    rejected: bool = False


@dataclass
class AlertRecord:
    """An alert, what the engineer did about it and what followed (A-4)."""

    alert: Alert
    option: str
    """Option label, ``pending``, ``ignored`` or ``expired``."""
    t_s: float
    our_ahead: bool
    """Our Car ahead of the rival when the alert fired (public order)."""
    our_lap: int
    outcome: str | None = None
    """After ``OUTCOME_LAPS`` of Our Car: pass made / position kept / position lost /
    re-passed / no pass."""
    true_diff_mj: float | None = None
    """Test mode: rival's TRUE battery minus ours when the alert fired."""
    correct: bool | None = None
    """Test mode, ATTACK / DEFEND: was the energy difference real? (energy branch: by
    the margin; observed clip / own battery: the rival really had less / more)"""

    @property
    def answered(self) -> bool:
        """A call was made (not pending, ignored or expired)."""
        return self.option not in ("pending", "ignored", "expired")


@dataclass(frozen=True)
class CallSummary:
    """End-of-race call summary (A-4)."""

    records: list[AlertRecord]
    alerts: int
    calls_made: int
    successful_attacks: int
    successful_defends: int
    correct: int | None
    """Test mode: alerts confirmed by Ground Truth (of those it can judge)."""
    judged: int | None


OUTCOME_LAPS = 2


@dataclass(frozen=True)
class Frame:
    """Everything the pit wall draws for one moment."""

    view: EngineerView
    alerts: list[Alert]
    """Active alerts, newest first."""
    options: dict[str, list[CallOption]]
    """alert_id -> its call options."""
    radio: list[RadioLine]
    truth_mj: dict[str, float] | None
    """Rivals' TRUE battery, Test mode only."""
    paused_on_alert: bool
    finished: bool
    lap: int
    laps: int


@dataclass
class _Ack:
    due_t: float
    text: str
    is_fallback: bool = False


@dataclass
class LiveSession:
    """One live race for the pit wall."""

    setup: LiveSetup
    config_dir: Path = DEFAULT_CONFIG_DIR
    engine: RaceEngine = field(init=False)
    radio: list[RadioLine] = field(default_factory=list)
    calls: list[AlertRecord] = field(default_factory=list)
    call_log: list[CallRecord] = field(default_factory=list)
    """Every engineer call (H1): alert options and button / radio commands."""
    snapshots: dict[str, Snapshot] = field(default_factory=dict)
    call_specs: list[CallSpec] = field(default_factory=list)
    costs: dict[int, CallCost] = field(default_factory=dict)
    strategy_lap: int | None = None
    """Our Car's lap the shown strategy was computed at (H5)."""
    """CallRecord index -> its decision cost, once computed."""
    """Per CallRecord: what the call was, to replay it and its alternatives (H1 costs)."""
    """snapshot_id -> the race just before the call(s) made at that moment."""
    paused_on_alert: bool = False
    radio_ai: RadioAI = field(init=False)
    """Hosted radio LLM (H2/H3) and its worker; off unless ``radio_llm.provider`` is set."""
    radio_path: str = field(init=False, default="")
    """Which path understood the last engineer message (LLM / KEYWORD / SAY AGAIN)."""

    def __post_init__(self) -> None:
        """Build the race, the view builder, the alert provider and the call runner."""
        s = self.setup
        grid_cfg = load_grid("real_2026", self.config_dir)
        default = tuple(d.driver_id for t in grid_cfg.teams for d in t.drivers)
        self.engine = RaceEngine(
            RaceSetup(track_id=s.track_id, rule_set_id=s.rule_set_id, seed=s.seed, laps=s.laps,
                      fuel_kg=s.fuel_kg, our_driver_id=s.our_driver_id,
                      scripted_sc_lap=s.scripted_sc_lap,
                      grid_order=presets.grid_order(s.preset, s.our_driver_id, default)),
            self.config_dir,
        )  # fmt: skip
        self.preset_rival = presets.apply(s.preset, self.engine, s.our_driver_id)
        self._lock = threading.RLock()
        self._builder = EngineerViewBuilder(self.engine, s.our_driver_id)
        eng = self.engine
        self._provider = make_provider(
            eng.app.alerts, eng.track, eng.rules.power, eng.app.feed.rate_hz
        )
        self._runner = CallRunner(self._issue)
        self._acks: list[_Ack] = []
        self._records: dict[str, AlertRecord] = {}
        self._seen: set[str] = set()
        self._answered: set[str] = set()
        self._alerts: list[Alert] = []
        self._options: dict[str, list[CallOption]] = {}
        self._issued: list[str] = []
        self._corners = corner_names(
            [(c.corner_id, c.name, list(c.aliases)) for c in self.engine.track.corners]
        )
        self._strategy = (
            StrategyWorker(self.engine.app.strategy_panel.workers) if s.strategy else None
        )
        self._strategy_lap = -1
        self._driver_radio = DriverRadio(s.our_driver_id, self.engine.track)
        if self._strategy is not None:
            self._strategy.start()  # spawn the processes before the race runs
        self._reveal = RevealRecorder(
            s.our_driver_id, self._builder.rivals, float(self.engine.trk.length_m)
        )
        self._status = self.engine.track_status.status
        """command_ids issued so far (CallRecords take the ones of their call)."""
        self._view = self._builder.build()
        self.radio_ai = RadioAI(
            make_llm_provider(self.engine.app.radio_llm), self.engine.app.radio_llm
        )
        grid = {d.driver_id: (t, d) for t in self.engine.grid.teams for d in t.drivers}
        self.drivers = {
            d: {"code": grid[d][1].code, "team": grid[d][0].display_name,
                "color": str(grid[d][0].color_hex) if str(grid[d][0].color_hex).startswith("#")
                else "#8C8C8C"}
            for d in self.engine.driver_ids
        }  # fmt: skip

    # ------------------------------------------------------------------ #
    # Track geometry for the map (public: the circuit layout)
    # ------------------------------------------------------------------ #

    @property
    def outline(self) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Return the centre line (x, y) in metres."""
        return self.engine.model.x_m, self.engine.model.y_m

    def xy_at(self, s_m: float) -> tuple[float, float]:
        """Return the map position of lap distance ``s_m``."""
        m = self.engine.model
        k = int(s_m / m.length_m * m.s_m.size) % m.s_m.size
        return float(m.x_m[k]), float(m.y_m[k])

    # ------------------------------------------------------------------ #
    # Running
    # ------------------------------------------------------------------ #

    @property
    def t_s(self) -> float:
        """Return the sim time."""
        return self.engine.t

    def advance(self, sim_s: float) -> bool:
        """Run up to ``sim_s`` of race (whole ticks); stop early on a new alert if asked.

        Returns False once the race is over. Every tick is simulated (HR-08).
        """
        with self._lock:
            if self.paused_on_alert:
                return not self.engine.finished
            end = self.engine.t + sim_s
            while self.engine.t < end and not self.engine.finished:
                self.engine.tick()
                self._after_tick()
                if self.paused_on_alert:
                    break
            return not self.engine.finished

    def resume(self) -> None:
        """Continue after a pause on alert."""
        with self._lock:
            self.paused_on_alert = False

    def _after_tick(self) -> None:
        self._view = view = self._builder.build()
        self._reveal.sample(view, self._truth_mj())
        self._reveal.after(view, self.engine.finished)
        self._strategy_upkeep(view)
        if not self.engine.finished and (said := self._driver_radio.update(view)):
            self._driver_line(said, view)  # unprompted (H3): template, or LLM-written
        if view.track_status.status != self._status:
            self._track_status_radio(self._status, view.track_status.status)
            self._status = view.track_status.status
        alerts = self._provider.update(view)
        current = {a.alert_id for a in alerts}
        for old in self._alerts:  # gone without an answer: expired
            if old.alert_id not in current and old.alert_id not in self._answered:
                self._records[old.alert_id].option = "expired"
                self._answered.add(old.alert_id)
        for alert in alerts:
            if alert.alert_id not in self._seen:
                self._seen.add(alert.alert_id)
                self._options[alert.alert_id] = options(alert, view, self.engine.track)
                self._record(alert, view)
                if self.setup.pause_on_alert:
                    self.paused_on_alert = True
        self._judge(view)
        self._alerts = [a for a in alerts if a.alert_id not in self._answered]
        for reason in self._runner.update(view):
            self._say("SYSTEM", f"Rejected: {reason}", rejected=True)
        due = [a for a in self._acks if a.due_t <= view.t_s]
        for ack in due:
            self._say("DRIVER", ack.text, is_fallback=ack.is_fallback)
        self._acks = [a for a in self._acks if a.due_t > view.t_s]

    # ------------------------------------------------------------------ #
    # Engineer input
    # ------------------------------------------------------------------ #

    def command(self, kind: CommandType, params: dict[str, Any], say: str | None = None) -> (
        str | None
    ):  # fmt: skip
        """Send one Engineer Command from a button; return the rejection reason or None."""
        return self.command_from(kind, params, say)

    def command_from(
        self, kind: CommandType, params: dict[str, Any], say: str | None = None,
        source: RadioSource = "TEMPLATE",
    ) -> str | None:  # fmt: skip
        """Send one command (button, or radio with ``source``); log its CallRecord."""
        with self._lock:
            snapshot_id = self._snapshot_now()
            first = len(self._issued)
            reason = self._issue(kind, params)
            ids = tuple(self._issued[first:])
            if say:
                self._say("ENGINEER", say, source=source, command_ids=ids)
            if reason is not None:
                self._say("SYSTEM", f"Rejected {kind}: {reason}", rejected=True)
                return reason
            spec = CallSpec(None, ((kind, dict(params)),), "now", self._view)
            self._log_call(None, ids, str(kind), snapshot_id, spec)
            return None

    def radio_message(self, text: str, source: RadioSource = "TEXT",
                      result: ParseResult | None = None) -> list[str]:  # fmt: skip
        """Engineer radio (H2): parse ``text`` into commands, send them; return rejections.

        Each command goes through ``commands.validate`` and the queue (HR-07) and is a
        :class:`CallRecord`; "next lap" ones are sent at the start of Our Car's next
        lap. Nothing understood: the driver answers "Say again?". ``result``: the
        commands the hosted LLM proposed (else the keyword parser reads ``text``).
        """
        with self._lock:
            view = self._view
            car = view.our_car
            compound = "MEDIUM" if str(car.compound) in ("HARD", "Compound.HARD") else "HARD"
            path = "LLM" if result is not None else "KEYWORD"
            if result is None:
                result = parse(text, self._corners, car.lap + 1, compound, str(car.energy_mode))
            path = path if result.commands else "SAY AGAIN"
            self.radio_path = ("VOICE > " if source == "VOICE" else "") + path
            snapshot_id = self._snapshot_now()
            first = len(self._issued)
            reasons: list[str] = []
            later: list[tuple[CommandType, dict[str, Any]]] = []
            for cmd in result.commands:
                spec = CallSpec(None, ((cmd.kind, dict(cmd.params)),), cmd.when, view)
                if cmd.when == "next_lap":
                    later.append((cmd.kind, cmd.params))
                    self._log_call(None, (), f"radio: {cmd.kind} (next lap)", snapshot_id, spec)
                    continue
                start = len(self._issued)
                reason = self._issue(cmd.kind, cmd.params)
                if reason is not None:
                    reasons.append(f"{cmd.kind}: {reason}")
                    continue
                ids = tuple(self._issued[start:])
                self._log_call(None, ids, f"radio: {cmd.kind}", snapshot_id, spec)
            if later:
                step = CallStep("next_lap", tuple(later))
                self._runner.start(CallOption(0, "radio", (step,), "", ""), view)
            self._say("ENGINEER", text, source=source, command_ids=tuple(self._issued[first:]))
            for reason in reasons:
                self._say("SYSTEM", f"Rejected {reason}", rejected=True)
            reply = result.ack if not reasons or len(reasons) < len(result.commands) else (
                "Can't do that.")  # fmt: skip
            latency = self.engine.app.radio.radio_latency_s
            if not result.commands:
                self._acks.append(_Ack(self.engine.t + latency, SAY_AGAIN, is_fallback=True))
            else:
                self._acks.append(_Ack(self.engine.t + latency, reply))
            return reasons

    def radio_send(self, text: str, source: RadioSource = "TEXT") -> None:
        """Engineer radio from the UI (H2): never blocks on the hosted LLM.

        LLM off: the keyword parser now (:meth:`radio_message`). LLM on: the request is
        built here (Our Car data, public timing, corner names; HR-03) and runs on the
        radio worker; its tool calls, or the keyword parser if it fails or times out,
        then go through :meth:`radio_message` (validation, HR-07).
        """
        ai = self.radio_ai
        if not ai.on or ai.provider is None:
            self.radio_message(text, source)
            return
        provider = ai.provider
        with self._lock:
            ctx = self.engine.command_context()
            corners = [(c.corner_id, c.name, list(c.aliases)) for c in self.engine.track.corners]
            user = llm_commands.prompt(text, self._view, self.setup.our_driver_id, ctx, corners)
            tool_set = llm_commands.tools(ctx, self.engine.app.engineer)
            self.radio_path = ("VOICE > " if source == "VOICE" else "") + "LLM ..."

        def job() -> None:
            result = llm_commands.interpret(provider, user, tool_set, ai.timeout_s)
            self.radio_message(text, source, result)

        ai.submit(job)

    def _driver_line(self, template: str, view: EngineerView) -> None:
        """Say an unprompted driver line (H3): LLM-written if it passes the fact check."""
        ai = self.radio_ai
        if not ai.replies_on or ai.provider is None:
            self._say("DRIVER", template)
            return
        provider = ai.provider
        facts = reply_facts(view, self.setup.our_driver_id, self.engine.laps, template)

        def job() -> None:
            text = write_reply(provider, facts, ai.timeout_s, ai.max_words)
            with self._lock:
                if text is not None:
                    self._say("DRIVER", text, source="LLM")
                else:
                    self._say("DRIVER", template, is_fallback=True)

        ai.submit(job)

    def call(self, alert_id: str, key: int) -> list[str]:
        """Answer an alert with option ``key`` (1..3); return rejection reasons."""
        with self._lock:
            opts = self._options.get(alert_id, [])
            option = next((o for o in opts if o.key == key), None)
            alert = next((a for a in self._alerts if a.alert_id == alert_id), None)
            if option is None or alert is None:
                return [f"no option {key} for {alert_id}"]
            self._answered.add(alert_id)
            self._alerts = [a for a in self._alerts if a.alert_id != alert_id]
            ignored = not option.steps and not option.radio
            self._records[alert_id].option = "ignored" if ignored else option.label
            snapshot_id = self._snapshot_now()
            first = len(self._issued)
            reasons = self._runner.start(option, self._view)
            ids = tuple(self._issued[first:])
            if option.radio:
                self._say("ENGINEER", option.radio, command_ids=ids)
            spec = CallSpec(tuple(opts), (), "now", self._view)
            self._log_call(alert_id, ids, option.label, snapshot_id, spec)
            for reason in reasons:
                self._say("SYSTEM", f"Rejected: {reason}", rejected=True)
            if option.ack and not reasons:
                latency = self.engine.app.radio.radio_latency_s
                self._acks.append(_Ack(self.engine.t + latency, option.ack))
            self.paused_on_alert = False
            return reasons

    # ------------------------------------------------------------------ #
    # Call summary (A-4)
    # ------------------------------------------------------------------ #

    def _record(self, alert: Alert, view: EngineerView) -> None:
        record = AlertRecord(
            alert, "pending", view.t_s, _ahead(view, self.setup.our_driver_id, alert.rival),
            view.our_car.lap,
        )  # fmt: skip
        if self.setup.test_mode:
            i = self.engine.driver_ids.index(alert.rival)
            diff = float(self.engine.st.battery_j[i]) / MJ - view.our_car.battery_mj
            margin = self.engine.app.alerts.energy_margin_mj
            record.true_diff_mj = diff
            if "energy" not in (alert.evidence.branch or "energy"):
                margin = 0.0  # observed clip / own battery: only the sign is claimed
            if alert.type == "ATTACK":
                record.correct = diff <= -margin
            elif alert.type == "DEFEND":
                record.correct = diff >= margin
        self._records[alert.alert_id] = record
        self.calls.append(record)

    def _judge(self, view: EngineerView) -> None:
        """Score each alert ``OUTCOME_LAPS`` of Our Car after it fired."""
        finished = self.engine.finished
        for record in self.calls:
            if record.outcome is not None:
                continue
            if view.our_car.lap < record.our_lap + OUTCOME_LAPS and not finished:
                continue
            ahead = _ahead(view, self.setup.our_driver_id, record.alert.rival)
            if not record.our_ahead:
                record.outcome = "pass made" if ahead else "no pass"
            elif ahead:
                record.outcome = "position kept"
            else:
                record.outcome = (
                    "re-passed" if record.alert.type == "REPASS_RISK" else "position lost"
                )

    def summary(self) -> CallSummary:
        """Return the call summary so far (complete after the flag)."""
        with self._lock:
            records = list(self.calls)
            judged = [r for r in records if r.correct is not None]
            return CallSummary(
                records=records,
                alerts=len(records),
                calls_made=sum(r.answered for r in records),
                successful_attacks=sum(
                    r.alert.type == "ATTACK" and r.answered and r.outcome == "pass made"
                    for r in records
                ),
                successful_defends=sum(
                    r.alert.type == "DEFEND" and r.answered and r.outcome == "position kept"
                    for r in records
                ),
                correct=sum(bool(r.correct) for r in judged) if self.setup.test_mode else None,
                judged=len(judged) if self.setup.test_mode else None,
            )

    def _issue(self, kind: CommandType, params: dict[str, Any]) -> str | None:
        engine = self.engine
        cmd = make_command(
            kind, params, engine.command_context(), engine.app.engineer, engine.t,
            engine.app.radio.radio_latency_s,
        )  # fmt: skip
        if not isinstance(cmd, EngineerCommand):
            return cmd.reason
        engine.submit(cmd)
        self._issued.append(cmd.command_id)
        return None

    def _track_status_radio(self, old: str, new: str) -> None:
        """Say the driver's Safety Car / VSC call (template, H4)."""
        line = TRACK_STATUS_LINES.get(new if new != "GREEN" else f"GREEN_FROM_{old}")
        if line:
            self._say("DRIVER", line)

    def _snapshot_now(self) -> str:
        """Snapshot the race now (shared by every call made at this moment)."""
        snapshot_id = f"snap-{self.engine.steps}"
        if snapshot_id not in self.snapshots:
            self.snapshots[snapshot_id] = self.engine.snapshot()
        return snapshot_id

    def _log_call(self, alert_id: str | None, command_ids: tuple[str, ...], label: str,
                  snapshot_id: str, spec: CallSpec) -> None:  # fmt: skip
        lap = max(1, int(self.engine.st.lap[self._builder.our_index]) + 1)
        record = CallRecord(self.engine.t, lap, alert_id, command_ids, label, snapshot_id)
        self.call_log.append(record)
        self.call_specs.append(spec)
        alert = self._records.get(alert_id) if alert_id else None
        rival = alert.alert.rival if alert is not None else None
        self._reveal.on_call(record, rival, self._view, self._truth_mj())

    def _truth_mj(self) -> dict[str, float]:
        """Every car's TRUE battery: for the Reveal recorder only (released after the flag)."""
        return {d: float(self.engine.st.battery_j[i]) / MJ
                for i, d in enumerate(self.engine.driver_ids)}  # fmt: skip

    def _strategy_upkeep(self, view: EngineerView) -> None:
        """Strategy panel (H5): a refresh at each of Our Car's laps; results into the view."""
        worker = self._strategy
        if worker is None:
            return
        if worker.poll():
            self._builder.strategy = worker.result
            self.strategy_lap = worker.result_lap
        lap = view.our_car.lap + 1
        if lap != self._strategy_lap and lap >= 1 and not self.engine.finished:
            if self.refresh_strategy():
                self._strategy_lap = lap

    def refresh_strategy(self) -> bool:
        """Start a strategy refresh now (unless one is running); return whether it started.

        The worker gets a snapshot and the public data only; it replaces every Rival's
        hidden state before any fork (``strategy.public_snapshot``, HR-03).
        """
        worker = self._strategy
        if worker is None or worker.busy or self.engine.finished:
            return False
        view = self._view
        return worker.submit(self.engine.snapshot(), self.setup.our_driver_id,
                             PublicInfo.from_view(view), plans_for(self.engine),
                             view.our_car.lap + 1)  # fmt: skip

    @property
    def strategy_busy(self) -> bool:
        """A strategy refresh is running."""
        return self._strategy is not None and self._strategy.busy

    def close(self) -> None:
        """Stop background work (the strategy processes)."""
        if self._strategy is not None:
            self._strategy.close()
        self.radio_ai.close()

    def compute_cost(self, index: int) -> str:
        """Decision cost of call ``index`` (H1): forks from its snapshot; after the flag only.

        Slow (seconds): the UI calls it from a worker thread. Cached by snapshot in
        ``paths.cost_cache``. The text is also stored in the Reveal.
        """
        if not self.engine.finished:
            raise RuntimeError("decision costs are computed after the flag")
        record = self.call_log[index]
        cache = Path(self.engine.app.paths.cost_cache)
        if not cache.is_absolute():
            cache = self.config_dir.resolve().parent / cache
        cost = call_cost(record, index, self.call_specs[index], self.snapshots[record.snapshot_id],
                         self.setup.our_driver_id, cache)  # fmt: skip
        text = describe(cost)
        with self._lock:
            self.costs[index] = cost
            self._reveal.calls[index].cost = text
        return text

    def reveal(self) -> RevealData | None:
        """Return the post-race Reveal (H1): None until the chequered flag (HR-03)."""
        with self._lock:
            if not self.engine.finished:
                return None
            return self._reveal.reveal()

    def _say(self, sender: Literal["ENGINEER", "DRIVER", "SYSTEM"], text: str,
             rejected: bool = False, source: RadioSource = "TEMPLATE",
             command_ids: tuple[str, ...] = (), is_fallback: bool = False) -> None:  # fmt: skip
        self.radio.append(RadioLine(self.engine.t, sender, text, rejected))
        if sender != "SYSTEM":  # the view's radio log: engineer and driver only
            self._builder.radio_log.append(
                RadioEvent(self.engine.t, sender, text, source, command_ids, is_fallback)
            )

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def frame(self) -> Frame:
        """Snapshot what the pit wall shows now."""
        with self._lock:
            e = self.engine
            truth = None
            if self.setup.test_mode:  # Test mode only: the Rivals' TRUE battery
                truth = {d: float(e.st.battery_j[i]) / MJ for i, d in enumerate(e.driver_ids)
                         if d != self.setup.our_driver_id}  # fmt: skip
            return Frame(
                view=self._view, alerts=list(self._alerts),
                options={a.alert_id: self._options[a.alert_id] for a in self._alerts},
                radio=list(self.radio), truth_mj=truth,
                paused_on_alert=self.paused_on_alert, finished=e.finished,
                lap=int(e.st.lap.max()) + 1, laps=e.laps,
            )  # fmt: skip

    def headline(self, alert: Alert) -> str:
        """Return the alert's one-line text."""
        return alert_line(alert)


def _ahead(view: EngineerView, a: str, b: str) -> bool:
    """Return whether ``a`` is ahead of ``b`` in the public order."""
    order = view.timing.order
    return a in order and b in order and order.index(a) < order.index(b)

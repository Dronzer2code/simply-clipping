"""Ask the pit wall (Graphify track step 3): questions about a finished race.

Preset questions are answered from the race record itself (exact, instant, no
graphify needed); any other question goes to ``graphify query`` on the race graph
(``graph.json``) when the graphify CLI is installed (:func:`graphify_available`).
Nothing here runs before the flag: it only reads a finished race's record / graph.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pitwall_sim.graph.race_graph import cost_label, rival_stats
from pitwall_sim.graph.record import RaceRecord

GRAPHIFY_TIMEOUT_S = 30.0
GRAPHIFY_BUDGET = 900
"""Token budget of a ``graphify query`` answer (keeps it short enough to read)."""
RACED_MOST = "Who did I race most?"
WRONG_ALERTS = "Which alerts were wrong?"


def calls_question(code: str) -> str:
    """Return the preset question about the calls against one Rival."""
    return f"What did my calls against {code} cost?"


def preset_questions(record: RaceRecord) -> list[str]:
    """Return the presets: who we raced, wrong alerts, calls against the most-raced Rival."""
    out = [RACED_MOST, WRONG_ALERTS]
    top = _raced(record)
    if top:
        out.append(calls_question(record.cars[top[0]].code))
    return out


def _raced(record: RaceRecord) -> list[str]:
    stats = rival_stats(record)
    return sorted((d for d in stats if stats[d]["time_within_1s_s"] > 0),
                  key=lambda d: -stats[d]["time_within_1s_s"])  # fmt: skip


def answer(record: RaceRecord, question: str) -> str | None:
    """Answer a preset question from the record; None if it is not one."""
    q = question.strip()
    code = {info.code: d for d, info in record.cars.items()}
    stats = rival_stats(record)
    if q == RACED_MOST:
        top = _raced(record)
        if not top:
            return "You never ran within 1 s of another car."
        lines = ["Rivals you raced most (time within 1 s):"]
        for d in top[:5]:
            s = stats[d]
            lines.append(f"- {record.cars[d].code}: {s['time_within_1s_s']:.0f} s in "
                         f"{s['battles']} battle(s); passes {s['passes_made']} made / "
                         f"{s['passes_lost']} lost")  # fmt: skip
        return "\n".join(lines)
    if q == WRONG_ALERTS:
        judged = [a for a in record.alerts if a.truth.right is not None]
        wrong = [a for a in judged if not a.truth.right]
        if not judged:
            return "No ATTACK / DEFEND alert to check against the truth."
        lines = [f"{len(wrong)} of {len(judged)} checked alerts were wrong:"]
        for a in wrong:
            lines.append(
                f"- Lap {a.lap} {a.type} on {record.cars[a.rival].code} ({a.branch or '-'}): "
                f"estimate {_mj(a.truth.estimate_mj)}, true {_mj(a.truth.rival_true_mj)}, "
                f"yours {_mj(a.truth.our_mj)}; you chose {a.option}"
            )
        return "\n".join(lines)
    for c, d in code.items():
        if q == calls_question(c):
            calls = [x for x in record.calls if x.rival == d]
            if not calls:
                return f"You made no calls about {c}."
            lines = [f"Your calls about {c}:"]
            total = 0.0
            for x in calls:
                cost = "cost not computed"
                if x.cost is not None:
                    cost = cost_label(x.cost.delta_s, x.cost.best_option)
                    total += x.cost.delta_s
                lines.append(f"- Lap {x.lap}: {x.label} -> {x.outcome or '-'}; {cost}")
            lines.append(f"Total: {total:+.1f} s against the best options.")
            return "\n".join(lines)
    return None


def _mj(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f} MJ"


def graphify_available() -> bool:
    """Return whether the graphify CLI is on the PATH."""
    return shutil.which("graphify") is not None


def graphify_query(graph_json: Path, question: str) -> str:
    """Run ``graphify query`` on a race graph; return its text (or why it failed)."""
    exe = shutil.which("graphify")
    if exe is None:
        return "graphify is not installed (pip install graphifyy), so free questions are off."
    try:
        done = subprocess.run(
            [exe, "query", question, "--graph", str(graph_json), "--budget", str(GRAPHIFY_BUDGET)],
            capture_output=True, text=True, timeout=GRAPHIFY_TIMEOUT_S, check=False,
            encoding="utf-8", errors="replace",
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"graphify query failed: {exc}"
    text = (done.stdout or "").strip() or (done.stderr or "").strip()
    if done.returncode == 4:
        return "Nothing in the race graph matches that. Try a driver code (e.g. OCO) or ATTACK."
    return text or f"graphify query returned nothing (exit {done.returncode})."


def ask(record: RaceRecord, graph_json: Path, question: str) -> str:
    """Answer ``question``: a preset from the record, anything else via graphify."""
    return answer(record, question) or graphify_query(graph_json, question)

"""LLM-written driver radio lines, checked against the facts (hackathon H3).

The driver's unprompted lines (``live/driver_radio``) are templates with the facts
filled in. With a hosted LLM on, the template and Our Car's own data (never a
Rival's hidden state, HR-03) go to the model, which writes the line in the
driver's voice. The answer is used only if it passes :func:`fact_check`:

- at most ``max_words`` words (owner: 20), one line;
- every number in it (digits or number words, ``P4``, ``74%``) is a number in the facts;
- a tyre compound it names is Our Car's compound;
- a place gained is not called a place lost, and the other way round.

Anything else (failure, timeout, a wrong number, too long): the template stands.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from pitwall_sim.engineer.radio_parser import COMPOUNDS, NUMBER_WORDS
from pitwall_sim.observe.engineer_view import EngineerView
from pitwall_sim.radio.hosted_llm import LLMProvider, call_with_timeout

logger = logging.getLogger(__name__)
MAX_WORDS = 20
NUMBER = re.compile(r"\d+(?:\.\d+)?")
SYSTEM = (
    "You are the Formula 1 driver of Our Car speaking on team radio to your race engineer. "
    "Rewrite the message in your own words as ONE short radio line of at most {words} words. "
    "Use only the facts given; do not add any number, tyre or place that is not in them. "
    "Reply with the line only, no quotes."
)
GAINED = re.compile(r"\b(lost|losing|down)\b")
LOST = re.compile(r"\b(gained|gaining|up)\b")


def _value(x: object) -> str:
    return str(getattr(x, "value", x))


def reply_facts(view: EngineerView, our: str, race_laps: int, message: str) -> dict[str, str]:
    """Facts for a driver line: Our Car's data and public timing only (HR-03)."""
    car = view.our_car
    order = view.timing.order
    facts = {
        "message": message,
        "lap": str(car.lap + 1),
        "race_laps": str(race_laps),
        "battery_mj": f"{car.battery_mj:.1f}",
        "tyre_wear_pct": f"{car.tyre_wear * 100:.0f}",
        "tyre_age_laps": str(car.tyre_age_laps),
        "compound": _value(car.compound),
        "energy_mode": _value(car.energy_mode),
    }
    if our in order:
        facts["position"] = f"P{order.index(our) + 1}"
    return facts


def _numbers(text: str) -> set[float]:
    text = text.lower()
    out = {float(n) for n in NUMBER.findall(text)}
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            out.add(float(n))
    return out


def fact_check(reply: str, facts: Mapping[str, str], max_words: int = MAX_WORDS) -> str | None:
    """Return why ``reply`` fails the facts, or None if it may be said."""
    if not reply or "\n" in reply:
        return "empty or more than one line"
    if len(reply.split()) > max_words:
        return f"more than {max_words} words"
    allowed = set().union(*(_numbers(v) for v in facts.values()))
    wrong = sorted(_numbers(reply) - allowed)
    if wrong:
        return f"number(s) not in the facts: {', '.join(f'{n:g}' for n in wrong)}"
    said = {c for w, c in COMPOUNDS.items() if re.search(rf"\b{w}\b", reply.lower())}
    compound = facts.get("compound", "")
    if said - {compound}:
        return f"tyre {', '.join(sorted(said))} is not {compound}"
    message = facts.get("message", "")
    if message.startswith("Up to") and GAINED.search(reply.lower()):
        return "a place gained called a place lost"
    if message.startswith("Down to") and LOST.search(reply.lower()):
        return "a place lost called a place gained"
    return None


def _clean(text: str) -> str:
    text = text.strip().strip('"').strip("'").strip()
    return re.sub(r"[ \t]+", " ", text)


def write_reply(provider: LLMProvider, facts: Mapping[str, str], timeout_s: float,
                max_words: int = MAX_WORDS) -> str | None:  # fmt: skip
    """Return the LLM's line if it passes :func:`fact_check`, else None (template)."""
    user = "\n".join(f"{k}: {v}" for k, v in facts.items())
    system = SYSTEM.format(words=max_words)
    try:
        reply = call_with_timeout(lambda: provider.complete(system, user, (), timeout_s),
                                  timeout_s)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 (any failure -> template)
        logger.info("driver reply LLM failed (%s): template", type(exc).__name__)
        return None
    text = _clean(reply.text)
    problem = fact_check(text, facts, max_words)
    if problem is not None:
        logger.info("driver reply rejected (%s): template", problem)
        return None
    return text

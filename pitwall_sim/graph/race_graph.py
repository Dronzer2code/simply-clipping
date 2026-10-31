"""Race comparison graph (Graphify track): Our Car against every Rival.

:func:`build_graph` turns a :class:`RaceRecord` into graphify's ``graph.json``
schema (``schema_version`` 1; nodes ``id / label / file_type / source_file /
source_location / community / community_name``; links ``source / target / relation /
confidence / confidence_score / weight``), so ``graphify query / path / explain
--graph <folder>/graph.json`` work on it. :func:`write_race_graph` also writes the
graphify labels file, our own offline ``graph.html`` viewer (graphify's viewer loads
its library from the internet and drops our per-Rival stats; spike, step 0) and a
short factual ``race_report.md``.

Nodes: Car (all 22, Our Car marked), Battle, Alert, Call, Outcome, Incident,
CallCost, TruthCheck. Facts read from the race are EXTRACTED; a call leading to its
outcome is INFERRED, with a confidence from the paired-fork decision cost.

Communities are battle groups: cars joined by their longest battles (union of the
heaviest pairs first, at most ``MAX_GROUP`` cars, battles of at least
``MIN_GROUP_BATTLE_S``), each named after its cars, e.g. "GAS-OCO-ALB battle".
"""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pitwall_sim.graph.record import RaceRecord
from pitwall_sim.live.costs import BEST_TIE_S

SCHEMA_VERSION = 1
GRAPHIFY_VERSION = "0.9.96"
"""The graphify release whose graph.json schema this follows (spike, step 0)."""
MAX_GROUP = 5
MIN_GROUP_BATTLE_S = 5.0
SOLO = "no close battles"
RACE_CONTROL = "Race control"
PIT_LAP_FACTOR = 1.15
"""Lap times over this x the car's median (pit stops, Safety Car) are left out of deltas."""
HERE = Path(__file__).parent
VENDOR = HERE / "vendor"
TEMPLATES = HERE / "templates"
PALETTE = ("#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1",
           "#FF9DA7", "#9C755F", "#BAB0AC")  # fmt: skip


@dataclass(frozen=True)
class Group:
    """One battle group (a graph community)."""

    cid: int
    name: str
    cars: tuple[str, ...]
    battle_s: float


@dataclass(frozen=True)
class RaceGraphPaths:
    """What :func:`write_race_graph` wrote."""

    folder: Path
    graph_json: Path
    graph_html: Path
    report: Path
    record: Path
    dashboard: Path | None = None


# ---------------------------------------------------------------------- #
# Battle groups and per-Rival stats
# ---------------------------------------------------------------------- #


def pair_battle_s(record: RaceRecord) -> dict[tuple[str, str], float]:
    """Total seconds within the battle gap, per pair of cars (sorted)."""
    out: dict[tuple[str, str], float] = {}
    for b in record.battles:
        out[b.cars] = out.get(b.cars, 0.0) + b.duration_s
    return out


def battle_groups(record: RaceRecord) -> tuple[list[Group], dict[str, int]]:
    """Group the cars by their battles; return the groups and car -> group id.

    Group 0 is Our Car's; the cars that never battled long enough share the
    ``SOLO`` group (last).
    """
    pairs = pair_battle_s(record)
    parent = {d: d for d in record.cars}

    def root(d: str) -> str:
        while parent[d] != d:
            parent[d] = parent[parent[d]]
            d = parent[d]
        return d

    size = dict.fromkeys(record.cars, 1)
    for (a, b), secs in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):
        if secs < MIN_GROUP_BATTLE_S or a not in parent or b not in parent:
            continue
        ra, rb = root(a), root(b)
        if ra != rb and size[ra] + size[rb] <= MAX_GROUP:
            parent[rb] = ra
            size[ra] += size[rb]
    members: dict[str, list[str]] = {}
    for d in record.cars:
        members.setdefault(root(d), []).append(d)
    seconds: dict[str, float] = {}
    for (a, b), secs in pairs.items():
        for d in (a, b):
            seconds[d] = seconds.get(d, 0.0) + secs
    groups, solo = [], []
    for cars in members.values():
        if len(cars) == 1:
            solo.extend(cars)
            continue
        inside = sum(s for (a, b), s in pairs.items() if a in cars and b in cars)
        groups.append((cars, inside))
    groups.sort(key=lambda g: (record.our not in g[0], -g[1], sorted(g[0])))
    out, of = [], {}
    for cid, (cars, inside) in enumerate(groups):
        ranked = sorted(cars, key=lambda d: (d != record.our, -seconds[d], d))
        codes = [record.cars[d].code for d in ranked]
        name = "-".join(codes[:3]) + (f" +{len(codes) - 3}" if len(codes) > 3 else "") + " battle"
        out.append(Group(cid, name, tuple(ranked), inside))
        for d in cars:
            of[d] = cid
    if solo:
        cid = len(out)
        out.append(Group(cid, SOLO, tuple(sorted(solo)), 0.0))
        for d in solo:
            of[d] = cid
    return out, of


def _lap_delta_s(ours: list[float], theirs: list[float]) -> float | None:
    """Mean lap-time difference (theirs - ours) over common laps, lap 1 and slow laps out."""
    n = min(len(ours), len(theirs))
    if n < 2:
        return None
    a, b = np.array(ours[:n]), np.array(theirs[:n])
    ok = np.ones(n, dtype=bool)
    ok[0] = False
    for x in (a, b):
        ok &= x <= PIT_LAP_FACTOR * float(np.median(x[1:]))
    return float((b - a)[ok].mean()) if ok.any() else None


def rival_stats(record: RaceRecord) -> dict[str, dict[str, Any]]:
    """Per Rival, against Our Car: what the Car node carries (and the dashboard shows)."""
    our = record.our
    pairs = pair_battle_s(record)
    out: dict[str, dict[str, Any]] = {}
    for d in record.cars:
        if d == our:
            continue
        lo, hi = sorted((our, d))
        key = (lo, hi)
        alerts = [a for a in record.alerts if a.rival == d]
        judged = [a for a in alerts if a.truth.right is not None]
        calls = [c for c in record.calls if c.rival == d]
        costed = [c.cost.delta_s for c in calls if c.cost is not None]
        radar = record.radar.get(d)
        out[d] = {
            "time_within_1s_s": round(pairs.get(key, 0.0), 1),
            "battles": sum(b.cars == key for b in record.battles),
            "passes_made": sum(p.passer == our and p.passed == d for p in record.passes),
            "passes_lost": sum(p.passer == d and p.passed == our for p in record.passes),
            "alerts": dict(Counter(a.type for a in alerts)),
            "alerts_judged": len(judged),
            "alerts_right": sum(bool(a.truth.right) for a in judged),
            "alerts_right_pct": (
                round(100.0 * sum(bool(a.truth.right) for a in judged) / len(judged), 1)
                if judged
                else None
            ),  # fmt: skip
            "est_minus_true_mj": _round(radar.bias_mj if radar else None, 2),
            "radar_mae_mj": _round(radar.mae_mj if radar else None, 2),
            "calls": len(calls),
            "call_cost_s": round(sum(costed), 2) if costed else None,
            "max_closing_kmh": _round(record.max_closing_kmh.get(d), 1),
            "lap_delta_s": _round(
                _lap_delta_s(record.lap_times_s.get(our, []), record.lap_times_s.get(d, [])), 3
            ),  # fmt: skip
        }
    return out


def _round(x: float | None, digits: int) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), digits)


def race_totals(record: RaceRecord) -> dict[str, Any]:
    """Return the dashboard's top tiles (also Our Car's node stats)."""
    our = record.our
    costed = [c.cost.delta_s for c in record.calls if c.cost is not None]
    judged = [a for a in record.alerts if a.truth.right is not None]
    return {
        "alerts": len(record.alerts),
        "calls_made": len(record.calls),
        "calls_costed": len(costed),
        "passes_made": sum(p.passer == our for p in record.passes),
        "passes_lost": sum(p.passed == our for p in record.passes),
        "total_call_cost_s": round(sum(costed), 2) if costed else None,
        "radar_mae_mj": _round(record.radar_mae_mj, 2),
        "alerts_judged": len(judged),
        "alerts_right": sum(bool(a.truth.right) for a in judged),
        "finish_position": record.cars[our].finish_position,
    }


def led_to_confidence(delta_s: float | None) -> float:
    """How sure "this call led to that outcome" is, from the decision cost.

    The forks replay the call and its alternatives: when every option ends within a
    whisker of the others, the call barely shaped what followed (0.5); the bigger the
    gap to the best option, the more it did (towards 0.95).
    """
    if delta_s is None:
        return 0.5
    return round(0.5 + 0.45 * (1.0 - math.exp(-abs(delta_s) / 2.0)), 3)


# ---------------------------------------------------------------------- #
# The graph
# ---------------------------------------------------------------------- #


def cost_label(delta_s: float, best: str) -> str:
    """Return the CallCost node's label (the Reveal's wording)."""
    return "best call" if delta_s <= BEST_TIE_S else f"+{delta_s:.1f} s vs best ({best})"


def build_graph(record: RaceRecord) -> dict[str, Any]:
    """Return the race as a graphify ``graph.json`` dictionary."""
    groups, group_of = battle_groups(record)
    names = {g.cid: g.name for g in groups}
    control = len(groups)
    names[control] = RACE_CONTROL
    stats = rival_stats(record)
    pairs = pair_battle_s(record)
    our = record.our
    src = f"race/{record.run_id}"
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    labels_used: Counter[str] = Counter()

    def code(d: str) -> str:
        return record.cars[d].code if d in record.cars else d

    def add_node(nid: str, label: str, kind: str, cid: int, where: str, **extra: Any) -> None:
        labels_used[label] += 1
        if labels_used[label] > 1:
            label = f"{label} #{labels_used[label]}"
        nodes.append({"id": nid, "label": label, "file_type": kind, "source_file": src,
                      "source_location": where, "community": cid,
                      "community_name": names[cid], **extra})  # fmt: skip

    def add_link(a: str, b: str, rel: str, weight: float = 1.0, inferred: float | None = None,
                 **extra: Any) -> None:  # fmt: skip
        links.append({"source": a, "target": b, "relation": rel,
                      "confidence": "INFERRED" if inferred is not None else "EXTRACTED",
                      "confidence_score": inferred if inferred is not None else 1.0,
                      "source_file": src, "weight": round(float(weight), 3), **extra})  # fmt: skip

    def car_id(d: str) -> str:
        return f"car:{d}"

    def cid_of(d: str | None) -> int:
        return group_of.get(d, group_of.get(our, 0)) if d else group_of.get(our, 0)

    totals = race_totals(record)
    for d, info in record.cars.items():
        extra: dict[str, Any] = {"team": info.team, "color": info.color,
                                 "finish_position": info.finish_position,
                                 "status": info.status, "our_car": d == our}  # fmt: skip
        extra["stats"] = totals if d == our else stats[d]
        where = f"P{info.finish_position}" if info.finish_position else info.status
        add_node(car_id(d), info.code, "car", group_of.get(d, 0), where, **extra)
    for (x, y), secs in sorted(pairs.items()):
        if x in record.cars and y in record.cars:
            add_link(car_id(x), car_id(y), "battled", secs, seconds=round(secs, 1))
    passed = Counter((p.passer, p.passed) for p in record.passes)
    for (x, y), n in sorted(passed.items()):
        if x in record.cars and y in record.cars:
            add_link(car_id(x), car_id(y), "passed", n, count=n)
    battle_ids = []
    for k, b in enumerate(record.battles):
        bid = f"battle:{k}"
        battle_ids.append(bid)
        cid = group_of.get(b.ahead, 0) if group_of.get(b.ahead) == group_of.get(b.behind) else (
            cid_of(b.behind if b.ahead == our else b.ahead))  # fmt: skip
        laps = f"L{b.start_lap}" + (f"-{b.end_lap}" if b.end_lap != b.start_lap else "")
        add_node(bid, f"{code(b.ahead)}-{code(b.behind)} battle {laps} ({b.duration_s:.0f} s)",
                 "battle", cid, laps, ahead=b.ahead, behind=b.behind, start_t_s=b.start_t_s,
                 end_t_s=b.end_t_s, duration_s=b.duration_s, our_battle=our in b.cars)  # fmt: skip
        for d in (b.ahead, b.behind):
            add_link(car_id(d), bid, "in_battle", b.duration_s)

    def battle_at(cars: tuple[str, ...], t: float) -> list[str]:
        """Battles going on at ``t`` (between ``cars`` if two are given; any if none)."""
        hits = []
        for bid, b in zip(battle_ids, record.battles, strict=True):
            if b.start_t_s - 1.0 <= t <= b.end_t_s + 1.0 and (not cars or set(cars) <= set(b.cars)):
                hits.append(bid)
        return hits

    outcome_ids: dict[str, str] = {}
    for a in record.alerts:
        aid = f"alert:{a.alert_id}"
        cid = cid_of(a.rival)
        branch = f" ({a.branch})" if a.branch else ""
        add_node(aid, f"{a.type.replace('_', ' ')} {code(a.rival)} L{a.lap}{branch}", "alert",
                 cid, f"L{a.lap}", alert_type=a.type, branch=a.branch,
                 confidence=round(a.confidence, 3), t_s=round(a.t_s, 2), option=a.option,
                 our_mj=_round(a.our_mj, 2), rival_est_mj=_round(a.rival_est_mj, 2),
                 dv_kmh=_round(a.dv_kmh, 1), gap_s=_round(a.gap_s, 2))  # fmt: skip
        add_link(aid, car_id(a.rival), "about")
        for bid in battle_at((our, a.rival), a.t_s):
            add_link(aid, bid, "during")
        tc = a.truth
        verdict = {True: "RIGHT", False: "WRONG", None: "not judged"}[tc.right]
        true_txt = "-" if tc.rival_true_mj is None else f"{tc.rival_true_mj:.1f}"
        est_txt = "-" if tc.estimate_mj is None else f"{tc.estimate_mj:.1f}"
        tid = f"truth:{a.alert_id}"
        add_node(tid, f"Truth {code(a.rival)} L{a.lap}: true {true_txt} MJ, est {est_txt} -> "
                 f"{verdict}", "truthcheck", cid, f"L{a.lap}",
                 rival_true_mj=_round(tc.rival_true_mj, 2), estimate_mj=_round(tc.estimate_mj, 2),
                 error_mj=_round(tc.error_mj, 2), our_mj=_round(tc.our_mj, 2),
                 right=tc.right)  # fmt: skip
        add_link(aid, tid, "checked_by")
        if a.outcome:
            oid = f"outcome:alert:{a.alert_id}"
            outcome_ids[a.alert_id] = oid
            add_node(oid, f"{a.outcome} ({code(a.rival)}) L{a.lap}", "outcome", cid,
                     f"L{a.lap}", outcome=a.outcome)  # fmt: skip
            add_link(aid, oid, "followed_by")
    for c in record.calls:
        cid_ = f"call:{c.index}"
        cid = cid_of(c.rival)
        if c.kind == "radio" and c.radio_text:
            label = f'Radio L{c.lap}: "{c.radio_text}"'
        elif c.kind == "alert option":
            label = f"Call L{c.lap}: {c.label}"
        else:
            label = f"Button L{c.lap}: {c.label}"
        add_node(cid_, label, "call", cid, f"L{c.lap}", call_kind=c.kind, option=c.label,
                 t_s=round(c.t_s, 2), rival=c.rival, position_before=c.position_before,
                 position_after=c.position_after, estimate_mj=_round(c.estimate_mj, 2),
                 truth_mj=_round(c.truth_mj, 2))  # fmt: skip
        if c.alert_id and f"alert:{c.alert_id}" in {n["id"] for n in nodes}:
            add_link(cid_, f"alert:{c.alert_id}", "answers")
        elif c.rival:
            add_link(cid_, car_id(c.rival), "about")
        delta = c.cost.delta_s if c.cost else None
        out_id: str | None = None
        if c.alert_id and c.alert_id in outcome_ids:
            out_id = outcome_ids[c.alert_id]
        elif c.outcome:
            out_id = f"outcome:call:{c.index}"
            add_node(out_id, f"{c.outcome} L{c.lap}", "outcome", cid, f"L{c.lap}",
                     outcome=c.outcome)  # fmt: skip
        if out_id:
            add_link(cid_, out_id, "led_to", inferred=led_to_confidence(delta))
        if c.cost is not None:
            kid = f"cost:{c.index}"
            add_node(kid, f"{cost_label(c.cost.delta_s, c.cost.best_option)} L{c.lap}",
                     "callcost", cid, f"L{c.lap}", delta_s=round(c.cost.delta_s, 2),
                     best_option=c.cost.best_option, your_s=round(c.cost.your_s, 2),
                     best_s=round(c.cost.best_s, 2), n_seeds=c.cost.n_seeds)  # fmt: skip
            add_link(cid_, kid, "cost", abs(c.cost.delta_s))
    for k, inc in enumerate(record.incidents):
        iid = f"incident:{k}"
        if inc.kind == "PASS":
            label = f"Pass: {code(inc.cars[0])} on {code(inc.cars[1])} L{inc.lap}"
        elif inc.kind == "CLOSING_SPEED":
            pair = f"{code(inc.cars[0])}-{code(inc.cars[1])}"
            label = f"Closing {inc.value or 0:.0f} km/h {pair} L{inc.lap}"
        else:
            label = f"{'Safety Car' if inc.kind == 'SC' else 'VSC'} L{inc.lap}"
        rival = next((d for d in inc.cars if d != our), None)
        cid = control if inc.kind in ("SC", "VSC") else cid_of(rival)
        add_node(iid, label, "incident", cid, f"L{inc.lap}", incident=inc.kind,
                 t_s=round(inc.t_s, 2), end_t_s=round(inc.end_t_s, 2), detail=inc.detail,
                 value=_round(inc.value, 1))  # fmt: skip
        for d in inc.cars:
            add_link(iid, car_id(d), "involves")
        for bid in battle_at(tuple(inc.cars), inc.t_s):
            add_link(iid, bid, "during")
    used = {n["community"] for n in nodes}
    return {
        "directed": True, "multigraph": False,
        "graph": {"schema_version": SCHEMA_VERSION, "graphify_version": GRAPHIFY_VERSION,
                  "race": {"run_id": record.run_id, "source": record.source,
                           "track_id": record.track_id, "seed": record.seed,
                           "laps": record.laps, "rule_set_id": record.rule_set_id,
                           "our": our, "test_mode": record.test_mode},
                  "communities": {str(c): names[c] for c in sorted(used)}},
        "nodes": nodes, "links": links, "hyperedges": [],
    }  # fmt: skip


def labels(graph: dict[str, Any]) -> dict[str, str]:
    """Community id -> name, in graphify's labels-file format (``--labels``)."""
    return dict(graph["graph"]["communities"])


# ---------------------------------------------------------------------- #
# Files
# ---------------------------------------------------------------------- #


def fill_page(template: str, title: str, data: dict[str, Any]) -> str:
    """Fill a page template (data as JSON, safe inside a script tag)."""
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return text.replace("__TITLE__", title).replace("/*__DATA__*/null", blob)


def palette(cid: int) -> str:
    """Return a community's colour."""
    return PALETTE[cid % len(PALETTE)]


def write_race_graph(record: RaceRecord, out: Path) -> RaceGraphPaths:
    """Write graph.json / .html, labels.json, dashboard.html, race_report.md, race_record.json."""
    out.mkdir(parents=True, exist_ok=True)
    lib = out / "lib"
    lib.mkdir(exist_ok=True)
    for name in ("vis-network.min.js", "d3.min.js"):
        shutil.copyfile(VENDOR / name, lib / name)
    graph = build_graph(record)
    graph_json = out / "graph.json"
    graph_json.write_text(json.dumps(graph, indent=1), encoding="utf-8")
    (out / "labels.json").write_text(json.dumps(labels(graph), indent=1), encoding="utf-8")
    record_path = out / "race_record.json"
    record.save(record_path)
    our = record.cars[record.our].code
    title = f"Race graph - {our} - {record.track_id} seed {record.seed}"
    html = out / "graph.html"
    colours = {int(c): palette(int(c)) for c in graph["graph"]["communities"]}
    html.write_text(fill_page("graph.html", title, {"graph": graph, "colours": colours}),
                    encoding="utf-8")  # fmt: skip
    report = out / "race_report.md"
    report.write_text(race_report(record), encoding="utf-8")
    from pitwall_sim.graph.dashboard import write_dashboard  # noqa: PLC0415 (it imports us)

    board = write_dashboard(record, out)
    return RaceGraphPaths(out, graph_json, html, report, record_path, board)


def race_report(record: RaceRecord) -> str:
    """Write a short, factual report of the race graph (rivals fought most, groups, checks)."""
    our = record.our
    c = record.cars
    totals = race_totals(record)
    stats = rival_stats(record)
    groups, _ = battle_groups(record)

    def code(d: str | None) -> str:
        return c[d].code if d and d in c else (d or "-")

    def fmt(x: float | None, spec: str = ".2f", unit: str = "") -> str:
        return "-" if x is None else f"{x:{spec}}{unit}"

    lines = [
        f"# Race report: {code(our)}, {record.track_id}, seed {record.seed}, {record.laps} laps",
        "",
        f"Source: {record.source} race `{record.run_id}`, rule set `{record.rule_set_id}`."
        + (" Test mode was on." if record.test_mode else ""),
        "Built after the chequered flag: the Rivals' true batteries are shown here.",
        "",
        "## Totals",
        "",
        "| Finish | Alerts | Calls made | Passes made / lost | Total call cost | Radar MAE |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| P{fmt(totals['finish_position'], 'd')} | {totals['alerts']} | "
        f"{totals['calls_made']} | {totals['passes_made']} / {totals['passes_lost']} | "
        f"{fmt(totals['total_call_cost_s'], '+.1f', ' s')} | "
        f"{fmt(totals['radar_mae_mj'], '.2f', ' MJ')} |",
        "",
        "## Rivals fought most (the graph's god nodes)",
        "",
        "| Rival | Within 1 s | Battles | Passes made / lost | Alerts | Alerts right "
        "| Radar MAE | Est - true | Call cost | Max closing | Lap delta |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    fought = sorted((d for d in stats if stats[d]["time_within_1s_s"] > 0),
                    key=lambda d: -stats[d]["time_within_1s_s"])  # fmt: skip
    for d in fought[:8]:
        s = stats[d]
        right = f"{s['alerts_right']}/{s['alerts_judged']}" if s["alerts_judged"] else "-"
        lines.append(
            f"| {code(d)} | {s['time_within_1s_s']:.0f} s | {s['battles']} | "
            f"{s['passes_made']} / {s['passes_lost']} | {sum(s['alerts'].values())} | {right} | "
            f"{fmt(s['radar_mae_mj'], '.2f', ' MJ')} | "
            f"{fmt(s['est_minus_true_mj'], '+.2f', ' MJ')} | "
            f"{fmt(s['call_cost_s'], '+.1f', ' s')} | "
            f"{fmt(s['max_closing_kmh'], '.0f', ' km/h')} | {fmt(s['lap_delta_s'], '+.2f', ' s')} |"
        )
    if not fought:
        lines.append("| (none: Our Car never ran within 1 s of another car) | | | | | | | | | | |")
    lines += ["", "## Battle groups (communities)", ""]
    for g in groups:
        cars = ", ".join(code(d) for d in g.cars)
        lines.append(f"- **{g.name}**: {cars}" + (f" ({g.battle_s:.0f} s of battles inside)"
                                                   if g.battle_s else ""))  # fmt: skip
    judged = [a for a in record.alerts if a.truth.right is not None]
    wrong = [a for a in judged if not a.truth.right]
    lines += ["", "## Alerts checked against the truth", "",
              f"{len(record.alerts)} alerts; {len(judged)} judged (ATTACK / DEFEND), "
              f"{len(judged) - len(wrong)} right, {len(wrong)} wrong."]  # fmt: skip
    for a in wrong:
        lines.append(
            f"- WRONG: {a.type} on {code(a.rival)}, lap {a.lap} ({a.branch or '-'}, confidence "
            f"{a.confidence:.2f}): estimate {fmt(a.truth.estimate_mj)} MJ, true "
            f"{fmt(a.truth.rival_true_mj)} MJ, ours {fmt(a.truth.our_mj)} MJ; "
            f"call: {a.option}; outcome: {a.outcome or '-'}"
        )
    lines += ["", "## Calls and their cost", ""]
    if not record.calls:
        lines.append("No calls" + (" (an export has no engineer)." if record.source == "export"
                                   else " were made."))  # fmt: skip
    for call in record.calls:
        cost = ("cost not computed" if call.cost is None
                else cost_label(call.cost.delta_s, call.cost.best_option))  # fmt: skip
        said = f' "{call.radio_text}"' if call.radio_text else ""
        after = f"P{call.position_after}" if call.position_after else "-"
        lines.append(
            f"- Lap {call.lap}, {call.kind}{said}: {call.label} (about {code(call.rival)}); "
            f"P{call.position_before} -> {after}; outcome: {call.outcome or '-'}; {cost}"
        )
    lines += ["", "## Incidents", ""]
    if not record.incidents:
        lines.append("None.")
    for inc in record.incidents:
        lines.append(f"- Lap {inc.lap}: {inc.detail}")
    lines += ["", "## Surprising connections", ""]
    lines += _surprises(record, stats, groups) or ["None found."]
    where = f"graphify-out/races/{record.run_id}/graph.json"
    lines += [
        "", "## Ask the graph", "",
        "```bash",
        f'graphify explain "{code(our)}" --graph {where}',
        f'graphify query "which alerts were wrong" --graph {where}',
        f'graphify path "{code(our)}" "<a rival code>" --graph {where} --undirected',
        "```", "",
    ]  # fmt: skip
    return "\n".join(lines)


def _surprises(record: RaceRecord, stats: dict[str, dict[str, Any]],
               groups: list[Any]) -> list[str]:  # fmt: skip
    """Facts worth a second look (rule-based, every number from the record)."""
    out = []
    c = record.cars
    for call in record.calls:
        alert = next((a for a in record.alerts if a.alert_id == call.alert_id), None)
        if call.cost and call.cost.delta_s > 1.0 and alert and alert.truth.right:
            out.append(f"- The {alert.type} alert on {c[alert.rival].code} (lap {alert.lap}) was "
                       f"right, yet the call cost {call.cost.delta_s:+.1f} s against "
                       f"'{call.cost.best_option}'.")  # fmt: skip
    for a in record.alerts:
        if a.truth.right is False and a.confidence >= 0.7:
            out.append(f"- A confident ({a.confidence:.2f}) {a.type} alert on {c[a.rival].code} "
                       f"(lap {a.lap}) was wrong: estimate {a.truth.estimate_mj or 0:.1f} MJ, "
                       f"true {a.truth.rival_true_mj or 0:.1f} MJ.")  # fmt: skip
    for d, s in stats.items():
        if s["time_within_1s_s"] >= 30 and not s["alerts"]:
            out.append(f"- {c[d].code}: {s['time_within_1s_s']:.0f} s within 1 s of Our Car, "
                       "but not one alert about them.")  # fmt: skip
    ours = next((g for g in groups if record.our in g.cars), None)
    for p in record.passes:
        if p.passed == record.our and ours is not None and p.passer not in ours.cars:
            out.append(f"- {c[p.passer].code} passed Our Car on lap {p.lap} without being in "
                       f"our battle group ({ours.name}).")  # fmt: skip
    return out

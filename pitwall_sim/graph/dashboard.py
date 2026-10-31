"""Race dashboard (Graphify track step 2): one page per race, next to its graph.

``dashboard.html`` (self-contained; d3 from the vendored ``lib/d3.min.js``):

- top tiles: alerts, calls made, passes made / lost, total call cost, radar MAE;
- a chord diagram: every car on the ring in its team colour (Our Car labelled
  "YOU"), ribbons = seconds within 1 s between two cars, with toggles for passes
  and alerts and an "only battles with my car" switch;
- "Rival read accuracy": per Rival Our Car battled, the estimate accuracy
  (1 - MAE / ``ACCURACY_SCALE_MJ``) and the share of alerts that were right;
- clicking a car shows the same stats as its node in the race graph.

Every number comes from the :class:`RaceRecord` through ``race_graph`` (the same
functions as the graph's node stats), so the two views always agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pitwall_sim.graph.race_graph import fill_page, pair_battle_s, race_totals, rival_stats
from pitwall_sim.graph.record import RaceRecord

ACCURACY_SCALE_MJ = 4.0
"""Estimate accuracy = 1 - MAE / this (the usable battery, 0-4 MJ)."""


def dashboard_data(record: RaceRecord) -> dict[str, Any]:
    """Return everything the dashboard page draws."""
    order = sorted(
        record.cars,
        key=lambda d: (
            d != record.our,  # Our Car at the top of the ring
            record.cars[d].finish_position or 99,
            d,
        ),
    )
    index = {d: k for k, d in enumerate(order)}
    n = len(order)
    battles = [[0.0] * n for _ in range(n)]
    for (a, b), secs in pair_battle_s(record).items():
        if a in index and b in index:
            battles[index[a]][index[b]] = battles[index[b]][index[a]] = round(secs, 1)
    passes = [[0.0] * n for _ in range(n)]
    for p in record.passes:
        if p.passer in index and p.passed in index:
            passes[index[p.passer]][index[p.passed]] += 1.0
    alerts = [[0.0] * n for _ in range(n)]
    for alert in record.alerts:
        if alert.rival in index and record.our in index:
            alerts[index[record.our]][index[alert.rival]] += 1.0
    stats = rival_stats(record)
    accuracy = []
    for d, s in stats.items():
        if s["time_within_1s_s"] <= 0:
            continue
        mae = s["radar_mae_mj"]
        est = None if mae is None else round(max(0.0, 1.0 - mae / ACCURACY_SCALE_MJ), 3)
        accuracy.append({
            "id": d, "code": record.cars[d].code, "color": record.cars[d].color,
            "battle_s": s["time_within_1s_s"],
            "estimate_accuracy": est,
            "radar_mae_mj": mae, "alerts_right_pct": s["alerts_right_pct"],
            "alerts_judged": s["alerts_judged"], "alerts_right": s["alerts_right"],
        })  # fmt: skip
    accuracy.sort(key=lambda r: -r["battle_s"])
    cars = [{"id": d, "code": record.cars[d].code, "team": record.cars[d].team,
             "color": record.cars[d].color, "finish": record.cars[d].finish_position,
             "status": record.cars[d].status, "our": d == record.our} for d in order]  # fmt: skip
    return {
        "race": {"run_id": record.run_id, "source": record.source, "track_id": record.track_id,
                 "seed": record.seed, "laps": record.laps, "our": record.our,
                 "our_code": record.cars[record.our].code, "test_mode": record.test_mode},
        "totals": race_totals(record), "cars": cars,
        "matrices": {"battles": battles, "passes": passes, "alerts": alerts},
        "stats": {d: s for d, s in stats.items()}, "accuracy": accuracy,
        "accuracy_scale_mj": ACCURACY_SCALE_MJ,
    }  # fmt: skip


def write_dashboard(record: RaceRecord, out: Path) -> Path:
    """Write ``dashboard.html`` into ``out`` (``lib/d3.min.js`` must sit next to it)."""
    path = out / "dashboard.html"
    title = (
        f"Race dashboard - {record.cars[record.our].code} - {record.track_id} seed {record.seed}"
    )
    path.write_text(fill_page("dashboard.html", title, dashboard_data(record)), encoding="utf-8")
    return path

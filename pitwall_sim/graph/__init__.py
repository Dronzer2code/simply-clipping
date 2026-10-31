"""Race comparison graphs (Graphify track): Our Car against every Rival, after the flag.

- ``record``: :class:`~pitwall_sim.graph.record.RaceRecord`, everything one finished
  race left behind (battles, passes, incidents, alerts with truth checks, calls with
  costs, radar error per Rival), from a live session or an export folder.
- ``race_graph``: the record as a graph in graphify's ``graph.json`` schema (so
  ``graphify query / path / explain --graph`` work on it), our own offline
  ``graph.html`` viewer and ``race_report.md``.
- ``dashboard``: the race dashboard page (tiles, chord diagram, rival read accuracy).
- ``race``: the command line, ``python -m pitwall_sim.graph.race``.

Graphs are built only after the chequered flag: truth is allowed then (owner, H1),
never before (HR-03).
"""

# BUILD_PROMPTS.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This document contains the ordered prompts a human operator pastes into an AI coding agent (Claude Code or another IDE agent) to build `pitwall_sim` task by task.

Each prompt is self-contained: it tells the agent which documents to read, which tasks from `docs/planning/TASKS.md` to do, what "done" means, and when to stop. Prompts MUST be used in order. One prompt = one agent session (or one clear context).

## RELATED DOCUMENTS

| Document | Role in prompts |
| --- | --- |
| `CLAUDE.md` | Rules and workflow every prompt relies on |
| `docs/planning/TASKS.md` | Task IDs, dependencies, acceptance criteria |
| `docs/spec/PRD.md`, `docs/spec/MVP.md`, `docs/spec/TRD.md`, `docs/spec/PROCESS_FLOW.md`, `docs/spec/UI_DESIGN.md`, `docs/guides/SETUP.md` | Referenced by section |

## OPERATOR RULES

- Before each prompt, check that the previous prompt's tasks are `DONE` in `docs/planning/TASKS.md`.
- If the agent reports `BLOCKED`, resolve the blocker (usually an `UNRESOLVED` decision) before continuing.
- After every block, run prompt `P-REVIEW`.
- Do not merge prompts to save time; each block has its own acceptance gate.

## P-00 SESSION START (prepend to every prompt)

```text
You are building pitwall_sim. Read CLAUDE.md fully before doing anything.
Follow its HARD RULES and WORKFLOW exactly.
Do not decide anything listed under "UNRESOLVED ITEMS AGENTS MUST NOT DECIDE"; mark the task BLOCKED instead.
Use only names defined in docs/spec/PRD.md GLOSSARY and docs/spec/TRD.md DATA CONTRACTS.
At the end, report: tasks completed, files changed, tests added, acceptance results, placeholders introduced, open questions.
```

## R1 — MVP PROMPTS

### P-01 Foundation (T-001 → T-005)

```text
[P-00]
Do tasks T-001, T-002, T-003, T-004, T-005 in docs/planning/TASKS.md, in order.
Read: docs/spec/TRD.md sections TECHNOLOGY STACK, REPOSITORY STRUCTURE, CONFIG SCHEMAS, RULE SET VALUES; docs/guides/SETUP.md sections 2, 3, 7.
Create the package skeleton exactly as TRD REPOSITORY STRUCTURE (empty modules with docstrings are fine).
Config values marked UNKNOWN/UNRESOLVED in the docs must stay UNRESOLVED or "# PLACEHOLDER: calibrate" — never invent numbers.
For real_2026.yaml, take teams/drivers from FastF1 results of the most recent 2026 race available; record which race in a comment.
Gate: pytest -q, lint-imports, ruff check . all pass; test_rules_load passes and prints the unresolved-key list.
```

### P-02 Track (T-010 → T-011)

```text
[P-00]
Do tasks T-010 and T-011.
Read: docs/spec/TRD.md F01 notes and CONFIG SCHEMAS (tracks); docs/spec/PROCESS_FLOW.md PF-01; docs/guides/SETUP.md section 4.
The builder must be generic: no Suzuka-specific code paths. Suzuka specifics go only in config/tracks/suzuka.yaml.
For overtaking zones and detection points, cite the source in a YAML comment; if no source, mark UNRESOLVED and report.
Gate: builder CLI writes data/tracks/suzuka.parquet; closed loop; length within ±1% of official; zone validation test passes.
```

### P-03 Single-car physics (T-020 → T-025)

```text
[P-00]
Do tasks T-020, T-021, T-022, T-023, T-024, T-025.
Read: docs/spec/TRD.md SIMULATION CORE (all subsections), DATA CONTRACTS, TESTING rows test_taper, test_battery_bounds, test_lap_limits, test_constant_speed_power.
Write the listed tests first, then implement.
Internal units SI; unit suffixes on names (CLAUDE.md CODE CONVENTIONS).
Every rule value must be read from the Rule Set file passed in; add a test that swaps 2026_pre_miami / 2026_post_miami and sees different zone caps and super-clip power.
Gate: all listed tests pass; calibration CLI prints Suzuka lap time delta and speed RMSE (any value is acceptable at this step).
```

### P-04 Calibration (T-026)

```text
[P-00]
Do task T-026.
Read: docs/spec/TRD.md CALIBRATION; docs/spec/PROCESS_FLOW.md PF-02.
Tune only coefficients in config/teams/performance.yaml and config/tyres.yaml. Do not change physics code to hit the target; if the target cannot be reached by coefficients alone, stop and report why.
Gate: MVP-02 — Suzuka lap time within 2% of the 2026 reference qualifying lap. Report final delta, speed RMSE, and every coefficient changed with old → new values.
```

### P-05 Race (T-030 → T-036)

```text
[P-00]
Do tasks T-030 to T-036 in order.
Read: docs/spec/TRD.md Per-step order, Longitudinal dynamics, AI DRIVER, OVERTAKE MODEL, PIT LANE, PERFORMANCE BUDGETS; docs/spec/PROCESS_FLOW.md PF-04, PF-11, PF-12.
The Numba kernel works on parallel NumPy arrays only (no Python objects inside @njit).
The per-step order in PF-04 is mandatory.
Overtake weights are placeholders until calibration; flag them in config.
Gate: MVP-05 — test_headless_runtime ≤ 10 s on this machine (report machine specs); a full 22-car Suzuka race completes with consistent laps, gaps and at least one overtake and one pit stop per car.
```

### P-06 Determinism and Snapshot (T-040)

```text
[P-00]
Do task T-040.
Read: docs/spec/TRD.md SNAPSHOT AND DETERMINISM; CLAUDE.md HR-04.
Search the codebase for any randomness not using the named RNG streams and fix it.
Gate: MVP-06 — test_determinism (identical hash every lap, same seed + commands) and test_snapshot_roundtrip pass.
```

### P-07 Observation (T-050 → T-052)

```text
[P-00]
Do tasks T-050, T-051, T-052.
Read: docs/spec/TRD.md PUBLIC FEED, RIVAL BATTERY RADAR, DATA CONTRACTS (EngineerView); docs/spec/PROCESS_FLOW.md PF-06.
If existing Rival Battery Radar source code is present in the repository or provided by the operator, port it; otherwise implement from the TRD algorithm summary. State which in the report.
The radar must use radar.* constants from config/app.yaml, not the simulator's true team values.
Gate: MVP-08 — test_info_barrier passes and lint-imports passes; test_radar_on_sim reports mean and 90th-percentile energy error vs Ground Truth.
```

### P-08 Rival Strategy (T-041)

```text
[P-00]
Do task T-041.
Read: docs/spec/TRD.md RIVAL STRATEGY AI; docs/spec/PROCESS_FLOW.md PF-10; CLAUDE.md HR-03.
Rival teams may read only their own Ground Truth plus Public Feed / Radar Estimates of other cars. Add a test that fails if a Rival strategy reads another car's battery_mj.
Gate: MVP-10 — at least one Rival pits and changes Energy Mode unaided in a seeded race.
```

### P-09 Commands (T-060 → T-061)

```text
[P-00]
Do tasks T-060 and T-061.
Read: docs/spec/TRD.md ENGINEER COMMANDS; docs/spec/PROCESS_FLOW.md PF-07; docs/spec/PRD.md FR-CTRL-01…05.
Commands take effect at effective_at_s = issued_at_s + radio_latency_s.
For test_each_command_effect: for each R1 CommandType, fork the same Snapshot with and without the command and assert a measurable difference in Our Car behaviour.
Gate: MVP-09 — test_each_command_effect passes for every R1 command type; invalid commands return a reason string.
```

### P-10 UI (T-070 → T-077)

```text
[P-00]
Do tasks T-070 to T-077 in order.
Read: docs/spec/UI_DESIGN.md fully; docs/spec/PROCESS_FLOW.md PF-03, PF-05, PF-07; CLAUDE.md HR-02, HR-08.
UI reads only EngineerView. Simulation runs in a QThread; UI refresh 10 Hz; plots update via setData only.
Rival battery is always shown as an estimate (tilde, hatched band, confidence).
Use QT_QPA_PLATFORM=offscreen for UI tests if no display.
Gate: MVP-07 — no frame > 100 ms over 60 s at 16x; every R1 command can be issued from buttons and shortcuts; screenshots of S1 and S2 attached to the report.
```

### P-11 MVP acceptance (T-080)

```text
[P-00]
Do task T-080.
Run every MVP acceptance check MVP-01…MVP-10 from docs/spec/MVP.md and write docs/MVP_REPORT.md with: pass/fail per check with evidence, machine specs, all placeholders still in config, all UNRESOLVED values used, known issues.
Do not fix failures in this prompt; list them.
```

## R2–R5 PROMPTS

### P-20 Split a release

```text
[P-00]
Release <R2|R3|R4|R5> is next. Read docs/spec/MVP.md RELEASE PLAN and the matching section of docs/planning/TASKS.md.
Split each coarse task of that release into tasks of the same size as the R1 tasks (one module or one behaviour each), with Files, Depends on, Acceptance, Refs, Status = TODO.
Use the next free IDs inside the release block (e.g. T-107, T-108 for R2).
Do not write code. Show the updated TASKS.md section in the report.
```

### P-21 Build a split release

```text
[P-00]
Do the next 3–6 TODO tasks of release <R2|R3|R4|R5> whose dependencies are DONE, in ID order.
Read every Refs section listed in those tasks.
Gate: each task's acceptance criteria pass; full test suite passes; for R3 tasks, the UI never blocks during LLM calls.
```

### P-22 Release gate

```text
[P-00]
Release <R2|R3|R4|R5> tasks are all DONE. Verify the release "Done when" line in docs/spec/MVP.md RELEASE PLAN with evidence.
Re-run calibration for every built track and confirm NFR-06 still holds.
Write docs/<RELEASE>_REPORT.md in the same format as docs/MVP_REPORT.md.
```

## SUPPORT PROMPTS

### P-REVIEW Block review (after every block)

```text
[P-00]
Review the code changed for tasks <IDs> against: CLAUDE.md HARD RULES, docs/spec/TRD.md for those tasks, and their acceptance criteria.
Do not change code. Report findings ranked by severity with file:line, rule or requirement violated, and a concrete failure scenario.
Specifically check: hard-coded rule numbers (HR-05), randomness outside named streams (HR-04), Rival Ground Truth leaks (HR-03), UI imports (HR-02), display names used as keys (HR-06).
```

### P-FIX Apply review findings

```text
[P-00]
Fix these review findings: <paste findings>.
For each, add or update a test that fails before the fix and passes after.
Gate: full test suite, lint-imports, ruff check . pass.
```

### P-UNBLOCK Record a decision

```text
[P-00]
The owner decided: <decision, e.g. "debrief.score_scale_s = 20">.
Update every document that lists this item as UNKNOWN/UNRESOLVED (PRD.md OPEN ITEMS, TRD.md, CLAUDE.md, SETUP.md, TASKS.md status) so all documents agree.
Do not change code unless the decision requires it; list affected tasks and set any BLOCKED task back to TODO.
```

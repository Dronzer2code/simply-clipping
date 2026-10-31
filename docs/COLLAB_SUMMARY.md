# Project summary for collaborators (2026-10-31)

Read this first for an overview of the project, what is done and what is open.
The details live in the documents linked at the end.

## What the project is

**We Are Racing, Not Testing** is a desktop Formula 1 pit-wall simulator for the
2026 rules, in which about half a car's power is electric. The user is the race
engineer of one car:

- they see their own car exactly;
- they see rivals only through public timing and an estimate of each rival's hidden battery;
- they give orders by buttons, typed radio or voice;
- after the race, the true values are revealed and every call is priced in seconds.

The repository has two parts:

| Part | Folder | What it does |
| --- | --- | --- |
| Simulator | `pitwall_sim/` | 22-car race at Suzuka: physics, rival AI, pit stops, Safety Car, weather, pit-wall UI, post-race Reveal |
| Simply Clipping | `simply_clipping/` | The owner's estimator. It reads public speed data, detects "clipping" (the battery running out on a straight), estimates each rival's battery with a confidence value, and raises ATTACK / DEFEND / RE-PASS / CLOSING-SPEED alerts. It is a plug-in and never imports the simulator. |

Python 3.13 and PySide6. Repository: https://github.com/Dronzer2code/simply-clipping (branch `main`).

## Setup and run

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
# optional: voice input and hosted LLM
uv pip install --python .venv/Scripts/python.exe faster-whisper sounddevice httpx

.venv\Scripts\Activate.ps1            # Windows PowerShell
python main.py                        # setup screen, then the live pit wall
```

Gates (all must pass before a commit):

```bash
pytest -q                 # 638 passed, 1 skipped (about 5 minutes)
ruff check . ; ruff format --check .
mypy pitwall_sim simply_clipping
lint-imports              # architecture contracts, including the information barrier
```

Other commands:

| Command | Does |
| --- | --- |
| `python -m pitwall_sim.race.engine --headless --track suzuka --rules 2026_post_miami --seed 42` | Headless race (53 laps, about 8 s) |
| `python -m pitwall_sim.bench --sc-module simply_clipping --scenario all --seeds 6-10 --rerun` | Score Simply Clipping against the built-in radar |
| `python -m pitwall_sim.replay.real_race --lap 30 --our NOR` | Start from lap 30 of the real 2026 Japanese GP |
| `python -m pitwall_sim.viewer --seed 2` | Replay viewer |

## What is built

| Feature | State |
| --- | --- |
| 2026 power-unit model, 22-car race, overtakes, pit stops, rival strategy AI | Done |
| Information barrier: no rival ground truth in the in-race view (tested) | Done |
| Built-in radar estimate and alerts with F1 / F2 / F3 call options | Done |
| Safety Car / VSC from crashes, including contact in overtakes; cheaper stops under SC | Done |
| Rain from a chosen lap; rivals switch to intermediates | Done |
| Real race moment: start from a real 2026 Japanese GP lap (OpenF1) | Done |
| Radio: buttons, typed keyword parser (offline), push-to-talk (faster-whisper, offline) | Done |
| Driver replies (templates) and driver voice (Windows SAPI, radio filter) | Done |
| Hosted LLM for radio commands and driver replies (OpenAI or Anthropic) | Built; off until a provider and API key are set |
| Strategy panel (pit-window forks from public data only, background processes) | Done |
| Telemetry tab (speed, throttle, battery, previous-lap ghost) | Done |
| Post-race Reveal, decision cost per call, engineer score out of 100 | Done |
| Simply Clipping estimator, alerts, live plug-in, real-race run | Done |

## Simply Clipping results (test seeds 6-10)

| Metric | Built-in radar | Simply Clipping |
| --- | --- | --- |
| Battery error (MAE) | 0.84-1.28 MJ | 0.36-0.88 MJ |
| CLIP precision | 4-6 % | 53-66 % |
| Confidence calibration error | 18-34 % | 4-10 % |

Weak spots: ATTACK recall is 0 %, and it cannot detect frozen data (it missed the real
lap-22 BEA crash). On the real 2026 Japanese GP it flagged the Norris / Hamilton
re-pass 15 s and 20 s ahead.

## Known issues and limits

- The live radar panel and the Reveal show the built-in radar, not Simply Clipping.
  Alerts use the built-in provider unless `alerts.provider: external:simply_clipping`
  is set in `config/app.yaml`. Making Simply Clipping the live radar is the top item
  in `docs/planning/IMPROVEMENTS.md`.
- Fuel is a placeholder: full-distance races run out at laps 41-46, so the default race is 15 laps (task `T-02B`).
- Tyre wear and team values are placeholders until calibration. The undercut rarely pays in 15-lap races.
- The strategy panel takes about 30 s for its first result and refreshes about every 25 s.
- Timing tests can fail on a busy machine; rerun them alone.

## Decisions still open (owner)

- LLM provider and API key: `radio_llm.provider` in `config/app.yaml`, plus `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- Simply Clipping open items O-1 (0.5 MJ "right" tolerance) and O-3 (closing rule).
- Fuel and calibration values (`T-02B`, `T-02C`, `T-026`); agents must not tune placeholders by hand.

## Rules for working on the code

- `CLAUDE.md` holds the hard rules. The main ones:
  - simulation core never imports the UI;
  - the UI gets data only through `EngineerView`;
  - no rival ground truth in any in-race view;
  - all randomness from the named RNG streams;
  - no hard-coded rule values;
  - ids, never display names.
- `simply_clipping` and `pitwall_sim` must not import each other (import-linter contracts).
- Commits: author `Dronzer2code <179497926+Dronzer2code@users.noreply.github.com>`, no AI attribution in messages. Run all gates first.
- Run data (`data/runs/`), caches and models (`models/`) are gitignored. Test scripts used for checks are in `data/runs/_tools/` on the owner's machine only.

## Where to read more

| Need | Document |
| --- | --- |
| Index of all docs | `docs/README.md` |
| Current state and history of decisions | `docs/status/SESSION_CONTEXT.md` |
| Product scope and requirements | `docs/spec/PRD.md`, `docs/spec/MVP.md` |
| Technical design and config schemas | `docs/spec/TRD.md` |
| Simply Clipping design | `docs/spec/SIMPLY_CLIPPING_SPEC.md`, `docs/spec/SIMPLY_CLIPPING_BRIDGE.md` |
| Hackathon scope and demo script | `docs/HACKATHON_SCOPE.md`, `docs/guides/DEMO_HACKATHON.md` |
| Plain-language pitch | `docs/PITCH.md` |
| Next improvements, ranked | `docs/planning/IMPROVEMENTS.md` |
| Task list | `docs/planning/TASKS.md` |
| Code map | `graphify-out/GRAPH_REPORT.md` (or `graphify query "..."`) |

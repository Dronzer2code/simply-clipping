# SETUP.md — Pit Wall Race Simulator (2026 Regulations)

## PURPOSE

This document defines how to set up, run and test `pitwall_sim` on a development machine. It is the source of truth for commands referenced in `CLAUDE.md` and `docs/planning/TASKS.md`.

Technology choices come from `docs/spec/TRD.md` TECHNOLOGY STACK.

## REQUIREMENTS

| Item | Requirement |
| --- | --- |
| OS | Windows 10/11, macOS 13+, or Linux (developer OS: UNKNOWN) |
| Python | 3.13 (owner decision 2026-10-19; the 3.11 install on the target machine is broken) |
| Disk | ~1 GB for FastF1 cache per few races; ~0.3 GB for the Gemma 3 270M GGUF (R3) |
| RAM | 8 GB (target machine). Gemma 3 270M Q8_0 (~0.3 GB) fits comfortably |
| GPU | None on the target machine. `llama-cpp-python` is a CPU build only |
| Network | Needed only to download dependencies, FastF1 data and the Gemma model; app runs offline afterwards (NFR-01) |

Target laptop hardware for performance targets (owner decision 2026-10-19): 8 GB RAM, CPU only, no GPU. Report measured times against NFR-02 / MVP-05 on this machine.

## 1. CLONE AND ENVIRONMENT

```bash
git clone https://github.com/Dronzer2code/We_are_racing-not_testing---F1sim_lite.git pitwall_sim
cd pitwall_sim
python3.13 -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## 2. DEPENDENCIES (`pyproject.toml`)

Versions are pinned (`T-001`). Groups:

```toml
[project]
name = "pitwall_sim"
requires-python = ">=3.13,<3.14"
dependencies = [
  "numpy==2.5.4",
  "numba==0.68.0",
  "scipy==1.18.1",
  "polars==2.0.0",
  "pyarrow==26.0.0",
  "fastf1==3.8.3",
  "pyyaml==6.0.3",
  "pydantic==2.14.1",
  "PySide6==6.12.0",
  "pyqtgraph==0.14.0",
]

[project.optional-dependencies]
dev = [
  "pytest==9.1.1", "pytest-qt==4.5.0", "hypothesis==6.170.1",
  "ruff==0.17.1", "mypy==2.4.0", "import-linter==2.15",
  "types-PyYAML==6.0.12.20260906",
]
radio = ["llama-cpp-python==0.3.36"]  # R3 only, CPU build
```

`.importlinter` also needs `include_external_packages = True`, because the
`sim-headless` contract forbids an external module (`PySide6`).

MVP (R1) MUST NOT require the `radio` group (MVP.md CONSTRAINTS).

## 3. IMPORT CONTRACTS (`.importlinter`)

```ini
[importlinter]
root_package = pitwall_sim

[importlinter:contract:sim-headless]
name = Simulation core is headless (HR-01)
type = forbidden
source_modules =
    pitwall_sim.race
    pitwall_sim.car
    pitwall_sim.track
    pitwall_sim.driver
forbidden_modules =
    pitwall_sim.ui
    pitwall_sim.radio
    PySide6

[importlinter:contract:ui-info-barrier]
name = UI reads only EngineerView (HR-02)
type = forbidden
source_modules =
    pitwall_sim.ui
forbidden_modules =
    pitwall_sim.race.state
```

## 4. REAL DATA (FASTF1)

FastF1 cache directory: `data/fastf1_cache/` (set in `config/app.yaml: paths.fastf1_cache`). Code MUST call `fastf1.Cache.enable_cache(<path>)` before loading sessions.

F1 serves its live-timing archive (laps, car and position telemetry) only to a
logged-in Formula 1 account; without it FastF1 returns no lap data for any
year (its public mirror has no 2026 data either). With an account, log in once
per machine (opens a browser; the token is stored in FastF1's user data folder,
not in this repo):

```bash
python -m fastf1 auth f1tv --authenticate
python -m fastf1 auth f1tv --status
```

**OpenF1 is the backup source for track geometry** (owner decision round 5).
The project owner has no F1TV account, so this is the normal path today.
[OpenF1](https://openf1.org) (`https://api.openf1.org/v1`) is free, needs no
login and has historical data from 2023. With the default `--source auto` the
builder tries FastF1 first and falls back to OpenF1 when FastF1 has no data,
logging which source it used; `--source fastf1` or `--source openf1` forces one.
It uses `/sessions` (session key), `/laps` (fastest timed lap: `lap_duration`,
`date_start`) and `/location` (x/y for that driver and lap window, ~3.7–3.9 Hz).
Requests are throttled to the free-tier limit (3 per second, 30 per minute;
`config/app.yaml: openf1`) and every raw response is cached in
`data/openf1_cache/` (git-ignored with `data/`), so a rebuild runs offline.
The provider used is written to the parquet metadata and to
`geometry_source.source` in `config/tracks/<track_id>.yaml`.

Build the Suzuka track model (R1):

```bash
python -m pitwall_sim.track.builder --track suzuka                  # auto: FastF1, then OpenF1
python -m pitwall_sim.track.builder --track suzuka --source openf1  # skip the FastF1 attempt
python -m pitwall_sim.track.builder --track suzuka --laps 1         # one lap, no pooling (T-029)
# output: data/tracks/suzuka.parquet
```

Corner and pit positions for `config/tracks/<track_id>.yaml` (T-011; prints a
YAML fragment with sources, does not edit the config; responses cached in
`data/openf1_cache/` and `data/multiviewer_cache/`):

```bash
python -m pitwall_sim.track.landmarks --track suzuka
```

Calibration compare (T-025; reference lap from OpenF1, cached; report in
`data/calibration/<track_id>.parquet`):

```bash
python -m pitwall_sim.calibration.compare --track suzuka              # every team
python -m pitwall_sim.calibration.compare --track suzuka --team mercedes
```

Pre-cache before working offline:

```bash
python -m pitwall_sim.track.builder --track suzuka --cache-only
```

R4/R5 Real Race cache (FastF1; without an F1TV login this will need the same
OpenF1 fallback as the track builder — not built yet):

```bash
python -m pitwall_sim.replay.real_race --year 2026 --event "Japan" --session R
# output: data/real_races/2026_<round>/*.parquet
```

If neither FastF1 nor OpenF1 has 2026 data for a track, the builder exits with status `UNAVAILABLE` (PF-01).

## 5. GEMMA MODEL (R3 ONLY)

| Item | Value |
| --- | --- |
| Base model | Gemma 3 270M instruct, `gemma-3-270m-it` (owner decision 2026-10-19) |
| Fine-tuning | REQUIRED, not optional. Trained on generated engineer-phrase → command pairs (`T-206`, `T-207`) |
| Shipped artefact | `models/gemma-3-270m-it-pitwall.gguf`, produced by `T-208` (fine-tune + GGUF conversion). Q8_0 quantisation preferred for a model this small |
| Path | set in `config/app.yaml: radio.model_path` |
| Output control | llama.cpp GBNF grammar forces valid command JSON; a keyword pre-parser runs first (TRD `RAD-02`, `RAD-03`) |
| Driver replies | templates only; the model may rephrase, never originate facts |
| License | Gemma terms of use MUST be accepted on the model page before download |

Install the runtime (CPU only — the target machine has no GPU). Build
`llama-cpp-python` without any GPU backend, so no CUDA/Metal/Vulkan toolkit is
needed or picked up:

```bash
# bash / macOS / Linux
CMAKE_ARGS="-DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_VULKAN=OFF" pip install -e ".[radio]"
```

```powershell
# Windows PowerShell
$env:CMAKE_ARGS = "-DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_VULKAN=OFF"; pip install -e ".[radio]"
```

`models/` and `data/` MUST be in `.gitignore`.

## 6. COMMANDS

| Purpose | Command |
| --- | --- |
| Run desktop app | `python main.py` |
| Headless race | `python -m pitwall_sim.race.engine --headless --track suzuka --rules 2026_post_miami --grid real_2026 --seed 42` |
| Headless race output | add `--out data/runs/<name>.parquet` to save Ground Truth log |
| Build track | `python -m pitwall_sim.track.builder --track <track_id>` |
| Calibration report | `python -m pitwall_sim.calibration.compare --track <track_id>` |
| All tests | `pytest -q` |
| Fast tests only | `pytest -q -m "not slow and not llm and not ui"` |
| UI tests | `pytest -q tests/ui` |
| LLM tests (R3) | `pytest -q -m llm` |
| Lint | `ruff check .` |
| Format check | `ruff format --check .` |
| Types | `mypy pitwall_sim --exclude pitwall_sim/ui` |
| Architecture contracts | `lint-imports` |

Pytest markers (declare in `pyproject.toml`): `slow` (full races, calibration), `ui` (pytest-qt), `llm` (needs model file).

## 7. CONFIG FILES

| File | Purpose |
| --- | --- |
| `config/app.yaml` | paths, sim/feed/ui/radar/predictor/debrief/radio defaults |
| `config/rules/2026_pre_miami.yaml`, `2026_post_miami.yaml` | Rule Sets |
| `config/grid/real_2026.yaml`, `fictional.yaml` | Grids |
| `config/teams/performance.yaml` | Team PU, aero, efficiency, strategy style |
| `config/tyres.yaml` | Compound coefficients |
| `config/tracks/<track_id>.yaml` | Track zones, pit, events, weather |

Schemas: `docs/spec/TRD.md` CONFIG SCHEMAS.

## 8. VERIFY THE SETUP

```bash
pytest -q -m "not slow and not llm and not ui"   # passes
lint-imports                                      # 2 contracts kept
python -m pitwall_sim.track.builder --track suzuka
python -m pitwall_sim.race.engine --headless --track suzuka --rules 2026_post_miami --seed 42
python main.py
```

Each command is available only after the task that creates it is `DONE` (see `docs/planning/TASKS.md`).

## TROUBLESHOOTING

| Symptom | Fix |
| --- | --- |
| Numba first run slow | Expected JIT compile; use `@njit(cache=True)` so later runs are fast |
| FastF1 load fails offline | Pre-cache with `--cache-only` while online |
| PySide6 window does not open on Linux | Install system Qt/xcb libraries (`libxcb-cursor0` on Debian/Ubuntu) |
| `llama-cpp-python` build fails | Install a C++ compiler (MSVC Build Tools on Windows, Xcode CLT on macOS, `build-essential` on Linux) |
| UI tests fail on headless CI | Set `QT_QPA_PLATFORM=offscreen` |

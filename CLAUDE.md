# Darwin agent context

Read this file first, then `README.md`, `STATUS.md`, `INTERFACES.md`, and
`firmware/REVIEW.md`. Treat repository-relative paths as authoritative. Never
reuse absolute paths, virtual environments, serial ports, or camera calibration
files from another computer.

## What Darwin is

Darwin is a two-wheel Hack the North robot that learns the relationship between
two abstract motor commands and camera-observed body motion. The same runtime,
ridge-regression learner, controller, safety state machine, recorder, replay,
evaluation, and dashboard run in simulation and on hardware. Only the camera and
actuator adapters change.

The learner must never receive the simulator's hidden map, the hardware mutation
type, or any privileged inverse. It learns only from requested actions and
camera-measured transitions. Hidden actuator mutations include swapping wheels,
reversing either or both wheels, and unequal gains. Persistent prediction
residuals trigger bounded active experiments, refitting, held-out validation,
and resumed navigation.

The model is a small affine ridge regression over
`[left_command, right_command, bias] -> [forward_speed, yaw_rate]`. Do not
describe it as a neural network or fabricate an AI visualization. Visualizations
may expose Darwin's learned coefficients, predicted command surface, recorded
samples, residuals, uncertainty, and model generations, but never simulator
truth.

## Current repository state

- Git remote: `https://github.com/athravseruwam07/darwin.git`
- Default branch: `main`
- Agent context was introduced in `1695e86`; always inspect local and remote `main` for newer work.
- Verified on Windows 11 x64 with PowerShell and the repository-local `venv`.
- Latest complete test run: **202 passed, 2 skipped, 0 failures**.
- The dashboard normally uses <http://127.0.0.1:8770/>. Verify the listener and
  `/api/status` instead of assuming it is running.
- Generated reports, local camera calibrations, `configs/*.local.yaml`, serial
  device names, logs, exports, caches, and virtual environments are not portable
  source and must not be committed.

There may be modified tracked files under `reports/` from local verification.
They are generated evidence, not permission to overwrite, discard, or publish
them. Preserve unrelated dirty-tree work and stage explicit paths only.

`CURRENT_CHAT_HANDOFF.md` is historical and currently stale: it refers to the
original macOS computer and the pre-hardware checkpoint. Do not follow its
machine paths or claimed live state. `README.md`, `STATUS.md`, and this file
override it until it is refreshed.

## Physical setup observed on this Windows computer

- Arduino Uno R3 with reviewed Darwin firmware and TB6612FNG motor driver.
- OAK overhead camera, 640 x 480 frames, ArUco marker ID 7.
- Taped 1 m x 1 m arena; saved marker-plane calibration is machine-specific.
- The previously identified controller was COM5, but always rediscover and
  verify the port before reconnecting.
- AA motor batteries and USB are physically connected during supervised tests.
- The marker is mounted flat on cardboard above the robot.
- Camera calibration is invalid if the camera or arena moves.

Measured local evidence exists for real camera tracking, serial ACKs, physical
motion learning, and one successful learned navigation. The exact flashed-binary
provenance is not recorded. An OAK `X_LINK_ERROR` and native DepthAI crash have
also occurred, so camera-loss behavior remains a real reliability concern.

Never automatically flash firmware or initiate physical movement. Before any
moving test, require a clear arena, restrained cables, a person ready to lift the
robot, confirmed motor power, stable tracking, and explicit operator readiness.
Start disarmed. STOP, stale frames, serial loss, lease loss, boundary limits, and
the firmware watchdog must remain fail-closed.

## Current behavior and product contract

- Default mode is simulation; hardware requires an explicit local config.
- Live mutation buttons may be used during active navigation when enabled.
- Applying a mutation is an operator event. Darwin remains unaware until repeated
  camera residuals cross the change-detection threshold.
- The UI must visually separate what the operator knows from what Darwin has
  inferred. Never display `Change detected` merely because a button was pressed.
- Navigation completes when the point target enters the configured robot
  footprint (`goal_contact_radius_m`, currently 0.08 m), followed by dwell.
- Leaving the green operating area should trigger inward boundary recovery while
  the physical footprint remains inside the red arena; it is not itself a fatal
  boundary error.
- Drive/Lab view changes must never stop, restart, or take ownership from an
  active runtime. Controls and telemetry use the same persistent browser owner.
- Only enabled actions should be clickable. STOP stays prominent and available
  whenever an operation is running.
- Replay must be unmistakably labeled and read-only. Never present recorded data
  as live hardware.

## Darwin Observatory UI

The **Arena** is intentionally only the live camera, simple current status, and
the actions needed for the demo: calibrate, choose a target, navigate, alter the
body mid-run, and stop. Do not put model IDs, raw coordinates, connection labels,
or learning diagrams on this screen.

An actual runtime `FAULT` must render as **STOPPED**, never **READY**, even when
the learned model remains valid. A tracking dropout is a real safety stop; once
tracking is healthy, an operator stop may disarm the fault without deleting the
validated model.

The **Observatory** explains genuine runtime evidence in judge-friendly language:

- What Darwin expected versus what the camera observed on the latest pulse.
- Whether repeated disagreement is normal, suspicious, or a detected change.
- The active Watch -> Notice -> Experiment -> Prove stage.
- A plain-English interpretation of each learned wheel-control coefficient.
- Before/after prediction-error improvement on held-out movements.
- A short causal event story from mutation through validation and recovery.

Raw model IDs, coordinates, RMSE tables, the 3D sensorimotor surface, fitted
coefficient graph, immutable events, and diagnostics live in a collapsed
**Technical proof** section. They remain available to technical judges without
competing with the story. All narration must be derived from structured runtime
facts so a future LLM may rephrase it without inventing state.

Switching Arena and Observatory is client-side and must never interrupt the
runtime or control lease. The renderer remains dependency-free Canvas/SVG, with
no WebGL, cloud, or CDN requirement.

The Observatory's **Darwin's inner monologue** card is implemented by
`darwin.cognition` and `web/static/brain.js`. It turns allow-listed public runtime
facts into deterministic thoughts, while operator mutations stay in a separate
"Darwin cannot see this" channel. Optional OpenAI rephrasing and ElevenLabs voice
use `.env` or environment variables only and must fail back to the deterministic
sentence without affecting robot control. Keep this card in Observatory; Arena
must remain camera and controls only. Extend this path instead of adding another
narration system.

The visual direction is a refined scientific instrument, not a generic neon AI
dashboard: near-black field, warm paper typography, Darwin acid green, measured
cyan, and stale-model amber. Animation must encode real state changes, respect
`prefers-reduced-motion`, and never delay STOP or other safety controls.

## Development rules

1. Inspect the dirty tree and applicable instruction files before editing.
2. Use test-driven development: add failing unit/integration/browser-contract
   tests, implement the smallest coherent behavior, then refactor.
3. Keep Python contracts typed and JavaScript data parsers defensive. Reject
   nonfinite or malformed telemetry rather than drawing it.
4. Keep functions focused and avoid a framework migration unless it clearly
   reduces risk. The current frontend is static HTML/CSS/JavaScript served by
   FastAPI.
5. UI visuals must use public learned state only. A visualization endpoint may
   return learned coefficients or predictions over a fixed action grid; it must
   never access a simulator plant or actuator mutation map.
6. Preserve local-only binding and never expose motor controls publicly.
7. Do not commit generated runs, local hardware configuration, calibration,
   credentials, logs, caches, or `venv`.
8. After changes, run focused tests, JavaScript syntax checks, the complete test
   suite, `git diff --check`, and real browser/API workflow verification when
   available.
9. Update this file, `README.md`, and `STATUS.md` when architecture, commands, or
   verified facts materially change.
10. Do not claim hardware or visual verification that was not actually run.

## Commands

```powershell
# Install
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.resolved.txt
.\venv\Scripts\python.exe -m pip install -e ".[dev]"

# Test
.\venv\Scripts\python.exe -m pytest -q
node --check src\darwin\web\static\app.js

# Simulation
.\venv\Scripts\python.exe -m darwin.cli demo --mode simulation --config configs\simulation.yaml --ui-port 8770

# Hardware: starts disarmed; never move without coordinated readiness
.\venv\Scripts\python.exe -m darwin.cli demo --mode hardware --config configs\hardware.local.yaml --ui-port 8770
```

When handing this project to another agent, instruct it to read `CLAUDE.md`
completely before acting, then inspect current Git status, `STATUS.md`, and the
live `/api/status` response. Historical documents and old logs are evidence, not
current machine state.

# Darwin hardware-independent evidence

Verified 2026-09-19T21:36:13.493313+00:00. **Software verified in simulation; physical robot behavior remains unverified.**

## Results

- Full pytest suite: **147 passed**, zero failures. Two dependency deprecation warnings are retained in the log.
- One-command verification: **9/9 commands exited zero**; no skipped checks. See [exact commands and exit codes](verification/commands.json).
- Real server subprocess served HTML, status and JPEG; learning starts asynchronously; STOP prevents later samples. Its ephemeral server was cleaned up.
- Firmware compiled for `arduino:avr:uno`: **3766 bytes flash (11%), 294 bytes SRAM (14%)**. The actual source also passes a desktop behavior harness; these are separate forms of evidence, neither is an electrical bench test.
- **13/13 fake firmware/actual pyserial PTY scenarios pass.** Additional tests exercise in-flight STOP, early watchdog, ACK/reset/disconnect, loss during settling, lease expiry, reconnect invalidation, no motion after old job completion, and camera calibration mismatches.
- Actual ArUco detection: **150/150 generated frames**, position RMSE **0.946 mm**, heading RMSE **0.003170 rad**. Max position error 1.184 mm; max heading error 0.007287 rad. Occlusion invalidated tracking. Declared maximum tolerances were 4 mm / .04 rad.
- DepthAI 3.10.0 imports on arm64; installed SDK signatures were verified. No actual OAK/webcam stream is claimed.

## Full recorded simulation benchmark

Five seeds: 11, 22, 33, 44, 55. Three plants: linear, process/sensor noise, and deadband/lag/asymmetry/noise/latency. Four changes: swap, reverse one, reverse both, unequal signed gains. Four target/headings per phase. No parameter tuning based on these reported runs; early module sweeps exercised the same seeds without parameter fitting from truth. Standalone rendered-camera seed 42 is reported separately.

| Phase | Successes | Trials | Rate |
|---|---:|---:|---:|
| before navigation | 240 | 240 | 100.0% |
| frozen navigation | 0 | 240 | 0.0% |
| adapted navigation | 240 | 240 | 100.0% |

**60 cases, zero workflow errors.** Minimum held-out error reduction after adaptation: **94.06%**; mean **98.16%**. Frozen and adapted predictions use identical new-map held-out pulse IDs, disjoint from all fit IDs.

Thresholds declared in code/report: goal radius .06 m, observed dwell 500 ms, max 100 actions and 45 synthetic seconds; success target ≥80% for baseline and adapted; normalized prediction error reduction target ≥80%. Neither threshold was lowered. All frozen failures are retained, including boundary and budget stops. Each explicit recenter is an intervention between trials; no teleport/reset occurs within a scored navigation trial. Frozen control uses the stricter unknown-response boundary guard.

[Readable per-case results](benchmark/REPORT.md) · [Complete JSON, trial failures and run paths](benchmark/results.json) · [Measured prediction comparison](benchmark/prediction_comparison.svg)

## Full camera-to-controller demo

Seed 42, generated frames through real ArUco tracking, reverse-one remapping: **4/4 baseline**, **0/4 frozen**, **4/4 adapted** target successes. Prediction error reduction **99.54%**.

Run: `/Users/athravseruwam/Documents/GitHub/darwin_robot/data/runs/20260919T213530.230366Z_b16f0c5496`.

Before forward/yaw RMSE: 0.00031802 m/s / 0.00220992 rad/s. Adapted: 0.00028459 m/s / 0.00270370 rad/s.

[Camera demo results](sim_42/results.json) · [Refit/evaluation/export command log](refit_evaluate_export.log) · [Replay state verified without a live transport](replay_verified.json)

## Browser evidence

Opened the actual local dashboard and clicked Start Calibration, Select Target on the canvas, Navigate, Recenter, Scramble, Recover, Navigate again, Export, Stop, Reset Model, Freeze & choose corners, all four image reference corners, Save calibration, and Hide marker/clear fault. Observed PROBING/READY/NAVIGATING/GOAL/RECOVERING/DISARMED/FAULT changes and real measured metrics. Calibration changed identity and invalidated the model. Exports created actual local ZIPs. Replay opened separately, played to final adapted metrics, and seek returned to the initial untrained observation; all live controls remained disabled.

The final build was additionally reloaded; an active calibration was stopped, reset, and started deliberately again. The controls continue to operate the runtime. Desktop and narrow app panels were observed; residual formatting/long path wrapping and invalid-pose display defects found during this browser test were fixed. No screenshot or animation supplies model data.

[Browser recovery screenshot](ui_recovery.png) · [Final build screenshot](ui_final.png) · [Final live state](ui_workflow.json)

## Data and safety evidence

Unique run directories preserve requested actions, observations, receipts/events, transitions, frame identities/timestamps, source/config/dependency metadata, public model checkpoints and separate privileged actuator audit. Whitelisted fitting reads only abstract actions and observed motion. Checkpoints are JSON, not executable pickle. Invalid/reset/calibration/cancellation-crossing transitions are rejected. Zero input yields zero actuator output and predicted propulsion. Rank-deficient action designs, motionless data, mismatched model/config/calibration and held-out overlap fail. Swept footprint checks supplement untrained central-area probe limits.

Replay constructs no live runtime/serial/camera/actuator. Its original-mode label and disconnected transport state remain explicit. Video recording is optional and was not enabled; replay reconstructs recorded poses and metrics, honestly labelled.

## Only physical checks remain

Confirm actual controller, TB6612FNG pins, power/common ground, motors and camera identity. Coordinate upload with motor power disconnected; then verify independent raised-wheel A/B pulses, STOP, unplug/watchdog and reconnect disarmed. Measure real direction/dead zone, footprint, probe travel, timing, coast/stationarity and stopping distance. Mount the marker/camera, calibrate at marker height, measure capture-age bounds and pose jitter, and test occlusion manually. Fill measured hardware configuration, collect independent real probes and held-out trials, then test slow target navigation and scramble/recovery. No simulated coefficient or result is represented as a robot measurement.

No physical camera or motor port was opened by this task; no board was flashed; no external publishing/push occurred. The prior WhisperBud project, recordings, environment and services were left untouched.

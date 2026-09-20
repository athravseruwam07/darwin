# Darwin

A two-wheel robot learns how two abstract commands move its body, then learns again after a hidden software remapping. **Software verified in simulation. Physical robot performance is unverified.** Native Mac CPU only; no cloud service, CUDA, neural network, or frontend build chain.

The default interactive demo renders an ArUco marker from differential-drive physics and measures motion with the actual OpenCV detector and homography. The ridge learner receives only requested actions and measured poses. It never reads hidden motor channels, mapping matrices, or plant truth. Simulation and hardware use the same runtime, model, controller, transition formation, supervisor, and web UI; camera and actuator adapters differ.

## Run on this Mac

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
source venv/bin/activate
python -m darwin.cli doctor
python -m darwin.cli demo --mode simulation --config configs/simulation.yaml --ui-port 8770
```

Open http://127.0.0.1:8770. If occupied, the CLI selects the next free port within 20 ports and prints the actual URL. It never stops the process using another port. The completed task leaves a simulation server running; see `STATUS.md` for its PID/log and URL.

A clean installation uses the verified native arm64 Python 3.11.9:

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 -m venv venv
venv/bin/python -m pip install -r requirements.resolved.txt
venv/bin/python -m pip install -e '.[dev]'
```

`requirements.resolved.txt` pins tested versions. Install only its one OpenCV distribution. DepthAI 3.10.0 is installed and import/API checked here; it is optional (`pip install -e '.[oak]'`). A physical OAK stream has not been tested. `doctor` opens no devices.

## Operator demo

1. **Start Calibration** collects 24 independent full-cycle trials and 12 separate held-out trials. Measured validation errors replace the dashes when fitting completes.
2. **Select Target**, then click inside the dashed safe arena. **Navigate** executes bounded pulses chosen by the learned forward model. The observed goal must persist for 500 ms.
3. Use **Recenter simulation** between comparison trials when desired. This is explicitly recorded as a manual intervention, never a navigation success.
4. **Scramble** stops first, preserves the old model, privately changes the actuator mapping, and inhibits navigation. **Recover** collects fresh data and compares frozen/adapted predictions on the same new held-out pulses.
5. Navigate again. **Export** creates a local ZIP under `reports/exports`. **Stop** cancels the episode; **Reset Model** discards learned state without moving the robot.

One tab owns an active episode; another tab cannot renew its lease. Refresh/close/background loss of heartbeat stops an active episode after the configured lease. The UI controls real runtime jobs. The canvas shows simulated generated frames honestly; the path and metrics come from recorded detections. This is explicit recalibration after a known change, not automatic damage detection or biological evolution.

Diagnostics inject actual marker loss, stale frames, disconnect, and boundary faults. Clearing a fault does not start motion. Recenter after the boundary diagnostic. Camera calibration freezes a frame, accepts four corners in TL/TR/BR/BL order plus measured dimensions, saves a homography, and invalidates the old model. Camera geometry in simulation stays fixed when changing the measurement calibration; wrong clicks produce wrong measurements, not a self-fulfilling render.

## Software-only verification

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
bash scripts/verify_without_hardware.sh
```

The script runs tests, doctor, marker generation, synthetic camera validation, fake firmware/PTY fault scenarios, the full rendered-camera demo, the 60-case benchmark, an actual HTTP server subprocess smoke test, and an Uno compile if the isolated toolchain is installed. It opens no physical camera or serial device and never flashes. Its temporary HTTP server is cleaned up. Logs and exact command/exit/duration records go to `reports/verification/`.

Individual commands:

```bash
venv/bin/python -m darwin.cli marker --id 7 --output reports/robot_marker.png
venv/bin/python -m darwin.cli simulate --seed 42 --output reports/sim_42
venv/bin/python -m darwin.cli benchmark --seeds 11,22,33,44,55 --output reports/benchmark
venv/bin/python -m darwin.cli vision-test --synthetic --output reports/vision
venv/bin/python -m darwin.cli protocol-test --fake
venv/bin/python -m pytest -q
bash firmware/compile.sh
```

Benchmark: five seeds × four changed maps × three plant variants = 60 recorded cases. Each includes four baseline, four frozen, and four adapted target/headings. Declared thresholds: 0.06 m radius, 500 ms observed dwell, 100 actions/45 synthetic seconds, at least 80% baseline/adapted goal success, and at least 80% reduction in normalized new-map held-out prediction error. Frozen trials use an extra conservative unknown-response travel guard. Failed/aborted trials remain in denominators. Explicit recentering occurs only between trials and before probe episodes. The benchmark uses noisy pose observations for speed; `simulate` and pixel integration tests cover actual vision. Final results and limitations are in `reports/EVIDENCE.md`.

## Refit, evaluate, export, replay

`reports/sample_run.txt` names the actual complete rendered-camera run used for the evidence. These commands work as written after verification:

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
RUN_PATH="$(cat reports/sample_run.txt)"
venv/bin/python -m darwin.cli fit --run "$RUN_PATH" --output checkpoints/refit_sample.json
venv/bin/python -m darwin.cli evaluate --run "$RUN_PATH" --checkpoint checkpoints/refit_sample.json
venv/bin/python -m darwin.cli export --run "$RUN_PATH" --output reports/export
venv/bin/python -m darwin.cli replay --run "$RUN_PATH" --ui-port 8771
```

Fit uses only the last complete `:train` episode; evaluation uses the separate last `:heldout` episode. Replaying reconstructs timestamped poses, target, path, and measured metrics. **REPLAY · SIMULATION/HARDWARE** labels the original mode. No transport/camera/actuator is instantiated. The timeline uses actual host recording times; fast offline simulation replays faster than synthetic physics time. Video was not recorded by default, so replay draws recorded poses and says so explicitly. Seek/play/pause/export work; live movement commands are unavailable.

Checkpoints are non-executable JSON containing feature/measurement versions, feature order, coefficients, normalization, regularization, public config/calibration IDs, fit metrics, and exact training action IDs. Incompatible loads and held-out/train overlap fail. No pickle is used.

## Measurement, model and safety details

Coordinates are meters, seconds, radians; x right, y up, heading counterclockwise. Live camera/control timestamps use host monotonic seconds. Synthetic physics uses a separately declared advancing monotonic clock. UTC names are for readability only.

The response model uses **full-cycle pulse-plus-settle displacement**, not pulse-only velocity: default 120 ms output followed by 300 ms stopped settling. Body displacement uses midpoint heading; velocity targets divide by the measured full-cycle duration. Planning multiplies model outputs by that same cycle length. Hardware waits for measured stationary observations before a new pulse; configured noise thresholds must be checked on the real marker. Excess duration error, uncertainty, nonfinite data, tracking loss, stale frame identity, calibration changes, intervention, or cancellation rejects the transition.

Features are `[u1,u2,1]`. Ridge uses `solve`, requires rank-three independent actions, reports conditioning and separate forward/yaw errors. Zero requested action predicts zero propulsion. Navigation also requires a useful response above the stationary baseline and held-out error below 70% of a zero-motion predictor in both outputs; a motionless/stalled robot cannot unlock navigation merely by having tiny training residuals. Baseline response minimums (.002 m/s and .02 rad/s), validation ceilings (.04 m/s and .4 rad/s), and geometry defaults are software starting gates, not physically validated tuning.

Controller scores a grid of abstract actions using only learned predictions, desired target motion, and swept arc/footprint boundaries. The simulator has wheel asymmetry, optional deadband/lag/process and sensor noise, independent seeds, command latency, delayed observations, frame loss, and a fake clock. The easy arena has no obstacles. The renderer alone sees plant truth. Physical outputs live exclusively in the actuator audit log.

Supervisor checks pose validity, bounded frame age, transport health, operator lease, action/time limits, calibration and footprint before pulses and continuously during hardware operation. STOP invalidates old generations before transport waits. Normal scheduled STOP is distinct from watchdog/ACK/reset faults. Reconnect stays disarmed, invalidates old models, and requires fresh observations. Firmware watchdog is independent of Python and browser life.

Run directories are unique and append-only. Essential-record queue overflow/disk errors fail closed; stop/fault flushes. Config/calibration/source SHA256/dependency metadata, requested actions, observations, full-cycle transitions, events, frames/timestamps, checkpoints and evaluations are recorded. The training loader has an explicit field whitelist. Export preserves raw logs, and privileged `actuator_audit.jsonl` remains separate. No source-control commit is claimed because this new project has not been initialized as a Git repository.

## Hardware handover — after team readiness

Do not copy synthetic learned coefficients into hardware or use the template geometry as measured values. No board was opened, flashed, or moved during this software task. Confirm controller/driver/wiring/power first, then coordinate the raised-wheel checks.

Firmware uses AIN1 D4, AIN2 D7, PWMA D5, BIN1 D8, BIN2 D9, PWMB D6, STBY D10. Review `firmware/REVIEW.md`; hardened source preserves the reference pin map/protocol. It was compiled for `arduino:avr:uno`. A RedBoard must actually be compatible before choosing that target. Toolchain and board packages are isolated in `firmware/toolchain/`.

1. Coordinate firmware upload with motor power disconnected. No upload command is automatically run.
2. Identify the actual serial port and verify handshake disarmed. The old pressure device is not assumed to be Darwin.
3. Authorize short independent A/B pulses with wheels raised, then verify STOP, host-loss timeout, reconnect disarmed, polarity, power stability and mechanical clearance.
4. Mount camera and marker. Read-only camera tests do not authorize motor movement. Calibrate reference points at the marker height. Moving/replacing the camera requires explicit recalibration; automatic physical movement detection is not claimed.
5. Measure camera age bound, pose noise, footprint, arena, maximum probe displacement, settling/coast, dead zone and timing. Fill a new `configs/hardware.local.yaml` from the example, including `measured_probe_bound_m` and `timestamp_bound_ms`, then set `hardware_confirmed: true` only after coordinated readiness checks.
6. Start hardware demo disarmed, explicitly Connect disarmed, inspect tracking, then deliberately Start Calibration. Observe one slow target before scramble/recovery. Record real held-out results and a backup video.

Exact adapter commands (replace uppercase placeholders with identified device/files):

```bash
venv/bin/python -m darwin.cli camera-test --backend oak
venv/bin/python -m darwin.cli camera-test --backend video --path ACTUAL_VIDEO
venv/bin/python -m darwin.cli camera-test --backend webcam --index 0
venv/bin/python -m darwin.cli calibrate --config configs/hardware.local.yaml --ui-port 8772
venv/bin/python -m darwin.cli motor-test --port /dev/cu.ACTUAL_CONTROLLER
# Only after explicit coordinated raised-wheel readiness:
venv/bin/python -m darwin.cli motor-test --port /dev/cu.ACTUAL_CONTROLLER --channel A --pwm 30 --pulse-ms 80 --raised-wheel-confirmed
venv/bin/python -m darwin.cli demo --mode hardware --config configs/hardware.local.yaml --ui-port 8770
```

`calibrate` starts the camera read-only and serves calibration UI without serial. Hardware UI Connect remains disarmed. Missing calibration/readiness/timing/probe bounds inhibit outputs. Receive-only cameras need a measured conservative capture-age bound; that bound is included in freshness checks. Recorded video can test detection but cannot authorize physical motion.

The project is isolated from `private_whisper_bud`: no files, environments, recordings or services there were modified; ports 8765/8766 were not used. Nothing was pushed, published or deployed externally.

# Darwin

Darwin is a two-wheel robot that learns the relationship between two abstract motor commands and camera-measured body motion. The same learner and controller run in simulation and on the Arduino robot. After a hidden actuator mutation—including swapping wheels or reversing either or both wheel directions—it detects persistent model mismatch, gathers a small active recovery dataset, refits, validates, and navigates again.

The learner never receives the hidden map, wheel truth, or simulator state. Everything is local, CPU-only, and cloud-free.

## Windows setup

Verified on Windows 11 x64 with PowerShell and Python 3.13:

```powershell
git clone https://github.com/athravseruwam07/darwin.git
cd darwin
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.resolved.txt
.\venv\Scripts\python.exe -m pip install -e ".[dev]"
.\venv\Scripts\python.exe -m darwin.cli doctor
```

Do not copy a virtual environment between computers.

## Simulation demo

```powershell
.\venv\Scripts\python.exe -m darwin.cli demo --mode simulation --config configs\simulation.yaml --ui-port 8770
```

Open the URL printed by the CLI. If 8770 is occupied, Darwin chooses the next free local port and prints it.

Demo flow:

1. Press **Start Calibration** to collect independent training and held-out camera observations, fit ridge regression, and show real validation error.
2. Press **Select Target**, click within the dashed safe box, then press **Navigate**.
3. Pick reverse left, reverse right, reverse both, swap wheels, weaken left, or **Random mashup**.
4. Press normal **Navigate**. While the robot is moving, press **Inject Mutation** whenever you want. The request is applied at the next safe boundary between motor pulses.
5. Darwin notices repeated camera-measured prediction mismatch, stops goal-directed motion, actively selects recovery experiments, validates the adapted model against the frozen model, and resumes toward the original target. The live reasoning panel narrates those recorded states and events.
6. **Full Adaptation Challenge** remains as a one-button convenience flow. **Draw Route** accepts two or more waypoints.

The dashboard shows mismatch score, action-space uncertainty, frozen/adapted motion ghosts, measured held-out errors, obstacle overlays, route, state machine, and immutable event trail. These are runtime values—not scripted animation.

## Hardware run on this computer

The local measured config is `configs\hardware.local.yaml`. It names COM5, the OAK camera, marker 7, the saved 1 m × 1 m calibration, 90 PWM ceiling, and a provisional 3 cm probe bound. That file is intentionally excluded from the portable ZIP because another computer may use different ports and calibration.

Start with the robot centered, the full taped square clear, the camera fixed, the USB cable restrained, and someone ready to lift the robot:

```powershell
.\venv\Scripts\python.exe -m darwin.cli doctor
.\venv\Scripts\python.exe -m darwin.cli camera-test --backend oak
.\venv\Scripts\python.exe -m darwin.cli demo --mode hardware --config configs\hardware.local.yaml --ui-port 8770
```

Open the printed local URL. The runtime starts disarmed. Press **Connect**, confirm tracking is stable, then deliberately press **Start Calibration**.

Do not run the adaptation challenge until a normal calibration and short navigation succeed in the current physical setup. A reversal can immediately make the stale controller turn the wrong way; the supervisor limits pulses and stops on tracking, boundary, lease, serial, and duration faults, but a human lift-stop is still mandatory.

Live mutation is currently disabled in `configs\hardware.local.yaml`. Leave it disabled until the raised-wheel polarity/STOP checks and the OAK disconnect gate are passed. Simulation enables it by default.

## New computer / hackathon setup

Copy `configs\hardware.example.yaml` to `configs\hardware.local.yaml`, then fill the actual serial port and a newly saved calibration. Never reuse this machine's COM name or camera calibration blindly.

```powershell
Copy-Item configs\hardware.example.yaml configs\hardware.local.yaml
.\venv\Scripts\python.exe -m darwin.cli doctor
.\venv\Scripts\python.exe -m darwin.cli motor-test --port COM_ACTUAL
.\venv\Scripts\python.exe -m darwin.cli calibrate --config configs\hardware.local.yaml --ui-port 8772
```

The first motor test performs a handshake and leaves the controller disarmed. Any moving pulse must be coordinated with the wheels raised:

```powershell
.\venv\Scripts\python.exe -m darwin.cli motor-test --port COM_ACTUAL --channel A --pwm 30 --pulse-ms 80 --raised-wheel-confirmed
.\venv\Scripts\python.exe -m darwin.cli motor-test --port COM_ACTUAL --channel B --pwm 30 --pulse-ms 80 --raised-wheel-confirmed
```

Confirm both wheel polarities, STOP, host-loss watchdog, reconnect-disarmed behavior, power stability, marker tracking, footprint, camera age/jitter, and stopping clearance before setting `hardware_confirmed: true`.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q
node --check src\darwin\web\static\app.js
.\venv\Scripts\python.exe -m darwin.cli vision-test --synthetic --output reports\vision
.\venv\Scripts\python.exe -m darwin.cli protocol-test --fake
.\venv\Scripts\python.exe -m darwin.cli simulate --seed 42 --output reports\sim_42
.\venv\Scripts\python.exe -m darwin.cli benchmark --observation pose --seeds 11,22,33 --variants linear,noisy,nonlinear --output reports\benchmark
```

The benchmark covers swap, reverse-left, reverse-right, reverse-both, and unequal-gain mutations across every requested seed and plant variant. Failures remain in the denominator. Synthetic vision uses generated pixels and the real ArUco detector; the benchmark uses pose observations for speed.

The full Windows verifier is:

```powershell
.\venv\Scripts\python.exe scripts\verify_without_hardware.py
```

## Architecture and safety

- Camera: OAK, webcam, video, or simulation-generated frames feed the same marker tracker.
- Model: small ridge regression over `[left command, right command, bias]`; separate held-out evaluation and JSON checkpoints.
- Change detection: normalized residual threshold with consecutive-evidence gating, so one noisy pulse does not trigger recovery.
- Live mutations: operator-owned requests are queued and applied only between pulses. STOP or a new episode clears the queue. Random mashups compose two or more seeded, reviewed maps and reject identity-like, nonfinite, rank-deficient, or amplifying results.
- Recovery: leverage-based experiment selection, bounded pulse count, frozen-versus-adapted validation, and per-run response signatures. Signatures are informational; they do not silently load an old model.
- Controller: learned-model candidate search with footprint/boundary checks; single-wheel pivots are excluded from normal motion.
- Obstacles: camera-derived circles/polygons are excluded from candidate swept paths. Keep detection disabled until the physical view is checked for false positives.
- Safety: local-only server, ownership lease, continuous pose/transport checks, hard action/time limits, cancellation, firmware watchdog, fail-closed logging, and disarmed reconnect.
- Evidence: append-only JSONL records observations, commands, transitions, events, checkpoints, evaluations, exports, and privileged actuator audit separately.

The hidden map lives only inside the simulator plant or hardware actuator. The learner and controller receive requested actions and observed motion only. Automatic recovery is designed for controlled software remaps; it is not a blanket claim that arbitrary mechanical damage can be diagnosed.

## Replay and export

```powershell
.\venv\Scripts\python.exe -m darwin.cli export --run data\runs\RUN_ID --output reports\exports
.\venv\Scripts\python.exe -m darwin.cli replay --run data\runs\RUN_ID --ui-port 8771
```

Replay is read-only and does not open a camera, serial port, or actuator. Source bundles exclude virtual environments, caches, credentials, local device paths, and generated run data.

Firmware pinout and protocol review are in `firmware\REVIEW.md`. Nothing auto-flashes the board.

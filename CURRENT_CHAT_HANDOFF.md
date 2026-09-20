# Darwin continuation handoff

Updated: 2026-09-19 (America/Toronto)

This file is the current handoff for continuing Darwin in a completely different chat. Read this file first, then `STATUS.md`, `README.md`, and `firmware/REVIEW.md` before operating hardware.

## Objective

Darwin is a two-wheel robot for Hack the North. An overhead camera observes an ArUco marker on the robot. The Mac sends two abstract motor commands, measures the resulting motion, learns the command-to-motion relationship, navigates to selected targets, and relearns after a hidden software remapping.

The learner must never see the hidden mapping or simulator truth. Simulation and hardware use the same runtime, learner, controller, safety state machine, logging, replay, evaluation, and dashboard. Only the camera and actuator adapters change.

## Project locations and preservation constraints

- Active project: `/Users/athravseruwam/Documents/GitHub/darwin_robot`
- Original handoff package: `/Users/athravseruwam/Downloads/DARWIN_SOFTWARE_HANDOFF`
- Original empty repository: `/Users/athravseruwam/Documents/GitHub/darwin`
- Preserve `/Users/athravseruwam/Documents/GitHub/private_whisper_bud`, including all uncommitted work, recordings, environments, and services.
- Do not push or publish unrelated work.
- Do not automatically flash a board or move a connected robot. Hardware work starts with coordinated, raised-wheel checks after readiness is confirmed.

No applicable `AGENTS.md` was found for `darwin_robot`. The project has not been initialized as a Git repository and no commit is claimed.

## Current physical assembly checkpoint

The team chose the original wired design using an **Arduino Uno R3** and a **TB6612FNG motor-driver breakout**. The ESP32/wireless idea was abandoned for now.

The user reports that all of the following wiring has been completed, but it has **not been independently inspected or electrically tested**:

| Arduino Uno R3 | Driver label visible on actual board | Purpose |
|---|---|---|
| 5V | VCC | Driver logic supply |
| GND | GND | Common ground |
| D4 | AI1 (equivalent to AIN1) | Motor A direction 1 |
| D7 | AI2 (equivalent to AIN2) | Motor A direction 2 |
| D5 | PWMA | Motor A PWM |
| D8 | BI1 (equivalent to BIN1) | Motor B direction 1 |
| D9 | BI2 (equivalent to BIN2) | Motor B direction 2 |
| D6 | PWMB | Motor B PWM |
| D10 | STBY | Driver standby/enable |

The actual red motor-driver breakout was shown in a photo. Its labels are:

- Left side, top to bottom: VM, VCC, GND, AO1, AO2, BO2, BO1, GND.
- Right side, top to bottom: PWMA, AI2, AI1, STBY, BI1, BI2, PWMB, GND.
- `AI1/AI2` are this breakout's abbreviations for `AIN1/AIN2`.
- `AO1/AO2` are motor outputs, not Arduino inputs.
- `BO2` is physically above `BO1` on this board.

The user reports these motor connections:

- Left motor red wire -> AO1; left motor black wire -> AO2.
- Right motor red wire -> BO1; right motor black wire -> BO2.
- Wire color is only an initial polarity convention. If a wheel direction is reversed, correct it after the raised-wheel test; Darwin can also learn the mapping.

The battery holder originally had a round DC barrel plug. The user cut off the plug and reports that the holder is connected to the driver:

- Holder positive -> driver VM.
- Holder negative -> common GND shared by driver and Arduino.
- The battery must never connect to Arduino 5V or driver VCC.
- The motor driver does not create motor power; it switches battery power to the motors.

Unknown and still requiring confirmation before inserting batteries:

- Number of AA cells in the holder.
- Battery chemistry and condition (alkaline versus rechargeable NiMH, etc.).
- Actual battery polarity as measured or traced; wire color alone is not proof.
- Motor rated voltage/current or kit specification.
- Whether the stripped battery leads are securely terminated with no loose strands.
- Full-board visual inspection of every wire.
- Adequate mechanical mounting and wheel clearance.

The battery holder should be secured low and near the robot's center, preferably on clear base-plate space. It must not sit directly on the Arduino or breadboard. Under-base mounting is acceptable only with adequate floor, wheel, and caster clearance. The motor-power disconnect must remain reachable.

## Exact present state and immediate next action

The conversation stopped immediately before firmware upload. The Arduino has not been flashed or tested by this software work. The next safe sequence is:

1. Keep every AA battery out of the holder. Keep the robot supported so both drive wheels are clear of the table.
2. Obtain a clear full-system photo and inspect VCC versus VM, common ground, all seven control wires, motor outputs, battery polarity/termination, shorts, and wheel clearance.
3. Confirm the holder cell count, battery chemistry, and motor voltage suitability.
4. Connect the Uno R3 to the Mac with a USB **data** cable while motor power remains absent.
5. Open `firmware/darwin_motor/darwin_motor.ino` in Arduino IDE.
6. Select `Arduino AVR Boards -> Arduino Uno` and the actual Uno serial port.
7. Verify/compile, then upload. Do not have Serial Monitor open when the Darwin Python process needs the port.
8. Verify the disarmed handshake with no motor battery connected.
9. Only after explicit team readiness, insert/connect motor batteries and perform very short A-only and B-only pulses with wheels raised. Verify physical STOP, watchdog timeout, unplug/lost-host behavior, and reconnect-disarmed behavior before any floor motion.

Do not skip directly to autonomous navigation. Do not run the motor-test pulse commands until the operator explicitly confirms raised wheels and readiness.

## Firmware

Source:

`/Users/athravseruwam/Documents/GitHub/darwin_robot/firmware/darwin_motor/darwin_motor.ino`

The firmware has already been compiled for `arduino:avr:uno` using the isolated toolchain:

- Flash: 3766 bytes (11%).
- SRAM: 294 bytes (14%), 1754 bytes free.
- Protocol: 115200 baud ASCII.
- PWM range: -90 to +90.
- TTL range: 20-250 ms.
- STBY is LOW at boot, STOP, parse failure, overflow, and timeout.
- Host normally schedules explicit STOP after a 120 ms pulse; 200 ms TTL is a backup watchdog.

Protocol summary:

- `HELLO` -> `DARWIN_FW 1`
- `ARM` -> `OK ARM`
- `STOP` -> `OK STOP`, disables outputs and disarms
- `M <seq> <A> <B> <ttl_ms>` -> `OK M <seq>` if valid and armed
- Watchdog expiry -> `EVENT TIMEOUT`, disables outputs and disarms

The firmware and host adapter were tested in software and with private pseudo-terminals, but no physical Uno has been flashed or electrically tested.

## Hardware commands to use in order

From the active project:

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
source venv/bin/activate
python -m darwin.cli doctor
```

After firmware upload and with motor power still disconnected, identify the actual Uno serial port. Do not assume a port from another project. The read-only/no-motion communication check is:

```bash
venv/bin/python -m darwin.cli motor-test --port /dev/cu.ACTUAL_CONTROLLER
```

Only after the team explicitly confirms that the wheels are raised, wiring and power have been inspected, and the motor battery is suitable, use short individual-channel tests:

```bash
venv/bin/python -m darwin.cli motor-test --port /dev/cu.ACTUAL_CONTROLLER --channel A --pwm 30 --pulse-ms 80 --raised-wheel-confirmed
venv/bin/python -m darwin.cli motor-test --port /dev/cu.ACTUAL_CONTROLLER --channel B --pwm 30 --pulse-ms 80 --raised-wheel-confirmed
```

Keep a physical motor-battery disconnect reachable. If the driver or wiring heats up, the Uno resets, a wheel moves unexpectedly, or STOP/watchdog fails, disconnect motor power immediately and diagnose before continuing.

## Camera and marker after motor bench checks

The overhead camera remains connected to the Mac and stationary above the arena. The robot carries the generated ArUco marker with its FRONT direction visible. Generate or inspect it with:

```bash
venv/bin/python -m darwin.cli marker --id 7 --output reports/robot_marker.png
```

Test the actual camera without enabling motors:

```bash
venv/bin/python -m darwin.cli camera-test --backend oak
# Alternatives:
venv/bin/python -m darwin.cli camera-test --backend webcam --index 0
venv/bin/python -m darwin.cli camera-test --backend video --path ACTUAL_VIDEO
```

Create `configs/hardware.local.yaml` from `configs/hardware.example.yaml`. The example intentionally cannot arm. Calibrate the actual arena at the marker's height:

```bash
venv/bin/python -m darwin.cli calibrate --config configs/hardware.local.yaml --ui-port 8772
```

The UI expects four reference corners in TL, TR, BR, BL order. Camera movement invalidates calibration. Recorded video can test detection but cannot authorize real motion.

Before enabling hardware operation, measure and enter the real serial port, calibration file, arena dimensions, robot footprint/radius, camera timestamp-age bound, marker jitter, stationary tolerances, maximum probe displacement, pulse timing, settling/coast behavior, dead zone, and stopping margin. Set `hardware_confirmed: true` only after the coordinated checks are complete.

Start hardware mode only after all gates above are satisfied:

```bash
venv/bin/python -m darwin.cli demo --mode hardware --config configs/hardware.local.yaml --ui-port 8770
```

The hardware UI starts disarmed. Connect remains disarmed. Deliberately start calibration only after tracking and safety state are valid. Learn a fresh physical model; never reuse simulation coefficients.

## Software status

All hardware-independent acceptance work is complete:

- Native arm64 Python 3.11.9 virtual environment at `venv/`.
- 147 pytest tests passing, zero failures.
- Complete verification script: nine commands pass, none skipped.
- 60 benchmark cases: baseline 240/240 goals, frozen after remap 0/240, adapted 240/240.
- Minimum adapted prediction-error reduction versus frozen model: 94.06%; mean 98.16%.
- Full rendered-camera seed 42: baseline 4/4, frozen 0/4, adapted 4/4.
- Synthetic marker tracking: 150/150 frames; position RMSE 0.946 mm; heading RMSE 0.003170 rad; occlusion correctly invalid.
- 13/13 fake firmware/serial PTY scenarios plus safety, concurrency, timeout, reconnect, and settling tests.
- UI controls, calibration, STOP, diagnostics, export, and replay exercised against the real local runtime.

Evidence:

- `STATUS.md`
- `reports/EVIDENCE.md`
- `reports/verification/summary.json`
- `reports/verification/commands.json`
- `reports/firmware_compile.log`
- `firmware/REVIEW.md`

Run all hardware-independent checks without opening a physical camera or serial device:

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
bash scripts/verify_without_hardware.sh
```

## Running simulation demo

At handoff time, the verified simulation demo is still running:

- URL: http://127.0.0.1:8770/
- Recorded PID: 14692
- Run ID: `20260919T213536.866189Z_2e06bbf670`
- Log: `/Users/athravseruwam/Documents/GitHub/darwin_robot/reports/demo.log`
- State at verification: GOAL, outputs stopped, learned model ready.

Check whether that PID/URL is still live rather than assuming. If it is not running:

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
venv/bin/python -m darwin.cli demo --mode simulation --config configs/simulation.yaml --ui-port 8770
```

The CLI chooses a nearby free port if 8770 is occupied and prints the actual URL. Detached launch is available with `venv/bin/python scripts/launch_demo.py`.

## Genuine hardware-dependent work remaining

1. Inspect the actual completed wiring and confirm battery/motor ratings and polarity.
2. Upload firmware to the actual Uno with motor power disconnected.
3. Confirm handshake, A/B polarity, STOP, watchdog, disconnect, reconnect-disarmed, power stability, and clearance with wheels raised.
4. Mount the camera and marker; calibrate the marker plane and heading.
5. Measure real camera age/jitter, footprint, arena, probe displacement, dead zone, settling/coast, timing, and stopping margin.
6. Populate a real hardware configuration and pass its readiness gates.
7. Collect fresh real training and held-out data, run slow navigation, then scramble/recovery trials while recording evidence and backup video.
8. Fix any issues exposed by physical commissioning and update `STATUS.md` and the evidence report with measured results only.

## Suggested first message in the new chat

Copy this into the new chat:

> Continue the Darwin project from `/Users/athravseruwam/Documents/GitHub/darwin_robot/CURRENT_CHAT_HANDOFF.md`. Read that entire file, then read `STATUS.md`, `README.md`, and `firmware/REVIEW.md` before acting. We are at the completed-but-unpowered Uno R3 + TB6612FNG wiring checkpoint. Do not assume the wiring is verified, do not flash or move the robot without coordinated readiness, and preserve `private_whisper_bud`. Help me inspect the full wiring and battery/motor ratings, then guide the firmware upload and raised-wheel commissioning step by step. Continue software work autonomously where safe.

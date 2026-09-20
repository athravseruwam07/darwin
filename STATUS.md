# Darwin status

**Software verified in simulation; hardware checks remain.**

## Running demo

- URL: http://127.0.0.1:8770
- PID: 14692
- Log: `/Users/athravseruwam/Documents/GitHub/darwin_robot/reports/demo.log`
- Run: `20260919T213536.866189Z_2e06bbf670`
- Mode: SIMULATION, generated camera frames → actual ArUco detection → learned model → bounded controller.
- Current state: GOAL after browser-operated recovery navigation; outputs stopped, model ready.
- No physical camera/serial device was opened or flashed.

## Verified

- 147 pytest tests pass, zero failures; two dependency deprecation warnings.
- Complete verification script: all 9 commands pass, none skipped.
- 60 recorded cases: baseline 240/240, frozen 0/240, adapted 240/240 targets; minimum prediction-error reduction 94.06%.
- Camera-loop seed 42: baseline 4/4, frozen 0/4, adapted 4/4.
- Synthetic vision 150/150; position RMSE 0.946 mm, yaw RMSE .003170 rad; occlusion invalid.
- 13/13 fake serial/PTY scenarios, plus hardware-runtime concurrency/freshness/reconnect tests.
- Actual Uno build: 3766 bytes flash, 294 bytes SRAM. Upload and electrical tests are unverified.
- Browser controls, four-corner calibration, active STOP, hidden-marker fault, export and replay exercised; visible metrics are measured.
- Recorded run refit, held-out evaluation, export and no-transport replay verified.

See [full evidence](reports/EVIDENCE.md), [exact command results](reports/verification/commands.json), and [README](README.md).

## Exact resume commands

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
venv/bin/python -m darwin.cli doctor
bash scripts/verify_without_hardware.sh
# Start only if the supplied demo is no longer running:
venv/bin/python -m darwin.cli demo --mode simulation --config configs/simulation.yaml --ui-port 8770
```

The CLI selects the next free local port if occupied, without stopping another service. Optional detached launch: `venv/bin/python scripts/launch_demo.py` (writes actual URL/PID to `reports/demo_process.json`).

## Hardware-dependent checks remaining

1. Confirm actual board/driver/pins, motor rating, independent power/common ground and clear raised wheels.
2. Coordinate upload; handshake-only, independent A/B pulses, STOP, lost-host watchdog, reconnect disarmed.
3. Mount/read actual camera and marker; calibrate reference plane and heading; measure jitter/capture-age bound and manual occlusion behavior.
4. Measure footprint, probe displacement bound, pulse timing, dead zone, settling/coast and safe stopping margin. Enter measured hardware YAML; readiness/timing/probe-bound gates remain closed in the template.
5. Collect fresh real training/held-out data; slow target tests, then comparable frozen/adapted hardware trials and backup recording.

No remaining software acceptance gate depends on obtaining hardware. Optional extensions such as automatic change detection, wireless control or obstacle navigation are outside this delivered scope. There are no background coding tasks or uncommitted edits in another project from this work. No Git push/publication was performed.

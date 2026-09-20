# Firmware and adapter evidence

Software verified only; no controller was opened, flashed, or moved. PTY devices were created by the tests themselves.

## Supplied firmware review

Original preserved at `darwin_motor/reference_original.ino.txt`; hardened source is `darwin_motor/darwin_motor.ino`.

Pin assignments unchanged: AIN1 4, AIN2 7, PWMA 5, BIN1 8, BIN2 9, PWMB 6, STBY 10. Protocol remains `DARWIN_FW 1`, HELLO/ARM/STOP/M, PWM ±90, TTL 20–250 ms. Host default uses PWM scale 60 and schedules explicit STOP after 120 ms; 200 ms TTL is fallback, not normal termination.

Fixed reference defects:

- Replaced `sscanf` integer conversion with strict token grammar and checked uint32 accumulation. Rejects signed sequence/TTL, overflow, PWM outside bounds, fractional numbers, extra/missing tokens and trailing spaces/garbage.
- Overflow and nonprintable input now discard the entire remaining line through newline. An `ARM` suffix can no longer survive overflow.
- Preserved CRLF handling (embedded CR inside commands now rejected), strictly increasing sequences within ARM, STBY low at boot/stop/error/timeout, a 32-byte input budget, and rollover-safe watchdog arithmetic.
- String literals use AVR flash storage through `F()`.

The host harness compiles and executes the *actual sketch source* with emulated GPIO/Serial/time. It verifies parser bounds, stale sequences, overflow suffixes, embedded NUL, timeout across millis rollover, and watchdog under input flood. It does not establish electrical operation or real-time target behavior.

## Actual Uno compilation

Executed successfully with Arduino CLI 1.5.2-rc.1 (fef6e48df), `arduino:avr@1.8.8`, AVR GCC `7.3.0-atmel3.6.1-arduino7`, FQBN **arduino:avr:uno**. Output: 3766 bytes flash (11%), 294 bytes SRAM (14%); 1754 bytes SRAM remain. Log: `reports/firmware_compile.log`. Artifacts: `firmware/build/darwin_motor.ino.hex` and `.elf`.

```bash
cd /Users/athravseruwam/Documents/GitHub/darwin_robot
bash firmware/compile.sh
venv/bin/python -m pytest -q tests/test_vision.py tests/test_serial.py tests/test_firmware.py
```

Compiler and board packages live entirely inside `firmware/toolchain/`; no global Arduino installation was modified. No upload command is in the verification script.

## Transport and lifecycle

The real pyserial adapter has exclusive port ownership, bounded read/write/ACK deadlines, boot wait plus explicit HELLO, exact sequence ACK matching, reset/timeout rejection, and fail-closed errors. Connect and reconnect leave firmware disarmed. Faults require reconnect before another ARM. STOP invalidates in-flight exchanges and clears queued bytes. The actuator generation check prevents an old action from issuing M after a concurrent STOP; a runtime callback runs before ARM, before M, and every ≤5 ms during pulse and settling.

Thirteen fake firmware/PTTY scenarios passed: startup disarmed, partial CRLF input, matching ACK, duplicate sequence, watchdog, overflow remainder discard, strict numerics/trailing garbage, pyserial handshake, pulse+STOP, invalid ACK, missing ACK, boot reset, disconnect. Twenty-six focused vision/serial/firmware tests passed after the final audit. Additional pytest cases exercise continuous safety callback, STOP during ARM, no delayed write, zero command under all five maps, normal explicit STOP, and fault latching. Premature watchdog events and reset events are inspected during pulses and before STOP clears input; they invalidate the sample even if STOP subsequently acknowledges. Normal scheduled pulse completion has a separate passing test; safety failures during settling invalidate that interval.

Firmware v1 intentionally has no cryptographic/session nonce. One local serial owner and no queued commands are enforced by this application; it is not an adversarial bus protocol. Receipt ACK time bounds parser acceptance, not physical motor onset.

## Camera evidence and limitations

OpenCV 5.0.0 generated/detected all 150 known-pose synthetic frames, covering 25 headings × 3 positions × 2 perspective calibrations. Position RMSE 0.000945799 m; max 0.001183768 m. Heading RMSE 0.003169721 rad; max 0.007286838 rad. Occlusion is invalid. Thresholds were max 0.004 m and 0.04 rad. This tests the actual detector/homography path, not a physical camera. Details: `reports/vision/results.json`.

Generated markers indicate FRONT along corner 0→1 (right edge direction). Calibration reference order TL, TR, BR, BL corresponds to world (0,h), (w,h), (w,0), (0,0). Reference corners must be at marker height; storing marker height does not secretly correct parallax. Camera movement invalidates calibration even if resolution remains unchanged; operator must recalibrate.

Webcam/video use latest-frame buffers. Repeated reads preserve frame identity and timestamp. End-of-file leaves an aging final frame, not a synthetic fresh frame. DepthAI **3.10.0** installed/imported on native arm64; Camera.requestOutput and createOutputQueue signatures inspected. Official example's `resize_mode` text differs from installed binding's `resizeMode`; implementation uses verified binding. Lazy OAK adapter import preserves core use without optional package. Queue size is 1/nonblocking.

Camera timestamps are explicitly **receive_only**, because no device clock alignment or capture-latency measurement is claimed. Hardware control must require a separately measured conservative timestamp bound. Actual OAK/webcam stream, frame-age bounds and mounting/marker-plane errors remain physical checks.

Sources checked: [DepthAI v3 camera example](https://docs.luxonis.com/software-v3/depthai/examples/camera/camera_multiple_outputs.md), [OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html), [pyserial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).

## Coordinated physical checks remaining

Confirm board/driver/pins and independent motor supply with common ground. With motor power disconnected, flash matching Uno/ATmega328P firmware through an operator-coordinated bench step. Verify no-motion handshake; then explicitly authorized raised-wheel A-only/B-only short pulses, STOP, host loss/TTL and reconnect disarmed. Confirm actual signs, power stability, PWM dead zone, timing/coast and stopping margin. Mount/read camera, calibrate at marker plane, measure noise and capture-age bound, manually test occlusion before floor motion. Hardware model must be learned anew from these measured observations.

# Darwin status — 2026-09-20

## Ready now

- Repository: `C:\Users\mohsi\Documents\Codex\2026-09-19\startup-prompt-for-a-different-computer\darwin`
- Windows 11 x64, PowerShell, local Python 3.13 venv.
- Simulation dashboard: <http://127.0.0.1:8773>
- Latest full suite after live-mutation integration: **182 passed, 2 platform skips, 0 failures**.
- JavaScript syntax check passes.
- The authoritative code remains local and unpushed.

## New adaptation demo

- Explicit hidden maps: reverse-left, reverse-right, reverse-both, swap, and unequal gain. Legacy `reverse_one` means reverse-left.
- Dashboard supports operator-selected mutation injection during active navigation plus a one-button **Full Adaptation Challenge**.
- Choices: reverse-left, reverse-right, reverse-both, swap, weaken-left, and seeded **Random mashup** of two or more reviewed factors.
- Requests require the active operator lease and apply only between motor pulses; STOP/new episodes discard queued changes.
- Residual change detector requires repeated normalized prediction failures; one noisy pulse is not enough.
- Automatic response: stop, preserve the frozen model, collect 12 leverage-selected recovery trials, evaluate on 6 separate held-out trials, then continue navigation.
- Dashboard displays change score, action-space uncertainty, frozen/adapted predictions, measured error table, adaptation phase, obstacles, and drawn routes.
- Model signatures are saved and compared within a run, but are informational only: old checkpoints are not silently reused and memory is not yet loaded across processes.

Browser-driven simulation proof used a hidden reverse-right mutation. The stale model produced normalized held-out RMSE **0.56852**; the adapted model produced **0.006506**, then reached the selected target with state `GOAL`. The UI workflow—not a direct internal call—selected the mutation and started the challenge.

The live-injection backend is covered across all six choices, including repeated queued requests, wrong-owner rejection, STOP queue clearing, random-map admissibility, recovery, and resumed goal completion. Physical live injection remains disabled by configuration pending the hardware gates below.

Browser verification also exercised the exact requested flow: normal navigation began, the operator injected **reverse both wheels** mid-run, mismatch rose to **1.529 / 0.250**, the UI showed `RECOVERING` and fresh experiment collection, frozen yaw RMSE measured **1.4635 rad/s**, adapted yaw RMSE fell to **0.0148 rad/s**, and the resumed controller reached `GOAL` at approximately `(0.705, 0.309)` m for target `(0.720, 0.280)` m.

## Software evidence

- 45-case benchmark: 3 seeds × 3 plant variants × 5 mappings; no workflow errors.
- Baseline navigation: **180/180**.
- Frozen post-change navigation: **5/180**.
- Adapted navigation: **180/180**.
- Minimum frozen-to-adapted prediction-error reduction: **89.95%**; mean: **97.73%**.
- Rendered-camera demo: baseline **4/4**, frozen **0/4**, adapted **4/4**; prediction reduction **99.55%**.
- Synthetic vision: **150/150** frames, position RMSE **0.946 mm**, heading RMSE **0.003170 rad**, occlusion invalidated correctly.
- Fake serial faults, runtime safety, replay/export, route navigation, obstacle geometry, and reversal semantics are covered by tests.

Detailed benchmark output is in `reports\wow_benchmark_reversals\results.json`; rendered-camera output is in `reports\wow_demo\results.json`; vision output is in `reports\wow_vision\results.json`.

## Physical evidence from this computer

This is not simulation-only anymore:

- OAK streamed real 640 × 480 frames and marker 7 was tracked through the calibrated 1 m × 1 m floor area.
- Saved calibration: marker plane 0.0635 m above the floor, heading offset −π/2.
- Arduino on COM5 exchanged hundreds of exact ACKed command sequences with roughly 3–7 ms ACK latency.
- Latest recorded hardware run `20260920T033929.733342Z_b9146e5034` contains 177 actions and 175 camera-measured transitions.
- One physical learned-navigation run succeeded in 10 actions / 5.795 s at **0.057101 m** final target distance.
- Firmware compiled for Uno at 3766 bytes flash / 294 bytes SRAM. The exact flashed-binary provenance is not recorded.

The previous hardware service on port 8770 is stopped. Its OAK stream logged an `X_LINK_ERROR`, reconnect warnings, and a native DepthAI crash trace. That failure is real and must be reproduced/fixed before calling the physical demo reliable.

## Required physical checks before the next moving run

1. Center the robot, clear the entire dashed/taped area, restrain USB cables, and assign one person to lift-stop it.
2. Repeat raised-wheel A-only and B-only pulses; record which physical wheel each channel drives and its forward polarity.
3. Verify physical STOP, host/USB loss watchdog, reconnect-disarmed behavior, battery stability, and no Arduino reset under load.
4. Measure camera latency/jitter, marker-pose jitter, footprint, PWM dead zone, settle/coast, stopping distance, and actual maximum probe displacement. Current 100 ms and 3 cm bounds are provisional config values, not proven metrology.
5. Reproduce OAK disconnect behavior and prove camera loss stops motor output.
6. Check physical obstacle detection for false positives on the black floor, red boundary tape, wires, shadows, and people before enabling it for motion.
7. Run a fresh normal calibration and short target first. Only then run one supervised reversal challenge.

`configs\hardware.local.yaml` is machine-specific and is excluded from the portable source ZIP. Use `configs\hardware.example.yaml` on another computer.

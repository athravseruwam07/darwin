# Firmware and adapter review

The firmware and host adapter are software-verified. COM5 has exchanged real ACKed commands and the robot has completed one camera-observed learned navigation, but the exact flashed-binary provenance and electrical watchdog behavior are not yet recorded.

## Source and pinout

The supplied source is preserved at `darwin_motor/reference_original.ino.txt`; hardened source is `darwin_motor/darwin_motor.ino`.

| Signal | Uno pin |
|---|---:|
| AIN1 | D4 |
| AIN2 | D7 |
| PWMA | D5 |
| BIN1 | D8 |
| BIN2 | D9 |
| PWMB | D6 |
| STBY | D10 |

Protocol v1 supports `HELLO`, `ARM`, `STOP`, and sequenced `M` commands. PWM is bounded to ±90 and TTL to 20–250 ms. STBY is low at boot, stop, parser error, or watchdog timeout.

The hardened parser rejects signed sequence/TTL fields, integer overflow, out-of-range PWM, fractions, missing/extra fields, trailing garbage, embedded nonprintable bytes, and stale sequence numbers. Overflow discards the rest of the line so an `ARM` suffix cannot survive. The watchdog remains rollover-safe and active during input floods.

## Compile and test evidence

Arduino CLI 1.5.2-rc.1, `arduino:avr@1.8.8`, AVR GCC `7.3.0-atmel3.6.1-arduino7`, FQBN `arduino:avr:uno`:

- Flash: 3766 bytes (11%)
- SRAM: 294 bytes (14%); 1754 bytes remain

The host harness compiles and executes the actual sketch source with emulated GPIO, serial, and time. It verifies parser bounds, stale sequences, overflow suffixes, embedded NUL, millis rollover, and watchdog under input flood. It does not prove electrical behavior.

```powershell
cd darwin
bash firmware/compile.sh
.\venv\Scripts\python.exe -m pytest -q tests\test_vision.py tests\test_serial.py tests\test_firmware.py
```

No verification command uploads firmware automatically.

## Host transport behavior

The pyserial adapter uses exclusive ownership, bounded read/write/ACK deadlines, explicit handshake, exact sequence matching, and fail-closed reset/timeout handling. Connect and reconnect leave firmware disarmed. STOP invalidates in-flight work and clears queued bytes. A generation check prevents a cancelled action from issuing a delayed motor command.

Thirteen fake-firmware scenarios pass: startup disarmed, partial CRLF, matching ACK, duplicate sequence, watchdog, overflow discard, strict numerics, handshake disarmed, pulse plus STOP, invalid ACK, missing ACK, reset, and disconnect.

Firmware v1 has no cryptographic session nonce. Safety assumes one local serial owner; it is not an adversarial bus protocol.

## Physical evidence and remaining gates

The real OAK streamed 640 × 480 marker frames and the Arduino ACKed hundreds of sequences at roughly 3–7 ms. A physical learned-navigation run succeeded at 0.057101 m final distance. The OAK later logged `X_LINK_ERROR`, reconnect warnings, and a native crash trace, so camera-loss reliability is not closed.

Before the next floor challenge:

1. Record the exact firmware binary flashed to the board.
2. Repeat raised-wheel A-only/B-only checks and record the physical wheel/polarity mapping.
3. Verify STOP, host/USB loss watchdog, reconnect-disarmed behavior, and power/reset stability.
4. Measure pose jitter, capture latency, PWM dead zone, probe travel, settle/coast, and stopping distance.
5. Reproduce the OAK disconnect and prove the runtime stops output.

Camera timestamps remain receive-only. The configured 100 ms timestamp and 3 cm probe bounds are provisional until measured evidence is saved.

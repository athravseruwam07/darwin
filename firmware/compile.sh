#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
firmware/toolchain/bin/arduino-cli --config-file firmware/toolchain/arduino-cli.yaml compile --fqbn arduino:avr:uno --output-dir firmware/build firmware/darwin_motor

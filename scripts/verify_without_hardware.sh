#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec venv/bin/python scripts/verify_without_hardware.py

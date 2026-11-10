#!/usr/bin/env bash
# Runs the Python tests (offline) and, if Rust is installed, the contract tests.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m unittest discover -s tests -t . -v 2>&1 | tail -n 60
if command -v cargo >/dev/null 2>&1; then (cd contract && cargo test 2>&1 | grep -E "^test |test result"); else echo "(cargo not found: skipping contract tests)"; fi

#!/usr/bin/env bash
# ScamBrake attack demo.
#   ./demo.sh          offline replay: recorded real testnet data + paper wallet. No keys, no network, same output every time.
#   ./demo.sh live     real signed transactions on NEAR testnet (needs the agent key from scripts/setup_testnet.py)
#   ./demo.sh live --on-warn approve    (also lets a human-approved warning go through)
set -euo pipefail
cd "$(dirname "$0")"
mode="${1:-replay}"
case "$mode" in
  replay) shift || true; exec python3 -m scambrake demo "$@" ;;
  live)   shift; exec python3 -m scambrake demo --live "$@" ;;
  *) echo "usage: ./demo.sh [replay|live] [--on-warn deny|approve|ask] [--log FILE]"; exit 2 ;;
esac

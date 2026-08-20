#!/bin/bash
# Start Local AI Control Center (backend + gateway + runtime).
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python cli/local_ai.py start

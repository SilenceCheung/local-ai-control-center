#!/bin/bash
# Stop the inference runtime (control backend and gateway stay up).
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python cli/local_ai.py stop

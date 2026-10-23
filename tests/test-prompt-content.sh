#!/usr/bin/env bash
# Exercise the complete prompt contract and fail-closed fallback helpers.
set -euo pipefail
TASK_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$TASK_ROOT/tests/test-prompt-library.py"
python3 "$TASK_ROOT/tests/test-gcp-ce-support.py"
python3 "$TASK_ROOT/scripts/validate-prompt-library.py"

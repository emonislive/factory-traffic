#!/usr/bin/env bash
# ==============================================================================
# Factory Traffic Management System - Scenario Demonstration Script
# Demonstrates Assessment Section 15 Scenarios 1 to 9
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export PYTHONPATH="${PROJECT_ROOT}/backend:${PYTHONPATH:-}"

if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v py &>/dev/null; then
    PYTHON_BIN="py"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    echo "Error: Python runtime not found in PATH." >&2
    exit 1
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/demo.py" "$@"

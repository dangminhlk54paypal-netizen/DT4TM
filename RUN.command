#!/bin/bash
# macOS double-click launcher: opens a Terminal window and runs RUN.py.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" RUN.py "$@"

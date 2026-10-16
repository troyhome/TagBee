#!/bin/bash
# Double-click to launch TagBee. First run sets itself up (needs internet once).
cd "$(dirname "$0")" || exit 1
export PYTHONIOENCODING=utf-8

if ! .venv.nosync/bin/python -c "import PySide6, mutagen" >/dev/null 2>&1; then
  echo "First-time setup (a few minutes - PySide6 is a big download)..."
  rm -rf .venv.nosync
  python3 -m venv .venv.nosync \
    && .venv.nosync/bin/python -m pip install --quiet --upgrade pip \
    && .venv.nosync/bin/python -m pip install --no-compile -r requirements.txt || {
      echo
      echo "Setup failed. Please send me the text above."
      rm -rf .venv.nosync
      read -p "Press Return to close"
      exit 1
    }
fi
exec .venv.nosync/bin/python tagbee.py "$@"

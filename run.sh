#!/usr/bin/env bash
# Start the PDF -> Confluence-ready Word converter.
# First run creates a virtualenv and installs dependencies; later runs just start.
set -euo pipefail

cd "$(dirname "$0")"
VENV=".venv"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if [ ! -d "$VENV" ]; then
  PY="$(find_python)" || {
    echo "Python 3.10 or newer is required. Install it with: brew install python@3.13" >&2
    exit 1
  }
  echo "Setting up (one time only) using $PY ..."
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet pymupdf python-docx pillow
  # Optional API backends. Only used when the matching key is set, and the app
  # still works without them, so a failure here is not fatal.
  "$VENV/bin/pip" install --quiet anthropic openai 2>/dev/null || true
  echo "Setup complete."
fi

exec "$VENV/bin/python" server.py "$@"

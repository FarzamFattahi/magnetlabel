#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up MagnetLabel for the first time..."
  python3 -m venv .venv
fi
if [ ! -f .venv/magnetlabel-ready.txt ]; then
  .venv/bin/python -m pip install -e .
  printf 'ready\n' > .venv/magnetlabel-ready.txt
fi
exec .venv/bin/python -m magnetlabel.cli "$@"

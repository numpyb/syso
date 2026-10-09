#!/bin/sh
# Launch syso from its venv regardless of where we're invoked from.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m syso
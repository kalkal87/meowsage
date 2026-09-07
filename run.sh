#!/usr/bin/env bash
# Convenience launcher: run the pet from the local venv.
set -euo pipefail
cd "$(dirname "$0")"
# No arguments means "run the pet for development": hold the terminal, so
# Ctrl-C works and tracebacks land on screen rather than in the log. Plain
# `meow` backgrounds itself instead; that's the installed-user path.
if [ $# -eq 0 ]; then
    exec .venv/bin/python -m meowsage --foreground
fi
exec .venv/bin/python -m meowsage "$@"

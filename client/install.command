#!/bin/bash
# Double-click to set up LuGroupLib for KiCad on this Mac (one time).
# Close KiCad first - it overwrites its own config when it exits.
#
# If double-clicking does nothing, make it executable once:
#     chmod +x install.command
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  python3 install.py "$@"
else
  echo
  echo "python3 was not found."
  echo "Install it with:  xcode-select --install"
  echo "or from https://www.python.org/downloads/"
  exit 1
fi

echo
read -r -p "Press Return to close."

#!/usr/bin/env bash
# agenttop — one-line install
# curl -fsSL https://raw.githubusercontent.com/vicarious11/agenttop/main/install.sh | bash
set -euo pipefail

echo ""
echo "  Installing agenttop..."
echo ""

if ! command -v python3 &>/dev/null; then
  echo "  Python 3 not found. Install it:"
  echo "    macOS:  brew install python@3.12"
  echo "    Linux:  sudo apt install python3 python3-pip"
  exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "  Python 3.10+ required (found $PY_VER)"
  exit 1
fi

if command -v pipx &>/dev/null; then
  pipx install agenttop 2>/dev/null || pipx upgrade agenttop
  echo "  Installed via pipx"
elif command -v pip3 &>/dev/null; then
  pip3 install --user agenttop
  echo "  Installed via pip"
else
  echo "  Neither pipx nor pip3 found."
  exit 1
fi

echo ""
echo "  Run:  agenttop          (terminal dashboard)"
echo "        agenttop web      (web dashboard)"
echo "        agenttop init     (configure LLM)"
echo ""

#!/usr/bin/env sh
# agenttop — setup script
#
# Usage:
#   ./setup.sh              # full setup (agenttop + Ollama + model)
#   ./setup.sh --no-ollama  # skip Ollama (use cloud provider instead)
#
# Supports: macOS, Linux. For Windows, use: pip install agenttop

set -e

OLLAMA_MODEL="gemma3:4b"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
SKIP_OLLAMA=false

for arg in "$@"; do
    case "$arg" in
        --no-ollama) SKIP_OLLAMA=true ;;
        --help|-h)
            echo "Usage: ./setup.sh [--no-ollama]"
            echo "  --no-ollama  Skip Ollama install (use cloud provider)"
            exit 0
            ;;
    esac
done

echo ""
echo "  agenttop setup"
echo "  =============="
echo ""

# ── Detect Python ──

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$version" ]; then
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [ "$major" -ge $MIN_PYTHON_MAJOR ] && [ "$minor" -ge $MIN_PYTHON_MINOR ]; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "  [error] Python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} not found"
    echo ""
    echo "  Install Python:"
    echo "    macOS:  brew install python@3.12"
    echo "    Linux:  sudo apt install python3.12  (or your distro's package)"
    echo "    Any:    https://www.python.org/downloads/"
    exit 1
fi
echo "  [ok] Python $version ($PYTHON_CMD)"

# ── Install agenttop via pipx (preferred) or pip ──

if command -v pipx >/dev/null 2>&1; then
    if pipx list 2>/dev/null | grep -q agenttop; then
        echo "  [ok] agenttop already installed (pipx)"
    else
        echo "  Installing agenttop via pipx..."
        pipx install agenttop
        echo "  [ok] agenttop installed (pipx)"
    fi
elif command -v uv >/dev/null 2>&1; then
    echo "  Installing agenttop via uv..."
    uv tool install agenttop
    echo "  [ok] agenttop installed (uv)"
else
    echo "  Installing agenttop via pip..."
    "$PYTHON_CMD" -m pip install --user --quiet agenttop
    echo "  [ok] agenttop installed (pip --user)"
    echo "  [tip] For better isolation, consider: pipx install agenttop"
fi

# ── Ollama setup (optional) ──

if [ "$SKIP_OLLAMA" = true ]; then
    echo ""
    echo "  Skipping Ollama. Configure a cloud provider:"
    echo "    export ANTHROPIC_API_KEY=sk-ant-..."
    echo "    agenttop web --provider anthropic --model claude-haiku-4-5-20251001"
    echo ""
    echo "  Setup complete!"
    exit 0
fi

# Install Ollama if missing
if ! command -v ollama >/dev/null 2>&1; then
    echo ""
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                echo "  Installing Ollama via Homebrew..."
                brew install --quiet ollama
            else
                echo "  [error] Ollama not found and Homebrew not available."
                echo "  Install manually: https://ollama.com/download"
                echo "  Or re-run with: ./setup.sh --no-ollama"
                exit 1
            fi
            ;;
        Linux)
            echo "  Installing Ollama..."
            echo "  Downloading installer from https://ollama.com/install.sh"
            echo "  (may require sudo)"
            OLLAMA_INSTALLER=$(mktemp /tmp/ollama-install-XXXXXX.sh)
            curl -fsSL https://ollama.com/install.sh -o "$OLLAMA_INSTALLER"
            echo "  Installer saved to $OLLAMA_INSTALLER — review before continuing if needed."
            sh "$OLLAMA_INSTALLER"
            rm -f "$OLLAMA_INSTALLER"
            ;;
        *)
            echo "  [error] Unsupported OS for automatic Ollama install."
            echo "  Install manually: https://ollama.com/download"
            echo "  Or re-run with: ./setup.sh --no-ollama"
            exit 1
            ;;
    esac
    echo "  [ok] Ollama installed"
else
    echo "  [ok] Ollama already installed"
fi

# Start server if needed
if ! curl -sf http://localhost:11434 >/dev/null 2>&1; then
    echo "  Starting Ollama server..."
    ollama serve >/dev/null 2>&1 &
    # Wait up to 10 seconds for server
    for i in $(seq 1 20); do
        if curl -sf http://localhost:11434 >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
fi

if ! curl -sf http://localhost:11434 >/dev/null 2>&1; then
    echo "  [warn] Could not start Ollama server automatically."
    echo "  Run 'ollama serve' manually, then 'agenttop web'."
    exit 0
fi

# Pull model if needed
if ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
    echo "  [ok] Model $OLLAMA_MODEL ready"
else
    echo "  Pulling $OLLAMA_MODEL (one-time download, ~3GB)..."
    ollama pull "$OLLAMA_MODEL"
    echo "  [ok] Model $OLLAMA_MODEL ready"
fi

echo ""
echo "  Setup complete! Launch with:"
echo ""
echo "    agenttop web"
echo ""

#!/usr/bin/env bash
# agenttop — one-command setup
#
# Clone and run:
#   git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh
#
# Options:
#   ./setup.sh              # full setup (venv + deps + Ollama + model)
#   ./setup.sh --no-ollama  # skip Ollama (use cloud LLM instead)
#
# What this does:
#   1. Finds or installs Python 3.10+
#   2. Creates a .venv inside this repo (no global pollution)
#   3. Installs agenttop + all deps into the venv
#   4. Optionally sets up Ollama for local AI analysis
#   5. Drops a one-line `run.sh` so you never think about venvs again

set -euo pipefail

OLLAMA_MODEL="gemma3:4b"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
SKIP_OLLAMA=false
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

for arg in "$@"; do
    case "$arg" in
        --no-ollama) SKIP_OLLAMA=true ;;
        --help|-h)
            echo "Usage: ./setup.sh [--no-ollama]"
            echo "  --no-ollama  Skip Ollama (use a cloud provider instead)"
            exit 0
            ;;
    esac
done

echo ""
echo "  ┌─────────────────────────┐"
echo "  │   agenttop setup        │"
echo "  └─────────────────────────┘"
echo ""

# ── Step 1: Find Python ≥ 3.10 ──

find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            ver=$("$cmd" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>/dev/null || true)
            if [ -n "$ver" ]; then
                major=$(echo "$ver" | cut -d. -f1)
                minor=$(echo "$ver" | cut -d. -f2)
                if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                    echo "$cmd"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

PYTHON_CMD=$(find_python) || true

if [ -z "$PYTHON_CMD" ]; then
    echo "  Python 3.10+ not found. Trying to install..."
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                brew install python@3.12
                PYTHON_CMD=$(find_python) || true
            fi
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip
                PYTHON_CMD=$(find_python) || true
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y python3 python3-pip
                PYTHON_CMD=$(find_python) || true
            fi
            ;;
    esac
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "  [error] Could not find or install Python 3.10+"
    echo ""
    echo "  Install manually:"
    echo "    macOS:  brew install python@3.12"
    echo "    Ubuntu: sudo apt install python3 python3-venv"
    echo "    Any:    https://www.python.org/downloads/"
    exit 1
fi

ver=$("$PYTHON_CMD" -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')")
echo "  [ok] Python $ver ($PYTHON_CMD)"

# ── Step 2: Create venv ──

if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python" ]; then
    echo "  [ok] venv already exists"
else
    echo "  Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
    echo "  [ok] venv created at .venv/"
fi

# Use the venv Python from here on
PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

# ── Step 3: Install deps ──

echo "  Installing dependencies..."
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet -e "$SCRIPT_DIR"
echo "  [ok] agenttop installed"

# ── Step 4: Create run.sh launcher ──

cat > "$SCRIPT_DIR/run.sh" << 'LAUNCHER'
#!/usr/bin/env bash
# Launch agenttop — auto-activates the venv, no thinking required
DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$DIR/src" exec "$DIR/.venv/bin/python" -m uvicorn agenttop.web.server:app --host 127.0.0.1 --port 8420 "$@"
LAUNCHER
chmod +x "$SCRIPT_DIR/run.sh"

# ── Step 5: Ollama (optional) ──

if [ "$SKIP_OLLAMA" = true ]; then
    echo ""
    echo "  Skipping Ollama. Set a cloud provider instead:"
    echo "    export ANTHROPIC_API_KEY=sk-ant-..."
    echo ""
    echo "  ┌─────────────────────────────────────┐"
    echo "  │  Done! Run:                         │"
    echo "  │    ./run.sh                          │"
    echo "  │    open http://localhost:8420         │"
    echo "  └─────────────────────────────────────┘"
    echo ""
    exit 0
fi

if ! command -v ollama >/dev/null 2>&1; then
    echo ""
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                echo "  Installing Ollama via Homebrew..."
                brew install --quiet ollama
            else
                echo "  [skip] Install Ollama manually: https://ollama.com/download"
                echo "  Or re-run with: ./setup.sh --no-ollama"
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
            echo "  [skip] Install Ollama manually: https://ollama.com/download"
            ;;
    esac
fi

if command -v ollama >/dev/null 2>&1; then
    echo "  [ok] Ollama installed"

    # Start server if not running
    if ! curl -sf http://localhost:11434 >/dev/null 2>&1; then
        echo "  Starting Ollama server..."
        ollama serve >/dev/null 2>&1 &
        for _ in $(seq 1 20); do
            curl -sf http://localhost:11434 >/dev/null 2>&1 && break
            sleep 0.5
        done
    fi

    # Pull model
    if curl -sf http://localhost:11434 >/dev/null 2>&1; then
        if ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
            echo "  [ok] Model $OLLAMA_MODEL ready"
        else
            echo "  Pulling $OLLAMA_MODEL (one-time, ~3GB)..."
            ollama pull "$OLLAMA_MODEL"
            echo "  [ok] Model $OLLAMA_MODEL ready"
        fi
    else
        echo "  [warn] Could not start Ollama server automatically."
        echo "  Run 'ollama serve' manually, then 'agenttop web'."
    fi
fi

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │  Done! Run:                         │"
echo "  │    ./run.sh                          │"
echo "  │    open http://localhost:8420         │"
echo "  └─────────────────────────────────────┘"
echo ""

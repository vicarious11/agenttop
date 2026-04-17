#!/usr/bin/env bash
# agenttop — one-line install
#
# Install only:
#   curl -fsSL https://raw.githubusercontent.com/vicarious11/agenttop/main/install.sh | bash
#
# Install + pick mode directly (skip menu):
#   curl -fsSL https://raw.githubusercontent.com/vicarious11/agenttop/main/install.sh | bash -s -- web-demo
#   Modes: web | web-demo | tui | tui-demo | none
set -euo pipefail

REPO="https://github.com/vicarious11/agenttop.git"
INSTALL_DIR="${AGENTTOP_HOME:-$HOME/.agenttop}"
SHIM_DIR="$HOME/.local/bin"
MODE="${1:-menu}"

echo ""
echo "  ┌─────────────────────────────┐"
echo "  │   agenttop installer        │"
echo "  └─────────────────────────────┘"
echo ""

# ── 1. Clone or update ──
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "  Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only --quiet || echo "  [warn] update failed, continuing with existing copy"
else
  echo "  Cloning to $INSTALL_DIR"
  git clone --quiet --depth 1 "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 2. Run setup (skip Ollama by default for a fast first run) ──
if [ ! -x "$INSTALL_DIR/.venv/bin/agenttop" ]; then
  bash setup.sh --no-ollama
else
  echo "  [ok] venv already set up"
fi

# ── 3. Create shim in ~/.local/bin so `agenttop` is on PATH ──
mkdir -p "$SHIM_DIR"
cat > "$SHIM_DIR/agenttop" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_DIR/.venv/bin/agenttop" "\$@"
EOF
chmod +x "$SHIM_DIR/agenttop"

PATH_HINT=""
if ! echo ":$PATH:" | grep -q ":$SHIM_DIR:"; then
  SHELL_RC="$HOME/.zshrc"
  [ -n "${BASH_VERSION:-}" ] && SHELL_RC="$HOME/.bashrc"
  PATH_HINT="  Add to PATH (one-time):
    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $SHELL_RC && source $SHELL_RC"
fi

echo ""
echo "  [ok] Installed to $INSTALL_DIR"
echo "  [ok] Command shim: $SHIM_DIR/agenttop"
[ -n "$PATH_HINT" ] && echo "" && echo "$PATH_HINT"
echo ""

# ── 4. Launch (arg-driven or interactive) ──
BIN="$INSTALL_DIR/.venv/bin/agenttop"

launch() {
  case "$1" in
    web)       echo "  Launching web dashboard (your data) on http://localhost:8420" ; exec "$BIN" web ;;
    web-demo)  echo "  Launching web dashboard (demo data) on http://localhost:8420" ; exec "$BIN" web --demo ;;
    tui)       echo "  Launching TUI (your data)"  ; exec "$BIN" ;;
    tui-demo)  echo "  Launching TUI (demo data)"  ; exec "$BIN" --demo ;;
    none|"")
      echo "  Done. Next, run one of:"
      echo "    agenttop web           # web dashboard — your data"
      echo "    agenttop web --demo    # web dashboard — demo data"
      echo "    agenttop               # TUI — your data"
      echo "    agenttop --demo        # TUI — demo data"
      exit 0
      ;;
    *)
      echo "  [warn] unknown mode '$1' — skipping launch"
      exit 0
      ;;
  esac
}

if [ "$MODE" != "menu" ]; then
  launch "$MODE"
fi

echo "  What do you want to launch now?"
echo "    1) Web dashboard  —  your data"
echo "    2) Web dashboard  —  demo data"
echo "    3) TUI            —  your data"
echo "    4) TUI            —  demo data"
echo "    5) Nothing, I'll run it later"
echo ""
# Read from terminal directly — stdin is the curl pipe when run via curl|bash
if [ -t 0 ] || [ -r /dev/tty ]; then
  read -rp "  Pick [1-5]: " CHOICE < /dev/tty || CHOICE=5
else
  CHOICE=5
fi

case "$CHOICE" in
  1) launch web ;;
  2) launch web-demo ;;
  3) launch tui ;;
  4) launch tui-demo ;;
  *) launch none ;;
esac

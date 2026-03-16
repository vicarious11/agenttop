#!/usr/bin/env python3
"""Cross-platform one-time setup for agenttop.

Works on Windows, macOS, and Linux. Requires Python 3.10+.

Usage:
    python3 install.py              # full setup (venv + deps + Ollama)
    python3 install.py --no-ollama  # skip Ollama (use cloud LLM instead)

After install, run:
    ./start          (macOS/Linux)
    start.bat        (Windows)
"""

import os
import platform
import shutil
import subprocess
import sys
import venv

MIN_PYTHON = (3, 10)
OLLAMA_MODEL = "gemma3:4b"
HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
IS_WINDOWS = platform.system() == "Windows"
SCRIPTS = "Scripts" if IS_WINDOWS else "bin"


def log(msg: str) -> None:
    print(f"  {msg}")


def log_ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def log_warn(msg: str) -> None:
    print(f"  [!!] {msg}")


def check_python() -> None:
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        print(f"\n  Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required (found {v.major}.{v.minor})")
        print("  Download: https://www.python.org/downloads/\n")
        sys.exit(1)
    log_ok(f"Python {v.major}.{v.minor}.{v.micro}")


def create_venv() -> None:
    pip = os.path.join(VENV_DIR, SCRIPTS, "pip")
    if os.path.exists(pip):
        log_ok("venv exists")
        return
    log("Creating virtual environment...")
    venv.create(VENV_DIR, with_pip=True)
    log_ok("venv created")


def install_package() -> None:
    pip = os.path.join(VENV_DIR, SCRIPTS, "pip")
    log("Installing agenttop (this takes ~30s)...")
    subprocess.run(
        [pip, "install", "--quiet", "--upgrade", "pip"],
        check=True, cwd=HERE,
    )
    subprocess.run(
        [pip, "install", "--quiet", "-e", "."],
        check=True, cwd=HERE,
    )
    log_ok("agenttop installed")


def create_launcher() -> None:
    agenttop_bin = os.path.join(VENV_DIR, SCRIPTS, "agenttop")

    if IS_WINDOWS:
        launcher = os.path.join(HERE, "start.bat")
        with open(launcher, "w") as f:
            f.write(f'@echo off\r\n"{agenttop_bin}" web %*\r\n')
        log_ok("created start.bat")
    else:
        launcher = os.path.join(HERE, "start")
        with open(launcher, "w") as f:
            f.write(f'#!/bin/sh\nexec "{agenttop_bin}" web "$@"\n')
        os.chmod(launcher, 0o755)
        log_ok("created ./start")


def setup_ollama() -> None:
    """One-time Ollama setup: install binary, start server, pull model."""
    system = platform.system()

    # Step 1: Check if Ollama is already installed
    ollama = shutil.which("ollama")
    if ollama:
        log_ok(f"Ollama found at {ollama}")
    else:
        log("Ollama not found. Installing...")
        if system == "Darwin":
            if shutil.which("brew"):
                try:
                    subprocess.run(["brew", "install", "ollama"], check=True, timeout=120)
                    ollama = shutil.which("ollama")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    pass
            if not ollama:
                log_warn("Install Ollama manually: https://ollama.com/download")
                return
        elif system == "Linux":
            try:
                import tempfile
                fd, path = tempfile.mkstemp(suffix=".sh", prefix="ollama-")
                os.close(fd)
                subprocess.run(
                    ["curl", "-fsSL", "https://ollama.com/install.sh", "-o", path],
                    check=True, timeout=60,
                )
                log("Running Ollama installer (may ask for sudo)...")
                subprocess.run(["sh", path], check=True, timeout=120)
                os.unlink(path)
                ollama = shutil.which("ollama")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                pass
            if not ollama:
                log_warn("Install Ollama manually: curl -fsSL https://ollama.com/install.sh | sh")
                return
        elif system == "Windows":
            log_warn("Download Ollama from: https://ollama.com/download/windows")
            log("  After installing, re-run: python install.py")
            return
        else:
            log_warn(f"Install Ollama manually for {system}: https://ollama.com/download")
            return

        if ollama:
            log_ok("Ollama installed")

    # Step 2: Start server if not running
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        server_running = True
    except Exception:
        server_running = False

    if not server_running:
        log("Starting Ollama server...")
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import time
        for _ in range(20):
            time.sleep(0.5)
            try:
                urllib.request.urlopen("http://localhost:11434", timeout=1)
                server_running = True
                break
            except Exception:
                pass

    if not server_running:
        log_warn("Could not start Ollama. Run 'ollama serve' manually.")
        return

    log_ok("Ollama server running")

    # Step 3: Pull model if not already pulled
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/show",
            data=f'{{"name":"{OLLAMA_MODEL}"}}'.encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        log_ok(f"Model {OLLAMA_MODEL} ready")
        return
    except Exception:
        pass

    log(f"Pulling {OLLAMA_MODEL} (one-time, ~3GB)...")
    try:
        subprocess.run([ollama, "pull", OLLAMA_MODEL], check=True, timeout=600)
        log_ok(f"Model {OLLAMA_MODEL} ready")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log_warn(f"Failed to pull model. Run: ollama pull {OLLAMA_MODEL}")


def main() -> None:
    skip_ollama = "--no-ollama" in sys.argv

    print()
    print("  agenttop setup")
    print("  ──────────────")
    print()

    check_python()
    create_venv()
    install_package()
    create_launcher()

    if not skip_ollama:
        print()
        setup_ollama()

    # Done
    print()
    print("  ──────────────────────────────────────")
    if IS_WINDOWS:
        print("  Done! Run:  start.bat")
    else:
        print("  Done! Run:  ./start")
    print("  Opens:      http://localhost:8420")
    print("  ──────────────────────────────────────")
    print()


if __name__ == "__main__":
    main()

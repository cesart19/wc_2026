#!/usr/bin/env python3
"""
dev.py — Uvicorn watchdog for development.

Starts uvicorn with --reload and periodically health-checks it.
If the worker dies silently (supervisor alive but not responding),
kills the whole uvicorn process and restarts it cleanly.

Usage:
    cd backend
    source venv/bin/activate
    python dev.py
"""

import os
import signal
import subprocess
import sys
import time

import httpx

PORT = 8000
HEALTH_URL = f"http://localhost:{PORT}/health"
CHECK_INTERVAL = 15   # seconds between health checks
FAIL_THRESHOLD = 3    # consecutive failures before hard restart
STARTUP_GRACE = 5     # seconds to wait after (re)start before checking

_proc: subprocess.Popen | None = None


def _start() -> None:
    global _proc
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app",
           "--reload", "--port", str(PORT)]
    _proc = subprocess.Popen(cmd)
    print(f"[watchdog] started uvicorn  PID={_proc.pid}", flush=True)
    time.sleep(STARTUP_GRACE)


def _stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def _healthy() -> bool:
    try:
        return httpx.get(HEALTH_URL, timeout=3).status_code == 200
    except Exception:
        return False


def _shutdown(signum, frame):
    print("\n[watchdog] shutting down…", flush=True)
    _stop()
    sys.exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# Change into the backend directory so uvicorn finds app.main
os.chdir(os.path.dirname(os.path.abspath(__file__)))

_start()
failures = 0

while True:
    time.sleep(CHECK_INTERVAL)

    if _proc.poll() is not None:
        print(f"[watchdog] uvicorn exited (code {_proc.returncode}) — restarting", flush=True)
        _start()
        failures = 0
        continue

    if _healthy():
        failures = 0
    else:
        failures += 1
        print(f"[watchdog] health check failed ({failures}/{FAIL_THRESHOLD})", flush=True)
        if failures >= FAIL_THRESHOLD:
            print("[watchdog] worker unresponsive — hard restart", flush=True)
            _stop()
            _start()
            failures = 0

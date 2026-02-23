"""
entrypoint.py — Azure App Service container entrypoint.

Azure App Service requires every container to expose an HTTP endpoint and
respond 200 OK to health probes, even when the container is not a web app.
This module satisfies that requirement while running the APScheduler daemon.

Architecture
------------
┌─────────────────────────────────────────────────────────┐
│  Python process (PID 1 in container)                    │
│                                                         │
│  Main thread ──── scheduler.main() (BlockingScheduler)  │
│       │            Fires every Monday 06:00 London      │
│       │            Registers SIGTERM → graceful exit    │
│       │                                                 │
│  Daemon thread ── HTTPServer on 0.0.0.0:$PORT           │
│                   GET /health → 200 {"status":"healthy"} │
│                   Dies automatically when main exits    │
└─────────────────────────────────────────────────────────┘

Design decisions
----------------
- Health server runs as a *daemon* thread so it never blocks process exit.
- scheduler.main() runs on the *main* thread because Python only allows
  signal.signal() calls from the main thread — the SIGTERM handler that
  gracefully shuts down APScheduler must live there.
- No third-party HTTP framework is needed; http.server from the standard
  library is sufficient for a single-route health check.
- $PORT is honoured so App Service can dynamically assign ports.
"""

import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Logging — minimal bootstrap before scheduler.main() sets up the full logger
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("entrypoint")

# ---------------------------------------------------------------------------
# Health-check HTTP handler
# ---------------------------------------------------------------------------
_HEALTH_PATHS = frozenset(("/", "/health", "/healthz", "/ping"))
_HEALTH_BODY = b'{"status":"healthy","service":"board-report-generator"}'


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler — returns 200 OK on health-check paths."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path in _HEALTH_PATHS:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_HEALTH_BODY)))
            self.end_headers()
            self.wfile.write(_HEALTH_BODY)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        # Suppress noisy HTTP access logs; APScheduler has its own structured logging.
        pass


def _start_health_server(port: int) -> None:
    """Start the HTTP health-check server (runs forever in a daemon thread).

    Args:
        port: TCP port to listen on (usually $PORT from App Service).
    """
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info("Health server listening on 0.0.0.0:%d  [GET /health → 200 OK]", port)
    server.serve_forever()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Start health server thread, then run the APScheduler daemon.

    Execution order:
    1. Resolve $PORT (App Service sets this; default 8000).
    2. Start _HealthHandler in a daemon thread (returns immediately).
    3. Import scheduler and call scheduler.main() on the main thread.
       - scheduler.main() registers SIGTERM → graceful APScheduler shutdown.
       - scheduler.main() blocks inside BlockingScheduler.start().
    4. On SIGTERM (container stop / App Service restart):
       - Scheduler shuts down cleanly (wait=False).
       - sys.exit(0) terminates the main thread.
       - Daemon health thread is automatically killed.
    """
    port = int(os.environ.get("PORT", 8000))

    # ── Step 1: Health server on daemon background thread ──────────────────
    health_thread = threading.Thread(
        target=_start_health_server,
        args=(port,),
        name="health-server",
        daemon=True,  # killed automatically when main thread exits
    )
    health_thread.start()

    # ── Step 2: Scheduler on main thread ───────────────────────────────────
    # Import deferred so the health server is already accepting connections
    # by the time heavy imports (pandas, matplotlib, etc.) are loaded.
    logger.info("Starting APScheduler daemon (importing pipeline modules…)")
    try:
        from scheduler import main as run_scheduler  # noqa: PLC0415
    except ImportError as exc:
        logger.critical("Cannot import scheduler module: %s", exc)
        sys.exit(1)

    run_scheduler()  # blocks until SIGTERM / SIGINT


if __name__ == "__main__":
    main()

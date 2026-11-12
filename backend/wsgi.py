#!/usr/bin/env python3
"""
Vote Without Doubt - Production/Staging WSGI Entry Point
Phase E.16.1 Application-Serving Hardening

Standard WSGI module for production application servers (e.g., Gunicorn or Waitress)
behind a reverse proxy (e.g., Nginx).

Usage examples:
  Linux staging / production (Single process, multi-threaded):
    gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 wsgi:app

  Cross-platform / local staging rehearsal (Waitress multi-threaded):
    python wsgi.py

Process Model Architecture:
  The VWD backend incorporates stateful background workers (RelayerDispatcher and
  ElectionLifecycleWorker) that coordinate blockchain batching and automated key
  provisioning. To ensure optimal performance and eliminate lock contention, a single
  master process with multi-threading is the authoritative configuration.
  If multi-process WSGI execution is utilized, `PersistentElectionLock` automatically
  enforces distributed mutual exclusion across processes.
"""

import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

# Resolve environment configuration: defaults to 'production' if not explicitly set
env_name = os.getenv('FLASK_ENV') or os.getenv('APP_ENV', 'production')

app = create_app(env_name)


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '5000'))

    try:
        from waitress import serve
        print(f"Starting production WSGI server (Waitress) on http://{host}:{port}")
        serve(app, host=host, port=port)
    except ImportError:
        print(f"Starting development fallback server on http://{host}:{port}")
        app.run(host=host, port=port)

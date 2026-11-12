#!/usr/bin/env python3
"""
Vote Without Doubt - Backend Entry Point

Development server defaults are safe by default:

* binds ``127.0.0.1`` only, so the development server is not exposed on the
  network;
* debug and the reloader are OFF unless ``FLASK_DEBUG=true`` is set explicitly,
  and the factory refuses to run in debug mode when ``APP_ENV=production``;
* host and port are overridable through ``HOST`` / ``PORT``.

For real deployments use a WSGI server behind TLS, not this module.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

app = create_app()


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '5000'))
    debug = bool(app.config.get('FLASK_DEBUG', False))

    if debug:
        print('WARNING: running with the Flask debugger enabled. '
              'Never do this on a reachable host.', file=sys.stderr)

    app.run(host=host, port=port, debug=debug)
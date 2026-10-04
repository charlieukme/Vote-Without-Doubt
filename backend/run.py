#!/usr/bin/env python3
"""
Vote Without Doubt - Backend Entry Point
"""

import os
import sys

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=app.config.get('FLASK_DEBUG', True))
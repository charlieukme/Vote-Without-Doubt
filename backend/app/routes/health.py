"""
Health Check Route
"""

from flask import Blueprint, jsonify
from datetime import datetime

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    Returns basic application status
    """
    return jsonify({
        'status': 'ok',
        'message': 'Vote Without Doubt backend is running',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'service': 'backend',
        'phase': 'Phase 1 - Backend Foundation'
    }), 200

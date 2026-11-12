"""
Health Check Routes - Phase 1
Vote Without Doubt - Backend

``GET /api/health``       liveness - the process is up and serving.
``GET /api/health/ready`  readiness - the process can reach its database.

The phase/build label is read from configuration instead of being hard-coded, so
the response cannot claim a stale phase. ``PROJECT_PHASE_LABEL`` defaults to the
current authoritative phase recorded in PROJECT_BIBLE Section 3.
"""

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..extensions import db

health_bp = Blueprint('health', __name__)

DEFAULT_PHASE_LABEL = 'Operational'


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@health_bp.route('/health', methods=['GET'])
def health_check():
    """Liveness check. Deliberately does not touch the database."""
    return jsonify({
        'status': 'ok',
        'message': 'Vote Without Doubt backend is running',
        'timestamp': _now_iso(),
        'service': 'backend',
        'environment': current_app.config.get('APP_ENV', 'unknown'),
        'phase': current_app.config.get('PROJECT_PHASE_LABEL', DEFAULT_PHASE_LABEL),
    }), 200


@health_bp.route('/health/ready', methods=['GET'])
def readiness_check():
    """Readiness check. Reports database reachability and runtime relayer configuration."""
    payload = {
        'status': 'ok',
        'service': 'backend',
        'timestamp': _now_iso(),
        'checks': {'database': 'ok'},
        'runtime_config': {
            'contract_address': current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS'),
            'relayer_account': current_app.config.get('RELAYER_ACCOUNT'),
            'rpc_url': current_app.config.get('BLOCKCHAIN_RPC_URL'),
        },
    }
    try:
        db.session.execute(text('SELECT 1'))
    except Exception as error:
        db.session.rollback()
        app = current_app._get_current_object()
        app.logger.error('Readiness check failed: %s', error)
        payload['status'] = 'degraded'
        payload['checks']['database'] = 'unavailable'
        return jsonify(payload), 503

    # Inspect relayer runtime state
    try:
        from app.relayer.relayer import Relayer
        from web3 import Web3
        relayer = Relayer()
        w3 = relayer.get_web3()
        if w3.is_connected():
            payload['checks']['blockchain'] = 'connected'
            contract_addr = relayer.contract_address
            if contract_addr:
                c = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=relayer._abi)
                onchain_relayer = c.functions.relayer().call()
                payload['checks']['contract_verified'] = True
                payload['checks']['onchain_relayer'] = onchain_relayer
                expected_relayer = current_app.config.get('RELAYER_ACCOUNT')
                payload['checks']['relayer_authorized'] = bool(
                    expected_relayer and onchain_relayer.lower() == expected_relayer.lower()
                )
            else:
                payload['checks']['contract_verified'] = False
                payload['checks']['relayer_error'] = 'NO_CONTRACT_ADDRESS'
        else:
            payload['checks']['blockchain'] = 'disconnected'
    except Exception as exc:
        payload['checks']['blockchain_error'] = str(exc)

    return jsonify(payload), 200
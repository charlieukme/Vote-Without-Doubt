"""
Tests for FIX 1B: Independent Merkle Root Authority Verification
Vote Without Doubt - Backend Test Suite
"""

import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import AuditEvent, BallotRecord, Election, User
from app.security.password import hash_password
from app.services.verification_service import VerificationService
from app.services.voting_service import VotingService


@pytest.fixture
def election_with_audit(db):
    election = Election(
        election_id='101',
        title='Audit Authority Test Election',
        description='Test election for audit chain and Merkle root authority',
        status='CLOSED',
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() - timedelta(hours=1),
    )
    db.session.add(election)
    db.session.commit()
    return election


def test_audit_chain_endpoint_returns_valid_schema(client, election_with_audit):
    """Test that public /verification/<election_id>/audit-chain returns required verification fields."""
    logger = AuditLogger()
    logger.log(
        event_type='ELECTION_MERKLE_ROOT_FINALIZED',
        metadata={
            'election_id': election_with_audit.election_id,
            'merkle_root': '0xabcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
            'leaf_count': 10,
        },
    )

    res = client.get(f'/api/verification/{election_with_audit.election_id}/audit-chain')
    assert res.status_code == 200
    data = res.get_json()

    assert data['election_id'] == str(election_with_audit.election_id)
    assert 'events' in data
    assert isinstance(data['events'], list)
    assert 'contract_address' in data
    assert 'rpc_url' in data
    assert data['chain_id'] == 1337

    # Verify event structure
    for ev in data['events']:
        assert 'id' in ev
        assert 'event_type' in ev
        assert 'created_at' in ev
        assert 'metadata' in ev
        assert 'current_hash' in ev


def test_finalization_event_preserves_unredacted_merkle_root(db, election_with_audit):
    """Test that ELECTION_MERKLE_ROOT_FINALIZED preserves merkle_root unredacted in SAFE_METADATA_KEYS."""
    test_root = '0x11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff'
    logger = AuditLogger()
    event = logger.log(
        event_type='ELECTION_MERKLE_ROOT_FINALIZED',
        metadata={
            'election_id': election_with_audit.election_id,
            'merkle_root': test_root,
            'leaf_count': 5,
        },
    )

    db_event = AuditEvent.query.get(event.id)
    assert db_event.event_metadata is not None
    assert db_event.event_metadata.get('merkle_root') == test_root
    assert db_event.event_metadata.get('merkle_root') != '[REDACTED]'


def test_audit_chain_recomputation_from_genesis(db, election_with_audit):
    """Test that AuditLogger chain verification passes from genesis up to head."""
    logger = AuditLogger()
    logger.log(
        event_type='ELECTION_MERKLE_ROOT_FINALIZED',
        metadata={
            'election_id': election_with_audit.election_id,
            'merkle_root': '0x4444444444444444444444444444444444444444444444444444444444444444',
            'leaf_count': 1,
        },
    )

    chain_valid = logger.verify_chain()
    assert chain_valid is True

    chain_export = VerificationService.get_audit_chain_for_verification(election_with_audit.election_id)
    assert 'events' in chain_export
    assert len(chain_export['events']) > 0


def test_historical_hmac_receipt_verification_path(client, db):
    """Test that historical HMAC receipts verify successfully through the legacy path."""
    election = Election(
        election_id='202',
        title='Historical Election',
        description='Historical election with HMAC receipts',
        status='CLOSED',
        start_time=datetime.utcnow() - timedelta(days=10),
        end_time=datetime.utcnow() - timedelta(days=9),
    )
    user = User(
        username='hist_voter',
        email='hist_voter@college.test',
        password_hash=hash_password('test-password-123'),
        is_active=True,
        is_verified=True,
    )
    db.session.add_all([election, user])
    db.session.commit()

    ballot = BallotRecord(
        election_id=election.id,
        pseudonym='a' * 64,
        candidate=0,
        state='FINALIZED',
        sequence=1,
        block_number=100,
        tx_hash='0x' + 'b' * 64,
        is_null=False,
        superseded=False,
    )
    db.session.add(ballot)
    db.session.commit()

    receipt_data = VotingService.generate_receipt(ballot, user.id)
    receipt_code = receipt_data['receipt_code']

    res = client.get(f'/api/verification/receipt/{receipt_code}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'VALID'
    assert data['hmac_verified'] is True
    assert data['receipt_code'] == receipt_code


def test_tampered_audit_chain_detected_and_rejected(db, election_with_audit):
    """Test that tampering an audit event record is detected and fails closed."""
    logger = AuditLogger()
    event = logger.log(
        event_type='ELECTION_MERKLE_ROOT_FINALIZED',
        metadata={'election_id': election_with_audit.election_id, 'merkle_root': '0x' + '1' * 64},
    )

    # Corrupt event metadata in the database directly
    event.current_hash = 'badhash0000000000000000000000000000000000000000000000000000000000'
    db.session.commit()

    result = VerificationService.verify_audit_anchor(election_with_audit.election_id)
    assert result['verification_status'] == 'FAILED'
    assert result['chain_intact'] is False

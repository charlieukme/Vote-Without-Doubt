"""
Test audit foundation - Phase 1
Hash-chained audit logging foundation
"""

import pytest
from app.audit.audit import AuditEvent, AuditLogger, audit_logger


def test_audit_event_creation():
    """Test audit event creation"""
    event = AuditEvent(event_type='test.event', metadata={'action': 'test'})
    assert event.event_type == 'test.event'
    assert event.current_hash is not None
    assert len(event.current_hash) == 64  # SHA-256 hex


def test_audit_event_sanitizes_sensitive_data():
    """Test audit event redacts sensitive data"""
    event = AuditEvent(
        event_type='auth.attempt',
        metadata={
            'username': 'testuser',
            'password': 'secret123',  # Should be redacted
            'otp': '123456',  # Should be redacted
            'action': 'login'
        }
    )
    sanitized = event._sanitize_metadata(event.metadata)
    assert sanitized['username'] == 'testuser'
    assert sanitized['password'] == '[REDACTED]'
    assert sanitized['otp'] == '[REDACTED]'
    assert sanitized['action'] == 'login'


def test_audit_logger_log():
    """Test audit logger logs events"""
    logger = AuditLogger()
    event = logger.log('system.start', {'phase': 'Phase 1'})
    assert event.event_type == 'system.start'
    assert len(logger.events) == 1


def test_audit_chain_integrity():
    """Test hash chain verification"""
    logger = AuditLogger()
    logger.log('event1', {'data': '1'})
    logger.log('event2', {'data': '2'})
    logger.log('event3', {'data': '3'})
    assert logger.verify_chain() is True
    assert len(logger.get_chain()) == 3


def test_audit_chain_first_event_no_previous_hash():
    """Test first event in chain has no previous hash"""
    logger = AuditLogger()
    logger.log('first', {})
    assert logger.events[0].previous_hash is None
    assert logger.verify_chain() is True


def test_audit_does_not_log_sensitive_secrets():
    """Test audit never stores sensitive candidate choices or private keys"""
    event = AuditEvent(
        event_type='vote.submission',
        metadata={
            'candidate_choice': 'candidate_123',
            'private_key': 'fake_key',
            'ballot_id': 'B001'  # OK to log non-sensitive
        }
    )
    sanitized = event.to_dict()
    assert sanitized['metadata']['candidate_choice'] == '[REDACTED]'
    assert sanitized['metadata']['private_key'] == '[REDACTED]'
    assert sanitized['metadata']['ballot_id'] == 'B001'

"""
Audit Foundation - Phase 1
Vote Without Doubt - Backend

This is the foundation for hash-chained audit logging.
Full implementation (hash chaining, blockchain anchoring) in later phases.

Privacy-Conscious: Never log passwords, OTPs, private keys, candidate choices,
face images, or sensitive auth secrets.
"""

import hashlib
import json
from datetime import datetime
from typing import Dict, Any, Optional


class AuditEvent:
    """
    Base audit event structure for hash-chained audit foundation
    """
    def __init__(self, 
                 event_type: str,
                 metadata: Dict[str, Any] = None,
                 previous_hash: Optional[str] = None):
        self.event_id = None  # Will be set by persistence layer later
        self.event_type = event_type
        self.timestamp = datetime.utcnow()
        self.metadata = metadata or {}
        self.previous_hash = previous_hash
        self.current_hash = None
        self.compute_hash()
    
    def compute_hash(self) -> str:
        """Compute hash of event data for chain integrity"""
        event_data = {
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat() + 'Z',
            'metadata': self._sanitize_metadata(self.metadata),
            'previous_hash': self.previous_hash
        }
        data_str = json.dumps(event_data, sort_keys=True)
        self.current_hash = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
        return self.current_hash
    
    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize metadata to prevent logging sensitive data
        Privacy rule: Never log passwords, OTPs, private keys, candidate choices,
        raw pseudonyms, face data, or auth tokens
        """
        # Sensitive keys to exclude
        sensitive_keys = {
            'password', 'passwd', 'pass',
            'otp', 'otp_code', 'one_time_password',
            'private_key', 'secret_key', 'api_key', 'token',
            'session_id', 'auth_token',
            'candidate_choice', 'candidate_id_selected',
            'pseudonym_raw', 'face_image', 'face_embedding_raw',
            'biometric_data'
        }
        
        sanitized = {}
        for key, value in metadata.items():
            key_lower = str(key).lower()
            if key_lower in sensitive_keys:
                # Redact sensitive values
                sanitized[key] = '[REDACTED]'
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_metadata(value)
            else:
                sanitized[key] = value
        return sanitized
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat() + 'Z',
            'metadata': self._sanitize_metadata(self.metadata),
            'previous_hash': self.previous_hash,
            'current_hash': self.current_hash
        }


class AuditLogger:
    """
    Audit logger foundation for Phase 1
    Full hash chain + persistence in later phases
    """
    def __init__(self):
        self.events = []  # In-memory for foundation; DB persistence later
    
    def log(self, event_type: str, metadata: Dict[str, Any] = None) -> AuditEvent:
        """
        Log an audit event
        """
        previous_hash = self.events[-1].current_hash if self.events else None
        event = AuditEvent(
            event_type=event_type,
            metadata=metadata,
            previous_hash=previous_hash
        )
        self.events.append(event)
        return event
    
    def get_chain(self) -> list:
        """Get audit chain (foundation)"""
        return [e.to_dict() for e in self.events]
    
    def verify_chain(self) -> bool:
        """Verify hash chain integrity (foundation)"""
        for i, event in enumerate(self.events):
            if i == 0:
                # First event should have previous_hash None
                if event.previous_hash is not None:
                    return False
            else:
                if event.previous_hash != self.events[i-1].current_hash:
                    return False
            # Recompute hash
            expected = AuditEvent(
                event_type=event.event_type,
                metadata=event.metadata,
                previous_hash=event.previous_hash
            )
            expected.timestamp = event.timestamp
            if expected.current_hash != event.current_hash:
                return False
        return True


# Global audit logger instance (foundation)
audit_logger = AuditLogger()

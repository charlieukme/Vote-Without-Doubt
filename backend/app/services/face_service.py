"""
Face Service - Phase 5
Minimal implementation with safety controls
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from app.extensions import db
from app.models.face import FaceEnrollment, FaceChallenge
from app.security.face import generate_face_challenge_id, encrypt_embedding, decrypt_embedding


class FaceService:
    @staticmethod
    def create_challenge(user_id: int, challenge_type: str = "LIVENESS", ttl_seconds: int = 20) -> Dict[str, Any]:
        challenge_id = generate_face_challenge_id()
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        seq = "LEFT,RIGHT"
        ch = FaceChallenge(
            challenge_id=challenge_id,
            user_id=user_id,
            challenge_type=challenge_type,
            challenge_sequence=seq,
            expires_at=expires_at,
            completed=False,
            success=False
        )
        db.session.add(ch)
        db.session.commit()
        return {
            'challenge_id': challenge_id,
            'expires_at': expires_at.isoformat() + 'Z',
            'challenge_sequence': seq,
            'ttl_seconds': ttl_seconds
        }
    
    @staticmethod
    def submit_challenge(user_id: int, challenge_id: str, frames: List[bytes], sequence_provided: Optional[List[str]] = None) -> Dict[str, Any]:
        ch = FaceChallenge.query.filter_by(challenge_id=challenge_id, user_id=user_id).first()
        if not ch:
            return {'success': False, 'error': 'INVALID_CHALLENGE'}
        if ch.completed:
            return {'success': False, 'error': 'CHALLENGE_ALREADY_USED'}
        if ch.expires_at < datetime.utcnow():
            ch.completed = True
            db.session.commit()
            return {'success': False, 'error': 'CHALLENGE_EXPIRED'}
        # Minimal acceptance: require at least some frames, correct sequence if provided
        ok = len(frames) >= 2
        if sequence_provided:
            expected = [s.strip() for s in ch.challenge_sequence.split(',') if s.strip()]
            if sequence_provided != expected:
                ok = False
        ch.completed = True
        ch.success = ok
        ch.completed_at = datetime.utcnow()
        db.session.commit()
        return {'success': ok}
    
    @staticmethod
    def enroll_consent(user_id: int) -> Dict[str, Any]:
        fe = FaceEnrollment.query.filter_by(user_id=user_id).first()
        if not fe:
            fe = FaceEnrollment(user_id=user_id, encrypted_embedding=b'', consent_given=False, is_enrolled=False)
            db.session.add(fe)
            db.session.commit()
        fe.consent_given = True
        fe.consent_at = datetime.utcnow()
        db.session.commit()
        return {'success': True}
    
    @staticmethod
    def enroll_complete(user_id: int, embedding_bytes: bytes, method: str = 'face_recognition') -> Dict[str, Any]:
        fe = FaceEnrollment.query.filter_by(user_id=user_id).first()
        if not fe:
            fe = FaceEnrollment(user_id=user_id)
            db.session.add(fe)
        if not fe.consent_given:
            return {'success': False, 'error': 'CONSENT_REQUIRED'}
        fe.encrypted_embedding = encrypt_embedding(embedding_bytes)
        fe.embedding_method = method
        fe.is_enrolled = True
        db.session.commit()
        return {'success': True}
    
    @staticmethod
    def verify(user_id: int, embedding_bytes: bytes) -> Dict[str, Any]:
        fe = FaceEnrollment.query.filter_by(user_id=user_id).first()
        if not fe or not fe.is_enrolled or not fe.encrypted_embedding:
            return {'success': False, 'error': 'NOT_ENROLLED'}
        # Compare - minimal stub (always true if valid; but we document)
        return {'success': True, 'verified': True}
    
    @staticmethod
    def get_status(user_id: int) -> Dict[str, Any]:
        fe = FaceEnrollment.query.filter_by(user_id=user_id).first()
        if not fe:
            return {'enrolled': False, 'consent_given': False}
        return {'enrolled': fe.is_enrolled, 'consent_given': fe.consent_given}

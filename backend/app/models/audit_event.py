"""
Audit event ORM model - Phase 1 (remediated)
Vote Without Doubt - Backend

The ORM mapping for the existing ``audit_events`` table. The class body lives
in :mod:`app.audit.audit` next to the hashing code so that the canonical hash
payload and the persistence mapping cannot drift apart; this module re-exports
it under the conventional ``app.models`` location.

No column is added, removed or renamed relative to ``schema.sql``:
``id``, ``event_type``, ``metadata``, ``previous_hash``, ``current_hash``,
``created_at``.
"""

from app.audit.audit import AuditEvent

__all__ = ['AuditEvent']
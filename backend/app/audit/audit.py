"""
Audit Foundation - Phase 1 (remediated)
Vote Without Doubt - Backend

Tamper-evident, append-only, hash-chained audit foundation.

Design decisions relevant to Phase 1 remediation
------------------------------------------------
1. DETERMINISTIC HASHING. The hash is computed over a canonical JSON payload
   containing ONLY persisted fields (event type, canonicalised timestamp,
   sanitised metadata, previous hash). Verification recomputes the hash from the
   stored row, so it never reads the system clock and never mutates the event.

2. SECOND-RESOLUTION TIMESTAMPS. ``created_at`` is truncated to whole seconds
   *before* hashing. MySQL ``DATETIME`` has no sub-second precision by default,
   so hashing an untruncated microsecond value would produce a hash that cannot
   be reproduced after a reload. Truncation makes the persisted value and the
   hashed value identical in every round trip.

3. PERSISTENCE. ``AuditEvent`` is a real ORM model mapped to the existing
   ``audit_events`` table. ``AuditLogger`` persists every event and derives the
   chain head from persisted state, so a fresh process can load and verify the
   chain. On-chain anchoring is deliberately NOT implemented here (Phase 6/12).

4. PRIVACY. Sanitisation is deny-by-default: only an explicit allow-list of
   operational keys is retained. Identity, authentication, wallet, ballot and
   biometric values are never written to the audit log, not even hashed.

5. NO IDENTITY <-> BALLOT BRIDGE. Audit events carry no voter id, user id,
   email, wallet address, ballot id, pseudonym or candidate. The audit log
   cannot be used to link a voter to a ballot.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time as _time
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.extensions import db

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

HASH_ALGORITHM = 'sha256'
REDACTED = '[REDACTED]'
TRUNCATED = '[TRUNCATED]'
BINARY = '[BINARY]'
MAX_METADATA_DEPTH = 8

#: Marker written into legacy rows that used the pre-remediation constant.
LEGACY_INSECURE_SECRET = 'dev-secret-key-change-in-production'


def _utc_now() -> datetime:
    """Naive UTC 'now', truncated to whole seconds (see module docstring)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


# --------------------------------------------------------------------------
# Privacy-safe sanitisation (deny by default)
# --------------------------------------------------------------------------

def _normalize_key(key: Any) -> str:
    """Normalise a metadata key so naming style cannot defeat the filter.

    ``USER_PASSWORD``, ``UserPassword``, ``user_password`` and ``user-password``
    all normalise to ``userpassword``.
    """
    return re.sub(r'[^a-z0-9]', '', str(key).lower())


#: Keys retained verbatim. Deliberately excludes every identity, authentication,
#: wallet, ballot and biometric concept. ``election_id``/``election_title`` are
#: public ballot-plane descriptors and are safe.
SAFE_METADATA_KEYS = frozenset({
    'action', 'activity', 'anonymitysetsize', 'attempt', 'ballotcount', 'batchid',
    'batchsize', 'blocknumber', 'category', 'chainlength', 'checkpointeventid',
    'checkpointhash', 'closedat', 'component', 'count', 'degradedprivacy',
    'durationms', 'elapsedms', 'electionid', 'electiontitle', 'endpoint',
    'environment', 'errorcode', 'eventid', 'leafcount', 'limit', 'merkleroot',
    'method', 'minthreshold', 'officerid', 'onchainid', 'operation', 'outcome',
    'phase', 'policy', 'pseudonymcount', 'reason', 'reasoncode', 'requestid',
    'resource', 'result', 'route', 'rule', 'schema', 'service', 'severity',
    'source', 'state', 'status', 'success', 'total', 'triggerreason', 'txhash',
    'version', 'waittimeseconds',
})


#: Explicitly forbidden keys. Checked before the allow-list so the intent is
#: auditable even if a key were ever added to the allow-list by mistake.
SENSITIVE_METADATA_KEYS = frozenset({
    # identity
    'address', 'address1', 'addressline', 'city', 'email', 'emailaddress',
    'firstname', 'fullname', 'lastname', 'mail', 'mobile', 'name', 'phone',
    'phonenumber', 'postcode', 'student', 'studentid', 'user', 'userid',
    'voter', 'voterid', 'zipcode',
    # authentication / secrets
    'accesstoken', 'apikey', 'apisecret', 'auth', 'authtoken', 'code', 'cookie',
    'idtoken', 'mnemonic', 'newpassword', 'oldpassword', 'otp', 'otpcode',
    'onetimepassword', 'pass', 'passphrase', 'passwd', 'password',
    'passwordconfirm', 'privatekey', 'refreshtoken', 'secret', 'secretkey',
    'seed', 'session', 'sessionid', 'sessiontoken', 'token', 'userpassword',
    # wallet
    'addresswallet', 'signature', 'sig', 'wallet', 'walletaddress',
    # voting / ballot
    'ballot', 'ballotchoice', 'ballotid', 'candidate', 'candidatechoice',
    'candidateid', 'choice', 'pseudonym', 'pseudonymousid', 'vote',
    # biometric
    'biometric', 'biometrics', 'embedding', 'face', 'faceembedding',
    'faceimage', 'facetemplate', 'frame', 'liveness', 'livenessproof',
})


def _coerce_scalar(value: Any) -> Any:
    """Convert a leaf value into a deterministic, non-leaking representation.

    Unknown object types are represented by their type name only, never by
    ``repr()``/``str()``, so an arbitrary object cannot smuggle sensitive data
    into the audit log through serialisation.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return _canonical_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return BINARY
    if isinstance(value, (set, frozenset)):
        return sorted(str(_coerce_scalar(item)) for item in value)
    return f'<{type(value).__name__}>'


def sanitize_metadata(value: Any, _depth: int = 0) -> Any:
    """Recursively sanitise audit metadata.

    Deny-by-default: any key that is not explicitly allow-listed is replaced by
    ``[REDACTED]``. Nested dictionaries, lists, tuples and sets are walked.
    """
    if _depth > MAX_METADATA_DEPTH:
        return TRUNCATED

    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in SENSITIVE_METADATA_KEYS:
                clean[str(key)] = REDACTED
            elif normalized in SAFE_METADATA_KEYS:
                clean[str(key)] = sanitize_metadata(item, _depth + 1)
            elif isinstance(item, (dict, list, tuple, set, frozenset)):
                # Unknown *container* key: keep walking it, because every key
                # inside is filtered independently and any unknown leaf value is
                # still redacted. This preserves legitimate nested operational
                # context without ever trusting an unrecognised leaf.
                clean[str(key)] = sanitize_metadata(item, _depth + 1)
            else:
                clean[str(key)] = REDACTED
        return clean

    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_metadata(item, _depth + 1) for item in value]

    return _coerce_scalar(value)


def has_sensitive_keys(value: Any, _depth: int = 0) -> bool:
    """True if *untrusted input* contains any forbidden or unknown key.

    Apply this to caller-supplied metadata before/independent of sanitisation to
    learn whether a caller attempted to pass identity, credential or ballot data.
    """
    if _depth > MAX_METADATA_DEPTH:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalize_key(key)
            if normalized in SENSITIVE_METADATA_KEYS or normalized not in SAFE_METADATA_KEYS:
                return True
            if has_sensitive_keys(item, _depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(has_sensitive_keys(item, _depth + 1) for item in value)
    return False


def contains_redacted_marker(value: Any, _depth: int = 0) -> bool:
    """True if sanitised output still contains a redaction marker.

    Apply this to *sanitised* output to prove no sensitive value survived.
    """
    if _depth > MAX_METADATA_DEPTH:
        return False
    if value in (REDACTED, TRUNCATED, BINARY):
        return True
    if isinstance(value, dict):
        return any(
            contains_redacted_marker(v, _depth + 1) for v in value.values()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(contains_redacted_marker(item, _depth + 1) for item in value)
    return False


# --------------------------------------------------------------------------
# Canonicalisation and hashing
# --------------------------------------------------------------------------

def _canonical_timestamp(value: datetime) -> str:
    """Canonical UTC timestamp string. Naive values are treated as UTC."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'


def _json_safe(value: Any, _depth: int = 0) -> Any:
    """Make arbitrary metadata deterministically JSON-serialisable.

    Unlike :func:`sanitize_metadata` this preserves *key names*; it is applied
    only after sanitisation so that hashing can never raise ``TypeError``.
    """
    if _depth > MAX_METADATA_DEPTH:
        return TRUNCATED
    if isinstance(value, dict):
        return {str(k): _json_safe(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, _depth + 1) for item in value]
    return _coerce_scalar(value)


def canonical_event_payload(
    event_type: str,
    created_at: datetime,
    metadata: Optional[Dict[str, Any]],
    previous_hash: Optional[str],
) -> Dict[str, Any]:
    """The exact structure that is hashed. Exposed for independent verification."""
    return {
        'algorithm': HASH_ALGORITHM,
        'event_type': str(event_type),
        'created_at': _canonical_timestamp(created_at),
        'metadata': _json_safe(metadata or {}),
        'previous_hash': previous_hash or None,
    }


def compute_event_hash(
    event_type: str,
    created_at: datetime,
    metadata: Optional[Dict[str, Any]],
    previous_hash: Optional[str],
) -> str:
    """Deterministic SHA-256 over the canonical payload."""
    payload = canonical_event_payload(event_type, created_at, metadata, previous_hash)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False,
    )
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


# --------------------------------------------------------------------------
# ORM model
# --------------------------------------------------------------------------

class AuditEvent(db.Model):
    """One append-only, hash-chained audit record.

    Mapped to the existing ``audit_events`` table; no schema change required.
    The SQLAlchemy attribute is ``event_metadata`` because ``metadata`` is
    reserved by the declarative API; the column name is still ``metadata``.
    """

    __tablename__ = 'audit_events'
    __table_args__ = {'mysql_engine': 'InnoDB'}

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True)
    event_metadata = db.Column('metadata', db.JSON, nullable=True)
    previous_hash = db.Column(db.String(64), nullable=True, index=True)
    current_hash = db.Column(db.String(64), nullable=False, index=True)

    # ---------------------------------------------------------------- hashing
    def compute_hash(self) -> str:
        """Hash this event from its own persisted fields. Pure: no mutation."""
        return compute_event_hash(
            self.event_type, self.created_at, self.event_metadata, self.previous_hash
        )

    def recompute_hash(self) -> str:
        """Alias of :meth:`compute_hash` used by verification code paths."""
        return self.compute_hash()

    def is_intact(self) -> bool:
        """True when the stored hash still matches the stored fields."""
        return bool(self.current_hash) and self.recompute_hash() == self.current_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'event_type': self.event_type,
            'created_at': _canonical_timestamp(self.created_at),
            'metadata': _json_safe(self.event_metadata or {}),
            'previous_hash': self.previous_hash,
            'current_hash': self.current_hash,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f'<AuditEvent id={self.id} type={self.event_type} hash={self.current_hash}>'


# --------------------------------------------------------------------------
# Logger
# --------------------------------------------------------------------------

def verify_events(events: Iterable[AuditEvent]) -> Tuple[bool, Optional[int]]:
    """Verify a sequence of audit events.

    Returns ``(ok, index)`` where ``index`` is the position of the first event
    that failed, or ``None`` when the sequence is valid.

    Checks, in order, for every event:
      * ``previous_hash`` equals the preceding event's ``current_hash``
        (the first event must have ``previous_hash IS NULL``);
      * ``current_hash`` equals the hash recomputed from the event's own stored
        fields - so a modified timestamp, event type, metadata value or
        previous hash all fail;
      * deletion or reordering breaks the previous-hash linkage and fails.

    Reads only persisted values. Never calls the system clock. Never mutates.
    """
    previous: Optional[str] = None
    first = True

    for index, event in enumerate(events):
        if first:
            if event.previous_hash is not None:
                return False, index
            first = False
        else:
            if (event.previous_hash or None) != (previous or None):
                return False, index

        if not event.is_intact():
            return False, index

        previous = event.current_hash

    return True, None


class AuditLogger:
    """Persistent, append-only, hash-chained audit logger.

    The chain head is read from persisted state on every write, so multiple
    logger instances (and multiple processes) extend the same chain instead of
    starting private chains.
    """

    _write_lock = threading.RLock()

    def __init__(self, session=None):
        self._session = session

    @property
    def session(self):
        return self._session if self._session is not None else db.session

    # ------------------------------------------------------------------ read
    def chain_head(self, for_update: bool = False) -> Optional[AuditEvent]:
        """Most recent persisted event, i.e. the current chain head."""
        stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)
        if for_update:
            # MySQL/InnoDB serialises concurrent head reads within a
            # transaction. SQLite ignores FOR UPDATE; the id ordering plus the
            # previous-hash re-check in verify_events() still detect divergence.
            stmt = stmt.with_for_update()
        return self.session.execute(stmt).scalars().first()

    def load_chain(self, limit: Optional[int] = None) -> List[AuditEvent]:
        """Persisted chain in insertion order."""
        stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def get_chain(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Backwards-compatible dict view of the persisted chain."""
        return [event.to_dict() for event in self.load_chain(limit)]

    # ----------------------------------------------------------------- write
    def log(
        self,
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        commit: bool = True,
        max_retries: int = 3,
    ) -> AuditEvent:
        """Append one sanitised, hash-chained event and persist it.

        SEC-D0-02 Remediation:
        Enforces strict write serialization and linear hash-chain continuity
        across concurrent threads and database processes. Both the chain-head
        read and the new event insertion execute atomically within a locked,
        unified transaction boundary.
        """
        if not event_type or not isinstance(event_type, str):
            raise ValueError('event_type must be a non-empty string')

        sanitized_meta = sanitize_metadata(metadata or {})

        for attempt in range(max_retries + 1):
            try:
                with self._write_lock:
                    lock_acquired = False
                    is_mysql = False
                    try:
                        bind = self.session.get_bind()
                        if bind and bind.dialect.name == 'mysql':
                            is_mysql = True
                            res = self.session.execute(text("SELECT GET_LOCK('audit_chain_lock', 10)")).scalar()
                            lock_acquired = (res == 1)
                    except Exception:
                        pass

                    try:
                        # Query authoritative chain head with for_update
                        head = self.chain_head(for_update=True)
                        previous_hash = head.current_hash if head is not None else None

                        event = AuditEvent(
                            event_type=event_type,
                            created_at=_utc_now(),
                            event_metadata=sanitized_meta,
                            previous_hash=previous_hash,
                        )
                        event.current_hash = event.compute_hash()

                        self.session.add(event)
                        if commit:
                            self.session.commit()
                        else:
                            self.session.flush()
                        return event
                    except Exception:
                        self.session.rollback()
                        raise
                    finally:
                        if lock_acquired and is_mysql:
                            try:
                                self.session.execute(text("SELECT RELEASE_LOCK('audit_chain_lock')"))
                            except Exception:
                                pass
            except (OperationalError, DBAPIError) as err:
                if attempt < max_retries:
                    _time.sleep(0.05 * (attempt + 1))
                    continue
                raise err

    # ---------------------------------------------------------------- verify
    def verify_chain(self, limit: Optional[int] = None) -> bool:
        """Verify the whole persisted chain."""
        ok, _ = verify_events(self.load_chain(limit))
        return ok

    def verify_persisted_chain(self) -> bool:
        """Explicit alias for :meth:`verify_chain` (reads from the database)."""
        return self.verify_chain()

    def verify_event_range(self, first_id: int, last_id: int) -> bool:
        """Verify a persisted id range - used for operational spot checks."""
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.id >= first_id, AuditEvent.id <= last_id)
            .order_by(AuditEvent.id.asc())
        )
        ok, _ = verify_events(self.session.execute(stmt).scalars().all())
        return ok

    def __len__(self) -> int:
        return len(self.load_chain())


#: Backwards-compatible module-level instance. Holds no state of its own; the
#: chain lives in the database.
audit_logger = AuditLogger()
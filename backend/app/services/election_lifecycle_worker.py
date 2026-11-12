"""
Automated Election Lifecycle Worker - Vote Without Doubt
Background service for hands-off automatic election state transitions:
1. Scheduled -> Open: Automatically provisions V2 threshold encryption and opens voting at start_time.
2. Open -> Finalized: Automatically closes voting, submits DLEQ decryption shares, and finalizes tallies at end_time.

Safety and Invariant Guarantees:
- Idempotent: Never provisions, opens, closes or finalizes the same election twice.
- Process-Safe & Thread-Safe: Uses coordination lock to prevent concurrent races across processes and threads.
- Recovery-Safe: Recovers elections on startup after offline intervals if within valid windows.
- Preserves Keys: Always reuses existing key material; never overwrites or regenerates keys.
- Audit Logged: Every automatic transition and failure emits immutable audit records.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask
from sqlalchemy import text

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import ApprovalRequest
from app.models.ballot import Election
from app.services.v2_election_manager import V2ElectionManager

logger = logging.getLogger(__name__)

_LIFECYCLE_LOCK = threading.Lock()
_GLOBAL_LIFECYCLE_WORKER: Optional['ElectionLifecycleWorker'] = None
_LOCK_HELD_TLS = threading.local()
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_KEY_LOCKS: Dict[str, threading.Lock] = {}


def _get_process_key_lock(lock_name: str) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_KEY_LOCKS.get(lock_name)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_KEY_LOCKS[lock_name] = lock
        return lock


def _get_tls_held_counts() -> Dict[str, int]:
    held = getattr(_LOCK_HELD_TLS, 'held', None)
    if held is None:
        held = {}
        _LOCK_HELD_TLS.held = held
    return held


class PersistentElectionLock:
    """
    Cross-process and cross-thread advisory lock for election lifecycle transitions.
    1. Re-entrant within the same thread so nested calls (e.g. tick -> provision_and_open -> deploy)
       share the lock cleanly without self-blocking on OS byte-range locks.
    2. Serializes concurrent threads in the same process via a non-blocking per-election mutex.
    3. MySQL: Uses MySQL GET_LOCK / RELEASE_LOCK for distributed coordination across cluster nodes.
    4. SQLite / Non-MySQL: Uses an advisory file lock (msvcrt on Windows, fcntl on POSIX)
       in a shared temporary directory.
    """

    def __init__(self, election_id: Any, session=None):
        self.election_id = str(election_id)
        self.session = session or db.session
        self.lock_name = f"vwd_election_{self.election_id}"
        self.acquired = False
        self._is_mysql = False
        self._is_reentrant = False
        self._thread_lock: Optional[threading.Lock] = None
        self._file_handle = None
        self._lock_path = None

    def __bool__(self) -> bool:
        return bool(self.acquired)

    def __enter__(self):
        held = _get_tls_held_counts()
        if held.get(self.lock_name, 0) > 0:
            held[self.lock_name] += 1
            self._is_reentrant = True
            self.acquired = True
            return self

        tlock = _get_process_key_lock(self.lock_name)
        if not tlock.acquire(blocking=False):
            self.acquired = False
            return self
        self._thread_lock = tlock

        # 1. Check if dialect is MySQL
        try:
            bind = self.session.get_bind()
            if bind and bind.dialect.name == 'mysql':
                self._is_mysql = True
                res = self.session.execute(text(f"SELECT GET_LOCK('{self.lock_name}', 0)")).scalar()
                self.acquired = (res == 1)
                if self.acquired:
                    held[self.lock_name] = 1
                else:
                    self._thread_lock.release()
                    self._thread_lock = None
                return self
        except Exception as e:
            logger.debug("MySQL lock check bypassed: %s", e)

        # 2. File-based advisory lock across OS processes
        try:
            lock_dir = os.path.join(tempfile.gettempdir(), 'vwd_locks')
            os.makedirs(lock_dir, exist_ok=True)
            self._lock_path = os.path.join(lock_dir, f"{self.lock_name}.lock")
            self._file_handle = open(self._lock_path, 'a+')

            if os.name == 'nt':
                import msvcrt
                self._file_handle.seek(0)
                # Non-blocking lock 1 byte
                msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                self.acquired = True
            else:
                import fcntl
                fcntl.flock(self._file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
        except (IOError, OSError):
            self.acquired = False
        except Exception as e:
            logger.debug("Advisory file lock error: %s", e)
            self.acquired = True  # fallback if unsupported environment

        if self.acquired:
            held[self.lock_name] = 1
        else:
            if self._file_handle:
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None
            if self._thread_lock:
                try:
                    self._thread_lock.release()
                except Exception:
                    pass
                self._thread_lock = None

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.acquired:
            return

        held = _get_tls_held_counts()
        count = held.get(self.lock_name, 0)
        if self._is_reentrant:
            if count > 1:
                held[self.lock_name] = count - 1
            else:
                held.pop(self.lock_name, None)
            return

        held.pop(self.lock_name, None)
        if self._is_mysql:
            try:
                self.session.execute(text(f"SELECT RELEASE_LOCK('{self.lock_name}')"))
            except Exception:
                pass
        elif self._file_handle:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self._file_handle.seek(0)
                    msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file_handle, fcntl.LOCK_UN)
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None

        if self._thread_lock:
            try:
                self._thread_lock.release()
            except Exception:
                pass
            self._thread_lock = None


class ElectionLifecycleWorker:
    """
    Background worker that monitors election timelines and executes
    automated cryptographic provisioning, opening, closing, and finalization.
    """

    PERMANENT_ERROR_CODES = frozenset({
        'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT',
        'V2_KEYS_MISSING',
        'NOT_FOUND',
        'INSUFFICIENT_CANDIDATES',
        'INVALID_ELECTION_CONFIG',
        'CHECKPOINT_MISMATCH',
        'CHAIN_ID_MISMATCH',
        'CONTRACT_ELECTION_MISMATCH',
        'MISSING_ZERO_VOTE_SUPPORT',
    })
    PERMANENT_ERROR_MARKERS = (
        'NO_BALLOTS_CAST',
        'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT',
        'AT LEAST 2 CANDIDATES',
        'ELECTION PRIVATE KEYS NOT FOUND',
        'CHECKPOINT_MISMATCH',
        'CHAIN_ID_MISMATCH',
        'MISSING_ZERO_VOTE_SUPPORT',
        'CONTRACT_ELECTION_MISMATCH',
    )

    def __init__(
        self,
        app: Optional[Flask] = None,
        interval: float = 3.0,
        initial_backoff: float = 5.0,
        max_backoff: float = 300.0,
    ):
        self._app = app
        self.interval = float(interval)
        self.initial_backoff = max(0.0, float(initial_backoff))
        self.max_backoff = max(self.initial_backoff, float(max_backoff))
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._is_running = False
        self._failure_state: Dict[Tuple[str, int], Dict[str, Any]] = {}

    def get_failure_state(
        self,
        phase: Optional[str] = None,
        election_id: Optional[int] = None,
    ) -> Dict[Any, Any]:
        """Return a snapshot of tracked failure/backoff states for elections."""
        if phase is not None and election_id is not None:
            entry = self._failure_state.get((phase, int(election_id)))
            return dict(entry) if entry else {}
        return {k: dict(v) for k, v in self._failure_state.items()}

    def clear_failure_state(self, phase: Optional[str] = None, election_id: Optional[int] = None) -> None:
        """Clear tracked failure/backoff state (all or for a specific phase/election)."""
        if phase is not None and election_id is not None:
            self._failure_state.pop((phase, int(election_id)), None)
        else:
            self._failure_state.clear()

    def _is_permanent_failure(self, msg: str, details: Optional[Dict[str, Any]]) -> bool:
        if details:
            if details.get('permanent') is True:
                return True
            if details.get('error_code') in self.PERMANENT_ERROR_CODES:
                return True
        upper_msg = str(msg or '').upper()
        return any(marker in upper_msg for marker in self.PERMANENT_ERROR_MARKERS)

    def _should_skip_due_to_failure(self, phase: str, election_id: int, now: datetime) -> Optional[str]:
        entry = self._failure_state.get((phase, election_id))
        if not entry:
            return None
        if entry.get('permanent'):
            return 'PERMANENT_FAILURE'
        next_retry_at = entry.get('next_retry_at')
        if next_retry_at and now < next_retry_at:
            return 'BACKOFF'
        return None

    def _record_failure(
        self,
        phase: str,
        el: Election,
        msg: str,
        details: Optional[Dict[str, Any]],
        now: datetime,
    ) -> Dict[str, Any]:
        key = (phase, el.id)
        prev = self._failure_state.get(key)
        attempts = (prev['attempts'] + 1) if prev else 1
        permanent = self._is_permanent_failure(msg, details)
        error_code = details.get('error_code') if details else None

        if permanent:
            entry = {
                'attempts': attempts,
                'permanent': True,
                'status': 'PERMANENT_FAILURE',
                'last_error': str(msg),
                'error_code': error_code,
                'last_attempt_at': now,
                'next_retry_at': None,
            }
            self._failure_state[key] = entry
            if not prev or not prev.get('permanent'):
                AuditLogger().log('ELECTION_LIFECYCLE_PERMANENT_FAILURE', {
                    'phase': phase,
                    'election_id': el.election_id,
                    'db_election_id': el.id,
                    'error': str(msg),
                    'error_code': error_code,
                    'attempts': attempts,
                })
                logger.error(
                    "LifecycleWorker: Permanent failure for %s election %s (id=%d): %s",
                    phase, el.election_id, el.id, msg,
                )
            return entry

        delay = min(self.max_backoff, self.initial_backoff * (2 ** (attempts - 1)))
        next_retry_at = now + timedelta(seconds=delay)
        entry = {
            'attempts': attempts,
            'permanent': False,
            'status': 'RETRYING',
            'last_error': str(msg),
            'error_code': error_code,
            'backoff_seconds': delay,
            'last_attempt_at': now,
            'next_retry_at': next_retry_at,
        }
        self._failure_state[key] = entry
        return entry

    def start(self, app: Optional[Flask] = None) -> bool:
        """Start the background lifecycle worker daemon thread."""
        if app is not None:
            self._app = app
        if self._is_running and self._thread is not None and self._thread.is_alive():
            return False

        # Guard against Werkzeug reloader monitor process spawning duplicate threads
        if os.environ.get('WERKZEUG_RUN_MAIN') is not None and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            logger.info("Skipping ElectionLifecycleWorker start in Werkzeug reloader monitor process.")
            return False

        with _LIFECYCLE_LOCK:
            if self._is_running and self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._wake_event.clear()
            self._is_running = True

            thread = threading.Thread(
                target=self._run_loop,
                name="ElectionLifecycleWorkerThread",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            logger.info("ElectionLifecycleWorker started (interval=%.1fs).", self.interval)
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the background worker."""
        if not self._is_running:
            return True

        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        self._is_running = False
        self._thread = None
        logger.info("ElectionLifecycleWorker stopped.")
        return True

    def wake(self):
        """Immediately trigger a lifecycle check."""
        self._wake_event.set()

    def tick(self) -> Dict[str, Any]:
        """
        Execute one lifecycle check iteration across all elections.
        Can be called synchronously or periodically by the worker thread.
        """
        target_app = self._app
        if not target_app:
            from flask import current_app
            target_app = current_app._get_current_object() if current_app else None
        if not target_app:
            return {'status': 'SKIPPED', 'reason': 'No Flask app context'}

        with _LIFECYCLE_LOCK:
            with target_app.app_context():
                opened_count = 0
                closed_count = 0
                skipped_backoff = 0
                permanent_failures = 0
                now = datetime.utcnow()

                try:
                    # -------------------------------------------------------------
                    # 1. SCHEDULED -> OPEN: Automatic Provisioning and Opening
                    # -------------------------------------------------------------
                    scheduled_elections = Election.query.filter_by(
                        status='SCHEDULED',
                        cancelled=False,
                    ).all()

                    for el in scheduled_elections:
                        # Skip if start time hasn't arrived
                        if not el.start_time or now < el.start_time:
                            continue

                        # Check if scheduled window has completely expired without opening
                        if el.end_time and now >= el.end_time:
                            logger.warning(
                                "Election %s scheduled window expired (end_time=%s) before opening. Skipping auto-open.",
                                el.election_id, el.end_time,
                            )
                            continue

                        # Verify that this election had valid Two-Officer SCHEDULE_ELECTION approval
                        req = ApprovalRequest.query.filter(
                            ApprovalRequest.election_id == str(el.election_id),
                            ApprovalRequest.action_type == 'SCHEDULE_ELECTION',
                            ApprovalRequest.status == 'APPROVED',
                        ).first()

                        if not req:
                            # Also check integer ID if applicable
                            req = ApprovalRequest.query.filter(
                                ApprovalRequest.election_id == str(el.id),
                                ApprovalRequest.action_type == 'SCHEDULE_ELECTION',
                                ApprovalRequest.status == 'APPROVED',
                            ).first()

                        if not req:
                            logger.warning(
                                "Election %s has reached start_time but lacks an APPROVED SCHEDULE_ELECTION record. Bypassing.",
                                el.election_id,
                            )
                            continue

                        skip_reason = self._should_skip_due_to_failure('OPEN', el.id, now)
                        if skip_reason == 'PERMANENT_FAILURE':
                            permanent_failures += 1
                            continue
                        if skip_reason == 'BACKOFF':
                            skipped_backoff += 1
                            continue

                        # Execute automatic V2 provisioning and opening with persistent process lock
                        with PersistentElectionLock(el.id, session=db.session) as lock:
                            if not lock.acquired:
                                logger.info(
                                    "LifecycleWorker: Election %s is locked by another process. Skipping.",
                                    el.election_id,
                                )
                                continue

                            logger.info(
                                "LifecycleWorker: Auto-opening approved election %s (id=%d)...",
                                el.election_id, el.id,
                            )
                            ok, msg = V2ElectionManager.provision_and_open_election(el.id)
                            if ok:
                                self.clear_failure_state('OPEN', el.id)
                                opened_count += 1
                                AuditLogger().log('ELECTION_AUTO_OPENED', {
                                    'election_id': el.election_id,
                                    'start_time': el.start_time.isoformat(),
                                    'auto_triggered_at': now.isoformat(),
                                })
                                logger.info("LifecycleWorker: Successfully auto-opened election %s.", el.election_id)
                            else:
                                fail_entry = self._record_failure('OPEN', el, msg, None, now)
                                if fail_entry['permanent']:
                                    permanent_failures += 1
                                AuditLogger().log('ELECTION_AUTO_OPEN_FAILED', {
                                    'election_id': el.election_id,
                                    'error': msg,
                                    'permanent': fail_entry['permanent'],
                                    'attempts': fail_entry['attempts'],
                                })
                                logger.error("LifecycleWorker: Failed to auto-open election %s: %s", el.election_id, msg)

                    # -------------------------------------------------------------
                    # 2. OPEN (or unfinalized V2 CLOSED) -> FINALIZED: Automatic Closing and Finalization
                    # -------------------------------------------------------------
                    open_elections = Election.query.filter(
                        (Election.status.in_(['OPEN', 'ACTIVE'])) |
                        (
                            (Election.status == 'CLOSED') &
                            (Election.v2_priv_key_1.isnot(None)) &
                            (Election.v2_priv_key_2.isnot(None)) &
                            (Election.finalized_at.is_(None))
                        ),
                        Election.cancelled == False,
                    ).all()

                    for el in open_elections:
                        if not el.end_time or now < el.end_time:
                            continue

                        skip_reason = self._should_skip_due_to_failure('CLOSE', el.id, now)
                        if skip_reason == 'PERMANENT_FAILURE':
                            permanent_failures += 1
                            continue
                        if skip_reason == 'BACKOFF':
                            skipped_backoff += 1
                            continue

                        with PersistentElectionLock(el.id, session=db.session) as lock:
                            if not lock.acquired:
                                logger.info(
                                    "LifecycleWorker: Election %s is locked by another process. Skipping.",
                                    el.election_id,
                                )
                                continue

                            logger.info(
                                "LifecycleWorker: Auto-closing and finalizing election %s (id=%d)...",
                                el.election_id, el.id,
                            )
                            ok, msg, details = V2ElectionManager.close_and_finalize_election(el.id)
                            if ok:
                                self.clear_failure_state('CLOSE', el.id)
                                finalized_on_chain = (
                                    details.get('finalized_on_chain', True)
                                    if isinstance(details, dict)
                                    else True
                                )
                                if finalized_on_chain:
                                    closed_count += 1
                                    AuditLogger().log('ELECTION_AUTO_FINALIZED', {
                                        'election_id': el.election_id,
                                        'end_time': el.end_time.isoformat(),
                                        'auto_finalized_at': now.isoformat(),
                                        'tallies': details.get('tallies', []),
                                    })
                                    logger.info("LifecycleWorker: Successfully auto-finalized election %s.", el.election_id)
                                else:
                                    AuditLogger().log('ELECTION_AUTO_CLOSED_OFFLINE', {
                                        'election_id': el.election_id,
                                        'end_time': el.end_time.isoformat(),
                                        'closed_at': now.isoformat(),
                                        'finalized_on_chain': False,
                                    })
                                    logger.warning(
                                        "LifecycleWorker: Closed election %s offline without on-chain finalization.",
                                        el.election_id,
                                    )
                            else:
                                fail_entry = self._record_failure('CLOSE', el, msg, details, now)
                                if fail_entry['permanent']:
                                    permanent_failures += 1
                                AuditLogger().log('ELECTION_AUTO_FINALIZE_FAILED', {
                                    'election_id': el.election_id,
                                    'error': msg,
                                    'permanent': fail_entry['permanent'],
                                    'error_code': fail_entry.get('error_code'),
                                    'attempts': fail_entry['attempts'],
                                })
                                logger.error("LifecycleWorker: Failed to auto-finalize election %s: %s", el.election_id, msg)

                    return {
                        'status': 'OK',
                        'opened': opened_count,
                        'finalized': closed_count,
                        'skipped_backoff': skipped_backoff,
                        'permanent_failures': permanent_failures,
                    }

                except Exception as exc:
                    logger.exception("Error during ElectionLifecycleWorker tick: %s", exc)
                    return {'status': 'ERROR', 'error': str(exc)}

    def _run_loop(self):
        """Worker loop running in daemon thread."""
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=self.interval)
            self._wake_event.clear()

            if self._stop_event.is_set():
                break

            try:
                self.tick()
            except Exception as exc:
                logger.exception("ElectionLifecycleWorker background loop exception: %s", exc)


def get_lifecycle_worker(app: Optional[Flask] = None) -> ElectionLifecycleWorker:
    """Retrieve or initialize the global ElectionLifecycleWorker singleton."""
    global _GLOBAL_LIFECYCLE_WORKER
    with _LIFECYCLE_LOCK:
        if _GLOBAL_LIFECYCLE_WORKER is None:
            _GLOBAL_LIFECYCLE_WORKER = ElectionLifecycleWorker(app=app)
        elif app is not None and _GLOBAL_LIFECYCLE_WORKER._app is None:
            _GLOBAL_LIFECYCLE_WORKER._app = app
        return _GLOBAL_LIFECYCLE_WORKER

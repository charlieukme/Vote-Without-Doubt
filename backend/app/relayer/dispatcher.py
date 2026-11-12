"""
Relayer Dispatcher & Background Worker - Fix 2 (Timing De-Correlation)
Vote Without Doubt

Responsibilities:
1. Manages a background worker thread for scheduled and threshold-based batch dispatch.
2. Decouples HTTP ballot submissions from blockchain transaction broadcasts.
3. Enforces configurable minimum batch threshold (K >= 5).
4. Enforces bounded waiting policy (max wait time before timeout flush).
5. Ensures safe election closure flushing (no stranded ballots).
6. Preserves election isolation (never mixes ballots across elections).
7. Preserves revote sequence ordering per pseudonym.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DISPATCHER_LOCK = threading.Lock()
_GLOBAL_DISPATCHER: Optional['RelayerDispatcher'] = None


class RelayerDispatcher:
    """
    Background worker and reliable scheduler for relayer batch dispatch (Fix 2).
    """

    def __init__(self, app=None, dispatch_interval: Optional[float] = None):
        self._app = app
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._dispatch_interval = dispatch_interval

    @property
    def dispatch_interval(self) -> float:
        if self._dispatch_interval is not None:
            return self._dispatch_interval
        try:
            if self._app and self._app.config:
                return float(self._app.config.get('RELAYER_DISPATCH_INTERVAL_SECONDS', 2.0))
        except Exception:
            pass
        try:
            return float(os.getenv('RELAYER_DISPATCH_INTERVAL_SECONDS', '2.0'))
        except (ValueError, TypeError):
            return 2.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, app=None) -> bool:
        """Start the background dispatcher worker daemon thread."""
        with self._lock:
            if app is not None:
                self._app = app
            if self.is_running:
                return True
            if self._app is None:
                logger.warning("RelayerDispatcher cannot start without Flask app reference.")
                return False

            self._stop_event.clear()
            self._wake_event.clear()
            thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="RelayerDispatcherWorker",
            )
            thread.start()
            self._thread = thread
            logger.info("RelayerDispatcher started (interval=%.1fs).", self.dispatch_interval)
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the background worker thread gracefully."""
        with self._lock:
            if not self.is_running:
                return True
            self._stop_event.set()
            self._wake_event.set()
            if self._thread:
                self._thread.join(timeout=timeout)
                self._thread = None
            logger.info("RelayerDispatcher stopped.")
            return True

    def notify(self, election_id: Optional[Any] = None):
        """Wake up the dispatcher to evaluate batch eligibility immediately."""
        self._wake_event.set()

    def tick(
        self,
        app=None,
        force: bool = False,
        election_id: Optional[Any] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synchronously evaluate and dispatch due batches across elections.
        Used by the background worker, test suites, and admin flush triggers.
        """
        from app.relayer.relayer import Relayer, _RELAYER_LOCK

        target_app = app or self._app
        if target_app is None:
            from flask import current_app
            target_app = current_app._get_current_object() if current_app else None

        if target_app is None:
            logger.warning("RelayerDispatcher.tick called with no app context available.")
            return {'status': 'NO_APP_CONTEXT', 'batches_dispatched': 0}

        with _RELAYER_LOCK:
            with target_app.app_context():
                try:
                    target_contract = contract_address or target_app.config.get('BALLOTBOX_CONTRACT_ADDRESS')
                    relayer = Relayer(contract_address=target_contract)
                    return relayer.dispatch_due_batches(
                        force=force,
                        election_id=election_id,
                        contract_address=target_contract,
                    )
                except Exception as exc:
                    logger.exception("Error in RelayerDispatcher.tick: %s", exc)
                    return {'status': 'ERROR', 'error': str(exc), 'batches_dispatched': 0}

    def _run_loop(self):
        """Worker loop running in daemon thread."""
        while not self._stop_event.is_set():
            # Wait for wake notification or interval timeout
            interval = self.dispatch_interval
            self._wake_event.wait(timeout=interval)
            self._wake_event.clear()

            if self._stop_event.is_set():
                break

            try:
                self.tick(force=False)
            except Exception as exc:
                logger.exception("Relayer background dispatcher loop exception: %s", exc)


def get_dispatcher(app=None) -> RelayerDispatcher:
    """Retrieve or initialize the global RelayerDispatcher singleton."""
    global _GLOBAL_DISPATCHER
    with _DISPATCHER_LOCK:
        if _GLOBAL_DISPATCHER is None:
            _GLOBAL_DISPATCHER = RelayerDispatcher(app=app)
        elif app is not None and _GLOBAL_DISPATCHER._app is None:
            _GLOBAL_DISPATCHER._app = app
        return _GLOBAL_DISPATCHER


def notify_ballot_queued(app, election_id: Optional[Any] = None):
    """
    Decoupled notification when a ballot is queued (Fix 2).
    Notifies the dispatcher without immediately flushing single ballots.
    """
    disp = get_dispatcher(app)
    disp.notify(election_id)


def trigger_election_close_flush(app, election_id: Any) -> Dict[str, Any]:
    """
    Immediately flush all remaining queued ballots for a closing election (Requirement 7).
    Guarantees no queued ballots are stranded upon election closure.
    """
    disp = get_dispatcher(app)
    return disp.tick(app=app, force=True, election_id=election_id)

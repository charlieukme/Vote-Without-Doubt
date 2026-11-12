"""
Backend Blockchain Relayer - Fix 2 (Relayer Batching & Timing De-Correlation)
Vote Without Doubt

Responsibilities:
1. Polls/processes the pseudonymous BallotQueue (ballot plane).
2. Decouples HTTP ballot submission time from blockchain transaction time.
3. Enforces configurable minimum batch threshold (K >= 5, configurable).
4. Enforces bounded waiting policy so ballots are never stranded indefinitely.
5. Flushes pending ballots safely upon election closure.
6. Strictly isolates elections: ballots from different elections are NEVER mixed.
7. Cryptographically shuffles queued ballots with CSPRNG while strictly preserving revote sequence ordering per pseudonym.
8. Submits valid castBallot transactions to EVotingBallotBox on blockchain.
9. Mined receipts update state to CONFIRMED and FINALIZED with real tx_hash and block_number.
10. Failures update state to FAILED with real error context and reconciliation metadata without inventing fake hashes.
11. Records comprehensive audit metadata for every dispatched batch.

Security & Privacy Limitations:
- When fewer than K ballots are available and dispatch is triggered by timeout (MAX_WAIT_EXCEEDED) or election closure (ELECTION_CLOSED),
  the anonymity set is reduced to N < K. When N=1, no timing decorrelation or shuffling anonymity is provided.
- Synthetic dummy ballots are intentionally NOT injected: without verifiable cryptographic dummy protocols, fake ballots would
  distort candidate tallies on-chain or require trusted-authority decryption.
- Latency Trade-Off: In low-volume elections, ballots wait up to RELAYER_MAX_WAIT_SECONDS before on-chain settlement.
  In high-volume elections, batches dispatch rapidly once K is reached. At election closure, availability takes precedence
  and all remaining ballots are flushed immediately.
"""

import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from web3 import Web3

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import BallotRecord as Ballot, Election, ReconciliationIssue

logger = logging.getLogger(__name__)

_RELAYER_LOCK = threading.Lock()
_BATCH_WORKER_THREAD = None

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DEFAULT_ARTIFACT_PATH = os.path.join(
    _REPO_ROOT, 'blockchain', 'artifacts', 'contracts', 'EVotingBallotBox.sol', 'EVotingBallotBox.json'
)


def _load_contract_abi(artifact_path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = artifact_path or _DEFAULT_ARTIFACT_PATH
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle).get('abi', [])
    logger.warning("EVotingBallotBox artifact not found at %s", path)
    return []


_UNSET = object()


class Relayer:
    """
    Submits pseudonymous ballots from BallotQueue to the smart contract.
    Preserves strict identity/ballot separation: operates solely on pseudonyms.
    Implements Fix 2 Relayer Batching and Timing De-Correlation.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        contract_address: Any = _UNSET,
        relayer_private_key: Optional[str] = None,
        relayer_account: Optional[str] = None,
        artifact_path: Optional[str] = None,
        w3_instance: Optional[Web3] = None,
    ):
        self._custom_rpc_url = rpc_url
        self._custom_contract_address = contract_address
        self._custom_private_key = relayer_private_key
        self._custom_relayer_account = relayer_account
        self._artifact_path = artifact_path
        self._w3 = w3_instance
        self._abi = _load_contract_abi(artifact_path)

    def _get_config_val(self, key: str, default: Any = None) -> Any:
        try:
            if current_app and current_app.config:
                return current_app.config.get(key, default)
        except RuntimeError:
            pass
        return os.getenv(key, default)

    @property
    def rpc_url(self) -> str:
        return self._custom_rpc_url or self._get_config_val('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')

    @property
    def contract_address(self) -> Optional[str]:
        if self._custom_contract_address is not _UNSET:
            return self._custom_contract_address
        return self._get_config_val('BALLOTBOX_CONTRACT_ADDRESS', None)

    @property
    def private_key(self) -> Optional[str]:
        return self._custom_private_key or self._get_config_val('RELAYER_PRIVATE_KEY', None)

    @property
    def relayer_account(self) -> Optional[str]:
        return self._custom_relayer_account or self._get_config_val('RELAYER_ACCOUNT', None)

    @property
    def is_enabled(self) -> bool:
        val = self._get_config_val('RELAYER_ENABLED', True)
        if isinstance(val, str):
            return val.strip().lower() in ('1', 'true', 'yes', 'on')
        return bool(val)

    @property
    def min_batch_size(self) -> int:
        """Minimum batch threshold K (Fix 2). Default 5."""
        try:
            return int(self._get_config_val('RELAYER_MIN_BATCH_SIZE', 5))
        except (ValueError, TypeError):
            return 5

    @property
    def max_batch_size(self) -> int:
        """Maximum batch limit. Default 10."""
        try:
            val = self._get_config_val('RELAYER_MAX_BATCH_SIZE', self._get_config_val('RELAYER_BATCH_SIZE', 10))
            return int(val)
        except (ValueError, TypeError):
            return 10

    @property
    def max_wait_seconds(self) -> float:
        """Bounded waiting policy timeout in seconds (Fix 2). Default 30.0s."""
        try:
            return float(self._get_config_val('RELAYER_MAX_WAIT_SECONDS', 30.0))
        except (ValueError, TypeError):
            return 30.0

    @property
    def dispatch_interval_seconds(self) -> float:
        """Polling interval for the background dispatcher (Fix 2). Default 2.0s."""
        try:
            return float(self._get_config_val('RELAYER_DISPATCH_INTERVAL_SECONDS', 2.0))
        except (ValueError, TypeError):
            return 2.0

    def get_web3(self) -> Web3:
        if self._w3 is not None:
            return self._w3
        provider = Web3.HTTPProvider(self.rpc_url, request_kwargs={'timeout': 15})
        return Web3(provider)

    def shuffle_queue(self, items: List[Ballot]) -> List[Ballot]:
        """
        Cryptographically secure queue shuffling to guarantee privacy while preserving sequence ordering per pseudonym.
        Uses secrets.SystemRandom() (CSPRNG).
        """
        by_pseud = {}
        for b in items:
            by_pseud.setdefault(b.pseudonym, []).append(b)
        for p in by_pseud:
            by_pseud[p].sort(key=lambda x: (x.sequence, x.id))
        pseudo_keys = list(by_pseud.keys())
        secrets.SystemRandom().shuffle(pseudo_keys)

        shuffled = []
        while any(by_pseud.values()):
            for pk in list(pseudo_keys):
                if by_pseud[pk]:
                    shuffled.append(by_pseud[pk].pop(0))
        return shuffled

    def _format_pseudonym(self, pseud: str) -> bytes:
        clean = pseud.strip()
        if clean.startswith('0x') or clean.startswith('0X'):
            clean = clean[2:]
        if len(clean) % 2 != 0:
            clean = '0' + clean
        raw = bytes.fromhex(clean)
        if len(raw) < 32:
            raw = raw.ljust(32, b'\x00')
        elif len(raw) > 32:
            raw = raw[:32]
        return raw

    def check_election_batch_eligibility(
        self,
        election_id: Any,
    ) -> Tuple[bool, str, List[Ballot], float]:
        """
        Evaluate whether the queued ballots for a specific election are eligible for dispatch.
        PERMANENTLY DISABLED per SEC-001 (Legacy V1 broadcast prohibition).
        """
        return False, "V1_RELAYER_BROADCAST_DISABLED_SEC_001", [], 0.0

    def _filter_batch_candidates(
        self,
        queued: List[Ballot],
        limit: int,
        force: bool = False,
    ) -> List[Ballot]:
        """
        Select candidates for the current batch up to limit, ensuring revote sequence dependencies.
        Never dispatches sequence S > 1 ahead of sequence S - 1 when sequence S - 1 is queued or in flight.
        """
        selected = []
        pseud_sequences_in_batch = {}

        for b in queued:
            if len(selected) >= limit:
                break
            seq = int(b.sequence or 1)
            pseud = b.pseudonym

            if not force and seq > 1:
                # Check if previous sequence is in the same batch
                prev_in_batch = pseud_sequences_in_batch.get(pseud, set())
                if (seq - 1) not in prev_in_batch:
                    # Check if previous sequence is still queued or in flight
                    prev_pending = Ballot.query.filter(
                        Ballot.election_id == b.election_id,
                        Ballot.pseudonym == pseud,
                        Ballot.sequence == seq - 1,
                        Ballot.state.in_(['QUEUED', 'SUBMITTED']),
                    ).first()
                    if prev_pending:
                        # Defer this ballot until prior sequence is processed
                        continue

            selected.append(b)
            pseud_sequences_in_batch.setdefault(pseud, set()).add(seq)

        return selected

    def _broadcast_ballot_batch(
        self,
        items: List[Ballot],
        contract_address: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Broadcast an atomic, shuffled batch of ballots to the blockchain.
        PERMANENTLY DISABLED per SEC-001 (Legacy V1 broadcast prohibition).
        Fail-closed: Never claim, update, or transmit any ballot to EVotingBallotBox contract.
        Historical ballot_queue records and their states are strictly preserved without alteration.
        """
        item_count = len(items) if items else 0
        logger.warning(
            "V1 blockchain broadcast permanently prohibited by security policy SEC-001. "
            "Refusing to broadcast %d queued ballot(s).",
            item_count,
        )
        try:
            from app.audit.audit import AuditLogger
            AuditLogger().log('V1_RELAYER_BROADCAST_BLOCKED', {
                'reason': 'SEC-001_V1_PROTOCOL_PERMANENTLY_DISABLED',
                'ballot_count': item_count,
            })
        except Exception as audit_err:
            logger.warning("Audit log for blocked V1 relayer broadcast failed: %s", audit_err)

        return {
            'processed': 0,
            'confirmed': 0,
            'failed': 0,
            'blocked_sec_001': item_count,
        }

    def dispatch_election_batch(
        self,
        election_id: Any,
        force: bool = False,
        reason: Optional[str] = None,
        contract_address: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Process and broadcast a batch of queued ballots for a single election.
        Strictly preserves election isolation (never mixes elections).
        """
        summary = {
            'processed': 0,
            'confirmed': 0,
            'failed': 0,
            'election_id': str(election_id),
            'status': 'SKIPPED',
        }

        is_eligible, check_reason, queued, wait_seconds = self.check_election_batch_eligibility(election_id)
        if not is_eligible:
            summary['status'] = 'BLOCKED' if force else 'SKIPPED'
            summary['reason'] = check_reason
            summary['wait_seconds'] = round(wait_seconds, 2)
            summary['queued_count'] = len(queued)
            return summary

        trigger_reason = reason or (check_reason if is_eligible else 'MANUAL_FLUSH')
        limit = batch_size or self.max_batch_size

        # Filter candidates ensuring revote dependency ordering
        batch_candidates = self._filter_batch_candidates(queued, limit, force=force)
        if not batch_candidates:
            summary['status'] = 'EMPTY'
            summary['reason'] = 'NO_ELIGIBLE_CANDIDATES'
            return summary

        # Cryptographically secure shuffle with sequence preservation per pseudonym
        shuffled_items = self.shuffle_queue(batch_candidates)

        batch_id = secrets.token_hex(8)
        unique_pseudonyms = set(b.pseudonym for b in shuffled_items)
        degraded = len(shuffled_items) < self.min_batch_size

        # Record audit dispatch metadata (Requirement 8)
        try:
            AuditLogger().log('RELAYER_BATCH_DISPATCHED', {
                'batch_id': batch_id,
                'election_id': str(election_id),
                'batch_size': len(shuffled_items),
                'trigger_reason': trigger_reason,
                'min_threshold': self.min_batch_size,
                'wait_time_seconds': round(wait_seconds, 2),
                'ballot_count': len(shuffled_items),
                'pseudonym_count': len(unique_pseudonyms),
                'degraded_privacy': degraded,
            })
        except Exception as audit_err:
            logger.warning("Audit log for relayer batch dispatch failed: %s", audit_err)

        target_contract = contract_address or self.contract_address
        broadcast_res = self._broadcast_ballot_batch(shuffled_items, target_contract)

        summary.update(broadcast_res)
        summary['status'] = 'DISPATCHED'
        summary['batch_id'] = batch_id
        summary['trigger_reason'] = trigger_reason
        summary['degraded_privacy'] = degraded
        summary['wait_seconds'] = round(wait_seconds, 2)
        summary['batch_size'] = len(shuffled_items)

        return summary

    def dispatch_due_batches(
        self,
        force: bool = False,
        contract_address: Optional[str] = None,
        election_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Inspect all distinct elections with queued ballots and dispatch due batches.
        Strictly processes each election independently.
        """
        if election_id is not None:
            eids = [election_id]
        else:
            eids = [
                row[0] for row in db.session.query(Ballot.election_id)
                .filter_by(state='QUEUED')
                .distinct()
                .all()
            ]

        overall_summary = {
            'elections_checked': len(eids),
            'batches_dispatched': 0,
            'total_processed': 0,
            'total_confirmed': 0,
            'total_failed': 0,
            'details': {},
        }

        for eid in eids:
            res = self.dispatch_election_batch(
                election_id=eid,
                force=force,
                contract_address=contract_address,
            )
            overall_summary['details'][str(eid)] = res
            if res.get('processed', 0) > 0:
                overall_summary['batches_dispatched'] += 1
                overall_summary['total_processed'] += res.get('processed', 0)
                overall_summary['total_confirmed'] += res.get('confirmed', 0)
                overall_summary['total_failed'] += res.get('failed', 0)

        return overall_summary

    def process_queue(
        self,
        batch_size: int = 10,
        contract_address: Optional[str] = None,
        force: bool = True,
        election_id: Optional[Any] = None,
    ) -> Dict[str, int]:
        """
        Process pending QUEUED ballots (Backward Compatibility Entrypoint).
        Maintains backward compatibility for tests and direct callers.
        If force=True, processes without waiting for threshold K, while still isolating by election!
        If force=False, enforces the K threshold and max wait policies.
        """
        summary = {'processed': 0, 'confirmed': 0, 'failed': 0}

        if election_id is not None:
            eids = [election_id]
        else:
            eids = [
                row[0] for row in db.session.query(Ballot.election_id)
                .filter_by(state='QUEUED')
                .distinct()
                .all()
            ]

        for eid in eids:
            res = self.dispatch_election_batch(
                election_id=eid,
                force=force,
                contract_address=contract_address,
                batch_size=batch_size,
            )
            summary['processed'] += res.get('processed', 0)
            summary['confirmed'] += res.get('confirmed', 0)
            summary['failed'] += res.get('failed', 0)

        return summary


def trigger_async_relayer(
    app,
    batch_delay: Optional[float] = None,
    force: bool = False,
) -> Optional[threading.Thread]:
    """
    Decoupled relayer trigger (Fix 2).
    Notifies the background dispatcher or triggers an asynchronous evaluation of due batches.
    Does NOT flush single ballots immediately unless force=True.
    """
    global _BATCH_WORKER_THREAD

    if app.config.get('TESTING') and not app.config.get('ENABLE_TEST_ASYNC_RELAYER'):
        return None

    # Notify global dispatcher if active
    try:
        from app.relayer.dispatcher import get_dispatcher
        disp = get_dispatcher(app)
        if disp.is_running:
            disp.notify()
            return None
    except Exception:
        pass

    delay = batch_delay
    if delay is None:
        try:
            delay = float(os.getenv('RELAYER_BATCH_DELAY_SECONDS', '0.2'))
        except (ValueError, TypeError):
            delay = 0.2

    def _worker():
        if delay > 0:
            time.sleep(delay)
        with _RELAYER_LOCK:
            with app.app_context():
                try:
                    relayer = Relayer()
                    relayer.dispatch_due_batches(force=force)
                except Exception as exc:
                    logger.exception("Background relayer worker error: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True, name="RelayerBatchWorker")
    thread.start()
    _BATCH_WORKER_THREAD = thread
    return thread

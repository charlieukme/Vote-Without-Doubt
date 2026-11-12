"""
Recovery Service - Phase 10
Vote Without Doubt

Provides crash recovery, unconfirmed transaction discovery, and failure handling:
1. Recovers in-flight SUBMITTED ballots after relayer or application restart
2. Inspects blockchain transaction receipts (distinguishing confirmed, reverted, pending)
3. Recovers unbroadcast SUBMITTED ballots (resets to retryable QUEUED)
4. Handles stale QUEUED ballots while preserving Phase 8 invariants
5. True idempotent recovery execution
6. Mismatch recording via ReconciliationIssue model
7. Hash-chained audit logging for recovery actions
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union

from flask import current_app
from web3 import Web3

from app.extensions import db
from app.models import BallotRecord as Ballot, Election, ReconciliationIssue
from app.models.ballot_record_v2 import (
    BallotQueueV2,
    IN_FLIGHT_V2_STATES,
    VALID_V2_FINAL_STATES,
    ensure_v2_receipt_code,
    mark_prior_v2_ballots_superseded,
)
from app.relayer import Relayer

logger = logging.getLogger(__name__)


class RecoveryService:
    @staticmethod
    def startup_recover(app=None, detailed: bool = False) -> Union[int, Dict[str, Any]]:
        """
        Discovers and reconciles unfinished ballots (QUEUED and SUBMITTED) on boot or recovery cycle.
        Preserves Phase 8 contract: returns integer count when detailed=False.
        """
        summary = {
            'recovered': 0,
            'confirmed': 0,
            'failed': 0,
            'requeued': 0,
            'pending': 0,
            'queued': 0,
            'v2_recovered': 0,
            'v2_confirmed': 0,
            'v2_failed': 0,
            'v2_requeued': 0,
            'v2_pending': 0,
            'v2_queued': 0,
            'v2_uncertain': 0,
        }

        # Query all in-flight V1 ballots
        ballots = Ballot.query.filter(
            Ballot.state.in_(['QUEUED', 'SUBMITTED'])
        ).order_by(Ballot.id.asc()).all()

        summary['recovered'] = len(ballots)

        # Attempt to obtain Web3 and Contract for V1 only if V1 ballots exist
        w3 = None
        contract = None
        relayer = None

        if ballots:
            target_contract = None
            rpc_url = None
            relayer_account = None

            cfg = app.config if app else (current_app.config if current_app else {})
            if cfg:
                target_contract = cfg.get('BALLOTBOX_CONTRACT_ADDRESS')
                rpc_url = cfg.get('BLOCKCHAIN_RPC_URL')
                relayer_account = cfg.get('RELAYER_ACCOUNT')

            try:
                relayer = Relayer(rpc_url=rpc_url, contract_address=target_contract, relayer_account=relayer_account)
                w3 = relayer.get_web3()
                if target_contract and w3 and w3.is_connected():
                    contract = w3.eth.contract(
                        address=Web3.to_checksum_address(target_contract),
                        abi=relayer._abi,
                    )
            except Exception as exc:
                logger.warning("RecoveryService: Web3 connection unavailable (%s); proceeding with offline recovery.", exc)
                w3 = None
                contract = None

        now = datetime.utcnow()

        for b in ballots:
            try:
                # ------------------------------------------------------------------
                # Case 1: Ballot is SUBMITTED (In-flight / Interrupted)
                # ------------------------------------------------------------------
                if b.state == 'SUBMITTED':
                    if w3 and w3.is_connected() and b.tx_hash:
                        # 1a. Transaction hash exists: check receipt on-chain
                        try:
                            receipt = w3.eth.get_transaction_receipt(b.tx_hash)
                        except Exception:
                            receipt = None

                        if receipt is not None:
                            status = getattr(receipt, 'status', None)
                            if status == 1:
                                # Transaction succeeded and was mined on blockchain
                                b.block_number = int(receipt.blockNumber)
                                b.tx_confirmed_at = now
                                b.state = 'CONFIRMED'
                                if not b.receipt_code:
                                    import hashlib
                                    import hmac
                                    import os
                                    secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY') or 'default-secret'
                                    msg = f"{b.election_id}|{b.pseudonym}|{now.strftime('%Y-%m-%dT%H:%M:00Z')}"
                                    raw_code = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].upper()
                                    b.receipt_code = f"REC-{b.election_id}-{raw_code}"
                                db.session.commit()
                                b.state = 'FINALIZED'
                                b.reconcile_required = False
                                b.reconcile_reason = 'RECOVERED_CONFIRMED'
                                db.session.commit()
                                summary['confirmed'] += 1
                                logger.info("Recovered confirmed ballot %s (tx: %s)", b.id, b.tx_hash)

                                try:
                                    from app.audit import AuditLogger
                                    AuditLogger().log('BALLOT_RECOVERED_CONFIRMED', {
                                        'ballot_id': b.id,
                                        'election_id': str(b.election_id),
                                        'sequence': b.sequence,
                                        'block_number': b.block_number,
                                    })
                                except Exception:
                                    pass
                                continue

                            elif status == 0:
                                # Transaction reverted on-chain
                                b.state = 'FAILED'
                                revert_reason = None
                                try:
                                    tx_data = w3.eth.get_transaction(b.tx_hash)
                                    call_dict = {
                                        'from': tx_data.get('from'),
                                        'to': tx_data.get('to'),
                                        'data': tx_data.get('input'),
                                        'value': tx_data.get('value', 0),
                                    }
                                    w3.eth.call(call_dict, block_identifier=receipt.blockNumber)
                                except Exception as call_err:
                                    err_str = str(call_err)
                                    if 'revert ' in err_str:
                                        revert_reason = err_str.split('revert ')[-1].split("'")[0].split('"')[0].strip()
                                    elif 'execution reverted' in err_str:
                                        revert_reason = err_str.split('execution reverted')[-1].strip(': "\'')

                                if revert_reason:
                                    clean_reason = revert_reason.split('\n')[0].strip()
                                    b.error = f'TRANSACTION_REVERTED: {clean_reason} (block {receipt.blockNumber})'
                                else:
                                    b.error = f'TRANSACTION_REVERTED (block {receipt.blockNumber})'
                                b.tx_failed_at = now
                                b.reconcile_required = True
                                b.reconcile_reason = 'TX_REVERTED'
                                db.session.commit()
                                summary['failed'] += 1
                                logger.warning("Recovered reverted ballot %s (tx: %s)", b.id, b.tx_hash)

                                try:
                                    from app.audit import AuditLogger
                                    AuditLogger().log('BALLOT_RECOVERED_REVERTED', {
                                        'ballot_id': b.id,
                                        'election_id': str(b.election_id),
                                        'sequence': b.sequence,
                                        'block_number': int(receipt.blockNumber),
                                    })
                                except Exception:
                                    pass
                                continue

                        # Receipt not yet found: check if tx is in mempool (pending)
                        try:
                            tx_obj = w3.eth.get_transaction(b.tx_hash)
                        except Exception:
                            tx_obj = None

                        if tx_obj is not None:
                            # Tx is still pending in mempool
                            b.reconcile_required = True
                            b.reconcile_reason = 'TX_PENDING'
                            db.session.commit()
                            summary['pending'] += 1
                            continue

                        # Tx missing from receipt and mempool: check contract getBallot
                        if contract and relayer:
                            try:
                                pseudo_bytes = relayer._format_pseudonym(b.pseudonym)
                                chain_ballot = contract.functions.getBallot(int(b.election_id), pseudo_bytes).call()
                                if chain_ballot[3] and chain_ballot[0] == b.sequence:
                                    # Already on chain! Finalize DB
                                    b.state = 'FINALIZED'
                                    b.tx_confirmed_at = now
                                    b.reconcile_required = False
                                    b.reconcile_reason = 'RECOVERED_ON_CHAIN'
                                    db.session.commit()
                                    summary['confirmed'] += 1
                                    continue
                            except Exception:
                                pass

                        # Missing tx and not on chain: check if timed out -> safely requeue
                        broadcast_time = b.tx_broadcast_at or b.created_at or now
                        if (now - broadcast_time).total_seconds() > 30:
                            b.state = 'QUEUED'
                            b.tx_hash = None
                            b.retry_count = (b.retry_count or 0) + 1
                            b.last_retry_at = now
                            b.reconcile_required = False
                            b.reconcile_reason = 'REQUEUED_MISSING_TX'
                            db.session.commit()
                            summary['requeued'] += 1
                            logger.info("Requeued dropped ballot %s for retransmission", b.id)

                            try:
                                from app.audit import AuditLogger
                                AuditLogger().log('BALLOT_REQUEUED', {
                                    'ballot_id': b.id,
                                    'election_id': str(b.election_id),
                                    'sequence': b.sequence,
                                    'retry_count': b.retry_count,
                                })
                            except Exception:
                                pass
                        else:
                            b.reconcile_required = True
                            b.reconcile_reason = 'TX_PENDING'
                            db.session.commit()
                            summary['pending'] += 1

                    elif w3 and w3.is_connected() and not b.tx_hash:
                        # 1b. Crash happened BEFORE or DURING broadcast (tx_hash is NULL)
                        # Check if contract already has this ballot
                        recovered_on_chain = False
                        if contract and relayer:
                            try:
                                pseudo_bytes = relayer._format_pseudonym(b.pseudonym)
                                chain_ballot = contract.functions.getBallot(int(b.election_id), pseudo_bytes).call()
                                if chain_ballot[3] and chain_ballot[0] == b.sequence:
                                    b.state = 'FINALIZED'
                                    b.tx_confirmed_at = now
                                    b.reconcile_required = False
                                    b.reconcile_reason = 'RECOVERED_ON_CHAIN'
                                    db.session.commit()
                                    summary['confirmed'] += 1
                                    recovered_on_chain = True
                            except Exception:
                                pass

                        if not recovered_on_chain:
                            # Not on chain and never had a tx_hash: return to QUEUED for safe dispatch
                            b.state = 'QUEUED'
                            b.retry_count = (b.retry_count or 0) + 1
                            b.last_retry_at = now
                            b.reconcile_required = False
                            b.reconcile_reason = 'REQUEUED_UNBROADCAST'
                            db.session.commit()
                            summary['requeued'] += 1

                            try:
                                from app.audit import AuditLogger
                                AuditLogger().log('BALLOT_REQUEUED', {
                                    'ballot_id': b.id,
                                    'election_id': str(b.election_id),
                                    'sequence': b.sequence,
                                    'retry_count': b.retry_count,
                                })
                            except Exception:
                                pass
                    else:
                        # Offline fallback: flag for investigation
                        b.reconcile_required = True
                        b.reconcile_reason = 'STALE_SUBMITTED'
                        db.session.commit()
                        summary['pending'] += 1

                # ------------------------------------------------------------------
                # Case 2: Ballot is QUEUED
                # ------------------------------------------------------------------
                elif b.state == 'QUEUED':
                    # Check if ballot is unexpectedly already on-chain (e.g. database restore edge case)
                    already_on_chain = False
                    if contract and relayer and w3 and w3.is_connected():
                        try:
                            pseudo_bytes = relayer._format_pseudonym(b.pseudonym)
                            chain_ballot = contract.functions.getBallot(int(b.election_id), pseudo_bytes).call()
                            if chain_ballot[3] and chain_ballot[0] == b.sequence:
                                b.state = 'FINALIZED'
                                b.tx_confirmed_at = now
                                b.reconcile_required = False
                                b.reconcile_reason = 'RECOVERED_ON_CHAIN'
                                db.session.commit()
                                summary['confirmed'] += 1
                                already_on_chain = True
                        except Exception:
                            pass

                    if not already_on_chain:
                        # Standard Phase 8 behavior: flag stale queued ballot for audit reconciliation
                        if b.reconcile_required is False:
                            b.reconcile_required = True
                            b.reconcile_reason = 'UNFINISHED_QUEUED'
                            db.session.commit()
                        summary['queued'] += 1

            except Exception as item_exc:
                logger.exception("Error recovering ballot %s: %s", b.id, item_exc)
                db.session.rollback()

        RecoveryService._recover_v2_ballots(now, summary)

        if summary['recovered'] > 0:
            try:
                from app.audit import AuditLogger
                AuditLogger().log('STARTUP_RECOVERY_COMPLETED', {
                    'recovered_count': summary['recovered'],
                    'confirmed_count': summary['confirmed'],
                    'requeued_count': summary['requeued'],
                    'failed_count': summary['failed'],
                    'v2_recovered_count': summary['v2_recovered'],
                    'v2_confirmed_count': summary['v2_confirmed'],
                    'v2_uncertain_count': summary['v2_uncertain'],
                })
            except Exception:
                pass

        return summary if detailed else summary['recovered']

    @staticmethod
    def _format_pseudo_bytes32(pseudonym: Any) -> bytes:
        """Convert V2 hex/string pseudonym into exact 32-byte value expected on-chain."""
        if isinstance(pseudonym, (bytes, bytearray)):
            raw = bytes(pseudonym)
            return raw[:32].rjust(32, b'\x00')
        s = str(pseudonym or '').strip()
        if s.startswith('0x'):
            s = s[2:]
        if s and len(s) <= 64 and all(c in '0123456789abcdefABCDEF' for c in s):
            return bytes.fromhex(s.zfill(64))
        return Web3.keccak(text=str(pseudonym or ''))

    @staticmethod
    def _find_v2_cast_event(
        contract: Any,
        onchain_eid: int,
        pseudo_bytes: bytes,
        sequence: int,
    ) -> Optional[Dict[str, Any]]:
        """Query BallotCastV2 logs for an authoritative match by (electionId, pseudonym, sequence)."""
        if not contract or not hasattr(contract, 'events'):
            return None
        try:
            ev_cls = contract.events.BallotCastV2
        except Exception:
            return None

        logs = None
        for kwargs in (
            {'from_block': 0, 'argument_filters': {'electionId': int(onchain_eid), 'pseudonym': pseudo_bytes}},
            {'fromBlock': 0, 'argument_filters': {'electionId': int(onchain_eid), 'pseudonym': pseudo_bytes}},
            {'from_block': 0},
            {'fromBlock': 0},
        ):
            try:
                logs = ev_cls.get_logs(**kwargs)
                break
            except TypeError:
                continue
            except Exception:
                continue

        for ev in (logs or []):
            args = ev.get('args', {}) if isinstance(ev, dict) else getattr(ev, 'args', {})
            ev_eid = args.get('electionId') if isinstance(args, dict) else getattr(args, 'electionId', None)
            ev_seq = args.get('sequence') if isinstance(args, dict) else getattr(args, 'sequence', None)
            ev_pseudo = args.get('pseudonym') if isinstance(args, dict) else getattr(args, 'pseudonym', None)
            if ev_seq != int(sequence):
                continue
            if ev_eid is not None and int(ev_eid) != int(onchain_eid):
                continue
            if ev_pseudo is not None and bytes(ev_pseudo) != pseudo_bytes:
                continue
            raw_tx = ev.get('transactionHash') if isinstance(ev, dict) else getattr(ev, 'transactionHash', None)
            tx_hex = None
            if isinstance(raw_tx, (bytes, bytearray)):
                h = raw_tx.hex()
                tx_hex = h if h.startswith('0x') else f'0x{h}'
            elif isinstance(raw_tx, str):
                tx_hex = raw_tx if raw_tx.startswith('0x') else f'0x{raw_tx}'
            blk = ev.get('blockNumber') if isinstance(ev, dict) else getattr(ev, 'blockNumber', None)
            return {'tx_hash': tx_hex, 'block_number': blk}
        return None

    @staticmethod
    def _confirm_recovered_v2_ballot(
        b2: BallotQueueV2,
        tx_hash: Optional[str],
        block_number: Optional[int],
        now: datetime,
        election: Optional[Election],
    ) -> None:
        """
        Transition an in-flight V2 ballot to CONFIRMED while preserving revote
        supersession order, deterministic receipt generation, and sealed Merkle immutability.
        """
        b2.state = 'CONFIRMED'
        if tx_hash:
            b2.tx_hash = tx_hash
        if block_number is not None:
            b2.block_number = int(block_number)
        b2.tx_confirmed_at = b2.tx_confirmed_at or now
        b2.error = None

        newer_confirmed = BallotQueueV2.query.filter(
            BallotQueueV2.election_id == int(b2.election_id),
            BallotQueueV2.pseudonym == str(b2.pseudonym),
            BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
            BallotQueueV2.sequence > int(b2.sequence),
            BallotQueueV2.id != b2.id,
        ).first()
        if newer_confirmed:
            b2.superseded = True
        else:
            b2.superseded = False
            mark_prior_v2_ballots_superseded(int(b2.election_id), str(b2.pseudonym), int(b2.sequence))

        merkle_sealed = bool(election and getattr(election, 'merkle_root', None))
        if not merkle_sealed:
            if not b2.receipt_code:
                ensure_v2_receipt_code(b2)
        elif not b2.receipt_code:
            RecoveryService.record_mismatch(
                election_id=int(b2.election_id) if str(b2.election_id).isdigit() else 0,
                issue_type='V2_LATE_RECOVERY_AFTER_MERKLE_SEAL',
                severity='HIGH',
                observed=f"ballot_v2_id={b2.id}, seq={b2.sequence}, tx={b2.tx_hash}",
                expected="Confirmed before Merkle root seal (sealed merkle_root left unchanged)",
                ballot_tx_id=b2.id,
                protocol_version='V2',
            )

    @staticmethod
    def _mark_v2_uncertain(
        b2: BallotQueueV2,
        summary: Dict[str, Any],
        issue_type: str,
        reason: str,
        observed: str,
        expected: str,
    ) -> None:
        """Mark a V2 ballot UNCERTAIN without ever silently confirming or double-casting."""
        prev_state = b2.state
        if prev_state != 'UNCERTAIN':
            b2.state = 'UNCERTAIN'
            b2.error = reason
            db.session.commit()
            RecoveryService.record_mismatch(
                election_id=int(b2.election_id) if str(b2.election_id).isdigit() else 0,
                issue_type=issue_type,
                severity='HIGH',
                observed=observed,
                expected=expected,
                ballot_tx_id=b2.id,
                protocol_version='V2',
            )
            summary['v2_uncertain'] += 1
            try:
                from app.audit import AuditLogger
                AuditLogger().log('BALLOT_V2_MARKED_UNCERTAIN', {
                    'ballot_v2_id': b2.id,
                    'election_id': b2.election_id,
                    'sequence': b2.sequence,
                    'tx_hash': b2.tx_hash,
                    'issue_type': issue_type,
                })
            except Exception:
                pass

    @staticmethod
    def _recover_v2_ballots(now: datetime, summary: Dict[str, Any]) -> None:
        """
        Discover and reconcile in-flight BallotQueueV2 records (QUEUED, SUBMITTED, PENDING, UNCERTAIN)
        strictly via election-scoped BlockchainV2Service & on-chain state.
        """
        v2_ballots = BallotQueueV2.query.filter(
            BallotQueueV2.state.in_(IN_FLIGHT_V2_STATES)
        ).order_by(
            BallotQueueV2.election_id.asc(),
            BallotQueueV2.sequence.asc(),
            BallotQueueV2.id.asc(),
        ).all()

        summary['v2_recovered'] = len(v2_ballots)
        summary['recovered'] += len(v2_ballots)
        if not v2_ballots:
            return

        from app.services.blockchain_v2_service import BlockchainV2Service

        election_ctx_cache: Dict[int, Dict[str, Any]] = {}

        def _get_v2_ctx(eid: int) -> Dict[str, Any]:
            if eid in election_ctx_cache:
                return election_ctx_cache[eid]

            election = db.session.get(Election, eid) if str(eid).isdigit() else None
            if not election:
                election = Election.query.filter(Election.election_id == str(eid)).first()

            svc = BlockchainV2Service.for_election(eid)
            w3_v2 = None
            contract_v2 = None
            onchain_eid = None
            is_connected = False
            eid_mismatch = False

            if svc and svc.contract_address:
                try:
                    w3_v2 = svc.get_web3()
                    is_connected = bool(w3_v2 and w3_v2.is_connected())
                    if is_connected:
                        contract_v2 = svc.get_contract()
                        onchain_eid = int(contract_v2.functions.electionId().call())
                        if onchain_eid != int(eid):
                            eid_mismatch = True
                            RecoveryService.record_mismatch(
                                election_id=int(eid),
                                issue_type='V2_CONTRACT_ELECTION_MISMATCH',
                                severity='HIGH',
                                observed=f"contract_eid={onchain_eid}",
                                expected=f"db_eid={eid}",
                                protocol_version='V2',
                            )
                except Exception as exc:
                    logger.warning("RecoveryService V2 context unavailable for election %s: %s", eid, exc)
                    is_connected = False
                    contract_v2 = None

            ctx = {
                'election': election,
                'svc': svc,
                'w3': w3_v2,
                'contract': contract_v2 if not eid_mismatch else None,
                'onchain_eid': onchain_eid,
                'is_connected': is_connected and not eid_mismatch,
            }
            election_ctx_cache[eid] = ctx
            return ctx

        for b2 in v2_ballots:
            try:
                ctx = _get_v2_ctx(int(b2.election_id))
                election = ctx['election']
                w3_v2 = ctx['w3']
                contract_v2 = ctx['contract']
                onchain_eid = ctx['onchain_eid']
                is_connected = ctx['is_connected']
                pseudo_bytes = RecoveryService._format_pseudo_bytes32(b2.pseudonym)

                # Case A: Ballot has a recorded tx_hash and V2 node is connected
                if b2.tx_hash and is_connected and w3_v2:
                    receipt = None
                    try:
                        receipt = w3_v2.eth.get_transaction_receipt(b2.tx_hash)
                    except Exception:
                        receipt = None

                    if receipt is not None:
                        status = receipt.get('status')
                        blk = receipt.get('blockNumber')
                        if status == 1:
                            RecoveryService._confirm_recovered_v2_ballot(
                                b2=b2,
                                tx_hash=b2.tx_hash,
                                block_number=blk,
                                now=now,
                                election=election,
                            )
                            db.session.commit()
                            summary['confirmed'] += 1
                            summary['v2_confirmed'] += 1
                            try:
                                from app.audit import AuditLogger
                                AuditLogger().log('BALLOT_V2_RECOVERED_CONFIRMED', {
                                    'ballot_v2_id': b2.id,
                                    'election_id': b2.election_id,
                                    'sequence': b2.sequence,
                                    'tx_hash': b2.tx_hash,
                                })
                            except Exception:
                                pass
                            continue
                        elif status == 0:
                            b2.state = 'REVERTED'
                            if blk is not None:
                                b2.block_number = int(blk)
                            b2.tx_failed_at = b2.tx_failed_at or now
                            b2.error = b2.error or 'TRANSACTION_REVERTED_ON_CHAIN'
                            db.session.commit()
                            RecoveryService.record_mismatch(
                                election_id=int(b2.election_id),
                                issue_type='V2_TX_REVERTED',
                                severity='MEDIUM',
                                observed=f"ballot_v2_id={b2.id}, tx={b2.tx_hash}, state=REVERTED",
                                expected="Successful tx status=1",
                                ballot_tx_id=b2.id,
                                protocol_version='V2',
                            )
                            summary['failed'] += 1
                            summary['v2_failed'] += 1
                            try:
                                from app.audit import AuditLogger
                                AuditLogger().log('BALLOT_V2_RECOVERED_REVERTED', {
                                    'ballot_v2_id': b2.id,
                                    'election_id': b2.election_id,
                                    'sequence': b2.sequence,
                                    'tx_hash': b2.tx_hash,
                                })
                            except Exception:
                                pass
                            continue

                    # Receipt not mined yet: inspect mempool
                    pending_tx = None
                    try:
                        pending_tx = w3_v2.eth.get_transaction(b2.tx_hash)
                    except Exception:
                        pending_tx = None

                    if pending_tx is not None:
                        summary['pending'] += 1
                        summary['v2_pending'] += 1
                        continue

                    # Dropped or uncertain without receipt: check on-chain sequence & BallotCastV2 logs
                    ev_match = None
                    onchain_seq = None
                    if contract_v2 is not None and onchain_eid is not None:
                        try:
                            onchain_seq = int(contract_v2.functions.voterSequence(pseudo_bytes).call())
                        except Exception:
                            onchain_seq = None
                        ev_match = RecoveryService._find_v2_cast_event(
                            contract_v2, onchain_eid, pseudo_bytes, int(b2.sequence)
                        )

                    if ev_match is not None:
                        RecoveryService._confirm_recovered_v2_ballot(
                            b2=b2,
                            tx_hash=ev_match.get('tx_hash') or b2.tx_hash,
                            block_number=ev_match.get('block_number'),
                            now=now,
                            election=election,
                        )
                        db.session.commit()
                        summary['confirmed'] += 1
                        summary['v2_confirmed'] += 1
                        try:
                            from app.audit import AuditLogger
                            AuditLogger().log('BALLOT_V2_RECOVERED_FROM_EVENT', {
                                'ballot_v2_id': b2.id,
                                'election_id': b2.election_id,
                                'sequence': b2.sequence,
                                'tx_hash': b2.tx_hash,
                            })
                        except Exception:
                            pass
                    elif onchain_seq is not None and onchain_seq >= int(b2.sequence):
                        RecoveryService._mark_v2_uncertain(
                            b2=b2,
                            summary=summary,
                            issue_type='V2_ONCHAIN_WITHOUT_RECEIPT',
                            reason=b2.error or 'ONCHAIN_SEQUENCE_ADVANCED_WITHOUT_TX_RECEIPT',
                            observed=f"ballot_v2_id={b2.id}, db_seq={b2.sequence}, onchain_seq={onchain_seq}, tx={b2.tx_hash}",
                            expected="Matching receipt or BallotCastV2 event log",
                        )
                    else:
                        RecoveryService._mark_v2_uncertain(
                            b2=b2,
                            summary=summary,
                            issue_type='V2_UNCERTAIN_TX',
                            reason=b2.error or 'TX_DROPPED_OR_NOT_FOUND_IN_MEMPOOL',
                            observed=f"ballot_v2_id={b2.id}, seq={b2.sequence}, tx={b2.tx_hash}",
                            expected="Mined receipt or pending mempool transaction",
                        )
                    continue

                # Case B: Ballot has NO tx_hash (interrupted broadcast or unbroadcast QUEUED)
                if not b2.tx_hash and is_connected and contract_v2 is not None and onchain_eid is not None:
                    onchain_seq = None
                    try:
                        onchain_seq = int(contract_v2.functions.voterSequence(pseudo_bytes).call())
                    except Exception:
                        onchain_seq = None
                    ev_match = RecoveryService._find_v2_cast_event(
                        contract_v2, onchain_eid, pseudo_bytes, int(b2.sequence)
                    )

                    if ev_match is not None:
                        RecoveryService._confirm_recovered_v2_ballot(
                            b2=b2,
                            tx_hash=ev_match.get('tx_hash'),
                            block_number=ev_match.get('block_number'),
                            now=now,
                            election=election,
                        )
                        db.session.commit()
                        summary['confirmed'] += 1
                        summary['v2_confirmed'] += 1
                        try:
                            from app.audit import AuditLogger
                            AuditLogger().log('BALLOT_V2_RECOVERED_FROM_EVENT', {
                                'ballot_v2_id': b2.id,
                                'election_id': b2.election_id,
                                'sequence': b2.sequence,
                                'tx_hash': b2.tx_hash,
                            })
                        except Exception:
                            pass
                        continue

                    if onchain_seq is not None and onchain_seq >= int(b2.sequence):
                        RecoveryService._mark_v2_uncertain(
                            b2=b2,
                            summary=summary,
                            issue_type='V2_ONCHAIN_WITHOUT_TX_HASH',
                            reason=b2.error or 'ONCHAIN_SEQUENCE_ADVANCED_WITHOUT_DB_TX_HASH',
                            observed=f"ballot_v2_id={b2.id}, db_seq={b2.sequence}, onchain_seq={onchain_seq}",
                            expected="Confirmed tx_hash or BallotCastV2 event match",
                        )
                        continue

                # Case C: Offline or onchain_seq < db_seq without event match
                if b2.state in ('SUBMITTED', 'PENDING') and not b2.tx_hash:
                    err_l = (b2.error or '').lower()
                    is_uncertain_err = any(
                        tok in err_l
                        for tok in ('uncertain', 'timeout', 'already known', 'nonce', 'replacement', 'gateway', 'reset', 'connection')
                    )
                    if is_uncertain_err:
                        RecoveryService._mark_v2_uncertain(
                            b2=b2,
                            summary=summary,
                            issue_type='V2_UNCERTAIN_TX',
                            reason=b2.error or 'UNCERTAIN_BROADCAST_WITHOUT_TX_HASH',
                            observed=f"ballot_v2_id={b2.id}, seq={b2.sequence}, state={b2.state}",
                            expected="Confirmed tx_hash or explicit operator resolution",
                        )
                    else:
                        b2.state = 'QUEUED'
                        b2.error = b2.error or 'Recovered from unbroadcast V2 SUBMITTED state'
                        db.session.commit()
                        summary['requeued'] += 1
                        summary['v2_requeued'] += 1
                elif b2.state == 'QUEUED':
                    summary['queued'] += 1
                    summary['v2_queued'] += 1
                    if election and election.status in ('CLOSED', 'FINALIZED'):
                        RecoveryService.record_mismatch(
                            election_id=int(b2.election_id) if str(b2.election_id).isdigit() else 0,
                            issue_type='STRANDED_QUEUED',
                            severity='HIGH',
                            observed=f"ballot_v2_id={b2.id}, seq={b2.sequence}, state=QUEUED",
                            expected="No unbroadcast queued ballots after election closure",
                            ballot_tx_id=b2.id,
                            protocol_version='V2',
                        )
                elif b2.state in ('SUBMITTED', 'PENDING'):
                    summary['pending'] += 1
                    summary['v2_pending'] += 1

            except Exception as v2_exc:
                logger.exception("Error recovering V2 ballot %s: %s", b2.id, v2_exc)
                db.session.rollback()

    @staticmethod
    def record_mismatch(
        election_id: int,
        issue_type: str,
        severity: str = 'INFO',
        observed=None,
        expected=None,
        ballot_tx_id: Optional[int] = None,
        protocol_version: str = 'V1',
        session=None,
    ) -> ReconciliationIssue:
        """
        Record a privacy-preserving reconciliation mismatch issue.
        Deduplicates open issues of the same type and election to prevent issue spam.
        """
        s = session or db.session
        existing = s.query(ReconciliationIssue).filter_by(
            election_id=election_id,
            issue_type=issue_type,
            status='OPEN',
        ).first()

        if existing:
            existing.observed_state = str(observed) if observed is not None else None
            existing.expected_state = str(expected) if expected is not None else None
            existing.severity = severity
            s.commit()
            return existing

        ri = ReconciliationIssue(
            election_id=election_id,
            issue_type=issue_type,
            severity=severity,
            protocol_version=protocol_version,
            ballot_tx_id=ballot_tx_id,
            observed_state=str(observed) if observed is not None else None,
            expected_state=str(expected) if expected is not None else None,
            status='OPEN',
        )
        s.add(ri)
        s.commit()

        try:
            from app.audit import AuditLogger
            AuditLogger(session=s).log('RECONCILIATION_MISMATCH_DETECTED', {
                'election_id': str(election_id),
                'issue_type': issue_type,
                'severity': severity,
                'issue_id': ri.id,
            })
        except Exception:
            pass

        return ri

    @staticmethod
    def is_idempotent_ok(election_id: Optional[int] = None) -> bool:
        """
        Genuinely verifies recovery idempotency:
        Executes a baseline recovery pass, followed by an immediate second pass.
        The second pass must find zero in-flight items to mutate (confirmed=0, requeued=0, failed=0),
        proving that repeated execution converges and produces no additional side effects.
        """
        # Pass 1: reconcile in-flight states
        RecoveryService.startup_recover()

        # Pass 2: verify state stability
        pass2 = RecoveryService.startup_recover(detailed=True)
        # Pass 2 must introduce zero state transitions
        is_stable = (
            pass2.get('confirmed', 0) == 0 and
            pass2.get('requeued', 0) == 0 and
            pass2.get('failed', 0) == 0 and
            pass2.get('v2_confirmed', 0) == 0 and
            pass2.get('v2_requeued', 0) == 0 and
            pass2.get('v2_failed', 0) == 0 and
            pass2.get('v2_uncertain', 0) == 0
        )
        return is_stable


# Re-export ReconciliationService for unified service access
from app.services.reconciliation_service import ReconciliationService

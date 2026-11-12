"""
Reconciliation Service - Phase 10
Vote Without Doubt

Provides authoritative DB <-> Blockchain state reconciliation:
1. Candidate tally verification (DB active finalized count vs smart contract getTally)
2. Distinct voter count verification (DB distinct voters vs smart contract distinctVoters)
3. Sequence consistency verification (DB active sequence vs smart contract getBallot)
4. Mismatch recording via ReconciliationIssue (privacy-preserving)
5. Audit logging for reconciliation events
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import current_app
from web3 import Web3

from app.extensions import db
from app.models import BallotRecord, Election, ReconciliationIssue
from app.relayer import Relayer

logger = logging.getLogger(__name__)


class ReconciliationService:
    @staticmethod
    def get_relayer_and_contract(contract_address: Optional[str] = None) -> tuple:
        """Helper to obtain connected Relayer and Contract instance."""
        target_contract = contract_address
        rpc_url = None
        relayer_account = None

        if current_app:
            target_contract = target_contract or current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS')
            rpc_url = current_app.config.get('BLOCKCHAIN_RPC_URL')
            relayer_account = current_app.config.get('RELAYER_ACCOUNT')

        relayer = Relayer(rpc_url=rpc_url, contract_address=target_contract, relayer_account=relayer_account)
        w3 = relayer.get_web3()

        contract = None
        if target_contract and w3 and w3.is_connected():
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(target_contract),
                abi=relayer._abi,
            )
        return relayer, w3, contract

    @staticmethod
    def reconcile_election(
        election_id: int,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compares on-chain state against database state for a specific election.
        Reconciles:
        - Candidate tallies
        - Distinct voter count
        - Sequences per voter
        - Stale in-flight ballots
        """
        from app.services.recovery import RecoveryService

        report: Dict[str, Any] = {
            'election_id': election_id,
            'status': 'CLEAN',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'tallies': {},
            'distinct_voters': {},
            'sequence_checks': 0,
            'issues_recorded': 0,
            'discrepancies': [],
        }

        election = None
        if isinstance(election_id, int) or str(election_id).isdigit():
            election = Election.query.filter(
                (Election.id == int(election_id)) | (Election.election_id == str(election_id))
            ).first()
        if not election:
            election = Election.query.filter_by(election_id=str(election_id)).first()

        int_eid = election.id if election else (int(election_id) if str(election_id).isdigit() else 0)
        target_ids = []
        if election:
            if election.election_id:
                target_ids.append(str(election.election_id))
            if election.id:
                target_ids.append(str(election.id))
        else:
            target_ids = [str(election_id)]

        on_chain_id = int(election.election_id) if (election and str(election.election_id).isdigit()) else int_eid

        from app.models.ballot_record_v2 import is_v2_election
        if election and is_v2_election(election):
            return ReconciliationService._reconcile_v2_election(
                election=election,
                int_eid=int_eid,
                on_chain_id=on_chain_id,
                report=report,
                contract_address=contract_address,
            )

        relayer, w3, contract = ReconciliationService.get_relayer_and_contract(contract_address)

        if not w3 or not w3.is_connected():
            logger.warning("Reconciliation skipped: Blockchain RPC unreachable.")
            report['status'] = 'RPC_UNREACHABLE'
            return report

        if not contract:
            logger.warning("Reconciliation skipped: No contract configured.")
            report['status'] = 'NO_CONTRACT'
            return report

        try:
            election_info = contract.functions.electionInfo(int(on_chain_id)).call()
        except Exception as exc:
            logger.error("Failed to query electionInfo for election %s: %s", election_id, exc)
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='ELECTION_QUERY_FAILED',
                severity='HIGH',
                observed=str(exc),
                expected="Valid on-chain election",
            )
            report['status'] = 'QUERY_ERROR'
            report['discrepancies'].append(str(exc))
            return report

        candidate_count = election_info[2]
        chain_distinct_voters = election_info[7]
        is_cancelled = election_info[6]

        # ------------------------------------------------------------------
        # 1. Tally Reconciliation
        # ------------------------------------------------------------------
        tally_mismatches = []
        for cand_idx in range(candidate_count):
            try:
                chain_tally = contract.functions.getTally(int(on_chain_id), cand_idx).call()
            except Exception as exc:
                logger.error("Failed to query getTally for candidate %s: %s", cand_idx, exc)
                chain_tally = -1

            # Count active, non-superseded, finalized, non-null ballots in DB
            db_tally = BallotRecord.query.filter(
                BallotRecord.election_id.in_(target_ids),
                BallotRecord.candidate == cand_idx,
                BallotRecord.state == 'FINALIZED',
                BallotRecord.superseded == False,
                BallotRecord.is_null == False,
            ).count()

            report['tallies'][str(cand_idx)] = {
                'chain': chain_tally,
                'db': db_tally,
                'match': (chain_tally == db_tally),
            }

            if chain_tally != db_tally and chain_tally >= 0:
                tally_mismatches.append(cand_idx)
                ri = RecoveryService.record_mismatch(
                    election_id=int_eid,
                    issue_type='TALLY_MISMATCH',
                    severity='HIGH',
                    observed=f"candidate={cand_idx}, db_count={db_tally}",
                    expected=f"chain_count={chain_tally}",
                )
                report['issues_recorded'] += 1
                report['discrepancies'].append(f"Tally mismatch for candidate {cand_idx}: DB={db_tally}, Chain={chain_tally}")

        # ------------------------------------------------------------------
        # 2. Distinct Voter Count Reconciliation
        # ------------------------------------------------------------------
        db_distinct_voters = db.session.query(
            db.func.count(db.distinct(BallotRecord.pseudonym))
        ).filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'FINALIZED',
        ).scalar() or 0

        voters_match = (chain_distinct_voters == db_distinct_voters)
        report['distinct_voters'] = {
            'chain': chain_distinct_voters,
            'db': db_distinct_voters,
            'match': voters_match,
        }

        if not voters_match:
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='DISTINCT_VOTER_MISMATCH',
                severity='HIGH',
                observed=f"db_distinct_voters={db_distinct_voters}",
                expected=f"chain_distinct_voters={chain_distinct_voters}",
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(f"Distinct voters mismatch: DB={db_distinct_voters}, Chain={chain_distinct_voters}")

        # ------------------------------------------------------------------
        # 3. Sequence Consistency Reconciliation (Per Active Voter)
        # ------------------------------------------------------------------
        distinct_pseuds = [
            r[0] for r in db.session.query(BallotRecord.pseudonym).filter(
                BallotRecord.election_id.in_(target_ids)
            ).distinct().all()
        ]

        for pseud in distinct_pseuds:
            report['sequence_checks'] += 1
            latest_finalized = BallotRecord.query.filter(
                BallotRecord.election_id.in_(target_ids),
                BallotRecord.pseudonym == pseud,
                BallotRecord.state == 'FINALIZED',
                BallotRecord.superseded == False,
            ).first()
            db_seq = latest_finalized.sequence if latest_finalized else 0

            try:
                pseudo_bytes = relayer._format_pseudonym(pseud)
                chain_ballot = contract.functions.getBallot(int(on_chain_id), pseudo_bytes).call()
                chain_seq = chain_ballot[0]
                chain_last_cand = chain_ballot[1]
                chain_is_null = chain_ballot[2]
                chain_exists = chain_ballot[3]
            except Exception as exc:
                logger.error("Failed to query getBallot for %s: %s", pseud, exc)
                continue

            if chain_exists and chain_seq != db_seq:
                RecoveryService.record_mismatch(
                    election_id=int_eid,
                    issue_type='SEQUENCE_MISMATCH',
                    severity='MEDIUM',
                    observed=f"pseudonym={pseud[:10]}..., db_seq={db_seq}",
                    expected=f"chain_seq={chain_seq}",
                    ballot_tx_id=latest_finalized.id if latest_finalized else None,
                )
                report['issues_recorded'] += 1
                report['discrepancies'].append(f"Sequence mismatch for voter: DB={db_seq}, Chain={chain_seq}")

        # ------------------------------------------------------------------
        # 4. Check for In-Flight & Stranded Ballots
        # ------------------------------------------------------------------
        queued_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'QUEUED',
        ).count()
        is_past_end = False
        if election and election.end_time:
            is_past_end = datetime.utcnow() >= election.end_time
        if queued_count > 0 and (is_past_end or (election and election.status in ('CLOSED', 'FINALIZED'))):
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='STRANDED_QUEUED',
                severity='HIGH',
                observed=f"stranded_queued_count={queued_count}",
                expected="0 queued ballots after closure",
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(f"{queued_count} stranded QUEUED ballots detected after closure")

        stale_threshold = datetime.utcnow() - timedelta(minutes=2)
        stale_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'SUBMITTED',
            BallotRecord.tx_broadcast_at < stale_threshold,
        ).count()

        if stale_count > 0:
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='STALE_SUBMITTED',
                severity='MEDIUM',
                observed=f"stale_in_flight_count={stale_count}",
                expected="0 stale submitted ballots",
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(f"{stale_count} stale SUBMITTED ballots detected")

        if report['discrepancies']:
            report['status'] = 'MISMATCH'
        else:
            report['status'] = 'CLEAN'

        try:
            from app.audit import AuditLogger
            AuditLogger().log('RECONCILIATION_COMPLETED', {
                'election_id': str(election_id),
                'status': report['status'],
                'issues_recorded': report['issues_recorded'],
            })
        except Exception:
            pass

        return report

    @staticmethod
    def _reconcile_v2_election(
        election: Election,
        int_eid: int,
        on_chain_id: int,
        report: Dict[str, Any],
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reconcile a V2 threshold ElGamal election against its dedicated EVotingBallotBoxV2 contract."""
        from app.models.ballot_record_v2 import (
            BallotQueueV2,
            VALID_V2_FINAL_STATES,
            get_active_v2_election_ballots,
        )
        from app.services.blockchain_v2_service import BlockchainV2Service
        from app.services.recovery import RecoveryService

        report['protocol_version'] = 'V2'
        svc = (
            BlockchainV2Service(contract_address=contract_address, election_id=int_eid)
            if contract_address
            else BlockchainV2Service.for_election(int_eid)
        )
        target_contract = svc.contract_address if svc else None
        if not target_contract:
            logger.warning("V2 reconciliation skipped for election %s: No dedicated V2 contract configured.", int_eid)
            report['status'] = 'NO_CONTRACT'
            return report

        w3 = None
        contract = None
        try:
            w3 = svc.get_web3()
            if w3 and w3.is_connected():
                contract = svc.get_contract()
        except Exception as exc:
            logger.warning("V2 reconciliation RPC error for election %s: %s", int_eid, exc)
            w3 = None

        if not w3 or not w3.is_connected() or not contract:
            report['status'] = 'RPC_UNREACHABLE'
            return report

        try:
            contract_eid = int(contract.functions.electionId().call())
        except Exception as exc:
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='V2_ELECTION_QUERY_FAILED',
                severity='HIGH',
                observed=str(exc),
                expected="Valid V2 contract electionId()",
                protocol_version='V2',
            )
            report['status'] = 'QUERY_ERROR'
            report['discrepancies'].append(str(exc))
            return report

        if contract_eid != int(int_eid):
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='V2_CONTRACT_ELECTION_MISMATCH',
                severity='HIGH',
                observed=f"contract_eid={contract_eid}",
                expected=f"db_eid={int_eid}",
                protocol_version='V2',
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(
                f"V2 contract electionId mismatch: DB={int_eid}, Chain={contract_eid}"
            )
            report['status'] = 'MISMATCH'
            return report

        # 1. Active Ballot / Distinct Voter Count Reconciliation (V2 homomorphic totalActiveBallots)
        chain_active_ballots = int(contract.functions.totalActiveBallots().call())
        active_v2_ballots = get_active_v2_election_ballots(int_eid)
        db_active_ballots = len(active_v2_ballots)
        voters_match = (chain_active_ballots == db_active_ballots)
        report['distinct_voters'] = {
            'chain': chain_active_ballots,
            'db': db_active_ballots,
            'match': voters_match,
        }
        if not voters_match:
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='V2_ACTIVE_BALLOT_COUNT_MISMATCH',
                severity='HIGH',
                observed=f"db_active_ballots={db_active_ballots}",
                expected=f"chain_active_ballots={chain_active_ballots}",
                protocol_version='V2',
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(
                f"V2 active ballot count mismatch: DB={db_active_ballots}, Chain={chain_active_ballots}"
            )

        # 2. Sequence Consistency per Pseudonym
        distinct_pseuds = [
            r[0] for r in db.session.query(BallotQueueV2.pseudonym).filter(
                BallotQueueV2.election_id == int_eid
            ).distinct().all()
        ]
        for pseud in distinct_pseuds:
            report['sequence_checks'] += 1
            confirmed_rows = BallotQueueV2.query.filter(
                BallotQueueV2.election_id == int_eid,
                BallotQueueV2.pseudonym == pseud,
                BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
            ).order_by(BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()).all()

            non_superseded_count = sum(1 for row in confirmed_rows if not row.superseded)
            if non_superseded_count > 1:
                RecoveryService.record_mismatch(
                    election_id=int_eid,
                    issue_type='V2_DUPLICATE_ACTIVE_BALLOT',
                    severity='HIGH',
                    observed=f"pseudonym={pseud[:10]}..., non_superseded={non_superseded_count}",
                    expected="At most 1 non-superseded confirmed ballot per pseudonym",
                    ballot_tx_id=confirmed_rows[0].id,
                    protocol_version='V2',
                )
                report['issues_recorded'] += 1
                report['discrepancies'].append("Duplicate active non-superseded V2 ballot rows in DB")

            latest_confirmed = confirmed_rows[0] if confirmed_rows else None
            db_seq = int(latest_confirmed.sequence) if latest_confirmed else 0

            try:
                pseudo_bytes = RecoveryService._format_pseudo_bytes32(pseud)
                chain_seq = int(contract.functions.voterSequence(pseudo_bytes).call())
            except Exception as exc:
                logger.error("Failed to query V2 voterSequence for %s: %s", pseud, exc)
                continue

            if chain_seq != db_seq:
                RecoveryService.record_mismatch(
                    election_id=int_eid,
                    issue_type='V2_SEQUENCE_MISMATCH',
                    severity='HIGH',
                    observed=f"pseudonym={pseud[:10]}..., db_seq={db_seq}",
                    expected=f"chain_seq={chain_seq}",
                    ballot_tx_id=latest_confirmed.id if latest_confirmed else None,
                    protocol_version='V2',
                )
                report['issues_recorded'] += 1
                report['discrepancies'].append(
                    f"V2 sequence mismatch for voter: DB={db_seq}, Chain={chain_seq}"
                )

        # 3. Stranded QUEUED and Stale In-Flight V2 Ballots
        queued_count = BallotQueueV2.query.filter(
            BallotQueueV2.election_id == int_eid,
            BallotQueueV2.state == 'QUEUED',
        ).count()
        is_past_end = bool(election.end_time and datetime.utcnow() >= election.end_time)
        if queued_count > 0 and (is_past_end or election.status in ('CLOSED', 'FINALIZED')):
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='STRANDED_QUEUED',
                severity='HIGH',
                observed=f"stranded_v2_queued_count={queued_count}",
                expected="0 queued V2 ballots after closure",
                protocol_version='V2',
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(f"{queued_count} stranded V2 QUEUED ballots detected after closure")

        stale_threshold = datetime.utcnow() - timedelta(minutes=2)
        stale_v2_count = BallotQueueV2.query.filter(
            BallotQueueV2.election_id == int_eid,
            BallotQueueV2.state.in_(('SUBMITTED', 'PENDING', 'UNCERTAIN')),
            db.or_(
                BallotQueueV2.tx_broadcast_at < stale_threshold,
                db.and_(
                    BallotQueueV2.tx_broadcast_at.is_(None),
                    BallotQueueV2.created_at < stale_threshold,
                ),
            ),
        ).count()
        if stale_v2_count > 0:
            RecoveryService.record_mismatch(
                election_id=int_eid,
                issue_type='STALE_V2_IN_FLIGHT',
                severity='MEDIUM',
                observed=f"stale_v2_in_flight_count={stale_v2_count}",
                expected="0 stale in-flight V2 ballots",
                protocol_version='V2',
            )
            report['issues_recorded'] += 1
            report['discrepancies'].append(f"{stale_v2_count} stale in-flight V2 ballots detected")

        report['status'] = 'MISMATCH' if report['discrepancies'] else 'CLEAN'
        try:
            from app.audit import AuditLogger
            AuditLogger().log('RECONCILIATION_COMPLETED', {
                'election_id': str(int_eid),
                'protocol_version': 'V2',
                'status': report['status'],
                'issues_recorded': report['issues_recorded'],
            })
        except Exception:
            pass
        return report

    @staticmethod
    def reconcile_all_active_elections(contract_address: Optional[str] = None) -> List[Dict[str, Any]]:
        """Run reconciliation across all active and closed (awaiting finalization) elections."""
        active_elections = Election.query.filter(Election.status.in_(['ACTIVE', 'OPEN', 'CLOSED'])).all()
        results = []
        for e in active_elections:
            try:
                eid = int(e.election_id if (e.election_id and str(e.election_id).isdigit()) else e.id)
                results.append(ReconciliationService.reconcile_election(eid, contract_address))
            except Exception as exc:
                logger.error("Error reconciling election %s: %s", e.id, exc)
        return results

    @staticmethod
    def get_open_issues(election_id: Optional[int] = None) -> List[ReconciliationIssue]:
        """Query open reconciliation issues."""
        query = ReconciliationIssue.query.filter_by(status='OPEN')
        if election_id is not None:
            target_eids = [int(election_id)] if str(election_id).isdigit() else []
            elec = Election.query.filter((Election.id == election_id) | (Election.election_id == str(election_id))).first()
            if elec:
                target_eids.append(elec.id)
                if elec.election_id and str(elec.election_id).isdigit():
                    target_eids.append(int(elec.election_id))
            if target_eids:
                query = query.filter(ReconciliationIssue.election_id.in_(list(set(target_eids))))
            else:
                query = query.filter_by(election_id=int(election_id) if str(election_id).isdigit() else 0)
        return query.order_by(ReconciliationIssue.id.desc()).all()

    @staticmethod
    def resolve_issue(issue_id: int, note: Optional[str] = None) -> Optional[ReconciliationIssue]:
        """Mark a reconciliation issue as resolved."""
        issue = db.session.get(ReconciliationIssue, issue_id)
        if not issue:
            return None
        issue.status = 'RESOLVED'
        issue.resolved_at = datetime.utcnow()
        issue.resolution_note = note or "Resolved by officer reconciliation."
        db.session.commit()

        try:
            from app.audit import AuditLogger
            AuditLogger().log('RECONCILIATION_ISSUE_RESOLVED', {
                'issue_id': issue.id,
                'election_id': str(issue.election_id),
                'issue_type': issue.issue_type,
            })
        except Exception:
            pass

        return issue

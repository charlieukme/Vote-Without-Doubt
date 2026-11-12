"""
Results Service - Phase 12
Vote Without Doubt - Public Results & Tally

Enforces:
1. Strict results gating: Results available ONLY when election is CLOSED or FINALIZED.
   Access while OPEN, DRAFT, PENDING_APPROVAL, or SCHEDULED is strictly blocked.
2. Canonical Phase 9 revoting semantics:
   - Sequence-aware latest-vote-wins per pseudonym.
   - Superseded ballots (superseded == True) excluded from tally.
   - Retracted/null ballots (is_null == True) counted in participation, excluded from candidate tallies.
   - Only finalized ballots (state == 'FINALIZED') counted.
3. Privacy preservation:
   - Zero voter identity, student ID, USN, email, or wallet address.
   - Zero plaintext pseudonyms.
   - Aggregated candidate counts and turnout metrics only.
4. On-chain cross-verification:
   - Compares DB tally against smart contract getTally() where blockchain is connected.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from web3 import Web3

from app.extensions import db
from app.models import BallotRecord, Election
from app.models.admin import Candidate
from app.models.ballot_record_v2 import BallotQueueV2, OfficerRegistrationV2
from app.models.reconciliation import ReconciliationIssue
from app.relayer import Relayer
from app.services.blockchain_v2_service import BlockchainV2Service

logger = logging.getLogger(__name__)


class ResultsService:
    @staticmethod
    def _resolve_election(election_id: Any) -> Optional[Election]:
        """Resolve election record by string identifier or integer primary key."""
        str_id = str(election_id)
        is_num = str_id.isdigit()
        return Election.query.filter(
            (Election.election_id == str_id) |
            (Election.id == int(str_id) if is_num else False)
        ).first()

    @staticmethod
    def _get_target_ids(election: Election) -> List[Any]:
        """Return list of election IDs used in ballot plane queries."""
        ids = [election.id, str(election.id)]
        if election.election_id:
            eid_str = str(election.election_id)
            if eid_str not in ids:
                ids.append(eid_str)
            if eid_str.isdigit():
                val = int(eid_str)
                if val not in ids:
                    ids.append(val)
        return ids

    @staticmethod
    def get_election_results(
        election_id: Any,
        contract_address: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Compute and return authoritative election results.

        Returns (success, message, data_dict).
        Fails if election does not exist or is not in CLOSED/FINALIZED state.
        """
        election = ResultsService._resolve_election(election_id)
        if not election:
            return False, "ELECTION_NOT_FOUND", {
                "error": "ELECTION_NOT_FOUND",
                "message": f"Election '{election_id}' does not exist.",
            }

        # ------------------------------------------------------------------
        # 1. State Gating: Results only accessible post-close
        # ------------------------------------------------------------------
        eff_status = election.effective_status
        if eff_status not in ('CLOSED', 'FINALIZED'):
            return False, "RESULTS_UNAVAILABLE", {
                "error": "RESULTS_UNAVAILABLE",
                "message": (
                    f"Results are withheld while election is '{eff_status}'. "
                    "Results become available only once the election is CLOSED or FINALIZED."
                ),
                "status": eff_status,
                "is_closed": False,
            }

        target_ids = ResultsService._get_target_ids(election)

        # ------------------------------------------------------------------
        # INT-003: Check if election uses V2 protocol (handles 0-ballot automated V2 elections too)
        # ------------------------------------------------------------------
        from app.models.ballot_record_v2 import VALID_V2_FINAL_STATES, is_v2_election
        is_v2 = is_v2_election(election)

        if is_v2:
            # 1B-V2. In-Flight Ballot Safety Guard for V2
            v2_queued = BallotQueueV2.query.filter(
                BallotQueueV2.election_id.in_(target_ids),
                BallotQueueV2.state == 'QUEUED',
            ).count()
            v2_submitted = BallotQueueV2.query.filter(
                BallotQueueV2.election_id.in_(target_ids),
                BallotQueueV2.state == 'SUBMITTED',
            ).count()
            v2_uncertain = BallotQueueV2.query.filter(
                BallotQueueV2.election_id.in_(target_ids),
                BallotQueueV2.state.in_(['PENDING', 'UNCERTAIN']),
            ).count()
            v2_pending = v2_queued + v2_submitted + v2_uncertain

            if v2_pending > 0:
                return False, "PROCESSING_PENDING_BALLOTS", {
                    "error": "PROCESSING_PENDING_BALLOTS",
                    "result_state": "PROCESSING_PENDING_BALLOTS",
                    "message": (
                        f"V2 ballot queue is actively draining on blockchain ({v2_pending} pending in-flight: "
                        f"{v2_queued} queued, {v2_submitted} submitted, {v2_uncertain} uncertain). Official results will be computed "
                        "once all pending ballots have settled."
                    ),
                    "election_id": election.election_id,
                    "internal_id": election.id,
                    "status": election.status,
                    "is_closed": True,
                    "results_available": False,
                    "pending_ballots_count": v2_pending,
                    "queued_count": v2_queued,
                    "submitted_count": v2_submitted,
                    "uncertain_count": v2_uncertain,
                }

            v2_addr = contract_address
            if not v2_addr:
                from app.services.blockchain_v2_service import load_deployment_checkpoint
                cp = load_deployment_checkpoint(election.id)
                if cp and cp.get('contract_address'):
                    v2_addr = Web3.to_checksum_address(cp['contract_address'])

            service = BlockchainV2Service(contract_address=v2_addr, election_id=election.id)
            v2_state = None
            on_chain_eid = None
            try:
                v2_state = service.get_election_state(v2_addr)
            except Exception as exc:
                logger.warning("Could not query V2 election state: %s", exc)

            # Strict contract-to-election binding verification
            if v2_state is not None:
                try:
                    on_chain_eid = service.get_election_id(v2_addr)
                    expected_eids = [election.id]
                    if election.election_id and str(election.election_id).isdigit():
                        expected_eids.append(int(election.election_id))
                    if on_chain_eid not in expected_eids:
                        logger.error("V2 contract electionId (%s) does not match election (%s)", on_chain_eid, election.id)
                        return False, "CONTRACT_ELECTION_MISMATCH", {
                            "error": "CONTRACT_ELECTION_MISMATCH",
                            "message": f"Smart contract at '{v2_addr}' is configured for election {on_chain_eid}, but results were requested for {election.election_id}.",
                        }
                except Exception as exc:
                    logger.warning("Could not verify on-chain electionId: %s", exc)

            # Authoritative candidate count from election or contract configuration (NO fallback to 2)
            candidate_count = election.candidate_count
            if not candidate_count and v2_state is not None:
                try:
                    candidate_count = service.get_candidate_count(v2_addr)
                except Exception:
                    pass

            if not candidate_count or candidate_count < 2:
                return False, "INVALID_CANDIDATE_COUNT", {
                    "error": "INVALID_CANDIDATE_COUNT",
                    "message": f"Authoritative candidate count for election '{election.election_id}' is unavailable or less than minimum required (2).",
                }

            # Candidate metadata validation - fail closed if any candidate metadata is missing
            all_candidates = Candidate.query.filter(
                (Candidate.election_id == str(election.election_id)) |
                (Candidate.election_id == str(election.id))
            ).order_by(Candidate.candidate_index.asc()).all()
            candidate_meta = {c.candidate_index: c for c in all_candidates}

            for idx in range(candidate_count):
                if idx not in candidate_meta:
                    return False, "MISSING_CANDIDATE_METADATA", {
                        "error": "MISSING_CANDIDATE_METADATA",
                        "message": f"Certified candidate profile metadata for candidate index {idx} in election '{election.election_id}' is missing.",
                    }

            # Check open reconciliation issues across both integer PK and slug IDs
            issue_eids = [election.id]
            if election.election_id and str(election.election_id).isdigit():
                issue_eids.append(int(election.election_id))
            open_issues = ReconciliationIssue.query.filter(
                ReconciliationIssue.election_id.in_(list(set(issue_eids))),
                ReconciliationIssue.status == 'OPEN',
            ).count()

            tallies_map = {}
            total_valid_votes = 0
            blockchain_verified = False

            if v2_state == 7:  # TallyFinalized
                try:
                    for idx in range(candidate_count):
                        ct = service.get_final_tally(idx, v2_addr)
                        tallies_map[idx] = ct
                        total_valid_votes += ct
                    blockchain_verified = True
                except Exception as exc:
                    logger.warning("Failed to retrieve V2 final tallies from contract: %s", exc)
                    blockchain_verified = False

            distinct_voters = db.session.query(
                db.func.count(db.distinct(BallotQueueV2.pseudonym))
            ).filter(
                BallotQueueV2.election_id.in_(target_ids),
                BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
            ).scalar() or 0

            # On-chain tally cross-verification against contract total active ballots & DB active distinct voters
            tally_matches_blockchain = False
            discrepancy_warning = None
            if blockchain_verified and v2_state == 7:
                try:
                    on_chain_total = service.get_total_active_ballots(v2_addr)
                    if total_valid_votes == on_chain_total and distinct_voters == on_chain_total:
                        tally_matches_blockchain = True
                    else:
                        tally_matches_blockchain = False
                        discrepancy_warning = (
                            f"Tally/ballot count mismatch: on-chain finalTallies sum={total_valid_votes}, "
                            f"totalActiveBallots={on_chain_total}, DB confirmed distinct voters={distinct_voters}."
                        )
                except Exception as exc:
                    logger.warning("Could not query on-chain totalActiveBallots: %s", exc)
                    tally_matches_blockchain = False
                    discrepancy_warning = f"Unable to verify on-chain totalActiveBallots: {exc}"

            reconciliation_clean = bool(open_issues == 0 and tally_matches_blockchain and v2_pending == 0)

            eligible_count = election.eligible_count or 0
            turnout_pct = round((distinct_voters / eligible_count) * 100, 2) if eligible_count > 0 else 0.0

            # If not finalized on-chain or blockchain verification failed, withhold official results
            if not blockchain_verified or v2_state != 7:
                if not v2_addr:
                    pending_notice = "No election-specific V2 smart contract deployment checkpoint was found for this election."
                elif eff_status == 'FINALIZED' and v2_state is None:
                    pending_notice = "Blockchain node is unreachable to verify finalized on-chain tallies."
                else:
                    pending_notice = "V2 election tally is awaiting officer decryption share submission and zero-knowledge verification."
                results_data = {
                    "election_id": election.election_id,
                    "internal_id": election.id,
                    "title": election.title,
                    "description": election.description,
                    "status": eff_status,
                    "result_state": "PROVISIONAL_UNFINALIZED",
                    "official_results": False,
                    "is_under_review": False,
                    "is_closed": True,
                    "is_finalized": False,
                    "candidate_count": candidate_count,
                    "eligible_count": eligible_count,
                    "total_distinct_voters": distinct_voters,
                    "total_valid_votes": 0,
                    "total_null_votes": 0,
                    "turnout_percentage": turnout_pct,
                    "candidates": [
                        {
                            "candidate_index": idx,
                            "name": candidate_meta[idx].name,
                            "department": candidate_meta[idx].department,
                            "votes": 0,
                            "percentage": 0.0,
                        }
                        for idx in range(candidate_count)
                    ],
                    "winners": [],
                    "is_tie": False,
                    "blockchain_verified": False,
                    "v2_state": v2_state,
                    "contract_address": v2_addr,
                    "on_chain_election_id": on_chain_eid,
                    "reconciliation_clean": (open_issues == 0),
                    "open_reconciliation_issues": open_issues,
                    "pending_ballots_count": 0,
                    "notice": pending_notice,
                    "v2_protocol": True,
                }
                return True, "RESULTS_COMPUTED", results_data

            # Finalized results computation
            candidate_results = []
            for idx in range(candidate_count):
                cand_obj = candidate_meta[idx]
                name = cand_obj.name
                dept = cand_obj.department
                votes = tallies_map.get(idx, 0)
                pct = round((votes / total_valid_votes) * 100, 2) if total_valid_votes > 0 else 0.0
                candidate_results.append({
                    "candidate_index": idx,
                    "name": name,
                    "department": dept,
                    "votes": votes,
                    "percentage": pct,
                })

            max_votes = -1
            winners = []
            if total_valid_votes > 0:
                for item in candidate_results:
                    if item["votes"] > max_votes:
                        max_votes = item["votes"]
                        winners = [{
                            "candidate_index": item["candidate_index"],
                            "name": item["name"],
                            "votes": item["votes"],
                        }]
                    elif item["votes"] == max_votes and max_votes > 0:
                        winners.append({
                            "candidate_index": item["candidate_index"],
                            "name": item["name"],
                            "votes": item["votes"],
                        })

            is_under_review = (open_issues > 0 or not tally_matches_blockchain)
            result_state = "RESULTS_UNDER_REVIEW" if is_under_review else "FINALIZED_RESULTS"
            official_results = not is_under_review

            results_data = {
                "election_id": election.election_id,
                "internal_id": election.id,
                "title": election.title,
                "description": election.description,
                "status": eff_status,
                "result_state": result_state,
                "official_results": official_results,
                "is_under_review": is_under_review,
                "is_closed": True,
                "is_finalized": (result_state == "FINALIZED_RESULTS"),
                "candidate_count": candidate_count,
                "eligible_count": eligible_count,
                "total_distinct_voters": distinct_voters,
                "total_valid_votes": total_valid_votes,
                "total_null_votes": 0,
                "turnout_percentage": turnout_pct,
                "candidates": candidate_results,
                "winners": winners if not is_under_review else [],
                "is_tie": (len(winners) > 1),
                "blockchain_verified": True,
                "blockchain_tallies": {str(k): v for k, v in tallies_map.items()},
                "tally_matches_blockchain": tally_matches_blockchain,
                "reconciliation_clean": reconciliation_clean,
                "open_reconciliation_issues": open_issues,
                "pending_ballots_count": 0,
                "contract_address": v2_addr,
                "on_chain_election_id": on_chain_eid,
                "v2_protocol": True,
            }
            if is_under_review:
                results_data["warning"] = discrepancy_warning or "Results are under review due to unresolved reconciliation issues or on-chain tally mismatch."
            return True, "RESULTS_COMPUTED", results_data

        # ------------------------------------------------------------------
        # 1B. In-Flight Ballot Safety Guard (V1)
        # ------------------------------------------------------------------
        queued_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'QUEUED',
        ).count()
        submitted_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'SUBMITTED',
        ).count()
        pending_count = queued_count + submitted_count

        if pending_count > 0:
            return False, "PROCESSING_PENDING_BALLOTS", {
                "error": "PROCESSING_PENDING_BALLOTS",
                "result_state": "PROCESSING_PENDING_BALLOTS",
                "message": (
                    f"Ballot queue is actively draining on blockchain ({pending_count} pending in-flight: "
                    f"{queued_count} queued, {submitted_count} submitted). Official results will be computed "
                    "once all pending ballots have settled."
                ),
                "election_id": election.election_id,
                "internal_id": election.id,
                "status": election.status,
                "is_closed": True,
                "results_available": False,
                "pending_ballots_count": pending_count,
                "queued_count": queued_count,
                "submitted_count": submitted_count,
            }

        # ------------------------------------------------------------------
        # 2. Canonical DB Tally (Phase 9 sequence & retraction semantics)
        # ------------------------------------------------------------------
        candidate_count = election.candidate_count or 0

        # Load candidates metadata
        all_candidates = Candidate.query.filter(
            (Candidate.election_id == str(election.election_id)) |
            (Candidate.election_id == str(election.id))
        ).order_by(Candidate.candidate_index.asc()).all()

        candidate_meta = {c.candidate_index: c for c in all_candidates}
        if not candidate_count and all_candidates:
            candidate_count = len(all_candidates)

        candidate_results = []
        total_valid_votes = 0
        tallies_map = {}

        for idx in range(candidate_count):
            cand_obj = candidate_meta.get(idx)
            name = cand_obj.name if cand_obj else f"Candidate {idx}"
            dept = cand_obj.department if cand_obj else None

            # Canonical tally rule:
            # Active, finalized, non-superseded, non-null ballots
            cand_votes = BallotRecord.query.filter(
                BallotRecord.election_id.in_(target_ids),
                BallotRecord.candidate == idx,
                BallotRecord.state == 'FINALIZED',
                BallotRecord.superseded == False,
                BallotRecord.is_null == False,
            ).count()

            tallies_map[idx] = cand_votes
            total_valid_votes += cand_votes

            candidate_results.append({
                "candidate_index": idx,
                "name": name,
                "department": dept,
                "votes": cand_votes,
                "percentage": 0.0,
            })

        # Calculate percentages
        if total_valid_votes > 0:
            for item in candidate_results:
                item["percentage"] = round((item["votes"] / total_valid_votes) * 100, 2)

        # Count null retractions (active, non-superseded, finalized with is_null=True)
        null_votes = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'FINALIZED',
            BallotRecord.superseded == False,
            BallotRecord.is_null == True,
        ).count()

        # Count distinct voters participating
        distinct_voters = db.session.query(
            db.func.count(db.distinct(BallotRecord.pseudonym))
        ).filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'FINALIZED',
        ).scalar() or 0

        # Turnout calculation
        eligible_count = election.eligible_count or 0
        turnout_pct = 0.0
        if eligible_count > 0:
            turnout_pct = round((distinct_voters / eligible_count) * 100, 2)

        # Winner determination
        max_votes = -1
        winners = []
        if total_valid_votes > 0:
            for item in candidate_results:
                if item["votes"] > max_votes:
                    max_votes = item["votes"]
                    winners = [{
                        "candidate_index": item["candidate_index"],
                        "name": item["name"],
                        "votes": item["votes"],
                    }]
                elif item["votes"] == max_votes and max_votes > 0:
                    winners.append({
                        "candidate_index": item["candidate_index"],
                        "name": item["name"],
                        "votes": item["votes"],
                    })

        # ------------------------------------------------------------------
        # 3. Cross-Check with Blockchain State
        # ------------------------------------------------------------------
        blockchain_verified = False
        chain_tallies = {}
        tally_matches_blockchain = True
        chain_distinct_voters = None

        try:
            relayer = Relayer(
                rpc_url=current_app.config.get('BLOCKCHAIN_RPC_URL') if current_app else None,
                contract_address=contract_address or (current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS') if current_app else None),
            )
            w3 = relayer.get_web3()
            addr = contract_address or (current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS') if current_app else None)
            if w3 and w3.is_connected() and addr:
                contract = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=relayer._abi)
                on_chain_id = int(election.election_id) if str(election.election_id).isdigit() else election.id

                e_info = contract.functions.electionInfo(on_chain_id).call()
                if e_info[1] > 0:  # end timestamp > 0 -> exists
                    chain_distinct_voters = e_info[7]
                    for idx in range(candidate_count):
                        ct = contract.functions.getTally(on_chain_id, idx).call()
                        chain_tallies[str(idx)] = ct
                        if ct != tallies_map.get(idx, 0):
                            tally_matches_blockchain = False

                    blockchain_verified = True
        except Exception as exc:
            logger.warning("Blockchain cross-check failed for election %s: %s", election_id, exc)
            blockchain_verified = False
            tally_matches_blockchain = False

        # Check reconciliation issues across both integer PK and slug IDs
        issue_eids = [election.id]
        if election.election_id and str(election.election_id).isdigit():
            issue_eids.append(int(election.election_id))
        open_issues = ReconciliationIssue.query.filter(
            ReconciliationIssue.election_id.in_(list(set(issue_eids))),
            ReconciliationIssue.status == 'OPEN',
        ).count()

        # Determine authoritative result state
        if election.status == 'FINALIZED' and tally_matches_blockchain and open_issues == 0:
            result_state = "FINALIZED_RESULTS"
            official_results = True
            is_under_review = False
        elif open_issues > 0 or not tally_matches_blockchain:
            result_state = "RESULTS_UNDER_REVIEW"
            official_results = False
            is_under_review = True
        else:
            result_state = "PROVISIONAL_UNFINALIZED"
            official_results = False
            is_under_review = False

        results_data = {
            "election_id": election.election_id,
            "internal_id": election.id,
            "title": election.title,
            "description": election.description,
            "status": election.status,
            "result_state": result_state,
            "official_results": official_results,
            "is_under_review": is_under_review,
            "is_closed": True,
            "is_finalized": (result_state == "FINALIZED_RESULTS"),
            "candidate_count": candidate_count,
            "eligible_count": eligible_count,
            "total_distinct_voters": distinct_voters,
            "total_valid_votes": total_valid_votes,
            "total_null_votes": null_votes,
            "turnout_percentage": turnout_pct,
            "candidates": candidate_results,
            "winners": winners,
            "is_tie": (len(winners) > 1),
            "blockchain_verified": blockchain_verified,
            "blockchain_tallies": chain_tallies,
            "tally_matches_blockchain": tally_matches_blockchain if blockchain_verified else None,
            "reconciliation_clean": (open_issues == 0 and tally_matches_blockchain is True),
            "open_reconciliation_issues": open_issues,
            "pending_ballots_count": pending_count,
        }

        if is_under_review:
            results_data["warning"] = "Results are under review due to unresolved reconciliation discrepancies or blockchain mismatch."
        elif result_state == "PROVISIONAL_UNFINALIZED":
            results_data["notice"] = "Election is closed and tallies match blockchain, awaiting two-officer finalization."

        return True, "RESULTS_COMPUTED", results_data

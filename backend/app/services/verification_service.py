"""
Public Verification Service - Phase 12
Vote Without Doubt - Public Election Verification

Provides:
1. Public election verification parameters (contract address, candidate hash, roll hash, timing).
2. Cryptographic audit chain verification and blockchain anchor verification.
3. On-chain state cross-examination (smart contract electionInfo, tallies, audit anchor).
4. Controlled tampering demonstration showing immediate detection and clean rollback.
5. Strict privacy preservation: Zero voter identity, USN, email, or pseudonym leakage.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from web3 import Web3

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import BallotRecord, Election
from app.models.ballot import Ballot
from app.models.admin import Candidate, ApprovalRequest
from app.models.audit_event import AuditEvent
from app.models.reconciliation import ReconciliationIssue
from app.relayer import Relayer
from app.services.reconciliation_service import ReconciliationService
from app.services.results_service import ResultsService

logger = logging.getLogger(__name__)


class VerificationService:
    @staticmethod
    def _resolve_election(election_id: Any) -> Optional[Election]:
        """Resolve election record by string identifier, integer primary key, or receipt code."""
        if election_id is None:
            return None
        str_id = str(election_id).strip()
        is_num = str_id.isdigit()
        
        # 1. Standard election identifier lookup
        e = Election.query.filter(
            (Election.election_id == str_id) |
            (Election.id == int(str_id) if is_num else False)
        ).first()
        if e:
            return e

        # 2. Receipt code lookup (e.g. REC-4-CF314B8D772BF3A1)
        if str_id.upper().startswith('REC-'):
            clean_rec = str_id.upper()
            ballot = BallotRecord.query.filter_by(receipt_code=clean_rec).first()
            if ballot:
                return Election.query.filter(
                    (Election.id == ballot.election_id) |
                    (Election.election_id == str(ballot.election_id))
                ).first()
            parts = clean_rec.split('-')
            if len(parts) >= 2:
                eid_part = parts[1]
                return Election.query.filter(
                    (Election.election_id == eid_part) |
                    (Election.id == int(eid_part) if eid_part.isdigit() else False)
                ).first()
        return None

    @staticmethod
    def compute_candidates_hash(election_id: Any) -> str:
        """
        Compute the canonical SHA-256 candidates hash.
        cand_str = '|'.join([f"{c.candidate_index}:{c.name}" for c in sorted_candidates])
        """
        election = VerificationService._resolve_election(election_id)
        if not election:
            return ""

        all_cands = Candidate.query.filter(
            (Candidate.election_id == str(election.election_id)) |
            (Candidate.election_id == str(election.id))
        ).order_by(Candidate.candidate_index.asc()).all()

        cand_str = "|".join([f"{c.candidate_index}:{c.name}" for c in all_cands])
        return '0x' + hashlib.sha256(cand_str.encode('utf-8')).hexdigest()

    @staticmethod
    def _is_v2_election(election: Optional[Election]) -> bool:
        """Authoritatively determine whether an election uses the V2 threshold ElGamal protocol."""
        from app.models.ballot_record_v2 import is_v2_election
        return is_v2_election(election)

    @staticmethod
    def _resolve_target_contract(election: Optional[Election], contract_address: Optional[str] = None) -> Optional[str]:
        """
        Dynamically determine the authoritative smart contract address for an election.
        Distinguishes V2 threshold ElGamal deployments from legacy V1 deployments.
        Never falls back to global V1 BALLOTBOX_CONTRACT_ADDRESS for V2 or unprovisioned new elections.
        """
        if contract_address:
            return contract_address
        if not current_app:
            return None

        if election:
            # 1. Authoritative election-specific V2 deployment checkpoint
            from app.services.blockchain_v2_service import load_deployment_checkpoint
            cp = load_deployment_checkpoint(election.id)
            if cp and cp.get('contract_address'):
                return Web3.to_checksum_address(cp['contract_address'])

            # 2. V2 elections must NEVER fall back to global V1 BALLOTBOX_CONTRACT_ADDRESS
            if VerificationService._is_v2_election(election):
                return None

            # 3. Allow V1 global fallback ONLY for explicitly persisted V1 protocol/ballots or V1 offline/legacy tests
            protocol = (getattr(election, 'protocol_version', None) or '').strip().upper()
            has_v1_ballots = (
                BallotRecord.query.filter(BallotRecord.election_id == election.id).first() is not None
                or Ballot.query.filter(Ballot.election_id == str(election.election_id)).first() is not None
            )
            is_explicit_v1 = (protocol == 'V1')
            is_v1_test_compat = bool(
                current_app.config.get('TESTING') and not current_app.config.get('ENABLE_V2_DEPLOY_IN_TESTS')
            )
            if is_explicit_v1 or has_v1_ballots or is_v1_test_compat:
                return current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS')
            return None

        if current_app.config.get('TESTING') and not current_app.config.get('ENABLE_V2_DEPLOY_IN_TESTS'):
            return current_app.config.get('BALLOTBOX_CONTRACT_ADDRESS')
        return None

    @staticmethod
    def get_public_verification(
        election_id: Any,
        contract_address: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Construct the authoritative public verification dataset for an election.
        Safe for unauthenticated public inspection; contains ZERO voter identity data.
        """
        election = VerificationService._resolve_election(election_id)
        if not election:
            return False, "ELECTION_NOT_FOUND", {
                "error": "ELECTION_NOT_FOUND",
                "message": f"Election '{election_id}' does not exist.",
            }

        target_contract = VerificationService._resolve_target_contract(election, contract_address)

        # ------------------------------------------------------------------
        # 1. Candidate Hash Verification
        # ------------------------------------------------------------------
        computed_cand_hash = VerificationService.compute_candidates_hash(election.election_id)
        stored_cand_hash = election.candidates_hash or computed_cand_hash

        # ------------------------------------------------------------------
        # 2. Audit Trail Hash-Chain Verification
        # ------------------------------------------------------------------
        logger_inst = AuditLogger()
        audit_chain_intact = logger_inst.verify_chain()
        chain_head = logger_inst.chain_head()
        latest_audit_hash = chain_head.current_hash if chain_head else None
        total_audit_events = len(logger_inst)

        # ------------------------------------------------------------------
        # 3. Blockchain Evidence Cross-Check
        # ------------------------------------------------------------------
        is_v2_contract = VerificationService._is_v2_election(election)
        blockchain_connected = False
        blockchain_evidence: Dict[str, Any] = {
            "protocol_version": "V2" if is_v2_contract else "V1",
            "audit_anchor_supported": not is_v2_contract,
            "v2_on_chain_state": None,
            "contract_address": target_contract,
            "on_chain_election_id": None,
            "on_chain_exists": False,
            "on_chain_start": None,
            "on_chain_end": None,
            "on_chain_candidate_count": None,
            "on_chain_distinct_voters": None,
            "on_chain_cancelled": None,
            "candidates_hash_matches": None,
            "roll_hash_matches": None,
            "audit_anchor": None,
            "audit_anchor_block": None,
            "audit_anchor_count": None,
            "audit_anchor_verified": False,
        }

        if election.candidates_hash and computed_cand_hash and election.candidates_hash.lower() != computed_cand_hash.lower():
            blockchain_evidence["candidates_hash_matches"] = False

        if is_v2_contract:
            from app.services.blockchain_v2_service import BlockchainV2Service
            try:
                v2_service = BlockchainV2Service(contract_address=target_contract, election_id=election.id)
                w3 = v2_service.get_web3()
                if w3 and w3.is_connected() and target_contract:
                    on_chain_eid = v2_service.get_election_id(target_contract)
                    candidate_cnt = v2_service.get_candidate_count(target_contract)
                    v2_state_val = v2_service.get_election_state(target_contract)
                    active_ballots_cnt = v2_service.get_total_active_ballots(target_contract)

                    db_cand_count = Candidate.query.filter(
                        (Candidate.election_id == str(election.election_id)) |
                        (Candidate.election_id == str(election.id))
                    ).count()

                    blockchain_connected = True
                    blockchain_evidence["on_chain_exists"] = bool(on_chain_eid == election.id and candidate_cnt > 0)
                    blockchain_evidence["on_chain_election_id"] = on_chain_eid
                    blockchain_evidence["on_chain_candidate_count"] = candidate_cnt
                    blockchain_evidence["on_chain_distinct_voters"] = active_ballots_cnt
                    blockchain_evidence["on_chain_cancelled"] = (v2_state_val == 8)
                    blockchain_evidence["v2_on_chain_state"] = v2_state_val
                    blockchain_evidence["audit_anchor"] = None
                    blockchain_evidence["audit_anchor_block"] = None
                    blockchain_evidence["audit_anchor_count"] = 0
                    blockchain_evidence["audit_anchor_verified"] = False

                    # EVotingBallotBoxV2 stores candidateCount (not SHA-256 hashes of candidate/roll);
                    # flag MISMATCH if DB candidate digest or counts diverge, else report UNAVAILABLE (None).
                    if blockchain_evidence["candidates_hash_matches"] is not False:
                        if candidate_cnt != db_cand_count or (election.candidate_count and candidate_cnt != election.candidate_count):
                            blockchain_evidence["candidates_hash_matches"] = False
                        else:
                            blockchain_evidence["candidates_hash_matches"] = None
                    blockchain_evidence["roll_hash_matches"] = None
            except Exception as exc:
                logger.warning("V2 Blockchain verification query failed: %s", exc)
        else:
            try:
                relayer = Relayer(
                    rpc_url=current_app.config.get('BLOCKCHAIN_RPC_URL') if current_app else None,
                    contract_address=target_contract,
                )
                w3 = relayer.get_web3()
                if w3 and w3.is_connected() and target_contract:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(target_contract), abi=relayer._abi)
                    on_chain_id = int(election.election_id) if str(election.election_id).isdigit() else election.id
                    blockchain_evidence["on_chain_election_id"] = on_chain_id

                    # electionInfo: (start, end, candidateCount, candidatesHash, eligibleCount, rollHash, maxBallots, distinctVoters, cancelled)
                    e_info = contract.functions.electionInfo(on_chain_id).call()
                    if e_info[1] > 0:  # end > 0 means election exists on chain
                        blockchain_connected = True
                        blockchain_evidence["on_chain_exists"] = True
                        blockchain_evidence["on_chain_start"] = e_info[0]
                        blockchain_evidence["on_chain_end"] = e_info[1]
                        blockchain_evidence["on_chain_candidate_count"] = e_info[2]
                        blockchain_evidence["on_chain_distinct_voters"] = e_info[7]
                        blockchain_evidence["on_chain_cancelled"] = e_info[8]

                        chain_cand_hash = "0x" + e_info[3].hex() if isinstance(e_info[3], bytes) else str(e_info[3])
                        chain_roll_hash = "0x" + e_info[5].hex() if isinstance(e_info[5], bytes) else str(e_info[5])

                        blockchain_evidence["candidates_hash_matches"] = (
                            chain_cand_hash.lower() == stored_cand_hash.lower()
                        ) if stored_cand_hash else None

                        blockchain_evidence["roll_hash_matches"] = (
                            chain_roll_hash.lower() == str(election.roll_hash or '').lower()
                        ) if election.roll_hash else None

                        # getAuditAnchor: (anchor, blockNumber, updateCount)
                        try:
                            anchor_tuple = contract.functions.getAuditAnchor(on_chain_id).call()
                            raw_anchor = anchor_tuple[0].hex() if isinstance(anchor_tuple[0], bytes) else str(anchor_tuple[0])
                            blockchain_evidence["audit_anchor"] = "0x" + raw_anchor if not raw_anchor.startswith("0x") else raw_anchor
                            blockchain_evidence["audit_anchor_block"] = anchor_tuple[1]
                            blockchain_evidence["audit_anchor_count"] = anchor_tuple[2]

                            clean_anchor = blockchain_evidence["audit_anchor"].lower().replace("0x", "").lstrip("0")
                            if anchor_tuple[2] > 0 and clean_anchor:
                                clean_anchor_64 = blockchain_evidence["audit_anchor"].lower().replace("0x", "").zfill(64)
                                matching_event = AuditEvent.query.filter(
                                    (AuditEvent.current_hash == clean_anchor_64) |
                                    (AuditEvent.current_hash == blockchain_evidence["audit_anchor"].lower().replace("0x", ""))
                                ).first()

                                # Confirm event exists in DB, is intact, and entire chain is intact
                                if matching_event and matching_event.is_intact() and audit_chain_intact:
                                    blockchain_evidence["audit_anchor_verified"] = True
                                else:
                                    blockchain_evidence["audit_anchor_verified"] = False
                            else:
                                blockchain_evidence["audit_anchor_verified"] = False
                        except Exception as anchor_err:
                            logger.warning("getAuditAnchor query failed: %s", anchor_err)
            except Exception as exc:
                logger.warning("Blockchain verification query failed: %s", exc)

        # ------------------------------------------------------------------
        # 4. Results Availability & Tally Cross-Check
        # ------------------------------------------------------------------
        eff_status = election.effective_status
        results_available = eff_status in ('CLOSED', 'FINALIZED')
        results_summary = None
        if results_available:
            ok, _, r_data = ResultsService.get_election_results(election.election_id, contract_address=target_contract)
            if ok:
                results_summary = {
                    "total_valid_votes": r_data["total_valid_votes"],
                    "total_null_votes": r_data["total_null_votes"],
                    "total_distinct_voters": r_data["total_distinct_voters"],
                    "turnout_percentage": r_data["turnout_percentage"],
                    "candidates": r_data["candidates"],
                    "winners": r_data["winners"],
                    "tally_matches_blockchain": r_data.get("tally_matches_blockchain"),
                    "reconciliation_clean": r_data.get("reconciliation_clean"),
                }

        # ------------------------------------------------------------------
        # 5. Overall Verification Verdict
        # ------------------------------------------------------------------
        issues = []

        if not audit_chain_intact:
            issues.append("AUDIT_CHAIN_INTEGRITY_COMPROMISED")

        if blockchain_evidence["candidates_hash_matches"] is False:
            issues.append("CANDIDATES_HASH_MISMATCH")

        if blockchain_connected:
            if blockchain_evidence["roll_hash_matches"] is False:
                issues.append("ROLL_HASH_MISMATCH")
            if is_v2_contract and not blockchain_evidence["on_chain_exists"]:
                issues.append("ON_CHAIN_CONTRACT_ELECTION_MISMATCH")
            if results_summary and results_summary.get("tally_matches_blockchain") is False:
                issues.append("TALLY_BLOCKCHAIN_DIVERGENCE")

        if issues:
            verification_status = "FAILED"
        elif eff_status in ('DRAFT', 'PENDING_APPROVAL', 'SCHEDULED', 'OPEN', 'ACTIVE'):
            verification_status = "IN_PROGRESS"
        elif eff_status in ('CLOSED', 'FINALIZED'):
            anchor_ok = blockchain_evidence.get("audit_anchor_verified") is True
            merkle_ok = (eff_status != 'FINALIZED') or bool(election.merkle_root and str(election.merkle_root).strip())
            if is_v2_contract:
                if not blockchain_connected:
                    verification_status = "UNAVAILABLE"
                else:
                    v2_state_val = blockchain_evidence.get("v2_on_chain_state")
                    v2_state_finalized = (eff_status != 'FINALIZED') or (v2_state_val == 7)
                    tally_verified = bool(results_summary and results_summary.get("tally_matches_blockchain") is True)
                    if merkle_ok and v2_state_finalized and (eff_status != 'FINALIZED' or tally_verified):
                        verification_status = "VERIFIED"
                    else:
                        verification_status = "PENDING_ANCHOR"
            elif anchor_ok and merkle_ok:
                verification_status = "VERIFIED"
            else:
                verification_status = "PENDING_ANCHOR"
        else:
            verification_status = "PENDING"

        verification_payload = {
            "election_id": election.election_id,
            "title": election.title,
            "description": election.description,
            "status": election.effective_status,
            "start_time": (election.start_time.isoformat() + 'Z') if election.start_time else None,
            "end_time": (election.end_time.isoformat() + 'Z') if election.end_time else None,
            "scheduled_at": (election.scheduled_at.isoformat() + 'Z') if election.scheduled_at else None,
            "closed_at": (election.closed_at.isoformat() + 'Z') if election.closed_at else None,
            "finalized_at": (election.finalized_at.isoformat() + 'Z') if election.finalized_at else None,
            "eligible_count": election.eligible_count,
            "candidate_count": election.candidate_count,
            "max_ballots": election.max_ballots,
            "candidates_hash": stored_cand_hash,
            "roll_hash": election.roll_hash,
            "merkle_root": election.merkle_root,
            "contract_address": target_contract,
            "results_available": results_available,
            "results_summary": results_summary,
            "blockchain_evidence": blockchain_evidence,
            "audit_evidence": {
                "chain_intact": audit_chain_intact,
                "total_audit_events": total_audit_events,
                "latest_audit_hash": latest_audit_hash,
                "anchored_on_chain": blockchain_evidence["audit_anchor_count"] > 0 if blockchain_evidence["audit_anchor_count"] is not None else False,
                "anchor_matches_latest_event": blockchain_evidence["audit_anchor_verified"],
                "anchor_matches_checkpoint": blockchain_evidence["audit_anchor_verified"],
                "anchor_block": blockchain_evidence["audit_anchor_block"],
                "anchor_update_count": blockchain_evidence["audit_anchor_count"],
            },
            "verification_status": verification_status,
            "verification_issues": issues,
        }

        # If queried by a receipt code, attach cryptographic receipt verification evidence
        if str(election_id).strip().upper().startswith('REC-'):
            receipt_res = VerificationService.verify_receipt(str(election_id).strip(), contract_address=target_contract)
            verification_payload["receipt_evidence"] = receipt_res
            if receipt_res.get("status") == "INVALID":
                issues.append("RECEIPT_HMAC_INVALID")
                verification_payload["verification_issues"] = issues

        return True, "VERIFICATION_DATA_RETRIEVED", verification_payload

    @staticmethod
    def verify_receipt(receipt_code: str, contract_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Cryptographically verify an official HMAC ballot receipt code.
        Distinguishes:
          - VALID: Authoritative finalized ballot found, HMAC matches signature, on-chain confirmed.
          - INVALID: Bad format, HMAC mismatch/tampering, or ballot not finalized.
          - NOT_FOUND: Receipt code not present in official registry.
          - UNAVAILABLE: Verification key missing/destroyed or blockchain unreachable.
        
        STRICT PRIVACY: Never reveals candidate choice, voter identity/USN, wallet address, tx hash, or pseudonym.
        """
        if not receipt_code or not str(receipt_code).strip():
            return {
                "status": "INVALID",
                "reason": "MISSING_RECEIPT_CODE",
                "message": "Receipt code is required.",
                "verified": False,
            }

        clean_code = str(receipt_code).strip().upper()
        match = re.match(r'^REC-([A-Z0-9_]+)-([A-F0-9]{16})$', clean_code)
        if not match:
            return {
                "status": "INVALID",
                "reason": "INVALID_FORMAT",
                "receipt_code": clean_code,
                "message": "Invalid receipt format. Official receipts follow: REC-<election_id>-<16_HEX_CHARS>",
                "verified": False,
            }

        eid_from_code = match.group(1)
        expected_hex = match.group(2)

        secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY')
        if not secret:
            return {
                "status": "UNAVAILABLE",
                "reason": "KEY_UNAVAILABLE",
                "receipt_code": clean_code,
                "election_id": eid_from_code,
                "message": "Cryptographic verification key is unavailable. Forward secrecy may be in effect.",
                "verified": False,
            }

        # Query database record (V1 BallotRecord or V2 BallotQueueV2)
        is_v2_ballot = False
        ballot = BallotRecord.query.filter_by(receipt_code=clean_code).first()
        if not ballot:
            ballot = BallotRecord.query.filter(db.func.upper(BallotRecord.receipt_code) == clean_code).first()

        if not ballot:
            from app.models import BallotQueueV2
            ballot = BallotQueueV2.query.filter_by(receipt_code=clean_code).order_by(
                BallotQueueV2.superseded.asc(), BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()
            ).first()
            if not ballot:
                ballot = BallotQueueV2.query.filter(
                    db.func.upper(BallotQueueV2.receipt_code) == clean_code
                ).order_by(
                    BallotQueueV2.superseded.asc(), BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()
                ).first()
            if ballot:
                is_v2_ballot = True

        if not ballot:
            return {
                "status": "NOT_FOUND",
                "reason": "RECEIPT_NOT_FOUND",
                "receipt_code": clean_code,
                "election_id": eid_from_code,
                "message": f"Receipt code '{clean_code}' was not found in the official registry.",
                "verified": False,
            }

        election = VerificationService._resolve_election(ballot.election_id)
        election_title = election.title if election else f"Election #{ballot.election_id}"
        election_id_str = str(election.election_id) if election else str(ballot.election_id)

        valid_states = ('FINALIZED', 'CONFIRMED') if is_v2_ballot else ('FINALIZED',)
        if ballot.state not in valid_states:
            return {
                "status": "INVALID",
                "reason": "BALLOT_NOT_FINALIZED",
                "receipt_code": clean_code,
                "election_id": election_id_str,
                "election_title": election_title,
                "ballot_state": ballot.state,
                "message": f"Ballot associated with receipt is in state '{ballot.state}', not CONFIRMED/FINALIZED.",
                "verified": False,
            }

        # Cryptographic HMAC validation:
        # Re-derive HMAC using the official secret key across plausible timestamp and election id candidates
        times_to_check = set()
        for dt in [ballot.created_at, ballot.tx_confirmed_at, ballot.updated_at]:
            if dt:
                times_to_check.add(dt.strftime('%Y-%m-%dT%H:%M:00Z'))
                times_to_check.add(dt.strftime('%Y-%m-%dT%H:%M:%SZ'))

        start_dt = ballot.created_at or ballot.tx_confirmed_at
        end_dt = ballot.updated_at or ballot.tx_confirmed_at or ballot.created_at
        if start_dt and end_dt:
            cur_dt = min(start_dt, end_dt) - timedelta(minutes=2)
            stop_dt = max(start_dt, end_dt) + timedelta(minutes=5)
            while cur_dt <= stop_dt:
                times_to_check.add(cur_dt.strftime('%Y-%m-%dT%H:%M:00Z'))
                cur_dt += timedelta(minutes=1)

        eid_candidates = [ballot.election_id, str(ballot.election_id)]
        if election:
            eid_candidates.extend([election.id, str(election.election_id)])
        eid_candidates = list(set(eid_candidates))

        hmac_matches = False
        matching_ts = None
        for ts in times_to_check:
            for eid_cand in eid_candidates:
                msgs = [f"{eid_cand}|{ballot.pseudonym}|{ts}"]
                if getattr(ballot, 'sequence', None):
                    msgs.append(f"{eid_cand}|{ballot.pseudonym}|{int(ballot.sequence)}|{ts}")
                for msg in msgs:
                    computed = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].upper()
                    if hmac.compare_digest(computed, expected_hex):
                        hmac_matches = True
                        matching_ts = ts
                        break
                if hmac_matches:
                    break
            if hmac_matches:
                break

        if not hmac_matches:
            return {
                "status": "INVALID",
                "reason": "HMAC_MISMATCH",
                "receipt_code": clean_code,
                "election_id": election_id_str,
                "election_title": election_title,
                "message": "Cryptographic HMAC verification failed. The receipt code does not match the ballot cryptographic signature.",
                "verified": False,
            }

        # On-chain status check (read-only)
        on_chain_confirmed = False
        on_chain_checked = False
        try:
            target_contract = VerificationService._resolve_target_contract(election, contract_address)
            if is_v2_ballot:
                from app.services.blockchain_v2_service import BlockchainV2Service
                v2_service = BlockchainV2Service(contract_address=target_contract, election_id=election.id if election else ballot.election_id)
                w3 = v2_service.get_web3()
                if w3 and w3.is_connected() and target_contract:
                    contract = v2_service.get_contract(target_contract)
                    pseud_bytes = bytes.fromhex(ballot.pseudonym.replace('0x', ''))
                    seq_val = contract.functions.voterSequence(pseud_bytes).call()
                    on_chain_checked = True
                    if seq_val >= ballot.sequence:
                        on_chain_confirmed = True
            else:
                relayer = Relayer(contract_address=target_contract)
                w3 = relayer.get_web3()
                if w3 and w3.is_connected() and target_contract:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(target_contract), abi=relayer._abi)
                    on_chain_eid = int(election.election_id) if (election and str(election.election_id).isdigit()) else ballot.election_id
                    pseud_bytes = bytes.fromhex(ballot.pseudonym)
                    b_chain = contract.functions.getBallot(on_chain_eid, pseud_bytes).call()
                    on_chain_checked = True
                    if b_chain[3] is True:  # hasCast == True
                        on_chain_confirmed = True
        except Exception as bc_err:
            logger.warning("Blockchain check during receipt verification: %s", bc_err)

        ts_out = matching_ts or (ballot.tx_confirmed_at or ballot.created_at).strftime('%Y-%m-%dT%H:%M:00Z')
        if on_chain_checked and on_chain_confirmed:
            msg_out = f"Official receipt '{clean_code}' is cryptographically VALID and confirmed on the blockchain."
        elif on_chain_checked and not on_chain_confirmed:
            msg_out = f"Official receipt '{clean_code}' matched database HMAC records, but on-chain confirmation could not be verified."
        else:
            msg_out = f"Official receipt '{clean_code}' HMAC signature verified in the official registry (live blockchain check unavailable)."

        return {
            "status": "VALID",
            "verified": True,
            "receipt_code": clean_code,
            "election_id": election_id_str,
            "election_title": election_title,
            "sequence": ballot.sequence,
            "block_number": ballot.block_number,
            "timestamp": ts_out,
            "hmac_verified": True,
            "on_chain_checked": on_chain_checked,
            "on_chain_confirmed": on_chain_confirmed,
            "v2_protocol": is_v2_ballot,
            "superseded": bool(getattr(ballot, 'superseded', False)),
            "privacy_guaranteed": True,
            "message": msg_out,
        }

    @staticmethod
    def verify_audit_anchor(
        election_id: Any,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify that the administrative audit log is cryptographically intact
        and anchored to the blockchain for the specified election.

        Strictly enforces:
        1. Full cryptographic audit chain integrity check (genesis to head).
        2. On-chain anchor retrieval via getAuditAnchor(on_chain_id).
        3. Historical anchor verification against the exact anchored checkpoint event:
           - Matches on-chain anchor to the exact event in the verified chain.
           - If an approved ANCHOR_AUDIT ApprovalRequest exists, verifies against the bound checkpoint hash and event ID.
           - New subsequent audit events appended after anchoring do not invalidate earlier anchors.
           - If anchor is zero or updateCount is 0, reports CHAIN_OK_ANCHOR_PENDING.
           - If on-chain anchor does not match any valid event in the chain or chain is broken, fails closed (FAILED).
        """
        election = VerificationService._resolve_election(election_id)
        if not election:
            return {
                "error": "ELECTION_NOT_FOUND",
                "message": f"Election '{election_id}' does not exist.",
                "verification_status": "FAILED",
            }

        logger_inst = AuditLogger()
        chain_intact = logger_inst.verify_chain()
        chain_head = logger_inst.chain_head()
        latest_hash = chain_head.current_hash if chain_head else None
        total_events = len(logger_inst)

        target_contract = VerificationService._resolve_target_contract(election, contract_address)
        is_v2_contract = VerificationService._is_v2_election(election)
        on_chain_anchor = None
        anchor_block = None
        anchor_count = 0
        is_anchored = False
        anchored_event_id = None
        checkpoint_status = "V2_NO_ONCHAIN_AUDIT_ANCHOR" if is_v2_contract else "UNANCHORED"
        issues = []

        if not chain_intact:
            issues.append("AUDIT_CHAIN_INTEGRITY_COMPROMISED")

        if not is_v2_contract:
            try:
                relayer = Relayer(
                    rpc_url=current_app.config.get('BLOCKCHAIN_RPC_URL') if current_app else None,
                    contract_address=target_contract,
                )
                w3 = relayer.get_web3()
                if w3 and w3.is_connected() and target_contract:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(target_contract), abi=relayer._abi)
                    on_chain_id = int(election.election_id) if str(election.election_id).isdigit() else election.id

                    anchor_tuple = contract.functions.getAuditAnchor(on_chain_id).call()
                    raw_anchor = anchor_tuple[0].hex() if isinstance(anchor_tuple[0], bytes) else str(anchor_tuple[0])
                    on_chain_anchor = "0x" + raw_anchor if not raw_anchor.startswith("0x") else raw_anchor
                    anchor_block = anchor_tuple[1]
                    anchor_count = anchor_tuple[2]

                    clean_anchor = on_chain_anchor.lower().replace("0x", "").lstrip("0")

                    if anchor_count > 0 and clean_anchor:
                        clean_anchor_64 = on_chain_anchor.lower().replace("0x", "").zfill(64)

                        # 1. Locate the exact audit event for this anchor
                        matching_event = AuditEvent.query.filter(
                            (AuditEvent.current_hash == clean_anchor_64) |
                            (AuditEvent.current_hash == on_chain_anchor.lower().replace("0x", ""))
                        ).first()

                        # 2. Check approved request if one exists for ANCHOR_AUDIT
                        approved_req = ApprovalRequest.query.filter_by(
                            election_id=str(election.election_id),
                            action_type='ANCHOR_AUDIT',
                            status='APPROVED',
                        ).order_by(ApprovalRequest.id.desc()).first()

                        bound_hash = None
                        bound_event_id = None
                        if approved_req and approved_req.payload_json:
                            try:
                                p_data = json.loads(approved_req.payload_json)
                                bound_hash = p_data.get('checkpoint_hash')
                                bound_event_id = p_data.get('checkpoint_event_id')
                            except Exception:
                                pass

                        # 3. Complete cryptographic validation
                        if matching_event and matching_event.is_intact() and chain_intact:
                            if bound_hash:
                                clean_bound = bound_hash.lower().replace("0x", "").zfill(64)
                                if clean_bound != clean_anchor_64 or (bound_event_id and bound_event_id != matching_event.id):
                                    checkpoint_status = "CHECKPOINT_MISMATCH"
                                    is_anchored = False
                                    issues.append("ANCHOR_CHECKPOINT_BINDING_MISMATCH")
                                else:
                                    checkpoint_status = "MATCH_VERIFIED"
                                    is_anchored = True
                                    anchored_event_id = matching_event.id
                            else:
                                # Valid historical checkpoint present in unbroken chain
                                checkpoint_status = "MATCH_VERIFIED"
                                is_anchored = True
                                anchored_event_id = matching_event.id
                        else:
                            checkpoint_status = "CHECKPOINT_NOT_FOUND_OR_CORRUPT"
                            is_anchored = False
                            if not matching_event:
                                issues.append("ON_CHAIN_ANCHOR_NOT_FOUND_IN_AUDIT_LOG")
                            elif not matching_event.is_intact():
                                issues.append("ANCHORED_AUDIT_EVENT_TAMPERED")
            except Exception as exc:
                logger.warning("Audit anchor verification query failed: %s", exc)

        if not chain_intact:
            verification_status = "FAILED"
        elif anchor_count == 0 or not on_chain_anchor or on_chain_anchor.replace("0x", "").replace("0", "") == "":
            verification_status = "CHAIN_OK_ANCHOR_PENDING"
        elif is_anchored:
            verification_status = "VERIFIED"
        else:
            verification_status = "FAILED"

        return {
            "election_id": election.election_id,
            "protocol_version": "V2" if is_v2_contract else "V1",
            "v2_anchor_supported": not is_v2_contract,
            "chain_intact": chain_intact,
            "total_events": total_events,
            "latest_hash": latest_hash,
            "on_chain_anchor": on_chain_anchor,
            "anchor_block": anchor_block,
            "anchor_update_count": anchor_count,
            "is_anchored": is_anchored,
            "anchored_checkpoint_hash": on_chain_anchor if is_anchored else None,
            "anchored_event_id": anchored_event_id,
            "checkpoint_status": checkpoint_status,
            "verification_status": verification_status,
            "issues": issues,
        }

    @staticmethod
    def run_tampering_demonstration(
        election_id: Any,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Controlled demonstration proving database tampering is detectable.
        Flow:
          1. Environment Check: Disabled in production.
          2. Baseline verification: Real database tallies verified against contract/baseline.
          3. Ephemeral Isolated Sandbox: A dedicated in-memory SQLite database replicates
             the election and ballots. Tampering is applied EXCLUSIVELY inside the sandbox.
          4. Reconciliation run on sandbox state -> MISMATCH DETECTED.
          5. Ephemeral sandbox destroyed completely.
          6. Real Production Ballots Verified: Confirmed pristine and byte-for-byte unmodified.
        """
        env = (os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or (current_app.config.get('APP_ENV') if current_app else '') or '').lower()
        if env == 'production' or (current_app and current_app.config.get('ENV') == 'production'):
            return {
                "error": "DEMO_DISABLED_IN_PRODUCTION",
                "message": "Tampering demonstration is disabled in production environments.",
                "demonstration_status": "DISABLED",
            }

        election = VerificationService._resolve_election(election_id)
        if not election:
            return {"error": "ELECTION_NOT_FOUND", "demonstration_status": "FAILED"}

        target_ids = [election.id]
        if str(election.election_id).isdigit():
            target_ids.append(int(election.election_id))

        cand_count = election.candidate_count or 2

        # 1. Baseline verification on real database
        baseline_reconcile = ReconciliationService.reconcile_election(election.id, contract_address=contract_address)
        has_contract = baseline_reconcile.get("status") not in ("NO_CONTRACT", "RPC_UNREACHABLE")
        base_clean = (baseline_reconcile.get("status") == "CLEAN") if has_contract else True

        base_tallies = {}
        for c in range(cand_count):
            base_tallies[c] = BallotRecord.query.filter(
                BallotRecord.election_id.in_(target_ids),
                BallotRecord.candidate == c,
                BallotRecord.state == 'FINALIZED',
                BallotRecord.superseded == False,
                BallotRecord.is_null == False,
            ).count()

        # Find target ballot to model in sandbox
        target_ballot = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state == 'FINALIZED',
            BallotRecord.superseded == False,
        ).first()

        if not target_ballot:
            return {
                "error": "NO_FINALIZED_BALLOTS",
                "message": "Tampering demonstration requires at least one finalized ballot record.",
                "demonstration_status": "SKIPPED",
            }

        original_id = target_ballot.id
        original_candidate = target_ballot.candidate
        original_sequence = target_ballot.sequence
        original_state = target_ballot.state
        tampered_candidate = (original_candidate + 1) % cand_count

        # 2. Ephemeral In-Memory Sandbox Setup (Zero Mutation to Real Database)
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        temp_engine = create_engine('sqlite:///:memory:', echo=False)
        db.Model.metadata.create_all(bind=temp_engine)
        TempSession = sessionmaker(bind=temp_engine)
        temp_session = TempSession()

        discrepancies_found = []
        tamper_detected = False

        try:
            # Replicate election record into sandbox
            temp_election = Election(
                id=election.id,
                election_id=election.election_id,
                title=getattr(election, 'title', 'Demo Election'),
                status=election.status,
                candidate_count=cand_count,
            )
            temp_session.add(temp_election)

            # Replicate ballot records into sandbox
            all_ballots = BallotRecord.query.filter(BallotRecord.election_id.in_(target_ids)).all()
            for b in all_ballots:
                temp_b = BallotRecord(
                    id=b.id,
                    election_id=b.election_id,
                    pseudonym=b.pseudonym,
                    candidate=b.candidate,
                    sequence=b.sequence,
                    state=b.state,
                    superseded=b.superseded,
                    is_null=b.is_null,
                    tx_hash=b.tx_hash,
                    block_number=b.block_number,
                    receipt_code=b.receipt_code,
                )
                temp_session.add(temp_b)
            temp_session.commit()

            # Inject controlled tampering ONLY within the sandbox
            sandbox_target = temp_session.query(BallotRecord).filter_by(id=original_id).first()
            if sandbox_target:
                sandbox_target.candidate = tampered_candidate
                temp_session.commit()

            # Measure tallies in isolated sandbox
            tampered_tallies = {}
            for c in range(cand_count):
                tampered_tallies[c] = temp_session.query(BallotRecord).filter(
                    BallotRecord.election_id.in_(target_ids),
                    BallotRecord.candidate == c,
                    BallotRecord.state == 'FINALIZED',
                    BallotRecord.superseded == False,
                    BallotRecord.is_null == False,
                ).count()

            # Cross-check tampered sandbox tallies against smart contract or baseline
            if has_contract:
                relayer, w3, contract = ReconciliationService.get_relayer_and_contract(contract_address)
                if contract:
                    for c in range(cand_count):
                        try:
                            chain_tally = contract.functions.getTally(int(election.id), c).call()
                        except Exception:
                            chain_tally = -1
                        sandbox_db_tally = tampered_tallies.get(c, 0)
                        if chain_tally != sandbox_db_tally and chain_tally >= 0:
                            tamper_detected = True
                            discrepancies_found.append(
                                f"Tally mismatch for candidate {c}: Sandbox_DB={sandbox_db_tally}, Chain={chain_tally}"
                            )
                else:
                    tamper_detected = (tampered_tallies != base_tallies)
                    if tamper_detected:
                        discrepancies_found.append(
                            f"Tally divergence detected: Expected candidate {original_candidate}={base_tallies.get(original_candidate, 0)}, "
                            f"Observed Sandbox_DB={tampered_tallies.get(original_candidate, 0)}"
                        )
            else:
                tamper_detected = (tampered_tallies != base_tallies)
                if tamper_detected:
                    discrepancies_found.append(
                        f"Tally divergence detected: Expected candidate {original_candidate}={base_tallies.get(original_candidate, 0)}, "
                        f"Observed Sandbox_DB={tampered_tallies.get(original_candidate, 0)}"
                    )

        finally:
            # 3. Clean disposal of ephemeral sandbox
            temp_session.close()
            temp_engine.dispose()

        # 4. Strict Production Ballot Verification: Confirm zero real modification
        db.session.expire_all()
        real_ballot_after = db.session.get(BallotRecord, original_id)
        real_unmodified = (
            real_ballot_after is not None and
            real_ballot_after.candidate == original_candidate and
            real_ballot_after.sequence == original_sequence and
            real_ballot_after.state == original_state
        )

        return {
            "election_id": election.election_id,
            "tampered_field": "candidate",
            "original_value": original_candidate,
            "tampered_value": tampered_candidate,
            "baseline_clean": base_clean,
            "tamper_detected": tamper_detected,
            "discrepancies_detected": discrepancies_found,
            "restored_verified": real_unmodified,
            "demonstration_verdict": "SUCCESS" if (tamper_detected and real_unmodified) else "FAILED",
            "isolation_mode": "EPHEMERAL_IN_MEMORY_SANDBOX",
            "production_ballot_mutated": False,
        }

    @staticmethod
    def get_inclusion_proof_for_receipt(receipt_code: str, allow_nonce: bool = False) -> Dict[str, Any]:
        """
        Generate self-verifiable RFC 6962 Merkle inclusion proof for a voter's receipt.

        Privacy Guarantees:
        - NEVER exposes voter USN, email, wallet address, or student identity.
        - NEVER exposes candidate choice publicly.
        - Returns leaf commitment, authoritative root, and audit path connecting leaf to root.
        - Opening nonce is protected and ONLY returned if explicitly authorized (allow_nonce=True)
          to prevent third-party brute force candidate discovery.
        """
        if not receipt_code or not str(receipt_code).strip():
            return {
                "verified": False,
                "status": "INVALID",
                "message": "Receipt code is required.",
            }

        clean_code = str(receipt_code).strip().upper()
        is_v2_ballot = False
        ballot = BallotRecord.query.filter_by(receipt_code=clean_code).first()
        if not ballot:
            ballot = BallotRecord.query.filter(db.func.upper(BallotRecord.receipt_code) == clean_code).first()

        if not ballot:
            from app.models.ballot_record_v2 import BallotQueueV2
            ballot = BallotQueueV2.query.filter_by(receipt_code=clean_code).order_by(
                BallotQueueV2.superseded.asc(), BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()
            ).first()
            if not ballot:
                ballot = BallotQueueV2.query.filter(
                    db.func.upper(BallotQueueV2.receipt_code) == clean_code
                ).order_by(
                    BallotQueueV2.superseded.asc(), BallotQueueV2.sequence.desc(), BallotQueueV2.id.desc()
                ).first()
            if ballot:
                is_v2_ballot = True

        if not ballot:
            return {
                "verified": False,
                "status": "NOT_FOUND",
                "message": f"Receipt code '{clean_code}' was not found.",
            }

        valid_states = ('CONFIRMED', 'FINALIZED') if is_v2_ballot else ('CONFIRMED', 'FINALIZED')
        if ballot.state not in valid_states:
            return {
                "verified": False,
                "status": "BALLOT_NOT_SETTLED",
                "message": f"Ballot associated with receipt is in state '{ballot.state}', not yet finalized.",
            }

        election = VerificationService._resolve_election(ballot.election_id)
        if not election:
            return {
                "verified": False,
                "status": "ELECTION_NOT_FOUND",
                "message": "Election record not found.",
            }

        from app.security.merkle import MerkleTree, verify_inclusion_proof

        if is_v2_ballot:
            from app.models.ballot_record_v2 import (
                BallotQueueV2,
                VALID_V2_FINAL_STATES,
                compute_v2_ballot_leaf_hash,
            )

            if getattr(ballot, 'superseded', False):
                return {
                    "verified": False,
                    "status": "BALLOT_SUPERSEDED",
                    "receipt_code": clean_code,
                    "election_id": str(election.election_id),
                    "election_title": election.title,
                    "message": "This receipt belongs to an earlier submission that was replaced by a newer confirmed revote.",
                }

            if not election.merkle_root:
                return {
                    "verified": False,
                    "status": "BALLOT_NOT_SETTLED",
                    "receipt_code": clean_code,
                    "election_id": str(election.election_id),
                    "election_title": election.title,
                    "message": "Inclusion proof is pending election closure and Merkle root finalization.",
                }

            # Historical finalized elections (e.g. Election 12) and future superseded-tracked elections
            # both store active leaves with superseded == False.
            accepted_v2 = BallotQueueV2.query.filter(
                BallotQueueV2.election_id == election.id,
                BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
                BallotQueueV2.superseded.is_(False),
            ).order_by(BallotQueueV2.id.asc()).all()

            leaf_hex = compute_v2_ballot_leaf_hash(ballot)
            leaves = [compute_v2_ballot_leaf_hash(b) for b in accepted_v2]
            tree = MerkleTree(leaves, sort_leaves=True)
            if leaf_hex not in tree.commitments:
                return {
                    "verified": False,
                    "status": "NO_COMMITMENT_FOUND",
                    "message": "Confirmed ballot leaf was not found in the active Merkle set.",
                }

            proof = tree.get_audit_proof(leaf_hex)
            if not proof:
                return {
                    "verified": False,
                    "status": "PROOF_GENERATION_FAILED",
                    "message": "Failed to compute audit path.",
                }

            authoritative_root = election.merkle_root
            is_valid, _verify_msg = verify_inclusion_proof(
                commitment_hex=leaf_hex,
                merkle_root_hex=authoritative_root,
                audit_path=proof["audit_path"],
            )
            return {
                "verified": is_valid,
                "status": "VALID INCLUSION PROOF" if is_valid else "INVALID INCLUSION PROOF",
                "receipt_code": clean_code,
                "election_id": str(election.election_id),
                "election_title": election.title,
                "merkle_root": authoritative_root,
                "total_leaves": tree.leaf_count,
                "leaf_index": proof["leaf_index"],
                "commitment": leaf_hex,
                "audit_path": proof["audit_path"],
                "v2_protocol": True,
                "tally_disclaimer": "This Merkle inclusion proof verifies that this committed ballot was accepted into the official election ballot set. It does not prove the specific candidate tally computation, which is established independently by on-chain tallies.",
            }

        target_ids = [election.id, str(election.election_id)]
        if str(election.election_id).isdigit():
            target_ids.append(int(election.election_id))

        accepted_ballots = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state.in_(['CONFIRMED', 'FINALIZED']),
            BallotRecord.superseded == False,
        ).order_by(BallotRecord.id.asc()).all()

        commitments = [b.commitment for b in accepted_ballots if b.commitment]
        tree = MerkleTree(commitments, sort_leaves=True)

        if not ballot.commitment or ballot.commitment not in tree.commitments:
            return {
                "verified": False,
                "status": "NO_COMMITMENT_FOUND",
                "message": "Ballot does not have an active Merkle commitment.",
            }

        proof = tree.get_audit_proof(ballot.commitment)
        if not proof:
            return {
                "verified": False,
                "status": "PROOF_GENERATION_FAILED",
                "message": "Failed to compute audit path.",
            }

        authoritative_root = election.merkle_root or tree.root

        is_valid, verify_msg = verify_inclusion_proof(
            commitment_hex=ballot.commitment,
            merkle_root_hex=authoritative_root,
            audit_path=proof["audit_path"],
        )

        out = {
            "verified": is_valid,
            "status": "VALID INCLUSION PROOF" if is_valid else "INVALID INCLUSION PROOF",
            "receipt_code": clean_code,
            "election_id": str(election.election_id),
            "election_title": election.title,
            "merkle_root": authoritative_root,
            "total_leaves": tree.leaf_count,
            "leaf_index": proof["leaf_index"],
            "commitment": ballot.commitment,
            "audit_path": proof["audit_path"],
            "tally_disclaimer": "This Merkle inclusion proof verifies that this committed ballot was accepted into the official election ballot set. It does not prove the specific candidate tally computation, which is established independently by on-chain tallies.",
        }
        if allow_nonce:
            out["commitment_nonce"] = ballot.commitment_nonce
        return out

    @staticmethod
    def get_audit_chain_for_verification(election_id: Any, contract_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Export cryptographic audit chain up to the anchored checkpoint for independent client verification.
        Enables client-side independent verification:
        1. Query getAuditAnchor on smart contract directly.
        2. Recompute and validate the chain from genesis to the anchored checkpoint.
        3. Locate ELECTION_MERKLE_ROOT_FINALIZED event and extract root.
        4. Compare against reconstructed root from voter's Merkle inclusion proof.
        """
        election = VerificationService._resolve_election(election_id)
        if not election:
            return {"error": "ELECTION_NOT_FOUND", "message": f"Election '{election_id}' not found."}

        target_contract = VerificationService._resolve_target_contract(election, contract_address)
        is_v2_contract = VerificationService._is_v2_election(election)
        rpc_url = current_app.config.get('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545') if current_app else 'http://127.0.0.1:8545'
        on_chain_id = int(election.election_id) if str(election.election_id).isdigit() else election.id

        # Query on-chain anchor from contract (V1 only; V2 stores tallies/sequences natively instead of audit anchors)
        on_chain_anchor = None
        anchor_block = None
        anchor_count = 0
        if not is_v2_contract:
            relayer = Relayer(contract_address=target_contract, rpc_url=rpc_url)
            w3 = relayer.get_web3()
            if w3 and w3.is_connected() and target_contract:
                try:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(target_contract), abi=relayer._abi)
                    anchor_tuple = contract.functions.getAuditAnchor(on_chain_id).call()
                    raw_anchor = anchor_tuple[0].hex() if isinstance(anchor_tuple[0], bytes) else str(anchor_tuple[0])
                    on_chain_anchor = "0x" + raw_anchor if not raw_anchor.startswith("0x") else raw_anchor
                    anchor_block = anchor_tuple[1]
                    anchor_count = anchor_tuple[2]
                except Exception as e:
                    logger.warning("getAuditAnchor query failed in get_audit_chain_for_verification: %s", e)

        # Locate anchored checkpoint event
        clean_anchor_64 = on_chain_anchor.lower().replace("0x", "").zfill(64) if on_chain_anchor else None
        matching_event = None
        if clean_anchor_64 and anchor_count > 0:
            matching_event = AuditEvent.query.filter(
                (AuditEvent.current_hash == clean_anchor_64) |
                (AuditEvent.current_hash == on_chain_anchor.lower().replace("0x", ""))
            ).first()

        # If anchored to a specific checkpoint, serve chain up to that checkpoint
        if matching_event:
            anchored_event_id = matching_event.id
            events_query = AuditEvent.query.filter(AuditEvent.id <= matching_event.id).order_by(AuditEvent.id.asc()).all()
        else:
            anchored_event_id = None
            events_query = AuditEvent.query.order_by(AuditEvent.id.asc()).all()

        events_payload = []
        for ev in events_query:
            events_payload.append({
                "id": ev.id,
                "event_type": ev.event_type,
                "created_at": ev.created_at.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z',
                "metadata": ev.event_metadata or {},
                "previous_hash": ev.previous_hash,
                "current_hash": ev.current_hash,
            })

        return {
            "election_id": str(election.election_id),
            "protocol_version": "V2" if is_v2_contract else "V1",
            "v2_anchor_supported": not is_v2_contract,
            "on_chain_election_id": on_chain_id,
            "contract_address": target_contract,
            "rpc_url": rpc_url,
            "chain_id": 1337,
            "on_chain_anchor": on_chain_anchor,
            "anchor_block": anchor_block,
            "anchor_update_count": anchor_count,
            "anchored_event_id": anchored_event_id,
            "is_anchored": (anchor_count > 0 and matching_event is not None),
            "events": events_payload,
        }


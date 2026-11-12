"""
Phase 10C Integration & Recovery Tests — V2 Contract Deployment Integration.

Covers:
1. Two-officer Four-Eyes approval flow & blocking direct /schedule and /open without approval.
2. Approval-time automatic V2 deployment + worker tick open with zero duplicate deployment.
3. Deferred worker-time deployment when RPC is offline during approval.
4. Uncertain broadcast recovery (TimeExhausted / ConnectionError): pre-broadcast tx_hash & nonce
   persistence, DEPLOYMENT_PENDING state, receipt reconciliation without duplicate broadcast.
5. Partial multi-step deployment recovery: BN254CDSVerifier confirmed, EVotingBallotBoxV2 pending,
   resuming at BALLOT_BOX without redeploying verifier.
6. Fail-closed verification on mismatched checkpoint / chain_id / electionId / candidateCount /
   missing finalizeZeroVoteElection, and strict non-overwrite guarantee for existing checkpoints.
7. Shared PersistentElectionLock preventing concurrent deployment races.
8. Strict V1 vs V2 contract resolution isolation (removing unsafe global V1 fallback for V2).
9. Explicit provisioning status distinction (NOT_DEPLOYED, DEPLOYMENT_PENDING, DEPLOYED_VERIFIED,
   DEPLOYMENT_FAILED).
10. Full isolated Hardhat EVM test compiling & deploying real BN254CDSVerifier + EVotingBallotBoxV2,
    worker auto-opening at start_time, and worker zero-vote finalization at end_time.
"""

from datetime import datetime, timedelta
import json
import os
import secrets
import socket
import subprocess
import threading
import time

import pytest
from web3 import Web3
from web3.exceptions import TimeExhausted, TransactionNotFound

from app.extensions import db
from app.models import BallotRecord, Election
from app.models.admin import AdminSession, AdminUser, ApprovalRequest, Candidate
from app.models.ballot_record_v2 import is_v2_election
from app.security.password import hash_password
from app.services import blockchain_v2_service as b2v
from app.services.blockchain_v2_service import (
    PROV_FAILED,
    PROV_NOT_DEPLOYED,
    PROV_PENDING,
    PROV_VERIFIED,
    BlockchainV2Service,
    get_provisioning_status,
    load_deployment_checkpoint,
    load_provisioning_state,
)
from app.services.election_admin_service import ElectionAdminService, TwoOfficerApprovalError
from app.services.election_lifecycle_worker import ElectionLifecycleWorker, PersistentElectionLock
from app.services.v2_election_manager import V2ElectionManager
from app.services.verification_service import VerificationService


ADMIN_KEY = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
ADMIN_ADDR = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
RELAYER_KEY = '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d'
RELAYER_ADDR = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'
VERIFIER_ADDR = '0x5FbDB2315678afecb367f032d93F642f64180aa3'
BALLOTBOX_ADDR = '0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512'

ZERO_VOTE_SELECTOR = Web3.keccak(text='finalizeZeroVoteElection()')[:4]
VALID_RUNTIME_CODE = b'\x60' * 6000 + ZERO_VOTE_SELECTOR + b'\x00' * 100
VERIFIER_RUNTIME_CODE = b'\x60' * 400


def _enable_v2_deploy(app, checkpoint_dir: str, monkeypatch):
    monkeypatch.setattr(b2v, '_DEFAULT_CHECKPOINT_DIR', str(checkpoint_dir))
    app.config['ENABLE_V2_DEPLOY_IN_TESTS'] = True
    app.config['BLOCKCHAIN_ENABLED'] = True
    app.config['ADMIN_PRIVATE_KEY'] = ADMIN_KEY
    app.config['RELAYER_PRIVATE_KEY'] = RELAYER_KEY


def _create_officers():
    o1 = AdminUser(
        admin_id='OFF_10C_1',
        name='Officer One',
        email='off1_10c@test.local',
        role='OFFICER',
        password_hash=hash_password('StrongPass!123'),
        is_active=True,
    )
    o2 = AdminUser(
        admin_id='OFF_10C_2',
        name='Officer Two',
        email='off2_10c@test.local',
        role='OFFICER',
        password_hash=hash_password('StrongPass!123'),
        is_active=True,
    )
    db.session.add_all([o1, o2])
    db.session.flush()
    return o1, o2


def _auth_header(admin_user: AdminUser) -> dict:
    token = secrets.token_hex(32)
    sess = AdminSession(
        session_token=token,
        admin_id=admin_user.id,
        role=admin_user.role,
        ip_address='127.0.0.1',
        expires_at=datetime.utcnow() + timedelta(hours=2),
        revoked=False,
    )
    db.session.add(sess)
    db.session.commit()
    return {'Authorization': f'Bearer {token}'}


def _create_draft_election(
    officer: AdminUser,
    eid_str: str = 'ELEC_10C_TEST',
    start_offset_minutes: int = 10,
    end_offset_minutes: int = 120,
    status: str = 'DRAFT',
) -> Election:
    now = datetime.utcnow()
    el = Election(
        election_id=eid_str,
        title=f'Test {eid_str}',
        status=status,
        start_time=now + timedelta(minutes=start_offset_minutes),
        end_time=now + timedelta(minutes=end_offset_minutes),
        candidate_count=2,
        eligible_count=20,
        created_by=officer.id,
    )
    db.session.add(el)
    db.session.flush()
    c1 = Candidate(election_id=el.election_id, candidate_index=0, name='Alice')
    c2 = Candidate(election_id=el.election_id, candidate_index=1, name='Bob')
    db.session.add_all([c1, c2])
    db.session.commit()
    return el


def _create_approved_schedule_request(election: Election, o1: AdminUser, o2: AdminUser) -> ApprovalRequest:
    req = ApprovalRequest(
        election_id=election.election_id,
        action_type='SCHEDULE_ELECTION',
        payload_hash=ElectionAdminService.compute_config_hash(election),
        requester_id=o1.id,
        approver_id=o2.id,
        status='APPROVED',
        payload_json='{}',
        expires_at=datetime.utcnow() + timedelta(hours=24),
        resolved_at=datetime.utcnow(),
    )
    db.session.add(req)
    db.session.commit()
    return req


class _FakeCall:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class _FakeTxBuilder:
    def __init__(self, payload: bytes, gas_est: int = 400_000):
        self._payload = payload
        self._gas_est = gas_est

    def estimate_gas(self, _params):
        return self._gas_est

    def build_transaction(self, params):
        tx = dict(params)
        tx['data'] = '0x' + self._payload.hex()
        tx['value'] = 0
        return tx


class _FakeContractFunctions:
    def __init__(self, state_ref: dict, owner_w3: '_FakeWeb3'):
        self._state = state_ref
        self._w3 = owner_w3

    def electionId(self):
        return _FakeCall(self._state['electionId'])

    def candidateCount(self):
        return _FakeCall(self._state['candidateCount'])

    def admin(self):
        return _FakeCall(self._state['admin'])

    def relayer(self):
        return _FakeCall(self._state['relayer'])

    def verifier(self):
        return _FakeCall(self._state['verifier'])

    def state(self):
        return _FakeCall(self._state['state'])

    def officer1Registered(self):
        return _FakeCall(self._state['o1_reg'])

    def officer2Registered(self):
        return _FakeCall(self._state['o2_reg'])

    def registerOfficer(self, officer_id, pub_key, pop):
        def _side_effect():
            if officer_id == 1:
                self._state['o1_reg'] = True
            else:
                self._state['o2_reg'] = True
            if self._state['o1_reg'] and self._state['o2_reg']:
                self._state['state'] = 3
        self._w3._queued_tx_side_effects.append(_side_effect)
        return _FakeTxBuilder(b'\xaa\x01')

    def openVoting(self):
        def _side_effect():
            self._state['state'] = 4
        self._w3._queued_tx_side_effects.append(_side_effect)
        return _FakeTxBuilder(b'\xaa\x02')

    def finalizeZeroVoteElection(self):
        return _FakeTxBuilder(b'\xaa\x03')


class _FakeContract:
    def __init__(self, address: str, state_ref: dict, owner_w3: '_FakeWeb3', abi=None, bytecode=''):
        self.address = Web3.to_checksum_address(address) if address else None
        self.functions = _FakeContractFunctions(state_ref, owner_w3)
        self._bytecode = bytecode

    def constructor(self, *args):
        return _FakeTxBuilder(b'\x60\x80' + bytes([len(args) + 1]))


class _FakeEth:
    def __init__(self, owner_w3: '_FakeWeb3'):
        self._w3 = owner_w3

    @property
    def chain_id(self):
        return self._w3.chain_id

    @property
    def block_number(self):
        return self._w3.block_number

    @property
    def gas_price(self):
        return 1_000_000_000

    @property
    def accounts(self):
        return [ADMIN_ADDR, RELAYER_ADDR]

    def get_transaction_count(self, address, block_identifier='latest'):
        return self._w3.confirmed_nonce if block_identifier == 'latest' else self._w3.pending_nonce

    def get_block(self, block_id):
        if block_id == 0:
            return {'hash': self._w3.genesis_hash}
        return {'hash': b'\xbb' * 32}

    def get_code(self, address):
        ck = Web3.to_checksum_address(address)
        return self._w3.codes.get(ck, b'')

    def send_raw_transaction(self, raw_tx):
        self._w3.broadcast_calls.append(raw_tx)
        idx = len(self._w3.broadcast_calls) - 1
        hook = self._w3.send_hooks.pop(0) if self._w3.send_hooks else None
        from eth_account._utils.legacy_transactions import serializable_unsigned_transaction_from_dict
        tx_hash = Web3.keccak(raw_tx)
        tx_hash_hex = ('0x' + tx_hash.hex()).lower()
        if hook is not None and callable(hook):
            hook(tx_hash_hex, idx)
        self._w3.pending_nonce += 1
        # Default receipt creation unless deferred
        step_mode = self._w3._queued_tx_side_effects.pop(0) if self._w3._queued_tx_side_effects else None
        if callable(step_mode):
            step_mode()
            self._w3.receipts[tx_hash_hex] = {'status': 1, 'blockNumber': self._w3.block_number}
            self._w3.confirmed_nonce += 1
        elif not self._w3.skip_auto_receipt_for_next:
            target = self._w3._next_deploy_addresses.pop(0)
            self._w3.block_number += 1
            self._w3.receipts[tx_hash_hex] = {
                'status': 1,
                'contractAddress': target,
                'blockNumber': self._w3.block_number,
            }
            self._w3.txs[tx_hash_hex] = {'hash': tx_hash, 'nonce': self._w3.confirmed_nonce}
            self._w3.confirmed_nonce += 1
        else:
            self._w3.skip_auto_receipt_for_next = False
        return tx_hash

    def wait_for_transaction_receipt(self, tx_hash, timeout=120):
        norm = b2v._normalize_hex_hash(tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash))
        hook = self._w3.wait_hooks.pop(0) if self._w3.wait_hooks else None
        if hook is not None and callable(hook):
            hook(norm)
        if norm in self._w3.receipts:
            return self._w3.receipts[norm]
        raise TimeExhausted(f"Timeout waiting for {norm}")

    def get_transaction_receipt(self, tx_hash):
        norm = b2v._normalize_hex_hash(tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash))
        if norm in self._w3.receipts:
            return self._w3.receipts[norm]
        raise TransactionNotFound(f"Receipt not found: {norm}")

    def get_transaction(self, tx_hash):
        norm = b2v._normalize_hex_hash(tx_hash.hex() if isinstance(tx_hash, bytes) else str(tx_hash))
        if norm in self._w3.txs:
            return self._w3.txs[norm]
        raise TransactionNotFound(f"Tx not found: {norm}")

    def contract(self, address=None, abi=None, bytecode=None):
        return _FakeContract(address, self._w3.contract_state, self._w3, abi=abi, bytecode=bytecode)


class _FakeWeb3:
    def __init__(
        self,
        election_id: int = 1,
        candidate_count: int = 2,
        chain_id: int = 31337,
        connected: bool = True,
        verifier_addr: str = VERIFIER_ADDR,
        ballotbox_addr: str = BALLOTBOX_ADDR,
    ):
        self.connected = connected
        self.chain_id = chain_id
        self.block_number = 5
        self.genesis_hash = b'\x11' * 32
        self.confirmed_nonce = 0
        self.pending_nonce = 0
        self.broadcast_calls = []
        self.send_hooks = []
        self.wait_hooks = []
        self.skip_auto_receipt_for_next = False
        self._queued_tx_side_effects = []
        self._next_deploy_addresses = [verifier_addr, ballotbox_addr]
        self.receipts = {}
        self.txs = {}
        self.codes = {
            Web3.to_checksum_address(verifier_addr): VERIFIER_RUNTIME_CODE,
            Web3.to_checksum_address(ballotbox_addr): VALID_RUNTIME_CODE,
        }
        self.contract_state = {
            'electionId': election_id,
            'candidateCount': candidate_count,
            'admin': Web3.to_checksum_address(ADMIN_ADDR),
            'relayer': Web3.to_checksum_address(RELAYER_ADDR),
            'verifier': Web3.to_checksum_address(verifier_addr),
            'state': 0,
            'o1_reg': False,
            'o2_reg': False,
        }
        self.eth = _FakeEth(self)

    def is_connected(self):
        return self.connected


# =============================================================================
# Test 1: Four-Eyes Governance & /open /schedule Enforcement
# =============================================================================

def test_four_eyes_blocks_self_approval_and_direct_open_or_schedule(app, client, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, o2 = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_FOUR_EYES')

    h1 = _auth_header(o1)
    # Officer 1 requests schedule approval
    req = ElectionAdminService.request_approval(el.election_id, 'SCHEDULE_ELECTION', o1)
    assert req is not None

    # Self-approval MUST fail
    with pytest.raises(TwoOfficerApprovalError):
        ElectionAdminService.approve_request(req.id, o1)

    # Direct /schedule without APPROVED ApprovalRequest MUST fail (403 FOUR_EYES_APPROVAL_REQUIRED)
    res_sched = client.post(f'/api/admin/elections/{el.election_id}/schedule', headers=h1)
    assert res_sched.status_code == 403
    assert res_sched.get_json()['error'] == 'FOUR_EYES_APPROVAL_REQUIRED'

    # Direct /open in DRAFT MUST fail (400 INVALID_LIFECYCLE_TRANSITION)
    res_open_draft = client.post(f'/api/admin/elections/{el.election_id}/open', headers=h1)
    assert res_open_draft.status_code == 400
    assert res_open_draft.get_json()['error'] == 'INVALID_LIFECYCLE_TRANSITION'

    # Even if an election were manually in SCHEDULED without an APPROVED request, /open blocks with 403
    el.status = 'SCHEDULED'
    db.session.commit()
    res_open_unapproved = client.post(f'/api/admin/elections/{el.election_id}/open', headers=h1)
    assert res_open_unapproved.status_code == 403
    assert res_open_unapproved.get_json()['error'] == 'FOUR_EYES_APPROVAL_REQUIRED'

    # Officer 2 approval acceptance enables authorized /schedule and /open
    el.status = 'PENDING_APPROVAL'
    db.session.commit()
    fake_w3 = _FakeWeb3(election_id=el.id, candidate_count=2)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: fake_w3)
    ok_appr, msg_appr = ElectionAdminService.approve_request(req.id, o2)
    assert ok_appr, msg_appr

    h2 = _auth_header(o2)
    res_sched_ok = client.post(f'/api/admin/elections/{el.election_id}/schedule', headers=h2)
    assert res_sched_ok.status_code == 200
    assert res_sched_ok.get_json()['status'] == 'SCHEDULED'

    res_open_ok = client.post(f'/api/admin/elections/{el.election_id}/open', headers=h2)
    assert res_open_ok.status_code == 200
    assert res_open_ok.get_json()['status'] == 'OPEN'


# =============================================================================
# Test 2: Approval-Time Auto-Deployment + Worker Auto-Open (No Duplicate Deploy)
# =============================================================================

def test_approval_auto_deploys_v2_and_worker_opens_without_duplicate_deploy(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, o2 = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_AUTO_DEPLOY', start_offset_minutes=5)
    fake_w3 = _FakeWeb3(election_id=el.id, candidate_count=2)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: fake_w3)

    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_NOT_DEPLOYED

    req = ElectionAdminService.request_approval(el.election_id, 'SCHEDULE_ELECTION', o1)
    ok, msg = ElectionAdminService.approve_request(req.id, o2)
    assert ok, msg

    db.session.refresh(el)
    assert el.status == 'SCHEDULED'
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_VERIFIED

    cp = load_deployment_checkpoint(el.id, checkpoint_dir=str(tmp_path))
    assert cp is not None
    assert cp['election_id'] == el.id
    assert cp['contract_address'] == Web3.to_checksum_address(BALLOTBOX_ADDR)
    assert cp['verifier_address'] == Web3.to_checksum_address(VERIFIER_ADDR)
    assert cp['relayer_address'] == Web3.to_checksum_address(RELAYER_ADDR)
    assert cp['candidate_count'] == 2
    assert cp['chain_id'] == 31337
    # 2 txs at approval: BN254CDSVerifier + EVotingBallotBoxV2
    assert len(fake_w3.broadcast_calls) == 2

    # Advance start_time into window & tick worker -> registers officers (2 txs) + openVoting (1 tx), ZERO new deploys!
    el.start_time = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    summary = ElectionLifecycleWorker(app=app).tick()
    assert summary['opened'] == 1, summary

    db.session.refresh(el)
    assert el.status == 'OPEN'
    assert len(fake_w3.broadcast_calls) == 5  # 2 deploy + 2 registerOfficer + 1 openVoting


# =============================================================================
# Test 3: Offline Approval Deferred -> Worker Deploys & Opens Once Later
# =============================================================================

def test_offline_approval_defers_provisioning_and_worker_deploys_once_when_online(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, o2 = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_OFFLINE_APPROVE', start_offset_minutes=5)

    offline_w3 = _FakeWeb3(election_id=el.id, candidate_count=2, connected=False)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: offline_w3)

    req = ElectionAdminService.request_approval(el.election_id, 'SCHEDULE_ELECTION', o1)
    ok, msg = ElectionAdminService.approve_request(req.id, o2)
    assert ok, msg  # Governance approval still succeeds

    db.session.refresh(el)
    assert el.status == 'SCHEDULED'
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_NOT_DEPLOYED
    assert load_deployment_checkpoint(el.id, checkpoint_dir=str(tmp_path)) is None

    # Even if start_time is reached while RPC is STILL offline, worker MUST NOT mark OPEN
    el.start_time = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    summary_offline = ElectionLifecycleWorker(app=app).tick()
    assert summary_offline['opened'] == 0
    db.session.refresh(el)
    assert el.status == 'SCHEDULED'

    # Now RPC comes online -> worker provisions V2 contract ONCE and opens election
    online_w3 = _FakeWeb3(election_id=el.id, candidate_count=2, connected=True)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: online_w3)

    summary_online = ElectionLifecycleWorker(app=app).tick()
    assert summary_online['opened'] == 1, summary_online
    db.session.refresh(el)
    assert el.status == 'OPEN'
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_VERIFIED
    assert len(online_w3.broadcast_calls) == 5


# =============================================================================
# Test 4: Uncertain Broadcast Timeout Recovery (No Duplicate Contract Deploy)
# =============================================================================

def test_uncertain_broadcast_recovery_reconciles_receipt_without_duplicate_deploy(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, o2 = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_UNCERTAIN', start_offset_minutes=-2, status='SCHEDULED')
    _create_approved_schedule_request(el, o1, o2)

    fake_w3 = _FakeWeb3(election_id=el.id, candidate_count=2)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: fake_w3)

    # Simulate Verifier succeeding cleanly (tx 0), and BallotBox broadcast timing out AFTER mining on node
    captured_box_hash = {}

    def _timeout_after_secret_mine(tx_hash_hex, idx):
        if idx == 1:
            captured_box_hash['hash'] = tx_hash_hex
            # Node ACTUALLY mined it at block 7, but network dropped response before returning!
            fake_w3.receipts[tx_hash_hex] = {
                'status': 1,
                'contractAddress': BALLOTBOX_ADDR,
                'blockNumber': 7,
            }
            fake_w3.block_number = 7
            fake_w3.txs[tx_hash_hex] = {'hash': tx_hash_hex, 'nonce': 1}
            fake_w3.confirmed_nonce += 1
            fake_w3.skip_auto_receipt_for_next = True
            raise TimeExhausted("Simulated timeout during send_raw_transaction")

    fake_w3.send_hooks = [None, _timeout_after_secret_mine]

    ok1, msg1, cp1 = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert not ok1
    assert 'DEPLOYMENT_PENDING' in msg1
    assert cp1 is None
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_PENDING

    prov_state = load_provisioning_state(el.id, checkpoint_dir=str(tmp_path))
    assert prov_state['tx_hash'] == captured_box_hash['hash']
    assert prov_state['sender_nonce'] == 1
    assert prov_state['pending_step'] == 'BALLOT_BOX'
    assert prov_state['verifier_address'] == Web3.to_checksum_address(VERIFIER_ADDR)
    assert len(fake_w3.broadcast_calls) == 2

    # Retry -> MUST reconcile existing receipt for captured_box_hash without ANY new broadcast!
    ok2, msg2, cp2 = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert ok2, msg2
    assert msg2 == PROV_VERIFIED
    assert cp2 is not None
    assert cp2['contract_address'] == Web3.to_checksum_address(BALLOTBOX_ADDR)
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_VERIFIED
    assert len(fake_w3.broadcast_calls) == 2  # ZERO duplicate broadcasts!


# =============================================================================
# Test 5: Partial Step Failure (Verifier Confirmed, BallotBox Still Pending)
# =============================================================================

def test_partial_step_pending_mempool_stays_pending_then_resumes_at_ballot_box(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, o2 = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_PARTIAL', start_offset_minutes=-2, status='SCHEDULED')
    _create_approved_schedule_request(el, o1, o2)

    fake_w3 = _FakeWeb3(election_id=el.id, candidate_count=2)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: fake_w3)

    # First call: Verifier mines & confirms, BallotBox wait_for_receipt times out while tx is still pending in mempool
    box_tx = {}

    def _keep_in_mempool(tx_hash_hex, idx):
        if idx == 1:
            box_tx['hash'] = tx_hash_hex
            fake_w3.skip_auto_receipt_for_next = True
            fake_w3.txs[tx_hash_hex] = {'hash': tx_hash_hex, 'nonce': 1}  # In mempool, no receipt yet

    fake_w3.send_hooks = [None, _keep_in_mempool]
    ok1, msg1, _ = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert not ok1
    assert 'DEPLOYMENT_PENDING' in msg1
    assert len(fake_w3.broadcast_calls) == 2

    # Second call while still pending in mempool -> stays DEPLOYMENT_PENDING, NO duplicate deploy!
    ok2, msg2, _ = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert not ok2
    assert 'DEPLOYMENT_PENDING' in msg2
    assert len(fake_w3.broadcast_calls) == 2

    # Worker MUST keep election SCHEDULED (never OPEN while pending)
    summary_pending = ElectionLifecycleWorker(app=app).tick()
    assert summary_pending['opened'] == 0
    db.session.refresh(el)
    assert el.status == 'SCHEDULED'

    # Now tx mines on-chain -> third call recovers BallotBox WITHOUT redeploying Verifier or BallotBox
    fake_w3.block_number = 8
    fake_w3.receipts[box_tx['hash']] = {
        'status': 1,
        'contractAddress': BALLOTBOX_ADDR,
        'blockNumber': 8,
    }
    fake_w3.confirmed_nonce = 2

    ok3, msg3, cp3 = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert ok3, msg3
    assert cp3['verifier_address'] == Web3.to_checksum_address(VERIFIER_ADDR)
    assert cp3['contract_address'] == Web3.to_checksum_address(BALLOTBOX_ADDR)
    assert len(fake_w3.broadcast_calls) == 2  # Still 2 txs total!


# =============================================================================
# Test 6: Fail-Closed Checks & Existing Checkpoint Never Overwritten
# =============================================================================

def test_mismatched_existing_checkpoint_never_overwritten_and_fails_closed(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, _ = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_MISMATCH_CP', start_offset_minutes=-2, status='SCHEDULED')

    # Write a pre-existing mismatched checkpoint (wrong election_id)
    cp_path = os.path.join(str(tmp_path), f'v2_checkpoint_election_{el.id}.json')
    original_content = {
        'election_id': el.id + 999,
        'contract_address': BALLOTBOX_ADDR,
        'verifier_address': VERIFIER_ADDR,
        'relayer_address': RELAYER_ADDR,
        'chain_id': 31337,
    }
    with open(cp_path, 'w', encoding='utf-8') as f:
        json.dump(original_content, f)

    fake_w3 = _FakeWeb3(election_id=el.id, candidate_count=2)
    monkeypatch.setattr(BlockchainV2Service, 'get_web3', lambda self: fake_w3)

    ok, msg, cp = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
    assert not ok
    assert 'CHECKPOINT_MISMATCH' in msg
    assert cp is None
    assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_FAILED
    assert len(fake_w3.broadcast_calls) == 0

    # Verify the existing file on disk was NEVER overwritten!
    with open(cp_path, 'r', encoding='utf-8') as f:
        after_content = json.load(f)
    assert after_content == original_content


def test_verify_deployed_contract_rejects_chain_id_election_id_candidate_count_and_zero_vote_missing(
    app, db, tmp_path, monkeypatch
):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, _ = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_STRICT_CHECKS')
    service = BlockchainV2Service(election_id=el.id)

    # 1. Wrong chain_id
    w3_bad_chain = _FakeWeb3(election_id=el.id, candidate_count=2, chain_id=99999)
    svc_bad_chain = BlockchainV2Service(w3_instance=w3_bad_chain, election_id=el.id)
    ok, msg = svc_bad_chain.verify_deployed_v2_contract(BALLOTBOX_ADDR, el, expected_chain_id=31337)
    assert not ok and 'CHAIN_ID_MISMATCH' in msg

    # 2. Wrong on-chain electionId
    w3_bad_eid = _FakeWeb3(election_id=el.id + 55, candidate_count=2)
    svc_bad_eid = BlockchainV2Service(w3_instance=w3_bad_eid, election_id=el.id)
    ok, msg = svc_bad_eid.verify_deployed_v2_contract(BALLOTBOX_ADDR, el)
    assert not ok and 'CONTRACT_ELECTION_MISMATCH' in msg

    # 3. Wrong candidateCount
    w3_bad_cc = _FakeWeb3(election_id=el.id, candidate_count=7)
    svc_bad_cc = BlockchainV2Service(w3_instance=w3_bad_cc, election_id=el.id)
    ok, msg = svc_bad_cc.verify_deployed_v2_contract(BALLOTBOX_ADDR, el)
    assert not ok and 'CONTRACT_CANDIDATE_COUNT_MISMATCH' in msg

    # 4. Missing finalizeZeroVoteElection selector in bytecode
    w3_no_zv = _FakeWeb3(election_id=el.id, candidate_count=2)
    w3_no_zv.codes[Web3.to_checksum_address(BALLOTBOX_ADDR)] = b'\x60' * 6000
    svc_no_zv = BlockchainV2Service(w3_instance=w3_no_zv, election_id=el.id)
    ok, msg = svc_no_zv.verify_deployed_v2_contract(BALLOTBOX_ADDR, el)
    assert not ok and 'MISSING_ZERO_VOTE_SUPPORT' in msg


# =============================================================================
# Test 7: Shared PersistentElectionLock Concurrency Guard
# =============================================================================

def test_persistent_lock_prevents_concurrent_deployment_race(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    o1, _ = _create_officers()
    el = _create_draft_election(o1, eid_str='ELEC_10C_LOCK')

    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()
    worker_result = {}

    def _holder():
        with app.app_context():
            with PersistentElectionLock(el.id, session=db.session) as acquired:
                assert acquired
                lock_acquired_event.set()
                release_lock_event.wait(timeout=5)

    def _contender():
        lock_acquired_event.wait(timeout=5)
        with app.app_context():
            ok, msg, _ = V2ElectionManager.ensure_v2_contract_deployed(el.id, checkpoint_dir=str(tmp_path))
            worker_result['ok'] = ok
            worker_result['msg'] = msg

    t1 = threading.Thread(target=_holder)
    t2 = threading.Thread(target=_contender)
    t1.start()
    t2.start()
    t2.join(timeout=6)
    release_lock_event.set()
    t1.join(timeout=6)

    assert worker_result['ok'] is False
    assert 'DEPLOYMENT_PENDING' in worker_result['msg']


# =============================================================================
# Test 8: V1 vs V2 Contract Resolution Isolation
# =============================================================================

def test_verification_contract_resolution_blocks_unsafe_v1_fallback_for_v2(app, db, tmp_path, monkeypatch):
    _enable_v2_deploy(app, str(tmp_path), monkeypatch)
    app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x1111111111111111111111111111111111111111'
    o1, _ = _create_officers()

    # Create a new election ID >= 9 with no checkpoint yet -> MUST NOT fall back to V1 BALLOTBOX_CONTRACT_ADDRESS!
    for i in range(9):
        el_tmp = _create_draft_election(o1, eid_str=f'ELEC_PAD_{i}')
    el_new = el_tmp
    assert el_new.id >= 9

    resolved_unprovisioned = VerificationService._resolve_target_contract(el_new)
    assert resolved_unprovisioned is None

    # Create a legacy V1 election with actual BallotRecord rows -> preserves V1 fallback cleanly
    el_v1 = _create_draft_election(o1, eid_str='ELEC_LEGACY_V1')
    rec = BallotRecord(
        election_id=el_v1.id,
        pseudonym='legacy_pseudo_1',
        candidate=1,
    )
    db.session.add(rec)
    db.session.commit()
    assert not is_v2_election(el_v1)
    assert VerificationService._resolve_target_contract(el_v1) == '0x1111111111111111111111111111111111111111'


# =============================================================================
# Test 9: Isolated Local Hardhat Real Contract Deployment + Zero-Vote Finalize
# =============================================================================

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


def test_real_hardhat_v2_deploy_approve_open_and_zero_vote_finalize(app, db, tmp_path, monkeypatch):
    """
    Full real-EVM end-to-end test against an isolated ephemeral `npx hardhat node`:
    Officer 1 create -> Officer 2 approve (auto-deploys BN254CDSVerifier + EVotingBallotBoxV2) ->
    Lifecycle worker opens at start_time without redeploy ->
    Lifecycle worker closes and finalizes 0 votes cleanly via finalizeZeroVoteElection().
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    blockchain_dir = os.path.join(repo_root, 'blockchain')
    hh_bin = os.path.join(
        blockchain_dir,
        'node_modules',
        '.bin',
        'hardhat.cmd' if os.name == 'nt' else 'hardhat',
    )
    port = _find_free_port()
    rpc_url = f'http://127.0.0.1:{port}'
    hh_env = dict(os.environ)
    hh_env.update({
        'LOCALAPPDATA': str(tmp_path),
        'APPDATA': str(tmp_path),
        'HOME': str(tmp_path),
        'USERPROFILE': str(tmp_path),
        'XDG_DATA_HOME': str(tmp_path),
        'XDG_CONFIG_HOME': str(tmp_path),
        'XDG_CACHE_HOME': str(tmp_path),
        'HARDHAT_DISABLE_TELEMETRY_PROMPT': 'true',
    })

    hh_log_path = os.path.join(str(tmp_path), 'hardhat_node.log')
    hh_log_file = open(hh_log_path, 'w+', encoding='utf-8')
    try:
        proc = subprocess.Popen(
            [hh_bin, 'node', '--hostname', '127.0.0.1', '--port', str(port)],
            cwd=blockchain_dir,
            env=hh_env,
            stdin=subprocess.DEVNULL,
            stdout=hh_log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        hh_log_file.close()
        pytest.fail(f"Failed to launch isolated Hardhat node: {exc}")

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        deadline = time.time() + 45.0
        while time.time() < deadline:
            if proc.poll() is not None:
                hh_log_file.flush()
                hh_log_file.seek(0)
                out = hh_log_file.read()
                pytest.fail(f"Isolated Hardhat node exited early ({proc.returncode}): {out}")
            try:
                if w3.is_connected():
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if not w3.is_connected():
            proc.terminate()
            hh_log_file.flush()
            hh_log_file.seek(0)
            out = hh_log_file.read()
            pytest.fail(f"Isolated Hardhat node did not respond at {rpc_url} within 45s. Output:\n{out}")

        _enable_v2_deploy(app, str(tmp_path), monkeypatch)
        app.config['BLOCKCHAIN_RPC_URL'] = rpc_url

        o1, o2 = _create_officers()
        el = _create_draft_election(o1, eid_str='ELEC_10C_REAL_HARDHAT', start_offset_minutes=5, end_offset_minutes=30)

        # 1. Officer 1 requests approval; Officer 2 approves -> auto-deploys on real Hardhat EVM
        req = ElectionAdminService.request_approval(el.election_id, 'SCHEDULE_ELECTION', o1)
        ok, msg = ElectionAdminService.approve_request(req.id, o2)
        assert ok, msg

        cp = load_deployment_checkpoint(el.id, checkpoint_dir=str(tmp_path))
        assert cp is not None
        assert cp['election_id'] == el.id
        assert cp['chain_id'] == w3.eth.chain_id
        assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_VERIFIED

        svc = BlockchainV2Service.for_election(el.id, rpc_url=rpc_url)
        contract = svc.get_contract()
        assert contract.functions.electionId().call() == el.id
        assert contract.functions.candidateCount().call() == 2
        assert Web3.to_checksum_address(contract.functions.admin().call()) == ADMIN_ADDR
        assert Web3.to_checksum_address(contract.functions.relayer().call()) == RELAYER_ADDR
        assert Web3.to_checksum_address(contract.functions.verifier().call()) == Web3.to_checksum_address(cp['verifier_address'])
        assert len(w3.eth.get_code(Web3.to_checksum_address(cp['verifier_address']))) > 0
        assert contract.functions.state().call() == 0

        # Nonce count of admin after VERIFIER + BALLOT_BOX deploys = 2
        assert w3.eth.get_transaction_count(ADMIN_ADDR, 'latest') == 2

        # 2. Worker tick at start_time opens voting WITHOUT a second deployment
        el.start_time = datetime.utcnow() - timedelta(minutes=2)
        db.session.commit()
        open_summary = ElectionLifecycleWorker(app=app).tick()
        assert open_summary['opened'] == 1, open_summary
        db.session.refresh(el)
        assert el.status == 'OPEN'
        assert contract.functions.state().call() == 4
        # Admin executed ONLY openVoting() (+1 -> 3); Relayer registered officers (2)
        assert w3.eth.get_transaction_count(ADMIN_ADDR, 'latest') == 3
        assert w3.eth.get_transaction_count(RELAYER_ADDR, 'latest') == 2

        # 3. Worker tick at end_time closes voting and executes finalizeZeroVoteElection() cleanly
        el.end_time = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        close_summary = ElectionLifecycleWorker(app=app).tick()
        assert close_summary['finalized'] == 1, close_summary
        db.session.refresh(el)
        assert el.status == 'FINALIZED'
        assert contract.functions.state().call() == 7  # Finalized
        assert contract.functions.getFinalTally(0).call() == 0
        assert contract.functions.getFinalTally(1).call() == 0
    finally:
        if proc.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        try:
            hh_log_file.close()
        except Exception:
            pass

"""
Phase 10D.1 Real Hardhat V2 Recovery Integration Test.

Runs against an isolated `npx hardhat node` on a free localhost port with
`tmp_path` checkpoints, never touching persistent Hardhat,
`backend/deployment_checkpoints`, `backend/instance/voting.db`, or Elections 9/11/12.

Verifies on real Hardhat EVM:
  a) Confirmed V2 tx recovery (both with tx_hash and missing tx_hash recovered via BallotCastV2 log)
     -> CONFIRMED, deterministic receipt_code, prior sequence marked superseded=True.
  b) Reverted V2 tx (status=0 mined on Hardhat) -> REVERTED + ReconciliationIssue(V2_TX_REVERTED).
  c) Pending V2 tx (unmined in Hardhat mempool via evm_setAutomine=false) -> stays SUBMITTED, v2_pending == 1.
  d) Uncertain dropped V2 tx -> UNCERTAIN + ReconciliationIssue(V2_UNCERTAIN_TX), no duplicate receipt.
  e) Recovery idempotency -> zero duplicate ballots or receipts across repeated recovery runs.
"""

from datetime import datetime, timedelta
import json
import os
import secrets
import socket
import subprocess
import time

import pytest
from web3 import Web3

from app.extensions import db
from app.models import Election, ReconciliationIssue
from app.models.admin import AdminUser, Candidate
from app.models.ballot_record_v2 import BallotQueueV2
from app.security.password import hash_password
from app.services import blockchain_v2_service as b2v
from app.services.blockchain_v2_service import (
    PROV_VERIFIED,
    BlockchainV2Service,
    get_provisioning_status,
    load_deployment_checkpoint,
)
from app.services.bn254_crypto import G, generate_ballot_proof, point_add, point_mul
from app.services.election_admin_service import ElectionAdminService
from app.services.election_lifecycle_worker import ElectionLifecycleWorker
from app.services.recovery import RecoveryService


ADMIN_KEY = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
ADMIN_ADDR = '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266'
RELAYER_KEY = '0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d'
RELAYER_ADDR = '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _format_cast_args(pseudonym_hex: str, sequence: int, ciphertexts, proof):
    p_hex = pseudonym_hex[2:] if pseudonym_hex.startswith('0x') else pseudonym_hex
    pseudo_bytes = bytes.fromhex(p_hex)
    ct_tuples = [
        ((int(ct['a']['x']), int(ct['a']['y'])), (int(ct['b']['x']), int(ct['b']['y'])))
        for ct in ciphertexts
    ]
    comm_tuples = [
        (
            (int(c['t_a_0']['x']), int(c['t_a_0']['y'])),
            (int(c['t_b_0']['x']), int(c['t_b_0']['y'])),
            (int(c['t_a_1']['x']), int(c['t_a_1']['y'])),
            (int(c['t_b_1']['x']), int(c['t_b_1']['y'])),
        )
        for c in proof['candidateCommitments']
    ]
    cp_tuples = [
        (int(cp['c0']), int(cp['c1']), int(cp['z0']), int(cp['z1']))
        for cp in proof['candidateProofs']
    ]
    sum_comm = (
        (int(proof['sumCommitments']['t_a_sum']['x']), int(proof['sumCommitments']['t_a_sum']['y'])),
        (int(proof['sumCommitments']['t_b_sum']['x']), int(proof['sumCommitments']['t_b_sum']['y'])),
    )
    proof_tuple = (comm_tuples, cp_tuples, sum_comm, int(proof['z_sum']))
    return pseudo_bytes, int(sequence), ct_tuples, proof_tuple


def test_real_hardhat_v2_recovery_confirmed_reverted_pending_uncertain(app, db, tmp_path, monkeypatch):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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

    hh_log_path = os.path.join(str(tmp_path), 'hardhat_recovery.log')
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
                pytest.fail(f"Isolated Hardhat node exited early ({proc.returncode}): {hh_log_file.read()}")
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
            pytest.fail(f"Isolated Hardhat node did not respond at {rpc_url} within 45s.\n{hh_log_file.read()}")

        monkeypatch.setattr(b2v, '_DEFAULT_CHECKPOINT_DIR', str(tmp_path))
        monkeypatch.setenv('BLOCKCHAIN_RPC_URL', rpc_url)
        monkeypatch.setenv('BLOCKCHAIN_CHECKPOINT_DIR', str(tmp_path))
        monkeypatch.setenv('V2_DEPLOY_ADMIN_KEY', ADMIN_KEY)
        monkeypatch.setenv('V2_DEPLOY_ADMIN_ADDRESS', ADMIN_ADDR)
        monkeypatch.setenv('RELAYER_PRIVATE_KEY', RELAYER_KEY)
        monkeypatch.setenv('RELAYER_ADDRESS', RELAYER_ADDR)
        app.config['ENABLE_V2_DEPLOY_IN_TESTS'] = True
        app.config['BLOCKCHAIN_ENABLED'] = True
        app.config['ADMIN_PRIVATE_KEY'] = ADMIN_KEY
        app.config['RELAYER_PRIVATE_KEY'] = RELAYER_KEY
        app.config['BLOCKCHAIN_RPC_URL'] = rpc_url
        app.config['BLOCKCHAIN_CHECKPOINT_DIR'] = str(tmp_path)
        app.config['V2_AUTO_DEPLOY_ON_APPROVAL'] = True
        app.config['RECOVERY_STALE_SUBMITTED_SECONDS'] = 60

        # Seed two officers & synthetic election (never 9/11/12)
        o1 = AdminUser(
            admin_id='OFF_10D_1',
            name='Officer One',
            email='hh_rec_o1@college.test',
            role='OFFICER',
            password_hash=hash_password('pass1!'),
            is_active=True,
        )
        o2 = AdminUser(
            admin_id='OFF_10D_2',
            name='Officer Two',
            email='hh_rec_o2@college.test',
            role='OFFICER',
            password_hash=hash_password('pass2!'),
            is_active=True,
        )
        db.session.add_all([o1, o2])
        db.session.flush()

        now = datetime.utcnow()
        el = Election(
            election_id='ELEC_10D_HH_RECOVERY',
            title='Hardhat V2 Recovery Test',
            status='DRAFT',
            protocol_version='V2',
            candidate_count=2,
            eligible_count=20,
            start_time=now + timedelta(minutes=5),
            end_time=now + timedelta(minutes=30),
            created_by=o1.id,
        )
        db.session.add(el)
        db.session.flush()
        db.session.add_all([
            Candidate(election_id=el.election_id, candidate_index=0, name='Alice'),
            Candidate(election_id=el.election_id, candidate_index=1, name='Bob'),
        ])
        db.session.commit()

        # Approve & deploy V2 contracts
        req = ElectionAdminService.request_approval(el.election_id, 'SCHEDULE_ELECTION', o1)
        ok, msg = ElectionAdminService.approve_request(req.id, o2)
        assert ok, msg
        assert get_provisioning_status(el.id, checkpoint_dir=str(tmp_path)) == PROV_VERIFIED
        cp = load_deployment_checkpoint(el.id, checkpoint_dir=str(tmp_path))
        verifier_addr = cp['verifier_address']
        chain_id = w3.eth.chain_id

        # Worker tick opens voting & registers officers (sets v2_priv_key_1/2)
        el.start_time = datetime.utcnow() - timedelta(minutes=2)
        db.session.commit()
        open_summary = ElectionLifecycleWorker(app=app).tick()
        assert open_summary['opened'] == 1, open_summary
        db.session.refresh(el)
        assert el.status == 'OPEN'

        svc = BlockchainV2Service.for_election(el.id, rpc_url=rpc_url)
        contract = svc.get_contract()
        assert contract.functions.state().call() == 4  # Voting
        jk = contract.functions.jointPubKey().call()
        jpk = {'x': int(jk[0]), 'y': int(jk[1])}

        # ------------------------------------------------------------------
        # (a) CONFIRMED V2 txs:
        #     - seq=1 crashed SUBMITTED with tx_hash
        #     - seq=2 crashed SUBMITTED with tx_hash=None (recovered via BallotCastV2 event log)
        # ------------------------------------------------------------------
        pseud1 = '0x' + secrets.token_hex(32)
        p1_proof = generate_ballot_proof(0, 2, {
            'election_id': el.id, 'pseudonym': pseud1, 'sequence': 1, 'joint_pub_key': jpk
        }, verifier_addr, chain_id)
        tx1_res = svc.cast_ballot(pseud1, 1, p1_proof['ciphertexts'], p1_proof['proof'], RELAYER_ADDR, RELAYER_KEY)
        assert tx1_res['status'] == 1

        p2_proof = generate_ballot_proof(1, 2, {
            'election_id': el.id, 'pseudonym': pseud1, 'sequence': 2, 'joint_pub_key': jpk
        }, verifier_addr, chain_id)
        tx2_res = svc.cast_ballot(pseud1, 2, p2_proof['ciphertexts'], p2_proof['proof'], RELAYER_ADDR, RELAYER_KEY)
        assert tx2_res['status'] == 1

        b1 = BallotQueueV2(
            election_id=el.id, pseudonym=pseud1, sequence=1,
            ciphertexts_json=json.dumps(p1_proof['ciphertexts']), proof_json=json.dumps(p1_proof['proof']),
            state='SUBMITTED', tx_hash=tx1_res['tx_hash'],
        )
        b2 = BallotQueueV2(
            election_id=el.id, pseudonym=pseud1, sequence=2,
            ciphertexts_json=json.dumps(p2_proof['ciphertexts']), proof_json=json.dumps(p2_proof['proof']),
            state='SUBMITTED', tx_hash=None,
        )
        db.session.add_all([b1, b2])
        db.session.commit()

        # ------------------------------------------------------------------
        # (b) REVERTED V2 tx (mined with status=0 on Hardhat)
        #     Resubmitting sequence=1 for pseud1 (already at sequence=2) reverts on-chain.
        # ------------------------------------------------------------------
        pseudo_bytes, _, ct_tuples, proof_tuple = _format_cast_args(pseud1, 1, p1_proof['ciphertexts'], p1_proof['proof'])
        rev_nonce = w3.eth.get_transaction_count(RELAYER_ADDR, 'pending')
        rev_tx = contract.functions.castBallot(pseudo_bytes, 1, ct_tuples, proof_tuple).build_transaction({
            'from': RELAYER_ADDR,
            'nonce': rev_nonce,
            'gas': 1_800_000,
            'gasPrice': w3.eth.gas_price,
            'chainId': chain_id,
        })
        signed_rev = w3.eth.account.sign_transaction(rev_tx, RELAYER_KEY)
        w3.provider.make_request('evm_setAutomine', [False])
        rev_hash = w3.eth.send_raw_transaction(signed_rev.raw_transaction).hex()
        if not rev_hash.startswith('0x'):
            rev_hash = '0x' + rev_hash
        w3.provider.make_request('evm_mine', [])
        w3.provider.make_request('evm_setAutomine', [True])
        rev_receipt = w3.eth.wait_for_transaction_receipt(rev_hash, timeout=30)
        assert rev_receipt['status'] == 0

        b_rev = BallotQueueV2(
            election_id=el.id, pseudonym=pseud1, sequence=3,
            ciphertexts_json=json.dumps(p1_proof['ciphertexts']), proof_json=json.dumps(p1_proof['proof']),
            state='SUBMITTED', tx_hash=rev_hash,
        )
        db.session.add(b_rev)
        db.session.commit()

        # ------------------------------------------------------------------
        # (c) PENDING V2 tx (unmined in Hardhat mempool via evm_setAutomine=false)
        # ------------------------------------------------------------------
        w3.provider.make_request('evm_setAutomine', [False])
        pseud2 = '0x' + secrets.token_hex(32)
        p3_proof = generate_ballot_proof(0, 2, {
            'election_id': el.id, 'pseudonym': pseud2, 'sequence': 1, 'joint_pub_key': jpk
        }, verifier_addr, chain_id)
        p2_bytes, _, p2_cts, p2_pt = _format_cast_args(pseud2, 1, p3_proof['ciphertexts'], p3_proof['proof'])
        pend_nonce = w3.eth.get_transaction_count(RELAYER_ADDR, 'pending')
        pend_tx = contract.functions.castBallot(p2_bytes, 1, p2_cts, p2_pt).build_transaction({
            'from': RELAYER_ADDR,
            'nonce': pend_nonce,
            'gas': 1_800_000,
            'gasPrice': w3.eth.gas_price,
            'chainId': chain_id,
        })
        signed_pend = w3.eth.account.sign_transaction(pend_tx, RELAYER_KEY)
        pend_hash = w3.eth.send_raw_transaction(signed_pend.raw_transaction).hex()
        if not pend_hash.startswith('0x'):
            pend_hash = '0x' + pend_hash

        b_pend = BallotQueueV2(
            election_id=el.id, pseudonym=pseud2, sequence=1,
            ciphertexts_json=json.dumps(p3_proof['ciphertexts']), proof_json=json.dumps(p3_proof['proof']),
            state='SUBMITTED', tx_hash=pend_hash,
        )
        db.session.add(b_pend)
        db.session.commit()

        # ------------------------------------------------------------------
        # (d) UNCERTAIN dropped V2 tx (aged past stale threshold, not on chain or mempool)
        # ------------------------------------------------------------------
        pseud3 = '0x' + secrets.token_hex(32)
        b_unc = BallotQueueV2(
            election_id=el.id, pseudonym=pseud3, sequence=1,
            ciphertexts_json='[]', proof_json='{}',
            state='SUBMITTED', tx_hash='0x' + secrets.token_hex(32),
            created_at=datetime.utcnow() - timedelta(seconds=300),
        )
        db.session.add(b_unc)
        db.session.commit()

        # Execute startup recovery against live Hardhat EVM
        summary = RecoveryService.startup_recover(app=app, detailed=True)
        assert summary['v2_confirmed'] == 2, summary
        assert summary['v2_failed'] == 1, summary
        assert summary['v2_pending'] == 1, summary
        assert summary['v2_uncertain'] == 1, summary

        db.session.refresh(b1)
        db.session.refresh(b2)
        db.session.refresh(b_rev)
        db.session.refresh(b_pend)
        db.session.refresh(b_unc)

        assert b1.state == 'CONFIRMED'
        assert b1.receipt_code is not None
        assert b1.superseded is True

        assert b2.state == 'CONFIRMED'
        assert b2.tx_hash == tx2_res['tx_hash']
        assert b2.receipt_code is not None
        assert b2.receipt_code != b1.receipt_code
        assert b2.superseded is False

        assert b_rev.state == 'REVERTED'
        assert b_rev.receipt_code is None
        rev_issue = ReconciliationIssue.query.filter_by(
            election_id=el.id, protocol_version='V2', issue_type='V2_TX_REVERTED'
        ).first()
        assert rev_issue is not None

        assert b_pend.state == 'SUBMITTED'
        assert b_pend.receipt_code is None

        assert b_unc.state == 'UNCERTAIN'
        assert b_unc.receipt_code is None
        unc_issue = ReconciliationIssue.query.filter_by(
            election_id=el.id, protocol_version='V2', issue_type='V2_UNCERTAIN_TX'
        ).first()
        assert unc_issue is not None

        # (e) Idempotency: re-running recovery creates zero duplicate ballots/receipts
        assert RecoveryService.is_idempotent_ok(el.id) is True
        assert BallotQueueV2.query.filter_by(election_id=el.id).count() == 5
        assert BallotQueueV2.query.filter_by(election_id=el.id, state='CONFIRMED').count() == 2

        w3.provider.make_request('evm_setAutomine', [True])
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

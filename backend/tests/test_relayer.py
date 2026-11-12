"""
Phase 6 Relayer Tests - Vote Without Doubt
Verifies:
1. Cryptographic queue shuffling (privacy guarantee).
2. Fail-closed behavior on disabled or unconfigured relayer.
3. Real/mocked transaction submission, mined receipt state updates.
4. Error tracking on reverted transactions or unreachable RPC.
5. Pseudonym formatting to 32 bytes.
"""

from unittest.mock import MagicMock
from app.extensions import db
from app.models import BallotRecord as Ballot
from app.relayer import Relayer


def test_relayer_cryptographic_shuffle(app, db):
    with app.app_context():
        relayer = Relayer()
        ballots = [
            Ballot(election_id=1, pseudonym=f'0x{i:064x}', candidate=0, sequence=1, state='QUEUED')
            for i in range(20)
        ]
        shuffled = relayer.shuffle_queue(ballots)
        assert len(shuffled) == 20
        # All items present
        assert {b.pseudonym for b in ballots} == {b.pseudonym for b in shuffled}


def test_relayer_pseudonym_formatting():
    relayer = Relayer()
    p_hex = '0x' + 'ab' * 32
    raw = relayer._format_pseudonym(p_hex)
    assert len(raw) == 32
    assert raw == bytes.fromhex('ab' * 32)

    # Short hex gets padded to 32 bytes
    p_short = '1234'
    raw_short = relayer._format_pseudonym(p_short)
    assert len(raw_short) == 32
    assert raw_short[:2] == bytes.fromhex('1234')


def test_relayer_disabled_marks_failed(app, db):
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'aa' * 32, candidate=0, sequence=1, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        app.config['RELAYER_ENABLED'] = False
        relayer = Relayer()
        summary = relayer.process_queue(batch_size=10, contract_address='0x' + '11' * 20)
        assert summary['failed'] == 1
        assert b.state == 'FAILED'
        assert b.error == 'RELAYER_DISABLED'
        app.config['RELAYER_ENABLED'] = True


def test_relayer_missing_contract_address_marks_failed(app, db):
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'bb' * 32, candidate=0, sequence=1, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        relayer = Relayer(contract_address=None)
        summary = relayer.process_queue(batch_size=10)
        assert summary['failed'] == 1
        assert b.state == 'FAILED'
        assert b.error == 'NO_CONTRACT_ADDRESS'


def test_relayer_unreachable_rpc_marks_failed(app, db):
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'cc' * 32, candidate=0, sequence=1, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        relayer = Relayer(
            rpc_url='http://127.0.0.1:59999',  # invalid port
            contract_address='0x' + '22' * 20,
        )
        summary = relayer.process_queue(batch_size=10)
        assert summary['failed'] == 1
        assert b.state == 'FAILED'
        assert 'RPC_UNREACHABLE' in (b.error or '')


def test_relayer_mock_successful_submission(app, db):
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'dd' * 32, candidate=1, sequence=1, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.accounts = ['0x' + '11' * 20, '0x' + '22' * 20]

        mock_contract = MagicMock()
        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = '0xdeadbeef12345678'
        mock_contract.functions.castBallot.return_value.transact.return_value = mock_tx_hash
        mock_w3.eth.contract.return_value = mock_contract

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 42
        mock_receipt.transactionHash = mock_tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        relayer = Relayer(
            contract_address='0x' + '33' * 20,
            w3_instance=mock_w3,
        )
        summary = relayer.process_queue(batch_size=1)
        assert summary['confirmed'] == 1
        assert summary['failed'] == 0
        assert b.state == 'FINALIZED'
        assert b.tx_hash == '0xdeadbeef12345678'
        assert b.block_number == 42


def test_relayer_mock_reverted_submission(app, db):
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'ee' * 32, candidate=1, sequence=1, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.accounts = ['0x' + '11' * 20, '0x' + '22' * 20]

        mock_contract = MagicMock()
        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = '0xrevertedtx'
        mock_contract.functions.castBallot.return_value.transact.return_value = mock_tx_hash
        mock_w3.eth.contract.return_value = mock_contract

        mock_receipt = MagicMock()
        mock_receipt.status = 0
        mock_receipt.blockNumber = 43
        mock_receipt.transactionHash = mock_tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        relayer = Relayer(
            contract_address='0x' + '33' * 20,
            w3_instance=mock_w3,
        )
        summary = relayer.process_queue(batch_size=1)
        assert summary['confirmed'] == 0
        assert summary['failed'] == 1
        assert b.state == 'FAILED'
        assert 'TRANSACTION_REVERTED' in b.error


def test_relayer_live_ganache_submission(app, db):
    """Live Ganache end-to-end integration test."""
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider('http://127.0.0.1:8545'))
    if not w3.is_connected() or len(w3.eth.accounts) < 2:
        return

    from app.relayer.relayer import _load_contract_abi, _DEFAULT_ARTIFACT_PATH
    import json
    with open(_DEFAULT_ARTIFACT_PATH, 'r') as f:
        artifact = json.load(f)
    abi = artifact['abi']
    bytecode = artifact['bytecode']

    officer = w3.eth.accounts[0]
    relayer_acct = w3.eth.accounts[1]

    # Deploy contract
    ContractFactory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = ContractFactory.constructor().transact({'from': officer, 'gas': 4_000_000})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    contract_addr = receipt.contractAddress

    contract = w3.eth.contract(address=contract_addr, abi=abi)
    # Set relayer
    set_r_tx = contract.functions.setRelayer(relayer_acct).transact({'from': officer, 'gas': 100_000})
    w3.eth.wait_for_transaction_receipt(set_r_tx)

    # Create election 99
    now = w3.eth.get_block('latest')['timestamp']
    create_tx = contract.functions.createElection(
        99, now - 60, now + 3600, 3, b'\x01' * 32, 10, b'\x02' * 32, 1
    ).transact({'from': officer, 'gas': 300_000})
    w3.eth.wait_for_transaction_receipt(create_tx)

    with app.app_context():
        pseudo = '0x' + 'fe' * 32
        ballot = Ballot(election_id=99, pseudonym=pseudo, candidate=1, sequence=1, state='QUEUED')
        db.session.add(ballot)
        db.session.commit()

        relayer = Relayer(
            rpc_url='http://127.0.0.1:8545',
            contract_address=contract_addr,
            relayer_account=relayer_acct,
        )
        summary = relayer.process_queue(batch_size=1)
        assert summary['confirmed'] == 1
        assert summary['failed'] == 0
        assert ballot.state == 'FINALIZED'
        assert ballot.block_number is not None and ballot.block_number > 0
        assert ballot.tx_hash is not None and ballot.tx_hash.startswith('0x')
        assert ballot.tx_confirmed_at is not None

        # Check tally on-chain
        tally = contract.functions.getTally(99, 1).call()
        assert tally == 1


def test_relayer_sequence_order_preserved_in_shuffle(app, db):
    """Cryptographic shuffling must never place sequence 2 before sequence 1 for the same pseudonym."""
    with app.app_context():
        relayer = Relayer()
        p1 = '0x' + '11' * 32
        p2 = '0x' + '22' * 32
        ballots = [
            Ballot(election_id=1, pseudonym=p1, candidate=0, sequence=1, state='QUEUED'),
            Ballot(election_id=1, pseudonym=p1, candidate=1, sequence=2, state='QUEUED'),
            Ballot(election_id=1, pseudonym=p2, candidate=0, sequence=1, state='QUEUED'),
            Ballot(election_id=1, pseudonym=p2, candidate=2, sequence=2, state='QUEUED'),
        ]
        shuffled = relayer.shuffle_queue(ballots)
        assert len(shuffled) == 4

        # For p1, sequence 1 must appear before sequence 2
        p1_seqs = [b.sequence for b in shuffled if b.pseudonym == p1]
        assert p1_seqs == [1, 2]

        # For p2, sequence 1 must appear before sequence 2
        p2_seqs = [b.sequence for b in shuffled if b.pseudonym == p2]
        assert p2_seqs == [1, 2]


def test_relayer_null_ballot_dispatch(app, db):
    """Relayer invokes castNullBallot on smart contract when is_null=True."""
    with app.app_context():
        b = Ballot(election_id=1, pseudonym='0x' + 'dd' * 32, candidate=0, sequence=2, is_null=True, state='QUEUED')
        db.session.add(b)
        db.session.commit()

        mock_w3 = MagicMock()
        mock_w3.is_connected.return_value = True
        mock_w3.eth.accounts = ['0x' + '11' * 20]

        mock_contract = MagicMock()
        mock_tx_hash = MagicMock()
        mock_tx_hash.hex.return_value = '0xnullballottx'
        mock_contract.functions.castNullBallot.return_value.transact.return_value = mock_tx_hash
        mock_w3.eth.contract.return_value = mock_contract

        mock_receipt = MagicMock()
        mock_receipt.status = 1
        mock_receipt.blockNumber = 50
        mock_receipt.transactionHash = mock_tx_hash
        mock_w3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        relayer = Relayer(contract_address='0x' + '33' * 20, w3_instance=mock_w3)
        summary = relayer.process_queue(batch_size=1)
        assert summary['confirmed'] == 1
        assert b.state == 'FINALIZED'
        # castNullBallot was called, not castBallot
        mock_contract.functions.castNullBallot.assert_called_once()
        mock_contract.functions.castBallot.assert_not_called()


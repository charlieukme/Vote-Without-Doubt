"""
Wallet cryptography unit tests - Phase 4 (remediated)

These exercise the real Ethereum primitives with a deterministic TEST-ONLY key.
The key below controls nothing and holds no funds; it exists purely so the
signature path can be tested without a browser wallet.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.security.wallet import (
    CHALLENGE_TTL_MINUTES,
    DISCLAIMER,
    ETH_ACCOUNT_AVAILABLE,
    MAX_SIGNATURE_ATTEMPTS,
    NO_CONTRACT_ADDRESS,
    WALLET_AUTH_PURPOSE,
    InvalidWalletAddress,
    WalletVerificationUnavailable,
    addresses_equal,
    create_auth_message,
    generate_challenge_nonce,
    is_valid_eth_address,
    normalize_address,
    require_wallet_verification,
    to_checksum,
    verify_signature,
)

#: TEST-ONLY deterministic key. Never used outside the test suite.
TEST_ONLY_PRIVATE_KEY = '0x' + '22' * 32
TEST_ACCOUNT = Account.from_key(TEST_ONLY_PRIVATE_KEY)


def sign(message: str) -> str:
    """Produce a real MetaMask ``personal_sign``-compatible signature."""
    return Account.sign_message(
        encode_defunct(text=message), private_key=TEST_ONLY_PRIVATE_KEY
    ).signature.hex()


# --------------------------------------------------------------- dependency

def test_eth_account_is_installed_and_usable():
    """C1: the verification dependency must be present, not silently absent."""
    assert ETH_ACCOUNT_AVAILABLE is True
    require_wallet_verification()


def test_real_signature_recovers_the_signing_address():
    message = 'Vote Without Doubt unit test'
    recovered = Account.recover_message(
        encode_defunct(text=message), signature=sign(message))
    assert recovered.lower() == TEST_ACCOUNT.address.lower()


# ------------------------------------------------------------------- nonce

def test_nonce_generation():
    n1 = generate_challenge_nonce()
    n2 = generate_challenge_nonce()
    assert n1 != n2
    assert len(n1) == 64
    assert int(n1, 16) >= 0


def test_nonce_is_256_bits_of_hex():
    nonce = generate_challenge_nonce()
    assert len(nonce) == 64          # 32 bytes
    assert len(bytes.fromhex(nonce)) == 32


# ----------------------------------------------------------------- message

def build_message(**overrides):
    payload = {
        'nonce': 'abc123',
        'user_id': 7,
        'election_id': 'E-2026-GEN',
        'chain_id': 1337,
        'contract_address': NO_CONTRACT_ADDRESS,
    }
    payload.update(overrides)
    return create_auth_message(**payload)


def test_message_contains_every_required_context_field():
    message = build_message()
    for field in ('Domain:', 'Purpose:', 'UserID:', 'ElectionID:',
                  'ChainId:', 'Contract:', 'Nonce:', 'IssuedAt:', 'ExpiresAt:'):
        assert field in message, field


def test_message_never_contains_candidate_or_vote_data():
    original = build_message()
    lowered = original.lower()
    for forbidden in ('candidate', 'ballot', 'election_result', 'txhash'):
        assert forbidden not in lowered
    assert 'do not sign this to vote' in lowered
    assert DISCLAIMER in original


def test_message_is_deterministic_for_the_same_inputs():
    assert build_message() == build_message()


def test_changing_election_changes_the_message():
    assert build_message(election_id='E-A') != build_message(election_id='E-B')


def test_changing_chain_changes_the_message():
    assert build_message(chain_id=1337) != build_message(chain_id=1)


def test_changing_contract_changes_the_message():
    other = '0x1111111111111111111111111111111111111111'
    assert build_message() != build_message(contract_address=other)


def test_changing_purpose_changes_the_message():
    assert build_message() != build_message(purpose='SOMETHING_ELSE')


# ------------------------------------------------------------------ address

@pytest.mark.parametrize('address', [
    '0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A',
    '0x19e7e376e7c213b7e7e7e46cc70a5dd086daff2a',
    '0x0000000000000000000000000000000000000000',
])
def test_valid_addresses_are_accepted(address):
    assert is_valid_eth_address(address)
    assert normalize_address(address) == address.lower()


@pytest.mark.parametrize('address', [
    'not-an-address', '0x123', '', None, 12345,
    '0xZZ7E376E7C213B7E7e7e46cc70A5dD086DAff2A',
    "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A'; DROP TABLE users--",
    '0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2',
    '19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A',
])
def test_invalid_addresses_are_rejected(address):
    """M1: arbitrary strings must never be accepted or stored."""
    assert is_valid_eth_address(address) is False
    with pytest.raises(InvalidWalletAddress):
        normalize_address(address)


def test_address_comparison_is_case_insensitive():
    lower = TEST_ACCOUNT.address.lower()
    upper = TEST_ACCOUNT.address.upper().replace('0X', '0x')
    assert addresses_equal(lower, upper) is True


def test_addresses_equal_is_false_for_different_addresses():
    assert addresses_equal(TEST_ACCOUNT.address,
                           '0x1111111111111111111111111111111111111111') is False


def test_addresses_equal_is_false_for_garbage():
    assert addresses_equal('not-an-address', TEST_ACCOUNT.address) is False


def test_checksum_form_is_available():
    assert to_checksum(TEST_ACCOUNT.address) == TEST_ACCOUNT.address


# -------------------------------------------------------------- verification

def test_verify_signature_accepts_a_real_signature():
    message = build_message()
    ok, recovered = verify_signature(message, sign(message), TEST_ACCOUNT.address)
    assert ok is True
    assert recovered.lower() == TEST_ACCOUNT.address.lower()


def test_verify_signature_rejects_a_modified_message():
    ok, _ = verify_signature(build_message(), sign(build_message(election_id='E-OTHER')),
                            TEST_ACCOUNT.address)
    assert ok is False


def test_verify_signature_rejects_another_wallet():
    other_key = '0x' + '33' * 32
    other = Account.from_key(other_key)
    message = build_message()
    ok, _ = verify_signature(message, sign(message), other.address)
    assert ok is False


@pytest.mark.parametrize('signature', [
    '', '0x', 'nothex', '0x' + 'ab' * 10, '0x' + 'ab' * 200,
])
def test_verify_signature_rejects_malformed_signatures(signature):
    ok, _ = verify_signature(build_message(), signature, TEST_ACCOUNT.address)
    assert ok is False


def test_policy_constants_match_the_architecture():
    assert MAX_SIGNATURE_ATTEMPTS == 5
    assert CHALLENGE_TTL_MINUTES == 10
    assert WALLET_AUTH_PURPOSE == 'WALLET_AUTHENTICATION'


def test_no_contract_sentinel_is_a_valid_address():
    assert is_valid_eth_address(NO_CONTRACT_ADDRESS)
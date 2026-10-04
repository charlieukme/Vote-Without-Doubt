"""
Test wallet auth - Phase 4
"""

from app.security.wallet import generate_challenge_nonce, create_auth_message, normalize_address


def test_nonce_generation():
    n1 = generate_challenge_nonce()
    n2 = generate_challenge_nonce()
    assert n1 != n2
    assert len(n1) > 20


def test_message_contains_nonce_and_no_candidate():
    nonce = generate_challenge_nonce()
    msg = create_auth_message(nonce, user_id=1)
    assert nonce in msg
    assert 'candidate' not in msg.lower()
    assert 'vote' not in msg.lower() or 'Do NOT sign' in msg


def test_normalize_address():
    addr = '0xAbCdEf1234567890aBcDeF1234567890AbCdEf12'
    n = normalize_address(addr)
    assert n == addr.lower()

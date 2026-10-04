"""
Pseudonym derivation - Phase 7/8
"""

import os
import hmac
import hashlib


def get_election_pseudonym_key(election_id: int) -> bytes:
    base = os.getenv('PSEUDONYM_SECRET', 'dev-pseudonym-secret')
    return hmac.new(base.encode(), f'election:{election_id}'.encode(), hashlib.sha256).digest()


def derive_pseudonym(user_id: int, election_id: int, chain_id: int = 1337, contract_addr: str = '') -> str:
    key = get_election_pseudonym_key(election_id)
    msg = '|'.join(['VOTE_WITHOUT_DOUBT', 'PSEUDONYM', str(chain_id), contract_addr or '0x0', str(election_id), str(user_id)])
    sig = hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()
    return sig

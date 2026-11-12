"""
Blockchain V2 Service for Vote Without Doubt (FIX 3 V2).
Manages interactions with EVotingBallotBoxV2 smart contracts.
Completely isolated from V1 relayer and contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import socket
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
from eth_account import Account
from flask import current_app
import requests.exceptions
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound, Web3Exception

logger = logging.getLogger(__name__)


class BroadcastUncertainError(Exception):
    """Raised when transaction broadcast outcome is uncertain (timeout, transport drop, or ambiguous provider response)."""
    def __init__(self, message: str, tx_hash: Optional[str] = None):
        super().__init__(message)
        self.tx_hash = tx_hash


def _parse_bool(val: Any) -> bool:
    """Safely normalizes boolean and string values. Fails closed (False) on unexpected values."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        norm = val.strip().lower()
        if norm in ('1', 'true', 'yes', 'on'):
            return True
        if norm in ('0', 'false', 'no', 'off'):
            return False
    return False

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DEFAULT_V2_ARTIFACT_PATH = os.path.join(
    _REPO_ROOT, 'blockchain', 'artifacts', 'contracts', 'EVotingBallotBoxV2.sol', 'EVotingBallotBoxV2.json'
)
_DEFAULT_V2_VERIFIER_ARTIFACT_PATH = os.path.join(
    _REPO_ROOT, 'blockchain', 'artifacts', 'contracts', 'BN254CDSVerifier.sol', 'BN254CDSVerifier.json'
)
_DEFAULT_CHECKPOINT_DIR = os.path.join(_REPO_ROOT, 'blockchain', 'deployments')

PROV_NOT_DEPLOYED = 'NOT_DEPLOYED'
PROV_PENDING = 'DEPLOYMENT_PENDING'
PROV_VERIFIED = 'DEPLOYED_VERIFIED'
PROV_FAILED = 'DEPLOYMENT_FAILED'


def _atomic_write_json(filepath: str, data: Dict[str, Any]) -> None:
    """Atomically write JSON via temp file + os.replace to avoid partial/corrupt files."""
    target_dir = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(target_dir, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=target_dir,
            prefix='.tmp_',
            suffix='.json',
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, indent=2)
            tmp.flush()
            try:
                os.fsync(tmp.fileno())
            except OSError:
                pass
        os.replace(tmp_path, filepath)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _normalize_hex_hash(val: Optional[str]) -> str:
    if not val:
        return ''
    s = str(val).strip()
    return (s if s.startswith('0x') else '0x' + s).lower()


def _extract_block_hash_hex(block_obj: Any) -> str:
    if not block_obj:
        return ''
    raw = block_obj.get('hash') if isinstance(block_obj, dict) else getattr(block_obj, 'hash', None)
    if raw is None:
        return ''
    h = raw.hex() if isinstance(raw, (bytes, bytearray)) else str(raw)
    return _normalize_hex_hash(h)


def save_deployment_checkpoint(
    election_id: Union[int, str],
    contract_address: str,
    verifier_address: str,
    relayer_address: str,
    deployment_tx_hash: str,
    deployment_block_number: int,
    deployment_block_hash: str,
    genesis_block_hash: str,
    chain_id: int,
    candidate_count: int,
    checkpoint_dir: Optional[str] = None,
    admin_address: Optional[str] = None,
    deployed_at: Optional[str] = None,
    overwrite: bool = True,
) -> str:
    """Atomically saves a persistent deployment fingerprint to disk surviving node restarts."""
    target_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    os.makedirs(target_dir, exist_ok=True)
    filepath = os.path.join(target_dir, f'v2_checkpoint_election_{election_id}.json')
    if not overwrite and os.path.exists(filepath):
        raise FileExistsError(f"Checkpoint already exists at {filepath}; refusing to overwrite.")

    tx_h = _normalize_hex_hash(deployment_tx_hash)
    b_h = _normalize_hex_hash(deployment_block_hash)
    g_h = _normalize_hex_hash(genesis_block_hash)
    data = {
        'election_id': int(election_id),
        'contract_address': Web3.to_checksum_address(contract_address),
        'verifier_address': Web3.to_checksum_address(verifier_address),
        'relayer_address': Web3.to_checksum_address(relayer_address),
        'deployment_tx_hash': tx_h,
        'deployment_block_number': int(deployment_block_number),
        'deployment_block_hash': b_h,
        'genesis_block_hash': g_h,
        'chain_id': int(chain_id),
        'candidate_count': int(candidate_count),
        'deployed_at': deployed_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    if admin_address:
        data['admin_address'] = Web3.to_checksum_address(admin_address)
    _atomic_write_json(filepath, data)
    return filepath


def _resolve_checkpoint_expected_id(election_id: Union[int, str]) -> Optional[int]:
    """Resolve expected integer Election.id when available."""
    try:
        from app.models.ballot import Election
        e = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()
        if e:
            return int(e.id)
    except Exception:
        pass
    if str(election_id).isdigit():
        return int(election_id)
    return None


def _is_valid_checkpoint_for_election(data: Dict[str, Any], expected_eid: Optional[int]) -> bool:
    if not isinstance(data, dict) or not data.get('contract_address'):
        return False
    cp_eid = data.get('election_id')
    if cp_eid is None:
        return False
    if expected_eid is not None:
        try:
            if int(cp_eid) != int(expected_eid):
                logger.error(
                    "Checkpoint election_id mismatch: checkpoint=%s expected=%s",
                    cp_eid,
                    expected_eid,
                )
                return False
        except (ValueError, TypeError):
            return False
    return True


def _checkpoint_file_exists_for_election(
    election_id: Union[int, str],
    checkpoint_dir: Optional[str] = None,
    election: Any = None,
) -> Optional[str]:
    """Return path to an existing checkpoint file on disk (even if malformed/mismatched)."""
    target_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    candidates = [str(election_id)]
    if election is not None:
        for val in (getattr(election, 'id', None), getattr(election, 'election_id', None)):
            if val is not None and str(val) not in candidates:
                candidates.append(str(val))
    else:
        expected_id = _resolve_checkpoint_expected_id(election_id)
        if expected_id is not None and str(expected_id) not in candidates:
            candidates.append(str(expected_id))
    for cid in candidates:
        p = os.path.join(target_dir, f'v2_checkpoint_election_{cid}.json')
        if os.path.isfile(p):
            return p
    return None


def load_deployment_checkpoint(
    election_id: Union[int, str],
    checkpoint_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Loads a persistent deployment fingerprint if present and verified for election_id."""
    target_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    expected_eid = _resolve_checkpoint_expected_id(election_id)
    filepath = os.path.join(target_dir, f'v2_checkpoint_election_{election_id}.json')
    if os.path.isfile(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if _is_valid_checkpoint_for_election(data, expected_eid) else None
        except Exception as exc:
            logger.warning("Failed to load deployment checkpoint from %s: %s", filepath, exc)

    # If election_id was string (e.g. ELEC_...) or integer, try resolving mapped alternative identifier
    try:
        from app.models.ballot import Election
        e = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()
        if e:
            alt_id = e.id if str(election_id) != str(e.id) else e.election_id
            alt_filepath = os.path.join(target_dir, f'v2_checkpoint_election_{alt_id}.json')
            if os.path.isfile(alt_filepath):
                with open(alt_filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data if _is_valid_checkpoint_for_election(data, int(e.id)) else None
    except Exception:
        pass

    return None


def _get_provisioning_path(
    election_id: Union[int, str],
    checkpoint_dir: Optional[str] = None,
) -> str:
    target_dir = checkpoint_dir or _DEFAULT_CHECKPOINT_DIR
    resolved_id = _resolve_checkpoint_expected_id(election_id)
    canonical_id = resolved_id if resolved_id is not None else str(election_id)
    return os.path.join(target_dir, f'v2_provisioning_election_{canonical_id}.json')


def load_provisioning_state(
    election_id: Union[int, str],
    checkpoint_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load persisted V2 deployment recovery/provisioning journal if present."""
    filepath = _get_provisioning_path(election_id, checkpoint_dir=checkpoint_dir)
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Failed to load provisioning state from %s: %s", filepath, exc)
        return None


def save_provisioning_state(
    election_id: Union[int, str],
    state_data: Dict[str, Any],
    checkpoint_dir: Optional[str] = None,
) -> str:
    """Atomically persist V2 deployment recovery/provisioning state."""
    filepath = _get_provisioning_path(election_id, checkpoint_dir=checkpoint_dir)
    payload = dict(state_data)
    payload['updated_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    _atomic_write_json(filepath, payload)
    return filepath


def get_provisioning_status(
    election_id: Union[int, str],
    checkpoint_dir: Optional[str] = None,
) -> str:
    """
    Return authoritative V2 provisioning state:
    NOT_DEPLOYED | DEPLOYMENT_PENDING | DEPLOYED_VERIFIED | DEPLOYMENT_FAILED.
    """
    prov = load_provisioning_state(election_id, checkpoint_dir=checkpoint_dir)
    if prov and prov.get('status') in (PROV_PENDING, PROV_FAILED, PROV_VERIFIED):
        return str(prov['status'])
    if load_deployment_checkpoint(election_id, checkpoint_dir=checkpoint_dir):
        return PROV_VERIFIED
    if _checkpoint_file_exists_for_election(election_id, checkpoint_dir=checkpoint_dir):
        return PROV_FAILED
    return PROV_NOT_DEPLOYED


def _contract_supports_zero_vote_abi(abi: List[Dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict) and item.get('type') == 'function' and item.get('name') == 'finalizeZeroVoteElection'
        for item in (abi or [])
    )


def load_v2_contract_artifact(artifact_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
    path = artifact_path or _DEFAULT_V2_ARTIFACT_PATH
    if not os.path.isfile(path):
        raise FileNotFoundError(f"EVotingBallotBoxV2 artifact not found at {path}")
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    abi = data.get('abi', [])
    bytecode = data.get('bytecode', '')
    if not abi or not bytecode or bytecode in ('0x', '0x0'):
        raise ValueError(f"EVotingBallotBoxV2 artifact at {path} lacks ABI or bytecode")
    if not _contract_supports_zero_vote_abi(abi):
        raise ValueError(f"MISSING_ZERO_VOTE_SUPPORT: EVotingBallotBoxV2 artifact at {path} lacks finalizeZeroVoteElection")
    return abi, bytecode


def load_v2_verifier_artifact(artifact_path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
    path = artifact_path or _DEFAULT_V2_VERIFIER_ARTIFACT_PATH
    if not os.path.isfile(path):
        raise FileNotFoundError(f"BN254CDSVerifier artifact not found at {path}")
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    abi = data.get('abi', [])
    bytecode = data.get('bytecode', '')
    if not abi or not bytecode or bytecode in ('0x', '0x0'):
        raise ValueError(f"BN254CDSVerifier artifact at {path} lacks ABI or bytecode")
    return abi, bytecode


def load_v2_contract_abi(artifact_path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = artifact_path or _DEFAULT_V2_ARTIFACT_PATH
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle).get('abi', [])
    logger.warning("EVotingBallotBoxV2 artifact not found at %s", path)
    return []


class BlockchainV2Service:
    """
    Service wrapper for EVotingBallotBoxV2 interactions:
    - Officer key registration & PoP
    - Election lifecycle management (open, close, stall)
    - Encrypted ballot submission with CDS proofs
    - Decryption share submission with DLEQ proofs
    - On-chain tally finalization & verification
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        contract_address: Optional[str] = None,
        artifact_path: Optional[str] = None,
        w3_instance: Optional[Web3] = None,
        election_id: Optional[Union[int, str]] = None,
    ):
        self._custom_rpc_url = rpc_url
        self._custom_contract_address = contract_address
        self._artifact_path = artifact_path
        self._w3 = w3_instance
        self._election_id = election_id
        self._abi = load_v2_contract_abi(artifact_path)

    @classmethod
    def for_election(
        cls,
        election_id: Union[int, str],
        rpc_url: Optional[str] = None,
        artifact_path: Optional[str] = None,
        w3_instance: Optional[Web3] = None,
    ) -> 'BlockchainV2Service':
        """
        Creates a BlockchainV2Service bound to a specific election.
        Automatically resolves the authoritative election-specific contract address
        from its deployment checkpoint if available.
        """
        cp = load_deployment_checkpoint(election_id)
        specific_address = None
        if cp and cp.get('contract_address'):
            specific_address = cp['contract_address']
        return cls(
            rpc_url=rpc_url,
            contract_address=specific_address,
            artifact_path=artifact_path,
            w3_instance=w3_instance,
            election_id=election_id,
        )

    @property
    def rpc_url(self) -> str:
        if self._custom_rpc_url:
            return self._custom_rpc_url
        try:
            if current_app and current_app.config:
                return current_app.config.get('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')
        except RuntimeError:
            pass
        return os.getenv('BLOCKCHAIN_RPC_URL', 'http://127.0.0.1:8545')

    @property
    def contract_address(self) -> Optional[str]:
        if self._custom_contract_address:
            return self._custom_contract_address
        # Election-scoped instances MUST resolve exclusively from their own checkpoint (never cross-bind global env)
        if self._election_id is not None:
            cp = load_deployment_checkpoint(self._election_id)
            if cp and cp.get('contract_address'):
                return Web3.to_checksum_address(cp['contract_address'])
            return None
        try:
            if current_app and current_app.config:
                return current_app.config.get('BALLOTBOX_V2_CONTRACT_ADDRESS', None)
        except RuntimeError:
            pass
        return os.getenv('BALLOTBOX_V2_CONTRACT_ADDRESS', None)

    def get_web3(self) -> Web3:
        if self._w3 is not None:
            return self._w3
        return Web3(Web3.HTTPProvider(self.rpc_url))

    def get_contract(self, address: Optional[str] = None) -> Contract:
        target_addr = address or self.contract_address
        if not target_addr:
            if self._election_id is not None:
                raise ValueError(f"No election-specific EVotingBallotBoxV2 deployment checkpoint found for election {self._election_id}")
            raise ValueError("No EVotingBallotBoxV2 contract address specified")
        w3 = self.get_web3()
        return w3.eth.contract(address=Web3.to_checksum_address(target_addr), abi=self._abi)

    def resolve_admin_credentials(self) -> Tuple[str, str]:
        """Resolves the admin private key and address used to open and close elections."""
        admin_key = (
            (current_app.config.get('ADMIN_PRIVATE_KEY') if current_app and current_app.config else None)
            or os.getenv('ADMIN_PRIVATE_KEY')
            or '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
        )
        admin_addr = Account.from_key(admin_key).address
        return admin_key, Web3.to_checksum_address(admin_addr)

    def resolve_relayer_credentials(self) -> Tuple[Optional[str], str]:
        """
        Resolves and validates relayer credentials from server configuration.
        Returns: (relayer_private_key, relayer_address).
        Enforces:
        - RELAYER_PRIVATE_KEY derivation and validation.
        - Matching RELAYER_ACCOUNT if configured (fails closed on mismatch).
        - ALLOW_DEV_UNLOCKED_RELAYER defaults to False.
        - Unlocked accounts strictly forbidden in production and staging.
        - In development with ALLOW_DEV_UNLOCKED_RELAYER=True: validates RELAYER_ACCOUNT against w3.eth.accounts.
        """
        app_env = 'production'
        allow_dev = False
        private_key = None
        configured_account = None

        try:
            if current_app and current_app.config:
                app_env = str(current_app.config.get('APP_ENV', 'production')).lower()
                allow_dev = _parse_bool(current_app.config.get('ALLOW_DEV_UNLOCKED_RELAYER', False))
                private_key = current_app.config.get('RELAYER_PRIVATE_KEY')
                configured_account = current_app.config.get('RELAYER_ACCOUNT')
            else:
                app_env = str(os.getenv('APP_ENV', 'production')).lower()
                allow_dev = _parse_bool(os.getenv('ALLOW_DEV_UNLOCKED_RELAYER', False))
                private_key = os.getenv('RELAYER_PRIVATE_KEY')
                configured_account = os.getenv('RELAYER_ACCOUNT')
        except RuntimeError:
            app_env = str(os.getenv('APP_ENV', 'production')).lower()
            allow_dev = _parse_bool(os.getenv('ALLOW_DEV_UNLOCKED_RELAYER', False))
            private_key = os.getenv('RELAYER_PRIVATE_KEY')
            configured_account = os.getenv('RELAYER_ACCOUNT')

        # 1. Private Key Configured (Standard Secure Mode)
        if private_key:
            try:
                derived_address = Account.from_key(private_key).address
            except Exception as exc:
                raise RuntimeError("Invalid RELAYER_PRIVATE_KEY configuration: failed to derive address.") from exc

            derived_ck = Web3.to_checksum_address(derived_address)
            if configured_account:
                conf_ck = Web3.to_checksum_address(configured_account)
                if derived_ck != conf_ck:
                    raise RuntimeError(
                        "Security violation: Configured RELAYER_ACCOUNT does not match the address derived from RELAYER_PRIVATE_KEY."
                    )
            return private_key, derived_ck

        # 2. Unlocked Account (Only in Development with Explicit Opt-In)
        if app_env in ('production', 'staging'):
            raise RuntimeError(
                f"Environment '{app_env}' strictly requires a configured RELAYER_PRIVATE_KEY. "
                "Unlocked RPC relayer accounts are strictly prohibited in production and staging."
            )

        if app_env == 'development' and allow_dev is True:
            w3 = self.get_web3()
            node_accounts = [Web3.to_checksum_address(a) for a in (w3.eth.accounts or [])]
            if not node_accounts:
                raise RuntimeError("ALLOW_DEV_UNLOCKED_RELAYER is enabled but RPC node exposes zero unlocked accounts.")

            if configured_account:
                conf_ck = Web3.to_checksum_address(configured_account)
                if conf_ck not in node_accounts:
                    raise RuntimeError(
                        f"Configured RELAYER_ACCOUNT '{configured_account}' is not available among the RPC node's unlocked accounts: {node_accounts}"
                    )
                return None, conf_ck
            return None, node_accounts[0]

        raise RuntimeError(
            "No valid relayer configuration available. RELAYER_PRIVATE_KEY must be configured, "
            "or ALLOW_DEV_UNLOCKED_RELAYER must be explicitly set to True in development environment."
        )

    def _send_transaction(
        self,
        tx_fn: Any,
        from_address: str,
        private_key: Optional[str] = None,
        gas_limit: int = 1_500_000,
    ) -> Dict[str, Any]:
        """Builds, signs/sends, and confirms transaction with receipt."""
        w3 = self.get_web3()
        sender = Web3.to_checksum_address(from_address)
        tx_hash: Optional[str] = None

        if private_key:
            nonce = w3.eth.get_transaction_count(sender, 'pending')
            tx_dict = tx_fn.build_transaction({
                'from': sender,
                'nonce': nonce,
                'gas': gas_limit,
                'gasPrice': w3.eth.gas_price,
                'chainId': w3.eth.chain_id,
            })
            signed_tx = Account.sign_transaction(tx_dict, private_key)
            raw_signed_hash = getattr(signed_tx, 'hash', None)
            pre_tx_hash = None
            if isinstance(raw_signed_hash, (bytes, bytearray)):
                hex_str = raw_signed_hash.hex()
                pre_tx_hash = hex_str if hex_str.startswith('0x') else f'0x{hex_str}'
            try:
                tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                tx_hash = tx_hash_bytes.hex() if isinstance(tx_hash_bytes, bytes) else str(tx_hash_bytes)
                if not tx_hash.startswith('0x'):
                    tx_hash = '0x' + tx_hash
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout) as exc:
                raise BroadcastUncertainError(
                    f"Network transport timeout during send_raw_transaction: {exc}",
                    tx_hash=pre_tx_hash,
                ) from exc
            except Exception as exc:
                err_str = str(exc).lower()
                if any(x in err_str for x in ('nonce', 'already known', 'replacement', 'timeout', 'gateway', 'reset')):
                    raise BroadcastUncertainError(
                        f"Ambiguous provider response during send_raw_transaction: {exc}",
                        tx_hash=pre_tx_hash,
                    ) from exc
                raise
        else:
            try:
                tx_hash_bytes = tx_fn.transact({'from': sender, 'gas': gas_limit})
                tx_hash = tx_hash_bytes.hex() if isinstance(tx_hash_bytes, bytes) else str(tx_hash_bytes)
                if not tx_hash.startswith('0x'):
                    tx_hash = '0x' + tx_hash
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout) as exc:
                raise BroadcastUncertainError(f"Network transport timeout during transact: {exc}") from exc
            except Exception as exc:
                err_str = str(exc).lower()
                if any(x in err_str for x in ('nonce', 'already known', 'replacement', 'timeout', 'gateway', 'reset')):
                    raise BroadcastUncertainError(f"Ambiguous provider response during transact: {exc}") from exc
                raise

        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except TimeExhausted as exc:
            raise BroadcastUncertainError(
                f"Confirmation timeout waiting for receipt of transaction {tx_hash}",
                tx_hash=tx_hash
            ) from exc
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout) as exc:
            raise BroadcastUncertainError(
                f"Transport error while polling receipt for transaction {tx_hash}: {exc}",
                tx_hash=tx_hash
            ) from exc

        return {
            'status': receipt.get('status', 1),
            'tx_hash': tx_hash,
            'block_number': receipt.get('blockNumber'),
            'gas_used': receipt.get('gasUsed'),
        }

    def get_election_state(self, contract_address: Optional[str] = None) -> int:
        """Returns the current state enum integer from contract."""
        contract = self.get_contract(contract_address)
        return contract.functions.state().call()

    def get_election_id(self, contract_address: Optional[str] = None) -> int:
        """Returns the immutable electionId configured on the contract."""
        contract = self.get_contract(contract_address)
        return contract.functions.electionId().call()

    def get_candidate_count(self, contract_address: Optional[str] = None) -> int:
        """Returns the immutable candidateCount configured on the contract."""
        contract = self.get_contract(contract_address)
        return contract.functions.candidateCount().call()

    def get_total_active_ballots(self, contract_address: Optional[str] = None) -> int:
        """Returns the total number of active non-superseded ballots on the contract."""
        contract = self.get_contract(contract_address)
        return contract.functions.totalActiveBallots().call()

    def register_officer(
        self,
        officer_id: int,
        pub_key: Dict[str, int],
        pop: Dict[str, Any],
        officer_address: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Registers officer public key share with Schnorr PoP on EVotingBallotBoxV2.
        Submits via authorized relayer account.
        """
        resolved_key, resolved_addr = self.resolve_relayer_credentials()
        sender_address = resolved_addr
        if not private_key:
            private_key = resolved_key

        contract = self.get_contract(contract_address)
        pub_key_tuple = (int(pub_key['x']), int(pub_key['y']))
        pop_tuple = ((int(pop['r']['x']), int(pop['r']['y'])), int(pop['z']))

        tx_fn = contract.functions.registerOfficer(
            int(officer_id),
            pub_key_tuple,
            pop_tuple,
        )
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=300_000)

    def invalidate_key_registration(
        self,
        officer_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Allows an officer to reset key registration before voting opens."""
        contract = self.get_contract(contract_address)
        tx_fn = contract.functions.invalidateKeyRegistration()
        return self._send_transaction(tx_fn, officer_address, private_key, gas_limit=150_000)

    def open_voting(
        self,
        admin_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Admin opens voting once key registration is complete."""
        contract = self.get_contract(contract_address)
        tx_fn = contract.functions.openVoting()
        return self._send_transaction(tx_fn, admin_address, private_key, gas_limit=100_000)

    def close_voting(
        self,
        admin_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Admin closes voting, initiating 72-hour tally period."""
        contract = self.get_contract(contract_address)
        tx_fn = contract.functions.closeVoting()
        return self._send_transaction(tx_fn, admin_address, private_key, gas_limit=150_000)

    def cast_ballot(
        self,
        pseudonym: Union[str, bytes],
        sequence: int,
        ciphertexts: List[Dict[str, Any]],
        proof: Dict[str, Any],
        sender_address: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submits encrypted ballot vector with non-circular CDS proof to EVotingBallotBoxV2.
        If sender_address or private_key is omitted, resolves from server relayer configuration.
        """
        if not sender_address:
            resolved_key, resolved_addr = self.resolve_relayer_credentials()
            sender_address = resolved_addr
            if not private_key:
                private_key = resolved_key

        contract = self.get_contract(contract_address)

        if isinstance(pseudonym, str):
            p_hex = pseudonym[2:] if pseudonym.startswith("0x") else pseudonym
            pseudo_bytes = bytes.fromhex(p_hex)
        else:
            pseudo_bytes = pseudonym

        # Format Ciphertext[]
        ct_tuples = [
            ((int(ct['a']['x']), int(ct['a']['y'])), (int(ct['b']['x']), int(ct['b']['y'])))
            for ct in ciphertexts
        ]

        # Format CandidateCommitments[]
        comm_tuples = [
            (
                (int(c['t_a_0']['x']), int(c['t_a_0']['y'])),
                (int(c['t_b_0']['x']), int(c['t_b_0']['y'])),
                (int(c['t_a_1']['x']), int(c['t_a_1']['y'])),
                (int(c['t_b_1']['x']), int(c['t_b_1']['y'])),
            )
            for c in proof['candidateCommitments']
        ]

        # Format CandidateProof[]
        cp_tuples = [
            (int(cp['c0']), int(cp['c1']), int(cp['z0']), int(cp['z1']))
            for cp in proof['candidateProofs']
        ]

        # Format SumCommitments
        sum_comm = (
            (int(proof['sumCommitments']['t_a_sum']['x']), int(proof['sumCommitments']['t_a_sum']['y'])),
            (int(proof['sumCommitments']['t_b_sum']['x']), int(proof['sumCommitments']['t_b_sum']['y'])),
        )

        proof_tuple = (
            comm_tuples,
            cp_tuples,
            sum_comm,
            int(proof['z_sum']),
        )

        tx_fn = contract.functions.castBallot(
            pseudo_bytes,
            int(sequence),
            ct_tuples,
            proof_tuple,
        )
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=1_800_000)

    def submit_decryption_shares(
        self,
        officer_id: int,
        shares: List[Dict[str, int]],
        proofs: List[Dict[str, Any]],
        officer_address: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submits officer decryption shares and DLEQ proofs via authorized relayer."""
        resolved_key, resolved_addr = self.resolve_relayer_credentials()
        sender_address = resolved_addr
        if not private_key:
            private_key = resolved_key

        contract = self.get_contract(contract_address)

        share_tuples = [(int(s['x']), int(s['y'])) for s in shares]
        proof_tuples = [
            (
                (int(p['u']['x']), int(p['u']['y'])),
                (int(p['v']['x']), int(p['v']['y'])),
                int(p['z']),
            )
            for p in proofs
        ]

        tx_fn = contract.functions.submitDecryptionShares(
            int(officer_id),
            share_tuples,
            proof_tuples,
        )
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=600_000)

    def verify_chain_synchronization(self, election: Any, contract_address: Optional[str] = None) -> Tuple[bool, str]:
        """
        Five-factor verification that the local blockchain has not reset and matches election state:
        1. Bytecode existence: Verifies contract bytecode is deployed at target_addr.
        2. Election binding: Contract immutable electionId matches DB election.id.
        3. Block height progression: Verifies current chain block number > 0 (detects genesis wipe / reset).
        4. Runtime bytecode sanity: Verifies bytecode size conforms to compiled EVotingBallotBoxV2 runtime.
        5. Persistent deployment fingerprint / checkpoint verification (if checkpoint exists):
           - Target address matches checkpoint contract_address.
           - Genesis block hash matches original deployment chain.
           - Deployment block hash matches at recorded deployment_block_number.
           - Deployment transaction receipt matches contract address.
           Detects node restarts followed by redeployment at the same deterministic address.
        """
        target_addr = contract_address or self.contract_address
        if not target_addr:
            return False, "NO_CONTRACT_ADDRESS_CONFIGURED"

        w3 = self.get_web3()
        try:
            # Factor 1: Bytecode presence
            code = w3.eth.get_code(Web3.to_checksum_address(target_addr))
            if not code or code == b'' or code.hex() in ('0x', '0x0'):
                return False, "CHAIN_RESET_DETECTED: Contract bytecode missing on connected node (Hardhat restart detected)."

            # Factor 2: On-chain election ID binding
            contract = self.get_contract(target_addr)
            onchain_eid = contract.functions.electionId().call()
            expected_eid = getattr(election, 'id', None)
            if expected_eid is not None and onchain_eid != int(expected_eid):
                return False, f"CHAIN_DESYNCHRONIZED: On-chain election ID {onchain_eid} does not match expected {expected_eid}."

            # Factor 2b: On-chain candidate count binding (when verifiable integer metadata exists)
            expected_cc = getattr(election, 'candidate_count', None)
            if isinstance(expected_cc, int) and not isinstance(expected_cc, bool) and expected_cc > 0:
                try:
                    onchain_cc = contract.functions.candidateCount().call()
                    if isinstance(onchain_cc, int) and not isinstance(onchain_cc, bool) and onchain_cc != int(expected_cc):
                        return False, f"CHAIN_DESYNCHRONIZED: On-chain candidate count {onchain_cc} does not match expected {expected_cc}."
                except Exception:
                    pass

            # Factor 3: Block height progression (block_number > 0)
            current_block = w3.eth.block_number
            if current_block is None or current_block < 1:
                return False, "CHAIN_RESET_DETECTED: Block height is 0 (uninitialized or reset node detected)."

            # Factor 4: Runtime bytecode consistency (EVotingBallotBoxV2 bytecode size validation)
            code_len = len(code)
            if code_len < 5000:
                return False, f"CHAIN_DESYNCHRONIZED: Bytecode size ({code_len} bytes) is incompatible with EVotingBallotBoxV2 runtime."

            # Factor 5: Persistent Deployment Checkpoint Fingerprint Check
            if expected_eid is not None:
                checkpoint = load_deployment_checkpoint(expected_eid)
                if checkpoint:
                    # 5a. Verify target_addr and chain_id match checkpoint metadata
                    cp_addr = checkpoint.get('contract_address')
                    if cp_addr and Web3.to_checksum_address(target_addr) != Web3.to_checksum_address(cp_addr):
                        return False, f"CHAIN_DESYNCHRONIZED: Contract address {target_addr} does not match checkpoint {cp_addr}."

                    cp_chain_id = checkpoint.get('chain_id')
                    if cp_chain_id is not None:
                        try:
                            actual_chain_id = w3.eth.chain_id
                            if isinstance(actual_chain_id, int) and not isinstance(actual_chain_id, bool):
                                if int(cp_chain_id) != int(actual_chain_id):
                                    return False, f"CHAIN_DESYNCHRONIZED: Checkpoint chain_id ({cp_chain_id}) does not match connected chain ({actual_chain_id})."
                        except Exception as exc:
                            return False, f"CHAIN_DESYNCHRONIZED: Unable to verify chain_id against checkpoint: {exc}"

                    # 5b. Verify Chain Genesis Block Hash
                    try:
                        genesis_block = w3.eth.get_block(0)
                        gen_hash = genesis_block.get('hash', b'').hex() if isinstance(genesis_block.get('hash'), bytes) else str(genesis_block.get('hash'))
                        if not gen_hash.startswith('0x'):
                            gen_hash = '0x' + gen_hash
                        if gen_hash.lower() != checkpoint.get('genesis_block_hash', '').lower():
                            return False, "CHAIN_RESET_DETECTED: Genesis block hash mismatch. The underlying blockchain node was restarted or recreated."
                    except Exception as exc:
                        return False, f"CHAIN_RESET_DETECTED: Failed to query genesis block: {exc}"

                    # 5c. Verify Deployment Block Hash at recorded block height
                    cp_block_num = checkpoint.get('deployment_block_number')
                    if cp_block_num is not None:
                        if cp_block_num > current_block:
                            return False, f"CHAIN_RESET_DETECTED: Current block ({current_block}) is lower than deployment block ({cp_block_num}). Chain was reset."
                        try:
                            dep_block = w3.eth.get_block(cp_block_num)
                            dep_hash = dep_block.get('hash', b'').hex() if isinstance(dep_block.get('hash'), bytes) else str(dep_block.get('hash'))
                            if not dep_hash.startswith('0x'):
                                dep_hash = '0x' + dep_hash
                            if dep_hash.lower() != checkpoint.get('deployment_block_hash', '').lower():
                                return False, "CHAIN_RESET_DETECTED: Deployment block hash mismatch. The underlying blockchain state was recreated."
                        except Exception as exc:
                            return False, f"CHAIN_RESET_DETECTED: Failed to query deployment block {cp_block_num}: {exc}"

                    # 5d. Verify Deployment Transaction
                    cp_tx_hash = checkpoint.get('deployment_tx_hash')
                    if cp_tx_hash:
                        try:
                            receipt = w3.eth.get_transaction_receipt(cp_tx_hash)
                            if not receipt:
                                return False, "CHAIN_RESET_DETECTED: Original deployment transaction receipt not found on chain."
                            rcpt_contract = receipt.get('contractAddress')
                            if rcpt_contract and Web3.to_checksum_address(rcpt_contract) != Web3.to_checksum_address(target_addr):
                                return False, "CHAIN_RESET_DETECTED: Deployment transaction contract address does not match target address."
                        except Exception as exc:
                            return False, f"CHAIN_RESET_DETECTED: Deployment transaction missing on connected node: {exc}"

            return True, "OK"
        except Exception as exc:
            return False, f"CHAIN_VERIFICATION_FAILED: {exc}"

    def finalize_tally(
        self,
        tallies: List[int],
        sender_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Finalizes tally by zero-trust verification against aggregate ciphertexts."""
        contract = self.get_contract(contract_address)
        tallies_ints = [int(t) for t in tallies]
        tx_fn = contract.functions.finalizeTally(tallies_ints)
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=300_000)

    def finalize_zero_vote_election(
        self,
        sender_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Finalizes an election that recorded zero active ballots without fabricating votes."""
        contract = self.get_contract(contract_address)
        tx_fn = contract.functions.finalizeZeroVoteElection()
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=300_000)

    def mark_tally_stalled(
        self,
        sender_address: str,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Permissionless trigger to mark election TallyStalled after 72 hours."""
        contract = self.get_contract(contract_address)
        tx_fn = contract.functions.markTallyStalled()
        return self._send_transaction(tx_fn, sender_address, private_key, gas_limit=100_000)

    def get_aggregate_ciphertext(self, candidate_index: int, contract_address: Optional[str] = None) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Returns (aggregateA, aggregateB) for candidate coordinate j."""
        contract = self.get_contract(contract_address)
        res = contract.functions.getAggregateCiphertext(int(candidate_index)).call()
        return ((res[0][0], res[0][1]), (res[1][0], res[1][1]))

    def get_final_tally(self, candidate_index: int, contract_address: Optional[str] = None) -> int:
        """Returns verified final tally for candidate coordinate j."""
        contract = self.get_contract(contract_address)
        return contract.functions.getFinalTally(int(candidate_index)).call()

    @staticmethod
    def _resolve_expected_candidate_count(election: Any) -> int:
        cc = getattr(election, 'candidate_count', None)
        if isinstance(cc, int) and not isinstance(cc, bool) and cc > 0:
            return int(cc)
        cands = getattr(election, 'candidates', None)
        if cands is not None:
            try:
                cnt = len(list(cands))
                if cnt > 0:
                    return cnt
            except Exception:
                pass
        return 0

    def verify_deployed_v2_contract(
        self,
        contract_address: str,
        election: Any,
        expected_chain_id: Optional[int] = None,
        expected_admin: Optional[str] = None,
        expected_relayer: Optional[str] = None,
        expected_verifier: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Fail-closed verification of a deployed EVotingBallotBoxV2 instance.
        Validates runtime bytecode, finalizeZeroVoteElection support, chain_id,
        electionId, candidateCount, admin, relayer, and verifier (with deployed code).
        """
        if not contract_address:
            return False, "NO_CONTRACT_ADDRESS_CONFIGURED"

        w3 = self.get_web3()
        try:
            target_addr = Web3.to_checksum_address(contract_address)
            code = w3.eth.get_code(target_addr)
            if not code or code == b'' or (isinstance(code, (bytes, bytearray)) and len(code) == 0):
                return False, f"CHAIN_RESET_DETECTED: Empty bytecode at {target_addr}"
            code_len = len(code)
            if code_len < 5000:
                return False, f"INVALID_BYTECODE: Contract at {target_addr} too small ({code_len} bytes)"

            actual_chain_id = w3.eth.chain_id
            if not isinstance(actual_chain_id, int) or isinstance(actual_chain_id, bool) or actual_chain_id <= 0:
                return False, f"CHAIN_ID_MISMATCH: Invalid chain_id returned by node ({actual_chain_id})"
            if expected_chain_id is not None and int(expected_chain_id) != int(actual_chain_id):
                return False, f"CHAIN_ID_MISMATCH: Expected chain_id {expected_chain_id}, connected to {actual_chain_id}"

            block_num = w3.eth.block_number
            if block_num is None or int(block_num) < 1:
                return False, "CHAIN_RESET_DETECTED: Chain block height is 0"

            if not _contract_supports_zero_vote_abi(self._abi):
                return False, "MISSING_ZERO_VOTE_SUPPORT: Loaded EVotingBallotBoxV2 ABI lacks finalizeZeroVoteElection"

            selector_bytes = Web3.keccak(text="finalizeZeroVoteElection()")[:4]
            selector_hex = selector_bytes.hex().lower()
            if selector_hex.startswith('0x'):
                selector_hex = selector_hex[2:]
            code_hex = (code.hex() if isinstance(code, (bytes, bytearray)) else str(code)).lower()
            if code_hex.startswith('0x'):
                code_hex = code_hex[2:]
            if selector_hex not in code_hex:
                return False, "MISSING_ZERO_VOTE_SUPPORT: Deployed bytecode does not implement finalizeZeroVoteElection()"

            contract = self.get_contract(target_addr)
            if not hasattr(contract.functions, 'finalizeZeroVoteElection'):
                return False, "MISSING_ZERO_VOTE_SUPPORT: Contract interface lacks finalizeZeroVoteElection"

            expected_eid = int(election.id)
            onchain_eid = contract.functions.electionId().call()
            if int(onchain_eid) != expected_eid:
                return False, f"CONTRACT_ELECTION_MISMATCH: Contract electionId={onchain_eid}, expected {expected_eid}"

            expected_cc = self._resolve_expected_candidate_count(election)
            if expected_cc < 1:
                return False, "INVALID_CANDIDATE_COUNT: Election has no configured candidates"
            onchain_cc = contract.functions.candidateCount().call()
            if int(onchain_cc) != expected_cc:
                return False, f"CONTRACT_CANDIDATE_COUNT_MISMATCH: Contract candidateCount={onchain_cc}, expected {expected_cc}"

            exp_admin = Web3.to_checksum_address(expected_admin or self.resolve_admin_credentials()[1])
            onchain_admin = Web3.to_checksum_address(contract.functions.admin().call())
            if onchain_admin != exp_admin:
                return False, f"CONTRACT_ADMIN_MISMATCH: Contract admin={onchain_admin}, expected {exp_admin}"

            exp_relayer = Web3.to_checksum_address(expected_relayer or self.resolve_relayer_credentials()[1])
            onchain_relayer = Web3.to_checksum_address(contract.functions.relayer().call())
            if onchain_relayer != exp_relayer:
                return False, f"CONTRACT_RELAYER_MISMATCH: Contract relayer={onchain_relayer}, expected {exp_relayer}"

            onchain_verifier = Web3.to_checksum_address(contract.functions.verifier().call())
            if onchain_verifier == '0x0000000000000000000000000000000000000000':
                return False, "VERIFIER_CONTRACT_MISSING: On-chain verifier is zero address"
            if expected_verifier and onchain_verifier != Web3.to_checksum_address(expected_verifier):
                return False, f"VERIFIER_CONTRACT_MISMATCH: Contract verifier={onchain_verifier}, expected {expected_verifier}"
            verifier_code = w3.eth.get_code(onchain_verifier)
            if not verifier_code or len(verifier_code) == 0:
                return False, f"VERIFIER_CONTRACT_MISSING: No runtime bytecode at verifier {onchain_verifier}"

            return True, "OK"
        except Exception as exc:
            return False, f"CONTRACT_VERIFICATION_FAILED: {exc}"

    def _safe_wait_for_receipt(self, w3: Web3, tx_hash: str, timeout: int = 120) -> Any:
        try:
            return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        except (TimeExhausted, TimeoutError, requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout) as exc:
            raise BroadcastUncertainError(
                f"DEPLOYMENT_PENDING: Receipt wait timed out/disconnected for tx {tx_hash}: {exc}",
                tx_hash=tx_hash,
            ) from exc

    def _reconcile_pending_tx(
        self,
        w3: Web3,
        election_id: int,
        prov_state: Dict[str, Any],
        checkpoint_dir: Optional[str] = None,
        wait_timeout: int = 15,
    ) -> Tuple[str, Optional[Any], str]:
        """
        Reconcile an existing DEPLOYMENT_PENDING transaction before considering any broadcast.
        Returns (outcome, receipt, reason) where outcome is one of:
        CONFIRMED | REVERTED | PENDING | FAILED.
        """
        tx_hash = prov_state.get('tx_hash')
        sender_address = prov_state.get('sender_address')
        sender_nonce = prov_state.get('sender_nonce')
        persisted_chain_id = prov_state.get('chain_id')
        persisted_genesis = prov_state.get('genesis_block_hash')

        if persisted_chain_id is not None and int(w3.eth.chain_id) != int(persisted_chain_id):
            return 'FAILED', None, f"CHAIN_ID_MISMATCH: Pending tx chain_id={persisted_chain_id}, connected chain_id={w3.eth.chain_id}"

        if persisted_genesis:
            current_genesis = _extract_block_hash_hex(w3.eth.get_block(0))
            if current_genesis and current_genesis != _normalize_hex_hash(persisted_genesis):
                return 'FAILED', None, "CHAIN_RESET_DETECTED: Genesis block hash changed while deployment transaction was pending"

        if not tx_hash:
            return 'FAILED', None, "DEPLOYMENT_STATE_CORRUPT: Pending deployment missing tx_hash"

        # 1. Check receipt first — tx may already have succeeded despite earlier client timeout
        receipt = None
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            receipt = None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout, TimeoutError) as exc:
            return 'PENDING', None, f"DEPLOYMENT_PENDING: Unable to reach node to check receipt for {tx_hash}: {exc}"

        if receipt is not None:
            status = receipt.get('status') if isinstance(receipt, dict) else getattr(receipt, 'status', None)
            if status == 1:
                return 'CONFIRMED', receipt, "OK"
            return 'REVERTED', receipt, f"DEPLOYMENT_TX_REVERTED: Transaction {tx_hash} mined with status={status}"

        # 2. Check if tx is known / queued in mempool
        tx_obj = None
        try:
            tx_obj = w3.eth.get_transaction(tx_hash)
        except TransactionNotFound:
            tx_obj = None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout, TimeoutError) as exc:
            return 'PENDING', None, f"DEPLOYMENT_PENDING: Unable to query pending tx {tx_hash}: {exc}"

        if tx_obj is not None:
            try:
                waited_rcpt = self._safe_wait_for_receipt(w3, tx_hash, timeout=wait_timeout)
                status = waited_rcpt.get('status') if isinstance(waited_rcpt, dict) else getattr(waited_rcpt, 'status', None)
                if status == 1:
                    return 'CONFIRMED', waited_rcpt, "OK"
                return 'REVERTED', waited_rcpt, f"DEPLOYMENT_TX_REVERTED: Transaction {tx_hash} mined with status={status}"
            except BroadcastUncertainError:
                return 'PENDING', None, f"DEPLOYMENT_PENDING: Transaction {tx_hash} is still awaiting confirmation"

        # 3. Neither receipt nor mempool entry found — check confirmed sender nonce
        if sender_address is not None and sender_nonce is not None:
            confirmed_nonce = int(w3.eth.get_transaction_count(Web3.to_checksum_address(sender_address), 'latest'))
            if confirmed_nonce > int(sender_nonce):
                return (
                    'FAILED',
                    None,
                    f"DEPLOYMENT_NONCE_CONSUMED: Sender nonce ({confirmed_nonce}) passed recorded nonce ({sender_nonce}) without receipt for {tx_hash}",
                )

        return (
            'PENDING',
            None,
            f"DEPLOYMENT_PENDING: Prior broadcast {tx_hash} (nonce={sender_nonce}) outcome still unconfirmed; refusing duplicate deployment",
        )

    def _sign_persist_and_broadcast_deploy(
        self,
        w3: Web3,
        election_id: int,
        step_name: str,
        deploy_callable: Any,
        sender_addr: str,
        sender_key: str,
        default_gas: int,
        prov_state: Dict[str, Any],
        checkpoint_dir: Optional[str] = None,
        wait_timeout: int = 120,
    ) -> Tuple[str, Any]:
        """
        Deterministically compute tx_hash before broadcast, persist DEPLOYMENT_PENDING state
        (tx_hash + sender_nonce), broadcast, and wait for confirmation.
        """
        sender_ck = Web3.to_checksum_address(sender_addr)
        nonce = int(w3.eth.get_transaction_count(sender_ck, 'pending'))
        chain_id = int(w3.eth.chain_id)
        try:
            est_gas = int(deploy_callable.estimate_gas({'from': sender_ck}))
            gas_limit = max(est_gas + 100_000, default_gas)
        except Exception:
            gas_limit = default_gas

        tx_dict = deploy_callable.build_transaction({
            'from': sender_ck,
            'nonce': nonce,
            'gas': gas_limit,
            'gasPrice': w3.eth.gas_price,
            'chainId': chain_id,
        })
        signed_tx = Account.sign_transaction(tx_dict, sender_key)
        raw_hash = signed_tx.hash.hex() if isinstance(signed_tx.hash, (bytes, bytearray)) else str(signed_tx.hash)
        tx_hash = _normalize_hex_hash(raw_hash)

        prov_state.update({
            'election_id': int(election_id),
            'status': PROV_PENDING,
            'pending_step': step_name,
            'tx_hash': tx_hash,
            'sender_address': sender_ck,
            'sender_nonce': nonce,
            'chain_id': chain_id,
        })
        save_provisioning_state(election_id, prov_state, checkpoint_dir=checkpoint_dir)

        try:
            broadcast_hash_raw = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            broadcast_hash = _normalize_hex_hash(
                broadcast_hash_raw.hex() if isinstance(broadcast_hash_raw, (bytes, bytearray)) else str(broadcast_hash_raw)
            )
            if broadcast_hash and broadcast_hash != tx_hash:
                tx_hash = broadcast_hash
                prov_state['tx_hash'] = tx_hash
                save_provisioning_state(election_id, prov_state, checkpoint_dir=checkpoint_dir)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, socket.timeout, TimeoutError) as exc:
            raise BroadcastUncertainError(
                f"DEPLOYMENT_PENDING: Broadcast timeout/disconnect for {step_name} tx {tx_hash}: {exc}",
                tx_hash=tx_hash,
            ) from exc
        except Exception as exc:
            err_str = str(exc).lower()
            if any(k in err_str for k in ('nonce', 'already known', 'replacement', 'timeout', 'gateway', 'reset', 'etimedout')):
                raise BroadcastUncertainError(
                    f"DEPLOYMENT_PENDING: Ambiguous broadcast response for {step_name} tx {tx_hash}: {exc}",
                    tx_hash=tx_hash,
                ) from exc
            prov_state.update({
                'status': PROV_FAILED,
                'error': f"{step_name}_BROADCAST_REJECTED: {exc}",
                'last_failed_tx_hash': tx_hash,
            })
            prov_state.pop('tx_hash', None)
            prov_state.pop('pending_step', None)
            save_provisioning_state(election_id, prov_state, checkpoint_dir=checkpoint_dir)
            raise

        receipt = self._safe_wait_for_receipt(w3, tx_hash, timeout=wait_timeout)
        status = receipt.get('status') if isinstance(receipt, dict) else getattr(receipt, 'status', None)
        contract_addr = receipt.get('contractAddress') if isinstance(receipt, dict) else getattr(receipt, 'contractAddress', None)
        if status != 1 or not contract_addr:
            prov_state.update({
                'status': PROV_FAILED,
                'error': f"{step_name}_TX_REVERTED: tx={tx_hash}, status={status}",
                'last_failed_tx_hash': tx_hash,
            })
            prov_state.pop('tx_hash', None)
            prov_state.pop('pending_step', None)
            save_provisioning_state(election_id, prov_state, checkpoint_dir=checkpoint_dir)
            raise RuntimeError(prov_state['error'])

        return tx_hash, receipt

    def deploy_election_contract(
        self,
        election: Any,
        checkpoint_dir: Optional[str] = None,
        expected_chain_id: Optional[int] = None,
        wait_timeout: int = 120,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Idempotently provision and verify a dedicated BN254CDSVerifier + EVotingBallotBoxV2
        pair for the given election, with pre-broadcast tx_hash/nonce recovery and atomic checkpointing.
        Never overwrites an existing checkpoint; fails closed on any mismatch or pending tx.
        Returns: (ok, status_message, checkpoint_dict_or_None)
        """
        eid = int(election.id)
        candidate_count = self._resolve_expected_candidate_count(election)
        if candidate_count < 1:
            return False, "INVALID_CANDIDATE_COUNT: Cannot deploy V2 contract without at least 1 candidate.", None

        w3 = self.get_web3()
        try:
            if not w3 or not w3.is_connected():
                return False, "RPC_UNAVAILABLE: Blockchain node is not connected.", None
        except Exception as exc:
            return False, f"RPC_UNAVAILABLE: {exc}", None

        actual_chain_id = int(w3.eth.chain_id)
        if expected_chain_id is not None and int(expected_chain_id) != actual_chain_id:
            msg = f"CHAIN_ID_MISMATCH: Expected chain_id={expected_chain_id}, connected chain_id={actual_chain_id}"
            save_provisioning_state(eid, {
                'election_id': eid,
                'status': PROV_FAILED,
                'error': msg,
                'chain_id': actual_chain_id,
            }, checkpoint_dir=checkpoint_dir)
            return False, msg, None

        # 1. Existing checkpoint check (NEVER overwrite an existing checkpoint file)
        if _checkpoint_file_exists_for_election(eid, checkpoint_dir=checkpoint_dir):
            existing_cp = load_deployment_checkpoint(eid, checkpoint_dir=checkpoint_dir)
            if not existing_cp:
                msg = f"CHECKPOINT_MISMATCH: Existing checkpoint file for election {eid} is invalid or bound to a different election; refusing overwrite."
                save_provisioning_state(eid, {
                    'election_id': eid,
                    'status': PROV_FAILED,
                    'error': msg,
                }, checkpoint_dir=checkpoint_dir)
                return False, msg, None

            ok_sync, reason_sync = self.verify_chain_synchronization(election, contract_address=existing_cp['contract_address'])
            if not ok_sync:
                save_provisioning_state(eid, {
                    'election_id': eid,
                    'status': PROV_FAILED,
                    'error': f"CHECKPOINT_MISMATCH: {reason_sync}",
                    'contract_address': existing_cp['contract_address'],
                }, checkpoint_dir=checkpoint_dir)
                return False, f"CHECKPOINT_MISMATCH: {reason_sync}", None

            ok_v2, reason_v2 = self.verify_deployed_v2_contract(
                existing_cp['contract_address'],
                election,
                expected_chain_id=existing_cp.get('chain_id', actual_chain_id),
                expected_relayer=existing_cp.get('relayer_address'),
                expected_verifier=existing_cp.get('verifier_address'),
            )
            if not ok_v2:
                save_provisioning_state(eid, {
                    'election_id': eid,
                    'status': PROV_FAILED,
                    'error': reason_v2,
                    'contract_address': existing_cp['contract_address'],
                }, checkpoint_dir=checkpoint_dir)
                return False, reason_v2, None

            return True, PROV_VERIFIED, existing_cp

        # 2. Load credentials & artifacts before any broadcast
        admin_key, admin_addr = self.resolve_admin_credentials()
        _, relayer_addr = self.resolve_relayer_credentials()
        genesis_hash = _extract_block_hash_hex(w3.eth.get_block(0))

        box_abi, box_bytecode = load_v2_contract_artifact(self._artifact_path)
        verifier_abi, verifier_bytecode = load_v2_verifier_artifact()
        self._abi = box_abi

        # 3. Load/reconcile persisted provisioning journal
        prov_state = load_provisioning_state(eid, checkpoint_dir=checkpoint_dir) or {
            'election_id': eid,
            'status': PROV_NOT_DEPLOYED,
            'genesis_block_hash': genesis_hash,
            'chain_id': actual_chain_id,
            'admin_address': admin_addr,
            'relayer_address': relayer_addr,
        }
        if not prov_state.get('genesis_block_hash'):
            prov_state['genesis_block_hash'] = genesis_hash

        verifier_addr = prov_state.get('verifier_address')
        verifier_confirmed = bool(verifier_addr)

        if prov_state.get('status') == PROV_PENDING and prov_state.get('tx_hash'):
            pending_step = prov_state.get('pending_step')
            outcome, rec_receipt, rec_reason = self._reconcile_pending_tx(
                w3,
                eid,
                prov_state,
                checkpoint_dir=checkpoint_dir,
                wait_timeout=min(wait_timeout, 15),
            )
            if outcome == 'PENDING':
                return False, rec_reason, None
            if outcome in ('REVERTED', 'FAILED'):
                prov_state.update({
                    'status': PROV_FAILED,
                    'error': rec_reason,
                    'last_failed_tx_hash': prov_state.get('tx_hash'),
                })
                prov_state.pop('tx_hash', None)
                prov_state.pop('pending_step', None)
                save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
                return False, rec_reason, None

            # outcome == 'CONFIRMED'
            if pending_step == 'VERIFIER':
                rec_addr = rec_receipt.get('contractAddress') if isinstance(rec_receipt, dict) else getattr(rec_receipt, 'contractAddress', None)
                if not rec_addr:
                    prov_state.update({'status': PROV_FAILED, 'error': "VERIFIER_RECEIPT_NO_ADDRESS"})
                    save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
                    return False, "VERIFIER_RECEIPT_NO_ADDRESS", None
                verifier_addr = Web3.to_checksum_address(rec_addr)
                verifier_confirmed = True
                prov_state.update({
                    'verifier_address': verifier_addr,
                    'verifier_tx_hash': prov_state.get('tx_hash'),
                    'status': PROV_PENDING,
                })
                prov_state.pop('tx_hash', None)
                prov_state.pop('pending_step', None)
                save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
            elif pending_step == 'BALLOT_BOX':
                return self._finalize_verified_checkpoint(
                    w3=w3,
                    election=election,
                    receipt=rec_receipt,
                    tx_hash=prov_state['tx_hash'],
                    verifier_address=verifier_addr,
                    admin_addr=admin_addr,
                    relayer_addr=relayer_addr,
                    genesis_hash=genesis_hash,
                    chain_id=actual_chain_id,
                    candidate_count=candidate_count,
                    prov_state=prov_state,
                    checkpoint_dir=checkpoint_dir,
                )

        # 4. Deploy BN254CDSVerifier if not already confirmed
        if not verifier_confirmed:
            verifier_factory = w3.eth.contract(abi=verifier_abi, bytecode=verifier_bytecode)
            try:
                v_tx_hash, v_receipt = self._sign_persist_and_broadcast_deploy(
                    w3=w3,
                    election_id=eid,
                    step_name='VERIFIER',
                    deploy_callable=verifier_factory.constructor(),
                    sender_addr=admin_addr,
                    sender_key=admin_key,
                    default_gas=2_500_000,
                    prov_state=prov_state,
                    checkpoint_dir=checkpoint_dir,
                    wait_timeout=wait_timeout,
                )
            except BroadcastUncertainError as exc:
                return False, str(exc), None
            except Exception as exc:
                return False, f"VERIFIER_DEPLOYMENT_FAILED: {exc}", None

            v_addr_raw = v_receipt.get('contractAddress') if isinstance(v_receipt, dict) else getattr(v_receipt, 'contractAddress', None)
            verifier_addr = Web3.to_checksum_address(v_addr_raw)
            prov_state.update({
                'verifier_address': verifier_addr,
                'verifier_tx_hash': v_tx_hash,
                'status': PROV_PENDING,
            })
            prov_state.pop('tx_hash', None)
            prov_state.pop('pending_step', None)
            save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)

        # 5. Deploy EVotingBallotBoxV2(electionId, candidateCount, relayer, verifier)
        box_factory = w3.eth.contract(abi=box_abi, bytecode=box_bytecode)
        try:
            box_tx_hash, box_receipt = self._sign_persist_and_broadcast_deploy(
                w3=w3,
                election_id=eid,
                step_name='BALLOT_BOX',
                deploy_callable=box_factory.constructor(
                    eid,
                    candidate_count,
                    Web3.to_checksum_address(relayer_addr),
                    Web3.to_checksum_address(verifier_addr),
                ),
                sender_addr=admin_addr,
                sender_key=admin_key,
                default_gas=4_500_000,
                prov_state=prov_state,
                checkpoint_dir=checkpoint_dir,
                wait_timeout=wait_timeout,
            )
        except BroadcastUncertainError as exc:
            return False, str(exc), None
        except Exception as exc:
            return False, f"BALLOT_BOX_DEPLOYMENT_FAILED: {exc}", None

        return self._finalize_verified_checkpoint(
            w3=w3,
            election=election,
            receipt=box_receipt,
            tx_hash=box_tx_hash,
            verifier_address=verifier_addr,
            admin_addr=admin_addr,
            relayer_addr=relayer_addr,
            genesis_hash=genesis_hash,
            chain_id=actual_chain_id,
            candidate_count=candidate_count,
            prov_state=prov_state,
            checkpoint_dir=checkpoint_dir,
        )

    def _finalize_verified_checkpoint(
        self,
        w3: Web3,
        election: Any,
        receipt: Any,
        tx_hash: str,
        verifier_address: Optional[str],
        admin_addr: str,
        relayer_addr: str,
        genesis_hash: str,
        chain_id: int,
        candidate_count: int,
        prov_state: Dict[str, Any],
        checkpoint_dir: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Verify deployed EVotingBallotBoxV2 strictly before atomically writing its checkpoint."""
        eid = int(election.id)
        raw_addr = receipt.get('contractAddress') if isinstance(receipt, dict) else getattr(receipt, 'contractAddress', None)
        block_num = receipt.get('blockNumber') if isinstance(receipt, dict) else getattr(receipt, 'blockNumber', None)
        if not raw_addr or block_num is None:
            msg = f"DEPLOYMENT_FAILED: Missing contractAddress or blockNumber in receipt for {tx_hash}"
            prov_state.update({'status': PROV_FAILED, 'error': msg})
            save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
            return False, msg, None

        contract_addr = Web3.to_checksum_address(raw_addr)
        ok_v2, reason_v2 = self.verify_deployed_v2_contract(
            contract_addr,
            election,
            expected_chain_id=chain_id,
            expected_admin=admin_addr,
            expected_relayer=relayer_addr,
            expected_verifier=verifier_address,
        )
        if not ok_v2:
            prov_state.update({
                'status': PROV_FAILED,
                'error': reason_v2,
                'contract_address': contract_addr,
            })
            save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
            return False, reason_v2, None

        dep_block_hash = _extract_block_hash_hex(w3.eth.get_block(int(block_num)))
        resolved_verifier = verifier_address or Web3.to_checksum_address(self.get_contract(contract_addr).functions.verifier().call())

        save_deployment_checkpoint(
            election_id=eid,
            contract_address=contract_addr,
            verifier_address=resolved_verifier,
            relayer_address=relayer_addr,
            deployment_tx_hash=tx_hash,
            deployment_block_number=int(block_num),
            deployment_block_hash=dep_block_hash,
            genesis_block_hash=genesis_hash,
            chain_id=chain_id,
            candidate_count=candidate_count,
            checkpoint_dir=checkpoint_dir,
            admin_address=admin_addr,
            overwrite=False,
        )
        cp_data = load_deployment_checkpoint(eid, checkpoint_dir=checkpoint_dir)
        prov_state.update({
            'status': PROV_VERIFIED,
            'contract_address': contract_addr,
            'verifier_address': resolved_verifier,
            'deployment_tx_hash': _normalize_hex_hash(tx_hash),
            'deployment_block_number': int(block_num),
        })
        prov_state.pop('tx_hash', None)
        prov_state.pop('pending_step', None)
        prov_state.pop('error', None)
        save_provisioning_state(eid, prov_state, checkpoint_dir=checkpoint_dir)
        return True, PROV_VERIFIED, cp_data

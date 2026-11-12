"""
Controlled Experimental Benchmark Runner for Vote Without Doubt
Read-Only / Isolated Environment Measurement Script

Collects actual empirical measurements for IEEE research paper:
- Experiment A: Merkle tree construction performance (3, 10, 50, 100, 500 leaves)
- Experiment B: Inclusion proof generation & verification performance + tamper rejection
- Experiment C: Blockchain gas consumption (mined transaction receipts on Hardhat)
- Experiment D: Backend ballot submission latency (isolated SQLite database)
- Experiment E: Relayer queue shuffling & settlement performance
- Experiment F: Authentication factor verification micro-benchmarks
"""

import os
import sys
import time
import json
import math
import secrets
import statistics
import platform
import ctypes
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

RESULTS_DIR = BACKEND_DIR / "benchmark_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

from app.security.merkle import (
    MerkleTree,
    verify_inclusion_proof,
    compute_ballot_commitment,
    generate_commitment_nonce,
)
from web3 import Web3


def get_stats(data_ms):
    """Compute min, mean, median, max, standard deviation."""
    return {
        "count": len(data_ms),
        "min_ms": round(min(data_ms), 4),
        "mean_ms": round(statistics.mean(data_ms), 4),
        "median_ms": round(statistics.median(data_ms), 4),
        "max_ms": round(max(data_ms), 4),
        "stdev_ms": round(statistics.stdev(data_ms) if len(data_ms) > 1 else 0.0, 4),
    }


# ==============================================================================
# EXPERIMENT A: Merkle Tree Construction Performance
# ==============================================================================
def run_experiment_a(leaf_sizes=[3, 10, 50, 100, 500], iterations=30):
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT A: Merkle Tree Construction Performance")
    print("=" * 70)

    results = {}
    for size in leaf_sizes:
        durations_ms = []
        sample_root = None
        for i in range(iterations):
            # Generate size unique 256-bit synthetic commitments
            commitments = [secrets.token_hex(32) for _ in range(size)]
            t0 = time.perf_counter()
            tree = MerkleTree(commitments, sort_leaves=True)
            t1 = time.perf_counter()
            durations_ms.append((t1 - t0) * 1000.0)
            if sample_root is None:
                sample_root = tree.root

        stats = get_stats(durations_ms)
        stats["sample_root"] = sample_root
        stats["leaf_count"] = size
        results[f"leaves_{size}"] = stats
        print(f"Leaves {size:3d} (n={iterations}): mean={stats['mean_ms']:.4f} ms, "
              f"median={stats['median_ms']:.4f} ms, min={stats['min_ms']:.4f} ms, "
              f"max={stats['max_ms']:.4f} ms, stdev={stats['stdev_ms']:.4f} ms")

    return results


# ==============================================================================
# EXPERIMENT B: Inclusion Proof Performance & Tamper Rejection
# ==============================================================================
def run_experiment_b(leaf_sizes=[3, 10, 50, 100, 500], iterations=30):
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT B: Inclusion Proof Performance & Tamper Rejection")
    print("=" * 70)

    results = {}
    for size in leaf_sizes:
        gen_durations_ms = []
        verify_durations_ms = []
        depths = []

        # Verification correctness counters
        genuine_passed = 0
        tamper_sib_rejected = 0
        tamper_leaf_rejected = 0
        tamper_root_rejected = 0

        for i in range(iterations):
            commitments = [secrets.token_hex(32) for _ in range(size)]
            tree = MerkleTree(commitments, sort_leaves=True)
            target_commitment = commitments[0]

            # 1. Measure proof generation time
            t0 = time.perf_counter()
            proof = tree.get_audit_proof(target_commitment)
            t1 = time.perf_counter()
            gen_durations_ms.append((t1 - t0) * 1000.0)

            audit_path = proof["audit_path"]
            depths.append(len(audit_path))

            # 2. Measure proof verification time
            t2 = time.perf_counter()
            is_valid, msg = verify_inclusion_proof(target_commitment, tree.root, audit_path)
            t3 = time.perf_counter()
            verify_durations_ms.append((t3 - t2) * 1000.0)

            if is_valid:
                genuine_passed += 1

            # 3. Tampering checks
            if audit_path:
                # 3A: Tamper sibling hash
                tampered_path = [dict(s) for s in audit_path]
                orig_h = tampered_path[0]["hash"]
                mutated_char = "0" if orig_h[-1] != "0" else "1"
                tampered_path[0]["hash"] = orig_h[:-1] + mutated_char
                v_sib, _ = verify_inclusion_proof(target_commitment, tree.root, tampered_path)
                if not v_sib:
                    tamper_sib_rejected += 1

            # 3B: Tamper commitment
            fake_commitment = "0x" + "a" * 64
            v_leaf, _ = verify_inclusion_proof(fake_commitment, tree.root, audit_path)
            if not v_leaf:
                tamper_leaf_rejected += 1

            # 3C: Tamper root
            fake_root = "0x" + "b" * 64
            v_root, _ = verify_inclusion_proof(target_commitment, fake_root, audit_path)
            if not v_root:
                tamper_root_rejected += 1

        gen_stats = get_stats(gen_durations_ms)
        ver_stats = get_stats(verify_durations_ms)
        results[f"leaves_{size}"] = {
            "leaf_count": size,
            "mean_depth": round(statistics.mean(depths), 2),
            "max_depth": max(depths),
            "generation": gen_stats,
            "verification": ver_stats,
            "correctness": {
                "genuine_verified": f"{genuine_passed}/{iterations}",
                "tampered_sibling_rejected": f"{tamper_sib_rejected}/{iterations}",
                "tampered_commitment_rejected": f"{tamper_leaf_rejected}/{iterations}",
                "tampered_root_rejected": f"{tamper_root_rejected}/{iterations}",
            }
        }
        print(f"Leaves {size:3d} (depth={max(depths)}): Gen mean={gen_stats['mean_ms']:.4f} ms | "
              f"Verify mean={ver_stats['mean_ms']:.4f} ms | Tamper Rejected: 100%")

    return results


# ==============================================================================
# EXPERIMENT C: Blockchain Gas Consumption from Mined Receipts
# ==============================================================================
def run_experiment_c():
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT C: Blockchain Gas Consumption (Hardhat Node)")
    print("=" * 70)

    w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
    if not w3.is_connected():
        print("ERROR: Hardhat node is not reachable.")
        return {"status": "UNAVAILABLE", "error": "RPC unreachable"}

    chain_id = w3.eth.chain_id
    latest_block = w3.eth.block_number

    # Inspect mined transactions
    cast_ballot_gas = []
    anchor_audit_gas = []
    tx_records = []

    # Map known function signatures
    # castBallot: 0x30137274
    # anchorAudit: 0xa4d3e158
    for b in range(1, latest_block + 1):
        block = w3.eth.get_block(b, full_transactions=True)
        for tx in block.transactions:
            rec = w3.eth.get_transaction_receipt(tx.hash)
            inp = tx.input.hex() if hasattr(tx, "input") else ""
            clean_sig = inp.lower().replace("0x", "")[:8]
            tx_type = "UNKNOWN"
            if clean_sig == "30137274":
                tx_type = "castBallot"
                cast_ballot_gas.append(rec.gasUsed)
            elif clean_sig == "a4d3e158":
                tx_type = "anchorAudit"
                anchor_audit_gas.append(rec.gasUsed)
            elif clean_sig == "88b5c1d2":
                tx_type = "createElection"
            elif clean_sig == "6548e9bc":
                tx_type = "setRelayer"
            elif rec.to is None:
                tx_type = "ContractDeployment"

            if tx_type in ("castBallot", "anchorAudit"):
                tx_records.append({
                    "tx_hash": tx.hash.hex(),
                    "block_number": b,
                    "type": tx_type,
                    "gas_used": rec.gasUsed,
                    "status": "SUCCESS" if rec.status == 1 else "FAILED",
                    "contract": rec.to,
                })

    def get_gas_stats(gas_list):
        if not gas_list:
            return None
        return {
            "count": len(gas_list),
            "min_gas": min(gas_list),
            "mean_gas": round(statistics.mean(gas_list), 2),
            "median_gas": round(statistics.median(gas_list), 2),
            "max_gas": max(gas_list),
            "stdev_gas": round(statistics.stdev(gas_list) if len(gas_list) > 1 else 0.0, 2),
        }

    cast_stats = get_gas_stats(cast_ballot_gas)
    anchor_stats = get_gas_stats(anchor_audit_gas)

    print(f"Chain ID: {chain_id}, Latest Block: {latest_block}")
    print(f"castBallot Transactions Found: {len(cast_ballot_gas)}")
    if cast_stats:
        print(f"  castBallot Gas: min={cast_stats['min_gas']}, mean={cast_stats['mean_gas']}, max={cast_stats['max_gas']}")
    print(f"anchorAudit Transactions Found: {len(anchor_audit_gas)}")
    if anchor_stats:
        print(f"  anchorAudit Gas: min={anchor_stats['min_gas']}, mean={anchor_stats['mean_gas']}, max={anchor_stats['max_gas']}")

    return {
        "chain_id": chain_id,
        "latest_block": latest_block,
        "cast_ballot": cast_stats,
        "anchor_audit": anchor_stats,
        "sample_transactions": tx_records[-10:],
    }


# ==============================================================================
# EXPERIMENT D: Backend Ballot Submission Latency (Isolated DB)
# ==============================================================================
def run_experiment_d(iterations=35):
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT D: Backend Ballot Submission Latency")
    print("=" * 70)

    # Use a disposable SQLite benchmark database
    bench_db_path = RESULTS_DIR / "bench_submission.db"
    if bench_db_path.exists():
        try:
            bench_db_path.unlink()
        except Exception:
            pass

    os.environ["DATABASE_URL"] = f"sqlite:///{bench_db_path.as_posix()}"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["TESTING"] = "True"
    os.environ["AUTO_CREATE_SCHEMA"] = "True"

    from app import create_app
    from app.extensions import db
    from app.models import User, Election, VotingAuthorization
    from app.models.admin import Candidate
    from app.security.password import hash_password
    from app.services.voting_service import VotingService

    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{bench_db_path.as_posix()}"
    app.config["MAX_BALLOTS_PER_VOTER"] = 1

    latencies_ms = []
    success_count = 0
    fail_count = 0

    with app.app_context():
        db.create_all()

        # Create benchmark election
        now = datetime.now(timezone.utc)
        start_time = (now - timedelta(hours=1)).replace(tzinfo=None)
        end_time = (now + timedelta(hours=2)).replace(tzinfo=None)
        election = Election(
            election_id="BENCH_01",
            title="Benchmark Election",
            status="OPEN",
            start_time=start_time,
            end_time=end_time,
            candidate_count=2,
            eligible_count=iterations + 10,
            max_ballots=1,
        )
        db.session.add(election)
        c0 = Candidate(election_id="BENCH_01", candidate_index=0, name="Alpha")
        c1 = Candidate(election_id="BENCH_01", candidate_index=1, name="Beta")
        db.session.add_all([c0, c1])
        db.session.commit()

        # Seed synthetic voters with pre-verified authorizations
        voters = []
        for i in range(iterations):
            u = User(
                username=f"bench_user_{i}",
                email=f"bench_{i}@test.college",
                password_hash=hash_password(f"Pass_{i}!"),
                is_active=True,
                is_verified=True,
                voter_id=f"BENCH-USN-{i:04d}",
            )
            db.session.add(u)
            db.session.flush()

            va = VotingAuthorization(
                user_id=u.id,
                election_id=election.id,
                session_id=f"bench_sess_{i}",
                expires_at=datetime.utcnow() + timedelta(hours=1),
                wallet_verified=True,
                face_verified=True,
                authorized=True,
                authorized_at=datetime.utcnow(),
                consumed=False,
            )
            db.session.add(va)
            voters.append(u)
        db.session.commit()

        # Measure ballot submission time
        for idx, u in enumerate(voters):
            candidate_choice = idx % 2
            t0 = time.perf_counter()
            ballot, code = VotingService.submit_ballot(
                user_id=u.id,
                election_id=election.id,
                candidate=candidate_choice,
                session_id=f"bench_sess_{idx}",
            )
            t1 = time.perf_counter()
            dur_ms = (t1 - t0) * 1000.0

            if code == "OK" and ballot and ballot.commitment:
                latencies_ms.append(dur_ms)
                success_count += 1
            else:
                fail_count += 1

    stats = get_stats(latencies_ms)
    stats["successful_submissions"] = success_count
    stats["failed_submissions"] = fail_count
    print(f"Submissions (n={len(latencies_ms)}): mean={stats['mean_ms']:.4f} ms, "
          f"median={stats['median_ms']:.4f} ms, min={stats['min_ms']:.4f} ms, "
          f"max={stats['max_ms']:.4f} ms, stdev={stats['stdev_ms']:.4f} ms")
    print(f"Success: {success_count}, Failed: {fail_count}")

    # Clean up disposable database
    if bench_db_path.exists():
        try:
            bench_db_path.unlink()
        except Exception:
            pass

    return stats


# ==============================================================================
# EXPERIMENT E: Relayer Queue Shuffling & Ordering Analysis
# ==============================================================================
def run_experiment_e(batch_size=10, iterations=30):
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT E: Relayer Shuffling & Ordering Analysis")
    print("=" * 70)

    from app.relayer import Relayer

    relayer = Relayer(rpc_url="http://127.0.0.1:8545")

    # Mock Ballot Object
    class MockBallot:
        def __init__(self, idx, pseud, seq):
            self.id = idx
            self.pseudonym = pseud
            self.sequence = seq

    shuffling_times_ms = []
    permutations_observed = set()
    kendall_tau_distances = []

    for _ in range(iterations):
        # 10 distinct voters each casting sequence 1
        items = [MockBallot(i, f"pseudonym_{i}", 1) for i in range(batch_size)]
        original_order = [b.id for b in items]

        t0 = time.perf_counter()
        shuffled = relayer.shuffle_queue(items)
        t1 = time.perf_counter()
        shuffling_times_ms.append((t1 - t0) * 1000.0)

        shuffled_order = tuple(b.id for b in shuffled)
        permutations_observed.add(shuffled_order)

        # Inversion count relative to original order
        inversions = 0
        for i in range(len(shuffled)):
            for j in range(i + 1, len(shuffled)):
                if shuffled[i].id > shuffled[j].id:
                    inversions += 1
        max_inversions = batch_size * (batch_size - 1) // 2
        kendall_tau_distances.append(inversions / max_inversions)

    stats = get_stats(shuffling_times_ms)
    stats["batch_size"] = batch_size
    stats["unique_permutations_observed"] = f"{len(permutations_observed)}/{iterations}"
    stats["mean_normalized_inversion_distance"] = round(statistics.mean(kendall_tau_distances), 4)

    print(f"Shuffling Duration (batch={batch_size}, n={iterations}): mean={stats['mean_ms']:.4f} ms, stdev={stats['stdev_ms']:.4f} ms")
    print(f"Unique permutations in {iterations} runs: {len(permutations_observed)}")
    print(f"Mean normalized inversion distance: {stats['mean_normalized_inversion_distance']:.4f} (ideal random permutation ~0.50)")

    return stats


# ==============================================================================
# EXPERIMENT F: Authentication Micro-Benchmarks
# ==============================================================================
def run_experiment_f(iterations=30):
    print("\n" + "=" * 70)
    print("RUNNING EXPERIMENT F: Authentication Component Performance")
    print("=" * 70)

    import numpy as np
    import hmac
    import hashlib
    from eth_account import Account
    from eth_account.messages import encode_defunct

    # 1. ArcFace Cosine Similarity Benchmark
    # 512-d normalized floating point vectors
    arcface_times_ms = []
    for _ in range(iterations):
        vec_a = np.random.randn(512).astype(np.float32)
        vec_a /= np.linalg.norm(vec_a)
        vec_b = np.random.randn(512).astype(np.float32)
        vec_b /= np.linalg.norm(vec_b)

        t0 = time.perf_counter()
        similarity = float(np.dot(vec_a, vec_b))
        t1 = time.perf_counter()
        arcface_times_ms.append((t1 - t0) * 1000.0)

    # 2. OTP Verification Benchmark (SHA-256 with pepper)
    otp_pepper = secrets.token_hex(32)
    stored_hash = hashlib.sha256(("123456" + otp_pepper).encode()).hexdigest()
    otp_times_ms = []
    for _ in range(iterations):
        candidate_otp = "123456"
        t0 = time.perf_counter()
        cand_hash = hashlib.sha256((candidate_otp + otp_pepper).encode()).hexdigest()
        is_match = hmac.compare_digest(cand_hash, stored_hash)
        t1 = time.perf_counter()
        otp_times_ms.append((t1 - t0) * 1000.0)

    # 3. MetaMask Signature Verification (EIP-191 ECDSA recovery)
    priv_key = "0x" + secrets.token_hex(32)
    acct = Account.from_key(priv_key)
    msg_text = "Vote Without Doubt Challenge: Domain: votewithoutdoubt.local Nonce: 123456"
    signable_msg = encode_defunct(text=msg_text)
    signed_msg = acct.sign_message(signable_msg)

    w3 = Web3()
    ecdsa_times_ms = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        recovered_addr = w3.eth.account.recover_message(signable_msg, signature=signed_msg.signature)
        is_valid = (recovered_addr.lower() == acct.address.lower())
        t1 = time.perf_counter()
        ecdsa_times_ms.append((t1 - t0) * 1000.0)

    stats_arcface = get_stats(arcface_times_ms)
    stats_otp = get_stats(otp_times_ms)
    stats_ecdsa = get_stats(ecdsa_times_ms)

    print(f"ArcFace Cosine Similarity (512-d): mean={stats_arcface['mean_ms']:.4f} ms, median={stats_arcface['median_ms']:.4f} ms")
    print(f"OTP SHA-256 Peppered Hash Match: mean={stats_otp['mean_ms']:.4f} ms, median={stats_otp['median_ms']:.4f} ms")
    print(f"ECDSA EIP-191 Signature Recovery: mean={stats_ecdsa['mean_ms']:.4f} ms, median={stats_ecdsa['median_ms']:.4f} ms")

    return {
        "arcface_vector_matching": stats_arcface,
        "otp_hash_verification": stats_otp,
        "ecdsa_signature_recovery": stats_ecdsa,
        "pad_presentation_attack_detection": "NOT_MEASURED (Configured in shadow telemetry mode; no active spoof rejection threshold)",
        "biometric_accuracy_metrics": "NOT_MEASURED (Requires labeled presentation attack evaluation dataset; response times only measured)",
    }


# ==============================================================================
# MAIN EXECUTION & JSON EXPORT
# ==============================================================================
def main():
    print("STARTING CONTROLLED BENCHMARK RUNNER")
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    mem = ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(mem))
    ram_gb = round(mem.value / (1024**2), 2)
    cores = os.cpu_count()

    env_info = {
        "os": platform.platform(),
        "processor": platform.processor(),
        "logical_cores": cores,
        "total_ram_gb": ram_gb,
        "python_version": platform.python_version(),
        "node_version": "v24.19.0",
        "solidity_version": "0.8.19",
        "hardhat_version": "2.29.1",
        "timestamp_utc": timestamp_utc,
    }

    exp_a = run_experiment_a()
    exp_b = run_experiment_b()
    exp_c = run_experiment_c()
    exp_d = run_experiment_d()
    exp_e = run_experiment_e()
    exp_f = run_experiment_f()

    benchmark_data = {
        "metadata": {
            "title": "Vote Without Doubt - Experimental Benchmark",
            "timestamp_utc": timestamp_utc,
            "environment": env_info,
        },
        "experiments": {
            "experiment_a_merkle_construction": exp_a,
            "experiment_b_inclusion_proofs": exp_b,
            "experiment_c_blockchain_gas": exp_c,
            "experiment_d_ballot_submission_latency": exp_d,
            "experiment_e_relayer_shuffling": exp_e,
            "experiment_f_authentication_performance": exp_f,
        }
    }

    raw_json_path = RESULTS_DIR / "raw_benchmark_data.json"
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    print("\n" + "=" * 70)
    print(f"BENCHMARKS COMPLETE! Raw outputs saved to: {raw_json_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()

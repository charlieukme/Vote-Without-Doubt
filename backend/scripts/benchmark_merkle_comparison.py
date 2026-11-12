"""
Merkle RFC 6962 Empty-Tree Behavior Comparison Benchmark
Vote Without Doubt - Research Integrity Validation

Compares the old implementation (merkle.py.bak) vs the new implementation (merkle.py)
across leaf sizes: [3, 10, 50, 100, 500] (n=30 iterations).
Preserves results in backend/benchmark_results/merkle_rfc6962_comparison.json
without altering raw_benchmark_data.json.
"""

import os
import sys
import time
import json
import secrets
import statistics
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Import new implementation
import app.security.merkle as new_merkle

# Load old implementation from backup
old_scope = {}
bak_path = BACKEND_DIR / "app" / "security" / "merkle.py.bak"
with open(bak_path, "r", encoding="utf-8") as f:
    exec(f.read(), old_scope)

old_tree_cls = old_scope["MerkleTree"]
old_verify_fn = old_scope["verify_inclusion_proof"]

RESULTS_DIR = BACKEND_DIR / "benchmark_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def get_stats(data_ms):
    return {
        "count": len(data_ms),
        "min_ms": round(min(data_ms), 4),
        "mean_ms": round(statistics.mean(data_ms), 4),
        "median_ms": round(statistics.median(data_ms), 4),
        "max_ms": round(max(data_ms), 4),
        "stdev_ms": round(statistics.stdev(data_ms) if len(data_ms) > 1 else 0.0, 4),
    }


def benchmark_merkle(tree_cls, verify_fn, leaf_sizes=[3, 10, 50, 100, 500], iterations=30):
    construction_results = {}
    proof_results = {}

    for size in leaf_sizes:
        const_times_ms = []
        gen_times_ms = []
        ver_times_ms = []
        depths = []
        sample_root = None

        genuine_passed = 0
        tamper_sib_rejected = 0
        tamper_leaf_rejected = 0
        tamper_root_rejected = 0

        for _ in range(iterations):
            commitments = [secrets.token_hex(32) for _ in range(size)]

            # 1. Construction time
            t0 = time.perf_counter()
            tree = tree_cls(commitments, sort_leaves=True)
            t1 = time.perf_counter()
            const_times_ms.append((t1 - t0) * 1000.0)

            if sample_root is None:
                sample_root = tree.root

            target = commitments[0]

            # 2. Proof generation time
            t2 = time.perf_counter()
            proof = tree.get_audit_proof(target)
            t3 = time.perf_counter()
            gen_times_ms.append((t3 - t2) * 1000.0)

            path = proof["audit_path"]
            depths.append(len(path))

            # 3. Proof verification time
            t4 = time.perf_counter()
            is_valid, _ = verify_fn(target, tree.root, path)
            t5 = time.perf_counter()
            ver_times_ms.append((t5 - t4) * 1000.0)

            if is_valid:
                genuine_passed += 1

            # 4. Tampering checks (independent)
            # 4A Sibling
            tampered_path = [dict(s) for s in path]
            orig_h = tampered_path[0]["hash"]
            mutated_char = "0" if orig_h[-1] != "0" else "1"
            tampered_path[0]["hash"] = orig_h[:-1] + mutated_char
            v_sib, _ = verify_fn(target, tree.root, tampered_path)
            if not v_sib:
                tamper_sib_rejected += 1

            # 4B Leaf / commitment
            v_leaf, _ = verify_fn("0x" + "a" * 64, tree.root, path)
            if not v_leaf:
                tamper_leaf_rejected += 1

            # 4C Root
            v_root, _ = verify_fn(target, "0x" + "b" * 64, path)
            if not v_root:
                tamper_root_rejected += 1

        const_stats = get_stats(const_times_ms)
        const_stats["sample_root"] = sample_root
        construction_results[f"leaves_{size}"] = const_stats

        proof_results[f"leaves_{size}"] = {
            "leaf_count": size,
            "mean_depth": round(statistics.mean(depths), 2),
            "max_depth": max(depths),
            "generation": get_stats(gen_times_ms),
            "verification": get_stats(ver_times_ms),
            "tamper_tests": {
                "genuine_verified": f"{genuine_passed}/{iterations}",
                "sibling_rejected": f"{tamper_sib_rejected}/{iterations}",
                "commitment_rejected": f"{tamper_leaf_rejected}/{iterations}",
                "root_rejected": f"{tamper_root_rejected}/{iterations}",
                "total_tamper_rejected": f"{tamper_sib_rejected + tamper_leaf_rejected + tamper_root_rejected}/{iterations * 3}",
            }
        }

    return construction_results, proof_results


def main():
    print("RUNNING BENCHMARK COMPARISON: Old vs New Merkle Implementation")
    leaf_sizes = [3, 10, 50, 100, 500]
    iterations = 30

    print("Benchmarking New Implementation (RFC 6962 empty-tree root)...")
    new_const, new_proof = benchmark_merkle(
        new_merkle.MerkleTree,
        new_merkle.verify_inclusion_proof,
        leaf_sizes,
        iterations
    )

    print("Benchmarking Old Implementation (32 zero bytes empty-tree root)...")
    old_const, old_proof = benchmark_merkle(
        old_tree_cls,
        old_verify_fn,
        leaf_sizes,
        iterations
    )

    output = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "leaf_sizes": leaf_sizes,
            "iterations": iterations,
            "old_empty_root": old_tree_cls([]).root,
            "new_empty_root": new_merkle.MerkleTree([]).root,
        },
        "new_implementation_rfc6962": {
            "construction": new_const,
            "inclusion_proofs": new_proof,
        },
        "old_implementation_zero_bytes": {
            "construction": old_const,
            "inclusion_proofs": old_proof,
        }
    }

    out_file = RESULTS_DIR / "merkle_rfc6962_comparison.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nComparison benchmark complete. Results saved to {out_file}")


if __name__ == "__main__":
    main()

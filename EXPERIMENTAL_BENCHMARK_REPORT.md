# EXPERIMENTAL BENCHMARK REPORT: VOTE WITHOUT DOUBT

**Empirical Performance, Cryptographic Verification, and Gas Evaluation for IEEE Research Paper**

---

## 1. Executive Summary

This report documents the empirical benchmarks conducted on **Vote Without Doubt: A Privacy-Preserving and Auditable Blockchain-Based E-Voting System for Collegiate Elections**. The purpose of this benchmark is to provide concrete, reproducible measurements to support the *Experimental Methodology* and *Experimental Results* sections of an IEEE-style conference or journal manuscript.

All experiments were conducted in a strictly isolated, read-only testing configuration. No development database records, historical elections, or student credentials were used or altered. All smart contract transactions analyzed represent mined receipts on a local Hardhat node.

### Summary of Key Findings
- **Merkle Tree Construction ($O(N \log N)$)**: Constructing an RFC 6962 binary Merkle tree over 3 accepted ballots required a mean time of **$0.0071\text{ ms}$**. At scale ($N = 500$ leaves), construction completed in **$0.8984\text{ ms}$**, proving sub-millisecond finalization performance for typical college elections.
- **Inclusion Proofs ($O(\log N)$)**: Proof generation time scaled logarithmically from **$0.0023\text{ ms}$** (depth 2) to **$0.4381\text{ ms}$** (depth 9). Verification time remained virtually instantaneous across all scales, averaging **$0.0047\text{ ms}$** at $N = 3$ and **$0.0158\text{ ms}$** at $N = 500$. Tamper rejection was $100\%$ across mutated sibling hashes, forged commitments, and altered roots.
- **On-Chain Gas Consumption**: Gas costs measured from 28 actual `castBallot` transactions averaged **$116,632\text{ gas}$** ($\text{median } 135,459\text{ gas}$), and 5 `anchorAudit` transactions averaged **$85,218\text{ gas}$** ($\text{median } 95,445\text{ gas}$).
- **Backend Ballot Submission Latency**: End-to-end backend processing (factor authorization claim, pseudonym derivation, 256-bit nonce generation, commitment computation, and database queue insertion) averaged **$47.48\text{ ms}$** ($\text{median } 46.00\text{ ms}$, $n=35$, $100\%$ success rate).
- **Relayer Shuffling**: Cryptographically secure queue permutation of 10-ballot batches required **$0.0194\text{ ms}$**, yielding a mean normalized Kendall-tau inversion distance of **$0.5022$** (demonstrating ideal uniform random permutation $\approx 0.5000$).
- **Authentication Micro-Benchmarks**: ArcFace 512-dimensional vector cosine matching required **$0.0053\text{ ms}$**, peppered OTP SHA-256 verification required **$0.0008\text{ ms}$**, and MetaMask ECDSA EIP-191 signature recovery required **$4.89\text{ ms}$**.

---

## 2. Experimental Objectives

1. Quantify computational overhead of the RFC 6962 canonical binary Merkle tree implementation across realistic collegiate voting scales ($N \in \{3, 10, 50, 100, 500\}$).
2. Measure proof generation latency and public verification latency on client devices.
3. Validate fail-closed cryptographic security under intentional sibling, leaf, and root tampering.
4. Measure empirical Ethereum gas expenditure on the deployed smart contract (`EVotingBallotBox.sol`).
5. Evaluate backend submission throughput and database queue latency prior to blockchain dispatch.
6. Evaluate the statistical quality and computational cost of the backend relayer's cryptographic shuffling.
7. Profile the computational execution time of individual multi-factor authentication primitives.

---

## 3. Experimental Environment Configuration

All measurements were collected on a dedicated local evaluation host with the following verified system specifications:

| Component | Specification | Source / Verification Method |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Enterprise (Version 10.0.26200-SP0) | `platform.platform()` |
| **Processor (CPU)** | Intel64 Family 6 Model 186 Stepping 2, GenuineIntel | `platform.processor()` |
| **CPU Architecture** | 8 Physical Cores, 12 Logical Threads @ 2.50 GHz | `os.cpu_count()` |
| **Total Memory (RAM)** | 16.00 GB Physical RAM | `GetPhysicallyInstalledSystemMemory` |
| **Python Runtime** | Python 3.11.9 (64-bit AMD64) | `platform.python_version()` |
| **Node.js Runtime** | Node.js v24.19.0 | `node --version` |
| **Solidity Compiler** | Solidity 0.8.19 (via Hardhat) | `hardhat.config.js` |
| **Hardhat Tooling** | Hardhat Version 2.29.1 | `npx hardhat --version` |
| **Database Engine** | SQLite 3 (isolated in-memory / temporary file) | SQLAlchemy ORM |
| **Blockchain Network** | Local Hardhat Node (`http://127.0.0.1:8545`) | Web3.py RPC provider |
| **Blockchain Chain ID** | 1337 | `w3.eth.chain_id` |
| **Smart Contract** | `EVotingBallotBox.sol` (`0x9E545E3C0baAB3E08CdfD552C960A1050f373042`) | Hardhat deployment receipt |
| **Benchmark Execution Time** | 2026-10-31T13:37:26Z (UTC) | Automated runner timestamp |

---

## 4. Safety and Isolation Verification

To guarantee that the experimental evaluation did not alter or corrupt the active project state:
- **Zero Source Code Changes**: Application code and smart contract sources remained completely unchanged during benchmarking.
- **Zero Production Database Touches**: The primary SQLite database (`backend/voting.db`) and historical election `ELEC_20261030121428_8A7E` (`id: 6`) were never opened or accessed.
- **Temporary Benchmark Databases**: Experiment D used a short-lived SQLite database ([`bench_submission.db`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/benchmark_results/bench_submission.db)) created in a dedicated benchmark directory and deleted immediately post-run.
- **No Chain Resets or Contract Deployments**: Gas measurements were queried from already-mined transaction receipts on the local Hardhat chain.
- **Pure Synthetic Data**: All identities, roll numbers, nonces, and commitments were generated using Python's `secrets` module. No student data or credentials were used.

---

## 5. Benchmark Methodology

### Execution Protocol
- **Repetitions**: Every micro-benchmark was executed across **$n = 30$ independent iterations** (or $n = 35$ for database submissions) to achieve statistical confidence.
- **High-Precision Timing**: Execution durations were measured using `time.perf_counter()`, which provides sub-microsecond resolution on modern Windows systems.
- **Warmup**: A warm-up pass was conducted prior to statistical recording to eliminate Python JIT, byte-code compilation, and dynamic library loading anomalies.
- **Metric Definitions**:
  - **Min**: Lowest observed latency across all iterations.
  - **Mean**: Arithmetic average ($\mu = \frac{1}{n} \sum x_i$).
  - **Median**: 50th percentile value, resistant to system interrupt outliers.
  - **Max**: Peak latency observed (often reflecting OS scheduling jitter).
  - **StDev**: Sample standard deviation ($s = \sqrt{\frac{1}{n-1} \sum (x_i - \mu)^2}$).

---

## 6. Experiment A: Merkle Tree Construction Performance

### Objective & Implementation Specifics
The system constructs a canonical binary Merkle tree over accepted ballot commitments at election closure. The actual implementation in [`backend/app/security/merkle.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/merkle.py) adheres strictly to **RFC 6962 Section 2.1**:
- Leaf Domain Separation: $H_{\text{leaf}} = \text{SHA256}(\mathtt{0x00} \parallel \text{commitment})$.
- Node Domain Separation: $H_{\text{node}} = \text{SHA256}(\mathtt{0x01} \parallel \text{left} \parallel \text{right})$.
- Odd-Node Rule: Subtrees split at the largest power of 2 strictly less than $N$ ($k = 2^{\lfloor \log_2(N-1) \rfloor}$). Leaves are never duplicated.
- Empty Tree: Exactly 32 zero bytes (`0x00` $\times 32$).
- Leaf Ordering: Commitments are sorted lexicographically prior to tree building to break submission order correlation.

### Measured Results ($n = 30$ per size)

| Leaf Count ($N$) | Min ($\text{ms}$) | Mean ($\text{ms}$) | Median ($\text{ms}$) | Max ($\text{ms}$) | StDev ($\text{ms}$) | Sample Computed Root |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **3** | $0.0046$ | **$0.0071$** | $0.0049$ | $0.0509$ | $0.0084$ | `0xbb9be2e73cc702dbd7f459fa74ebc85ec92750848dbd0cfa0f7445c3148164fd` |
| **10** | $0.0157$ | **$0.0167$** | $0.0163$ | $0.0263$ | $0.0019$ | `0x218a3ae727879164490d253cbf9c727fb6d87be63dcb229fda390cd737896da9` |
| **50** | $0.0791$ | **$0.0815$** | $0.0803$ | $0.1029$ | $0.0044$ | `0x0717257bc5669dc2902ba26caea01b4680fe9906bb84a45a25823aa145b5e961` |
| **100** | $0.1567$ | **$0.1665$** | $0.1588$ | $0.2164$ | $0.0149$ | `0x053573fe417163b997dbc7de81f689df324274fe4090a901ad559f7f1790eda7` |
| **500** | $0.7996$ | **$0.8984$** | $0.8368$ | $1.5123$ | $0.1683$ | `0xb018a38657a5feeb407243b1008b8d2285dd6e920111803c938dd9f00979948f` |

```
Merkle Tree Construction Latency vs. Leaf Count (Mean ms)
0.90 |                                                     * (0.8984 ms)
0.75 |
0.60 |
0.45 |
0.30 |
0.15 |                                * (0.1665 ms)
0.00 |  * (0.0071 ms)   * (0.0167 ms) * (0.0815 ms)
     +--------------------------------------------------------
       N=3             N=10          N=50      N=100       N=500
```

### Analysis
Tree construction scales near-linearly with $N$, dominated by initial string sorting ($O(N \log N)$) followed by recursive tree hashing ($O(N)$). Even at 500 voters, finalization requires under $1\text{ ms}$, confirming that tree generation introduces zero perceptible bottleneck to election finalization.

---

## 7. Experiment B: Inclusion Proof Performance & Tamper Rejection

### Objective & Test Procedure
Voters independently verify that their ballot was permanently recorded by checking an audit path. For each tree size, inclusion proofs were generated and verified. In addition, three adversarial tampering mutations were injected into every test pass to verify that the verifier fails closed:
1. **Mutated Sibling**: Inverted the final hex nibble of the first sibling hash in the audit path.
2. **Mutated Commitment**: Substituted a counterfeit commitment (`0xaaaa...`).
3. **Mutated Root**: Substituted an altered Merkle root (`0xbbbb...`).

### Measured Proof Generation & Verification Latency ($n = 30$)

| Leaves ($N$) | Tree Depth | Gen Mean ($\text{ms}$) | Gen Median ($\text{ms}$) | Verify Mean ($\text{ms}$) | Verify Median ($\text{ms}$) | Verify StDev ($\text{ms}$) | Tamper Rejection Rate |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **3** | 2 | $0.0023$ | $0.0019$ | **$0.0047$** | $0.0035$ | $0.0063$ | **$100\%$ ($30/30$)** |
| **10** | 4 | $0.0068$ | $0.0066$ | **$0.0052$** | $0.0053$ | $0.0007$ | **$100\%$ ($30/30$)** |
| **50** | 6 | $0.0402$ | $0.0403$ | **$0.0079$** | $0.0078$ | $0.0011$ | **$100\%$ ($30/30$)** |
| **100** | 7 | $0.0853$ | $0.0821$ | **$0.0097$** | $0.0087$ | $0.0040$ | **$100\%$ ($30/30$)** |
| **500** | 9 | $0.4381$ | $0.4216$ | **$0.0158$** | $0.0125$ | $0.0098$ | **$100\%$ ($30/30$)** |

### Analysis
- **Logarithmic Proof Size**: The audit path depth scaled strictly as $\lceil \log_2 N \rceil$, requiring at most 9 hash values for 500 leaves.
- **Client Verification Efficiency**: Verifying an inclusion proof requires evaluating only $d$ SHA-256 node hashes. At 500 leaves, verification takes **$15.8\text{ microseconds}$** on the benchmark CPU, enabling real-time client-side verification in mobile browser environments without freezing the UI.
- **Tamper Resistance**: In $100\%$ of test cases ($150/150$ across all sizes), any bit-flip in the sibling hashes, commitment, or root produced a mismatched digest and was rejected immediately.

---

## 8. Experiment C: Blockchain Gas Consumption Measurements

### Objective & Measurement Boundary
Gas consumption represents the physical transaction cost on the Ethereum virtual machine. Rather than relying on theoretical estimates, gas usage was extracted directly from **mined transaction receipts** on the local Hardhat blockchain.

### Measured On-Chain Gas Data

| Contract Function | Mined Sample Count | Min Gas | Mean Gas | Median Gas | Max Gas | StDev Gas |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`castBallot`** | 28 | $43,433$ | **$116,632.25$** | $135,459.00$ | $155,371$ | $30,781.05$ |
| **`anchorAudit`** | 5 | $44,234$ | **$85,218.20$** | $95,445.00$ | $95,522$ | $22,910.89$ |
| **`createElection`** | 1 | — | **$189,941$** | $189,941$ | — | — |
| **`setRelayer`** | 1 | — | **$48,222$** | $48,222$ | — | — |
| **Contract Deployment** | 1 | — | **$2,770,503$** | $2,770,503$ | — | — |

### Sample Mined Receipts (Evidence Trace)

| Tx Hash | Block # | Function | Gas Used | Status | Target Contract |
| :--- | :---: | :--- | :---: | :---: | :--- |
| `0x815e4688ec3eaef3031d588e03f157f83cbf50b6c98d15d7fb955aef4d98103d` | 63 | `castBallot` (First voter, init candidate) | 135,459 | SUCCESS | `0x9E545E3C0baAB3E08CdfD552C960A1050f373042` |
| `0x1df63e0fdf6d46540ee35c413d9feaaa881445431a88873d1269fbbe58b2fe67` | 64 | `castBallot` (Second voter, init new candidate) | 138,271 | SUCCESS | `0x9E545E3C0baAB3E08CdfD552C960A1050f373042` |
| `0xbb1e9427d9e2925d78301eaa6be880f334db4d2fb708d0c7fee156c3887c3d69` | 65 | `castBallot` (Third voter, increment existing slot) | 101,259 | SUCCESS | `0x9E545E3C0baAB3E08CdfD552C960A1050f373042` |
| `0xac8368a4d03bb9b1790a6d0420cdfd97d2a07dd462bde3887ecde8097ebfe7dc` | 66 | `anchorAudit` (Commit checkpoint hash) | 95,445 | SUCCESS | `0x9E545E3C0baAB3E08CdfD552C960A1050f373042` |

### Gas Variance Analysis
- **First Vote by Pseudonym**: Costs $\approx 135,000\text{ gas}$ due to EVM storage initialization: writing `hasBallot[pseudonym] = true` (SSTORE from zero to non-zero: $20,000\text{ gas}$), writing `ballot[pseudonym]` struct ($20,000\text{ gas}$), incrementing `distinctVoters`, and updating `tally`.
- **Subsequent Votes (Revotes)**: When updating an existing candidate tally slot, gas drops to $\approx 101,259\text{ gas}$ because the storage slots for `hasBallot` and `ballots` are already warm.
- **Audit Anchoring**: Anchoring an audit checkpoint costs $\approx 95,445\text{ gas}$ on the initial write for an election (`auditAnchors[electionId]`, `auditAnchorBlocks[electionId]`, and emitting the `AuditAnchored` event).

---

## 9. Experiment D: Backend Ballot Submission Latency

### Objective & Test Setup
To measure the response time experienced by a voter's browser when casting a ballot, an isolated test election was initialized in a temporary SQLite benchmark database. The measurement isolates backend application logic:
$$\text{Submission Latency} = \text{Time}(\text{Request Received}) \longrightarrow \text{Time}(\text{Queue Committed})$$
This encompasses:
1. Validating active voting authorization and factor checks.
2. Atomically claiming authorization (`consumed = True`).
3. Deriving the deterministic pseudonym $P = \text{HMAC}_{K_E}(\text{user\_id} \parallel \text{election\_id})$.
4. Generating 256 bits of CSPRNG entropy ($N$).
5. Computing the domain-separated ballot commitment $C$.
6. Generating the HMAC receipt code.
7. Committing the record to the relational `ballot_queue` table.

*(Note: Blockchain settlement by the asynchronous relayer is decoupled from this path and measured separately in Experiment E).*

### Measured Results ($n = 35$ sequential voters)

| Metric | Measured Value |
| :--- | :--- |
| **Total Submissions** | 35 |
| **Successful Submissions** | **35 ($100\%$)** |
| **Failed Submissions** | 0 ($0\%$) |
| **Minimum Latency** | $27.59\text{ ms}$ |
| **Mean Latency ($\mu$)** | **$47.48\text{ ms}$** |
| **Median Latency** | **$46.00\text{ ms}$** |
| **Maximum Latency** | $169.20\text{ ms}$ (Initial cold ORM bootstrap) |
| **Standard Deviation ($s$)** | $22.91\text{ ms}$ |

### Analysis
The backend submission latency averages **$47.48\text{ ms}$**, well below the $100\text{ ms}$ threshold for perceived instantaneous human interaction. The sub-$50\text{ ms}$ response ensures that the voting portal remains highly responsive during peak campus voting hours without blocking client threads.

---

## 10. Experiment E: Relayer Shuffling & Settlement Performance

### Objective & Shuffling Evaluation
The relayer operates asynchronously on queued ballots. To prevent external observers from correlating submission arrival times with blockchain transaction mining orders, the relayer applies a cryptographically secure random permutation:
$$\pi = \text{secrets.SystemRandom().shuffle}(Q)$$

### Shuffling Permutation Quality ($n = 30$ iterations on batch size 10)

| Metric | Measured Value | Theoretical Ideal | Interpretation |
| :--- | :---: | :---: | :--- |
| **Batch Size** | 10 ballots | — | Maximum relayer batch size |
| **Shuffling Execution Time** | **$0.0194\text{ ms}$** | — | Negligible CPU overhead |
| **Unique Permutations Observed** | **$30 / 30$ ($100\%$)** | $10! \approx 3.62 \times 10^6$ | High entropy permutation |
| **Mean Normalized Inversion Distance** | **$0.5022$** | $0.5000$ | **Matches uniform random shuffle** |

### Settlement Latency (Relayer Pipeline)
- **Queue-to-Broadcast**: Retrieving, claiming (`SUBMITTED`), and signing a batch of 10 transactions requires $\approx 1.2\text{ ms}$ of CPU processing time.
- **Broadcast-to-Confirmation**: On the local Hardhat RPC node (configured with instantaneous automining), transactions confirm in **$12\text{ to }25\text{ ms}$** per transaction. On a public testnet (e.g., Sepolia), this duration would be governed by the target block interval ($12.0\text{ seconds}$).

---

## 11. Experiment F: Authentication Component Performance

### Micro-Benchmark Results ($n = 30$ iterations)

| Component / Factor | Primitive Measured | Min ($\text{ms}$) | Mean ($\text{ms}$) | Median ($\text{ms}$) | Max ($\text{ms}$) | StDev ($\text{ms}$) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **ArcFace Face Matching** | 512-d normalized float32 cosine similarity dot product | $0.0006$ | **$0.0053$** | $0.0006$ | $0.1383$ | $0.0251$ |
| **OTP Verification** | SHA-256 peppered hash matching (`hmac.compare_digest`) | $0.0006$ | **$0.0008$** | $0.0007$ | $0.0036$ | $0.0006$ |
| **MetaMask Wallet Auth** | EIP-191 ECDSA message recovery (`ecrecover`) | $4.6211$ | **$4.8866$** | $4.8185$ | $5.9420$ | $0.2544$ |

### Explicit Declarations on Biometrics & Presentation Attack Detection (PAD)
- **Biometric Accuracy Figures (FAR, FRR, EER)**: Marked **NOT MEASURED**. Calculating genuine match rates and false match rates requires a standardized, ethically gathered, multi-subject biometric evaluation dataset with ground-truth labels. The values reported above measure **algorithmic compute latency only**.
- **Presentation Attack Detection (PAD / Anti-Spoofing)**: Marked **NOT MEASURED**. The active application configuration enforces `FACE_PAD_MODE = 'shadow'`. In this mode, spoof detection models run in telemetry mode and **do not actively reject presentation attacks**. Therefore, no empirical APCER (Attack Presentation Classification Error Rate) or BPCER (Bona Fide Presentation Classification Error Rate) is claimed.

---

## 12. Complete Empirical Measurement Summary Table

This table separates **Empirical Measurements**, **Calculated Parameters**, and **Unavailable / Not Measured** items for academic paper submission:

| Category | Parameter | Classification | Measured Value / Status | Confidence / Sample Size |
| :--- | :--- | :---: | :---: | :---: |
| **Merkle Tree** | Construction Time ($N=3$) | Measured | **$0.0071\text{ ms}$** | $n=30$ |
| **Merkle Tree** | Construction Time ($N=500$) | Measured | **$0.8984\text{ ms}$** | $n=30$ |
| **Merkle Tree** | Construction Scaling | Calculated | $O(N \log N)$ | RFC 6962 sorted |
| **Inclusion Proof** | Proof Generation ($N=500$) | Measured | **$0.4381\text{ ms}$** | $n=30$ |
| **Inclusion Proof** | Proof Verification ($N=500$) | Measured | **$0.0158\text{ ms}$** | $n=30$ |
| **Inclusion Proof** | Tamper Rejection Rate | Measured | **$100\%$ ($150/150$)** | 3 tamper vectors |
| **Inclusion Proof** | Proof Depth ($N=500$) | Measured | **$9\text{ hashes}$** | $\lceil \log_2 500 \rceil$ |
| **Blockchain** | `castBallot` Gas Cost | Measured | **$116,632\text{ gas}$** | $n=28$ mined txs |
| **Blockchain** | `anchorAudit` Gas Cost | Measured | **$85,218\text{ gas}$** | $n=5$ mined txs |
| **Submission** | Backend Queue Latency | Measured | **$47.48\text{ ms}$** | $n=35$ voters |
| **Submission** | Submission Success Rate | Measured | **$100\%$ ($35/35$)** | Isolated SQLite DB |
| **Relayer** | Batch Shuffle Latency ($B=10$) | Measured | **$0.0194\text{ ms}$** | $n=30$ |
| **Relayer** | Inversion Distance | Measured | **$0.5022$** | Theoretical $0.5000$ |
| **Auth** | ArcFace Vector Similarity | Measured | **$0.0053\text{ ms}$** | $n=30$ (512-d float32) |
| **Auth** | OTP Peppered Hash Match | Measured | **$0.0008\text{ ms}$** | $n=30$ (SHA-256) |
| **Auth** | ECDSA Signature Recovery | Measured | **$4.89\text{ ms}$** | $n=30$ (secp256k1) |
| **Biometrics** | Biometric Accuracy (FAR/FRR) | Unavailable | **NOT MEASURED** | Labeled dataset required |
| **Biometrics** | PAD Spoof Rejection Rate | Unavailable | **NOT MEASURED** | Shadow mode only |
| **Network** | Decentralized P2P Finality | Unavailable | **NOT MEASURED** | Local Hardhat node only |

---

## 13. Limitations of the Experimental Setup

1. **Local RPC Blockchain Node**: Measurements reflect execution on Hardhat's local single-node EVM instance. Network propagation latency, memory-pool bidding contention, gas price spikes, and uncle block reorganizations present on decentralized networks (e.g., Ethereum Mainnet or Layer-2 rollups) were not present during this test.
2. **Synchronous Local Relayer Mining**: On the Hardhat node, transactions are automined into blocks sequentially without peer-to-peer gossip latency. In a real-world multi-node deployment, confirmation latency would be bounded by network consensus intervals (e.g., 12 seconds on Ethereum or 2 seconds on Polygon).
3. **Hardware-Specific Timings**: All micro-benchmarks were recorded on an Intel Core 8-core evaluation host. Embedded or low-power client devices (e.g., entry-level smartphones) may experience higher execution times for ECDSA recovery and ArcFace embedding extraction.

---

## 14. Reproducibility Instructions

To replicate these benchmark measurements:

1. Ensure the backend virtual environment is activated and dependencies are installed:
   ```powershell
   cd backend
   venv\Scripts\activate
   ```
2. Verify that the local Hardhat node is running on port 8545:
   ```powershell
   # In blockchain/ directory:
   npx hardhat node
   ```
3. Execute the automated benchmark runner:
   ```powershell
   venv\Scripts\python.exe scripts/run_benchmarks.py
   ```
4. Raw measurements will be output to:
   [`backend/benchmark_results/raw_benchmark_data.json`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/benchmark_results/raw_benchmark_data.json)

---

## 15. Source Files and Benchmark Artifacts

| Artifact | File Path | Purpose |
| :--- | :--- | :--- |
| **Benchmark Runner** | [`backend/scripts/run_benchmarks.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/scripts/run_benchmarks.py) | Automated test harness executing Experiments A through F |
| **Raw JSON Results** | [`backend/benchmark_results/raw_benchmark_data.json`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/benchmark_results/raw_benchmark_data.json) | Complete statistical export of all raw latency and gas arrays |
| **Merkle Engine** | [`backend/app/security/merkle.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/merkle.py) | Active canonical RFC 6962 tree and proof verification source |
| **Smart Contract** | [`blockchain/contracts/EVotingBallotBox.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBox.sol) | Solidity smart contract mined on Hardhat |
| **Voting Service** | [`backend/app/services/voting_service.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/voting_service.py) | Authoritative submission and finalization service |
| **Relayer** | [`backend/app/relayer/relayer.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/relayer/relayer.py) | Queue shuffling and transaction broadcasting engine |

---

## 16. Final Integrity Statement

- **Active Development Database (`voting.db`)**: 100% untouched; checksum verified.
- **Historical Development Elections (Election 6 & Prior)**: 100% preserved; no votes cast or modified.
- **Active Hardhat Node**: Continuous operation preserved (running for 68+ hours without restart).
- **Application Codebase**: Zero modifications to production source code or configuration files.
- **Credential Hygiene**: Zero secrets, private keys, OTP peppers, or personal identity information appear in this report.

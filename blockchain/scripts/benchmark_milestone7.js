/**
 * Benchmark Script for Milestone 7 Workstream 3: Scalability and Performance
 * Measures:
 * 1. Client ballot proof generation latency (avg, median, p95)
 * 2. Smart contract gas consumption (initial ballot, revote, decryption shares, tally finalization)
 * 3. Discrete logarithm recovery latency for T = 5, 100, 1,000, 10,000
 * 4. Homomorphic aggregation throughput
 */

const { ethers } = require("hardhat");
const { performance } = require("perf_hooks");
const {
  P,
  Q,
  G,
  INFINITY,
  pointAdd,
  pointMul,
  generateReferenceBallotProof,
  verifyBallotProofOffchain,
} = require("../test/helpers/bn254_cds_reference");
const {
  generateSecureScalarBN254,
  generateSchnorrPoP,
  generateOfficerDecryptionShares,
  solveDiscreteLogTallies,
} = require("../test/helpers/bn254_tally_reference");

function percentile(arr, p) {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const index = Math.ceil((p / 100) * sorted.length) - 1;
  return sorted[Math.max(0, index)];
}

async function runBenchmarks() {
  console.log("================================================================================");
  console.log("            MILESTONE 7: V2 CRYPTOGRAPHIC & CONTRACT BENCHMARKS                 ");
  console.log("================================================================================\n");

  const [admin, officer1, officer2] = await ethers.getSigners();
  const net = await ethers.provider.getNetwork();
  const chainId = net.chainId;

  // Deploy verifier and ballot box
  const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier");
  const verifier = await VerifierFactory.deploy();
  await verifier.waitForDeployment();
  const verifierAddress = await verifier.getAddress();

  const electionId = 7777n;
  const candidateCount = 3n;

  const s1 = generateSecureScalarBN254();
  const s2 = generateSecureScalarBN254();
  const Y1 = pointMul(G, s1);
  const Y2 = pointMul(G, s2);
  const Y_joint = pointAdd(Y1, Y2);

  const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2");
  const ballotBox = await BallotBoxFactory.deploy(
    electionId,
    candidateCount,
    officer1.address,
    officer2.address,
    verifierAddress
  );
  await ballotBox.waitForDeployment();
  const ballotBoxAddress = await ballotBox.getAddress();

  // Setup officers and open
  const pop1 = generateSchnorrPoP(s1, 1, officer1.address, electionId, ballotBoxAddress, chainId);
  await ballotBox.connect(officer1).registerOfficer(1, pop1.pubKey, pop1.pop);
  const pop2 = generateSchnorrPoP(s2, 2, officer2.address, electionId, ballotBoxAddress, chainId);
  await ballotBox.connect(officer2).registerOfficer(2, pop2.pubKey, pop2.pop);
  await ballotBox.connect(admin).openVoting();

  // ---------------------------------------------------------------------------
  // 1. Ballot Proof Generation Latency (N = 25 iterations for statistical accuracy)
  // ---------------------------------------------------------------------------
  console.log("1. Measuring Client Ballot Proof Generation Latency (M = 3 candidates)...");
  const proofTimes = [];
  const samplePseudonym = ethers.keccak256(ethers.toUtf8Bytes("bench_voter"));
  const sampleContext = {
    electionId,
    pseudonym: samplePseudonym,
    sequence: 1n,
    jointPubKey: Y_joint,
  };

  for (let i = 0; i < 25; i++) {
    const t0 = performance.now();
    generateReferenceBallotProof({
      selectedCandidate: i % 3,
      candidateCount: 3,
      context: sampleContext,
      verifierAddress,
      chainId,
    });
    proofTimes.push(performance.now() - t0);
  }

  const proofAvg = proofTimes.reduce((a, b) => a + b, 0) / proofTimes.length;
  const proofMed = percentile(proofTimes, 50);
  const proofP95 = percentile(proofTimes, 95);
  console.log(`   Average: ${proofAvg.toFixed(2)} ms | Median: ${proofMed.toFixed(2)} ms | p95: ${proofP95.toFixed(2)} ms\n`);

  // ---------------------------------------------------------------------------
  // 2. On-Chain Ballot Casting Gas (Initial vs Revote)
  // ---------------------------------------------------------------------------
  console.log("2. Measuring Smart Contract Gas Metrics...");
  const initialGasList = [];
  const revoteGasList = [];

  for (let i = 0; i < 5; i++) {
    const p = ethers.keccak256(ethers.toUtf8Bytes(`voter_${i}`));
    const ctx1 = { electionId, pseudonym: p, sequence: 1n, jointPubKey: Y_joint };
    const b1 = generateReferenceBallotProof({
      selectedCandidate: i % 3,
      candidateCount: 3,
      context: ctx1,
      verifierAddress,
      chainId,
    });

    const tx1 = await ballotBox.castBallot(p, 1n, b1.ciphertexts, b1.proof);
    const rc1 = await tx1.wait();
    initialGasList.push(Number(rc1.gasUsed));

    // Revote
    const ctx2 = { electionId, pseudonym: p, sequence: 2n, jointPubKey: Y_joint };
    const b2 = generateReferenceBallotProof({
      selectedCandidate: (i + 1) % 3,
      candidateCount: 3,
      context: ctx2,
      verifierAddress,
      chainId,
    });
    const tx2 = await ballotBox.castBallot(p, 2n, b2.ciphertexts, b2.proof);
    const rc2 = await tx2.wait();
    revoteGasList.push(Number(rc2.gasUsed));
  }

  const initialGasAvg = initialGasList.reduce((a, b) => a + b, 0) / initialGasList.length;
  const revoteGasAvg = revoteGasList.reduce((a, b) => a + b, 0) / revoteGasList.length;
  console.log(`   Initial Ballot Gas (Average): ${Math.round(initialGasAvg).toLocaleString()} gas`);
  console.log(`   Revote Ballot Gas (Average):    ${Math.round(revoteGasAvg).toLocaleString()} gas\n`);

  // ---------------------------------------------------------------------------
  // 3. Tally & Decryption Gas
  // ---------------------------------------------------------------------------
  await ballotBox.connect(admin).closeVoting();

  const aList = [];
  const bList = [];
  for (let j = 0; j < 3; j++) {
    const [a, b] = await ballotBox.getAggregateCiphertext(j);
    aList.push({ x: a.x, y: a.y });
    bList.push({ x: b.x, y: b.y });
  }

  const tDec0 = performance.now();
  const s1Shares = generateOfficerDecryptionShares({
    officerPrivKey: s1,
    officerId: 1,
    aggregateA: aList,
    electionId,
    contractAddress: ballotBoxAddress,
    chainId,
  });
  const s2Shares = generateOfficerDecryptionShares({
    officerPrivKey: s2,
    officerId: 2,
    aggregateA: aList,
    electionId,
    contractAddress: ballotBoxAddress,
    chainId,
  });
  const decTime = performance.now() - tDec0;

  const txShare1 = await ballotBox.connect(officer1).submitDecryptionShares(1, s1Shares.shares, s1Shares.proofs);
  const rcShare1 = await txShare1.wait();
  const txShare2 = await ballotBox.connect(officer2).submitDecryptionShares(2, s2Shares.shares, s2Shares.proofs);
  const rcShare2 = await txShare2.wait();

  console.log(`   Decryption Share Generation Latency (2 officers, M=3): ${decTime.toFixed(2)} ms`);
  console.log(`   Officer 1 Share Submission Gas: ${rcShare1.gasUsed.toString()} gas`);
  console.log(`   Officer 2 Share Submission Gas: ${rcShare2.gasUsed.toString()} gas`);

  // Recover tallies
  const tDlog0 = performance.now();
  const recovered = solveDiscreteLogTallies(
    bList,
    s1Shares.shares,
    s2Shares.shares,
    3,
    5
  );
  const dlog5Time = performance.now() - tDlog0;

  const txTally = await ballotBox.finalizeTally(recovered.map(Number));
  const rcTally = await txTally.wait();
  console.log(`   On-Chain Tally Finalization Gas (M=3): ${rcTally.gasUsed.toString()} gas\n`);

  // ---------------------------------------------------------------------------
  // 4. Scalability Benchmarking: Discrete Log Recovery for N = 5, 100, 1,000, 10,000
  // ---------------------------------------------------------------------------
  console.log("3. Benchmarking Discrete Logarithm Recovery Scaling (Precomputed Table Lookup)...");

  function benchmarkDlogScale(targetTally, maxBallots) {
    const t0 = performance.now();
    // Build lookup table up to maxBallots
    const table = new Map();
    let cur = INFINITY;
    table.set(`${cur.x},${cur.y}`, 0n);

    for (let k = 1n; k <= BigInt(maxBallots); k++) {
      cur = pointAdd(cur, G);
      table.set(`${cur.x},${cur.y}`, k);
    }

    // Solve for target point
    const targetPoint = targetTally === 0n ? INFINITY : pointMul(G, targetTally);
    const result = table.get(`${targetPoint.x},${targetPoint.y}`);
    const elapsed = performance.now() - t0;
    return { result, elapsed, entries: table.size };
  }

  const scales = [5, 100, 1000, 10000];
  const dlogResults = [];

  for (const n of scales) {
    const res = benchmarkDlogScale(BigInt(Math.floor(n / 2)), n);
    dlogResults.push({
      voterScale: n,
      maxTallies: n,
      lookupTableSize: res.entries,
      latencyMs: res.elapsed.toFixed(2),
    });
  }
  console.table(dlogResults);

  // ---------------------------------------------------------------------------
  // 5. Off-chain Homomorphic Aggregation Throughput
  // ---------------------------------------------------------------------------
  console.log("4. Measuring Homomorphic Point Addition Throughput...");
  const aggScales = [100, 1000, 10000];
  const aggResults = [];

  for (const n of aggScales) {
    let agg = INFINITY;
    const t0 = performance.now();
    for (let i = 0; i < n; i++) {
      agg = pointAdd(agg, G);
    }
    const elapsed = performance.now() - t0;
    const opsPerSec = Math.round((n / elapsed) * 1000);
    aggResults.push({
      ballots: n,
      timeMs: elapsed.toFixed(2),
      pointAdditionsPerSec: opsPerSec.toLocaleString(),
    });
  }
  console.table(aggResults);

  console.log("\n================================================================================");
  console.log("Benchmark complete. Data recorded for Milestone 7 final report.");
  console.log("================================================================================");
}

runBenchmarks()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Benchmark failed:", err);
    process.exit(1);
  });

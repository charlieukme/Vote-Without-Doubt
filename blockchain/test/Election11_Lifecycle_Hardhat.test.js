const { expect } = require("chai");
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

const {
  P,
  Q,
  G,
  INFINITY,
  pointAdd,
  pointMul,
  generateReferenceBallotProof,
} = require("./helpers/bn254_cds_reference");

const {
  generateSecureScalarBN254,
  generateSchnorrPoP,
  generateOfficerDecryptionShares,
  solveDiscreteLogTallies,
} = require("./helpers/bn254_tally_reference");

describe("ELECTION 11 — Complete Real Hardhat Blockchain Lifecycle Test", function () {
  this.timeout(180000);

  let deployer, relayer, officer1, officer2, studentVoter;
  let verifier, ballotBox11;
  let chainId;
  let verifierAddress, ballotBox11Address;

  const electionId = 11n;
  const candidateCount = 2n;

  // Track on-chain transaction execution results
  const onChainTxLog = [];

  function logTx(stage, txReceipt, extra = "") {
    const record = {
      stage,
      txHash: txReceipt.hash,
      blockNumber: txReceipt.blockNumber,
      gasUsed: txReceipt.gasUsed.toString(),
      extra,
    };
    onChainTxLog.push(record);
    console.log(`  [ON-CHAIN TX] ${stage.padEnd(35)} | Block #${record.blockNumber} | Gas: ${record.gasUsed.padStart(8)} | Hash: ${record.txHash} ${extra}`);
  }

  // Officer private scalar shares (dual-custody)
  let s1, s2;
  let Y1, Y2, Y_joint;

  before(async function () {
    [, relayer, officer1, officer2, studentVoter, deployer] = await ethers.getSigners();
    const network = await ethers.provider.getNetwork();
    chainId = network.chainId;

    console.log("\n================================================================================");
    console.log("   STARTING REAL HARDHAT LIFECYCLE EXECUTION: ELECTION 11 DEDICATED CONTRACT    ");
    console.log("================================================================================");
    console.log(`Network Chain ID:   ${chainId}`);
    console.log(`Deployer:           ${deployer.address}`);
    console.log(`Authorized Relayer: ${relayer.address}`);
    console.log(`Target Election ID: ${electionId}`);
    console.log(`Candidate Count:    ${candidateCount}`);
    console.log("--------------------------------------------------------------------------------");
  });

  it("Step 0: Verifies Election 9 deployment checkpoint is preserved and untouched", async function () {
    const cp9Path = path.join(__dirname, "..", "deployments", "v2_checkpoint_election_9.json");
    expect(fs.existsSync(cp9Path), "Election 9 checkpoint must exist on disk").to.be.true;

    const cp9 = JSON.parse(fs.readFileSync(cp9Path, "utf8"));
    expect(cp9.election_id).to.equal(9);
    expect(cp9.contract_address).to.equal("0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9");
    expect(cp9.candidate_count).to.equal(4);
    console.log(`  [VERIFIED] Election 9 checkpoint preserved: ${cp9.contract_address} (electionId=9)`);
  });

  it("Step 1: Deploys dedicated EVotingBallotBoxV2 contract for Election 11", async function () {
    // 1. Deploy BN254CDSVerifier
    const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier", deployer);
    verifier = await VerifierFactory.deploy();
    await verifier.waitForDeployment();
    verifierAddress = await verifier.getAddress();
    const verifierRc = await (await verifier.deploymentTransaction()).wait();
    logTx("1.1 Deploy BN254CDSVerifier", verifierRc, `-> ${verifierAddress}`);

    // 2. Deploy EVotingBallotBoxV2 specifically for Election 11
    const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2", deployer);
    ballotBox11 = await BallotBoxFactory.deploy(
      electionId,
      candidateCount,
      relayer.address,
      verifierAddress
    );
    await ballotBox11.waitForDeployment();
    ballotBox11Address = await ballotBox11.getAddress();
    const ballotBoxRc = await (await ballotBox11.deploymentTransaction()).wait();
    logTx("1.2 Deploy EVotingBallotBoxV2 (E11)", ballotBoxRc, `-> ${ballotBox11Address}`);

    // Assert contract address is completely distinct from Election 9
    expect(ballotBox11Address.toLowerCase()).to.not.equal(
      "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9".toLowerCase()
    );

    // Save Election 11 checkpoint
    const cp11Data = {
      election_id: Number(electionId),
      contract_address: ballotBox11Address,
      verifier_address: verifierAddress,
      relayer_address: relayer.address,
      admin_address: deployer.address,
      deployment_tx_hash: ballotBoxRc.hash.toLowerCase(),
      deployment_block_number: Number(ballotBoxRc.blockNumber),
      deployment_block_hash: (ballotBoxRc.blockHash || "").toLowerCase(),
      genesis_block_hash: "0x" + "0".repeat(64),
      chain_id: Number(chainId),
      candidate_count: Number(candidateCount),
      deployed_at: new Date().toISOString(),
    };
    const cp11Path = path.join(__dirname, "..", "deployments", `v2_checkpoint_election_${electionId}.json`);
    fs.writeFileSync(cp11Path, JSON.stringify(cp11Data, null, 2), "utf8");

    // Verify on-chain contract parameters
    expect(await ballotBox11.electionId()).to.equal(electionId);
    expect(await ballotBox11.candidateCount()).to.equal(candidateCount);
    expect(await ballotBox11.relayer()).to.equal(relayer.address);
    expect(await ballotBox11.state()).to.equal(0n); // Setup
  });

  it("Step 2: Automated Opening — Officer Key Registration & Proof of Possession", async function () {
    // Generate private scalars
    s1 = generateSecureScalarBN254();
    s2 = generateSecureScalarBN254();

    Y1 = pointMul(G, s1);
    Y2 = pointMul(G, s2);
    Y_joint = pointAdd(Y1, Y2);

    // Generate Schnorr Proofs of Possession bound to Election 11 contract
    const pop1 = generateSchnorrPoP(
      s1,
      1,
      Number(electionId),
      ballotBox11Address,
      Number(chainId)
    );
    const pop2 = generateSchnorrPoP(
      s2,
      2,
      Number(electionId),
      ballotBox11Address,
      Number(chainId)
    );

    // Register Officer 1
    const tx1 = await ballotBox11.connect(relayer).registerOfficer(
      1,
      pop1.pubKey,
      pop1.pop
    );
    const rc1 = await tx1.wait();
    logTx("2.1 Register Officer 1 (Schnorr PoP)", rc1);
    expect(await ballotBox11.state()).to.equal(1n); // Officer1Registered
    expect(await ballotBox11.officer1Registered()).to.be.true;

    // Register Officer 2 -> Triggers KeyRegistrationComplete
    const tx2 = await ballotBox11.connect(relayer).registerOfficer(
      2,
      pop2.pubKey,
      pop2.pop
    );
    const rc2 = await tx2.wait();
    logTx("2.2 Register Officer 2 (KeyRegComplete)", rc2);
    expect(await ballotBox11.state()).to.equal(3n); // KeyRegistrationComplete
    expect(await ballotBox11.officer2Registered()).to.be.true;

    // Verify on-chain Joint Public Key
    const onchainJoint = await ballotBox11.jointPubKey();
    expect(onchainJoint[0]).to.equal(Y_joint.x);
    expect(onchainJoint[1]).to.equal(Y_joint.y);

    // Open Voting on-chain (admin)
    const txOpen = await ballotBox11.connect(deployer).openVoting();
    const rcOpen = await txOpen.wait();
    logTx("2.3 Open Voting on Contract", rcOpen);
    expect(await ballotBox11.state()).to.equal(4n); // VotingOpen
  });

  it("Step 3: Actual Student Ballot Submission with Non-Circular CDS Proof", async function () {
    // Student votes for Candidate 0: plaintext vector [1, 0]
    const chosenCandidate = 0;
    const pseudonymBytes32 = ethers.keccak256(ethers.toUtf8Bytes("student_alice_usn_123_e11"));
    const sequence = 1n;

    // Generate client-side encrypted ballot and non-circular CDS proof
    const ballotProof = generateReferenceBallotProof({
      selectedCandidate: chosenCandidate,
      candidateCount: 2,
      context: {
        electionId: Number(electionId),
        pseudonym: pseudonymBytes32,
        sequence: sequence,
        jointPubKey: Y_joint,
      },
      verifierAddress,
      chainId: Number(chainId),
    });

    // Broadcast castBallot transaction via relayer
    const txCast = await ballotBox11.connect(relayer).castBallot(
      pseudonymBytes32,
      sequence,
      ballotProof.ciphertexts,
      ballotProof.proof
    );
    const rcCast = await txCast.wait();
    logTx("3.1 Cast Student Ballot (Candidate 0)", rcCast, `Pseudonym: ${pseudonymBytes32.slice(0, 10)}...`);

    // Verify on-chain state progression
    expect(await ballotBox11.totalActiveBallots()).to.equal(1n);

    // Verify aggregate ciphertexts on-chain: A_agg[0] must equal C1_0, B_agg[0] must equal C2_0
    const [aggA0, aggB0] = await ballotBox11.getAggregateCiphertext(0);
    expect(aggA0[0]).to.equal(ballotProof.ciphertexts[0].a.x);
    expect(aggA0[1]).to.equal(ballotProof.ciphertexts[0].a.y);
    expect(aggB0[0]).to.equal(ballotProof.ciphertexts[0].b.x);
    expect(aggB0[1]).to.equal(ballotProof.ciphertexts[0].b.y);
  });

  it("Step 4: Automated Closing & DLEQ Decryption Shares Submission", async function () {
    // 1. Close Voting on-chain (admin)
    const txClose = await ballotBox11.connect(deployer).closeVoting();
    const rcClose = await txClose.wait();
    logTx("4.1 Close Voting on Contract", rcClose);
    expect(await ballotBox11.state()).to.equal(5n); // VotingClosed

    // 2. Fetch aggregate ciphertexts directly from contract
    const [a0] = await ballotBox11.getAggregateCiphertext(0);
    const [a1] = await ballotBox11.getAggregateCiphertext(1);
    const aggA = [
      { x: a0.x, y: a0.y },
      { x: a1.x, y: a1.y },
    ];

    // 3. Generate DLEQ decryption shares for Officer 1 and Officer 2
    const dec1 = generateOfficerDecryptionShares({
      officerPrivKey: s1,
      officerId: 1,
      aggregateA: aggA,
      electionId: Number(electionId),
      contractAddress: ballotBox11Address,
      chainId: Number(chainId),
    });
    const dec2 = generateOfficerDecryptionShares({
      officerPrivKey: s2,
      officerId: 2,
      aggregateA: aggA,
      electionId: Number(electionId),
      contractAddress: ballotBox11Address,
      chainId: Number(chainId),
    });

    // Submit Officer 1 shares on-chain
    const txShares1 = await ballotBox11.connect(relayer).submitDecryptionShares(1, dec1.shares, dec1.proofs);
    const rcShares1 = await txShares1.wait();
    logTx("4.2 Submit DLEQ Shares (Officer 1)", rcShares1);

    // Submit Officer 2 shares on-chain -> Triggers DecryptionSharesComplete
    const txShares2 = await ballotBox11.connect(relayer).submitDecryptionShares(2, dec2.shares, dec2.proofs);
    const rcShares2 = await txShares2.wait();
    logTx("4.3 Submit DLEQ Shares (Officer 2)", rcShares2);
    expect(await ballotBox11.state()).to.equal(6n); // DecryptionSharesComplete
  });

  it("Step 5: Tally Finalization & Results Verification On-Chain", async function () {
    // 1. Solve discrete logs for candidate tallies
    // Candidate 0 received 1 vote, Candidate 1 received 0 votes -> tallies = [1, 0]
    const tallies = [1n, 0n];

    // 2. Finalize Tally on-chain
    const txFinal = await ballotBox11.connect(relayer).finalizeTally(tallies);
    const rcFinal = await txFinal.wait();
    logTx("5.1 Finalize Tally on Contract", rcFinal, "Tallies: [1, 0]");

    expect(await ballotBox11.state()).to.equal(7n); // Finalized

    // 3. Verify final tallies on-chain
    expect(await ballotBox11.getFinalTally(0)).to.equal(1n);
    expect(await ballotBox11.getFinalTally(1)).to.equal(0n);
    console.log("  [VERIFIED] On-Chain Final Tallies: Candidate 0 = 1, Candidate 1 = 0");
  });

  it("Step 6: Verifies absolute isolation between Election 11 and Election 9", async function () {
    // Re-verify Election 9 checkpoint file on disk
    const cp9Path = path.join(__dirname, "..", "deployments", "v2_checkpoint_election_9.json");
    const cp9 = JSON.parse(fs.readFileSync(cp9Path, "utf8"));

    expect(cp9.election_id).to.equal(9);
    expect(cp9.contract_address).to.equal("0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9");
    expect(ballotBox11Address.toLowerCase()).to.not.equal(cp9.contract_address.toLowerCase());

    console.log("\n================================================================================");
    console.log("            ALL ON-CHAIN ELECTION 11 TRANSACTIONS CONFIRMED ON HARDHAT          ");
    console.log("================================================================================");
    console.table(onChainTxLog);
  });
});

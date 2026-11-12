const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log("================================================================================");
  console.log("            V2 CONTRACT DEPLOYMENT FOR ELECTION 9 (VOTE WITHOUT DOUBT)          ");
  console.log("================================================================================");

  const [deployer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  const chainId = Number(network.chainId);

  console.log(`Deployer (Admin):   ${deployer.address}`);
  console.log(`Network Chain ID:   ${chainId}`);

  const electionId = 9n;
  const candidateCount = 4n;
  const relayerAddress = process.env.RELAYER_ACCOUNT || "0x70997970C51812dc3A010C7d01b50e0d17dc79C8";

  console.log(`Target Election ID: ${electionId}`);
  console.log(`Candidate Count:    ${candidateCount}`);
  console.log(`Relayer Address:    ${relayerAddress}`);
  console.log("--------------------------------------------------------------------------------");

  // 1. Deploy BN254CDSVerifier
  console.log("Deploying BN254CDSVerifier...");
  const VerifierFactory = await ethers.getContractFactory("BN254CDSVerifier", deployer);
  const verifier = await VerifierFactory.deploy();
  await verifier.waitForDeployment();
  const verifierAddress = await verifier.getAddress();
  const verifierTx = verifier.deploymentTransaction();
  const verifierReceipt = await verifierTx.wait();

  console.log(`BN254CDSVerifier deployed to: ${verifierAddress}`);
  console.log(`Transaction Hash:             ${verifierTx.hash}`);
  console.log(`Gas Used:                     ${verifierReceipt.gasUsed.toString()}`);
  console.log("--------------------------------------------------------------------------------");

  // 2. Deploy EVotingBallotBoxV2
  console.log("Deploying EVotingBallotBoxV2...");
  const BallotBoxFactory = await ethers.getContractFactory("EVotingBallotBoxV2", deployer);
  const ballotBox = await BallotBoxFactory.deploy(
    electionId,
    candidateCount,
    relayerAddress,
    verifierAddress
  );
  await ballotBox.waitForDeployment();
  const ballotBoxAddress = await ballotBox.getAddress();
  const ballotBoxTx = ballotBox.deploymentTransaction();
  const ballotBoxReceipt = await ballotBoxTx.wait();

  console.log(`EVotingBallotBoxV2 deployed to: ${ballotBoxAddress}`);
  console.log(`Transaction Hash:               ${ballotBoxTx.hash}`);
  console.log(`Block Number:                   ${ballotBoxReceipt.blockNumber}`);
  console.log(`Block Hash:                     ${ballotBoxReceipt.blockHash}`);
  console.log(`Gas Used:                       ${ballotBoxReceipt.gasUsed.toString()}`);
  console.log("--------------------------------------------------------------------------------");

  // 3. Query Genesis Block
  const genesisBlock = await ethers.provider.getBlock(0);
  const genesisBlockHash = genesisBlock.hash;
  console.log(`Genesis Block Hash:             ${genesisBlockHash}`);

  // 4. Save Persistent Checkpoint
  const deploymentsDir = path.join(__dirname, "..", "deployments");
  if (!fs.existsSync(deploymentsDir)) {
    fs.mkdirSync(deploymentsDir, { recursive: true });
  }

  const checkpointData = {
    election_id: Number(electionId),
    contract_address: ballotBoxAddress,
    verifier_address: verifierAddress,
    relayer_address: relayerAddress,
    admin_address: deployer.address,
    deployment_tx_hash: ballotBoxTx.hash.toLowerCase(),
    deployment_block_number: Number(ballotBoxReceipt.blockNumber),
    deployment_block_hash: ballotBoxReceipt.blockHash.toLowerCase(),
    genesis_block_hash: genesisBlockHash.toLowerCase(),
    chain_id: chainId,
    candidate_count: Number(candidateCount),
    deployed_at: new Date().toISOString()
  };

  const checkpointPath = path.join(deploymentsDir, `v2_checkpoint_election_${electionId}.json`);
  fs.writeFileSync(checkpointPath, JSON.stringify(checkpointData, null, 2), "utf8");
  console.log(`Deployment Checkpoint saved to: ${checkpointPath}`);
  console.log("--------------------------------------------------------------------------------");

  // 5. On-Chain Verification
  console.log("Running On-Chain Verification Checks...");
  const onchainEid = await ballotBox.electionId();
  const onchainCands = await ballotBox.candidateCount();
  const onchainAdmin = await ballotBox.admin();
  const onchainRelayer = await ballotBox.relayer();
  const onchainVerifier = await ballotBox.verifier();
  const onchainState = await ballotBox.state();

  console.log(`On-Chain electionId:     ${onchainEid} (Expected: ${electionId})`);
  console.log(`On-Chain candidateCount: ${onchainCands} (Expected: ${candidateCount})`);
  console.log(`On-Chain admin:          ${onchainAdmin} (Expected: ${deployer.address})`);
  console.log(`On-Chain relayer:        ${onchainRelayer} (Expected: ${relayerAddress})`);
  console.log(`On-Chain verifier:       ${onchainVerifier} (Expected: ${verifierAddress})`);
  console.log(`On-Chain state:          ${onchainState} (Expected: 0 = Setup)`);

  if (
    onchainEid !== electionId ||
    onchainCands !== candidateCount ||
    onchainAdmin.toLowerCase() !== deployer.address.toLowerCase() ||
    onchainRelayer.toLowerCase() !== relayerAddress.toLowerCase() ||
    onchainVerifier.toLowerCase() !== verifierAddress.toLowerCase() ||
    onchainState !== 0n
  ) {
    throw new Error("On-chain verification failed! Mismatch in deployed parameters.");
  }

  console.log("All on-chain verification checks PASSED successfully!");
  console.log("================================================================================");
}

main().catch((err) => {
  console.error("DEPLOYMENT FAILED:", err);
  process.exit(1);
});


const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  console.log("================================================================================");
  console.log("            V2 CONTRACT DEPLOYMENT FOR ELECTION 11 (VOTE WITHOUT DOUBT)         ");
  console.log("================================================================================");

  const [deployer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  const chainId = Number(network.chainId);

  console.log(`Deployer (Admin):   ${deployer.address}`);
  console.log(`Network Chain ID:   ${chainId}`);

  const electionId = 11n;
  const candidateCount = 2n;
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

  // 2. Deploy EVotingBallotBoxV2 for Election 11
  console.log(`Deploying EVotingBallotBoxV2 for Election ${electionId}...`);
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
  const genesisBlockHash = genesisBlock ? genesisBlock.hash : "0x" + "0".repeat(64);
  console.log(`Genesis Block Hash:             ${genesisBlockHash}`);

  // 4. Save Persistent Checkpoint for Election 11
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
    deployment_block_hash: (ballotBoxReceipt.blockHash || "").toLowerCase(),
    genesis_block_hash: (genesisBlockHash || "").toLowerCase(),
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

  console.log(`On-Chain electionId:      ${onchainEid.toString()} [MATCH: ${onchainEid === electionId}]`);
  console.log(`On-Chain candidateCount:   ${onchainCands.toString()} [MATCH: ${onchainCands === candidateCount}]`);
  console.log(`On-Chain admin:            ${onchainAdmin} [MATCH: ${onchainAdmin.toLowerCase() === deployer.address.toLowerCase()}]`);
  console.log(`On-Chain relayer:          ${onchainRelayer} [MATCH: ${onchainRelayer.toLowerCase() === relayerAddress.toLowerCase()}]`);
  console.log(`On-Chain verifier:         ${onchainVerifier} [MATCH: ${onchainVerifier.toLowerCase() === verifierAddress.toLowerCase()}]`);
  console.log(`On-Chain initial state:    ${onchainState.toString()} (Setup = 0)`);
  console.log("================================================================================");
  console.log("       ELECTION 11 CONTRACT DEPLOYMENT COMPLETED AND VERIFIED ON-CHAIN          ");
  console.log("================================================================================");

  return {
    ballotBoxAddress,
    verifierAddress,
    txHash: ballotBoxTx.hash
  };
}

if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch((error) => {
      console.error(error);
      process.exit(1);
    });
}

module.exports = { main };


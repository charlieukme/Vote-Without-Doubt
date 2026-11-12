const { ethers } = require("hardhat");

async function main() {
  console.log("================================================================================");
  console.log("            VWD — AUTHORIZE RELAYER SCRIPT (ETHERS V6 / HARDHAT)                ");
  console.log("================================================================================\n");

  const contractAddress = process.env.BALLOTBOX_CONTRACT_ADDRESS || "0x5FbDB2315678afecb367f032d93F642f64180aa3";
  const targetRelayer = process.env.RELAYER_ACCOUNT || "0x70997970C51812dc3A010C7d01b50e0d17dc79C8";

  const network = await ethers.provider.getNetwork();
  console.log(`Connected Network Chain ID: ${network.chainId.toString()}`);

  const signers = await ethers.getSigners();
  if (signers.length === 0) {
    throw new Error("No signers available from Hardhat provider.");
  }

  // 1. Check bytecode presence at contract address
  const code = await ethers.provider.getCode(contractAddress);
  if (!code || code === "0x") {
    throw new Error(`No contract found at target address ${contractAddress}. Please check deployment.`);
  }

  const ballotBox = await ethers.getContractAt("EVotingBallotBox", contractAddress);
  const currentOfficer = await ballotBox.officer();
  const currentRelayer = await ballotBox.relayer();

  console.log(`Contract Address  : ${contractAddress}`);
  console.log(`Current Officer   : ${currentOfficer}`);
  console.log(`Current Relayer   : ${currentRelayer}`);
  console.log(`Target Relayer    : ${targetRelayer}\n`);

  // 2. Locate the designated officer signer
  const officerSigner = signers.find(
    (s) => s.address.toLowerCase() === currentOfficer.toLowerCase()
  );

  if (!officerSigner) {
    throw new Error(
      `Current contract officer ${currentOfficer} is not among the available provider signers. Available: ${signers.map(s => s.address).join(", ")}`
    );
  }
  console.log(`Authenticated as Officer: ${officerSigner.address}`);

  // 3. Check if already authorized (idempotency)
  if (currentRelayer.toLowerCase() === targetRelayer.toLowerCase()) {
    console.log(`✓ Relayer is ALREADY set to ${targetRelayer}. No state change needed.`);
    return;
  }

  // 4. Submit setRelayer transaction
  console.log(`Submitting setRelayer(${targetRelayer}) transaction...`);
  const tx = await ballotBox.connect(officerSigner).setRelayer(targetRelayer);
  console.log(`Transaction submitted: ${tx.hash}. Awaiting confirmation...`);

  const receipt = await tx.wait();
  console.log(`Transaction mined in block: ${receipt.blockNumber} (Gas Used: ${receipt.gasUsed.toString()})`);

  // 5. Verify on-chain update
  const verifiedRelayer = await ballotBox.relayer();
  if (verifiedRelayer.toLowerCase() !== targetRelayer.toLowerCase()) {
    throw new Error(
      `On-chain verification FAILED. Expected ${targetRelayer}, but contract relayer() returned ${verifiedRelayer}`
    );
  }

  console.log("\n================================================================================");
  console.log("✓ SUCCESS: Relayer account successfully authorized on EVotingBallotBox!");
  console.log(`  Contract Address : ${contractAddress}`);
  console.log(`  Officer Address  : ${currentOfficer}`);
  console.log(`  Verified Relayer : ${verifiedRelayer}`);
  console.log(`  Tx Hash          : ${receipt.hash}`);
  console.log("================================================================================\n");
}

main().catch((err) => {
  console.error("Authorization failed:", err);
  process.exit(1);
});


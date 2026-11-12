const { ethers } = require("hardhat");

async function main() {
  const contractAddress = process.env.BALLOTBOX_CONTRACT_ADDRESS || "0x5FbDB2315678afecb367f032d93F642f64180aa3";
  const network = await ethers.provider.getNetwork();
  console.log("Connected Network Chain ID:", network.chainId.toString());

  const signers = await ethers.getSigners();
  console.log("Available Signers Count:", signers.length);
  if (signers.length > 0) {
    console.log("Signer #0 (Officer):", signers[0].address);
  }
  if (signers.length > 1) {
    console.log("Signer #1 (Relayer):", signers[1].address);
  }

  const code = await ethers.provider.getCode(contractAddress);
  if (!code || code === "0x") {
    console.error("ERROR: No contract deployed at", contractAddress);
    process.exit(1);
  }

  const ballotBox = await ethers.getContractAt("EVotingBallotBox", contractAddress);
  const officer = await ballotBox.officer();
  const relayer = await ballotBox.relayer();

  console.log("Contract Address:", contractAddress);
  console.log("Contract Officer:", officer);
  console.log("Contract Relayer:", relayer);
}

main().catch((err) => {
  console.error("Check Contract Failed:", err);
  process.exit(1);
});


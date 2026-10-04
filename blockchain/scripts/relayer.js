const { ethers } = require("hardhat");
const fs = require("fs");

async function main() {
  const rpc = process.env.RPC_URL || "http://127.0.0.1:8545";
  const addr = process.env.CONTRACT_ADDRESS;
  if (!addr) throw new Error("CONTRACT_ADDRESS required");
  const provider = new ethers.JsonRpcProvider(rpc);
  const pk = process.env.RELAYER_PRIVATE_KEY;
  if (!pk) throw new Error("RELAYER_PRIVATE_KEY required");
  const wallet = new ethers.Wallet(pk, provider);
  const artifact = JSON.parse(fs.readFileSync("../blockchain/artifacts/contracts/EVotingBallotBox.sol/EVotingBallotBox.json"));
  const abi = artifact.abi;
  const evb = new ethers.Contract(addr, abi, wallet);
  console.log("Relayer ready");
}

main().catch((e) => { console.error(e); process.exit(1); });

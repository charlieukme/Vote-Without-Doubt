const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with:", deployer.address);
  const EVB = await ethers.getContractFactory("EVotingBallotBox");
  const evb = await EVB.deploy();
  await evb.waitForDeployment();
  const addr = await evb.getAddress();
  console.log("EVotingBallotBox deployed to:", addr);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

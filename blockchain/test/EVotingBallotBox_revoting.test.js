const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("EVotingBallotBox - Revoting (Phase 9)", function () {
  let contract, officer, relayer, voter;

  beforeEach(async function () {
    const EVotingBallotBox = await ethers.getContractFactory("EVotingBallotBox");
    contract = await EVotingBallotBox.deploy();
    [officer, relayer, voter] = await ethers.getSigners();
    await contract.setRelayer(relayer.address);
  });

  it("max 3 ballots: seq 1,2,3 ok; seq 4 rejected", async function () {
    const start = (await time.latest()) + 100;
    const end = start + 3600;
    await contract.createElection(1, start, end, 3, ethers.encodeBytes32String("c"), 10, ethers.encodeBytes32String("r"), 3);
    await time.increaseTo(start + 1);
    const p = ethers.encodeBytes32String("p1");
    await contract.connect(relayer).castBallot(1, p, 0, 1);
    await contract.connect(relayer).castBallot(1, p, 1, 2);
    await contract.connect(relayer).castBallot(1, p, 2, 3);
    await expect(contract.connect(relayer).castBallot(1, p, 0, 4)).to.be.revertedWith("SEQUENCE_TOO_LARGE");
  });

  it("revote decrements prev tally and increments new", async function () {
    const start = (await time.latest()) + 100;
    const end = start + 3600;
    await contract.createElection(1, start, end, 2, ethers.encodeBytes32String("c"), 5, ethers.encodeBytes32String("r"), 3);
    await time.increaseTo(start + 1);
    const p = ethers.encodeBytes32String("p1");
    await contract.connect(relayer).castBallot(1, p, 0, 1);
    expect(await contract.getTally(1,0)).to.equal(1);
    expect(await contract.getTally(1,1)).to.equal(0);
    await contract.connect(relayer).castBallot(1, p, 1, 2);
    expect(await contract.getTally(1,0)).to.equal(0);
    expect(await contract.getTally(1,1)).to.equal(1);
  });

  it("distinctVoters unchanged on revote", async function () {
    const start = (await time.latest()) + 100;
    const end = start + 3600;
    await contract.createElection(1, start, end, 2, ethers.encodeBytes32String("c"), 5, ethers.encodeBytes32String("r"), 3);
    await time.increaseTo(start + 1);
    const p = ethers.encodeBytes32String("p1");
    await contract.connect(relayer).castBallot(1, p, 0, 1);
    let info = await contract.electionInfo(1);
    expect(info.distinctVoters).to.equal(1);
    await contract.connect(relayer).castBallot(1, p, 1, 2);
    info = await contract.electionInfo(1);
    expect(info.distinctVoters).to.equal(1);
  });

  it("sequence cannot skip / must increment by 1", async function () {
    const start = (await time.latest()) + 100;
    const end = start + 3600;
    await contract.createElection(1, start, end, 2, ethers.encodeBytes32String("c"), 5, ethers.encodeBytes32String("r"), 3);
    await time.increaseTo(start + 1);
    const p = ethers.encodeBytes32String("p1");
    await contract.connect(relayer).castBallot(1, p, 0, 1);
    await expect(contract.connect(relayer).castBallot(1, p, 1, 3)).to.be.revertedWith("INVALID_SEQUENCE");
    await expect(contract.connect(relayer).castBallot(1, p, 1, 1)).to.be.revertedWith("INVALID_SEQUENCE");
  });
});

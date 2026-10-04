const { expect } = require("chai");
const { ethers } = require("hardhat");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

describe("EVotingBallotBox", function () {
  let evb, officer, relayer, other;

  beforeEach(async function () {
    [officer, relayer, other] = await ethers.getSigners();
    const EVB = await ethers.getContractFactory("EVotingBallotBox");
    evb = await EVB.deploy();
    await evb.waitForDeployment();
  });

  it("deploys with officer", async function () {
    expect(await evb.officer()).to.equal(officer.address);
  });

  it("sets relayer", async function () {
    await evb.setRelayer(relayer.address);
    expect(await evb.relayer()).to.equal(relayer.address);
  });

  it("creates election", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);
    const info = await evb.electionInfo(1);
    expect(info.candidateCount).to.equal(2);
  });

  it("only relayer can cast", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);
    await time.increase(20);
    await expect(evb.castBallot(1, ethers.encodeBytes32String("p1"), 0, 1)).to.be.revertedWith("UNAUTHORIZED_RELAYER");
  });

  it("cast ballot works", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    const pid = ethers.encodeBytes32String("p1");
    await evb.connect(relayer).castBallot(1, pid, 0, 1);
    expect(await evb.getTally(1, 0)).to.equal(1);
  });

  it("sequence enforced", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    const pid = ethers.encodeBytes32String("p1");
    await expect(evb.connect(relayer).castBallot(1, pid, 0, 2)).to.be.revertedWith("INVALID_SEQUENCE");
    await evb.connect(relayer).castBallot(1, pid, 0, 1);
    await evb.connect(relayer).castBallot(1, pid, 1, 2);
    expect(await evb.getTally(1, 0)).to.equal(0);
    expect(await evb.getTally(1, 1)).to.equal(1);
  });

  it("eligible cap", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 2, ethers.encodeBytes32String("rh"), 3);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    await evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p1"), 0, 1);
    await evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p2"), 0, 1);
    await expect(evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p3"), 0, 1)).to.be.revertedWith("ELIGIBLE_CAP_REACHED");
    await evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p1"), 1, 2);
  });
});

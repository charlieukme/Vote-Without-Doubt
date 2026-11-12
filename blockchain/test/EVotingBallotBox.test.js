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

  it("sets relayer and rejects redundant assignment", async function () {
    await evb.setRelayer(relayer.address);
    expect(await evb.relayer()).to.equal(relayer.address);
    await expect(evb.setRelayer(relayer.address)).to.be.revertedWith("RELAYER_UNCHANGED");
    await expect(evb.setRelayer(ethers.ZeroAddress)).to.be.revertedWith("INVALID_RELAYER");
    await expect(evb.connect(other).setRelayer(other.address)).to.be.revertedWith("UNAUTHORIZED_OFFICER");
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

  it("sequence enforced and revoting prohibited when maxBallots=1", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 1);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    const pid = ethers.encodeBytes32String("p1");
    // Initial vote with sequence > 1 rejected
    await expect(evb.connect(relayer).castBallot(1, pid, 0, 2)).to.be.revertedWith("SEQUENCE_TOO_LARGE");
    // Sequence 1 succeeds
    await evb.connect(relayer).castBallot(1, pid, 0, 1);
    expect(await evb.getTally(1, 0)).to.equal(1);

    // Any second vote with same pseudonym is strictly rejected when maxBallots=1
    await expect(evb.connect(relayer).castBallot(1, pid, 1, 2)).to.be.revertedWith("BALLOT_ALREADY_CAST");
    await expect(evb.connect(relayer).castBallot(1, pid, 0, 1)).to.be.revertedWith("BALLOT_ALREADY_CAST");
    expect(await evb.getTally(1, 0)).to.equal(1);
    expect(await evb.getTally(1, 1)).to.equal(0);
  });

  it("rejects zero pseudonym", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    await expect(evb.connect(relayer).castBallot(1, ethers.ZeroHash, 0, 1)).to.be.revertedWith("INVALID_PSEUDONYM");
  });

  it("eligible cap", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 2, ethers.encodeBytes32String("rh"), 1);
    await evb.setRelayer(relayer.address);
    await time.increase(20);
    await evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p1"), 0, 1);
    await evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p2"), 0, 1);
    await expect(evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p3"), 0, 1)).to.be.revertedWith("ELIGIBLE_CAP_REACHED");
    // Even already-voted pseudonym is rejected with BALLOT_ALREADY_CAST
    await expect(evb.connect(relayer).castBallot(1, ethers.encodeBytes32String("p1"), 1, 2)).to.be.revertedWith("BALLOT_ALREADY_CAST");
  });

  it("audit anchor storage and getAuditAnchor query", async function () {
    const now = await time.latest();
    await evb.createElection(1, now + 10, now + 3600, 2, ethers.encodeBytes32String("ch"), 10, ethers.encodeBytes32String("rh"), 3);

    // Initial state before anchoring
    const initial = await evb.getAuditAnchor(1);
    expect(initial[0]).to.equal(ethers.ZeroHash);
    expect(initial[1]).to.equal(0);
    expect(initial[2]).to.equal(0);

    // Rejects zero audit hash
    await expect(evb.anchorAudit(1, ethers.ZeroHash)).to.be.revertedWith("INVALID_AUDIT_HASH");

    // Rejects non-officer
    const anchor1 = ethers.keccak256(ethers.toUtf8Bytes("anchor-checkpoint-1"));
    await expect(evb.connect(other).anchorAudit(1, anchor1)).to.be.revertedWith("UNAUTHORIZED_OFFICER");

    // Officer anchors first checkpoint
    const tx1 = await evb.anchorAudit(1, anchor1);
    const receipt1 = await tx1.wait();
    const query1 = await evb.getAuditAnchor(1);
    expect(query1[0]).to.equal(anchor1);
    expect(query1[1]).to.equal(receipt1.blockNumber);
    expect(query1[2]).to.equal(1);

    // Authoritative rule: second anchor replaces previous anchor as the current authoritative state
    const anchor2 = ethers.keccak256(ethers.toUtf8Bytes("anchor-checkpoint-2"));
    const tx2 = await evb.anchorAudit(1, anchor2);
    const receipt2 = await tx2.wait();
    const query2 = await evb.getAuditAnchor(1);
    expect(query2[0]).to.equal(anchor2);
    expect(query2[1]).to.equal(receipt2.blockNumber);
    expect(query2[2]).to.equal(2);
  });
});

const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("BN254 (alt_bn128) Cryptographic Library - Milestone 1", function () {
  let bn254;

  const P = 21888242871839275222246405745257275088696311157297823662689037894645226208583n;
  const Q = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;
  const GX = 1n;
  const GY = 2n;

  // Independently calculated Weierstrass addition reference points
  const REF_2G_X = 0x30644e72e131a029b85045b68181585d97816a916871ca8d3c208c16d87cfd3n;
  const REF_2G_Y = 0x15ed738c0e0a7c92e7845f96b2ae9c0a68a6a449e3538fc7ff3ebf7a5a18a2c4n;

  const REF_3G_X = 0x769bf9ac56bea3ff40232bcb1b6bd159315d84715b8e679f2d355961915abf0n;
  const REF_3G_Y = 0x2ab799bee0489429554fdb7c8d086475319e63b40b9c5b57cdf1ff3dd9fe2261n;

  before(async function () {
    const Factory = await ethers.getContractFactory("BN254TestWrapper");
    bn254 = await Factory.deploy();
    await bn254.waitForDeployment();
  });

  it("1. Verifies mathematical constants against authoritative specification", async function () {
    const [p, q, gx, gy] = await bn254.getConstants();
    expect(p).to.equal(P);
    expect(q).to.equal(Q);
    expect(gx).to.equal(GX);
    expect(gy).to.equal(GY);
  });

  it("2. Generator G is on the curve", async function () {
    const [gx, gy] = await bn254.generator();
    expect(gx).to.equal(GX);
    expect(gy).to.equal(GY);
    expect(await bn254.isPointOnCurve(gx, gy)).to.be.true;
    await expect(bn254.validatePoint(gx, gy)).to.not.be.reverted;
  });

  it("3. Generator multiplied by 1 equals generator (1 * G = G)", async function () {
    const [rx, ry] = await bn254.pointMul(GX, GY, 1n);
    expect(rx).to.equal(GX);
    expect(ry).to.equal(GY);
  });

  it("4. Generator multiplied by 0 equals point at infinity (0 * G = (0, 0))", async function () {
    const [rx, ry] = await bn254.pointMul(GX, GY, 0n);
    expect(rx).to.equal(0n);
    expect(ry).to.equal(0n);
  });

  it("5. G + (-G) equals point at infinity", async function () {
    const [negGx, negGy] = await bn254.pointNeg(GX, GY);
    expect(negGx).to.equal(GX);
    expect(negGy).to.equal(P - GY);

    const [rx, ry] = await bn254.pointAdd(GX, GY, negGx, negGy);
    expect(rx).to.equal(0n);
    expect(ry).to.equal(0n);
  });

  it("6. G multiplied by q equals point at infinity (q * G = (0, 0) via (q-1)*G + G)", async function () {
    // In BN254 subgroup of order q, scalar q is equivalent to 0 mod q.
    // The library enforces strict validation s < q.
    // Here we verify that (q - 1) * G equals -G:
    const [rx, ry] = await bn254.pointMul(GX, GY, Q - 1n);
    expect(rx).to.equal(GX);
    expect(ry).to.equal(P - GY);

    // Adding G to (q - 1) * G yields q * G = (0, 0):
    const [infX, infY] = await bn254.pointAdd(rx, ry, GX, GY);
    expect(infX).to.equal(0n);
    expect(infY).to.equal(0n);
  });

  it("7. Valid point addition matches independent reference implementation", async function () {
    // Independent reference: G + G = 2G
    const [twoGx, twoGy] = await bn254.pointAdd(GX, GY, GX, GY);
    expect(twoGx).to.equal(REF_2G_X);
    expect(twoGy).to.equal(REF_2G_Y);
    expect(await bn254.isPointOnCurve(twoGx, twoGy)).to.be.true;

    // Independent reference: 2G + G = 3G
    const [threeGx, threeGy] = await bn254.pointAdd(twoGx, twoGy, GX, GY);
    expect(threeGx).to.equal(REF_3G_X);
    expect(threeGy).to.equal(REF_3G_Y);
    expect(await bn254.isPointOnCurve(threeGx, threeGy)).to.be.true;

    // Scalar multiplication: 3 * G == 3G
    const [mul3Gx, mul3Gy] = await bn254.pointMul(GX, GY, 3n);
    expect(mul3Gx).to.equal(REF_3G_X);
    expect(mul3Gy).to.equal(REF_3G_Y);
  });

  it("8. Point subtraction behaves correctly: 3G - G = 2G", async function () {
    const [rx, ry] = await bn254.pointSub(REF_3G_X, REF_3G_Y, GX, GY);
    expect(rx).to.equal(REF_2G_X);
    expect(ry).to.equal(REF_2G_Y);
  });

  it("9. Off-curve points are rejected", async function () {
    // (1, 3) is not on curve: 3^2 = 9 != 1^3 + 3 = 4
    expect(await bn254.isPointOnCurve(1n, 3n)).to.be.false;
    await expect(bn254.validatePoint(1n, 3n)).to.be.revertedWith("POINT_NOT_ON_CURVE");
    await expect(bn254.pointAdd(1n, 3n, GX, GY)).to.be.revertedWith("POINT_NOT_ON_CURVE");
    await expect(bn254.pointMul(1n, 3n, 2n)).to.be.revertedWith("POINT_NOT_ON_CURVE");
  });

  it("10. Coordinates greater than or equal to field modulus p are rejected", async function () {
    await expect(bn254.validatePoint(P, GY)).to.be.revertedWith("COORDINATE_EXCEEDS_FIELD_P");
    await expect(bn254.validatePoint(GX, P)).to.be.revertedWith("COORDINATE_EXCEEDS_FIELD_P");
    await expect(bn254.validatePoint(P + 100n, GY)).to.be.revertedWith("COORDINATE_EXCEEDS_FIELD_P");
  });

  it("11. Scalars greater than or equal to subgroup order q are rejected", async function () {
    await expect(bn254.validateScalar(Q)).to.be.revertedWith("SCALAR_EXCEEDS_ORDER_Q");
    await expect(bn254.validateScalar(Q + 1n)).to.be.revertedWith("SCALAR_EXCEEDS_ORDER_Q");
    await expect(bn254.pointMul(GX, GY, Q)).to.be.revertedWith("SCALAR_EXCEEDS_ORDER_Q");
  });

  it("12. Point at infinity (0, 0) is handled correctly in addition, subtraction, and multiplication", async function () {
    const [infX, infY] = await bn254.infinity();
    expect(infX).to.equal(0n);
    expect(infY).to.equal(0n);

    // Infinity is on the curve as group identity
    expect(await bn254.isPointOnCurve(0n, 0n)).to.be.true;

    // Infinity + G = G
    const [addInfG_X, addInfG_Y] = await bn254.pointAdd(0n, 0n, GX, GY);
    expect(addInfG_X).to.equal(GX);
    expect(addInfG_Y).to.equal(GY);

    // G + Infinity = G
    const [addGInf_X, addGInf_Y] = await bn254.pointAdd(GX, GY, 0n, 0n);
    expect(addGInf_X).to.equal(GX);
    expect(addGInf_Y).to.equal(GY);

    // Infinity + Infinity = Infinity
    const [addInfInf_X, addInfInf_Y] = await bn254.pointAdd(0n, 0n, 0n, 0n);
    expect(addInfInf_X).to.equal(0n);
    expect(addInfInf_Y).to.equal(0n);

    // G - G = Infinity
    const [subGG_X, subGG_Y] = await bn254.pointSub(GX, GY, GX, GY);
    expect(subGG_X).to.equal(0n);
    expect(subGG_Y).to.equal(0n);

    // Infinity * s = Infinity
    const [mulInf_X, mulInf_Y] = await bn254.pointMul(0n, 0n, 5n);
    expect(mulInf_X).to.equal(0n);
    expect(mulInf_Y).to.equal(0n);

    // Negation of Infinity is Infinity
    const [negInf_X, negInf_Y] = await bn254.pointNeg(0n, 0n);
    expect(negInf_X).to.equal(0n);
    expect(negInf_Y).to.equal(0n);
  });

  it("13. Precompile failure is handled safely when out-of-field inputs are passed", async function () {
    // Calling ecAdd (0x06) directly with coordinate X >= P triggers EIP-196 precompile error
    const outOfFieldAdd = ethers.AbiCoder.defaultAbiCoder().encode(
      ["uint256", "uint256", "uint256", "uint256"],
      [P, GY, GX, GY]
    );
    await expect(bn254.rawEcAdd(outOfFieldAdd)).to.be.revertedWith("EC_ADD_PRECOMPILE_FAILED");

    // Calling ecMul (0x07) directly with coordinate X >= P triggers EIP-196 precompile error
    const outOfFieldMul = ethers.AbiCoder.defaultAbiCoder().encode(
      ["uint256", "uint256", "uint256"],
      [P, GY, 5n]
    );
    await expect(bn254.rawEcMul(outOfFieldMul)).to.be.revertedWith("EC_MUL_PRECOMPILE_FAILED");
  });

  it("14. Measures exact gas consumption for precompile operations in isolated environment", async function () {
    // Benchmark Point Validation
    const valTx = await bn254.validatePoint(GX, GY);
    // Point Add (ecAdd 0x06)
    const addGas = await bn254.pointAdd.estimateGas(GX, GY, REF_2G_X, REF_2G_Y);
    // Point Mul (ecMul 0x07)
    const mulGas = await bn254.pointMul.estimateGas(GX, GY, 123456789n);
    // Point Neg
    const negGas = await bn254.pointNeg.estimateGas(GX, GY);
    // Point Sub
    const subGas = await bn254.pointSub.estimateGas(REF_3G_X, REF_3G_Y, GX, GY);

    console.log(`\n    --- MEASURED GAS BENCHMARKS (Hardhat Paris EVM) ---`);
    console.log(`    pointAdd (ecAdd precompile + on-curve validation): ${addGas.toString()} gas`);
    console.log(`    pointMul (ecMul precompile + on-curve validation): ${mulGas.toString()} gas`);
    console.log(`    pointNeg (modular arithmetic):                     ${negGas.toString()} gas`);
    console.log(`    pointSub (negation + ecAdd):                       ${subGas.toString()} gas`);
    console.log(`    ---------------------------------------------------\n`);

    expect(Number(addGas)).to.be.lessThan(50000);
    expect(Number(mulGas)).to.be.lessThan(50000);
  });
});

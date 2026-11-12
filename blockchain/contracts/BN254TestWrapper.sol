// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./BN254.sol";

/**
 * @title BN254TestWrapper
 * @dev Test harness contract exposing BN254 library functions for isolated unit testing.
 */
contract BN254TestWrapper {
    using BN254 for BN254.G1Point;

    function getConstants() external pure returns (uint256 p, uint256 q, uint256 gx, uint256 gy) {
        return (BN254.P, BN254.Q, BN254.GX, BN254.GY);
    }

    function generator() external pure returns (uint256 x, uint256 y) {
        BN254.G1Point memory g = BN254.generator();
        return (g.x, g.y);
    }

    function infinity() external pure returns (uint256 x, uint256 y) {
        BN254.G1Point memory inf = BN254.infinity();
        return (inf.x, inf.y);
    }

    function isPointOnCurve(uint256 x, uint256 y) external pure returns (bool) {
        return BN254.isOnCurve(BN254.G1Point(x, y));
    }

    function validatePoint(uint256 x, uint256 y) external pure {
        BN254.validatePoint(BN254.G1Point(x, y));
    }

    function validateScalar(uint256 s) external pure {
        BN254.validateScalar(s);
    }

    function pointNeg(uint256 x, uint256 y) external pure returns (uint256 rx, uint256 ry) {
        BN254.G1Point memory res = BN254.neg(BN254.G1Point(x, y));
        return (res.x, res.y);
    }

    function pointAdd(
        uint256 x1,
        uint256 y1,
        uint256 x2,
        uint256 y2
    ) external view returns (uint256 rx, uint256 ry) {
        BN254.G1Point memory p1 = BN254.G1Point(x1, y1);
        BN254.G1Point memory p2 = BN254.G1Point(x2, y2);
        BN254.G1Point memory res = BN254.add(p1, p2);
        return (res.x, res.y);
    }

    function pointMul(
        uint256 x,
        uint256 y,
        uint256 s
    ) external view returns (uint256 rx, uint256 ry) {
        BN254.G1Point memory p = BN254.G1Point(x, y);
        BN254.G1Point memory res = BN254.mul(p, s);
        return (res.x, res.y);
    }

    function pointSub(
        uint256 x1,
        uint256 y1,
        uint256 x2,
        uint256 y2
    ) external view returns (uint256 rx, uint256 ry) {
        BN254.G1Point memory p1 = BN254.G1Point(x1, y1);
        BN254.G1Point memory p2 = BN254.G1Point(x2, y2);
        BN254.G1Point memory res = BN254.sub(p1, p2);
        return (res.x, res.y);
    }

    /**
     * @notice Invokes precompile 0x06 directly with arbitrary calldata to test precompile failure handling.
     */
    function rawEcAdd(bytes calldata input) external view returns (uint256 rx, uint256 ry) {
        bool success;
        uint256[2] memory result;
        assembly {
            let memPtr := mload(0x40)
            calldatacopy(memPtr, input.offset, input.length)
            success := staticcall(gas(), 0x06, memPtr, input.length, result, 0x40)
            if success {
                rx := mload(result)
                ry := mload(add(result, 0x20))
            }
        }
        require(success, "EC_ADD_PRECOMPILE_FAILED");
    }

    /**
     * @notice Invokes precompile 0x07 directly with arbitrary calldata to test precompile failure handling.
     */
    function rawEcMul(bytes calldata input) external view returns (uint256 rx, uint256 ry) {
        bool success;
        uint256[2] memory result;
        assembly {
            let memPtr := mload(0x40)
            calldatacopy(memPtr, input.offset, input.length)
            success := staticcall(gas(), 0x07, memPtr, input.length, result, 0x40)
            if success {
                rx := mload(result)
                ry := mload(add(result, 0x20))
            }
        }
        require(success, "EC_MUL_PRECOMPILE_FAILED");
    }
}

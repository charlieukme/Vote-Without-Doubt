// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title BN254
 * @dev High-assurance mathematical library for the BN254 (alt_bn128) elliptic curve G1 group.
 * Complies with Ethereum EIP-196 / EIP-197 standard precompiles at 0x06 (ecAdd) and 0x07 (ecMul).
 */
library BN254 {
    // Curve equation over F_p: Y^2 = X^3 + 3 (mod p)

    // Base field modulus p
    uint256 internal constant P = 21888242871839275222246405745257275088696311157297823662689037894645226208583;

    // Subgroup scalar order q (order of G1)
    uint256 internal constant Q = 21888242871839275222246405745257275088548364400416034343698204186575808495617;

    // Standard generator G in G1
    uint256 internal constant GX = 1;
    uint256 internal constant GY = 2;

    struct G1Point {
        uint256 x;
        uint256 y;
    }

    /**
     * @notice Returns the standard base generator G of G1.
     */
    function generator() internal pure returns (G1Point memory) {
        return G1Point(GX, GY);
    }

    /**
     * @notice Returns the point at infinity (group identity element).
     * In EIP-196, point at infinity is encoded as (0, 0).
     */
    function infinity() internal pure returns (G1Point memory) {
        return G1Point(0, 0);
    }

    /**
     * @notice Checks whether a given point is the point at infinity (0, 0).
     */
    function isInfinity(G1Point memory p) internal pure returns (bool) {
        return (p.x == 0 && p.y == 0);
    }

    /**
     * @notice Verifies whether a given point lies on the BN254 G1 curve.
     * The point at infinity (0, 0) is valid identity.
     * Finite points must satisfy: x < p, y < p, and y^2 = x^3 + 3 (mod p).
     */
    function isOnCurve(G1Point memory p) internal pure returns (bool) {
        if (isInfinity(p)) {
            return true;
        }

        if (p.x >= P || p.y >= P) {
            return false;
        }

        uint256 lhs = mulmod(p.y, p.y, P);
        uint256 x3 = mulmod(mulmod(p.x, p.x, P), p.x, P);
        uint256 rhs = addmod(x3, 3, P);

        return (lhs == rhs);
    }

    /**
     * @notice Reverts if point coordinates are out of field range or point is off-curve.
     */
    function validatePoint(G1Point memory p) internal pure {
        require(p.x < P, "COORDINATE_EXCEEDS_FIELD_P");
        require(p.y < P, "COORDINATE_EXCEEDS_FIELD_P");
        require(isOnCurve(p), "POINT_NOT_ON_CURVE");
    }

    /**
     * @notice Reverts if scalar is not in valid subgroup range [0, q-1].
     */
    function validateScalar(uint256 s) internal pure {
        require(s < Q, "SCALAR_EXCEEDS_ORDER_Q");
    }

    /**
     * @notice Computes point negation: -P.
     * For (0, 0), returns (0, 0).
     * For (x, y), returns (x, p - y).
     */
    function neg(G1Point memory p) internal pure returns (G1Point memory) {
        if (isInfinity(p)) {
            return infinity();
        }
        validatePoint(p);
        return G1Point(p.x, P - p.y);
    }

    /**
     * @notice Adds two G1 points using EVM precompile 0x06 (ecAdd).
     * Validates input points and safely handles point at infinity and precompile failure.
     */
    function add(G1Point memory p1, G1Point memory p2) internal view returns (G1Point memory result) {
        validatePoint(p1);
        validatePoint(p2);

        // Identity optimizations
        if (isInfinity(p1)) {
            return p2;
        }
        if (isInfinity(p2)) {
            return p1;
        }

        uint256[4] memory input = [p1.x, p1.y, p2.x, p2.y];
        bool success;

        assembly {
            success := staticcall(gas(), 0x06, input, 0x80, input, 0x40)
            if success {
                mstore(result, mload(input))
                mstore(add(result, 0x20), mload(add(input, 0x20)))
            }
        }

        require(success, "EC_ADD_PRECOMPILE_FAILED");
    }

    /**
     * @notice Multiplies G1 point p by scalar s using EVM precompile 0x07 (ecMul).
     * Validates input point and scalar s < q.
     */
    function mul(G1Point memory p, uint256 s) internal view returns (G1Point memory result) {
        validatePoint(p);
        validateScalar(s);

        if (s == 0 || isInfinity(p)) {
            return infinity();
        }

        uint256[3] memory input = [p.x, p.y, s];
        bool success;

        assembly {
            success := staticcall(gas(), 0x07, input, 0x60, input, 0x40)
            if success {
                mstore(result, mload(input))
                mstore(add(result, 0x20), mload(add(input, 0x20)))
            }
        }

        require(success, "EC_MUL_PRECOMPILE_FAILED");
    }

    /**
     * @notice Subtracts point p2 from p1: p1 - p2 = p1 + (-p2).
     */
    function sub(G1Point memory p1, G1Point memory p2) internal view returns (G1Point memory) {
        return add(p1, neg(p2));
    }
}

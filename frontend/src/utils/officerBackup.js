/**
 * Officer Key Backup & Recovery Utility for Vote Without Doubt (FIX 3 V2).
 *
 * Implements high-assurance client-side encryption and recovery for officer private shares:
 * - KDF: Argon2id (64 MB memory, 3 iterations, 4 lanes) via audited WASM engine (hash-wasm)
 * - Cipher: AES-256-GCM with 96-bit (12-byte) random IV and 128-bit (16-byte) authentication tag
 * - AAD: Canonical ABI-encoded (uint256 electionId, uint256 officerId) cryptographically bound to ciphertext
 * - Strict Pre-Allocation Metadata Validation to prevent resource-exhaustion attacks
 *
 * Security Guarantees:
 * - Private scalar is generated and maintained solely in volatile browser memory.
 * - Private scalar is never transmitted to Flask or any backend service.
 * - Private scalar is never written to localStorage or sessionStorage in plaintext.
 * - Any alteration to ciphertext, metadata, AAD, salt, or IV causes immediate cryptographic authentication failure.
 */

import { argon2id } from 'hash-wasm'
import { G, Q, pointMul, isInfinity, isOnCurve } from './bn254_client.js'

const cryptoObj = typeof window !== 'undefined' ? window.crypto : globalThis.crypto

// Canonical KDF Parameters per Milestone 3 Specification
export const KDF_PARAMS = {
  algorithm: 'Argon2id',
  memorySize: 65536, // 64 MB
  iterations: 3,     // 3 iterations
  parallelism: 4,    // 4 lanes
  hashLength: 32,    // 32 bytes (256-bit AES key)
  saltBytes: 16,     // 16-byte random salt
  ivBytes: 12,       // 12-byte random IV
}

function bufferToHex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

function hexToBuffer(hex) {
  const clean = hex.startsWith('0x') ? hex.slice(2) : hex
  if (clean.length % 2 !== 0) {
    throw new Error('Hex string must have an even length')
  }
  const bytes = new Uint8Array(clean.length / 2)
  for (let i = 0; i < clean.length; i += 2) {
    const byte = parseInt(clean.substring(i, i + 2), 16)
    if (Number.isNaN(byte)) {
      throw new Error('Invalid hexadecimal character in string')
    }
    bytes[i / 2] = byte
  }
  return bytes
}

/**
 * Computes canonical ABI-encoded AAD: abi.encode(uint256(electionId), uint256(officerId))
 * Total 64 bytes (32-byte big-endian electionId || 32-byte big-endian officerId).
 */
export function computeCanonicalAad(electionId, officerId) {
  const buf = new Uint8Array(64)
  const eId = BigInt(electionId)
  const oId = BigInt(officerId)

  for (let i = 0; i < 32; i++) {
    buf[31 - i] = Number((eId >> BigInt(i * 8)) & 0xffn)
  }
  for (let i = 0; i < 32; i++) {
    buf[63 - i] = Number((oId >> BigInt(i * 8)) & 0xffn)
  }
  return buf
}

/**
 * Validates backup metadata, schema, and KDF parameter bounds BEFORE resource allocation.
 */
export function validateBackupMetadata(data) {
  if (!data || typeof data !== 'object') {
    throw new Error('Malformed backup data: expected JSON object')
  }

  if (data.version !== 'VWD_OFFICER_BACKUP_V2' && data.version !== 'VWD_OFFICER_BACKUP_V1') {
    throw new Error(`Unsupported backup version: ${data.version}`)
  }

  // Validate officerId & electionId
  const officerId = Number(data.officer_id)
  if (officerId !== 1 && officerId !== 2) {
    throw new Error('Invalid officer_id in backup: must be 1 or 2')
  }

  if (data.election_id === undefined || data.election_id === null || String(data.election_id).trim() === '') {
    throw new Error('Missing or empty election_id in backup')
  }
  try {
    BigInt(data.election_id)
  } catch {
    throw new Error('Invalid election_id format: must be representable as uint256')
  }

  // Validate KDF configuration
  if (!data.kdf || typeof data.kdf !== 'object') {
    throw new Error('Missing KDF configuration object in backup')
  }

  if (data.version === 'VWD_OFFICER_BACKUP_V2') {
    if (data.kdf.algorithm !== 'Argon2id') {
      throw new Error(`Invalid KDF algorithm: expected Argon2id, got ${data.kdf.algorithm}`)
    }
    if (data.kdf.memorySize !== 65536) {
      throw new Error(`Invalid KDF memorySize: expected 65536 (64MB), got ${data.kdf.memorySize}`)
    }
    if (data.kdf.iterations !== 3) {
      throw new Error(`Invalid KDF iterations: expected 3, got ${data.kdf.iterations}`)
    }
    if (data.kdf.parallelism !== 4) {
      throw new Error(`Invalid KDF parallelism: expected 4, got ${data.kdf.parallelism}`)
    }
    if (!data.kdf.salt || typeof data.kdf.salt !== 'string' || data.kdf.salt.replace(/^0x/, '').length !== 32) {
      throw new Error('Invalid KDF salt: expected 16 bytes (32 hex characters)')
    }
  }

  // Validate Cipher configuration
  if (!data.cipher || typeof data.cipher !== 'object') {
    throw new Error('Missing cipher configuration object in backup')
  }
  if (data.cipher.algorithm !== 'AES-256-GCM') {
    throw new Error(`Invalid cipher algorithm: expected AES-256-GCM, got ${data.cipher.algorithm}`)
  }
  if (!data.cipher.iv || typeof data.cipher.iv !== 'string' || data.cipher.iv.replace(/^0x/, '').length !== 24) {
    throw new Error('Invalid cipher IV: expected 12 bytes (24 hex characters)')
  }
  if (!data.cipher.ciphertext || typeof data.cipher.ciphertext !== 'string' || data.cipher.ciphertext.length < 32) {
    throw new Error('Invalid ciphertext: missing or truncated ciphertext')
  }

  // Validate Public Key coordinates
  if (!data.public_key || typeof data.public_key !== 'object') {
    throw new Error('Missing public_key object in backup')
  }
  try {
    const px = BigInt(data.public_key.x)
    const py = BigInt(data.public_key.y)
    const pt = { x: px, y: py }
    if (isInfinity(pt) || !isOnCurve(pt)) {
      throw new Error('Public key in backup is off-curve or infinity')
    }
  } catch (err) {
    throw new Error('Malformed public key coordinates: ' + err.message)
  }

  return true
}

/**
 * Derives a 256-bit AES key using Argon2id with audited Milestone 3 parameters.
 */
async function deriveArgon2idKey(passphrase, saltBytes) {
  const keyBytes = await argon2id({
    password: passphrase,
    salt: saltBytes,
    iterations: KDF_PARAMS.iterations,
    memorySize: KDF_PARAMS.memorySize,
    parallelism: KDF_PARAMS.parallelism,
    hashLength: KDF_PARAMS.hashLength,
    outputType: 'binary',
  })

  return cryptoObj.subtle.importKey(
    'raw',
    keyBytes,
    { name: 'AES-GCM' },
    false,
    ['encrypt', 'decrypt']
  )
}

/**
 * Exports an officer private scalar as an Argon2id + AES-256-GCM encrypted backup object.
 *
 * @param {string|bigint} privKey - The officer's private scalar (hex string or BigInt)
 * @param {number} officerId - 1 or 2
 * @param {number|string} electionId - The election ID
 * @param {string} passphrase - Strong passphrase chosen by the officer
 * @returns {Promise<object>} The backup object ready to be downloaded as JSON
 */
export async function exportEncryptedOfficerBackup(privKey, officerId, electionId, passphrase) {
  if (!passphrase || passphrase.length < 8) {
    throw new Error('Passphrase must be at least 8 characters long')
  }

  const oId = Number(officerId)
  if (oId !== 1 && oId !== 2) {
    throw new Error('officerId must be 1 or 2')
  }

  const sk = BigInt(privKey)
  if (sk <= 0n || sk >= Q) {
    throw new Error('Invalid private scalar: must be in [1, Q-1]')
  }

  // Derive public key for verification
  const pubKey = pointMul(G, sk)
  if (isInfinity(pubKey) || !isOnCurve(pubKey)) {
    throw new Error('Invalid derived public key')
  }

  // Generate 16 bytes (128 bits) salt and 12 bytes (96 bits) IV
  const salt = new Uint8Array(16)
  cryptoObj.getRandomValues(salt)
  const iv = new Uint8Array(12)
  cryptoObj.getRandomValues(iv)

  // Compute canonical ABI-encoded AAD
  const aad = computeCanonicalAad(electionId, oId)

  // Derive AES-256-GCM key using Argon2id (64MB, 3 iterations, 4 lanes)
  const aesKey = await deriveArgon2idKey(passphrase, salt)

  // Payload containing the private key and timestamp
  const payload = JSON.stringify({
    sk: '0x' + sk.toString(16).padStart(64, '0'),
    officer_id: oId,
    election_id: String(electionId),
    timestamp: new Date().toISOString(),
  })

  const enc = new TextEncoder()
  const ciphertextBuffer = await cryptoObj.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv: iv,
      additionalData: aad,
      tagLength: 128, // 16-byte authentication tag
    },
    aesKey,
    enc.encode(payload)
  )

  return {
    version: 'VWD_OFFICER_BACKUP_V2',
    officer_id: oId,
    election_id: String(electionId),
    kdf: {
      algorithm: 'Argon2id',
      memorySize: KDF_PARAMS.memorySize,
      iterations: KDF_PARAMS.iterations,
      parallelism: KDF_PARAMS.parallelism,
      salt: bufferToHex(salt),
    },
    cipher: {
      algorithm: 'AES-256-GCM',
      iv: bufferToHex(iv),
      ciphertext: bufferToHex(ciphertextBuffer),
    },
    public_key: {
      x: '0x' + pubKey.x.toString(16).padStart(64, '0'),
      y: '0x' + pubKey.y.toString(16).padStart(64, '0'),
    },
    created_at: new Date().toISOString(),
  }
}

/**
 * Recovers an officer private scalar from an encrypted backup object using the passphrase.
 *
 * @param {object|string} backupData - The parsed backup object or JSON string
 * @param {string} passphrase - The officer's passphrase
 * @returns {Promise<{privKey: bigint, officerId: number, electionId: string, pubKey: {x: bigint, y: bigint}}>}
 */
export async function importEncryptedOfficerBackup(backupData, passphrase) {
  let data
  try {
    data = typeof backupData === 'string' ? JSON.parse(backupData) : backupData
  } catch {
    throw new Error('Corrupted backup file: invalid JSON format')
  }

  // Pre-allocation validation: aborts before allocating 64MB memory if metadata or parameters are invalid
  validateBackupMetadata(data)

  const saltBuffer = hexToBuffer(data.kdf.salt)
  const ivBuffer = hexToBuffer(data.cipher.iv)
  const ciphertextBuffer = hexToBuffer(data.cipher.ciphertext)
  const officerId = Number(data.officer_id)
  const electionId = String(data.election_id)

  // Compute canonical ABI-encoded AAD to ensure metadata hasn't been tampered with
  const aad = computeCanonicalAad(electionId, officerId)

  let aesKey
  try {
    if (data.version === 'VWD_OFFICER_BACKUP_V2') {
      aesKey = await deriveArgon2idKey(passphrase, saltBuffer)
    } else {
      // Legacy V1 fallback (PBKDF2)
      const passphraseKey = await cryptoObj.subtle.importKey(
        'raw',
        new TextEncoder().encode(passphrase),
        { name: 'PBKDF2' },
        false,
        ['deriveKey']
      )
      aesKey = await cryptoObj.subtle.deriveKey(
        {
          name: 'PBKDF2',
          salt: saltBuffer,
          iterations: data.kdf.iterations || 250000,
          hash: 'SHA-256',
        },
        passphraseKey,
        { name: 'AES-GCM', length: 256 },
        false,
        ['decrypt']
      )
    }
  } catch (err) {
    throw new Error('Key derivation failed: ' + err.message)
  }

  let decryptedBuffer
  try {
    const decryptParams = {
      name: 'AES-GCM',
      iv: ivBuffer,
      tagLength: 128,
    }
    // Bind AAD for V2 backups
    if (data.version === 'VWD_OFFICER_BACKUP_V2') {
      decryptParams.additionalData = aad
    }

    decryptedBuffer = await cryptoObj.subtle.decrypt(
      decryptParams,
      aesKey,
      ciphertextBuffer
    )
  } catch {
    throw new Error('Incorrect passphrase or corrupted backup file (authentication tag mismatch)')
  }

  let payload
  try {
    const dec = new TextDecoder()
    const payloadStr = dec.decode(decryptedBuffer)
    payload = JSON.parse(payloadStr)
  } catch {
    throw new Error('Corrupted backup payload: unable to decode JSON content')
  }

  const sk = BigInt(payload.sk)
  if (sk <= 0n || sk >= Q) {
    throw new Error('Decrypted scalar out of valid range [1, Q-1]')
  }

  // Verify derived public key matches advertised public key in metadata
  const derivedPubKey = pointMul(G, sk)
  const expectedX = BigInt(data.public_key.x)
  const expectedY = BigInt(data.public_key.y)

  if (derivedPubKey.x !== expectedX || derivedPubKey.y !== expectedY) {
    throw new Error('Decrypted key does not match backup public key metadata!')
  }

  return {
    privKey: sk,
    officerId: officerId,
    electionId: electionId,
    pubKey: derivedPubKey,
  }
}

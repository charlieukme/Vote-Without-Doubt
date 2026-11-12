import test from 'node:test'
import assert from 'node:assert'
import { generateClientSecureScalar, G, pointMul } from '../src/utils/bn254_client.js'
import {
  exportEncryptedOfficerBackup,
  importEncryptedOfficerBackup,
  validateBackupMetadata,
  computeCanonicalAad,
  KDF_PARAMS,
} from '../src/utils/officerBackup.js'

test('Officer Backup: Argon2id + AES-256-GCM Cryptographic Security Suite', async (t) => {
  const sk = generateClientSecureScalar()
  const pub = pointMul(G, sk)
  const electionId = '1'
  const officerId = 1
  const password = 'SuperSecretOfficerPassphrase123!'

  await t.test('1. Valid Export: Parameter compliance and specification conformance', async () => {
    const backup = await exportEncryptedOfficerBackup(sk, officerId, electionId, password)

    // Version and identity
    assert.strictEqual(backup.version, 'VWD_OFFICER_BACKUP_V2')
    assert.strictEqual(backup.officer_id, officerId)
    assert.strictEqual(backup.election_id, electionId)

    // Argon2id specification: 64MB memory, 3 iterations, 4 lanes, 16-byte salt
    assert.strictEqual(backup.kdf.algorithm, 'Argon2id')
    assert.strictEqual(backup.kdf.memorySize, 65536)
    assert.strictEqual(backup.kdf.iterations, 3)
    assert.strictEqual(backup.kdf.parallelism, 4)
    assert.strictEqual(backup.kdf.salt.length, 32) // 16 bytes = 32 hex chars

    // AES-256-GCM specification: 12-byte IV, 16-byte tag included in ciphertext
    assert.strictEqual(backup.cipher.algorithm, 'AES-256-GCM')
    assert.strictEqual(backup.cipher.iv.length, 24) // 12 bytes = 24 hex chars
    assert.ok(backup.cipher.ciphertext.length >= 32)

    // Advertised public key matches point multiplication
    assert.strictEqual(backup.public_key.x, '0x' + pub.x.toString(16).padStart(64, '0'))
    assert.strictEqual(backup.public_key.y, '0x' + pub.y.toString(16).padStart(64, '0'))
  })

  await t.test('2. Valid Recovery: Round-trip key recovery and integrity check', async () => {
    const backup = await exportEncryptedOfficerBackup(sk, officerId, electionId, password)
    const recovered = await importEncryptedOfficerBackup(backup, password)

    assert.strictEqual(recovered.privKey, sk)
    assert.strictEqual(recovered.officerId, officerId)
    assert.strictEqual(recovered.electionId, electionId)
    assert.strictEqual(recovered.pubKey.x, pub.x)
    assert.strictEqual(recovered.pubKey.y, pub.y)
  })

  await t.test('3. Wrong Passphrase: Cryptographic authentication failure', async () => {
    const backup = await exportEncryptedOfficerBackup(sk, officerId, electionId, password)

    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(backup, 'IncorrectPassphrase999!')
      },
      /Incorrect passphrase or corrupted backup file \(authentication tag mismatch\)/
    )
  })

  await t.test('4. Modified Ciphertext: GCM authentication tag rejection', async () => {
    const backup = await exportEncryptedOfficerBackup(sk, officerId, electionId, password)
    const tampered = JSON.parse(JSON.stringify(backup))

    // Flip a character in ciphertext
    const ctChars = Array.from(tampered.cipher.ciphertext)
    ctChars[10] = ctChars[10] === 'a' ? 'b' : 'a'
    tampered.cipher.ciphertext = ctChars.join('')

    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(tampered, password)
      },
      /Incorrect passphrase or corrupted backup file \(authentication tag mismatch\)/
    )
  })

  await t.test('5. Modified AAD Metadata: Tampering electionId or officerId fails GCM authentication', async () => {
    const backup = await exportEncryptedOfficerBackup(sk, 1, '1', password)

    // Tamper officer_id: change from 1 to 2 without changing ciphertext
    const tamperedOfficer = JSON.parse(JSON.stringify(backup))
    tamperedOfficer.officer_id = 2

    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(tamperedOfficer, password)
      },
      /Incorrect passphrase or corrupted backup file \(authentication tag mismatch\)/
    )

    // Tamper election_id: change from '1' to '2'
    const tamperedElection = JSON.parse(JSON.stringify(backup))
    tamperedElection.election_id = '2'

    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup(tamperedElection, password)
      },
      /Incorrect passphrase or corrupted backup file \(authentication tag mismatch\)/
    )
  })

  await t.test('6. Pre-Allocation Validation: Malformed parameters rejected before resource allocation', () => {
    // 6.1 Unsupported algorithm
    assert.throws(() => {
      validateBackupMetadata({
        version: 'VWD_OFFICER_BACKUP_V2',
        officer_id: 1,
        election_id: '1',
        kdf: { algorithm: 'MD5', memorySize: 65536, iterations: 3, parallelism: 4, salt: '0'.repeat(32) },
        cipher: { algorithm: 'AES-256-GCM', iv: '0'.repeat(24), ciphertext: '0'.repeat(64) },
        public_key: { x: pub.x.toString(), y: pub.y.toString() },
      })
    }, /Invalid KDF algorithm: expected Argon2id/)

    // 6.2 Malicious memory size parameter
    assert.throws(() => {
      validateBackupMetadata({
        version: 'VWD_OFFICER_BACKUP_V2',
        officer_id: 1,
        election_id: '1',
        kdf: { algorithm: 'Argon2id', memorySize: 99999999, iterations: 3, parallelism: 4, salt: '0'.repeat(32) },
        cipher: { algorithm: 'AES-256-GCM', iv: '0'.repeat(24), ciphertext: '0'.repeat(64) },
        public_key: { x: pub.x.toString(), y: pub.y.toString() },
      })
    }, /Invalid KDF memorySize: expected 65536/)

    // 6.3 Truncated salt
    assert.throws(() => {
      validateBackupMetadata({
        version: 'VWD_OFFICER_BACKUP_V2',
        officer_id: 1,
        election_id: '1',
        kdf: { algorithm: 'Argon2id', memorySize: 65536, iterations: 3, parallelism: 4, salt: '0'.repeat(16) },
        cipher: { algorithm: 'AES-256-GCM', iv: '0'.repeat(24), ciphertext: '0'.repeat(64) },
        public_key: { x: pub.x.toString(), y: pub.y.toString() },
      })
    }, /Invalid KDF salt: expected 16 bytes/)

    // 6.4 Truncated IV
    assert.throws(() => {
      validateBackupMetadata({
        version: 'VWD_OFFICER_BACKUP_V2',
        officer_id: 1,
        election_id: '1',
        kdf: { algorithm: 'Argon2id', memorySize: 65536, iterations: 3, parallelism: 4, salt: '0'.repeat(32) },
        cipher: { algorithm: 'AES-256-GCM', iv: '0'.repeat(16), ciphertext: '0'.repeat(64) },
        public_key: { x: pub.x.toString(), y: pub.y.toString() },
      })
    }, /Invalid cipher IV: expected 12 bytes/)

    // 6.5 Corrupted off-curve public key
    assert.throws(() => {
      validateBackupMetadata({
        version: 'VWD_OFFICER_BACKUP_V2',
        officer_id: 1,
        election_id: '1',
        kdf: { algorithm: 'Argon2id', memorySize: 65536, iterations: 3, parallelism: 4, salt: '0'.repeat(32) },
        cipher: { algorithm: 'AES-256-GCM', iv: '0'.repeat(24), ciphertext: '0'.repeat(64) },
        public_key: { x: '12345', y: '67890' }, // Off curve coordinates
      })
    }, /Public key in backup is off-curve/)
  })

  await t.test('7. Corrupted JSON file format handling', async () => {
    await assert.rejects(
      async () => {
        await importEncryptedOfficerBackup('{ invalid json: true ', password)
      },
      /Corrupted backup file: invalid JSON format/
    )
  })

  await t.test('8. Canonical AAD computation matches ABI specification', () => {
    const aad = computeCanonicalAad('1', 2)
    assert.strictEqual(aad.length, 64)
    // First 32 bytes = electionId (1)
    assert.strictEqual(aad[31], 1)
    assert.strictEqual(aad[0], 0)
    // Second 32 bytes = officerId (2)
    assert.strictEqual(aad[63], 2)
    assert.strictEqual(aad[32], 0)
  })
})

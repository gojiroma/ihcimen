package com.ihcimen.android.crypto

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class SyncCryptoTest {

    // A fixed all-zero 16-byte seed, base64url-encoded with no padding —
    // deterministic so deriveSyncId's output here can be cross-checked
    // against index.html / Crypto.swift by hand if this test ever fails.
    private val fixedSeed = "AAAAAAAAAAAAAAAAAAAAAA"

    @Test
    fun `seedBytes rejects the wrong length`() {
        try {
            SyncCrypto.seedBytes("AAAA")
            error("expected InvalidSeedException")
        } catch (e: SyncCrypto.InvalidSeedException) {
            // expected
        }
    }

    @Test
    fun `deriveSyncId is deterministic and 64 lowercase hex chars`() {
        val seed = SyncCrypto.seedBytes(fixedSeed)
        val id1 = SyncCrypto.deriveSyncId(seed)
        val id2 = SyncCrypto.deriveSyncId(seed)
        assertEquals(id1, id2)
        assertEquals(64, id1.length)
        assertEquals(id1, id1.lowercase())
        assert(id1.all { it in "0123456789abcdef" })
    }

    /**
     * Cross-checks against a fully independent implementation: for the
     * all-zero 16-byte seed, `python3 -c "import hashlib,hmac; seed=bytes(16);
     * print(hashlib.sha256(seed + b'ihcimen-sync-id-entries-v1').hexdigest())"`
     * (and the equivalent HKDF HMAC chain for the AES key) produces these
     * exact values. If this ever fails, the Kotlin implementation has
     * diverged from index.html / Crypto.swift, not the other way around.
     */
    @Test
    fun `deriveSyncId and deriveAesKey match an independently computed reference value`() {
        val seed = SyncCrypto.seedBytes(fixedSeed) // 16 zero bytes
        val syncId = SyncCrypto.deriveSyncId(seed)
        assertEquals("5e2843ac145d7a414576a2ba7609c29de90768f3d8f524d8574f81feac031d3d", syncId)

        val aesKey = SyncCrypto.deriveAesKey(seed)
        val aesKeyHex = aesKey.encoded.joinToString("") { "%02x".format(it) }
        assertEquals("4d40707b649e0a885c209ddd9316433efb24b1976dea522dfbabba1c9fd9b68a", aesKeyHex)
    }

    @Test
    fun `different seeds derive different sync ids`() {
        val idA = SyncCrypto.deriveSyncId(SyncCrypto.seedBytes(fixedSeed))
        val idB = SyncCrypto.deriveSyncId(SyncCrypto.seedBytes(SyncCrypto.generateSeed()))
        assertNotEquals(idA, idB)
    }

    @Test
    fun `encrypt then decrypt round-trips`() {
        val seed = SyncCrypto.seedBytes(fixedSeed)
        val key = SyncCrypto.deriveAesKey(seed)
        val plaintext = "{\"hello\":\"世界\"}".toByteArray(Charsets.UTF_8)

        val (ciphertext, iv) = SyncCrypto.encrypt(plaintext, key)
        val decrypted = SyncCrypto.decrypt(ciphertext, iv, key)

        assertEquals(String(plaintext, Charsets.UTF_8), String(decrypted, Charsets.UTF_8))
    }

    @Test
    fun `same seed always derives the same aes key`() {
        val seed = SyncCrypto.seedBytes(fixedSeed)
        val keyA = SyncCrypto.deriveAesKey(seed)
        val keyB = SyncCrypto.deriveAesKey(seed)
        assertEquals(keyA, keyB)
    }

    @Test
    fun `generated seeds have the expected shape`() {
        repeat(20) {
            val seed = SyncCrypto.generateSeed()
            // Must round-trip through seedBytes without throwing, i.e. be a
            // valid 16-byte base64url (no padding) string.
            SyncCrypto.seedBytes(seed)
        }
    }
}

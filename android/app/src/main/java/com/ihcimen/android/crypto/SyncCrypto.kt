package com.ihcimen.android.crypto

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Mirrors the exact key derivation and AES-GCM scheme used by index.html's
 * sync code (deriveSyncId / deriveAesKey / encryptBlob / decryptBlob) and its
 * Swift port in macapp/TodayH1/Sources/TodayH1/Crypto.swift, so this app can
 * read and write the same encrypted blob as the web app's "entries" sync
 * channel. Do not change any of the constants below without changing them
 * identically in both of those places too.
 */
object SyncCrypto {
    private const val INFO_ENTRIES = "ihcimen-sync-id-entries-v1"
    private const val AES_INFO = "ihcimen-aes-key-v1"
    private const val HKDF_SALT = "ihcimen-fixed-salt-v1"
    private const val GCM_TAG_BITS = 128
    private const val GCM_IV_BYTES = 12
    private const val SEED_BYTES = 16

    class InvalidSeedException(message: String) : Exception(message)

    fun seedBytes(seed: String): ByteArray {
        val decoded = try {
            Base64.getUrlDecoder().decode(padBase64Url(seed.trim()))
        } catch (e: IllegalArgumentException) {
            throw InvalidSeedException("シードの形式が不正です")
        }
        if (decoded.size != SEED_BYTES) {
            throw InvalidSeedException("シードの形式が不正です(16バイトのbase64url文字列である必要があります)")
        }
        return decoded
    }

    fun generateSeed(): String {
        val bytes = ByteArray(SEED_BYTES)
        SecureRandom().nextBytes(bytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }

    fun deriveSyncId(seed: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        digest.update(seed)
        digest.update(INFO_ENTRIES.toByteArray(Charsets.UTF_8))
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    /**
     * HKDF-SHA256(salt=HKDF_SALT, ikm=seed, info=AES_INFO, length=32), i.e.
     * exactly what WebCrypto's `deriveBits({name:'HKDF', ...}, 256)` and
     * CryptoKit's `HKDF<SHA256>.deriveKey(outputByteCount: 32)` compute.
     * 32 bytes equals the hash's output length, so RFC 5869's HKDF-Expand
     * needs only a single block (T(1) = HMAC(PRK, info || 0x01)) — there is
     * no JDK-builtin HKDF, so this implements just that one block by hand
     * rather than the general multi-block algorithm.
     */
    fun deriveAesKey(seed: ByteArray): SecretKeySpec {
        val prk = hmacSha256(HKDF_SALT.toByteArray(Charsets.UTF_8), seed)
        val info = AES_INFO.toByteArray(Charsets.UTF_8)
        val t1 = hmacSha256(prk, info + byteArrayOf(1))
        return SecretKeySpec(t1, "AES")
    }

    private fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    /**
     * AES-GCM encrypt. JCE's Cipher already appends the 16-byte auth tag to
     * the ciphertext in doFinal's output, which is the same wire format
     * WebCrypto uses (unlike CryptoKit, which keeps them separate and needs
     * manual concatenation — see the comment in Crypto.swift).
     */
    fun encrypt(plaintext: ByteArray, key: SecretKeySpec): Pair<String, String> {
        val iv = ByteArray(GCM_IV_BYTES)
        SecureRandom().nextBytes(iv)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, iv))
        val combined = cipher.doFinal(plaintext)
        return Base64.getEncoder().encodeToString(combined) to Base64.getEncoder().encodeToString(iv)
    }

    fun decrypt(ciphertextB64: String, ivB64: String, key: SecretKeySpec): ByteArray {
        val combined = Base64.getDecoder().decode(ciphertextB64)
        val iv = Base64.getDecoder().decode(ivB64)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(GCM_TAG_BITS, iv))
        return cipher.doFinal(combined)
    }

    private fun padBase64Url(s: String): String {
        val padding = (4 - s.length % 4) % 4
        return s + "=".repeat(padding)
    }
}

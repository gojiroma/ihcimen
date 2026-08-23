package com.ihcimen.android.settings

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private val Context.dataStore by preferencesDataStore(name = "ihcimen_settings")

/**
 * Stores the sync seed (equivalent to a shared password — anyone with it
 * can read and write this account's data) encrypted with a non-exportable
 * Android Keystore AES key, on top of Preferences DataStore. Deliberately
 * does not use androidx.security:security-crypto's
 * EncryptedSharedPreferences, which Google deprecated (as of
 * security-crypto 1.1.0-alpha07) in favor of exactly this kind of
 * DataStore + manually-managed-Keystore-key approach.
 */
class SeedStore(private val context: Context) {
    private val keyAlias = "ihcimen_seed_key"
    private val seedKey = stringPreferencesKey("encrypted_seed")
    private val apiUrlKey = stringPreferencesKey("api_base_url")

    private fun keystoreKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(keyAlias, null) as? SecretKey)?.let { return it }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                keyAlias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    suspend fun getSeed(): String? {
        val stored = context.dataStore.data.first()[seedKey] ?: return null
        val combined = Base64.getDecoder().decode(stored)
        val iv = combined.copyOfRange(0, 12)
        val ciphertext = combined.copyOfRange(12, combined.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, keystoreKey(), GCMParameterSpec(128, iv))
        return String(cipher.doFinal(ciphertext), Charsets.UTF_8)
    }

    suspend fun setSeed(seed: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, keystoreKey())
        val ciphertext = cipher.doFinal(seed.toByteArray(Charsets.UTF_8))
        val combined = cipher.iv + ciphertext
        context.dataStore.edit { it[seedKey] = Base64.getEncoder().encodeToString(combined) }
    }

    suspend fun clearSeed() {
        context.dataStore.edit { it.remove(seedKey) }
    }

    suspend fun getApiBaseUrl(): String = context.dataStore.data.first()[apiUrlKey] ?: DEFAULT_API_BASE_URL

    suspend fun setApiBaseUrl(url: String) {
        context.dataStore.edit { it[apiUrlKey] = url }
    }

    companion object {
        const val DEFAULT_API_BASE_URL = "https://ihcimen.vercel.app"
    }
}

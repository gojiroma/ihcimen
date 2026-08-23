package com.ihcimen.android.sync

import kotlinx.serialization.Serializable

/**
 * Same shape as the JSON object index.html's encryptBlob wraps for the
 * "entries" channel, and Crypto.swift's EntriesBlob: the decrypted payload
 * for the whole "entries" sync channel.
 */
@Serializable
data class EntriesBlob(
    val version: Int = 1,
    val updatedAt: String,
    val entries: Map<String, String> = emptyMap(),
    val h1Shortcuts: String = "[]",
)

@Serializable
data class PullResponse(
    val found: Boolean,
    val ciphertext: String? = null,
    val iv: String? = null,
    val updated_at: String? = null,
)

@Serializable
data class PushRequestBody(
    val sync_id: String,
    val ciphertext: String,
    val iv: String,
    val updated_at: String,
)

@Serializable
data class PushResponse(
    val applied: Boolean,
    val updated_at: String,
)

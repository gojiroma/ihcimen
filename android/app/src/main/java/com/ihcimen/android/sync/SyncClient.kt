package com.ihcimen.android.sync

import com.ihcimen.android.crypto.SyncCrypto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

class SyncRejectedException : Exception("サーバー側に新しい変更があるため保存できませんでした")

/**
 * One "entries" sync channel client, talking to the same /api/pull and
 * /api/push endpoints as the web app (index.html) and TodayH1
 * (SyncClient.swift), using the identical crypto and wire format. This
 * class only knows how to pull/push a whole blob or prepend today's block
 * — it has no knowledge of local storage; see SyncManager for that.
 */
class SyncClient(
    baseUrl: String,
    seed: String,
    private val client: OkHttpClient = defaultClient,
) {
    private val apiBaseUrl = baseUrl.trimEnd('/')
    private val seedBytes = SyncCrypto.seedBytes(seed)
    val syncId: String = SyncCrypto.deriveSyncId(seedBytes)
    private val aesKey = SyncCrypto.deriveAesKey(seedBytes)
    private val json = Json { ignoreUnknownKeys = true }

    companion object {
        private val defaultClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        private val ISO_FORMATTER: DateTimeFormatter =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneId.of("UTC"))

        /** yyyy-MM-dd in the device's local timezone, matching localStorage's date keys. */
        fun todayDateKey(zone: ZoneId = ZoneId.systemDefault()): String =
            java.time.LocalDate.now(zone).toString()

        /** Matches JS's `new Date().toISOString()` exactly (millisecond precision, trailing "Z"). */
        fun nowJsIso(instant: Instant = Instant.now()): String = ISO_FORMATTER.format(instant)
    }

    suspend fun pull(): Pair<EntriesBlob, Instant?> = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$apiBaseUrl/api/pull?sync_id=$syncId").get().build()
        val responseBody = execute(request)
        val body = json.decodeFromString(PullResponse.serializer(), responseBody)
        if (!body.found || body.ciphertext == null || body.iv == null || body.updated_at == null) {
            return@withContext EntriesBlob(updatedAt = nowJsIso()) to null
        }
        val plaintext = SyncCrypto.decrypt(body.ciphertext, body.iv, aesKey)
        val blob = json.decodeFromString(EntriesBlob.serializer(), String(plaintext, Charsets.UTF_8))
        val serverUpdatedAt = OffsetDateTime.parse(body.updated_at).toInstant()
        blob to serverUpdatedAt
    }

    suspend fun push(blob: EntriesBlob): Boolean = withContext(Dispatchers.IO) {
        val plaintext = json.encodeToString(EntriesBlob.serializer(), blob).toByteArray(Charsets.UTF_8)
        val (ciphertext, iv) = SyncCrypto.encrypt(plaintext, aesKey)
        val payload = PushRequestBody(syncId, ciphertext, iv, blob.updatedAt)
        val bodyStr = json.encodeToString(PushRequestBody.serializer(), payload)
        val request = Request.Builder()
            .url("$apiBaseUrl/api/push")
            .post(bodyStr.toRequestBody(JSON_MEDIA_TYPE))
            .build()
        val responseBody = execute(request)
        json.decodeFromString(PushResponse.serializer(), responseBody).applied
    }

    /**
     * Mirrors SyncClient.swift's prependToday: pull the freshest server
     * state, prepend blockText to dateKey's entry within that fresh blob,
     * then push. If the push is rejected because another device wrote in
     * between, re-pull and retry — this device is just one more "sync
     * client" writing to the same blob, following the same last-write-wins
     * protocol the web app uses between browsers.
     */
    suspend fun prependToday(blockText: String, dateKey: String = todayDateKey(), maxAttempts: Int = 3) {
        var lastError: Exception = SyncRejectedException()
        repeat(maxAttempts) {
            try {
                val (blob, serverUpdatedAt) = pull()
                val current = blob.entries[dateKey] ?: "# "
                val trimmed = current.trim()
                val base = if (trimmed.isEmpty() || trimmed == "#") "" else current
                val next = if (base.isEmpty()) blockText else "$blockText\n$base"
                val entries = blob.entries.toMutableMap().apply { put(dateKey, next) }

                val now = Instant.now()
                val bumped = serverUpdatedAt?.let { maxOf(now, it.plusMillis(1)) } ?: now
                val nextBlob = blob.copy(version = 1, updatedAt = nowJsIso(bumped), entries = entries)

                if (push(nextBlob)) return
                lastError = SyncRejectedException()
            } catch (e: Exception) {
                lastError = e
            }
        }
        throw lastError
    }

    private fun execute(request: Request): String {
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
            return response.body?.string() ?: throw IOException("empty response body")
        }
    }
}

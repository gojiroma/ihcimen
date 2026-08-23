package com.ihcimen.android.sync

import com.ihcimen.android.data.AppDatabase
import com.ihcimen.android.data.EntryEntity
import com.ihcimen.android.data.SyncMetaEntity
import com.ihcimen.android.settings.SeedStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.OffsetDateTime

/**
 * Mirrors index.html's SYNC_CHANNELS.entries handling (pullAndMergeChannel /
 * doSyncPushChannel / handlePushConflict): the whole "entries" blob is
 * compared and replaced as one unit keyed on contentUpdatedAt
 * (last-write-wins), never merged field-by-field. Bridges SyncClient (wire
 * protocol) and Room (local cache).
 */
class SyncManager(
    private val db: AppDatabase,
    private val seedStore: SeedStore,
) {
    sealed class SyncOutcome {
        object NotConfigured : SyncOutcome()
        object UpToDate : SyncOutcome()
        object AppliedServer : SyncOutcome()
        object PushedLocal : SyncOutcome()
        data class Conflict(val serverBlob: EntriesBlob, val serverUpdatedAt: String) : SyncOutcome()
        data class Failed(val message: String) : SyncOutcome()
    }

    private suspend fun client(): SyncClient? {
        val seed = seedStore.getSeed() ?: return null
        return SyncClient(seedStore.getApiBaseUrl(), seed)
    }

    suspend fun fullSync(): SyncOutcome = withContext(Dispatchers.IO) {
        val client = client() ?: return@withContext SyncOutcome.NotConfigured
        try {
            val (serverBlob, serverUpdatedAt) = client.pull()
            val meta = db.syncMetaDao().get()
            val localUpdatedAt = meta?.contentUpdatedAt?.let { OffsetDateTime.parse(it).toInstant() }

            if (serverUpdatedAt != null && localUpdatedAt != null && serverUpdatedAt == localUpdatedAt) {
                return@withContext SyncOutcome.UpToDate
            }

            if (serverUpdatedAt != null && (localUpdatedAt == null || serverUpdatedAt.isAfter(localUpdatedAt))) {
                applyServerBlob(serverBlob, SyncClient.nowJsIso(serverUpdatedAt))
                return@withContext SyncOutcome.AppliedServer
            }

            if (localUpdatedAt == null) {
                // Nothing has ever been edited locally, and the server has
                // nothing newer either — there's nothing to push.
                return@withContext SyncOutcome.UpToDate
            }

            val localBlob = collectLocalBlob(meta!!)
            if (client.push(localBlob)) {
                return@withContext SyncOutcome.PushedLocal
            }

            // Rejected: someone else wrote first. Re-pull and compare
            // content — if it's actually identical, adopt the server
            // timestamp silently (mirrors handlePushConflict's
            // stableStringify short-circuit); otherwise surface a conflict
            // for the user to resolve, same choice the web app offers.
            val (freshServerBlob, freshServerUpdatedAt) = client.pull()
            if (freshServerUpdatedAt == null) {
                return@withContext SyncOutcome.Failed("pull after reject returned nothing")
            }
            val freshUpdatedAtIso = SyncClient.nowJsIso(freshServerUpdatedAt)
            if (contentEquals(freshServerBlob, localBlob)) {
                db.syncMetaDao().upsert(meta.copy(contentUpdatedAt = freshUpdatedAtIso))
                return@withContext SyncOutcome.UpToDate
            }
            SyncOutcome.Conflict(freshServerBlob, freshUpdatedAtIso)
        } catch (e: Exception) {
            SyncOutcome.Failed(e.message ?: e.toString())
        }
    }

    /** Returns whether the local content was successfully pushed; false (never throws) on any failure, so the caller can leave the conflict open to retry. */
    suspend fun resolveConflictKeepLocal(serverUpdatedAt: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val client = client() ?: return@withContext false
            val meta = db.syncMetaDao().get() ?: return@withContext false
            // Bump strictly past the server's timestamp so this push is
            // unambiguously accepted, matching the web app's conflict dialog.
            val bumped = maxOf(Instant.now(), OffsetDateTime.parse(serverUpdatedAt).toInstant().plusSeconds(1))
            val bumpedIso = SyncClient.nowJsIso(bumped)
            val bumpedMeta = meta.copy(contentUpdatedAt = bumpedIso)
            db.syncMetaDao().upsert(bumpedMeta)
            client.push(collectLocalBlob(bumpedMeta))
        } catch (e: Exception) {
            false
        }
    }

    /** Returns whether the server's content was successfully applied locally; false (never throws) on any failure. */
    suspend fun resolveConflictKeepServer(serverBlob: EntriesBlob, serverUpdatedAt: String): Boolean =
        withContext(Dispatchers.IO) {
            try {
                applyServerBlob(serverBlob, serverUpdatedAt)
                true
            } catch (e: Exception) {
                false
            }
        }

    /**
     * Mirrors TodayH1's PendingQueue flush: applies queued widget captures
     * to the freshest server state (not the possibly-stale local cache),
     * oldest first, in a single pull-then-push cycle, retrying against a
     * fresh pull if the push is rejected.
     */
    suspend fun flushPendingCaptures(): Boolean = withContext(Dispatchers.IO) {
        val client = client() ?: return@withContext false
        val pending = db.pendingCaptureDao().getAllOrdered()
        if (pending.isEmpty()) return@withContext true

        repeat(3) {
            try {
                val (blob, serverUpdatedAt) = client.pull()
                val entries = blob.entries.toMutableMap()
                for (p in pending) {
                    val current = entries[p.dateKey] ?: "# "
                    val trimmed = current.trim()
                    val base = if (trimmed.isEmpty() || trimmed == "#") "" else current
                    entries[p.dateKey] = if (base.isEmpty()) p.text else "${p.text}\n$base"
                }
                val now = Instant.now()
                val bumped = serverUpdatedAt?.let { maxOf(now, it.plusMillis(1)) } ?: now
                val nextBlob = blob.copy(version = 1, updatedAt = SyncClient.nowJsIso(bumped), entries = entries)

                if (client.push(nextBlob)) {
                    applyServerBlob(nextBlob, nextBlob.updatedAt)
                    db.pendingCaptureDao().deleteByIds(pending.map { it.id })
                    return@withContext true
                }
            } catch (e: Exception) {
                // fall through to retry
            }
        }
        false
    }

    private suspend fun applyServerBlob(blob: EntriesBlob, updatedAtIso: String) {
        db.entryDao().clearAll()
        db.entryDao().upsertAll(blob.entries.map { (dateKey, content) -> EntryEntity(dateKey, content) })
        db.syncMetaDao().upsert(SyncMetaEntity(contentUpdatedAt = updatedAtIso, h1ShortcutsJson = blob.h1Shortcuts))
    }

    private suspend fun collectLocalBlob(meta: SyncMetaEntity): EntriesBlob {
        val entries = db.entryDao().getAll().associate { it.dateKey to it.content }
        return EntriesBlob(
            version = 1,
            updatedAt = meta.contentUpdatedAt ?: SyncClient.nowJsIso(),
            entries = entries,
            h1Shortcuts = meta.h1ShortcutsJson,
        )
    }

    private fun contentEquals(a: EntriesBlob, b: EntriesBlob): Boolean =
        a.entries == b.entries && a.h1Shortcuts == b.h1Shortcuts
}

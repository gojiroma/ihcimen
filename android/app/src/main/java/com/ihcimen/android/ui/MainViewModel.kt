package com.ihcimen.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ihcimen.android.crypto.SyncCrypto
import com.ihcimen.android.data.AppDatabase
import com.ihcimen.android.data.EntryEntity
import com.ihcimen.android.data.SyncMetaEntity
import com.ihcimen.android.settings.SeedStore
import com.ihcimen.android.sync.SyncClient
import com.ihcimen.android.sync.SyncManager
import com.ihcimen.android.sync.SyncWorker
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val db = AppDatabase.get(application)
    private val seedStore = SeedStore(application)
    private val syncManager = SyncManager(db, seedStore)

    val entryDao get() = db.entryDao()
    val pendingCaptureDao get() = db.pendingCaptureDao()
    val syncMetaDao get() = db.syncMetaDao()

    private val _isSyncing = MutableStateFlow(false)
    val isSyncing: StateFlow<Boolean> = _isSyncing.asStateFlow()

    private val _conflict = MutableStateFlow<SyncManager.SyncOutcome.Conflict?>(null)
    val conflict: StateFlow<SyncManager.SyncOutcome.Conflict?> = _conflict.asStateFlow()

    private val _syncError = MutableStateFlow<String?>(null)
    val syncError: StateFlow<String?> = _syncError.asStateFlow()

    suspend fun getSeed(): String? = seedStore.getSeed()
    suspend fun getApiBaseUrl(): String = seedStore.getApiBaseUrl()

    fun enableSync() {
        viewModelScope.launch {
            if (seedStore.getSeed() == null) seedStore.setSeed(SyncCrypto.generateSeed())
            syncNow()
        }
    }

    fun importSeed(seed: String) {
        val trimmed = seed.trim()
        if (trimmed.isEmpty()) return
        viewModelScope.launch {
            seedStore.setSeed(trimmed)
            syncNow()
        }
    }

    fun disableSync() {
        viewModelScope.launch { seedStore.clearSeed() }
    }

    fun setApiBaseUrl(url: String) {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) return
        viewModelScope.launch { seedStore.setApiBaseUrl(trimmed) }
    }

    /** Saves an edit locally and marks it dirty; SyncWorker picks it up right away if online. */
    fun saveEntry(dateKey: String, content: String) {
        viewModelScope.launch {
            db.entryDao().upsert(EntryEntity(dateKey, content))
            val meta = db.syncMetaDao().get() ?: SyncMetaEntity()
            db.syncMetaDao().upsert(meta.copy(contentUpdatedAt = SyncClient.nowJsIso()))
            SyncWorker.enqueueImmediate(getApplication())
        }
    }

    fun syncNow() {
        viewModelScope.launch {
            _isSyncing.value = true
            _syncError.value = null
            when (val outcome = syncManager.fullSync()) {
                is SyncManager.SyncOutcome.Conflict -> _conflict.value = outcome
                is SyncManager.SyncOutcome.Failed -> _syncError.value = outcome.message
                else -> _conflict.value = null
            }
            syncManager.flushPendingCaptures()
            _isSyncing.value = false
        }
    }

    fun resolveConflictKeepLocal() {
        val c = _conflict.value ?: return
        viewModelScope.launch {
            // Leave the conflict dialog up on failure (e.g. offline) so the user can retry.
            if (syncManager.resolveConflictKeepLocal(c.serverUpdatedAt)) _conflict.value = null
        }
    }

    fun resolveConflictKeepServer() {
        val c = _conflict.value ?: return
        viewModelScope.launch {
            if (syncManager.resolveConflictKeepServer(c.serverBlob, c.serverUpdatedAt)) _conflict.value = null
        }
    }
}

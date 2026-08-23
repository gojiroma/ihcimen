package com.ihcimen.android.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkRequest
import androidx.work.WorkerParameters
import com.ihcimen.android.data.AppDatabase
import com.ihcimen.android.settings.SeedStore
import java.util.concurrent.TimeUnit

/**
 * Flushes any queued widget captures and refreshes the local cache from the
 * server. Runs periodically in the background and also as an expedited
 * one-off right after a quick capture or a manual edit, so writes get out
 * quickly when online but are never lost when offline.
 */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val db = AppDatabase.get(applicationContext)
        val seedStore = SeedStore(applicationContext)
        val manager = SyncManager(db, seedStore)

        val flushed = manager.flushPendingCaptures()
        val syncOutcome = manager.fullSync()
        val syncFailed = syncOutcome is SyncManager.SyncOutcome.Failed
        return if (flushed && !syncFailed) Result.success() else Result.retry()
    }

    companion object {
        private const val PERIODIC_NAME = "ihcimen_periodic_sync"
        private const val IMMEDIATE_NAME = "ihcimen_immediate_sync"
        private val NETWORK_CONSTRAINTS = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        fun schedulePeriodic(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(NETWORK_CONSTRAINTS)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, WorkRequest.MIN_BACKOFF_MILLIS, TimeUnit.MILLISECONDS)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        fun enqueueImmediate(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                .setConstraints(NETWORK_CONSTRAINTS)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniqueWork(IMMEDIATE_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
        }
    }
}

package com.ihcimen.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * A widget quick-capture that couldn't be pushed yet (offline, server
 * error, repeated conflicts). Kept here so it is never lost — flushed by
 * SyncWorker on the next connectivity window. dateKey is fixed at capture
 * time (not recomputed at flush time), so an overnight offline capture
 * still lands on the day it was actually written, not the day it happens
 * to get flushed.
 */
@Entity(tableName = "pending_captures")
data class PendingCaptureEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val dateKey: String,
    val text: String,
    val capturedAtEpochMs: Long,
)

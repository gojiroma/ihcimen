package com.ihcimen.android.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface PendingCaptureDao {
    @Insert
    suspend fun insert(entry: PendingCaptureEntity): Long

    @Query("SELECT * FROM pending_captures ORDER BY capturedAtEpochMs ASC")
    suspend fun getAllOrdered(): List<PendingCaptureEntity>

    @Query("SELECT * FROM pending_captures ORDER BY capturedAtEpochMs ASC")
    fun observeAll(): Flow<List<PendingCaptureEntity>>

    @Query("SELECT COUNT(*) FROM pending_captures")
    fun observeCount(): Flow<Int>

    @Query("DELETE FROM pending_captures WHERE id IN (:ids)")
    suspend fun deleteByIds(ids: List<Long>)
}

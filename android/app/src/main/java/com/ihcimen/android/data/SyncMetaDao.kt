package com.ihcimen.android.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface SyncMetaDao {
    @Query("SELECT * FROM sync_meta WHERE id = 0")
    suspend fun get(): SyncMetaEntity?

    @Query("SELECT * FROM sync_meta WHERE id = 0")
    fun observe(): Flow<SyncMetaEntity?>

    @Upsert
    suspend fun upsert(meta: SyncMetaEntity)
}

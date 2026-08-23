package com.ihcimen.android.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface EntryDao {
    @Query("SELECT * FROM entries WHERE dateKey = :dateKey")
    fun observe(dateKey: String): Flow<EntryEntity?>

    @Query("SELECT * FROM entries ORDER BY dateKey DESC LIMIT :limit")
    fun observeRecent(limit: Int): Flow<List<EntryEntity>>

    @Query("SELECT COUNT(*) FROM entries")
    suspend fun count(): Int

    @Query("SELECT * FROM entries")
    suspend fun getAll(): List<EntryEntity>

    @Upsert
    suspend fun upsert(entry: EntryEntity)

    @Upsert
    suspend fun upsertAll(entries: List<EntryEntity>)

    @Query("DELETE FROM entries")
    suspend fun clearAll()
}

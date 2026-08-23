package com.ihcimen.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/** One day's raw markdown, keyed the same way as localStorage's "YYYY-MM-DD" keys. */
@Entity(tableName = "entries")
data class EntryEntity(
    @PrimaryKey val dateKey: String,
    val content: String,
)

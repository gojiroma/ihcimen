package com.ihcimen.android.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Single-row table (id is always 0) tracking the "entries" channel's local
 * state: when it was last actually edited (drives last-write-wins, mirrors
 * localStorage's entriesContentUpdatedAt) and the h1Shortcuts blob that
 * rides along with it so it round-trips through sync untouched.
 */
@Entity(tableName = "sync_meta")
data class SyncMetaEntity(
    @PrimaryKey val id: Int = 0,
    val contentUpdatedAt: String? = null,
    val h1ShortcutsJson: String = "[]",
)

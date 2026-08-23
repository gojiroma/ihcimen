package com.ihcimen.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ihcimen.android.R
import com.ihcimen.android.sync.SyncClient
import kotlinx.coroutines.delay

@Composable
fun TodayScreen(viewModel: MainViewModel, modifier: Modifier = Modifier) {
    val dateKey = remember { SyncClient.todayDateKey() }
    val entry by viewModel.entryDao.observe(dateKey).collectAsStateWithLifecycle(initialValue = null)
    val isSyncing by viewModel.isSyncing.collectAsStateWithLifecycle()
    val conflict by viewModel.conflict.collectAsStateWithLifecycle()

    var value by remember { mutableStateOf<TextFieldValue?>(null) }

    // Load the stored content into the editor once (and whenever a sync
    // replaces it while the user hasn't started typing), without clobbering
    // in-progress edits on every Room emission.
    LaunchedEffect(entry?.content) {
        if (value == null) {
            val text = entry?.content ?: "# "
            value = TextFieldValue(text, TextRange(text.length))
        }
    }

    // Debounced autosave, mirroring the web app's maybeSyncPushChannel debounce.
    LaunchedEffect(value?.text) {
        val text = value?.text ?: return@LaunchedEffect
        delay(1200)
        if (text != (entry?.content ?: "# ")) {
            viewModel.saveEntry(dateKey, text)
        }
    }

    Column(modifier = modifier.fillMaxSize().padding(16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(dateKey, style = MaterialTheme.typography.titleMedium)
            if (isSyncing) {
                CircularProgressIndicator(modifier = Modifier.padding(4.dp))
            } else {
                TextButton(onClick = { viewModel.syncNow() }) {
                    Text(stringResource(R.string.today_sync_now))
                }
            }
        }

        val currentValue = value
        if (currentValue != null) {
            MarkdownTextField(
                value = currentValue,
                onValueChange = { value = it },
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = 12.dp),
                textStyle = MaterialTheme.typography.bodyLarge,
            )
        }
    }

    val activeConflict = conflict
    if (activeConflict != null) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text(stringResource(R.string.conflict_title)) },
            text = { Text(stringResource(R.string.conflict_message)) },
            confirmButton = {
                Button(onClick = { viewModel.resolveConflictKeepLocal() }) {
                    Text(stringResource(R.string.conflict_keep_local))
                }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.resolveConflictKeepServer() }) {
                    Text(stringResource(R.string.conflict_keep_server))
                }
            },
        )
    }
}

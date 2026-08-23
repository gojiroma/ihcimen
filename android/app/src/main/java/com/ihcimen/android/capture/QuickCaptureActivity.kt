package com.ihcimen.android.capture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.ihcimen.android.R
import com.ihcimen.android.data.AppDatabase
import com.ihcimen.android.data.PendingCaptureEntity
import com.ihcimen.android.sync.SyncClient
import com.ihcimen.android.sync.SyncWorker
import com.ihcimen.android.ui.MarkdownTextField
import com.ihcimen.android.ui.theme.IhcimenTheme
import kotlinx.coroutines.launch

/**
 * The floating "quick capture" screen the widget's "+" button opens.
 * Equivalent to TodayH1's CapturePanelController: a title starting at
 * "# " with the cursor right after it, saved as a queued capture that
 * SyncWorker prepends to today's page as soon as it can reach the server.
 */
class QuickCaptureActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            IhcimenTheme {
                Surface {
                    var value by remember { mutableStateOf(TextFieldValue("# ", TextRange(2))) }
                    Column(Modifier.padding(16.dp)) {
                        MarkdownTextField(
                            value = value,
                            onValueChange = { value = it },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(140.dp),
                            textStyle = MaterialTheme.typography.bodyLarge,
                        )
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 12.dp),
                            horizontalArrangement = Arrangement.End,
                        ) {
                            TextButton(onClick = { finish() }) {
                                Text(stringResource(R.string.capture_cancel))
                            }
                            TextButton(onClick = { submit(value.text) }) {
                                Text(stringResource(R.string.capture_save))
                            }
                        }
                    }
                }
            }
        }
    }

    private fun submit(text: String) {
        val trimmed = text.trim('\n', ' ')
        val hasTitle = trimmed.replace("#", "").trim().isNotEmpty()
        if (!hasTitle) return
        lifecycleScope.launch {
            val db = AppDatabase.get(applicationContext)
            db.pendingCaptureDao().insert(
                PendingCaptureEntity(
                    dateKey = SyncClient.todayDateKey(),
                    text = trimmed,
                    capturedAtEpochMs = System.currentTimeMillis(),
                ),
            )
            SyncWorker.enqueueImmediate(applicationContext)
            finish()
        }
    }
}

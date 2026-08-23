package com.ihcimen.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ihcimen.android.data.EntryEntity
import kotlinx.coroutines.delay

private const val RECENT_DAYS_LIMIT = 14

@Composable
fun RecentDaysScreen(viewModel: MainViewModel, modifier: Modifier = Modifier) {
    val recent by viewModel.entryDao.observeRecent(RECENT_DAYS_LIMIT)
        .collectAsStateWithLifecycle(initialValue = emptyList())
    var openedDateKey by remember { mutableStateOf<String?>(null) }

    val opened = openedDateKey
    if (opened != null) {
        val entry = recent.find { it.dateKey == opened }
        DayEditor(
            dateKey = opened,
            initialContent = entry?.content ?: "# ",
            viewModel = viewModel,
            onBack = { openedDateKey = null },
            modifier = modifier,
        )
        return
    }

    LazyColumn(modifier = modifier.fillMaxSize()) {
        items(recent, key = EntryEntity::dateKey) { entry ->
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { openedDateKey = entry.dateKey }
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                Text(entry.dateKey, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = entry.content.lineSequence().firstOrNull { it.isNotBlank() } ?: "",
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                )
            }
            HorizontalDivider()
        }
    }
}

@Composable
private fun DayEditor(
    dateKey: String,
    initialContent: String,
    viewModel: MainViewModel,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var value by remember(dateKey) {
        mutableStateOf(TextFieldValue(initialContent, TextRange(initialContent.length)))
    }

    androidx.compose.runtime.LaunchedEffect(value.text) {
        delay(1200)
        if (value.text != initialContent) {
            viewModel.saveEntry(dateKey, value.text)
        }
    }

    Column(modifier = modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = dateKey,
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .clickable(onClick = onBack)
                .padding(8.dp),
        )
        MarkdownTextField(
            value = value,
            onValueChange = { value = it },
            modifier = Modifier
                .fillMaxSize()
                .padding(top = 12.dp),
            textStyle = MaterialTheme.typography.bodyLarge,
        )
    }
}

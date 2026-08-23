package com.ihcimen.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.unit.dp
import com.ihcimen.android.R
import com.ihcimen.android.settings.SeedStore

@Composable
fun SettingsScreen(viewModel: MainViewModel, modifier: Modifier = Modifier) {
    var currentSeed by remember { mutableStateOf<String?>(null) }
    var apiBaseUrl by remember { mutableStateOf(SeedStore.DEFAULT_API_BASE_URL) }
    var pastedSeed by remember { mutableStateOf("") }
    var reloadKey by remember { mutableStateOf(0) }

    LaunchedEffect(reloadKey) {
        currentSeed = viewModel.getSeed()
        apiBaseUrl = viewModel.getApiBaseUrl()
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(16.dp),
    ) {
        val seed = currentSeed
        if (seed == null) {
            Text("同期は無効です", style = MaterialTheme.typography.bodyMedium)
            Button(
                onClick = {
                    viewModel.enableSync()
                    reloadKey++
                },
                modifier = Modifier.padding(top = 12.dp),
            ) {
                Text(stringResource(R.string.settings_sync_enable))
            }
        } else {
            Text(stringResource(R.string.settings_seed_label), style = MaterialTheme.typography.titleSmall)
            SelectionContainer {
                Text(seed, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
            }
            TextButton(
                onClick = {
                    viewModel.disableSync()
                    reloadKey++
                },
                modifier = Modifier.padding(top = 8.dp),
            ) {
                Text(stringResource(R.string.settings_sync_disable))
            }
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))

        Text(stringResource(R.string.settings_seed_hint), style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(
            value = pastedSeed,
            onValueChange = { pastedSeed = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            singleLine = true,
        )
        Button(
            onClick = {
                viewModel.importSeed(pastedSeed)
                pastedSeed = ""
                reloadKey++
            },
            modifier = Modifier.padding(top = 8.dp),
        ) {
            Text(stringResource(R.string.settings_seed_paste_save))
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))

        Text(stringResource(R.string.settings_api_url_label), style = MaterialTheme.typography.titleSmall)
        OutlinedTextField(
            value = apiBaseUrl,
            onValueChange = { apiBaseUrl = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            singleLine = true,
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = { viewModel.setApiBaseUrl(apiBaseUrl) }) {
                Text("保存")
            }
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))

        Button(onClick = { viewModel.syncNow() }) {
            Text(stringResource(R.string.today_sync_now))
        }
    }
}

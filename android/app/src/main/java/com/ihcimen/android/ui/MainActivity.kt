package com.ihcimen.android.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ihcimen.android.R
import com.ihcimen.android.ui.theme.IhcimenTheme

private enum class Screen { TODAY, RECENT, SETTINGS }

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            IhcimenTheme {
                Surface {
                    MainScreen(viewModel)
                }
            }
        }
    }
}

@Composable
private fun MainScreen(viewModel: MainViewModel) {
    var screen by remember { mutableStateOf(Screen.TODAY) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                // Text-only "icons" to avoid pulling in the separate
                // material-icons-extended artifact for three glyphs.
                NavigationBarItem(
                    selected = screen == Screen.TODAY,
                    onClick = { screen = Screen.TODAY },
                    icon = { Text("今") },
                    label = { Text(stringResource(R.string.nav_today)) },
                )
                NavigationBarItem(
                    selected = screen == Screen.RECENT,
                    onClick = { screen = Screen.RECENT },
                    icon = { Text("週") },
                    label = { Text(stringResource(R.string.nav_recent)) },
                )
                NavigationBarItem(
                    selected = screen == Screen.SETTINGS,
                    onClick = { screen = Screen.SETTINGS },
                    icon = { Text("設") },
                    label = { Text(stringResource(R.string.nav_settings)) },
                )
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        when (screen) {
            Screen.TODAY -> TodayScreen(viewModel, modifier)
            Screen.RECENT -> RecentDaysScreen(viewModel, modifier)
            Screen.SETTINGS -> SettingsScreen(viewModel, modifier)
        }
    }
}

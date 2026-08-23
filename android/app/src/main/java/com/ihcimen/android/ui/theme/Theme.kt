package com.ihcimen.android.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Matches manifest.json's theme_color (#3b82c4) for the web app.
private val BrandPrimary = Color(0xFF3B82C4)

private val LightColors = lightColorScheme(primary = BrandPrimary)
private val DarkColors = darkColorScheme(primary = BrandPrimary)

@Composable
fun IhcimenTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) DarkColors else LightColors
    MaterialTheme(colorScheme = colors, content = content)
}

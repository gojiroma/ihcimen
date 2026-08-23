package com.ihcimen.android.widget

import android.content.Context
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Row
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.text.Text
import androidx.glance.unit.ColorProvider
import com.ihcimen.android.capture.QuickCaptureActivity

/**
 * Home-screen widget: the page title plus a single "+" button that opens
 * QuickCaptureActivity, the Android equivalent of TodayH1's Cmd-Cmd
 * capture panel.
 *
 * Kept deliberately simple (fixed colors, no GlanceTheme/material3
 * interop) since the Glance API surface has moved around across versions
 * more than most of Jetpack — if Android Studio's quick-fixes suggest a
 * renamed import here, that's expected; see android/README.md.
 */
class TodayWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent {
            Row(
                modifier = GlanceModifier
                    .fillMaxWidth()
                    .background(ColorProvider(day = Color.White, night = Color(0xFF1E1E1E)))
                    .padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(text = "今日のページ")
                Box(
                    modifier = GlanceModifier
                        .size(40.dp)
                        .background(ColorProvider(day = Color(0xFF3B82C4), night = Color(0xFF3B82C4)))
                        .clickable(actionStartActivity<QuickCaptureActivity>()),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "+",
                        style = androidx.glance.text.TextStyle(
                            color = ColorProvider(day = Color.White, night = Color.White),
                        ),
                    )
                }
            }
        }
    }
}

class TodayWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = TodayWidget()
}

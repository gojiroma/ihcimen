package com.ihcimen.android

import android.app.Application
import com.ihcimen.android.sync.SyncWorker

class IhcimenApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        SyncWorker.schedulePeriodic(this)
    }
}

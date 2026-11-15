package com.synclayer.app

import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.os.Build
import android.provider.MediaStore
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

/** Periodically uploads new photos and videos to "Camera Uploads" on the active server. Resumes after any failure. */
class CameraBackupWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("synclayer", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("camera_backup", false)) return Result.success()
        if (!hasPermission(applicationContext)) return Result.success()
        val cm = applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        if (prefs.getBoolean("camera_wifi_only", true) && cm.isActiveNetworkMetered) return Result.retry()
        val base = Servers.activeUrl(prefs)
        val tok = prefs.getString("token:$base", "") ?: ""
        if (base.isEmpty() || tok.isEmpty()) return Result.success()      // not signed in yet: nothing to do
        val key = "camera_last:$base"
        if (!prefs.contains("$key:images")) {      // first run for this server: new photos only, unless the person asked for everything
            val from = if (prefs.getBoolean("camera_existing", false)) 0L else System.currentTimeMillis() / 1000
            prefs.edit().putLong("$key:images", from).putLong("$key:video", from).apply()
        }
        return try {
            val root = Uploader.defaultRoot(base, tok)
            val cr = applicationContext.contentResolver
            for ((label, table) in listOf("images" to MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "video" to MediaStore.Video.Media.EXTERNAL_CONTENT_URI)) {
                val last = prefs.getLong("$key:$label", 0L)
                val cols = arrayOf(MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE, MediaStore.MediaColumns.DATE_ADDED)
                val rows = ArrayList<LongArray>()
                val names = ArrayList<String>()
                cr.query(table, cols, "${MediaStore.MediaColumns.DATE_ADDED} > ?", arrayOf(last.toString()), "${MediaStore.MediaColumns.DATE_ADDED} ASC")?.use { c ->
                    while (c.moveToNext()) {
                        rows.add(longArrayOf(c.getLong(0), c.getLong(2), c.getLong(3)))
                        names.add(c.getString(1) ?: "media")
                    }
                }
                for ((i, r) in rows.withIndex()) {
                    val uri = android.content.ContentUris.withAppendedId(table, r[0])
                    val stamp = java.text.SimpleDateFormat("yyyy/MM", java.util.Locale.US).format(java.util.Date(r[2] * 1000))
                    Uploader.upload(cr, base, tok, root, uri, "Camera Uploads/$stamp/${names[i]}", r[1], r[2].toDouble())
                    prefs.edit().putLong("$key:$label", r[2]).apply()     // progress survives a failure half way through
                }
            }
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        fun hasPermission(c: Context): Boolean = if (Build.VERSION.SDK_INT >= 33)
            ContextCompat.checkSelfPermission(c, android.Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED
        else ContextCompat.checkSelfPermission(c, android.Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }
}

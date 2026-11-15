package com.synclayer.app

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Resumable uploads to the server, shared by "Share to Synclayer" and camera backup. */
object Uploader {
    val http: OkHttpClient by lazy { OkHttpClient.Builder().readTimeout(120, TimeUnit.SECONDS).writeTimeout(120, TimeUnit.SECONDS).build() }
    private val json = "application/json".toMediaType()

    fun call(r: Request): String = http.newCall(r).execute().use { resp ->
        val body = resp.body?.string() ?: ""
        if (!resp.isSuccessful) throw RuntimeException("HTTP ${resp.code}")
        body
    }

    /** The folder uploads go to: the signed-in person's own drive. */
    fun defaultRoot(base: String, tok: String): String {
        val me = JSONObject(call(Request.Builder().url("$base/api/me").header("Authorization", "Bearer $tok").build()))
        return me.optString("default_root").ifEmpty {
            JSONObject(call(Request.Builder().url("$base/api/roots").header("Authorization", "Bearer $tok").build())).getJSONArray("roots").getString(0)
        }
    }

    fun nameAndSize(cr: ContentResolver, uri: Uri): Pair<String, Long> {
        var name = "file"
        var size = -1L
        cr.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { name = c.getString(it) ?: name }
                c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 }?.let { size = c.getLong(it) }
            }
        }
        if (size < 0) size = cr.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: 0L
        return name to size
    }

    /** Uploads [uri] to [remotePath] (relative to [rootName]); picks up where an interrupted upload stopped. */
    fun upload(cr: ContentResolver, base: String, tok: String, rootName: String, uri: Uri, remotePath: String, size: Long, mtimeSec: Double) {
        val start = JSONObject().put("root", rootName).put("path", remotePath).put("size", size).put("mtime", mtimeSec)
        val st = JSONObject(call(Request.Builder().url("$base/api/uploads").header("Authorization", "Bearer $tok")
            .post(start.toString().toRequestBody(json)).build()))
        val id = st.getString("id")
        var off = st.getLong("offset")
        val chunk = 4 * 1024 * 1024
        cr.openInputStream(uri)!!.use { input ->
            var skipped = 0L
            while (skipped < off) { val n = input.skip(off - skipped); if (n <= 0) break; skipped += n }
            do {
                val want = minOf(chunk.toLong(), size - off).toInt().coerceAtLeast(0)
                val buf = ByteArray(want)
                var got = 0
                while (got < want) { val n = input.read(buf, got, want - got); if (n < 0) break; got += n }
                val body = buf.copyOf(got).toRequestBody("application/octet-stream".toMediaType())
                val r = JSONObject(call(Request.Builder().url("$base/api/uploads/$id?root=$rootName")
                    .header("Authorization", "Bearer $tok").header("Upload-Offset", off.toString()).patch(body).build()))
                off = r.getLong("offset")
            } while (off < size)
        }
    }
}

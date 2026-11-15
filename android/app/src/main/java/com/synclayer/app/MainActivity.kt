package com.synclayer.app

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.*
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Synclayer for Android: the server's web app (files, previews for images / video / audio / PDF, code editor,
 * sharing, admin) in a native shell with full-screen video, back-button navigation, file upload through the
 * system picker, downloads, and "Share to Synclayer" from any other app.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var refresh: SwipeRefreshLayout
    private lateinit var root: FrameLayout
    private var chooser: ValueCallback<Array<Uri>>? = null
    private var customView: View? = null
    private var customCb: WebChromeClient.CustomViewCallback? = null
    private var pageReady = false
    private var pendingShare: List<Uri> = emptyList()
    private val prefs by lazy { getSharedPreferences("synclayer", Context.MODE_PRIVATE) }

    private var welcome: View? = null
    private fun server(): String = Servers.activeUrl(prefs)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        root = FrameLayout(this)
        web = WebView(this)
        // Pull-to-refresh would fight with scrolling inside the web app (the web app has its own refresh and live updates).
        refresh = SwipeRefreshLayout(this).apply { addView(web); isEnabled = false }
        root.addView(refresh, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        setContentView(root)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true            // the web app keeps its session in localStorage
            allowFileAccess = false
            allowContentAccess = false
            mediaPlaybackRequiresUserGesture = false
            setSupportZoom(false)
            userAgentString = userAgentString + " SynclayerAndroid/" + BuildConfig.VERSION_NAME
        }
        CookieManager.getInstance().setAcceptCookie(true)
        web.addJavascriptInterface(AppBridge(), "SynclayerApp")

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean {
                val u = r.url.toString()
                if (u.startsWith(server())) return false       // stay inside the app
                startActivity(Intent(Intent.ACTION_VIEW, r.url)) // anything else opens in the browser
                return true
            }
            override fun onPageFinished(v: WebView, url: String) {
                pageReady = true
                rememberToken()
                if (pendingShare.isNotEmpty()) { val l = pendingShare; pendingShare = emptyList(); uploadShared(l) }
            }
            override fun onReceivedError(v: WebView, r: WebResourceRequest, e: WebResourceError) {
                if (r.isForMainFrame) showOffline(e.description?.toString() ?: "error")
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(w: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null)
                chooser = cb
                return try {
                    @Suppress("DEPRECATION")
                    startActivityForResult(p.createIntent(), 42); true
                } catch (e: Exception) { chooser = null; false }
            }
            // full-screen video playback
            override fun onShowCustomView(view: View, callback: CustomViewCallback) {
                if (customView != null) { callback.onCustomViewHidden(); return }
                customView = view; customCb = callback
                root.addView(view, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                refresh.visibility = View.GONE
                window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                @Suppress("DEPRECATION")
                window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_FULLSCREEN or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            }
            override fun onHideCustomView() { leaveFullscreen() }
        }
        web.setDownloadListener { url, ua, disp, mime, _ ->
            val name = URLUtil.guessFileName(url, disp, mime)
            val req = DownloadManager.Request(Uri.parse(url))
                .setMimeType(mime).addRequestHeader("User-Agent", ua)
                .addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            Toast.makeText(this, "Downloading $name", Toast.LENGTH_SHORT).show()
        }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (customView != null) { leaveFullscreen(); return }
                // close a dialog / go up one folder inside the web app first, then leave the app
                web.evaluateJavascript(BACK_JS) { r -> if (r != "\"x\"") finish() }
            }
        })

        if (server().isEmpty()) showWelcome(false) else load()
        handleIntent(intent)
    }

    private fun leaveFullscreen() {
        val v = customView ?: return
        root.removeView(v); customView = null
        customCb?.onCustomViewHidden(); customCb = null
        refresh.visibility = View.VISIBLE
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleIntent(intent) }

    private fun handleIntent(i: Intent?) {
        val uris: List<Uri> = when (i?.action) {
            Intent.ACTION_SEND -> listOfNotNull(@Suppress("DEPRECATION") i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
            Intent.ACTION_SEND_MULTIPLE -> @Suppress("DEPRECATION") (i.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM) ?: arrayListOf())
            else -> emptyList()
        }
        if (uris.isEmpty()) return
        i?.action = null
        if (pageReady) uploadShared(uris) else pendingShare = uris
    }

    private fun online(): Boolean {
        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        return cm.activeNetworkInfo?.isConnected == true
    }

    private fun load() {
        if (!online()) { showOffline("no network"); return }
        web.loadUrl(server())
    }

    private fun showOffline(why: String) {
        refresh.isRefreshing = false
        AlertDialog.Builder(this).setTitle("Cannot reach the server")
            .setMessage("${server().ifEmpty { "(no server set)" }}\n\n$why")
            .setPositiveButton("Retry") { _, _ -> load() }
            .setNeutralButton("Servers") { _, _ -> showServers() }
            .setNegativeButton("Close", null).show()
    }

    // ---------------------------------------------------------------- servers (the app ships with none)
    inner class AppBridge {
        @JavascriptInterface fun servers() { runOnUiThread { showServers() } }
        @JavascriptInterface fun backup() { runOnUiThread { showBackup() } }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    /** First run, or "add a server": a full-screen page asking for the server address. */
    private fun showWelcome(adding: Boolean) {
        welcome?.let { root.removeView(it) }
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setPadding(dp(32), dp(32), dp(32), dp(32))
            val tv = android.util.TypedValue()
            theme.resolveAttribute(android.R.attr.colorBackground, tv, true)
            setBackgroundColor(tv.data)
            isClickable = true
        }
        val logo = android.widget.ImageView(this).apply { setImageResource(R.mipmap.ic_launcher) }
        col.addView(logo, LinearLayout.LayoutParams(dp(84), dp(84)))
        col.addView(TextView(this).apply { text = if (adding) "Add a server" else "Connect to your server"; textSize = 24f; setPadding(0, dp(18), 0, dp(6)); gravity = android.view.Gravity.CENTER })
        col.addView(TextView(this).apply { text = "Enter the address of your Synclayer server, or a friend's. You sign in on the next screen."; gravity = android.view.Gravity.CENTER; alpha = .7f })
        val input = EditText(this).apply { hint = "https://files.example.com"; inputType = InputType.TYPE_TEXT_VARIATION_URI; setSingleLine() }
        col.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(24) })
        val go = Button(this).apply { text = "Connect" }
        col.addView(go, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(12) })
        if (adding) col.addView(Button(this).apply { text = "Cancel"; setOnClickListener { welcome?.let { root.removeView(it) }; welcome = null } })
        go.setOnClickListener {
            val u = Servers.clean(input.text.toString())
            if (u.isEmpty()) { input.error = "Enter an address"; return@setOnClickListener }
            Servers.add(prefs, u)
            welcome?.let { root.removeView(it) }; welcome = null
            pageReady = false
            load()
        }
        root.addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        welcome = col
    }

    private fun showServers() {
        val list = Servers.list(prefs)
        val act = prefs.getInt("active", 0)
        val labels = list.mapIndexed { i, e -> (if (i == act) "● " else "○ ") + e.url.substringAfter("://") } + "+  Add a server…"
        AlertDialog.Builder(this).setTitle("Servers").setItems(labels.toTypedArray()) { _, i ->
            if (i == list.size) showWelcome(true)
            else { Servers.save(prefs, list, i); pageReady = false; load() }
        }.setNeutralButton("Forget current") { _, _ ->
            AlertDialog.Builder(this).setTitle("Forget this server?").setMessage(server().substringAfter("://") + "\nNothing is deleted on the server.")
                .setPositiveButton("Forget") { _, _ ->
                    Servers.remove(prefs, act); web.loadUrl("about:blank")
                    if (Servers.list(prefs).isEmpty()) showWelcome(false) else load()
                }.setNegativeButton("Cancel", null).show()
        }.setNegativeButton("Close", null).show()
    }

    /** The background photo backup cannot read the web view's storage, so keep a copy of the sign-in token per server. */
    private fun rememberToken() {
        val base = server()
        web.evaluateJavascript("(function(){return localStorage.getItem('sl_token')||sessionStorage.getItem('sl_token')||''})()") { raw ->
            val tok = raw?.trim('"') ?: ""
            if (tok.isNotEmpty()) prefs.edit().putString("token:$base", tok).apply()
        }
    }

    // ---------------------------------------------------------------- camera backup
    private fun showBackup() {
        val on = prefs.getBoolean("camera_backup", false)
        val items = arrayOf("Back up photos and videos", "Only on Wi-Fi", "Include photos already on this phone")
        val checked = booleanArrayOf(on, prefs.getBoolean("camera_wifi_only", true), prefs.getBoolean("camera_existing", false))
        AlertDialog.Builder(this).setTitle("Camera backup")
            .setMultiChoiceItems(items, checked) { _, i, v -> checked[i] = v }
            .setPositiveButton("Save") { _, _ ->
                prefs.edit().putBoolean("camera_backup", checked[0]).putBoolean("camera_wifi_only", checked[1]).putBoolean("camera_existing", checked[2]).apply()
                if (checked[0]) {
                    rememberToken()
                    if (!CameraBackupWorker.hasPermission(this)) {
                        val perms = if (android.os.Build.VERSION.SDK_INT >= 33) arrayOf(android.Manifest.permission.READ_MEDIA_IMAGES, android.Manifest.permission.READ_MEDIA_VIDEO)
                                    else arrayOf(android.Manifest.permission.READ_EXTERNAL_STORAGE)
                        requestPermissions(perms, 77)
                    }
                    scheduleBackup(true)
                    Toast.makeText(this, "Camera backup is on. New photos go to Camera Uploads.", Toast.LENGTH_LONG).show()
                } else scheduleBackup(false)
            }.setNegativeButton("Cancel", null).show()
    }

    private fun scheduleBackup(on: Boolean) {
        val wm = WorkManager.getInstance(this)
        if (!on) { wm.cancelUniqueWork("camera-backup"); return }
        val req = PeriodicWorkRequestBuilder<CameraBackupWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
        wm.enqueueUniquePeriodicWork("camera-backup", ExistingPeriodicWorkPolicy.UPDATE, req)
    }

    // ---------------------------------------------------------------- share to Synclayer
    private fun uploadShared(uris: List<Uri>) {
        web.evaluateJavascript("(function(){return localStorage.getItem('sl_token')||sessionStorage.getItem('sl_token')||''})()") { raw ->
            val tok = raw?.trim('"') ?: ""
            if (tok.isEmpty()) { Toast.makeText(this, "Sign in to Synclayer first, then share again", Toast.LENGTH_LONG).show(); return@evaluateJavascript }
            Toast.makeText(this, "Uploading ${uris.size} file(s)…", Toast.LENGTH_SHORT).show()
            Thread {
                var ok = 0
                var last = ""
                try {
                    val base = server()
                    val rootName = Uploader.defaultRoot(base, tok)
                    for (u in uris) {
                        try {
                            val (name, size) = Uploader.nameAndSize(contentResolver, u)
                            Uploader.upload(contentResolver, base, tok, rootName, u, name, size, System.currentTimeMillis() / 1000.0); ok++
                        } catch (e: Exception) { last = e.message ?: "error" }
                    }
                } catch (e: Exception) { last = e.message ?: "error" }
                runOnUiThread {
                    Toast.makeText(this, if (ok == uris.size) "Uploaded $ok file(s)" else "Uploaded $ok of ${uris.size}: $last", Toast.LENGTH_LONG).show()
                    web.evaluateJavascript("window.refresh&&refresh(true)", null)
                }
            }.start()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == 42) {
            chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
            chooser = null
        } else super.onActivityResult(requestCode, resultCode, data)
    }

    override fun onCreateOptionsMenu(menu: android.view.Menu): Boolean = false

    override fun onKeyLongPress(keyCode: Int, event: android.view.KeyEvent?): Boolean {
        if (keyCode == android.view.KeyEvent.KEYCODE_MENU) { showServers(); return true }
        return super.onKeyLongPress(keyCode, event)
    }

    override fun onPause() { web.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); web.onResume() }

    companion object {
        /** Returns "x" when the web app handled "back" itself (closed a dialog, went up a folder / to Files). */
        private const val BACK_JS = "(function(){try{var d=document.querySelector('dialog[open]');if(d){var b=d.querySelector('#edClose,#pvClose,[data-close]');if(b){b.click()}else{d.close()}return 'x'}" +
            "if(typeof S!=='undefined'){if(S.view==='files'&&S.path){go('files',parentOf(S.path));return 'x'}if(S.view!=='files'){go('files','');return 'x'}}}catch(e){}return ''})()"
    }
}

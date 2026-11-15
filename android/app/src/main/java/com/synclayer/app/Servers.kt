package com.synclayer.app

import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/** The servers this phone knows about (yours, a friend's ...). Stored as JSON in preferences; one is active. */
object Servers {
    data class Entry(val url: String, val name: String)

    fun clean(u: String): String {
        var s = u.trim().trimEnd('/')
        if (s.isNotEmpty() && !s.startsWith("http")) s = "https://$s"
        return s
    }

    fun list(p: SharedPreferences): MutableList<Entry> {
        val out = mutableListOf<Entry>()
        try {
            val a = JSONArray(p.getString("servers", "[]"))
            for (i in 0 until a.length()) a.getJSONObject(i).let { out.add(Entry(it.getString("url"), it.optString("name"))) }
        } catch (_: Exception) {}
        val legacy = p.getString("server", null)           // single-server versions of the app
        if (out.isEmpty() && !legacy.isNullOrBlank()) { out.add(Entry(clean(legacy), "")); save(p, out, 0) }
        return out
    }

    fun save(p: SharedPreferences, list: List<Entry>, active: Int) {
        val a = JSONArray()
        list.forEach { a.put(JSONObject().put("url", it.url).put("name", it.name)) }
        p.edit().putString("servers", a.toString()).putInt("active", active.coerceIn(0, maxOf(0, list.size - 1))).apply()
    }

    fun activeUrl(p: SharedPreferences): String {
        val l = list(p)
        return l.getOrNull(p.getInt("active", 0))?.url ?: BuildConfig.DEFAULT_SERVER.trim().trimEnd('/')
    }

    fun add(p: SharedPreferences, url: String) {
        val l = list(p)
        val u = clean(url)
        val i = l.indexOfFirst { it.url.equals(u, true) }
        if (i >= 0) save(p, l, i) else { l.add(Entry(u, "")); save(p, l, l.size - 1) }
    }

    fun remove(p: SharedPreferences, index: Int) {
        val l = list(p)
        if (index !in l.indices) return
        p.edit().remove("token:" + l[index].url).apply()
        l.removeAt(index)
        save(p, l, 0)
    }
}

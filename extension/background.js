// VibeDownloader - background service worker
// Catches every browser download and forwards it to the desktop app.

const DEFAULT_PORT = 8765;
const DEFAULTS = { port: DEFAULT_PORT, catchAll: true };

let aliveCache = { at: 0, ok: false };
const bypass = new Map();          // url -> expiry (downloads we must not catch)

// ------------------------------------------------------------ stream sniffing
// Remember the real media URLs a page's player loads (mp4, HLS, DASH, audio).
// If yt-dlp has no extractor for a site, the app downloads one of these instead.
const STREAM_LIMIT = 30;
const SEGMENT_EXT = /\.(ts|m4s|m4f|aac|vtt|webvtt|key|jpg|png)(\?|$)/i;
const MEDIA_EXT = /\.(m3u8|mpd|mp4|m4v|webm|mov|mkv|flv|mp3|m4a|ogg|opus)(\?|$)/i;
const SKIP_HOSTS = /(^|\.)(googlevideo\.com|youtube\.com|ytimg\.com|doubleclick\.net|googlesyndication\.com)$/i;

function streamKind(url, ctype) {
  ctype = (ctype || "").toLowerCase();
  if (/mpegurl/.test(ctype) || /\.m3u8(\?|$)/i.test(url)) return "hls";
  if (/dash\+xml/.test(ctype) || /\.mpd(\?|$)/i.test(url)) return "dash";
  if (/^audio\//.test(ctype) || /\.(mp3|m4a|ogg|opus)(\?|$)/i.test(url)) return "audio";
  if (/^video\//.test(ctype) && !/mp2t/.test(ctype)) return "video";
  if (MEDIA_EXT.test(url)) return "video";
  return "";
}

async function getStreams(tabId) {
  try {
    const key = `streams_${tabId}`;
    const saved = await chrome.storage.session.get({ [key]: [] });
    return saved[key] || [];
  } catch (e) {
    return [];
  }
}

async function setStreams(tabId, list) {
  try {
    await chrome.storage.session.set({ [`streams_${tabId}`]: list });
  } catch (e) { /* ignore */ }
  try {
    const n = list.length;
    chrome.action.setBadgeBackgroundColor({ tabId, color: "#6A3DF5" });
    chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" });
  } catch (e) { /* tab gone */ }
}

const streamQueue = new Map();       // tabId -> promise chain (no lost updates)

function rememberStream(tabId, entry) {
  const prev = streamQueue.get(tabId) || Promise.resolve();
  const next = prev.then(async () => {
    const list = await getStreams(tabId);
    const known = list.find((s) => s.url === entry.url);
    if (known) {
      if (entry.size > (known.size || 0)) known.size = entry.size;
    } else {
      list.push(entry);
      if (list.length > STREAM_LIMIT) list.shift();
    }
    await setStreams(tabId, list);
  }).catch(() => {});
  streamQueue.set(tabId, next);
}

chrome.webRequest.onHeadersReceived.addListener((details) => {
  if (details.tabId < 0) return;
  if (details.type === "main_frame") {          // new page in this tab: forget old streams
    setStreams(details.tabId, []);
    return;
  }
  const url = details.url || "";
  if (!/^https?:\/\//i.test(url) || SEGMENT_EXT.test(url)) return;
  let host = "";
  try { host = new URL(url).hostname; } catch (e) { return; }
  if (SKIP_HOSTS.test(host)) return;           // YouTube: yt-dlp handles it properly
  if (details.statusCode && details.statusCode >= 400) return;

  const headers = details.responseHeaders || [];
  const get = (name) => {
    const h = headers.find((x) => x.name.toLowerCase() === name);
    return h ? h.value || "" : "";
  };
  const ctype = get("content-type");
  const kind = streamKind(url, ctype);
  if (!kind) return;
  let size = parseInt(get("content-length") || "0", 10) || 0;
  const range = get("content-range").match(/\/(\d+)\s*$/);
  if (range) size = parseInt(range[1], 10) || size;
  // tiny files are thumbnails / previews / single segments, not the video
  if ((kind === "video" || kind === "audio") && size && size < 300 * 1024) return;

  rememberStream(details.tabId, { url, kind, ctype, size, at: Date.now() });
}, { urls: ["http://*/*", "https://*/*"],
     types: ["main_frame", "media", "xmlhttprequest", "other"] },
   ["responseHeaders"]);

chrome.tabs.onRemoved.addListener((tabId) => {
  try { chrome.storage.session.remove(`streams_${tabId}`); } catch (e) { /* ignore */ }
});

// Order: HLS/DASH master first (yt-dlp picks the best quality from it), then the
// biggest progressive video, then audio. Each link carries its own site's cookies.
async function streamsForTab(tabId) {
  const list = (await getStreams(tabId)).slice();
  const rank = { hls: 0, dash: 1, video: 2, audio: 3 };
  list.sort((a, b) => {
    const r = (rank[a.kind] ?? 9) - (rank[b.kind] ?? 9);
    if (r) return r;
    if (a.kind === "hls" || a.kind === "dash") {
      const am = /master|index|playlist/i.test(a.url) ? 0 : 1;
      const bm = /master|index|playlist/i.test(b.url) ? 0 : 1;
      return am - bm || a.at - b.at;
    }
    return (b.size || 0) - (a.size || 0);
  });
  const out = [];
  for (const s of list.slice(0, 8)) {
    out.push({ url: s.url, kind: s.kind, size: s.size || 0, cookie: await cookieHeader(s.url) });
  }
  return out;
}

// Only catch downloads the user started with a real click / key press.
// Pages that start a download on their own are left to the browser.
const GESTURE_WINDOW_MS = 8000;
let lastGesture = 0;

async function recentGesture() {
  let at = lastGesture;
  if (!at) {
    try {
      const saved = await chrome.storage.session.get({ lastGesture: 0 });
      at = saved.lastGesture || 0;
    } catch (e) { /* session storage unavailable */ }
  }
  return at && Date.now() - at <= GESTURE_WINDOW_MS;
}

async function getCfg() {
  return chrome.storage.local.get(DEFAULTS);
}

async function pingPort(port, timeout) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const res = await fetch(`http://127.0.0.1:${port}/ping`, {
      cache: "no-store",
      signal: controller.signal
    });
    clearTimeout(timer);
    const data = await res.json();
    return !!(data && data.status === "ok" && data.app === "VibeDownloader");
  } catch (e) {
    return false;
  }
}

// The app moves to 8766..8776 when 8765 is busy; find it and remember the port.
const PORT_RANGE = Array.from({ length: 12 }, (_, i) => DEFAULT_PORT + i);

async function ping(force = false) {
  const now = Date.now();
  if (!force && now - aliveCache.at < 2500) return aliveCache.ok;

  const { port } = await getCfg();
  let ok = await pingPort(port, 2500);
  if (!ok) {
    const others = PORT_RANGE.filter((p) => p !== port);
    const answers = await Promise.all(others.map((p) => pingPort(p, 800)));
    const found = others[answers.indexOf(true)];
    if (found) {
      await chrome.storage.local.set({ port: found });
      ok = true;
    }
  }
  aliveCache = { at: Date.now(), ok };
  return ok;
}

async function postToApp(payload, timeout = 12000) {
  const { port } = await getCfg();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function cookieHeader(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    if (!cookies || !cookies.length) return "";
    return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch (e) {
    return "";
  }
}

function setBadge(text, color = "#0B62C4") {
  try {
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setBadgeText({ text });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
  } catch (e) { /* ignore */ }
}

async function sendDownload(rawUrl, options = {}) {
  if (!rawUrl || !/^https?:\/\//i.test(rawUrl)) {
    return { status: "error", error: "Unsupported link (only http/https)" };
  }

  const cookie = await cookieHeader(rawUrl);
  const payload = {
    action: "download",
    url: rawUrl,
    kind: options.kind || "auto",
    quality: options.quality || "best",
    filename: options.filename || "",
    referrer: options.referrer || "",
    verify: !!options.verify,
    streams: Array.isArray(options.streams) ? options.streams : [],
    cookie,
    userAgent: self.navigator.userAgent
  };

  try {
    const result = await postToApp(payload);
    if (result && result.status === "ok") {
      setBadge("✓", "#1E8E3E");
    } else {
      setBadge("!", "#C62828");
    }
    return result;
  } catch (e) {
    setBadge("!", "#C62828");
    return { status: "error", error: "VibeDownloader is not running" };
  }
}

// ------------------------------------------------------------------ messages
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      if (message.type === "GESTURE") {
        lastGesture = Date.now();
        try {
          await chrome.storage.session.set({ lastGesture });
        } catch (e) { /* ignore */ }
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "PING") {
        const ok = await ping(true);
        sendResponse({ ok, port: (await getCfg()).port });
        return;
      }
      if (message.type === "DOWNLOAD") {
        const payload = message.payload || {};
        const tab = sender.tab;
        // video button: hand over what the player really loaded as a fallback
        const streams = (payload.kind === "media" && tab && tab.id >= 0)
          ? await streamsForTab(tab.id) : [];
        const result = await sendDownload(payload.url || (tab && tab.url), {
          ...payload,
          streams,
          referrer: payload.referrer || (tab && tab.url) || ""
        });
        sendResponse(result);
        return;
      }
      if (message.type === "TAB") {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        sendResponse({ url: (tab && tab.url) || "", title: (tab && tab.title) || "" });
        return;
      }
      sendResponse({ status: "error", error: "unknown message" });
    } catch (e) {
      sendResponse({ status: "error", error: String(e) });
    }
  })();
  return true;   // keep the channel open for the async reply
});

// -------------------------------------------------- catch browser downloads
const SKIP_SCHEME = /^(blob|data|filesystem|chrome-extension|moz-extension|about):/i;
const LOCAL_APP = /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i;

chrome.downloads.onCreated.addListener(async (item) => {
  const url = item.finalUrl || item.url;
  if (!url || SKIP_SCHEME.test(url) || LOCAL_APP.test(url)) return;

  const expiry = bypass.get(url);
  if (expiry && expiry > Date.now()) {
    bypass.delete(url);
    return;
  }

  // Pause the browser's copy at once, before any other await: a small file could
  // otherwise finish in the browser while we decide, and then download twice.
  // Pausing (not cancelling) keeps the browser's own request, so it can simply
  // be resumed if the app does not take the job.
  let paused = false;
  try {
    await chrome.downloads.pause(item.id);
    paused = true;
  } catch (e) { /* not pausable / already finished */ }

  const giveBack = async () => {
    if (!paused) return;
    try { await chrome.downloads.resume(item.id); } catch (e) { /* ignore */ }
  };

  try {
    const cfg = await getCfg();
    // catchAll off, page started it by itself, or app not running -> browser keeps it.
    if (!cfg.catchAll || !(await recentGesture()) || !(await ping())) {
      await giveBack();
      return;
    }

    // Finished in the browser before we could pause it -> don't download it again.
    const [current] = await chrome.downloads.search({ id: item.id });
    if (!current || current.state === "complete") return;

    const result = await sendDownload(url, {
      filename: (item.filename || "").split(/[\\/]/).pop(),
      referrer: item.referrer || "",
      kind: "auto",
      verify: true
    });

    if (result && result.status === "ok") {
      try { await chrome.downloads.cancel(item.id); } catch (e) { /* already gone */ }
      try { await chrome.downloads.erase({ id: item.id }); } catch (e) { /* ignore */ }
      return;
    }

    // The app could not use this link (expired token, login needed, POST form...):
    // continue the browser's own download, which still has the right request.
    if (paused) {
      await giveBack();
    } else {
      bypass.set(url, Date.now() + 15000);
      chrome.downloads.download({ url });
    }
  } catch (e) {
    await giveBack();
    console.warn("VibeDownloader intercept failed", e);
  }
});

// --------------------------------------------------------------- right click
function rebuildMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "vibe-link",
      title: "Download with VibeDownloader",
      contexts: ["link"]
    });
    chrome.contextMenus.create({
      id: "vibe-media",
      title: "Download with VibeDownloader",
      contexts: ["image", "video", "audio"]
    });
    chrome.contextMenus.create({
      id: "vibe-page",
      title: "Download this page with VibeDownloader",
      contexts: ["page"]
    });
    chrome.contextMenus.create({
      id: "vibe-grab",
      title: "Download all links on this page",
      contexts: ["page"]
    });
  });
}

// Context menus persist in MV3; creating them once per install/update avoids
// "duplicate id" races from re-creating them on every service-worker start.
chrome.runtime.onInstalled.addListener(rebuildMenus);

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "vibe-grab") {
    const pageUrl = info.pageUrl || (tab && tab.url) || "";
    if (!tab || !tab.id) return;
    // ask the top frame only (iframes/ads would answer first with 0 links)
    chrome.tabs.sendMessage(tab.id, { type: "COLLECT_LINKS" }, { frameId: 0 }, async (response) => {
      if (chrome.runtime.lastError) {
        setBadge("!", "#C62828");       // page opened before the extension was loaded
        return;
      }
      const urls = (response && response.urls) || [];
      // each link gets only its own site's cookies, never the page's cookies
      const byOrigin = new Map();
      const items = [];
      for (const url of urls) {
        let origin = "";
        try { origin = new URL(url).origin; } catch (e) { continue; }
        if (!byOrigin.has(origin)) byOrigin.set(origin, await cookieHeader(url));
        items.push({ url, cookie: byOrigin.get(origin) });
      }
      try {
        await postToApp({
          action: "grab",
          items,
          referrer: pageUrl,
          userAgent: self.navigator.userAgent
        });
        setBadge(String(urls.length || "!"), urls.length ? "#1E8E3E" : "#C62828");
      } catch (e) {
        setBadge("!", "#C62828");
      }
    });
    return;
  }

  let url = info.linkUrl || info.srcUrl || "";
  let kind = "auto";

  // blob:/data: video or audio (YouTube, Facebook, most players) can't be fetched
  // directly -> download the page with yt-dlp instead
  if (url && !/^https?:\/\//i.test(url) && info.mediaType && info.mediaType !== "image") {
    url = info.pageUrl || (tab && tab.url) || "";
    kind = "media";
  }

  if (info.menuItemId === "vibe-page" || !url) {
    url = info.pageUrl || (tab && tab.url) || "";
    kind = "auto";
    if (/youtube\.com|youtu\.be|vimeo\.com|tiktok\.com|instagram\.com/i.test(url)) {
      kind = "media";
    }
  }

  if (!url) return;
  const streams = (kind === "media" && tab && tab.id >= 0) ? await streamsForTab(tab.id) : [];
  const result = await sendDownload(url, {
    kind,
    streams,
    referrer: (tab && tab.url) || ""
  });
  if (!result || result.status !== "ok") {
    setBadge("!", "#C62828");
  }
});

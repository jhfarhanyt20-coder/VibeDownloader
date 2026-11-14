// VibeDownloader - background service worker
// Catches every browser download and forwards it to the desktop app.

const DEFAULT_PORT = 8765;
const DEFAULTS = { port: DEFAULT_PORT, catchAll: true };

let aliveCache = { at: 0, ok: false };
const bypass = new Map();          // url -> expiry (downloads we must not catch)

async function getCfg() {
  return chrome.storage.local.get(DEFAULTS);
}

async function ping(force = false) {
  const now = Date.now();
  if (!force && now - aliveCache.at < 2500) return aliveCache.ok;

  const { port } = await getCfg();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`http://127.0.0.1:${port}/ping`, {
      cache: "no-store",
      signal: controller.signal
    });
    clearTimeout(timer);
    const data = await res.json();
    aliveCache = { at: Date.now(), ok: data && data.status === "ok" };
    return aliveCache.ok;
  } catch (e) {
    aliveCache = { at: Date.now(), ok: false };
    return false;
  }
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
      if (message.type === "PING") {
        const ok = await ping(true);
        sendResponse({ ok, port: (await getCfg()).port });
        return;
      }
      if (message.type === "DOWNLOAD") {
        const payload = message.payload || {};
        const tab = sender.tab;
        const result = await sendDownload(payload.url || (tab && tab.url), {
          ...payload,
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
  try {
    const cfg = await getCfg();
    if (!cfg.catchAll) return;

    const url = item.finalUrl || item.url;
    if (!url || SKIP_SCHEME.test(url) || LOCAL_APP.test(url)) return;

    const expiry = bypass.get(url);
    if (expiry && expiry > Date.now()) {
      bypass.delete(url);
      return;
    }

    // If the app is not running, let the browser do a normal download.
    if (!(await ping())) return;

    // Stop Chrome's copy first, then hand the job to the app.
    try {
      await chrome.downloads.cancel(item.id);
    } catch (e) { /* already gone */ }
    try {
      await chrome.downloads.erase({ id: item.id });
    } catch (e) { /* ignore */ }

    const result = await sendDownload(url, {
      filename: item.filename || "",
      referrer: item.referrer || "",
      kind: "auto"
    });

    // If forwarding failed, put the download back in the browser.
    if (!result || result.status !== "ok") {
      const name = (item.filename || "").split(/[\\/]/).pop();
      bypass.set(url, Date.now() + 15000);
      chrome.downloads.download({ url, filename: name || undefined });
    }
  } catch (e) {
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

chrome.runtime.onInstalled.addListener(rebuildMenus);
chrome.runtime.onStartup.addListener(rebuildMenus);
rebuildMenus();

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "vibe-grab") {
    const pageUrl = info.pageUrl || (tab && tab.url) || "";
    if (!tab || !tab.id) return;
    chrome.tabs.sendMessage(tab.id, { type: "COLLECT_LINKS" }, async (response) => {
      const urls = (response && response.urls) || [];
      const cookie = pageUrl ? await cookieHeader(pageUrl) : "";
      try {
        await postToApp({
          action: "grab",
          urls,
          referrer: pageUrl,
          cookie,
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

  if (info.menuItemId === "vibe-page" || !url) {
    url = info.pageUrl || (tab && tab.url) || "";
    kind = "auto";
    if (/youtube\.com|youtu\.be|vimeo\.com|tiktok\.com|instagram\.com/i.test(url)) {
      kind = "media";
    }
  }

  if (!url) return;
  const result = await sendDownload(url, {
    kind,
    referrer: (tab && tab.url) || ""
  });
  if (!result || result.status !== "ok") {
    setBadge("!", "#C62828");
  }
});

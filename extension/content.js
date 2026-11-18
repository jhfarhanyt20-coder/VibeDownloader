// VibeDownloader content script
// 1) catches clicks on downloadable links on ANY website
// 2) adds a draggable download button on top of every <video> on every website

(function () {
  "use strict";

  const DOWNLOAD_EXTENSIONS = new Set([
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab",
    "exe", "msi", "apk", "dmg", "pkg", "deb", "rpm", "jar", "bat",
    "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg",
    "mpeg", "ts", "3gp", "mp3", "m4a", "flac", "wav", "aac", "ogg",
    "opus", "wma", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "epub", "mobi", "csv", "rtf", "srt", "vtt", "img", "bin"
  ]);

  const SKIP_SCHEME = /^(blob|data|filesystem|javascript|mailto|tel):/i;

  function toast(message, isError) {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483647;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>.box{font:13px/1.4 "Segoe UI",Arial,sans-serif;color:#fff;background:${isError ? "#c62828" : "#1e8e3e"};padding:10px 16px;border-radius:6px;box-shadow:0 6px 24px rgba(0,0,0,.35);}</style><div class="box"></div>`;
    root.querySelector(".box").textContent = message;
    document.documentElement.appendChild(host);
    setTimeout(() => host.remove(), 2600);
  }

  function basename(url) {
    try {
      const path = new URL(url).pathname;
      const name = decodeURIComponent(path.split("/").pop() || "");
      return name.replace(/[\\/:*?"<>|]/g, "_").slice(0, 160);
    } catch (e) { return ""; }
  }

  function sendDownload(url, options) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(
          { type: "DOWNLOAD", payload: { url, ...(options || {}) } },
          (response) => {
            if (chrome.runtime.lastError) {
              resolve({ status: "error", error: chrome.runtime.lastError.message });
              return;
            }
            resolve(response || { status: "error", error: "no response" });
          }
        );
      } catch (e) {
        resolve({ status: "error", error: String(e) });
      }
    });
  }

  // "Catch all browser downloads" switch from the extension popup
  let catchAll = true;
  try {
    chrome.storage.local.get({ catchAll: true }, (v) => { catchAll = !!(v && v.catchAll); });
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === "local" && changes.catchAll) catchAll = !!changes.catchAll.newValue;
    });
  } catch (e) { /* extension reloaded */ }

  let appAlive = false;
  function refreshAlive() {
    try {
      chrome.runtime.sendMessage({ type: "PING" }, (response) => {
        if (chrome.runtime.lastError) return;
        appAlive = !!(response && response.ok);
      });
    } catch (e) { }
  }
  refreshAlive();
  setInterval(refreshAlive, 10000);

  function browserFallback(url, filename) {
    const link = document.createElement("a");
    link.href = url;
    if (filename) link.download = filename;
    link.style.display = "none";
    document.documentElement.appendChild(link);
    link.click();
    link.remove();
  }

  async function handleDownload(url, options, label, canFallback = true) {
    const result = await sendDownload(url, options);
    if (result && result.status === "ok") {
      toast((label || "Download") + " added to VibeDownloader");
      appAlive = true;
    } else {
      const error = (result && result.error) || "Not connected";
      if (canFallback) {
        toast("VibeDownloader: " + error + " - using the browser instead", true);
        browserFallback(url, options && options.filename);
      } else {
        toast("VibeDownloader: " + error + " - open the VibeDownloader app and try again", true);
      }
      if (!result || /not running|not connected/i.test(error)) appAlive = false;
    }
    return result;
  }

  // --------------------------------------------------- report real user gestures
  // The background only catches browser downloads that follow one of these,
  // so pages that start downloads by themselves never open the app's dialog.
  let lastGestureSent = 0;
  function reportGesture(event) {
    if (!event.isTrusted) return;
    if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
    const now = Date.now();
    if (now - lastGestureSent < 500) return;
    lastGestureSent = now;
    try {
      chrome.runtime.sendMessage({ type: "GESTURE" }, () => void chrome.runtime.lastError);
    } catch (e) { /* extension reloaded */ }
  }
  document.addEventListener("pointerdown", reportGesture, true);
  document.addEventListener("keydown", reportGesture, true);

  // --------------------------------------------------- catch download clicks
  document.addEventListener("click", (event) => {
    if (!event.isTrusted) return;
    if (event.defaultPrevented) return;
    if (event.button !== 0) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!anchor) return;
    const href = anchor.href || "";
    if (!/^https?:\/\//i.test(href) || SKIP_SCHEME.test(href)) return;
    const hasDownloadAttr = anchor.hasAttribute("download");
    let extension = "";
    try {
      const path = new URL(href).pathname;
      extension = (path.split(".").pop() || "").toLowerCase();
    } catch (e) { return; }
    if (!hasDownloadAttr && !DOWNLOAD_EXTENSIONS.has(extension)) return;
    if (!catchAll || !appAlive) return;
    event.preventDefault();
    event.stopPropagation();
    const filename = anchor.getAttribute("download") || basename(href);
    handleDownload(href, { kind: "file", filename, referrer: location.href, verify: true },
                   filename || "File");
  }, true);

  // --------------------------------------------------- always-visible video download button
  // Every real <video> on the page gets a button that is ALWAYS shown (no hover, no timer).
  // Videos are never wrapped/moved. The button lives in a shadow-DOM overlay and follows
  // scroll / resize / fullscreen. Drag it anywhere on the video; the position is remembered.
  (function alwaysVisibleVideoButtons() {
    const MIN_W = 150, MIN_H = 80;

    const host = document.createElement("div");
    host.style.cssText = "position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      .btn{position:fixed;display:none;pointer-events:auto;align-items:center;gap:6px;
        background:linear-gradient(135deg,rgba(106,61,245,.96),rgba(0,184,240,.96));color:#fff;border:none;
        padding:5px 12px 5px 6px;border-radius:14px;font:600 12px/1 "Segoe UI",Arial,sans-serif;cursor:grab;
        box-shadow:0 2px 10px rgba(0,0,0,.5);user-select:none;white-space:nowrap;touch-action:none}
      .btn img{width:16px;height:16px;border-radius:4px;pointer-events:none;display:block}
      .btn:hover{filter:brightness(1.1)}
      .btn.drag{cursor:grabbing}
    </style>`;

    function mount() {
      const parent = document.fullscreenElement || document.webkitFullscreenElement || document.documentElement;
      if (parent && host.parentNode !== parent) parent.appendChild(host);
    }
    mount();
    document.addEventListener("fullscreenchange", () => { mount(); update(); });
    document.addEventListener("webkitfullscreenchange", () => { mount(); update(); });

    // saved position: distance from the video's top-right corner
    let off = { right: 8, top: 8 };
    try {
      chrome.storage.local.get({ btnOff: null }, (v) => {
        if (v && v.btnOff && typeof v.btnOff.right === "number") { off = v.btnOff; update(); }
      });
    } catch (e) { }

    const buttons = new Map();   // video -> button element
    let dragging = false;

    function visibleRect(video) {
      const r = video.getBoundingClientRect();
      const left = Math.max(r.left, 0), top = Math.max(r.top, 0);
      const right = Math.min(r.right, window.innerWidth), bottom = Math.min(r.bottom, window.innerHeight);
      return { left, top, right, bottom, width: right - left, height: bottom - top };
    }

    function usable(video) {
      if (!video.isConnected) return false;
      const cs = getComputedStyle(video);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      const r = visibleRect(video);
      return r.width >= MIN_W && r.height >= MIN_H;
    }

    function download(video) {
      let url = video.currentSrc || video.src || "";
      let direct = true;
      // blob:/MSE/HLS streams can't be fetched directly -> let the app resolve the page URL
      if (!/^https?:\/\//i.test(url) || /\.(m3u8|mpd)(\?|$)/i.test(url)) {
        url = location.href;
        direct = false;            // never "fall back" to downloading the web page itself
      }
      handleDownload(url, { kind: "media", quality: "best", referrer: location.href,
                            filename: document.title || "" }, "Video", direct);
    }

    let iconUrl = "";
    try { iconUrl = chrome.runtime.getURL("icon16.png"); } catch (e) { /* reloaded */ }

    function makeButton(video) {
      const btn = document.createElement("button");
      btn.className = "btn";
      if (iconUrl) {
        const img = document.createElement("img");
        img.src = iconUrl;
        img.alt = "";
        img.draggable = false;
        btn.appendChild(img);
      }
      btn.appendChild(document.createTextNode("Download"));
      btn.title = "Download with VibeDownloader";

      let moved = false, sx = 0, sy = 0, sOff = null;
      btn.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        dragging = true; moved = false;
        sx = e.clientX; sy = e.clientY; sOff = { right: off.right, top: off.top };
        btn.classList.add("drag");
        try { btn.setPointerCapture(e.pointerId); } catch (err) { }
        e.preventDefault(); e.stopPropagation();
      });
      btn.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        const dx = e.clientX - sx, dy = e.clientY - sy;
        if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
        if (!moved) return;
        off = { right: sOff.right - dx, top: sOff.top + dy };
        update();
        e.preventDefault(); e.stopPropagation();
      });
      const end = (e) => {
        if (!dragging) return;
        dragging = false;
        btn.classList.remove("drag");
        try { btn.releasePointerCapture(e.pointerId); } catch (err) { }
        if (moved) { try { chrome.storage.local.set({ btnOff: off }); } catch (err) { } }
      };
      btn.addEventListener("pointerup", end);
      btn.addEventListener("pointercancel", end);

      btn.addEventListener("click", (e) => {
        e.stopPropagation(); e.preventDefault();
        if (moved) { moved = false; return; }
        download(video);
      });
      // keep players from reacting to clicks on our button
      ["mousedown", "mouseup", "dblclick", "contextmenu"].forEach((t) =>
        btn.addEventListener(t, (e) => e.stopPropagation()));

      root.appendChild(btn);
      return btn;
    }

    function place(video, btn) {
      const r = visibleRect(video);
      const w = btn.offsetWidth || 90, h = btn.offsetHeight || 26;
      let x = r.right - w - off.right;
      let y = r.top + off.top;
      x = Math.max(r.left, Math.min(r.right - w, x));
      y = Math.max(r.top, Math.min(r.bottom - h, y));
      btn.style.left = x + "px";
      btn.style.top = y + "px";
    }

    function update() {
      mount();
      const seen = new Set();
      document.querySelectorAll("video").forEach((v) => {
        if (!usable(v)) return;
        seen.add(v);
        let btn = buttons.get(v);
        if (!btn) { btn = makeButton(v); buttons.set(v, btn); }
        btn.style.display = "flex";
        place(v, btn);
      });
      buttons.forEach((btn, v) => {
        if (!seen.has(v)) { btn.remove(); buttons.delete(v); }
      });
    }

    let queued = false;
    function schedule() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; update(); });
    }

    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    document.addEventListener("play", schedule, true);
    document.addEventListener("loadedmetadata", schedule, true);
    document.addEventListener("playing", schedule, true);
    new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
    // safety net: players resize/move videos without events
    setInterval(update, 500);
    update();
  })();

  function collectLinks() {
    const urls = new Set();
    document.querySelectorAll("a[href]").forEach((anchor) => {
      const href = anchor.href || "";
      if (!/^https?:\/\//i.test(href) || SKIP_SCHEME.test(href)) return;
      let extension = "";
      try {
        extension = (new URL(href).pathname.split(".").pop() || "").toLowerCase();
      } catch (e) { return; }
      if (anchor.hasAttribute("download") || DOWNLOAD_EXTENSIONS.has(extension)) {
        urls.add(href);
      }
    });
    return Array.from(urls).slice(0, 200);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message && message.type === "COLLECT_LINKS") {
      sendResponse({ urls: collectLinks() });
      return true;
    }
    return false;
  });
})();

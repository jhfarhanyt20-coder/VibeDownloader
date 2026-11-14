// VibeDownloader popup
const DEFAULTS = { port: 8765, catchAll: true };
const MEDIA_HOST = /(youtube\.com|youtu\.be|vimeo\.com|tiktok\.com|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|soundcloud\.com|twitch\.tv|dailymotion\.com|reddit\.com|bilibili\.com)/i;

const statusEl = document.getElementById("status");
const pageBtn = document.getElementById("downloadPage");
const showAppBtn = document.getElementById("showApp");
const testBtn = document.getElementById("testBtn");
const catchAllEl = document.getElementById("catchAll");
const portEl = document.getElementById("port");
const savedEl = document.getElementById("saved");

let currentTab = { url: "", title: "" };

function showStatus(ok, port) {
  if (ok) {
    statusEl.innerHTML = `<strong>✓ Connected</strong><br>App ready on port ${port}`;
    statusEl.className = "status connected";
  } else {
    statusEl.innerHTML =
      "<strong>⚠ App not running</strong><br>Start VibeDownloader first";
    statusEl.className = "status error";
  }
}

async function pingApp() {
  const { port } = await chrome.storage.local.get(DEFAULTS);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`http://127.0.0.1:${port}/ping`, {
      cache: "no-store",
      signal: controller.signal
    });
    clearTimeout(timer);
    const data = await res.json();
    const ok = data && data.status === "ok";
    showStatus(ok, port);
    if (ok && data.downloads != null) {
      showAppBtn.textContent = `↗ Show VibeDownloader window (${data.downloads})`;
    } else {
      showAppBtn.textContent = "↗ Show VibeDownloader window";
    }
    return ok;
  } catch (e) {
    showStatus(false, port);
    showAppBtn.textContent = "↗ Show VibeDownloader window";
    return false;
  }
}

async function showApp() {
  const { port } = await chrome.storage.local.get(DEFAULTS);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`http://127.0.0.1:${port}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "show" }),
      signal: controller.signal
    });
    clearTimeout(timer);
    const data = await res.json();
    if (data && data.status === "ok" && data.shown) {
      showAppBtn.textContent = "✓ Window shown";
      setTimeout(() => { showAppBtn.textContent = "↗ Show VibeDownloader window"; }, 1800);
    }
  } catch (e) {
    showAppBtn.textContent = "✗ App not running";
  }
}

async function loadSettings() {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  portEl.value = cfg.port;
  catchAllEl.checked = !!cfg.catchAll;
}

async function loadTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTab = { url: (tab && tab.url) || "", title: (tab && tab.title) || "" };

  const isMedia = MEDIA_HOST.test(currentTab.url) ||
    /youtube\.com\/watch|youtu\.be\/|vimeo\.com\/\d+/i.test(currentTab.url);

  if (!currentTab.url || !/^https?:/i.test(currentTab.url)) {
    pageBtn.disabled = true;
    pageBtn.textContent = "No downloadable page";
    return;
  }

  if (isMedia) {
    pageBtn.textContent = "⬇ Download video on this page";
    pageBtn.dataset.kind = "media";
  } else {
    pageBtn.textContent = "⬇ Download this page";
    pageBtn.dataset.kind = "auto";
  }
}

function sendMessage(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ status: "error", error: chrome.runtime.lastError.message });
      } else {
        resolve(response || { status: "error", error: "no response" });
      }
    });
  });
}

pageBtn.addEventListener("click", async () => {
  if (!currentTab.url) return;
  pageBtn.disabled = true;
  const previous = pageBtn.textContent;
  pageBtn.textContent = "Sending…";

  const result = await sendMessage({
    type: "DOWNLOAD",
    payload: {
      url: currentTab.url,
      kind: pageBtn.dataset.kind || "auto",
      quality: "best",
      filename: currentTab.title || ""
    }
  });

  if (result && result.status === "ok") {
    pageBtn.textContent = "✓ Added to VibeDownloader";
    setTimeout(() => {
      pageBtn.textContent = previous;
      pageBtn.disabled = false;
    }, 1600);
  } else {
    pageBtn.textContent = "✗ App not running";
    showStatus(false, portEl.value);
    setTimeout(() => {
      pageBtn.textContent = previous;
      pageBtn.disabled = false;
    }, 1600);
  }
});

showAppBtn.addEventListener("click", showApp);
testBtn.addEventListener("click", async () => {
  testBtn.textContent = "Checking…";
  await pingApp();
  testBtn.textContent = "Reconnect";
});

catchAllEl.addEventListener("change", async () => {
  await chrome.storage.local.set({ catchAll: catchAllEl.checked });
  savedEl.textContent = "Saved ✓";
  setTimeout(() => { savedEl.textContent = ""; }, 1500);
});

portEl.addEventListener("change", async () => {
  let port = parseInt(portEl.value, 10);
  if (!port || port < 1024 || port > 65535) {
    port = 8765;
    portEl.value = port;
  }
  await chrome.storage.local.set({ port });
  savedEl.textContent = "Saved ✓";
  setTimeout(() => { savedEl.textContent = ""; }, 1500);
  await pingApp();
});

(async function init() {
  await loadSettings();
  await loadTab();
  await pingApp();
})();

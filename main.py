"""
VibeDownloader - download manager.

* multi-connection direct downloads with pause / resume
* YouTube & ~1800 other sites through yt-dlp
* browser extension that catches every download click in Chrome / Edge
* classic layout: menu bar, toolbar, category tree, list, status bar
"""

import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tkinter import filedialog, ttk
from urllib.parse import unquote, urlparse

import customtkinter as ctk
import requests
from PIL import Image, ImageTk

from classic_icons import toolbar_icon
from app_info import APP_DISPLAY_NAME, APP_NAME, APP_VERSION
import app_updater
import downloader as engine
from update_dialog import AppUpdateDialog
import windows_startup
import quiet_notify
import yt_helper
import window_frame
# themed replacements: every message box uses our own window frame
from window_frame import themed_messagebox as messagebox
from window_frame import themed_simpledialog as simpledialog

UI_REVISION = 3

ctk.set_default_color_theme("blue")
# We draw our own title bar (window_frame). CustomTkinter's Windows title-bar
# coloring hides and re-shows every window, which is slow and races with ours.
ctk.CTk._deactivate_windows_window_header_manipulation = True
ctk.CTkToplevel._deactivate_windows_window_header_manipulation = True

# --------------------------------------------------------------------- folders
DATA_DIR = yt_helper.app_data_dir()
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

DEFAULT_SETTINGS = {
    "default_save_dir": DEFAULT_DOWNLOAD_DIR,
    "max_concurrent": 3,
    "connections": 8,
    "port": 8765,
    "auto_start": True,
    "auto_install_ffmpeg": True,
    "ask_save_path": True,
    "show_progress_window": True,
    "theme": "dark",
    "theme_default_dark": True,
    "show_complete_dialog": True,
    "prefetch_in_dialog": True,      # start downloading while Download File Info is open
    "start_with_windows": True,
    "start_minimized": True,
    "close_to_tray": True,
    "ui_revision": 3,
    "category_paths": {},            # {"video": "C:\\...\\\Downloads\\Video", ...}
    "custom_categories": [],         # extra category names added via "+" in the dialog
    # off by default: a copied link must not pop the download dialog by itself
    "clipboard_monitor": False,
    "clipboard_default_v2": True,
    "check_updates": True,
    "sound_on_complete": True,
    "max_retries": 3,
    "queue_running": True,
    "schedule_enabled": False,
    "schedule_start": "",
    "schedule_stop": "",
    "queue_complete_action": "none",  # none | exit | sleep | shutdown
}

# ---- theme selection (read early so palette constants match) ----
def _early_theme():
    try:
        import json as _j
        path = os.path.join(yt_helper.app_data_dir(), "settings.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as _f:
                data = _j.load(_f)
                # Dark is the default. Older builds forced "light" on every
                # install, so switch those to dark once (see load_settings).
                if not data.get("theme_default_dark"):
                    return "dark"
                return data.get("theme", "dark")
    except Exception:  # noqa: BLE001
        pass
    return "dark"


_THEME = _early_theme()
_IS_DARK = _THEME != "light"

if _IS_DARK:
    # near-black, layered "glossy" dark: each surface a step lighter than the
    # one below it, thin highlight lines, one calm blue accent
    C_BG = "#0D0E10"
    C_PANEL = "#121316"
    C_TOOLBAR = "#18191D"
    C_BORDER = "#2A2C32"
    C_TEXT = "#ECEDEF"
    C_MUTED = "#8E949E"
    C_BLUE = "#4C8DFF"
    C_BLUE_HOVER = "#6AA1FF"
    C_SELECT = "#1C2740"
    C_ROW_ALT = "#15161A"
    C_GREEN = "#3FBF7F"
    C_RED = "#F0625A"
    C_ORANGE = "#F0A53C"
    C_BTN = "#1E2025"
    C_BTN_HOVER = "#2A2D34"
    C_INPUT_BG = "#0A0B0D"
    C_BADGE = "#1C2433"
    C_SHEEN = "#2E3138"      # 1 px top highlight on bars = the "gloss"
else:
    C_BG = "#F3F3F3"
    C_PANEL = "#FFFFFF"
    C_TOOLBAR = "#F8F8F8"
    C_BORDER = "#C8C8C8"
    C_TEXT = "#161616"
    C_MUTED = "#5B5B5B"
    C_BLUE = "#1769AA"
    C_BLUE_HOVER = "#0E5C98"
    C_SELECT = "#CCE8FF"
    C_ROW_ALT = "#F8FAFC"
    C_GREEN = "#2E8B57"
    C_RED = "#C43B32"
    C_ORANGE = "#A86600"
    C_BTN = "#E9E9E9"
    C_BTN_HOVER = "#DDEEFF"
    C_INPUT_BG = "#FFFFFF"
    C_BADGE = "#E5F2FA"
    C_SHEEN = "#FFFFFF"

ctk.set_appearance_mode("dark" if _IS_DARK else "light")

# Our own title bar / window frame on every window, in the theme's colors.
window_frame.configure(
    colors={
        "bg": C_BG, "bar": C_TOOLBAR, "text": C_TEXT, "muted": C_MUTED,
        "border": C_BORDER, "hover": C_BTN_HOVER, "button": C_BTN,
        "input": C_INPUT_BG, "accent": "#6A3DF5", "accent2": "#00B8F0",
        "close_hover": "#C42B1C", "sheen": C_SHEEN,
    },
    icon_path=os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
                           "VibeDownloader.ico"),
)

COLUMNS = [
    ("name", "File Name", 170, "w"),
    ("queue", "Q", 22, "center"),
    ("size", "Size", 66, "e"),
    ("status", "Status", 74, "w"),
    ("description", "Description", 80, "w"),
    ("speed", "Transfer rate", 84, "e"),
    ("date", "Date Added", 106, "w"),
    ("eta", "Time left", 62, "e"),
]

CATEGORIES = [
    ("all", "All Downloads"),
    ("compressed", "Compressed"),
    ("documents", "Documents"),
    ("music", "Music"),
    ("programs", "Programs"),
    ("video", "Video"),
    ("other", "Other"),
]

EXT_CATEGORY = {
    "video": {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v",
              "mpg", "mpeg", "ts", "3gp", "ogv"},
    "music": {"mp3", "m4a", "flac", "wav", "aac", "ogg", "opus", "wma", "aiff"},
    "documents": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt",
                  "epub", "mobi", "csv", "rtf", "odt"},
    "compressed": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab"},
    "programs": {"exe", "msi", "apk", "dmg", "pkg", "deb", "rpm", "jar", "bat"},
}


# ----------------------------------------------------------------------- helpers
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)}


def sanitize_filename(name):
    if not name:
        return ""
    name = str(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip().strip(".")
    if len(name) > 180:
        # shorten the name, never the extension (".pdf" must stay ".pdf")
        stem, ext = os.path.splitext(name)
        ext = ext if 1 < len(ext) <= 12 else ""
        name = stem[:180 - len(ext)].rstrip(" .") + ext
    name = name.rstrip(" .")
    if os.path.splitext(name)[0].upper() in WINDOWS_RESERVED:
        name = "_" + name                         # CON, NUL.zip, aux.pdf...
    return name


def filename_from_headers(headers):
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    if match:
        return match.group(1).strip()
    return ""


MEDIA_EXTS = EXT_CATEGORY["video"] | EXT_CATEGORY["music"]
WEB_EXTS = {".php", ".asp", ".aspx", ".jsp", ".cgi", ".do", ".action", ".htm", ".html"}
CONTENT_TYPE_EXT = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/x-matroska": ".mkv",
    "video/quicktime": ".mov", "video/x-msvideo": ".avi", "video/mpeg": ".mpg",
    "video/mp2t": ".ts", "video/3gpp": ".3gp", "video/x-flv": ".flv",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/ogg": ".ogg",
    "audio/opus": ".opus", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/flac": ".flac", "audio/webm": ".webm",
    "application/pdf": ".pdf", "application/zip": ".zip",
    "application/x-zip-compressed": ".zip", "application/x-rar-compressed": ".rar",
    "application/vnd.rar": ".rar", "application/x-7z-compressed": ".7z",
    "application/gzip": ".gz", "application/x-tar": ".tar",
    "application/x-msdownload": ".exe", "application/vnd.microsoft.portable-executable": ".exe",
    "application/x-msi": ".msi", "application/vnd.android.package-archive": ".apk",
    "application/x-iso9660-image": ".iso", "application/epub+zip": ".epub",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "text/html": ".html", "text/plain": ".txt",
    "text/csv": ".csv", "application/json": ".json",
}
GENERIC_CTYPES = {"", "application/octet-stream", "binary/octet-stream",
                  "application/force-download", "application/download"}


def _real_ext(name, ctype=""):
    """Return the extension of `name` if it looks like a real file format."""
    ext = os.path.splitext(name or "")[1].lower()
    if not ext or len(ext) > 6 or not ext[1:].isalnum():
        return ""
    if ext in WEB_EXTS and not (ctype or "").startswith("text/html"):
        return ""
    return ext


def ext_from_ctype(ctype):
    ctype = (ctype or "").split(";")[0].strip().lower()
    if ctype in GENERIC_CTYPES:
        return ""
    return CONTENT_TYPE_EXT.get(ctype) or mimetypes.guess_extension(ctype) or ""


def choose_filename(header_name, given, url_name, ctype=""):
    """File name: Content-Disposition > name from the page > URL name,
    and the extension is fixed from Content-Type when the name has none."""
    names = [sanitize_filename(n) for n in (header_name, given, url_name)]
    for name in names:
        if name and _real_ext(name, ctype):
            return name
    chosen = next((n for n in names if n), "") or "download"
    ext = ext_from_ctype(ctype)
    if ext:
        if os.path.splitext(chosen)[1].lower() in WEB_EXTS:
            chosen = os.path.splitext(chosen)[0]
        return chosen + ext
    if "." not in chosen:
        chosen += ".bin"
    return chosen


def probe_file_info(url, headers):
    """One tiny ranged request: real file name, format and size of a direct link."""
    info = {"header_name": "", "url_name": "", "ctype": "", "size": 0}
    probe = dict(headers or {})
    probe.setdefault("User-Agent", engine.USER_AGENT)
    probe["Range"] = "bytes=0-0"
    probe["Accept-Encoding"] = "identity"
    try:
        with requests.get(url, headers=probe, stream=True, timeout=(10, 20),
                          allow_redirects=True) as resp:
            info["header_name"] = filename_from_headers(resp.headers)
            info["url_name"] = unquote(os.path.basename(urlparse(resp.url).path))
            info["ctype"] = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if resp.status_code == 206:
                match = re.search(r"/\s*(\d+)\s*$", resp.headers.get("Content-Range", ""))
                if match:
                    info["size"] = int(match.group(1))
            else:
                info["size"] = int(resp.headers.get("Content-Length") or 0)
    except Exception:                            # noqa: BLE001
        if not info["url_name"]:
            info["url_name"] = unquote(os.path.basename(urlparse(url).path))
    return info


def probe_media_title(url, headers):
    """Real video / audio title (and container) through yt-dlp - works for all
    sites yt-dlp supports. Returns ("", "") when it cannot be read."""
    try:
        info = yt_helper.media_info(url, headers)
    except Exception:                            # noqa: BLE001
        return "", ""
    if isinstance(info, dict) and "title" not in info and isinstance(info.get("info"), dict):
        info = info["info"]
    if not isinstance(info, dict):
        return "", ""
    title = str(info.get("title") or "").strip()
    ext = str(info.get("ext") or "").strip().lower().lstrip(".")
    return title, ("." + ext if ext else "")


def unique_path(path, reserved=()):
    """A path no file, half-downloaded part or other task (reserved) uses."""
    taken = {os.path.normcase(os.path.abspath(p)) for p in reserved if p}

    def free(candidate):
        return (not os.path.exists(candidate) and not os.path.exists(candidate + ".part")
                and os.path.normcase(os.path.abspath(candidate)) not in taken)

    if free(path):
        return path
    base, ext = os.path.splitext(path)
    for index in range(1, 1000):
        candidate = f"{base} ({index}){ext}"
        if free(candidate):
            return candidate
    return path


def format_size(size_bytes):
    try:
        size_bytes = float(size_bytes or 0)
    except (TypeError, ValueError):
        return "-"
    if size_bytes <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def format_eta(seconds):
    try:
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0 or seconds > 7 * 86400:
        return "-"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_date(timestamp):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(timestamp)))
    except (TypeError, ValueError, OSError):
        return ""


def category_of(task):
    if task.kind == "media":
        return "music" if task.quality == "audio" else "video"
    extension = os.path.splitext(task.name or "")[1].lower().lstrip(".")
    for category, extensions in EXT_CATEGORY.items():
        if extension in extensions:
            return category
    return "other"


CATEGORY_LABELS = dict(CATEGORIES)          # key -> display name


def category_icon(task):
    """A short two-char badge shown in the Download File Info dialog."""
    cat = category_of(task)
    return {"video": "🎬", "music": "🎵", "documents": "📄",
            "compressed": "🗜", "programs": "⚙", "other": "📁"}.get(cat, "📁")


def migrate_old_files():
    for name in ("history.json", "settings.json"):
        old = os.path.join(yt_helper.installed_dir(), name)
        new = os.path.join(DATA_DIR, name)
        if os.path.isfile(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)
            except OSError:
                pass


# ------------------------------------------------------------------- task model
class DownloadTask:
    def __init__(self, url="", name="", save_dir="", save_path="",
                 kind="file", quality="best", headers=None, autostart=True):
        self.id = uuid.uuid4().hex[:10]
        self.url = url
        self.name = name or "download"
        self.save_dir = save_dir or DEFAULT_DOWNLOAD_DIR
        self.save_path = save_path
        self.kind = kind
        self.quality = quality or "best"
        self.headers = dict(headers or {})
        self.autostart = autostart

        self.size = 0
        self.downloaded = 0
        self.speed = 0
        self.progress = 0.0
        self.status = "queued"
        self.error_msg = ""
        self.note = ""
        self.description = ""
        self.speed_limit = 0            # bytes/s, 0 = unlimited
        self.completion_action = "none"  # none | open | folder
        self.created_at = time.time()
        self.queue_id = "main"
        self.queue_wait = not autostart  # Download Later waits for Start Queue
        self.queue_order = self.created_at
        self.retry_count = 0
        self.retry_after = 0.0
        # media links the browser player really loaded (fallback when yt-dlp fails)
        self.streams = []
        # file name (no extension) this media task writes; chosen once
        self.output_stem = ""
        self.legacy_naming = False

        # runtime only
        self.stop_event = None
        self.pause_event = None
        self.limiter = None             # downloader.RateLimiter (files)
        self.removed = False
        self.runner = None
        self.segments = []

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "save_dir": self.save_dir,
            "save_path": self.save_path,
            "kind": self.kind,
            "quality": self.quality,
            "headers": self.headers,
            "size": self.size,
            "downloaded": self.downloaded,
            "speed": self.speed,
            "progress": self.progress,
            "status": self.status,
            "error_msg": self.error_msg,
            "description": self.description,
            "speed_limit": self.speed_limit,
            "completion_action": self.completion_action,
            "created_at": self.created_at,
            "queue_id": self.queue_id,
            "queue_wait": self.queue_wait,
            "queue_order": self.queue_order,
            "retry_count": self.retry_count,
            "streams": self.streams,
            "output_stem": self.output_stem,
        }

    @classmethod
    def from_dict(cls, data):
        task = cls(
            url=data.get("url", ""),
            name=data.get("name", "download"),
            save_dir=data.get("save_dir") or DEFAULT_DOWNLOAD_DIR,
            save_path=data.get("save_path", ""),
            kind=data.get("kind", "file"),
            quality=data.get("quality", "best"),
            headers=data.get("headers") or {},
            autostart=False,
        )
        task.id = data.get("id") or task.id
        task.size = int(data.get("size") or 0)
        task.downloaded = int(data.get("downloaded") or 0)
        task.speed = 0
        task.progress = float(data.get("progress") or 0)
        task.status = data.get("status") or "paused"
        task.error_msg = data.get("error_msg") or ""
        task.description = data.get("description") or ""
        task.speed_limit = int(data.get("speed_limit") or 0)
        task.completion_action = data.get("completion_action") or "none"
        task.created_at = data.get("created_at") or time.time()
        task.queue_id = data.get("queue_id") or "main"
        task.queue_wait = bool(data.get("queue_wait"))
        task.queue_order = float(data.get("queue_order") or task.created_at)
        task.retry_count = int(data.get("retry_count") or 0)
        task.streams = [s for s in (data.get("streams") or []) if isinstance(s, dict)]
        task.output_stem = str(data.get("output_stem") or "")
        # saved by an older version: its parts use yt-dlp's "title [id]" names
        task.legacy_naming = "output_stem" not in data and task.downloaded > 0
        if task.status in ("downloading", "queued", "pausing"):
            task.status = "paused"
        return task


# ------------------------------------------------------------- dialog prefetch
PREFETCH_DIR = os.path.join(DATA_DIR, "prefetch")


class _Prefetch:
    """Downloads into a temp folder while "Download File Info" is still open.

    When the user picks the folder, the part downloaded so far (plus its resume
    state) is moved there and the real download continues from it.
    """

    def __init__(self, app, task):
        self.folder = os.path.join(PREFETCH_DIR, task.id)
        os.makedirs(self.folder, exist_ok=True)
        self.temp_path = os.path.join(self.folder, "download.bin")
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.result = None
        self.runner = engine.MultiConnectionDownloader(
            task.url, self.temp_path, connections=app.connections,
            headers=task.headers, rate_limiter=engine.RateLimiter(task.speed_limit),
            dynamic=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def downloaded(self):
        return self.runner.downloaded or 0

    @property
    def total(self):
        return self.runner.total_size or 0

    def _run(self):
        try:
            self.result = self.runner.run(self.stop_event, self.pause_event)
        except Exception as exc:                 # noqa: BLE001
            self.result = (engine.ERROR, str(exc))

    def _cleanup(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def hand_over(self, final_path, done, post):
        """Stop, move the data to final_path, then post done(outcome) to the UI thread.

        outcome: "completed" (whole file already there), "partial" (resume from
        the moved .part) or "none" (nothing usable; download starts fresh).
        """
        def work():
            self.pause_event.set()
            self.thread.join(timeout=20)
            outcome = "none"
            if not self.thread.is_alive():
                status = (self.result or (None, ""))[0]
                try:
                    os.makedirs(os.path.dirname(final_path) or ".", exist_ok=True)
                    if status == engine.COMPLETED and os.path.isfile(self.temp_path):
                        shutil.move(self.temp_path, final_path)
                        outcome = "completed"
                    elif os.path.isfile(self.temp_path + ".part"):
                        shutil.move(self.temp_path + ".part", final_path + ".part")
                        state = self.temp_path + ".vibe.json"
                        if os.path.isfile(state):
                            shutil.move(state, final_path + ".vibe.json")
                        outcome = "partial"
                except OSError:
                    outcome = "none"
                    for leftover in (final_path + ".part", final_path + ".vibe.json"):
                        try:
                            os.remove(leftover)
                        except OSError:
                            pass
            else:
                self.stop_event.set()
            self._cleanup()
            post(lambda: done(outcome))

        threading.Thread(target=work, daemon=True).start()

    def discard(self):
        self.stop_event.set()

        def work():
            self.thread.join(timeout=30)
            self._cleanup()
        threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------------- api server
class ApiHandler(BaseHTTPRequestHandler):
    app = None
    server_version = "VibeDownloader/" + APP_VERSION

    def log_message(self, *args):
        pass

    def _allowed_origin(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return "*"
        allowed = (
            origin.startswith("chrome-extension://")
            or origin.startswith("moz-extension://")
            or origin.startswith("http://127.0.0.1")
            or origin.startswith("http://localhost")
        )
        return origin if allowed else None

    def _send_json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        if not self._allowed_origin():
            self._send_json({"status": "error", "error": "forbidden origin"}, 403)
            return
        origin = self._allowed_origin()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/ping", "/status"):
            self._send_json({
                "status": "ok",
                "app": APP_NAME,
                "version": APP_VERSION,
                "port": self.app.server_port,
                "ffmpeg": bool(yt_helper.find_ffmpeg()),
                "ytdlp": bool(yt_helper.find_ytdlp()),
                "downloads": len(self.app.tasks),
            })
        else:
            self._send_json({"status": "error", "error": "not found"}, 404)

    def do_POST(self):
        if not self._allowed_origin():
            self._send_json({"status": "error", "error": "forbidden origin"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:                 # noqa: BLE001
            self._send_json({"status": "error", "error": f"bad json: {exc}"}, 400)
            return

        action = (data.get("action") or "download").lower()
        try:
            if action == "test":
                self._send_json({"status": "ok", "port": self.app.server_port})
            elif action == "show":
                self.app.post(self.app._show_window)
                self._send_json({"status": "ok", "shown": True})
            elif action == "download":
                task_id = self.app.api_add(data)
                self._send_json({"status": "ok", "id": task_id})
            elif action == "grab":
                count = self.app.api_grab(data)
                self._send_json({"status": "ok", "count": count})
            elif action in ("info", "probe"):
                self._send_json({"status": "ok", "info": self.app.api_info(data)})
            else:
                self._send_json({"status": "error",
                                 "error": f"unknown action: {action}"}, 400)
        except Exception as exc:                 # noqa: BLE001
            self._send_json({"status": "error", "error": str(exc)}, 400)


# ------------------------------------------------------------------------ app
UI_FONT = ("Segoe UI", 9)
UI_FONT_BOLD = ("Segoe UI", 9, "bold")
SEG_BLUE = "#3C7FD8"          # segment blocks, connection map
SEG_EMPTY = C_PANEL if _IS_DARK else "#FFFFFF"


def _ensure_classic_style(root):
    """Classic Windows look (ttk 'vista') for the progress and complete dialogs."""
    if getattr(root, "_classic_style_ready", False):
        return
    style = ttk.Style(root)
    names = style.theme_names()
    if not _IS_DARK and "vista" in names:
        style.theme_use("vista")
    elif "clam" in names:
        style.theme_use("clam")
    bg = "#F0F0F0" if not _IS_DARK else C_BG
    fg = "#000000" if not _IS_DARK else C_TEXT
    style.configure("Vibe.TFrame", background=bg)
    style.configure("Vibe.TLabel", background=bg, foreground=fg, font=UI_FONT)
    style.configure("VibeKey.TLabel", background=bg, foreground=fg, font=UI_FONT)
    style.configure("VibeBold.TLabel", background=bg, foreground=fg, font=UI_FONT_BOLD)
    style.configure("Vibe.TButton", font=UI_FONT, padding=(10, 2))
    style.configure("Vibe.TCheckbutton", background=bg, foreground=fg, font=UI_FONT)
    style.configure("Vibe.TRadiobutton", background=bg, foreground=fg, font=UI_FONT)
    style.configure("Vibe.TNotebook", background=bg)
    style.configure("Vibe.TNotebook.Tab", font=UI_FONT, padding=(10, 3))
    style.configure("Vibe.Horizontal.TProgressbar", thickness=18)
    style.configure("Vibe.Treeview", font=UI_FONT, rowheight=18)
    style.configure("Vibe.Treeview.Heading", font=UI_FONT)
    if _IS_DARK:
        # flat, quiet dark palette - easy on the eyes
        style.configure("Vibe.TButton", background=C_BTN, foreground=C_TEXT,
                        bordercolor=C_BORDER, lightcolor=C_BTN, darkcolor=C_BTN,
                        focuscolor=C_BLUE)
        style.map("Vibe.TButton",
                  background=[("disabled", C_BG), ("pressed", C_SELECT),
                              ("active", C_BTN_HOVER)],
                  foreground=[("disabled", C_MUTED)])
        style.configure("Vibe.TNotebook", bordercolor=C_BORDER, lightcolor=C_BG,
                        darkcolor=C_BG, tabmargins=(0, 0, 0, 0))
        style.configure("Vibe.TNotebook.Tab", background=C_TOOLBAR, foreground=C_MUTED,
                        bordercolor=C_BORDER, lightcolor=C_TOOLBAR, darkcolor=C_TOOLBAR)
        style.map("Vibe.TNotebook.Tab",
                  background=[("selected", C_BG)],
                  foreground=[("selected", C_TEXT)],
                  lightcolor=[("selected", C_BG)])
        for name in ("Vibe.TCheckbutton", "Vibe.TRadiobutton"):
            style.configure(name, indicatorbackground=C_INPUT_BG,
                            indicatorforeground=C_TEXT, focuscolor=bg)
            style.map(name, background=[("active", bg)],
                      indicatorbackground=[("selected", C_BLUE)])
        style.configure("Vibe.Treeview", background=C_PANEL, fieldbackground=C_PANEL,
                        foreground=C_TEXT, bordercolor=C_BORDER,
                        lightcolor=C_PANEL, darkcolor=C_PANEL)
        style.configure("Vibe.Treeview.Heading", background=C_TOOLBAR, foreground=C_MUTED,
                        bordercolor=C_BORDER, lightcolor=C_TOOLBAR, darkcolor=C_TOOLBAR,
                        relief="flat")
        style.map("Vibe.Treeview.Heading", background=[("active", C_BTN_HOVER)])
        style.configure("Vibe.Horizontal.TProgressbar", background=C_GREEN,
                        troughcolor=C_PANEL, bordercolor=C_BORDER,
                        lightcolor=C_GREEN, darkcolor=C_GREEN)
        style.configure("Vibe.TSpinbox", fieldbackground=C_INPUT_BG, foreground=C_TEXT,
                        background=C_BTN, bordercolor=C_BORDER, arrowcolor=C_TEXT,
                        insertcolor=C_TEXT)
        style.configure("Vibe.Vertical.TScrollbar", background=C_BTN, troughcolor=C_PANEL,
                        bordercolor=C_BORDER, arrowcolor=C_MUTED,
                        lightcolor=C_BTN, darkcolor=C_BTN)
        style.configure("Vibe.TSeparator", background=C_BORDER)
    root._classic_style_ready = True
    root._classic_bg = bg


def _dark_title_bar(window):
    """Dark Windows title bar for a Toplevel when the dark theme is on."""
    if os.name != "nt" or not _IS_DARK:
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):               # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except Exception:                            # noqa: BLE001
        pass


def _short_url(url, limit=62):
    url = url or ""
    return url if len(url) <= limit else url[:limit - 3] + "..."


class _ProgressWindow:
    """Per-download progress window: Download status / Speed Limiter / Options."""

    def __init__(self, app, task):
        self.app = app
        self.task = task
        _ensure_classic_style(app)
        bg = app._classic_bg
        self.window = tk.Toplevel(app)
        self.window.title(f"0% {task.name} - {APP_DISPLAY_NAME}")
        self.window.configure(bg=bg)
        self.window.resizable(False, False)
        self._details_open = True
        self._closed = False

        outer = ttk.Frame(self.window, style="Vibe.TFrame", padding=(8, 8, 8, 8))
        outer.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(outer, style="Vibe.TNotebook")
        self.notebook.pack(fill="x")

        # ----------------------------------------------------- Download status
        status = ttk.Frame(self.notebook, style="Vibe.TFrame", padding=(10, 8))
        self.notebook.add(status, text="Download status")
        self._url = ttk.Label(status, text=_short_url(task.url), style="Vibe.TLabel")
        self._url.grid(row=0, column=0, columnspan=2, sticky="w")
        self._status = ttk.Label(status, text="Connecting...", style="Vibe.TLabel")
        self._status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 6))
        ttk.Separator(status, style="Vibe.TSeparator").grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self._fields = {}
        rows = [("size", "File size"), ("done", "Downloaded"),
                ("speed", "Transfer rate"), ("eta", "Time left"),
                ("resume", "Resume capability")]
        for i, (key, text) in enumerate(rows, start=3):
            ttk.Label(status, text=text, style="VibeKey.TLabel", width=18
                      ).grid(row=i, column=0, sticky="w", pady=1)
            val = ttk.Label(status, text="", style="Vibe.TLabel", width=40)
            val.grid(row=i, column=1, sticky="w", pady=1)
            self._fields[key] = val

        self._bar = ttk.Progressbar(status, style="Vibe.Horizontal.TProgressbar",
                                    orient="horizontal", mode="determinate",
                                    maximum=100, length=460)
        self._bar.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        # ------------------------------------------------------ Speed Limiter
        limit = ttk.Frame(self.notebook, style="Vibe.TFrame", padding=(12, 10))
        self.notebook.add(limit, text="Speed Limiter")
        self._limit_enable = tk.BooleanVar(value=bool(task.speed_limit))
        ttk.Checkbutton(limit, text="Use speed limiter", variable=self._limit_enable,
                        style="Vibe.TCheckbutton").pack(anchor="w")
        row = ttk.Frame(limit, style="Vibe.TFrame")
        row.pack(anchor="w", pady=(8, 4))
        ttk.Label(row, text="Maximum download speed", style="Vibe.TLabel").pack(side="left")
        self._limit_kb = tk.StringVar(value=str(max(1, (task.speed_limit or 0) // 1024) or 512))
        if not task.speed_limit:
            self._limit_kb.set("512")
        ttk.Spinbox(row, from_=1, to=1024000, increment=64, width=8,
                    textvariable=self._limit_kb, font=UI_FONT,
                    style="Vibe.TSpinbox").pack(side="left", padx=6)
        ttk.Label(row, text="KBytes/sec", style="Vibe.TLabel").pack(side="left")
        ttk.Label(limit, text="For video (yt-dlp) downloads the limit applies from the next Resume.",
                  style="Vibe.TLabel").pack(anchor="w", pady=(10, 0))

        # -------------------------------------------------- Options on completion
        opt = ttk.Frame(self.notebook, style="Vibe.TFrame", padding=(12, 10))
        self.notebook.add(opt, text="Options on completion")
        self._opt_var = tk.StringVar(value=task.completion_action or "none")
        for value, text in (("none", "Show download complete dialog"),
                            ("open", "Open the file when done"),
                            ("folder", "Open the folder when done")):
            ttk.Radiobutton(opt, text=text, value=value, variable=self._opt_var,
                            style="Vibe.TRadiobutton").pack(anchor="w", pady=2)

        # ------------------------------------------------------------- buttons
        buttons = ttk.Frame(outer, style="Vibe.TFrame")
        buttons.pack(fill="x", pady=(8, 0))
        self._details_btn = ttk.Button(buttons, text="<< Hide details", width=15,
                                       style="Vibe.TButton", command=self._toggle_details)
        self._details_btn.pack(side="left")
        self._cancel_btn = ttk.Button(buttons, text="Cancel", width=10,
                                      style="Vibe.TButton", command=self._cancel)
        self._cancel_btn.pack(side="right")
        self._start_btn = ttk.Button(buttons, text="Pause", width=10,
                                     style="Vibe.TButton", command=self._toggle_start)
        self._start_btn.pack(side="right", padx=(0, 6))

        # ------------------------------------------------------------- details
        self._details = ttk.Frame(outer, style="Vibe.TFrame")
        ttk.Label(self._details,
                  text="Start positions and download progress by connections",
                  style="Vibe.TLabel").pack(anchor="w", pady=(10, 3))
        self._seg_canvas = tk.Canvas(self._details, height=16, bg=SEG_EMPTY,
                                     highlightthickness=1,
                                     highlightbackground=C_BORDER if _IS_DARK else "#8E8F8F")
        self._seg_canvas.pack(fill="x")
        table = ttk.Frame(self._details, style="Vibe.TFrame")
        table.pack(fill="x", pady=(6, 0))
        self._conn = ttk.Treeview(table, columns=("n", "done", "info"), show="headings",
                                  height=6, style="Vibe.Treeview", selectmode="none")
        for col, text, width, anchor in (("n", "N.", 40, "center"),
                                         ("done", "Downloaded", 130, "e"),
                                         ("info", "Info", 290, "w")):
            self._conn.heading(col, text=text, anchor=anchor)
            self._conn.column(col, width=width, anchor=anchor, stretch=(col == "info"))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self._conn.yview,
                               style="Vibe.Vertical.TScrollbar")
        self._conn.configure(yscrollcommand=scroll.set)
        self._conn.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        self._details.pack(fill="x")

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.bind("<Escape>", lambda _e: self._on_close())
        self.app._center_window(self.window)
        window_frame.apply(self.window, maximize=False)
        self.window.after(50, self._tick)

    # ------------------------------------------------------------------ actions
    def _toggle_start(self):
        task = self.task
        if task.status == "downloading":
            self.app.pause_task(task)
        elif task.status in ("paused", "error"):
            self.app.start_task(task)

    def _cancel(self):
        # Cancel stops the transfer and closes the window; the file stays
        # in the list and can be resumed later.
        self.app.pause_task(self.task)
        self._on_close()

    def _toggle_details(self):
        self._details_open = not self._details_open
        if self._details_open:
            self._details.pack(fill="x")
            self._details_btn.configure(text="<< Hide details")
        else:
            self._details.pack_forget()
            self._details_btn.configure(text="Show details >>")

    def _on_close(self):
        self._closed = True
        self.app._progress_windows.pop(self.task.id, None)
        try:
            self.window.destroy()
        except Exception:                    # noqa: BLE001
            pass

    # ------------------------------------------------------------------ refresh
    @staticmethod
    def _status_text(task):
        status = task.status
        if status == "downloading":
            if task.note:
                return task.note
            return "Receiving data..." if (task.downloaded or 0) > 0 else "Connecting..."
        return {"pausing": "Pausing...", "paused": "Paused",
                "queued": "Waiting in queue", "completed": "Complete",
                "error": f"Error: {task.error_msg or 'unknown'}"}.get(status, status)

    def _apply_limit(self, task):
        try:
            kb = max(1, int(float(self._limit_kb.get() or 0)))
        except (TypeError, ValueError):
            return
        new_limit = kb * 1024 if self._limit_enable.get() else 0
        if new_limit != task.speed_limit:
            task.speed_limit = new_limit
            if task.limiter:
                task.limiter.set_limit(new_limit)

    def _tick(self):
        if self._closed:
            return
        task = self.app.tasks.get(self.task.id)
        if task is None:
            self._on_close()
            return
        self.task = task
        try:
            progress = float(task.progress or 0)
            size = task.size or 0
            done = task.downloaded or 0
            self.window.title(f"{int(progress)}% {task.name} - {APP_DISPLAY_NAME}")
            task.completion_action = self._opt_var.get()
            self._apply_limit(task)

            self._url.configure(text=_short_url(task.url))
            self._status.configure(text=self._status_text(task))
            self._fields["size"].configure(text=format_size(size) if size else "Unknown")
            self._fields["done"].configure(
                text=(f"{format_size(done)} ( {progress:.2f} % )" if size
                      else format_size(done)))
            self._fields["speed"].configure(
                text=f"{format_size(task.speed)}/sec" if task.speed else "")
            remaining = max(0, size - done)
            self._fields["eta"].configure(
                text=format_eta(remaining / task.speed) if (task.speed and size) else "")
            runner = getattr(task, "runner", None)
            if task.kind == "media":
                resume = "Yes"
            elif runner is not None and hasattr(runner, "ranges_ok") and runner.total_size:
                resume = "Yes" if runner.ranges_ok else "No"
            else:
                resume = ""
            self._fields["resume"].configure(text=resume)
            self._bar.configure(value=max(0.0, min(100.0, progress)))

            if task.status in ("downloading", "pausing"):
                self._start_btn.configure(text="Pause", state="normal")
            elif task.status in ("paused", "error"):
                self._start_btn.configure(text="Resume", state="normal")
            else:
                self._start_btn.configure(state="disabled")

            if self._details_open:
                self._draw_segments(task)
                self._fill_connections(task)
        except Exception:                    # noqa: BLE001
            pass
        self.window.after(500, self._tick)

    def _fill_connections(self, task):
        segments = list(getattr(task, "segments", None) or [])
        if not segments:
            if task.status == "downloading":
                info = "Receiving data..." if task.downloaded else "Connecting..."
                segments_rows = [("1", format_size(task.downloaded or 0), info)]
            else:
                segments_rows = []
        else:
            segments_rows = []
            for i, seg in enumerate(segments, start=1):
                if seg.get("complete"):
                    info = "Finished"
                elif task.status == "downloading":
                    info = "Receiving data..." if seg.get("done") else "Connecting..."
                else:
                    info = self._status_text(task)
                segments_rows.append((str(i), format_size(seg.get("done") or 0), info))
        existing = self._conn.get_children()
        for index, values in enumerate(segments_rows):
            if index < len(existing):
                self._conn.item(existing[index], values=values)
            else:
                self._conn.insert("", "end", values=values)
        for extra in existing[len(segments_rows):]:
            self._conn.delete(extra)

    def _draw_segments(self, task):
        canvas = self._seg_canvas
        try:
            width = max(canvas.winfo_width(), 200)
            height = int(canvas.cget("height"))
            canvas.delete("all")
            segments = list(getattr(task, "segments", None) or [])
            total = max(task.size or 0, 1)
            if not segments:
                filled = int(width * min(1.0, (task.downloaded or 0) / total)) if task.size else 0
                if filled:
                    canvas.create_rectangle(0, 0, filled, height + 2,
                                            fill=SEG_BLUE, width=0)
                return
            for seg in segments:
                start = int(seg.get("start") or 0)
                end = int(seg.get("end") or start)
                done = int(seg.get("done") or 0)
                x0 = int(start * width / total)
                x1 = max(x0 + 1, int((end + 1) * width / total))
                span = max(1, end - start + 1)
                filled = x0 + int(min(done, span) * (x1 - x0) / span)
                if filled > x0:
                    canvas.create_rectangle(x0, 0, filled, height + 2,
                                            fill=SEG_BLUE, width=0)
                canvas.create_line(x0, 0, x0, height + 2,
                                   fill=C_BORDER if _IS_DARK else "#8E8F8F")
        except Exception:                    # noqa: BLE001
            pass


class _CompleteDialog:
    """"Download complete" dialog: Open / Open with / Open folder / Close."""

    def __init__(self, app, task):
        self.app = app
        _ensure_classic_style(app)
        win = self.window = tk.Toplevel(app)
        win.title(f"Download complete - {APP_DISPLAY_NAME}")
        win.configure(bg=app._classic_bg)
        win.resizable(False, False)

        outer = ttk.Frame(win, style="Vibe.TFrame", padding=(14, 12))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Download complete", style="VibeBold.TLabel"
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        path = task.save_path or os.path.join(task.save_dir or "", task.name)
        rows = (("Downloaded", format_size(task.size or task.downloaded or 0)),
                ("Address", _short_url(task.url, 70)),
                ("The file saved as", _short_url(path, 70)))
        for i, (key, value) in enumerate(rows, start=1):
            ttk.Label(outer, text=key, style="VibeKey.TLabel", width=16
                      ).grid(row=i, column=0, sticky="w", pady=1)
            ttk.Label(outer, text=value, style="Vibe.TLabel"
                      ).grid(row=i, column=1, sticky="w", pady=1)

        self._dont_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text="Don't show this dialog again",
                        variable=self._dont_show, style="Vibe.TCheckbutton"
                        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(outer, style="Vibe.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        has_file = bool(task.save_path and os.path.isfile(task.save_path))
        open_btn = ttk.Button(buttons, text="Open", width=11, style="Vibe.TButton",
                              command=lambda: self._do(lambda: app.open_task_file(task)))
        open_btn.pack(side="left", padx=3)
        with_btn = ttk.Button(buttons, text="Open with...", width=11, style="Vibe.TButton",
                              command=lambda: self._do(lambda: self._open_with(task.save_path)))
        with_btn.pack(side="left", padx=3)
        if not has_file:
            open_btn.state(["disabled"])
            with_btn.state(["disabled"])
        ttk.Button(buttons, text="Open folder", width=11, style="Vibe.TButton",
                   command=lambda: self._do(lambda: app.open_task_folder(task))
                   ).pack(side="left", padx=3)
        ttk.Button(buttons, text="Close", width=11, style="Vibe.TButton",
                   command=self._close).pack(side="left", padx=3)

        win.protocol("WM_DELETE_WINDOW", self._close)
        win.bind("<Escape>", lambda _e: self._close())
        app._center_window(win)
        window_frame.apply(win, minimize=False, maximize=False)
        win.after(60, lambda: (win.lift(), win.focus_force()))

    @staticmethod
    def _open_with(path):
        if os.name == "nt" and path and os.path.isfile(path):
            try:
                subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
            except OSError:
                pass

    def _do(self, action):
        try:
            action()
        finally:
            self._close()

    def _close(self):
        if self._dont_show.get():
            self.app.settings["show_complete_dialog"] = False
            self.app.save_settings()
        try:
            self.window.destroy()
        except Exception:                    # noqa: BLE001
            pass


# ----------------------------------------------------- lightweight list rows
ROW_FONT = ("Segoe UI", -12)
ROW_FONT_BOLD = ("Segoe UI", -12, "bold")


class _Cell(tk.Label):
    """tk.Label that also accepts the CustomTkinter option names used here."""

    def __init__(self, master, **kw):
        kw.setdefault("bg", master.cget("bg"))
        kw.setdefault("font", ROW_FONT)
        kw.setdefault("text", "")
        kw.setdefault("width", 1)          # take the column's width, never widen it
        super().__init__(master, bd=0, padx=0, pady=0, **kw)

    def configure(self, cnf=None, **kw):
        if "text_color" in kw:
            kw["fg"] = kw.pop("text_color")
        if "fg_color" in kw:
            kw["bg"] = kw.pop("fg_color")
        if isinstance(kw.get("font"), ctk.CTkFont):
            kw["font"] = ROW_FONT_BOLD if kw["font"].cget("weight") == "bold" else ROW_FONT
        # skip no-op updates: the list refreshes several times a second
        kw = {key: value for key, value in kw.items() if str(self.cget(key)) != str(value)}
        if kw or cnf:
            return super().configure(cnf, **kw)
        return None

    config = configure


class _RowFrame(tk.Frame):
    """Row background; changing it recolors every cell in the row."""

    def __init__(self, master, **kw):
        super().__init__(master, bd=0, highlightthickness=0, **kw)

    def configure(self, cnf=None, **kw):
        if "fg_color" in kw:
            kw["bg"] = kw.pop("fg_color")
        if "bg" in kw and str(self.cget("bg")) == str(kw["bg"]):
            kw.pop("bg")
        elif "bg" in kw:
            for child in self.winfo_children():
                if isinstance(child, _Cell):
                    tk.Label.configure(child, bg=kw["bg"])
                elif isinstance(child, _RowProgress):
                    tk.Frame.configure(child, bg=kw["bg"])
        if kw or cnf:
            return super().configure(cnf, **kw)
        return None

    config = configure


class _RowProgress(tk.Frame):
    """2 px progress line at the bottom of a row (CTkProgressBar-compatible API)."""

    def __init__(self, master, color=C_BLUE):
        super().__init__(master, bg=master.cget("bg"), height=2, bd=0, highlightthickness=0)
        self._fill = tk.Frame(self, bg=color, height=2, bd=0, highlightthickness=0)
        self._value = -1.0

    def set(self, value):
        value = max(0.0, min(1.0, float(value or 0)))
        if abs(value - self._value) < 0.001:
            return
        self._value = value
        if value <= 0:
            self._fill.place_forget()
        else:
            self._fill.place(relx=0, rely=0, relheight=1.0, relwidth=value)

    def configure(self, cnf=None, **kw):
        color = kw.pop("progress_color", None)
        if color and str(self._fill.cget("bg")) != str(color):
            self._fill.configure(bg=color)
        if kw or cnf:
            return super().configure(cnf, **kw)
        return None

    config = configure


class VibeDownloaderApp(ctk.CTk):
    def __init__(self, startup_launch=False):
        super().__init__()
        self.startup_launch = bool(startup_launch)
        if self.startup_launch:
            self.withdraw()
        self.title(f"{APP_DISPLAY_NAME} {APP_VERSION}")
        # a medium window by default (maximize for more); never larger than the screen
        width = min(960, max(800, self.winfo_screenwidth() - 160))
        height = min(580, max(460, self.winfo_screenheight() - 180))
        # open in the middle of the screen (the title bar adds ~36 px, the taskbar ~40)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - 40 - (height + 36)) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(760, 440)
        self.configure(fg_color=C_BG)
        migrate_old_files()

        self.tasks = {}
        self.rows = {}
        self.selected_id = None
        self.running = True
        self.ui_queue = queue.Queue()
        self.lock = threading.RLock()
        self.history_lock = threading.Lock()

        self.server_port = DEFAULT_SETTINGS["port"]
        self.httpd = None
        self.settings = dict(DEFAULT_SETTINGS)
        self.current_category = "all"
        self._download_dialog_queue = queue.Queue()
        self._download_dialog_open = False
        self._progress_windows = {}      # task_id -> _ProgressWindow
        self._menu_window = None
        self.tray_icon = None
        self._toolbar_images = {}
        self._toolbar_photo_refs = []  # keep PhotoImage alive
        self.toolbar_buttons = {}
        self._sort_column = "date"
        self._sort_reverse = True
        self._last_order = []
        self.category_ids = {}          # kept for compatibility
        self.search_text = ""
        self._last_clip = ""
        self._ignore_clip = ""
        self._queue_had_work = False
        self._queue_action_fired = False
        self._pending_update = None
        self._update_dialog = None
        self._update_check_running = False
        self._update_install_running = False
        self._update_shutdown = False
        self._schedule_holding = False

        self.load_settings()
        self.load_history()
        # leftovers of "Download File Info" prefetches from a previous run
        shutil.rmtree(PREFETCH_DIR, ignore_errors=True)

        self.create_menubar()
        self.create_widgets()
        self._apply_window_icon()
        self.update_stats()
        self.render()

        self.worker = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.worker.start()
        self.start_server()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Control-n>", lambda _event: self.open_add_dialog())
        self.bind("<Delete>", lambda _event: self.remove_selected())
        self.bind("<Control-f>", lambda _event: self.focus_search())
        self.bind("<space>", lambda _event: self._space_toggle())
        self.after(300, self._tick)
        self.after(400, self._apply_window_icon)
        # our own themed title bar instead of the Windows caption
        window_frame.apply(self)
        self.after(800, self._seed_clipboard)
        self.after(500, self._enable_file_drop)
        # The tray endpoint exists for the whole app lifetime, not only after
        # the user closes the window. This mirrors a resident download manager.
        self.after(250, self._start_tray)
        if self.startup_launch and self.settings.get("start_minimized", True):
            self.after(0, self.withdraw)

        # Check at startup and while resident in the tray, at most every 12 h.
        # The timer also allows enabling checks without restarting the app.
        self.after(4000, self._auto_update_check)

    # ------------------------------------------------------------- persistence
    def load_settings(self):
        migrated_ui = False
        migrated_clip = False
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                migrated_ui = int(data.get("ui_revision") or 0) < UI_REVISION
                for key, value in DEFAULT_SETTINGS.items():
                    if key in data:
                        self.settings[key] = data[key]
                if not data.get("clipboard_default_v2"):
                    # one-time: older builds enabled clipboard catching by default
                    self.settings["clipboard_monitor"] = False
                    self.settings["clipboard_default_v2"] = True
                    migrated_clip = True
                if not data.get("theme_default_dark"):
                    # one-time: dark is the default theme now
                    self.settings["theme"] = "dark"
                    self.settings["theme_default_dark"] = True
                    migrated_clip = True
            except Exception:                    # noqa: BLE001
                pass
        if migrated_ui:
            self.settings["ui_revision"] = UI_REVISION
        save_dir = self.settings.get("default_save_dir") or DEFAULT_DOWNLOAD_DIR
        if not os.path.isdir(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)      # e.g. a deleted folder
            except OSError:
                pass
        if not os.path.isdir(save_dir):
            # the drive (USB, NAS, D:) is not ready yet: use Downloads for now,
            # but keep the user's choice saved for the next start
            save_dir = DEFAULT_DOWNLOAD_DIR
        else:
            self.settings["default_save_dir"] = save_dir
        self.default_save_dir = save_dir
        self.max_concurrent = max(1, int(self.settings.get("max_concurrent") or 3))
        self.connections = max(1, int(self.settings.get("connections") or 8))
        self.server_port = int(self.settings.get("port") or 8765)
        self.queue_running = bool(self.settings.get("queue_running", True))
        if migrated_ui or migrated_clip:
            self.save_settings()
        self._sync_windows_startup()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
                json.dump(self.settings, handle, indent=2)
        except OSError:
            pass

    def load_history(self):
        if not os.path.isfile(HISTORY_FILE):
            return
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            for item in data:
                task = DownloadTask.from_dict(item)
                self.tasks[task.id] = task
        except Exception:                        # noqa: BLE001
            pass

    def save_history(self):
        with self.history_lock:
            try:
                payload = [task.to_dict() for task in list(self.tasks.values())]
                tmp = HISTORY_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
                os.replace(tmp, HISTORY_FILE)
            except Exception:                    # noqa: BLE001
                pass

    # ------------------------------------------------------------------- menu
    def create_menubar(self):
        """Custom dark menu bar: never light, works in dark theme."""
        bar = ctk.CTkFrame(self, height=28, fg_color=C_TOOLBAR, corner_radius=0,
                           border_width=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        menus = [
            ("Tasks", [
                ("Add URL...\tCtrl+N", self.open_add_dialog),
                ("Add URL from clipboard", self.add_from_clipboard),
                None,
                ("Start / Resume", self.start_selected),
                ("Stop", self.stop_selected),
                ("Stop All", self.pause_all),
                None,
                ("Delete\tDel", self.remove_selected),
                ("Delete All Completed", self.clear_completed),
                None,
                ("Exit", self._real_close),
            ]),
            ("File", [
                ("Open downloaded file", self.open_selected_file),
                ("Open download folder", self.open_selected_folder),
                ("Download properties", self._open_selected_progress),
                ("Copy download address", self.copy_selected_url),
            ]),
            ("Downloads", [
                ("Start All", self.start_all),
                ("Stop All", self.pause_all),
                ("Start Queue", self.start_queue),
                ("Stop Queue", self.stop_queue),
                None,
                ("Scheduler...", self.open_scheduler),
                ("Options...", self.open_settings),
            ]),
            ("View", [(label, (lambda k=key: self.select_category(k)))
                      for key, label in CATEGORIES]
                      + [
                          None,
                          ("Unfinished", lambda: self.select_category("unfinished")),
                          ("Finished", lambda: self.select_category("finished")),
                          None,
                          ("Search...\tCtrl+F", self.focus_search),
                      ]),
            ("Help", [
                ("Install / Reload Browser Extension", self.install_extension),
                ("Check for Updates", self.check_for_updates),
                None,
                ("About BD Downloader", self.show_about),
            ]),
        ]

        for index, (label, items) in enumerate(menus):
            button = ctk.CTkButton(
                bar, text=label, width=70, height=22, corner_radius=3,
                fg_color="transparent", hover_color=C_BTN,
                text_color=C_TEXT,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=lambda i=items: None)
            button.pack(side="left", padx=(8 if index == 0 else 0, 0), pady=3)
            button.configure(command=lambda b=button, i=items: self._popup_menu(b, i))

        self._menu_window = None
        self.bind("<Button-1>", self._close_menu_event, add="+")

    def _close_menu_event(self, _event=None):
        self._close_menu()

    def _popup_menu(self, button, items):
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        self._show_popup(x, y, items)

    def _show_popup(self, x, y, items):
        self._close_menu()
        top = ctk.CTkToplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(fg_color=C_BORDER)
        self._menu_window = top

        frame = ctk.CTkFrame(top, fg_color=C_PANEL, corner_radius=0,
                             border_width=0)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        for item in items:
            if item is None:
                ctk.CTkFrame(frame, height=1, fg_color=C_BORDER).pack(
                    fill="x", padx=6, pady=3)
                continue
            label, command = item
            ctk.CTkButton(
                frame, text=label, anchor="w", height=26, width=230,
                corner_radius=3, fg_color="transparent", hover_color=C_BLUE,
                text_color=C_TEXT,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=lambda c=command: self._run_menu_command(c)
            ).pack(fill="x", padx=4, pady=1)

        top.update_idletasks()
        height = top.winfo_reqheight()
        try:
            screen_h = self.winfo_screenheight()
            if y + height > screen_h - 8:
                y = max(8, y - height - 30)
        except Exception:                        # noqa: BLE001
            pass
        top.geometry(f"+{x}+{y}")
        top.lift()
        top.focus_force()
        top.bind("<Escape>", lambda _event: self._close_menu())

    def _run_menu_command(self, command):
        self._close_menu()
        try:
            command()
        except Exception:                        # noqa: BLE001
            pass

    def _close_menu(self):
        window = getattr(self, "_menu_window", None)
        if window is not None:
            try:
                window.destroy()
            except Exception:                    # noqa: BLE001
                pass
            self._menu_window = None

    def _enable_dark_title_bar(self):
        if os.name != "nt" or not _IS_DARK:
            return
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):           # DWMWA_USE_IMMERSIVE_DARK_MODE
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled),
                    ctypes.sizeof(enabled))
        except Exception:                        # noqa: BLE001
            pass

    # ------------------------------------------------------------------- UI
    def create_widgets(self):
        # ---- large selection-aware toolbar ----
        self._load_toolbar_icons()
        toolbar = tk.Frame(self, bg=C_TOOLBAR, height=74)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)
        # thin highlight along the top edge: a subtle glossy layer look
        tk.Frame(toolbar, bg=C_SHEEN, height=1).place(relx=0, rely=0, relwidth=1.0)
        toolbar.configure(highlightthickness=0)

        icon_for = {
            "Add URL": "add", "Resume": "resume", "Stop": "stop",
            "Stop All": "stop_all", "Delete": "delete",
            "Clear Completed": "clear", "Options": "options",
            "Scheduler": "scheduler", "Start Queue": "start_queue",
            "Stop Queue": "stop_queue",
        }
        for item in self._toolbar_items():
            label, command, state_hint = item
            img = self._toolbar_images.get(icon_for.get(label, ""), None)
            btn = ctk.CTkButton(
                toolbar,
                text=label,
                image=img,
                compound="top",
                command=command,
                font=ctk.CTkFont(family="Segoe UI", size=9),
                fg_color=C_BLUE if label == "Add URL" else C_BTN,
                hover_color=C_BLUE_HOVER if label == "Add URL" else C_BTN_HOVER,
                text_color="white" if label == "Add URL" else C_TEXT,
                border_width=0,
                corner_radius=4,
                width=76,
                height=64,
            )
            btn.pack(side="left", padx=1, pady=4)
            self.toolbar_buttons[label] = btn
        # (the browser extension is installed from Downloads/Help menus and Options)

        self.connection_label = ctk.CTkLabel(
            toolbar, text="", font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=C_MUTED)
        self.connection_label.pack(side="right", padx=(4, 10))
        # no textvariable: CustomTkinter hides the placeholder when one is set
        self.search_entry = ctk.CTkEntry(
            toolbar, width=190, height=30, corner_radius=4,
            placeholder_text="\U0001F50D  Search downloads",
            placeholder_text_color=C_MUTED,
            fg_color=C_INPUT_BG, border_color=C_BORDER, text_color=C_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=11))
        self.search_entry.pack(side="right", padx=(4, 6))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._on_search())

        # ---- body (classic tree + table layout) ----
        body = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # left categories
        sidebar = ctk.CTkFrame(body, width=168, fg_color=C_PANEL,
                               border_width=1, border_color=C_BORDER)
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="Categories", anchor="w",
                     font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                     text_color=C_MUTED).pack(fill="x", padx=8, pady=(6, 3))

        cat_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        cat_frame.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        self.category_buttons = {}
        # created once and reused (a new CTkFont per refresh leaked Tk fonts)
        self._cat_fonts = {False: ctk.CTkFont(family="Segoe UI", size=11),
                           True: ctk.CTkFont(family="Segoe UI", size=11, weight="bold")}
        for key, label in CATEGORIES:
            btn = ctk.CTkButton(
                cat_frame,
                text=f"{label}  (0)",
                anchor="w",
                height=28,
                corner_radius=4,
                fg_color="transparent",
                hover_color=C_SELECT if key == "all" else C_BTN,
                text_color=C_BLUE if key == "all" else C_TEXT,
                font=ctk.CTkFont(family="Segoe UI", size=11,
                                 weight="bold" if key == "all" else "normal"),
                command=lambda k=key: self.select_category(k))
            btn.pack(fill="x", pady=1)
            self.category_buttons[key] = btn

        for extra_key, extra_label in (("unfinished", "Unfinished"),
                                        ("finished", "Finished"),
                                        ("grabber", "Grabber projects"),
                                        ("queues", "Queues")):
            btn = ctk.CTkButton(
                cat_frame,
                text=extra_label,
                anchor="w",
                height=28,
                corner_radius=4,
                fg_color="transparent",
                hover_color=C_BTN,
                text_color=C_TEXT,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                command=lambda k=extra_key: self.select_category(k))
            btn.pack(fill="x", pady=1)
            self.category_buttons[extra_key] = btn
        ctk.CTkLabel(sidebar, text="Double-click a download\nto open the file.",
                     justify="left", anchor="w",
                     font=ctk.CTkFont(family="Segoe UI", size=9),
                     text_color=C_MUTED).pack(fill="x", padx=8, pady=6)

        # right table
        panel = ctk.CTkFrame(body, fg_color=C_PANEL, border_width=1,
                             border_color=C_BORDER)
        panel.pack(side="left", fill="both", expand=True)

        # header row for the rich table
        self.header_frame = ctk.CTkFrame(panel, fg_color=C_TOOLBAR, height=24,
                                         corner_radius=0)
        # right padding = the list's scrollbar, so header and rows line up
        self.header_frame.pack(fill="x", padx=(0, 18))
        self.header_frame.pack_propagate(False)
        self._configure_columns(self.header_frame)
        self._header_labels = {}
        header_font = ctk.CTkFont(family="Segoe UI", size=10, weight="bold")
        for index, (col, text, _minsize, align) in enumerate(COLUMNS):
            anchor_map = {"w": "w", "e": "e", "center": "center"}
            header = ctk.CTkButton(
                self.header_frame, text=text, anchor=anchor_map.get(align, "w"),
                font=header_font, width=1,      # width=1: follow the column, like the rows
                text_color=C_TEXT, fg_color="transparent", hover_color=C_BTN,
                height=22, corner_radius=0,
                command=lambda c=col: self._sort_by(c))
            header.grid(row=0, column=index, sticky="ew",
                        padx=((10, 4) if index == 0 else (4, 4)), pady=1)
            self._header_labels[col] = header

        self.list_container = ctk.CTkScrollableFrame(panel, fg_color=C_PANEL,
                                                     corner_radius=0)
        self.list_container.pack(fill="both", expand=True)

        self.empty_label = ctk.CTkLabel(
            self.list_container,
            text="No downloads here yet.\n\n"
                 "Click “Add URL”, or click any download link in Chrome / Edge — "
                 "it will be caught automatically.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#6E7681", justify="center")
        self.empty_label.pack(pady=70)

        # ---- status bar ----
        status = ctk.CTkFrame(self, height=26, fg_color=C_TOOLBAR, corner_radius=0,
                              border_width=1, border_color=C_BORDER)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)

        self.status_bar = ctk.CTkLabel(
            status, text="Ready", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11), text_color=C_MUTED)
        self.status_bar.pack(side="left", padx=10)

        self.stats_label = ctk.CTkLabel(
            status, text="", anchor="e",
            font=ctk.CTkFont(family="Segoe UI", size=11), text_color=C_MUTED)
        self.stats_label.pack(side="right", padx=10)

    def _toolbar_items(self):
        return [
            ("Add URL", self.open_add_dialog, True),
            ("Resume", self.start_selected, False),
            ("Stop", self.stop_selected, False),
            ("Stop All", self.pause_all, False),
            ("Delete", self.remove_selected, False),
            ("Clear Completed", self.clear_completed, False),
            ("Options", self.open_settings, False),
            ("Scheduler", self.open_scheduler, False),
            ("Start Queue", self.start_queue, False),
            ("Stop Queue", self.stop_queue, False),
        ]

    def _load_toolbar_icons(self):
        self._toolbar_photo_refs = []
        for name in ("add", "resume", "stop", "stop_all", "delete",
                     "clear", "options", "scheduler",
                     "start_queue", "stop_queue"):
            try:
                icon = toolbar_icon(name, size=32)
                photo = ctk.CTkImage(light_image=icon, dark_image=icon, size=(28, 28))
                self._toolbar_photo_refs.append(photo)
                self._toolbar_images[name] = photo
            except Exception:                    # noqa: BLE001
                pass

    def _apply_window_icon(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VibeDownloader.ico")
        if not os.path.isfile(path):
            return
        try:
            self.iconbitmap(default=path)
        except Exception:                        # noqa: BLE001
            try:
                self.iconbitmap(path)
            except Exception:                    # noqa: BLE001
                pass
        try:
            image = Image.open(path).convert("RGBA")
            photo = ImageTk.PhotoImage(image.resize((32, 32)))
            self._window_icon_photo = photo
            self.iconphoto(True, photo)
        except Exception:                        # noqa: BLE001
            pass

    def _configure_columns(self, frame):
        # only File Name stretches; fixed columns keep header and rows aligned
        for index, (col, _text, minsize, _align) in enumerate(COLUMNS):
            frame.grid_columnconfigure(index, weight=1 if col == "name" else 0,
                                       minsize=minsize)

    def _category_selected(self, _event=None):
        pass  # CTkButton clicks handle selection directly

    # --------------------------------------------------------------- selection
    def select_category(self, key):
        self.current_category = key
        if hasattr(self, "category_tree"):
            try:
                self.category_tree.selection_set(self.category_ids.get(key))
            except Exception:                    # noqa: BLE001
                pass
        # Update CTk button highlights
        if hasattr(self, "category_buttons"):
            for k, btn in self.category_buttons.items():
                active = k == key
                try:
                    btn.configure(
                        fg_color=C_SELECT if active else "transparent",
                        text_color=C_BLUE if active else C_TEXT,
                        font=self._cat_fonts[bool(active)])
                except Exception:                    # noqa: BLE001
                    pass
        self.render()

    def select_task(self, task_id):
        self.selected_id = task_id
        for row_id, row in self.rows.items():
            selected = row_id == task_id
            try:
                row["frame"].configure(fg_color=C_SELECT if selected
                                       else row["base_color"])
            except Exception:                    # noqa: BLE001
                pass

    def _update_selection_states(self):
        for label, btn in self.toolbar_buttons.items():
            selected = self.selected_task()
            enabled = False
            if label == "Resume":
                enabled = bool(selected and selected.status in ("paused", "error", "queued"))
            elif label == "Stop":
                enabled = bool(selected and selected.status == "downloading")
            elif label == "Delete":
                enabled = bool(selected)
            elif label == "Clear Completed":
                enabled = any(t.status == "completed" for t in self.tasks.values())
            elif label in ("Stop All", "Stop Queue"):
                enabled = any(t.status == "downloading" for t in self.tasks.values()) or self.queue_running
            elif label == "Start Queue":
                enabled = not self.queue_running or any(
                    t.status in ("queued", "paused", "error") for t in self.tasks.values())
            elif label in ("Add URL", "Options", "Scheduler"):
                enabled = True
            try:
                btn.configure(state="normal" if enabled else "disabled")
            except Exception:                    # noqa: BLE001
                pass

    def selected_task(self):
        return self.tasks.get(self.selected_id) if self.selected_id else None

    # ------------------------------------------------------------ task creation
    def add_from_clipboard(self):
        text = self._clipboard_url()
        if not text:
            self.show_status("Clipboard does not contain a link", "warning")
            return
        self.open_add_dialog(text)

    def _clipboard_url(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:                        # noqa: BLE001
            return ""
        if re.match(r"^https?://\S+$", text) and "\n" not in text:
            return text
        return ""

    def add_url(self, url, filename=None, kind="auto", quality="best",
                headers=None, referrer=None, save_dir=None, autostart=True):
        if kind == "auto":
            kind = "media" if yt_helper.is_media_url(url) else "file"

        headers = dict(headers or {})
        if referrer:
            headers.setdefault("Referer", referrer)

        if kind == "file" and not filename:
            self.show_status("Reading file name...")
            threading.Thread(target=self._resolve_and_add,
                             args=(url, headers, quality, save_dir, autostart),
                             daemon=True).start()
            return

        task = self._build_task(url, filename, kind, quality, headers,
                                save_dir=save_dir, autostart=autostart)
        self._register_task(task)

    def _resolve_and_add(self, url, headers, quality, save_dir, autostart):
        filename = ""
        try:
            probe_headers = dict(headers)
            probe_headers.setdefault("User-Agent", engine.USER_AGENT)
            probe_headers["Accept-Encoding"] = "identity"
            response = requests.get(url, headers=probe_headers, stream=True,
                                    timeout=(10, 20), allow_redirects=True)
            try:
                filename = filename_from_headers(response.headers)
                if not filename:
                    filename = os.path.basename(urlparse(response.url).path)
            finally:
                response.close()
        except Exception:                        # noqa: BLE001
            filename = os.path.basename(urlparse(url).path) or "download.bin"

        task = self._build_task(url, filename, "file", quality, headers,
                                save_dir=save_dir, autostart=autostart)
        self.post(lambda: self._register_task(task))

    def _resolve_task_name(self, task, given=""):
        """Blocking - run in a thread. Finds the real title + format."""
        if task.kind == "media":
            title, ext = probe_media_title(task.url, task.headers)
            if yt_helper.is_generic_title(title, task.url):
                title = yt_helper.clean_page_title(given) or title
            title = sanitize_filename(title) or sanitize_filename(given) or "video"
            if ext.lstrip(".") in EXT_CATEGORY["music"]:
                suffix = ext
            else:
                suffix = ".mp3" if task.quality == "audio" else ".mp4"
            return {"name": title, "display": title + suffix, "size": 0}
        info = probe_file_info(task.url, task.headers)
        name = choose_filename(info["header_name"], given, info["url_name"], info["ctype"])
        return {"name": name, "display": name, "size": info["size"]}

    def _apply_resolved(self, task, res):
        """Used when no dialog is shown (ask_save_path off)."""
        name = (res or {}).get("name")
        if name:
            task.name = name
        if task.kind != "media":
            task.save_path = unique_path(os.path.join(
                task.save_dir or self.default_save_dir, task.name), self._task_paths(task))
            task.name = os.path.basename(task.save_path)
        self._register_task(task)

    def _build_task(self, url, filename, kind, quality, headers,
                    save_dir=None, autostart=True):
        folder = save_dir or self.default_save_dir
        filename = sanitize_filename(filename)
        if kind == "media":
            name = sanitize_filename(yt_helper.clean_page_title(filename)) or filename or "media"
            save_path = ""
        else:
            if not filename:
                filename = "download.bin"
            elif "." not in filename:
                filename += ".bin"
            save_path = unique_path(os.path.join(folder, filename), self._task_paths())
            name = os.path.basename(save_path)
        return DownloadTask(url=url, name=name, save_dir=folder,
                            save_path=save_path, kind=kind, quality=quality,
                            headers=headers, autostart=autostart)

    def _register_task(self, task):
        self.tasks[task.id] = task
        task.queue_id = task.queue_id or "main"
        if not task.queue_order:
            task.queue_order = time.time()
        if task.autostart and self.settings.get("auto_start", True):
            task.status = "queued"
            task.queue_wait = False
        else:
            task.status = "queued"
            task.queue_wait = True
        if self.current_category != "all" and category_of(task) != self.current_category:
            self.current_category = "all"
            self.select_category("all")
        self.selected_id = task.id
        self.save_history()
        self.show_status(f"Added: {task.name}", "success")
        self.render()
        self.update_stats()

    # ------------------------------------------------------------ api endpoints
    def api_add(self, data):
        url = (data.get("url") or "").strip()
        if not re.match(r"^https?://", url, re.I):
            raise ValueError("Only http:// and https:// links are supported")

        kind = data.get("kind") or "auto"
        if kind == "auto":
            kind = "media" if yt_helper.is_media_url(url) else "file"

        headers = dict(data.get("headers") or {})
        cookie = data.get("cookie") or data.get("cookies")
        if cookie and "Cookie" not in headers:
            headers["Cookie"] = cookie
        if data.get("referrer") and "Referer" not in headers:
            headers["Referer"] = data["referrer"]
        if data.get("userAgent"):
            headers.setdefault("User-Agent", data["userAgent"])

        filename = data.get("filename") or data.get("name") or ""
        quality = data.get("quality") or "best"
        page = (data.get("referrer") or "").strip()
        if (kind == "media" and yt_helper.is_stream_chunk_url(url)
                and re.match(r"^https?://", page, re.I)
                and not yt_helper.is_stream_chunk_url(page)):
            # e.g. a YouTube "videoplayback" piece: it has no title and every one
            # gets the same name, so the next video "finished" as the old file
            url = page

        if data.get("verify") and kind == "file":
            # The browser hands over a download it already started. Only accept it
            # when we can fetch it too; otherwise the extension lets the browser
            # finish it (expired tokens, logins, form POSTs...).
            self._verify_link(url, headers, filename)

        task = self._build_task(url, filename, kind, quality, headers)
        task.given_name = filename
        if kind == "media":
            task.streams = self._clean_streams(data.get("streams"))
        if self.settings.get("ask_save_path", True):
            # the small dialog opens at once; the real title / format is filled in
            # from a background thread (see _open_download_dialog)
            self.post(lambda: self._enqueue_download_dialog(task))
        else:
            def work():
                try:
                    res = self._resolve_task_name(task, filename)
                except Exception:                # noqa: BLE001
                    res = {}
                self.post(lambda: self._apply_resolved(task, res))
            threading.Thread(target=work, daemon=True).start()
        return task.id

    @staticmethod
    def _clean_streams(raw):
        """Keep only well-formed http(s) stream entries sent by the extension."""
        out = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            kind = str(item.get("kind") or "")
            if not re.match(r"^https?://", url, re.I) or kind not in ("hls", "dash", "video", "audio"):
                continue
            out.append({"url": url, "kind": kind,
                        "size": int(item.get("size") or 0),
                        "cookie": str(item.get("cookie") or "")})
            if len(out) >= 8:
                break
        return out

    @staticmethod
    def _verify_link(url, headers, filename=""):
        """Raise ValueError when the app can't download this link itself."""
        probe = dict(headers)
        probe.setdefault("User-Agent", engine.USER_AGENT)
        probe["Range"] = "bytes=0-0"
        probe["Accept-Encoding"] = "identity"
        try:
            with requests.get(url, headers=probe, stream=True, timeout=(6, 8),
                              allow_redirects=True) as resp:
                status = resp.status_code
                ctype = (resp.headers.get("Content-Type") or "").lower()
                disposition = resp.headers.get("Content-Disposition") or ""
        except requests.RequestException as exc:
            raise ValueError(engine.friendly_error(exc)) from exc
        if status >= 400:
            raise ValueError(f"Server returned HTTP {status} to the app")
        wants_page = os.path.splitext(filename or "")[1].lower() in (".htm", ".html")
        if "text/html" in ctype and not wants_page and "attachment" not in disposition.lower():
            raise ValueError("The link returned a web page (login or expired link)")

    def api_grab(self, data):
        referrer = data.get("referrer") or ""
        base = {}
        if referrer:
            base["Referer"] = referrer
        if data.get("userAgent"):
            base["User-Agent"] = data["userAgent"]

        # new extension: one cookie string per link (its own site's cookies)
        pairs = [(str(item.get("url") or "").strip(), item.get("cookie") or "")
                 for item in data.get("items") or [] if isinstance(item, dict)]
        if not pairs:
            # older extension: one page cookie -> only for links on the page's own host
            page_cookie = data.get("cookie") or data.get("cookies") or ""
            page_host = urlparse(referrer).hostname or ""
            for raw in data.get("urls") or []:
                url = str(raw or "").strip()
                same = page_host and urlparse(url).hostname == page_host
                pairs.append((url, page_cookie if same else ""))

        entries = []
        for url, cookie in pairs:
            if not re.match(r"^https?://", url, re.I):
                continue
            headers = dict(base)
            if cookie:
                headers["Cookie"] = cookie
            entries.append((url, headers))
        self.post(lambda: self._confirm_grab(entries, referrer))
        return len(entries)

    def api_info(self, data):
        url = (data.get("url") or "").strip()
        if not re.match(r"^https?://", url, re.I):
            raise ValueError("Invalid URL")
        headers = {}
        if data.get("cookie"):
            headers["Cookie"] = data["cookie"]
        if data.get("userAgent"):
            headers["User-Agent"] = data["userAgent"]
        return yt_helper.media_info(url, headers)

    # --------------------------------------------------------------- task control
    def start_task(self, task):
        if task and task.status in ("paused", "error", "queued"):
            task.error_msg = ""
            task.queue_wait = False
            task.retry_after = 0
            task.status = "queued"
            self.save_history()
            self.render()

    def pause_task(self, task):
        if task and task.status == "downloading" and task.pause_event:
            task.pause_event.set()
            task.status = "pausing"
            self.save_history()
            self.render()

    def remove_task(self, task):
        if not task:
            return
        task.removed = True
        if task.stop_event:
            task.stop_event.set()
        self._close_progress_window(task.id)
        self.tasks.pop(task.id, None)
        row = self.rows.pop(task.id, None)
        if row:
            try:
                row["frame"].destroy()
            except Exception:                    # noqa: BLE001
                pass
        if self.selected_id == task.id:
            self.selected_id = None
        self.save_history()
        self.update_stats()
        self.render()
        self.show_status(f"Removed: {task.name}")

    # selection actions
    def start_selected(self):
        task = self.selected_task()
        if not task:
            self.show_status("Select a download first", "warning")
            return
        if task.status == "completed":
            self.show_status("This download is already complete")
            return
        self.start_task(task)

    def stop_selected(self):
        task = self.selected_task()
        if not task:
            self.show_status("Select a download first", "warning")
            return
        self.pause_task(task)

    def remove_selected(self):
        task = self.selected_task()
        if not task:
            self.show_status("Select a download first", "warning")
            return
        self.remove_task(task)

    def open_selected_file(self):
        task = self.selected_task()
        if task:
            self.open_task_file(task)
        else:
            self.show_status("Select a download first", "warning")

    def open_selected_folder(self):
        task = self.selected_task()
        if task:
            self.open_task_folder(task)
        else:
            self._open_path(self.default_save_dir)

    def copy_selected_url(self):
        task = self.selected_task()
        if not task:
            self.show_status("Select a download first", "warning")
            return
        self._ignore_clip = task.url
        self._last_clip = task.url
        self.clipboard_clear()
        self.clipboard_append(task.url)
        self.show_status("URL copied to clipboard")

    def start_all(self):
        self.queue_running = True
        self.settings["queue_running"] = True
        self._queue_action_fired = False
        for task in list(self.tasks.values()):
            if task.status in ("paused", "error", "queued"):
                task.status = "queued"
                task.queue_wait = False
                task.error_msg = ""
                task.retry_after = 0
        self.save_history()
        self.save_settings()
        self.render()
        self.show_status("Started all waiting downloads", "success")

    def start_queue(self):
        self.queue_running = True
        self.settings["queue_running"] = True
        self._queue_action_fired = False
        self._schedule_holding = False
        self.save_settings()
        waiting = 0
        for task in self.tasks.values():
            if task.status in ("paused", "error"):
                task.status = "queued"
                task.queue_wait = True
                task.error_msg = ""
                waiting += 1
            elif task.status == "queued":
                task.queue_wait = True
                waiting += 1
        self.save_history()
        self.render()
        self.show_status(f"Queue started ({waiting} waiting)", "success")

    def stop_queue(self):
        self.queue_running = False
        self.settings["queue_running"] = False
        self.save_settings()
        for task in list(self.tasks.values()):
            if task.status == "downloading":
                self.pause_task(task)
            elif task.status == "queued":
                task.queue_wait = True
        self.save_history()
        self.render()
        self.show_status("Queue stopped")

    def pause_all(self):
        for task in list(self.tasks.values()):
            self.pause_task(task)

    def clear_completed(self):
        for task in list(self.tasks.values()):
            if task.status == "completed":
                self.tasks.pop(task.id, None)
                row = self.rows.pop(task.id, None)
                if row:
                    try:
                        row["frame"].destroy()
                    except Exception:            # noqa: BLE001
                        pass
        self.save_history()
        self.update_stats()
        self.render()

    def open_task_file(self, task):
        path = task.save_path
        if path and os.path.isfile(path):
            self._open_path(path)
            return
        self.open_task_folder(task)

    def open_task_folder(self, task):
        folder = os.path.dirname(task.save_path) if task.save_path else task.save_dir
        if folder and os.path.isdir(folder):
            self._open_path(folder)
        else:
            self._open_path(self.default_save_dir)

    @staticmethod
    def _open_path(path):
        try:
            if os.name == "nt":
                os.startfile(path)           # noqa: S606
            else:
                webbrowser.open(path)
        except Exception:                        # noqa: BLE001
            pass

    # ------------------------------------------------------------- scheduler
    def _schedule_window_open(self):
        if not self.settings.get("schedule_enabled"):
            return None
        def minutes(text):
            # "9:00", "09:00", "21:5" -> minutes since midnight; None when empty/invalid
            match = re.match(r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*$", text or "")
            if not match:
                return None
            hour, minute = int(match.group(1)), int(match.group(2))
            if hour > 23 or minute > 59:
                return None
            return hour * 60 + minute

        local = time.localtime()
        now = local.tm_hour * 60 + local.tm_min
        start = minutes(self.settings.get("schedule_start"))
        stop = minutes(self.settings.get("schedule_stop"))
        if start is None and stop is None:
            return True
        if start is None:
            return now < stop
        if stop is None:
            return now >= start
        if start <= stop:
            return start <= now < stop
        return now >= start or now < stop       # overnight, e.g. 23:00 -> 06:00

    def _queue_gate_open(self):
        scheduled = self._schedule_window_open()
        if scheduled is None:
            return self.queue_running
        return scheduled

    def _ordered_tasks(self):
        return sorted(self.tasks.values(),
                      key=lambda task: (task.queue_order or task.created_at, task.created_at))

    def _scheduler_loop(self):
        last_autosave = 0.0
        while self.running:
            if self._update_shutdown:
                time.sleep(0.1)
                continue
            try:
                scheduled = self._schedule_window_open()
                if scheduled is False and not self._schedule_holding:
                    self._schedule_holding = True
                    for task in list(self.tasks.values()):
                        if task.status == "downloading" and task.pause_event:
                            task.pause_event.set()
                            task.status = "pausing"
                            task.queue_wait = True
                    self.post(lambda: self.show_status("Scheduler stopped the queue"))
                elif scheduled is True and self._schedule_holding:
                    self._schedule_holding = False
                    for task in self.tasks.values():
                        if task.status == "paused" and task.queue_wait:
                            task.status = "queued"
                            task.retry_after = 0

                gate = self._queue_gate_open()
                with self.lock:
                    if self._update_shutdown:
                        continue
                    active = sum(1 for task in self.tasks.values()
                                 if task.status in ("downloading", "pausing"))
                    free = max(1, self.max_concurrent) - active
                    now = time.time()
                    if free > 0:
                        for task in self._ordered_tasks():
                            if free <= 0:
                                break
                            if task.status != "queued":
                                continue
                            if task.retry_after and now < task.retry_after:
                                continue
                            if task.queue_wait and not gate:
                                continue
                            task.status = "downloading"
                            task.error_msg = ""
                            task.speed = 0
                            task.note = ""
                            free -= 1
                            self._queue_had_work = True
                            self._queue_action_fired = False
                            if self.settings.get("show_progress_window", True):
                                self.post(lambda t=task: self._open_progress_window(t))
                            threading.Thread(target=self._run_task, args=(task,),
                                             daemon=True).start()

                self._maybe_finish_queue()
                now = time.time()
                if now - last_autosave >= 5:
                    last_autosave = now
                    self.save_history()
            except Exception:                    # noqa: BLE001
                pass
            time.sleep(0.25)

    def _maybe_finish_queue(self):
        if not self._queue_had_work or self._queue_action_fired:
            return
        pending = any(
            task.status in ("queued", "downloading", "pausing")
            or (task.status == "paused" and task.queue_wait)
            for task in self.tasks.values())
        if pending:
            return
        self._queue_action_fired = True
        self._queue_had_work = False
        action = self.settings.get("queue_complete_action") or "none"
        self.post(lambda a=action: self._queue_finished(a))

    def _run_task(self, task):
        stop_event = threading.Event()
        pause_event = threading.Event()
        task.stop_event = stop_event
        task.pause_event = pause_event
        if self._update_shutdown:
            pause_event.set()
        task.note = ""
        self.save_history()

        highest = [0.0]

        def on_progress(downloaded, total, speed):
            if downloaded:
                task.downloaded = downloaded
            if total:
                task.size = total
                progress = min(99.9, downloaded * 100.0 / total)
                if task.kind == "media":
                    # video + audio streams: the total grows when the audio starts;
                    # never let the bar jump backwards within one run
                    progress = max(progress, highest[0])
                    highest[0] = progress
                task.progress = progress
            task.speed = speed

        def on_segments(snapshot):
            task.segments = snapshot or []

        def on_file(path):
            task.save_path = path
            task.name = os.path.basename(path)
            try:
                task.size = os.path.getsize(path)
            except OSError:
                pass

        try:
            if task.kind == "media":
                if (not yt_helper.find_ffmpeg()
                        and self.settings.get("auto_install_ffmpeg", True)):
                    task.note = "Installing FFmpeg (one time)..."
                    self.post(lambda: self.show_status(
                        "First video download: installing FFmpeg (one time, ~80 MB)..."))
                    ok, detail = yt_helper.install_ffmpeg(
                        progress_cb=lambda text: self.post(
                            lambda t=text: self.show_status(t)))
                    task.note = ""
                    if not ok:
                        # without FFmpeg yt-dlp can only fetch low "single file" formats
                        self.post(lambda d=detail: self.show_status(
                            f"FFmpeg install failed ({d}). This video may download "
                            "in lower quality. Settings > Install FFmpeg to retry.",
                            "warning"))
                runner = yt_helper.YtDlpRunner(
                    task.url, task.save_dir or self.default_save_dir,
                    quality=task.quality, headers=task.headers,
                    on_progress=on_progress, on_file=on_file,
                    speed_limit=task.speed_limit,
                    output_name=self._media_stem(task))
            else:
                if not task.save_path or task.save_path in self._task_paths(task):
                    # two tasks must never write one file (same name added twice)
                    task.save_path = unique_path(os.path.join(
                        task.save_dir, os.path.basename(task.save_path) or task.name),
                        self._task_paths(task))
                    task.name = os.path.basename(task.save_path)
                task.limiter = engine.RateLimiter(task.speed_limit)
                runner = engine.MultiConnectionDownloader(
                    task.url, task.save_path, connections=self.connections,
                    headers=task.headers, on_progress=on_progress,
                    on_segments=on_segments, rate_limiter=task.limiter,
                    dynamic=True)
            task.runner = runner
            status, error = runner.run(stop_event, pause_event)
            if (task.kind == "media" and status == engine.ERROR and task.streams
                    and not stop_event.is_set() and not pause_event.is_set()):
                status, error = self._run_sniffed_streams(
                    task, error, stop_event, pause_event, on_progress, on_file, on_segments)
        except Exception as exc:                 # noqa: BLE001
            status, error = engine.ERROR, str(exc)

        with self.lock:
            if task.removed or task.id not in self.tasks:
                return

        task.speed = 0
        if status == engine.COMPLETED:
            task.status = "completed"
            task.progress = 100.0
            if task.save_path and os.path.isfile(task.save_path):
                try:
                    task.size = os.path.getsize(task.save_path)
                except OSError:
                    pass
                task.downloaded = task.size
            self.post(lambda: self.show_status(f"✓ Completed: {task.name}", "success"))
            self.post(lambda: self._notify_complete(task))
            self.post(lambda: self._close_progress_window(task.id))
            action = task.completion_action
            if (action not in ("open", "folder")
                    and self.settings.get("show_complete_dialog", True)):
                self.post(lambda: self._show_complete_dialog(task))
            if action in ("open", "folder"):
                path = task.save_path if action == "open" else None
                def _open_after():
                    if action == "open" and task.save_path and os.path.isfile(task.save_path):
                        self._open_path(task.save_path)
                    elif action == "folder":
                        folder = (os.path.dirname(task.save_path)
                                  if task.save_path else task.save_dir)
                        if folder and os.path.isdir(folder):
                            self._open_path(folder)
                self.post(_open_after)
        elif status == engine.PAUSED:
            task.status = "paused"
            self.post(lambda: self.show_status(f"Paused: {task.name}"))
        elif status == engine.STOPPED:
            task.status = "paused"
        else:
            limit = max(0, int(self.settings.get("max_retries") or 0))
            if task.retry_count < limit and not task.removed:
                task.retry_count += 1
                task.status = "queued"
                task.queue_wait = False
                task.retry_after = time.time() + min(30, 4 * task.retry_count)
                task.note = f"Retry {task.retry_count}/{limit}"
                task.error_msg = error or "Unknown error"
                self.post(lambda: self.show_status(
                    f"Retry {task.retry_count}/{limit}: {task.name}", "warning"))
            else:
                task.status = "error"
                task.error_msg = error or "Unknown error"
                self.post(lambda: self.show_status(
                    f"✗ {task.name}: {task.error_msg}", "error"))

        self.save_history()
        self.post(self.update_stats)

    def _task_paths(self, exclude=None):
        """Files other unfinished tasks will write (no two tasks share one)."""
        with self.lock:
            return [t.save_path for t in self.tasks.values()
                    if t is not exclude and not t.removed and t.save_path
                    and t.status != "completed"]

    def _media_stem(self, task, force=False):
        """File name (no extension) for a media task, chosen once and kept so a
        paused task resumes into the same file.

        Pages yt-dlp understands (YouTube, Facebook...) return "": yt-dlp then
        names the file "<real title> [<video id>]", always the right title and
        unique per video. Raw stream links (m3u8, direct files) have no title,
        so they get the page title, made unique in the folder. force=True is
        for the player's own stream links when yt-dlp could not read the page."""
        if task.output_stem:
            return task.output_stem
        if task.legacy_naming:
            return ""
        if not force and not yt_helper.is_raw_media_link(task.url):
            return ""
        name = task.name or ""
        stem, ext = os.path.splitext(name)
        if ext.lower().lstrip(".") in MEDIA_EXTS:
            name = stem
        name = sanitize_filename(name)
        if not name or yt_helper.is_generic_title(name, task.url) or name.lower() == "media":
            if not force:
                return ""
            name = "video"
        folder = task.save_dir or self.default_save_dir
        with self.lock:
            others = [t.output_stem for t in self.tasks.values()
                      if t is not task and not t.removed and t.output_stem
                      and t.status != "completed"
                      and os.path.normcase(t.save_dir or self.default_save_dir)
                      == os.path.normcase(folder)]
            # short enough that " (2)" is never cut off again
            task.output_stem = yt_helper.unique_media_stem(folder, name[:140].rstrip(" ."), others)
        return task.output_stem

    def _run_sniffed_streams(self, task, first_error, stop_event, pause_event,
                             on_progress, on_file, on_segments):
        """yt-dlp could not handle the page: try the media links the player loaded.

        HLS/DASH go through yt-dlp as plain stream URLs (works on any site);
        direct video/audio files use the multi-connection engine.
        """
        status, error = engine.ERROR, first_error
        folder = task.save_dir or self.default_save_dir
        stem = self._media_stem(task, force=True) or "video"
        for stream in task.streams:
            if stop_event.is_set() or pause_event.is_set():
                break
            headers = {k: v for k, v in task.headers.items() if k.lower() != "cookie"}
            if stream.get("cookie"):
                headers["Cookie"] = stream["cookie"]
            task.note = "Downloading the stream the page's player uses..."
            task.progress = 0.0
            task.downloaded = 0
            if stream["kind"] in ("hls", "dash"):
                runner = yt_helper.YtDlpRunner(
                    stream["url"], folder, quality=task.quality, headers=headers,
                    on_progress=on_progress, on_file=on_file,
                    speed_limit=task.speed_limit, output_name=stem)
            else:
                ext = os.path.splitext(urlparse(stream["url"]).path)[1].lower()
                if ext.lstrip(".") not in MEDIA_EXTS:
                    ext = ".mp3" if stream["kind"] == "audio" else ".mp4"
                path = os.path.join(folder, stem + ext)
                if os.path.isfile(path):
                    path = unique_path(path, self._task_paths(task))  # never overwrite
                task.save_path = path
                task.limiter = engine.RateLimiter(task.speed_limit)
                runner = engine.MultiConnectionDownloader(
                    stream["url"], path, connections=self.connections,
                    headers=headers, on_progress=on_progress,
                    on_segments=on_segments, rate_limiter=task.limiter, dynamic=True)
            task.runner = runner
            status, error = runner.run(stop_event, pause_event)
            if status == engine.COMPLETED:
                if stream["kind"] not in ("hls", "dash"):
                    on_file(task.save_path)
                break
        task.note = ""
        if status == engine.ERROR:
            error = f"{first_error} (the page's own video links failed too: {error})"
        return status, error

    # -------------------------------------------------------------- rendering
    def _tick(self):
        for _ in range(300):
            try:
                callback = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:                    # noqa: BLE001
                pass

        if not self.running:
            return
        try:
            self.render()
        except Exception:                        # noqa: BLE001
            pass
        self.after(350, self._tick)

    def _task_matches_view(self, task):
        key = self.current_category
        if key == "unfinished":
            ok = task.status != "completed"
        elif key == "finished":
            ok = task.status == "completed"
        elif key == "queues":
            ok = bool(task.queue_id) and task.status != "completed"
        elif key == "grabber":
            ok = task.kind == "grabber"
        elif key != "all":
            ok = category_of(task) == key
        else:
            ok = True
        if not ok:
            return False
        query = (self.search_text or "").strip().lower()
        if not query:
            return True
        blob = " ".join([
            task.name or "", task.url or "", task.description or "",
            task.save_dir or "", task.status or "",
        ]).lower()
        return query in blob

    def _sort_key(self, task):
        col = self._sort_column
        if col == "name":
            return (task.name or "").lower()
        if col == "size":
            return task.size or 0
        if col == "status":
            return task.status or ""
        if col == "speed":
            return task.speed or 0
        if col == "eta":
            remaining = max(0, (task.size or 0) - (task.downloaded or 0))
            return remaining / task.speed if task.speed else 10 ** 12
        if col == "save_to":
            return (task.save_dir or "").lower()
        if col == "queue":
            return task.queue_order or task.created_at
        if col == "description":
            return (task.description or "").lower()
        return task.created_at or 0

    def _visible_tasks(self):
        visible = [task for task in self.tasks.values() if self._task_matches_view(task)]
        visible.sort(key=self._sort_key, reverse=self._sort_reverse)
        return visible

    def render(self):
        visible = self._visible_tasks()
        visible_ids = {task.id for task in visible}

        for task_id in list(self.rows.keys()):
            if task_id not in visible_ids:
                try:
                    self.rows[task_id]["frame"].destroy()
                except Exception:                # noqa: BLE001
                    pass
                del self.rows[task_id]

        if visible:
            self.empty_label.pack_forget()
        elif not self.empty_label.winfo_ismapped():
            self.empty_label.pack(pady=70)

        for task in visible:
            row = self.rows.get(task.id)
            if row is None:
                row = self._create_row(task)
                self.rows[task.id] = row
            self._update_row(row, task)

        order = [task.id for task in visible]
        if order != self._last_order:
            self._last_order = order
            for task_id in order:
                row = self.rows.get(task_id)
                if row:
                    try:
                        row["frame"].pack_forget()
                        row["frame"].pack(fill="x")
                    except Exception:                # noqa: BLE001
                        pass

        self._update_category_counts()
        self._update_selection_states()

    def _create_row(self, task):
        base_color = C_PANEL if len(self.rows) % 2 == 0 else C_ROW_ALT
        # Plain Tk widgets: a row is redrawn several times a second while
        # downloading, and CustomTkinter widgets (each one a canvas) made long
        # lists slow. Same look, a fraction of the cost.
        selected = task.id == self.selected_id
        frame = _RowFrame(self.list_container,
                          bg=C_SELECT if selected else base_color, height=30)
        frame.pack(fill="x")
        frame.pack_propagate(False)
        frame.grid_propagate(False)
        self._configure_columns(frame)
        frame.grid_rowconfigure(0, weight=1)

        def cell(column, anchor, color=C_MUTED, pad=(4, 4)):
            label = _Cell(frame, anchor=anchor, fg=color)
            label.grid(row=0, column=column, sticky="ew", padx=pad)
            return label

        name = cell(0, "w", C_TEXT, (10, 4))
        queue = cell(1, "center")
        size = cell(2, "e")
        status = cell(3, "w")
        desc = cell(4, "w")
        speed = cell(5, "e")
        date = cell(6, "w")
        eta = cell(7, "e")
        # thin progress line along the bottom edge of the row
        progress = _RowProgress(frame, color=C_BLUE)
        progress.place(relx=0, rely=1.0, relwidth=1.0, height=2, anchor="sw")

        row = {
            "frame": frame,
            "name": name, "queue": queue, "size": size, "status": status,
            "description": desc, "speed": speed, "date": date,
            "eta": eta, "progress": progress,
            "base_color": base_color, "state": None,
        }

        for widget in (frame, name, queue, size, status, desc, speed, date, eta, progress):
            widget.bind("<Button-1>", lambda _e, tid=task.id: self.select_task(tid))
            widget.bind("<Double-Button-1>",
                        lambda _e, t=task: self._open_or_progress(t))
            widget.bind("<Button-3>",
                        lambda e, t=task: self._row_menu(e, t))

        self._rebuild_row_state(row, task)
        return row

    def _row_menu(self, event, task):
        self.select_task(task.id)
        items = []
        if task.status == "completed":
            items.append(("Open file", lambda: self.open_task_file(task)))
        if task.status in ("paused", "error", "queued"):
            items.append(("Start / Resume", lambda: self.start_task(task)))
        if task.status in ("downloading", "pausing"):
            items.append(("Stop", lambda: self.pause_task(task)))
        items.append(("Download properties", lambda: self._open_progress_window(task)))
        items.append(("Move up in queue", lambda: self._move_in_queue(task, -1)))
        items.append(("Move down in queue", lambda: self._move_in_queue(task, 1)))
        items.append(("Open folder", lambda: self.open_task_folder(task)))
        items.append(("Copy URL", lambda: self._copy_url(task.url)))
        items.append(None)
        items.append(("Remove from list", lambda: self.remove_task(task)))
        self._show_popup(event.x_root, event.y_root, items)

    def _copy_url(self, url):
        self.clipboard_clear()
        self.clipboard_append(url)
        self.show_status("URL copied to clipboard")

    def _rebuild_row_state(self, row, task):
        row["state"] = task.status
        row["frame"].configure(fg_color=C_SELECT if task.id == self.selected_id
                               else row["base_color"])

    def _update_row(self, row, task):
        name = task.name
        if len(name) > 36:
            name = name[:33] + "..."
        if task.status == "error":
            name += "  ⓘ"
        row["name"].configure(text=name,
                              text_color=C_RED if task.status == "error" else C_TEXT,
                              font=ROW_FONT_BOLD if task.id == self.selected_id else ROW_FONT)

        labels = {
            "queued": ("Queued", C_MUTED),
            "downloading": ("Downloading", C_BLUE),
            "pausing": ("Stopping...", C_ORANGE),
            "paused": ("Paused", C_ORANGE),
            "completed": ("Complete", C_GREEN),
            "error": ("Error", C_RED),
        }
        text, color = labels.get(task.status, (task.status, C_MUTED))
        progress_pct = float(task.progress or 0)
        if task.status == "queued" and task.queue_wait:
            text = "Waiting"
        if task.status in ("downloading", "paused") and 0 < progress_pct < 100:
            # unfinished files show how far they got, like classic download managers
            text = f"{progress_pct:.2f}%"
        if getattr(task, "note", "") and task.status in ("downloading", "queued"):
            text = task.note
            color = C_BLUE
        row["status"].configure(text=text, text_color=color)
        row["queue"].configure(text="" if task.status == "completed" or not task.queue_id else "1")

        # Size = the file's total size (progress is in the Status column)
        row["size"].configure(text=format_size(task.size) if task.size else "")

        if task.status == "downloading" and task.speed:
            row["speed"].configure(text=f"{format_size(task.speed)}/s",
                                   text_color=C_BLUE)
            remaining = max(0, (task.size or 0) - (task.downloaded or 0))
            row["eta"].configure(text=format_eta(remaining / task.speed
                                                 if task.speed else 0))
        else:
            row["speed"].configure(text="-", text_color=C_MUTED)
            row["eta"].configure(text="-")

        row["description"].configure(text=(task.description or ""))
        row["date"].configure(text=format_date(task.created_at))

        progress = max(0.0, min(1.0, (task.progress or 0) / 100.0))
        if task.status == "completed":
            progress = 0.0          # finished rows stay clean; the line is for unfinished ones
        row["progress"].set(progress)
        colors = {"downloading": C_BLUE, "paused": C_ORANGE,
                  "pausing": C_ORANGE, "completed": C_GREEN,
                  "error": C_RED, "queued": "#A0A0A0"}
        row["progress"].configure(progress_color=colors.get(task.status, C_BLUE))

        selected = task.id == self.selected_id
        row["frame"].configure(fg_color=C_SELECT if selected else row["base_color"])

    def _update_category_counts(self):
        counts = {key: 0 for key, _label in CATEGORIES}
        counts["all"] = len(self.tasks)
        counts["unfinished"] = sum(1 for t in self.tasks.values()
                                   if t.status != "completed")
        counts["finished"] = sum(1 for t in self.tasks.values()
                                 if t.status == "completed")
        counts["queues"] = sum(1 for t in self.tasks.values()
                               if t.queue_id and t.status != "completed")
        counts["grabber"] = sum(1 for t in self.tasks.values()
                                if t.kind == "grabber")
        for task in self.tasks.values():
            counts[category_of(task)] = counts.get(category_of(task), 0) + 1
        labels = dict(CATEGORIES)
        labels.update({
            "unfinished": "Unfinished",
            "finished": "Finished",
            "grabber": "Grabber projects",
            "queues": "Queues",
        })
        shown = self.__dict__.setdefault("_cat_shown", {})
        for key, btn in self.category_buttons.items():
            label = labels.get(key, key)
            count = counts.get(key, 0)
            selected = key == self.current_category
            if shown.get(key) == (count, selected, label):
                continue                         # unchanged: don't redraw the button
            shown[key] = (count, selected, label)
            try:
                btn.configure(
                    text=f"{label}  ({count})",
                    fg_color=C_SELECT if selected else "transparent",
                    text_color=C_BLUE if selected else C_TEXT,
                    font=self._cat_fonts[selected])
            except Exception:                    # noqa: BLE001
                pass

    def update_stats(self):
        total = len(self.tasks)
        active = sum(1 for task in self.tasks.values()
                     if task.status in ("downloading", "queued", "pausing"))
        speed = sum(task.speed or 0 for task in self.tasks.values()
                    if task.status == "downloading")
        self.stats_label.configure(
            text=f"{total} downloads   •   {active} active   •   "
                 f"{format_size(speed)}/s   •   port {self.server_port}")
        connected = self.httpd is not None
        self.connection_label.configure(
            text=f"● Browser link {'ready' if connected else 'off'}",
            text_color=C_GREEN if connected else C_RED)

    def show_status(self, message, kind="info"):
        colors = {"info": C_MUTED, "success": C_GREEN,
                  "error": C_RED, "warning": C_ORANGE}
        try:
            self.status_bar.configure(text=message, text_color=colors.get(kind, C_MUTED))
        except Exception:                        # noqa: BLE001
            pass

    def post(self, callback):
        try:
            self.ui_queue.put_nowait(callback)
        except queue.Full:
            pass

    # ---------------------------------------------------- download info dialog
    # Show "Download File Info" before saving whenever a
    # download arrives from the browser extension.
    def _enqueue_download_dialog(self, task):
        self._download_dialog_queue.put(task)
        self._show_next_download_dialog()

    def _show_next_download_dialog(self):
        if self._download_dialog_open:
            return
        try:
            task = self._download_dialog_queue.get_nowait()
        except queue.Empty:
            return
        self._download_dialog_open = True
        try:
            self._open_download_dialog(task)
        except Exception:                        # noqa: BLE001
            self._download_dialog_open = False

    def _download_dialog_done(self):
        self._download_dialog_open = False
        self.after(120, self._show_next_download_dialog)

    # ------------------------------------------------------------------ helpers
    def _category_choices(self):
        """Display names: Video, Music, Documents, Compressed, Programs, Other + custom."""
        base = ["Video", "Music", "Documents", "Compressed", "Programs", "Other"]
        base += [name for name in self.settings.get("custom_categories") or []
                 if name and name not in base]
        return base

    def _category_key_from_label(self, label):
        for key, text in CATEGORY_LABELS.items():
            if text.lower() == (label or "").lower():
                return key
        return (label or "other").strip().lower() or "other"

    def _category_folder(self, cat_key):
        """Folder for a category; stored per-category path or a default sub-folder."""
        stored = (self.settings.get("category_paths") or {}).get(cat_key)
        if stored and os.path.isdir(stored):
            return stored
        label = CATEGORY_LABELS.get(cat_key)
        if not label:
            # custom category: keep the name exactly as the user typed it
            customs = self.settings.get("custom_categories") or []
            label = next((name for name in customs if name.lower() == cat_key), cat_key)
        return os.path.join(self.default_save_dir, label)

    def _open_download_dialog(self, task):
        # Only this small dialog pops up - the main window is
        # never forced open (it can stay hidden in the tray).
        self._close_menu()
        main_visible = self.state() == "normal"

        dialog = ctk.CTkToplevel(self)
        dialog.title("Download File Info")
        dialog.geometry("760x470")
        dialog.resizable(False, False)
        dialog.configure(fg_color=C_BG)
        if main_visible:                         # a transient of a hidden window is hidden too
            dialog.transient(self)
        dialog.attributes("-topmost", True)
        window_frame.apply(dialog)

        def _grab():
            try:
                dialog.grab_set()
            except Exception:                    # noqa: BLE001
                pass
        dialog.after(150, _grab)

        is_media = task.kind == "media"
        cat_key = category_of(task)              # video/music/documents/.../other
        cat_name = CATEGORY_LABELS.get(cat_key, "Other")

        # ------------------------------------------------------------- header
        header = ctk.CTkFrame(dialog, fg_color=C_PANEL, corner_radius=0, height=78)
        header.pack(fill="x")
        header.pack_propagate(False)

        badge = ctk.CTkFrame(header, width=46, height=46, corner_radius=23,
                             fg_color=C_BADGE)
        badge.pack(side="left", padx=(16, 12), pady=16)
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text=category_icon(task), font=ctk.CTkFont(size=24)
                     ).place(relx=0.5, rely=0.5, anchor="center")

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", pady=14)
        ctk.CTkLabel(titles, text="Download File Info", anchor="w",
                     font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
                     text_color=C_TEXT).pack(anchor="w")
        cat_header = ctk.CTkLabel(titles, text=f"Category: {cat_name}", anchor="w",
                     text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11))
        cat_header.pack(anchor="w")

        self._info_size_label = ctk.CTkLabel(header, text="", anchor="e",
                                             text_color=C_MUTED,
                                             font=ctk.CTkFont(family="Segoe UI", size=12))
        self._info_size_label.pack(side="right", padx=18)

        # -------------------------------------------------------------- form
        form = ctk.CTkFrame(dialog, fg_color=C_PANEL, corner_radius=4,
                            border_width=1, border_color=C_BORDER)
        form.pack(fill="both", expand=True, padx=16, pady=12)
        form.grid_columnconfigure(1, weight=1)

        url_var = ctk.StringVar(value=task.url)
        save_var = ctk.StringVar(value="")
        desc_var = ctk.StringVar(value=task.description or "")

        default_folder = self._category_folder(cat_key)
        explicit = task.save_dir or ""
        if (explicit and os.path.isdir(explicit)
                and os.path.normcase(os.path.abspath(explicit))
                != os.path.normcase(os.path.abspath(self.default_save_dir))):
            default_folder = explicit
        base_name = sanitize_filename(task.name)
        if is_media:
            if os.path.splitext(base_name)[1].lower().lstrip(".") in MEDIA_EXTS:
                base_name = os.path.splitext(base_name)[0]
            base_name = (base_name or "video") + (".mp3" if task.quality == "audio" else ".mp4")
        else:
            base_name = base_name or "download"
            if "." not in base_name:
                base_name += ".bin"
        save_var.set(os.path.join(default_folder, base_name))

        def label(text, row):
            ctk.CTkLabel(form, text=text, anchor="w",
                         font=ctk.CTkFont(family="Segoe UI", size=11),
                         text_color=C_TEXT
                         ).grid(row=row, column=0, sticky="w",
                                padx=(14, 6), pady=(9, 2))

        entry_style = dict(fg_color=C_INPUT_BG, border_color=C_BORDER,
                           text_color=C_TEXT)

        # URL
        label("URL:", 0)
        url_entry = ctk.CTkEntry(form, textvariable=url_var, height=30,
                                 font=ctk.CTkFont(family="Segoe UI", size=11),
                                 **entry_style)
        url_entry.grid(row=0, column=1, columnspan=4, sticky="ew",
                       padx=(4, 14), pady=(9, 2))
        url_entry.configure(state="readonly")

        # Category
        label("Category:", 1)
        choices = self._category_choices()
        cat_var = ctk.StringVar(value=cat_name if cat_name in choices else "Other")
        # keep the header ("Category: ...") in sync with the category box
        cat_var.trace_add("write", lambda *_: cat_header.configure(
            text=f"Category: {cat_var.get()}"))
        cat_header.configure(text=f"Category: {cat_var.get()}")
        combo = ctk.CTkComboBox(form, variable=cat_var, values=choices,
                                height=30, width=170, corner_radius=4,
                                fg_color=C_INPUT_BG, border_color=C_BORDER,
                                button_color=C_BLUE, button_hover_color=C_BLUE_HOVER,
                                text_color=C_TEXT,
                                dropdown_fg_color=C_PANEL,
                                dropdown_hover_color=C_SELECT,
                                dropdown_text_color=C_TEXT,
                                font=ctk.CTkFont(family="Segoe UI", size=11))
        combo.grid(row=1, column=1, sticky="w", padx=4, pady=(9, 2))
        ctk.CTkButton(form, text="＋", width=30, height=30, corner_radius=4,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER, text_color=C_TEXT,
                      command=lambda: _category_added(
                          self._add_category(dialog, combo, cat_var, save_var))
                      ).grid(row=1, column=2, sticky="w", padx=(6, 0), pady=(9, 2))

        # Save as
        label("Save as:", 2)
        save_entry = ctk.CTkEntry(form, textvariable=save_var, height=30,
                                  font=ctk.CTkFont(family="Segoe UI", size=11),
                                  **entry_style)
        save_entry.grid(row=2, column=1, columnspan=3, sticky="ew",
                        padx=4, pady=(9, 2))
        ctk.CTkButton(form, text="…", width=30, height=30, corner_radius=4,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER, text_color=C_TEXT,
                      command=lambda: self._browse_save_as(save_var, dialog)
                      ).grid(row=2, column=4, sticky="e", padx=(4, 14), pady=(9, 2))

        # Remember this path for category
        remember_var = ctk.BooleanVar(value=True)
        remember_check = ctk.CTkCheckBox(
            form, text=f"Remember this path for '{cat_name}' category",
            variable=remember_var,
            font=ctk.CTkFont(family="Segoe UI", size=11), text_color=C_TEXT)
        remember_check.grid(row=3, column=1, columnspan=4, sticky="w",
                            padx=6, pady=(6, 0))

        cat_folder_var = ctk.StringVar(value=self._category_folder(cat_key))
        cat_path_entry = ctk.CTkEntry(form, textvariable=cat_folder_var, height=26,
                                      font=ctk.CTkFont(family="Segoe UI", size=10),
                                      fg_color=C_INPUT_BG, border_color=C_BORDER,
                                      text_color=C_MUTED)
        cat_path_entry.grid(row=4, column=1, columnspan=4, sticky="ew",
                            padx=(6, 14), pady=(2, 6))

        def _remember_toggle():
            state = "normal" if remember_var.get() else "disabled"
            cat_path_entry.configure(state=state)
        remember_var.trace_add("write", lambda *_: _remember_toggle())
        _remember_toggle()

        def _on_category(choice):
            nonlocal cat_key
            cat_key = self._category_key_from_label(choice)
            folder = self._category_folder(cat_key)
            name = os.path.basename(save_var.get()) or base_name
            save_var.set(os.path.join(folder, name))
            cat_folder_var.set(folder)
            remember_check.configure(text=f"Remember this path for '{choice}' category")
            try:
                state["initial"] = save_var.get()
            except (NameError, UnboundLocalError):
                pass

        combo.configure(command=_on_category)

        def _category_added(name):
            # a new category from "+" must also become the category we remember for
            if name:
                _on_category(name)

        def _category_folder_edited(*_args):
            # typing a folder in the category-path box moves "Save as" there too
            folder = cat_folder_var.get().strip()
            if not folder:
                return
            name = os.path.basename(save_var.get()) or base_name
            if os.path.dirname(save_var.get()) != folder:
                save_var.set(os.path.join(folder, name))
        cat_folder_var.trace_add("write", _category_folder_edited)

        # Description
        label("Description:", 5)
        ctk.CTkEntry(form, textvariable=desc_var, height=30,
                     font=ctk.CTkFont(family="Segoe UI", size=11), **entry_style
                     ).grid(row=5, column=1, columnspan=4, sticky="ew",
                            padx=(4, 14), pady=(9, 2))

        quality_labels = ["Best available", "2160p", "1440p", "1080p",
                          "720p", "480p", "360p", "Audio (MP3)"]
        quality_var = ctk.StringVar(value="Best available")
        if task.quality == "audio":
            quality_var.set("Audio (MP3)")
        elif task.quality in quality_labels:
            quality_var.set(task.quality)
        if is_media:
            label("Quality:", 6)
            ctk.CTkComboBox(form, variable=quality_var, values=quality_labels,
                            height=30, width=180,
                            fg_color=C_INPUT_BG, border_color=C_BORDER,
                            button_color=C_BLUE, button_hover_color=C_BLUE_HOVER,
                            text_color=C_TEXT, dropdown_fg_color=C_PANEL,
                            dropdown_text_color=C_TEXT,
                            font=ctk.CTkFont(family="Segoe UI", size=11)
                            ).grid(row=6, column=1, sticky="w", padx=4, pady=(4, 8))

        # -------------------------------------------------------------- footer
        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(0, 14))

        state = {"done": False, "pending": None, "closed": False,
                 "initial": save_var.get()}

        def _finish(autostart):
            if not state["done"]:
                # name / format is still being read -> start as soon as it is known,
                # but never wait forever on a slow or silent server
                state["pending"] = autostart
                try:
                    self._info_size_label.configure(text="Reading file info...")
                except Exception:                # noqa: BLE001
                    pass

                def give_up_waiting():
                    if state["closed"] or state["done"] or state["pending"] is None:
                        return
                    state["done"] = True
                    pending, state["pending"] = state["pending"], None
                    _finish(pending)
                dialog.after(12000, give_up_waiting)
                return
            raw = save_var.get().strip()
            if not raw:
                messagebox.showwarning("Download File Info", "Please choose a save path.",
                                       parent=dialog)
                return
            folder = os.path.dirname(raw)
            name = os.path.basename(raw)
            if not folder:
                folder = self.default_save_dir
            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                except OSError:
                    messagebox.showerror("Download File Info",
                                         "That folder cannot be created.", parent=dialog)
                    return

            task.save_dir = folder
            task.description = desc_var.get().strip()
            task.autostart = autostart
            if is_media:
                picked = quality_var.get()
                task.quality = "audio" if picked.startswith("Audio") else (
                    "best" if picked == "Best available" else picked)
                task.kind = "media"

            if remember_var.get():
                ch_key = cat_key
                ch_dir = folder
                (self.settings.setdefault("category_paths", {}))[ch_key] = ch_dir
                self.save_settings()

            if is_media:
                task.save_path = ""
                stem, ext = os.path.splitext(name)
                clean = sanitize_filename(stem if ext.lower().lstrip(".") in MEDIA_EXTS else name) or "video"
                task.name = clean
            else:
                if not name or not sanitize_filename(name):
                    messagebox.showwarning("Download File Info",
                                           "Please enter a file name.", parent=dialog)
                    return
                if "." not in name:
                    # keep the name as-is; do not force a .bin extension
                    pass
                task.name = sanitize_filename(name)
                task.save_path = unique_path(os.path.join(folder, task.name),
                                             self._task_paths(task))

            try:
                dialog.destroy()
            except Exception:                    # noqa: BLE001
                pass
            state["closed"] = True
            self._download_dialog_done()
            prefetch = state.get("prefetch")
            if prefetch is None or is_media:
                self._register_task(task)
                return
            # Whatever was already downloaded while the dialog was open moves
            # into the chosen folder and the download continues from there.
            self.show_status(f"Moving downloaded part to: {folder}")
            prefetch.hand_over(task.save_path,
                               lambda outcome: self._after_prefetch(task, outcome),
                               self.post)

        def cancel():
            state["closed"] = True
            prefetch = state.get("prefetch")
            if prefetch is not None:
                prefetch.discard()
            try:
                dialog.destroy()
            except Exception:                    # noqa: BLE001
                pass
            self.show_status(f"Cancelled: {task.name}")
            self._download_dialog_done()

        ctk.CTkButton(footer, text="Start Download", width=150, height=36,
                      corner_radius=4, fg_color=C_BLUE, hover_color=C_BLUE_HOVER,
                      text_color="white", command=lambda: _finish(True)
                      ).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Download Later", width=150, height=36,
                      corner_radius=4, fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT, command=lambda: _finish(False)
                      ).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Cancel", width=110, height=36,
                      corner_radius=4, fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT, command=cancel
                      ).pack(side="right", padx=6)

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Return>", lambda _event: _finish(True))
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.after(60, lambda: (dialog.lift(), dialog.focus_force(), url_entry.focus_set()))
        self._center_window(dialog)

        def apply(res):
            nonlocal cat_key
            if state["closed"]:
                return
            state["done"] = True
            try:
                if res.get("size"):
                    self._info_size_label.configure(text=format_size(res["size"]))
                elif self._info_size_label.cget("text") == "Reading file info...":
                    self._info_size_label.configure(text="")
                # only touch the fields when the user has not edited them
                if res.get("display") and save_var.get() == state["initial"]:
                    task.name = res["name"]
                    folder = os.path.dirname(save_var.get()) or self.default_save_dir
                    save_var.set(os.path.join(folder, sanitize_filename(res["display"])))
                    new_key = category_of(task)
                    if new_key != cat_key:
                        cat_key = new_key
                        label_text = CATEGORY_LABELS.get(new_key, "Other")
                        cat_var.set(label_text)
                        cat_folder_var.set(self._category_folder(new_key))
                        remember_check.configure(
                            text=f"Remember this path for '{label_text}' category")
            except Exception:                    # noqa: BLE001
                pass
            if state["pending"] is not None:
                pending, state["pending"] = state["pending"], None
                _finish(pending)

        def worker():
            try:
                res = self._resolve_task_name(task, getattr(task, "given_name", ""))
            except Exception:                    # noqa: BLE001
                res = {}
            self.post(lambda: apply(res))
        threading.Thread(target=worker, daemon=True).start()

        # Start downloading in the background right away (into a temp folder)
        # while the user is still choosing the folder / name.
        if not is_media and self.settings.get("prefetch_in_dialog", True):
            try:
                state["prefetch"] = _Prefetch(self, task)
            except Exception:                    # noqa: BLE001
                state["prefetch"] = None

            def show_prefetch():
                if state["closed"]:
                    return
                pre = state.get("prefetch")
                try:
                    if pre is not None and pre.total:
                        pct = min(100.0, pre.downloaded * 100.0 / pre.total)
                        self._info_size_label.configure(
                            text=f"{format_size(pre.total)}   ·   {pct:.0f}% downloaded")
                except Exception:                # noqa: BLE001
                    pass
                dialog.after(500, show_prefetch)
            dialog.after(500, show_prefetch)

    def _after_prefetch(self, task, outcome):
        """Runs on the UI thread once the prefetched data sits at task.save_path."""
        self._register_task(task)
        if outcome == "completed":
            task.status = "completed"
            task.queue_wait = False
            task.progress = 100.0
            try:
                task.size = os.path.getsize(task.save_path)
            except OSError:
                pass
            task.downloaded = task.size
            self.save_history()
            self.render()
            self.show_status(f"✓ Completed: {task.name}", "success")
            self._notify_complete(task)
            if self.settings.get("show_complete_dialog", True):
                self._show_complete_dialog(task)

    def _probe_info_size(self, task, dialog):
        size = 0
        try:
            headers = dict(task.headers)
            headers.setdefault("User-Agent", engine.USER_AGENT)
            headers["Range"] = "bytes=0-0"
            with requests.get(task.url, headers=headers, stream=True,
                              timeout=(10, 20), allow_redirects=True) as resp:
                if resp.status_code == 206:
                    match = re.search(r"/\s*(\d+)\s*$",
                                      resp.headers.get("Content-Range", ""))
                    if match:
                        size = int(match.group(1))
                else:
                    size = int(resp.headers.get("Content-Length") or 0)
        except Exception:                        # noqa: BLE001
            return
        if size > 0:
            def update():
                try:
                    self._info_size_label.configure(text=format_size(size))
                except Exception:                # noqa: BLE001
                    pass
            self.post(update)

    def _add_category(self, dialog, combo, cat_var, save_var):
        name = simpledialog.askstring("New category", "Category name:",
                                         parent=dialog)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        customs = list(self.settings.get("custom_categories") or [])
        if name not in customs:
            customs.append(name)
            self.settings["custom_categories"] = customs
            self.save_settings()
        combo.configure(values=self._category_choices())
        cat_var.set(name)
        folder = os.path.join(self.default_save_dir, name)
        current = save_var.get()
        base = os.path.basename(current) if current else ""
        save_var.set(os.path.join(folder, base))
        return name

    def _browse_save_as(self, save_var, dialog=None):
        if dialog is not None:
            try:
                dialog.attributes("-topmost", False)
            except Exception:                    # noqa: BLE001
                pass
        current = save_var.get()
        base = os.path.basename(current) if current else "download.bin"
        ext = os.path.splitext(base)[1]
        # a real "Save As" dialog: pick the folder and the file name together
        chosen = filedialog.asksaveasfilename(
            parent=dialog, title="Save As",
            initialdir=os.path.dirname(current) or self.default_save_dir,
            initialfile=base, defaultextension=ext,
            filetypes=[(f"{ext[1:].upper()} file", f"*{ext}"), ("All files", "*.*")]
            if ext else [("All files", "*.*")])
        if chosen:
            save_var.set(os.path.normpath(chosen))
        if dialog is not None:
            try:
                dialog.attributes("-topmost", True)
                dialog.lift()
                dialog.focus_force()
            except Exception:                    # noqa: BLE001
                pass

    # ----------------------------------------------------- progress window
    def _open_progress_window(self, task):
        existing = self._progress_windows.get(task.id)
        if existing is not None:
            try:
                existing.window.deiconify()
                existing.window.lift()
                return
            except Exception:                    # noqa: BLE001
                pass
        try:
            window = _ProgressWindow(self, task)
            self._progress_windows[task.id] = window
            window.window.attributes("-topmost", True)
            window.window.after(700, lambda: window.window.attributes("-topmost", False))
        except Exception:                        # noqa: BLE001
            pass

    def _close_progress_window(self, task_id):
        window = self._progress_windows.pop(task_id, None)
        if window is not None:
            try:
                window.window.destroy()
            except Exception:                    # noqa: BLE001
                pass

    def _show_complete_dialog(self, task):
        try:
            _CompleteDialog(self, task)
        except Exception:                        # noqa: BLE001
            pass

    def _close_all_progress_windows(self):
        for task_id in list(self._progress_windows.keys()):
            self._close_progress_window(task_id)

    # --------------------------------------------------------------- add dialog
    def open_add_dialog(self, initial_url=""):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add URL")
        dialog.geometry("580x350")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=C_BG)
        window_frame.apply(dialog)

        ctk.CTkLabel(dialog, text="Add a download", anchor="w",
                     font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
                     ).pack(fill="x", padx=18, pady=(16, 2))
        ctk.CTkLabel(dialog, text="Paste a link to a file or a video page.",
                     anchor="w", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11)
                     ).pack(fill="x", padx=18, pady=(0, 10))

        form = ctk.CTkFrame(dialog, fg_color=C_PANEL, corner_radius=3,
                            border_width=1, border_color=C_BORDER)
        form.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        url_var = ctk.StringVar(value=initial_url or self._clipboard_url())
        folder_var = ctk.StringVar(value=self.default_save_dir)
        name_var = ctk.StringVar(value="")

        def field(label, variable, row, browse=False):
            ctk.CTkLabel(form, text=label, anchor="w",
                         font=ctk.CTkFont(family="Segoe UI", size=11),
                         text_color="#C9D1D9").grid(row=row, column=0, sticky="w",
                                                    padx=12, pady=(10, 2))
            entry = ctk.CTkEntry(form, textvariable=variable, height=32,
                                 font=ctk.CTkFont(family="Segoe UI", size=12))
            entry.grid(row=row, column=1, sticky="ew", padx=(6, 12), pady=(10, 2))
            if browse:
                ctk.CTkButton(form, text="Browse", width=74, height=32,
                              fg_color=C_BTN, hover_color=C_BTN_HOVER,
                              text_color="#58A6FF",
                              command=lambda: self._browse_into(folder_var)
                              ).grid(row=row, column=2, padx=(0, 12), pady=(10, 2))
            return entry

        form.grid_columnconfigure(1, weight=1)
        url_entry = field("URL:", url_var, 0)
        field("Save to:", folder_var, 1, browse=True)
        field("File name:", name_var, 2)

        ctk.CTkLabel(form, text="Leave the file name empty to detect it automatically.",
                     anchor="w", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=10)
                     ).grid(row=3, column=1, sticky="w", padx=6, pady=(0, 10))

        start_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(form, text="Start download immediately",
                        variable=start_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11)
                        ).grid(row=4, column=1, sticky="w", padx=6, pady=(0, 12))

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(0, 14))

        def submit():
            url = url_var.get().strip()
            if not url:
                messagebox.showwarning("Add URL", "Please enter a link.", parent=dialog)
                return
            if not re.match(r"^https?://", url, re.I):
                url = "https://" + url
            folder = folder_var.get().strip() or self.default_save_dir
            if not os.path.isdir(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                except OSError:
                    messagebox.showerror("Add URL", "Cannot use that folder.",
                                         parent=dialog)
                    return
            dialog.destroy()
            self.add_url(url, filename=name_var.get().strip() or None,
                         save_dir=folder, autostart=bool(start_var.get()))

        ctk.CTkButton(footer, text="OK", width=100, height=34, fg_color=C_BLUE,
                      hover_color=C_BLUE_HOVER,
                      command=submit).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Cancel", width=100, height=34,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT, command=dialog.destroy).pack(side="right", padx=6)

        url_entry.focus_set()
        dialog.bind("<Return>", lambda _event: submit())
        self.after(80, lambda: self._center_window(dialog))

    @staticmethod
    def _center_window(window):
        try:
            window.update_idletasks()
            width = window.winfo_width()
            height = window.winfo_height()
            x = (window.winfo_screenwidth() // 2) - width // 2
            y = (window.winfo_screenheight() // 2) - height // 2
            window.geometry(f"+{x}+{y}")
        except Exception:                        # noqa: BLE001
            pass

    @staticmethod
    def _browse_into(variable):
        folder = filedialog.askdirectory(initialdir=variable.get() or ".")
        if folder:
            variable.set(folder)

    # --------------------------------------------------------------- settings UI
    def open_scheduler(self):
        window = ctk.CTkToplevel(self)
        window.title("Scheduler")
        window.geometry("640x520")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()
        window.configure(fg_color=C_BG)
        window_frame.apply(window)

        body = ctk.CTkFrame(window, fg_color=C_BG)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(body, text="Main download queue", anchor="w",
                     font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                     text_color=C_TEXT).pack(fill="x")
        ctk.CTkLabel(body,
                     text="Start Queue runs waiting files. Stop Queue pauses them. "
                          "A schedule overrides the queue while it is inside the time window.",
                     anchor="w", justify="left", wraplength=600, text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(fill="x", pady=(2, 8))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkButton(row, text="Start Queue", width=120, height=32, fg_color=C_BLUE,
                      hover_color=C_BLUE_HOVER, command=self.start_queue
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(row, text="Stop Queue", width=120, height=32,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER, text_color=C_TEXT,
                      command=self.stop_queue).pack(side="left")
        state_text = "running" if self.queue_running else "stopped"
        ctk.CTkLabel(row, text=f"Queue is {state_text}", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left", padx=12)

        sched = ctk.BooleanVar(value=bool(self.settings.get("schedule_enabled")))
        ctk.CTkCheckBox(body, text="Start and stop the queue on a schedule",
                        variable=sched, text_color=C_TEXT,
                        font=ctk.CTkFont(family="Segoe UI", size=11)).pack(anchor="w", pady=6)
        times = ctk.CTkFrame(body, fg_color="transparent")
        times.pack(fill="x")
        start_var = ctk.StringVar(value=self.settings.get("schedule_start") or "01:00")
        stop_var = ctk.StringVar(value=self.settings.get("schedule_stop") or "06:00")
        ctk.CTkLabel(times, text="Start", text_color=C_TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left")
        ctk.CTkEntry(times, textvariable=start_var, width=80, height=28).pack(side="left", padx=6)
        ctk.CTkLabel(times, text="Stop", text_color=C_TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(side="left", padx=(12, 0))
        ctk.CTkEntry(times, textvariable=stop_var, width=80, height=28).pack(side="left", padx=6)
        ctk.CTkLabel(times, text="HH:MM", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=10)).pack(side="left")

        ctk.CTkLabel(body, text="When the queue finishes", anchor="w", text_color=C_TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(anchor="w", pady=(10, 2))
        action_labels = {
            "none": "Do nothing",
            "exit": "Exit BD Downloader",
            "sleep": "Put the computer to sleep",
            "shutdown": "Shut down the computer",
        }
        current = self.settings.get("queue_complete_action") or "none"
        action_var = ctk.StringVar(value=action_labels.get(current, "Do nothing"))
        ctk.CTkComboBox(body, variable=action_var, values=list(action_labels.values()),
                        width=280, height=30, fg_color=C_INPUT_BG, border_color=C_BORDER,
                        button_color=C_BLUE, text_color=C_TEXT,
                        dropdown_fg_color=C_PANEL, dropdown_text_color=C_TEXT
                        ).pack(anchor="w")

        waiting = [task for task in self._ordered_tasks()
                   if task.status in ("queued", "paused", "downloading", "error")]
        ctk.CTkLabel(body, text=f"In queue: {len(waiting)}", anchor="w", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(anchor="w", pady=(10, 2))
        listing = ctk.CTkTextbox(body, height=140, fg_color=C_PANEL, text_color=C_TEXT)
        listing.pack(fill="both", expand=True)
        if waiting:
            for task in waiting[:40]:
                mark = "waiting" if task.queue_wait else task.status
                listing.insert("end", f"{task.name}   [{mark}]\n")
        else:
            listing.insert("end", "No waiting downloads.\n")
        listing.configure(state="disabled")

        footer = ctk.CTkFrame(window, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 14))

        def save_schedule():
            start = start_var.get().strip()
            stop = stop_var.get().strip()
            if sched.get() and not re.match(r"^\d{2}:\d{2}$", start):
                messagebox.showwarning("Scheduler", "Start time must be HH:MM.", parent=window)
                return
            if sched.get() and stop and not re.match(r"^\d{2}:\d{2}$", stop):
                messagebox.showwarning("Scheduler", "Stop time must be HH:MM.", parent=window)
                return
            reverse = {label: key for key, label in action_labels.items()}
            self.settings["schedule_enabled"] = bool(sched.get())
            self.settings["schedule_start"] = start
            self.settings["schedule_stop"] = stop
            self.settings["queue_complete_action"] = reverse.get(action_var.get(), "none")
            self.save_settings()
            self.show_status("Scheduler saved", "success")
            window.destroy()

        ctk.CTkButton(footer, text="Save", width=100, height=32, fg_color=C_BLUE,
                      hover_color=C_BLUE_HOVER, command=save_schedule).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Close", width=100, height=32,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER, text_color=C_TEXT,
                      command=window.destroy).pack(side="right")

    def open_settings(self):
        window = ctk.CTkToplevel(self)
        window.title("Options")
        window.geometry("560x700")
        window.resizable(True, True)
        window.minsize(480, 420)
        window.maxsize(900, 900)
        window.configure(fg_color=C_BG)
        window_frame.apply(window, maximize=False)
        try:
            window.grab_set()
        except Exception:                        # noqa: BLE001
            pass
        self._center_window(window)
        window.after(80, lambda: (window.lift(), window.focus_force()))
        window.after(600, lambda: window.attributes("-topmost", False))

        body = ctk.CTkScrollableFrame(window, fg_color=C_BG)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        def section(text):
            ctk.CTkLabel(body, text=text, anchor="w",
                         font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                         text_color=C_BLUE).pack(fill="x", pady=(12, 4))

        section("Default download folder")
        folder_row = ctk.CTkFrame(body, fg_color=C_PANEL, border_width=1,
                                  border_color=C_BORDER, corner_radius=3)
        folder_row.pack(fill="x", pady=2)
        folder_var = ctk.StringVar(value=self.default_save_dir)
        ctk.CTkEntry(folder_row, textvariable=folder_var, height=32
                     ).pack(side="left", fill="x", expand=True, padx=8, pady=8)

        def browse():
            chosen = filedialog.askdirectory(initialdir=folder_var.get() or ".")
            if chosen:
                folder_var.set(chosen)

        ctk.CTkButton(folder_row, text="Browse", width=80, height=32,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color="#58A6FF", command=browse
                      ).pack(side="right", padx=8)

        section("Performance")
        concurrent_label = ctk.CTkLabel(body, text="", anchor="w",
                                        font=ctk.CTkFont(family="Segoe UI", size=11))
        concurrent_label.pack(fill="x")
        concurrent_slider = ctk.CTkSlider(
            body, from_=1, to=10, number_of_steps=9,
            command=lambda v: concurrent_label.configure(
                text=f"Simultaneous downloads: {int(v)}"))
        concurrent_slider.set(self.max_concurrent)
        concurrent_slider.pack(fill="x", pady=(0, 8))
        concurrent_label.configure(text=f"Simultaneous downloads: {self.max_concurrent}")

        connections_label = ctk.CTkLabel(body, text="", anchor="w",
                                         font=ctk.CTkFont(family="Segoe UI", size=11))
        connections_label.pack(fill="x")
        connections_slider = ctk.CTkSlider(
            body, from_=1, to=16, number_of_steps=15,
            command=lambda v: connections_label.configure(
                text=f"Connections per file: {int(v)}"))
        connections_slider.set(self.connections)
        connections_slider.pack(fill="x", pady=(0, 8))
        connections_label.configure(
            text=f"Connections per file: {self.connections}")

        auto_var = ctk.BooleanVar(value=bool(self.settings.get("auto_start", True)))
        ctk.CTkCheckBox(body, text="Start new downloads automatically",
                        variable=auto_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=6)

        startup_var = ctk.BooleanVar(value=bool(self.settings.get("start_with_windows", True)))
        ctk.CTkCheckBox(body, text="Start with Windows (tray background mode)",
                        variable=startup_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        minimize_var = ctk.BooleanVar(value=bool(self.settings.get("start_minimized", True)))
        ctk.CTkCheckBox(body, text="Hide window at startup (minimize to tray)",
                        variable=minimize_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        close_var = ctk.BooleanVar(value=bool(self.settings.get("close_to_tray", True)))
        ctk.CTkCheckBox(body, text="Close to tray instead of exiting",
                        variable=close_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        ask_var = ctk.BooleanVar(value=bool(self.settings.get("ask_save_path", True)))
        ctk.CTkCheckBox(body, text="Show Download File Info before saving",
                        variable=ask_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=6)

        clip_var = ctk.BooleanVar(value=bool(self.settings.get("clipboard_monitor", False)))
        ctk.CTkCheckBox(body, text="Monitor clipboard for new URLs",
                        variable=clip_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        sound_var = ctk.BooleanVar(value=bool(self.settings.get("sound_on_complete", True)))
        ctk.CTkCheckBox(body, text="Play a sound when a download finishes",
                        variable=sound_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        updates_var = ctk.BooleanVar(value=bool(self.settings.get("check_updates", True)))
        ctk.CTkCheckBox(body, text="Check for app updates automatically (every 12 hours)",
                        variable=updates_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=4)

        retry_label = ctk.CTkLabel(body, text="", anchor="w",
                                   font=ctk.CTkFont(family="Segoe UI", size=11))
        retry_label.pack(fill="x", pady=(6, 0))
        retry_slider = ctk.CTkSlider(
            body, from_=0, to=10, number_of_steps=10,
            command=lambda v: retry_label.configure(
                text=f"Retry failed downloads: {int(v)} times"))
        retry_slider.set(int(self.settings.get("max_retries") or 0))
        retry_slider.pack(fill="x", pady=(0, 6))
        retry_label.configure(
            text=f"Retry failed downloads: {int(self.settings.get('max_retries') or 0)} times")

        # Theme selector
        section("Theme")
        theme_var = ctk.StringVar(value=self.settings.get("theme", "dark"))
        theme_row = ctk.CTkFrame(body, fg_color="transparent")
        theme_row.pack(fill="x", pady=4)
        ctk.CTkRadioButton(theme_row, text="Dark", value="dark", variable=theme_var,
                           text_color=C_TEXT,
                           font=ctk.CTkFont(family="Segoe UI", size=11)
                           ).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(theme_row, text="Light", value="light", variable=theme_var,
                           text_color=C_TEXT,
                           font=ctk.CTkFont(family="Segoe UI", size=11)
                           ).pack(side="left")
        ctk.CTkLabel(body, text="Restart the app after changing theme.",
                     text_color=C_MUTED, font=ctk.CTkFont(family="Segoe UI", size=10)
                     ).pack(anchor="w", pady=(0, 6))

        pw_var = ctk.BooleanVar(value=bool(self.settings.get("show_progress_window", True)))
        ctk.CTkCheckBox(body, text="Show progress window for each download",
                        variable=pw_var,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        text_color=C_TEXT
                        ).pack(anchor="w", pady=6)

        section("Browser extension")
        port_var = ctk.StringVar(value=str(self.server_port))
        port_row = ctk.CTkFrame(body, fg_color="transparent")
        port_row.pack(fill="x")
        ctk.CTkLabel(port_row, text="Port:",
                     font=ctk.CTkFont(family="Segoe UI", size=11)
                     ).pack(side="left")
        ctk.CTkEntry(port_row, textvariable=port_var, width=90, height=30
                     ).pack(side="left", padx=8)
        ctk.CTkLabel(port_row, text=f"Live: 127.0.0.1:{self.server_port}",
                     font=ctk.CTkFont(family="Segoe UI", size=11),
                     text_color=C_MUTED).pack(side="left", padx=6)

        ctk.CTkButton(body, text="🔌 Install / Reload Extension", height=34,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color="#58A6FF", command=self.install_extension
                      ).pack(fill="x", pady=10)

        section("Tools")
        ytdlp_path = yt_helper.find_ytdlp()
        # "yt-dlp --version" takes ~1.5 s (a big one-file exe): never block the
        # window on it - show the cached value or fill it in from a thread
        cached = yt_helper.ytdlp_version_cached(ytdlp_path) if ytdlp_path else None
        if not ytdlp_path:
            ytdlp_text = "yt-dlp: not found"
        elif cached is not None:
            ytdlp_text = f"yt-dlp: {cached or 'not found'}"
        else:
            ytdlp_text = "yt-dlp: checking version..."
        self.ytdlp_label = ctk.CTkLabel(body, text=ytdlp_text, anchor="w",
                                        font=ctk.CTkFont(family="Segoe UI", size=11),
                                        text_color=C_MUTED if ytdlp_path else C_RED)
        self.ytdlp_label.pack(fill="x", pady=2)
        if ytdlp_path and cached is None:
            label = self.ytdlp_label

            def read_version():
                found = yt_helper.ytdlp_version(ytdlp_path)

                def show():
                    try:
                        label.configure(text=f"yt-dlp: {found or 'not found'}")
                    except Exception:            # noqa: BLE001
                        pass                     # Options was closed meanwhile
                self.post(show)
            threading.Thread(target=read_version, daemon=True).start()

        self.ffmpeg_label = ctk.CTkLabel(body, text="", anchor="w",
                                         font=ctk.CTkFont(family="Segoe UI", size=11))
        self._refresh_ffmpeg_label()
        self.ffmpeg_label.pack(fill="x", pady=2)

        tools_row = ctk.CTkFrame(body, fg_color="transparent")
        tools_row.pack(fill="x", pady=6)

        ctk.CTkButton(tools_row, text="Update yt-dlp", width=130, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT,
                      command=lambda: self._update_ytdlp(self.ytdlp_label)
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools_row, text="Install FFmpeg (HD)", width=150, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT, command=self._install_ffmpeg
                      ).pack(side="left", padx=6)
        ctk.CTkButton(tools_row, text="Data folder", width=100, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT,
                      command=lambda: self._open_path(DATA_DIR)
                      ).pack(side="left", padx=6)
        section("Application updates")
        ctk.CTkLabel(body, text=f"BD Downloader {APP_VERSION}  |  Stable Windows releases",
                     anchor="w", text_color=C_MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=11)).pack(fill="x", pady=2)
        ctk.CTkButton(body, text="Check for App Updates", width=170, height=32,
                      fg_color=C_BLUE, hover_color=C_BLUE_HOVER,
                      text_color="#161616" if _IS_DARK else "#FFFFFF", command=self.check_for_updates
                      ).pack(anchor="w", pady=6)

        footer = ctk.CTkFrame(window, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=(0, 14))

        def save_and_close():
            old_default = self.default_save_dir
            self.default_save_dir = folder_var.get().strip() or DEFAULT_DOWNLOAD_DIR
            self.settings["default_save_dir"] = self.default_save_dir
            if os.path.normcase(old_default) != os.path.normcase(self.default_save_dir):
                # category folders that lived in the old default follow it
                paths = self.settings.get("category_paths") or {}
                old_norm = os.path.normcase(os.path.abspath(old_default))
                for key, value in list(paths.items()):
                    norm = os.path.normcase(os.path.abspath(value or ""))
                    if norm == old_norm or norm.startswith(old_norm + os.sep):
                        rel = os.path.relpath(os.path.abspath(value), os.path.abspath(old_default))
                        paths[key] = os.path.normpath(os.path.join(
                            self.default_save_dir, "" if rel == "." else rel))
            self.max_concurrent = max(1, int(concurrent_slider.get()))
            self.settings["max_concurrent"] = self.max_concurrent
            self.connections = max(1, int(connections_slider.get()))
            self.settings["connections"] = self.connections
            self.settings["auto_start"] = bool(auto_var.get())
            self.settings["ask_save_path"] = bool(ask_var.get())
            self.settings["clipboard_monitor"] = bool(clip_var.get())
            self.settings["sound_on_complete"] = bool(sound_var.get())
            self.settings["check_updates"] = bool(updates_var.get())
            self.settings["max_retries"] = max(0, int(retry_slider.get()))
            self.settings["show_progress_window"] = bool(pw_var.get())
            self.settings["theme"] = theme_var.get()
            self.settings["start_with_windows"] = bool(startup_var.get())
            self.settings["start_minimized"] = bool(minimize_var.get())
            self.settings["close_to_tray"] = bool(close_var.get())
            self.settings["ui_revision"] = UI_REVISION
            self._sync_windows_startup()
            try:
                new_port = int(port_var.get().strip())
            except ValueError:
                new_port = self.server_port
            self.save_settings()
            if new_port != self.server_port:
                self.start_server(new_port)
            self.show_status("Options saved", "success")
            window.destroy()

        ctk.CTkButton(footer, text="Save", width=110, height=34, fg_color=C_BLUE,
                      hover_color=C_BLUE_HOVER,
                      command=save_and_close).pack(side="right", padx=6)
        ctk.CTkButton(footer, text="Cancel", width=110, height=34,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT, command=window.destroy
                      ).pack(side="right", padx=6)

    def _refresh_ffmpeg_label(self):
        ffmpeg = yt_helper.find_ffmpeg()
        if ffmpeg:
            self.ffmpeg_label.configure(
                text="FFmpeg: installed  (1080p/4K merging + MP3 ready)",
                text_color=C_GREEN)
        else:
            self.ffmpeg_label.configure(
                text="FFmpeg: missing - 1080p+ and MP3 need it. Click Install FFmpeg.",
                text_color=C_ORANGE)

    def _update_ytdlp(self, label):
        def work():
            ok, message = yt_helper.update_ytdlp()
            version = yt_helper.ytdlp_version()

            def done():
                try:
                    label.configure(text=f"yt-dlp: {version or 'unknown'}",
                                    text_color=C_GREEN if ok else C_RED)
                except Exception:                # noqa: BLE001
                    pass
                self.show_status(f"yt-dlp: {message}", "success" if ok else "error")
            self.post(done)

        self.show_status("Updating yt-dlp...")
        threading.Thread(target=work, daemon=True).start()

    def _install_ffmpeg(self):
        def work():
            ok, message = yt_helper.install_ffmpeg(
                progress_cb=lambda text: self.post(
                    lambda: self.show_status(text)))

            def done():
                self._refresh_ffmpeg_label()
                self.show_status(
                    "FFmpeg installed! 1080p/4K downloads now work." if ok
                    else f"FFmpeg install failed: {message}",
                    "success" if ok else "error")
            self.post(done)

        self.show_status("Downloading FFmpeg (about 80 MB), please wait...")
        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- extension
    def extension_dir(self):
        for base in (yt_helper.installed_dir(), yt_helper.resource_dir()):
            path = os.path.join(base, "extension")
            if os.path.isfile(os.path.join(path, "manifest.json")):
                return path
        return os.path.join(yt_helper.installed_dir(), "extension")

    @staticmethod
    def _find_browser(executable):
        found = shutil.which(executable)
        if found:
            return found
        roots = (os.environ.get("PROGRAMFILES"),
                 os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA"))
        for root in roots:
            if not root:
                continue
            for relative in (os.path.join("Microsoft", "Edge", "Application", executable),
                             os.path.join("Google", "Chrome", "Application", executable)):
                candidate = os.path.join(root, relative)
                if os.path.isfile(candidate):
                    return candidate
        return None

    def install_extension(self):
        folder = self.extension_dir()
        if not os.path.isfile(os.path.join(folder, "manifest.json")):
            messagebox.showerror(
                "Extension not found",
                "The 'extension' folder is missing.\n\n"
                "Keep the extension folder next to VibeDownloader.exe.")
            return

        try:
            self.clipboard_clear()
            self.clipboard_append(folder)
        except Exception:                        # noqa: BLE001
            pass

        opened = False
        for browser, page in ((self._find_browser("msedge.exe"), "edge://extensions"),
                              (self._find_browser("chrome.exe"), "chrome://extensions")):
            if not browser:
                continue
            try:
                subprocess.Popen([browser, page])
                opened = True
            except Exception:                    # noqa: BLE001
                pass

        self._open_path(folder)
        self.show_status("Extension folder copied to clipboard", "success")

        messagebox.showinfo(
            "Install the extension",
            "1. Edge/Chrome extensions page is opening.\n"
            "2. Turn ON 'Developer mode' (top right).\n"
            "3. Click 'Load unpacked'.\n"
            "4. Paste the path (already copied) and press Enter.\n\n"
            f"Folder:\n{folder}" + ("" if opened else
                                    "\n\nOpen edge://extensions manually."))

    def check_for_updates(self):
        """The Help menu updates the app, not the separate yt-dlp tool."""
        self._check_app_update()

    def _ensure_update_dialog(self):
        # Opened from Options? Options holds the input grab, which would keep the
        # update window behind it and unclickable: hand the grab back first.
        try:
            holder = self.grab_current()
            if holder is not None:
                holder.grab_release()
        except Exception:                        # noqa: BLE001
            pass
        if self._update_dialog is not None and self._update_dialog.alive:
            window_frame._bring_to_front(self._update_dialog)
            return self._update_dialog
        palette = {
            "bg": C_BG, "panel": C_PANEL, "border": C_BORDER, "text": C_TEXT,
            "muted": C_MUTED, "accent": C_BLUE, "accent_hover": C_BLUE_HOVER,
            "accent_text": "#161616" if _IS_DARK else "#FFFFFF",
            "error": C_RED, "success": C_GREEN,
        }

        def closed(window):
            if self._update_dialog is window:
                self._update_dialog = None

        self._update_dialog = AppUpdateDialog(
            self, palette=palette, data_dir=DATA_DIR, on_check=self.check_for_updates,
            on_install=self._install_app_update, on_close=closed)
        return self._update_dialog

    def _check_app_update(self, silent=False):
        if not self.running or self._update_install_running:
            return
        dialog = self._update_dialog
        if dialog is not None and dialog.alive and dialog.busy:
            if not silent:
                dialog.lift()
            return
        if not silent:
            self._ensure_update_dialog().show_checking()
        if self._update_check_running:
            return
        self._update_check_running = True

        def worker():
            info, error = None, None
            try:
                info = app_updater.check_for_updates()
            except app_updater.UpdateError as exc:
                error = str(exc)
            app_updater.record_check(os.path.join(DATA_DIR, "update_state.json"), error is None)
            self.post(lambda: self._finish_update_check(info, error, silent))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update_check(self, info, error, silent):
        self._update_check_running = False
        if not self.running:
            return
        dialog = self._update_dialog
        if not silent and (dialog is None or not dialog.alive):
            return  # Closing a manual check must not reopen its window later.
        if dialog is not None and dialog.alive and dialog.busy:
            return  # A background check cannot interrupt an active download/install.
        if error:
            if dialog is not None and dialog.alive:
                dialog.show_error(error)
            elif not silent:
                self._ensure_update_dialog().show_error(error)
            return
        if info is None:
            if dialog is not None and dialog.alive:
                dialog.show_current()
            return
        self._pending_update = info
        if silent:
            self._show_window()
        self._ensure_update_dialog().show_available(info)

    def _auto_update_check(self):
        if not self.running:
            return
        self.after(3600 * 1000, self._auto_update_check)
        if self.settings.get("check_updates", True) and app_updater.should_check_automatically(
                os.path.join(DATA_DIR, "update_state.json")):
            self._check_app_update(silent=True)

    def _install_app_update(self, info, installer_path):
        if self._update_install_running or not getattr(sys, "frozen", False):
            return
        self._update_install_running = True
        self._ensure_update_dialog().show_installing()

        def worker():
            try:
                # Our one-file PyInstaller bootloader outlives the Python child
                # while deleting its extracted files. Wait for BOTH to exit so
                # the installer does not race a still-mapped old executable.
                app_updater.launch_installer(
                    installer_path, info, yt_helper.installed_dir(), os.getppid())
            except app_updater.UpdateError as exc:
                self.post(lambda message=str(exc): self._update_install_failed(message))
            else:
                self.post(self._close_for_update)

        threading.Thread(target=worker, daemon=True).start()

    def _update_install_failed(self, message):
        self._update_install_running = False
        if self._update_dialog is not None and self._update_dialog.alive:
            self._update_dialog.show_install_error(message)

    def _close_for_update(self):
        # Stop scheduling and wait for pause/resume state before leaving the tray.
        self._update_shutdown = True
        self._queue_action_fired = True
        with self.lock:
            for task in list(self.tasks.values()):
                if task.status in ("downloading", "pausing"):
                    if task.pause_event:
                        task.pause_event.set()
                    task.status = "pausing"
                elif task.status == "queued":
                    task.status = "paused"
        self.show_status("Pausing downloads before installing the update...")
        deadline = time.monotonic() + 60

        def finish():
            active = any(task.status in ("downloading", "pausing")
                         for task in list(self.tasks.values()))
            if active and time.monotonic() < deadline:
                self.after(250, finish)
                return
            self._real_close()

        self.after(250, finish)

    def show_about(self):
        messagebox.showinfo(
            "About",
            f"{APP_DISPLAY_NAME} {APP_VERSION}\n\n"
            "Fast multi-connection download manager\n"
            "• multi-connection downloads with resume\n"
            "• yt-dlp for YouTube and 1800+ sites\n"
            "• Chrome / Edge extension\n\n"
            f"Data folder:\n{DATA_DIR}")

    # ------------------------------------------------------------------ server
    def start_server(self, port=None):
        self.stop_server()
        port = int(port or self.server_port or 8765)
        handler = type("Handler", (ApiHandler,), {"app": self})
        for candidate in range(port, port + 12):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            except OSError:
                continue
            self.httpd = httpd
            self.server_port = candidate
            self.settings["port"] = candidate
            self.save_settings()
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            if candidate != port:
                self.show_status(
                    f"Port {port} busy - using {candidate}. "
                    "Set the same port in the extension popup.", "warning")
            else:
                self.show_status(
                    f"Extension server ready on 127.0.0.1:{candidate}", "success")
            self.update_stats()
            return
        self.show_status("Could not start the extension server (ports busy)", "error")

    def stop_server(self):
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:                    # noqa: BLE001
                pass
            self.httpd = None

    def focus_search(self):
        try:
            self._show_window()
            self.search_entry.focus_set()
            self.search_entry.select_range(0, "end")
        except Exception:                    # noqa: BLE001
            pass

    def _on_search(self):
        if not hasattr(self, "list_container"):
            return
        self.search_text = self.search_entry.get() if hasattr(self, "search_entry") else ""
        self._last_order = []
        self.render()

    def _sort_by(self, column):
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = column in ("date", "size", "speed")
        arrow = " ↓" if self._sort_reverse else " ↑"
        for col, header in getattr(self, "_header_labels", {}).items():
            base = dict(COLUMNS).get(col, col) if False else None
            text = next((label for key, label, _w, _a in COLUMNS if key == col), col)
            try:
                header.configure(text=text + (arrow if col == column else ""))
            except Exception:                    # noqa: BLE001
                pass
        self._last_order = []
        self.render()

    def _space_toggle(self):
        task = self.selected_task()
        if not task:
            return
        if task.status == "downloading":
            self.pause_task(task)
        elif task.status in ("paused", "error", "queued"):
            self.start_task(task)

    def _open_or_progress(self, task):
        if task.status == "completed":
            self.open_task_file(task)
        else:
            self._open_progress_window(task)

    def _open_selected_progress(self):
        task = self.selected_task()
        if task:
            self._open_progress_window(task)

    def _move_in_queue(self, task, direction):
        ordered = [item for item in self._ordered_tasks()
                   if item.queue_id and item.status != "completed"]
        if task not in ordered:
            return
        index = ordered.index(task)
        swap = index + direction
        if swap < 0 or swap >= len(ordered):
            return
        other = ordered[swap]
        task.queue_order, other.queue_order = other.queue_order, task.queue_order
        self._last_order = []
        self.save_history()
        self.render()

    def _notify_complete(self, task):
        # Quiet, like every VibeCoder app: no Windows "ding", our own soft chime,
        # and a silent tray note that leaves by itself after a few seconds.
        if self.settings.get("sound_on_complete", True):
            quiet_notify.play_chime()
        icon = getattr(self, "tray_icon", None)
        if icon is not None:
            quiet_notify.quiet_notify(icon, f"Download complete: {task.name}", APP_DISPLAY_NAME)

    def _queue_finished(self, action):
        self.show_status("Queue finished", "success")
        if action in (None, "", "none"):
            return
        labels = {
            "exit": "exit BD Downloader",
            "sleep": "put this PC to sleep",
            "shutdown": "shut down this PC",
        }
        if not messagebox.askyesno(
                "Queue finished",
                f"The download queue is finished.\n\n{labels.get(action, action)} now?"):
            return
        if action == "exit":
            self._real_close()
            return
        if os.name != "nt":
            return
        if action == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "20", "/c",
                              "BD Downloader: queue finished"])

    def _sync_windows_startup(self):
        if os.name != "nt":
            return
        want = bool(self.settings.get("start_with_windows", True))
        try:
            if want != windows_startup.is_startup_enabled():
                windows_startup.set_startup_enabled(want)
        except Exception:                        # noqa: BLE001
            pass

    def _seed_clipboard(self):
        self._last_clip = self._clipboard_url()
        self._poll_clipboard()

    def _poll_clipboard(self):
        try:
            if (self.settings.get("clipboard_monitor", False)
                    and not self._download_dialog_open):
                url = self._clipboard_url()
                if url and url != self._last_clip and url != self._ignore_clip:
                    known = any(task.url == url and task.status != "completed"
                                for task in self.tasks.values())
                    self._last_clip = url
                    if not known:
                        self.api_add({"url": url, "kind": "auto"})
                        self.show_status("Clipboard link caught — confirm to download",
                                         "success")
                elif url:
                    self._last_clip = url
        except Exception:                        # noqa: BLE001
            pass
        if self.running:
            self.after(1200, self._poll_clipboard)

    def _enable_file_drop(self):
        # Tk's window procedure cannot be subclassed safely from Python.
        # Clipboard monitoring already catches new URLs.
        return

    def _on_drop(self, paths):
        for path in paths or []:
            url = ""
            if re.match(r"^https?://", path or "", re.I):
                url = path.strip()
            elif path.lower().endswith(".url") and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                        for line in handle:
                            if line.lower().startswith("url="):
                                url = line.split("=", 1)[1].strip()
                                break
                except OSError:
                    url = ""
            if url:
                self.api_add({"url": url, "kind": "auto"})

    def _confirm_grab(self, entries, referrer):
        entries = [(url, headers) for url, headers in entries if url]
        urls = [url for url, _headers in entries]
        if not urls:
            messagebox.showinfo("Grabber", "No downloadable links found on this page.")
            return
        if not messagebox.askyesno(
                "Grabber",
                f"Found {len(urls)} downloadable link(s).\n\n"
                "Add them to the queue (Download Later)?"):
            return
        added = 0
        for url, headers in entries[:200]:
            kind = "media" if yt_helper.is_media_url(url) else "file"
            guessed = sanitize_filename(os.path.basename(urlparse(url).path)) or "download"
            task = self._build_task(url, guessed, kind, "best", dict(headers))
            task.kind = "grabber" if kind == "file" else kind
            task.autostart = False
            task.description = referrer or "Grabbed from page"
            self._register_task(task)
            added += 1
        self.show_status(f"Grabbed {added} link(s) into the queue", "success")
        self.select_category("queues")

    # ------------------------------------------------------------------- close
    def on_closing(self):
        """X button: hide to the tray, unless Options says to exit."""
        if self.settings.get("close_to_tray", True) and self._start_tray():
            self.withdraw()
            self.show_status("Still running in the tray")
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                quiet_notify.quiet_notify(getattr(self, "tray_icon", None),
                                          "BD Downloader is still running in the tray. Right-click the icon and choose Exit to close it.",
                                          APP_DISPLAY_NAME)
            return "break"
        self._real_close()
        return "break"

    def _tray_log(self, text):
        try:
            with open(os.path.join(DATA_DIR, "tray.log"), "a", encoding="utf-8") as handle:
                handle.write(time.strftime("%H:%M:%S ") + text + "\n")
        except Exception:                        # noqa: BLE001
            pass

    def _show_window(self):
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.focus_force()
            self._tray_log("window shown")
        except Exception as exc:                 # noqa: BLE001
            self._tray_log(f"show failed: {exc!r}")

    def _real_close(self):
        if not self.running:
            return
        self.running = False
        if self._update_dialog is not None:
            self._update_dialog._cancel.set()
        for task in list(self.tasks.values()):
            if task.stop_event:
                task.stop_event.set()
        self._close_all_progress_windows()
        if getattr(self, "tray_icon", None) is not None:
            try:
                self.tray_icon.stop()
            except Exception:                    # noqa: BLE001
                pass
            self.tray_icon = None
        self.save_history()
        self.save_settings()
        self.stop_server()
        try:
            self.destroy()
        except Exception:                        # noqa: BLE001
            pass

    def _start_tray(self):
        """Create the tray icon once. Returns True if the tray is available."""
        if getattr(self, "tray_icon", None) is not None:
            return True
        try:
            import pystray
            from PIL import Image
        except Exception as exc:                 # noqa: BLE001
            self._tray_log(f"pystray import failed: {exc!r}")
            return False

        # --- load icon image (works both in source and PyInstaller bundle) ---
        image = None
        candidates = []
        try:
            import sys as _sys
            if getattr(_sys, "frozen", False):
                candidates.append(os.path.join(_sys._MEIPASS, "VibeDownloader.ico"))
        except Exception:                    # noqa: BLE001
            pass
        candidates += [
            os.path.join(yt_helper.installed_dir(), "VibeDownloader.ico"),
            os.path.join(yt_helper.resource_dir(), "VibeDownloader.ico"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "VibeDownloader.ico"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    image = Image.open(path)
                    break
                except Exception:            # noqa: BLE001
                    pass
        if image is None:
            image = Image.new("RGB", (64, 64), "#1F6FEB")

        # pystray callbacks run in another thread -> hand over to the Tk thread
        def on_show(_icon=None, _item=None):
            self._tray_log("tray click -> show")
            self.post(self._show_window)

        def on_exit(_icon=None, _item=None):
            self._tray_log("tray exit")
            self.post(self._real_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show", on_show, default=True, visible=False),
            pystray.MenuItem("Add URL...", lambda i: self.post(self.open_add_dialog)),
            pystray.MenuItem("Start Queue", lambda i: self.post(self.start_queue)),
            pystray.MenuItem("Stop Queue", lambda i: self.post(self.stop_queue)),
            pystray.MenuItem("Start All", lambda i: self.post(self.start_all)),
            pystray.MenuItem("Stop All", lambda i: self.post(self.pause_all)),
            pystray.MenuItem("Check for Updates", lambda i: self.post(self.check_for_updates)),
            pystray.MenuItem("Exit", on_exit),
        )
        try:
            self.tray_icon = pystray.Icon("VibeDownloader", image,
                                          "BD Downloader", menu)
            self.tray_icon.run_detached()
        except Exception as exc:                 # noqa: BLE001
            self._tray_log(f"tray start failed: {exc!r}")
            self.tray_icon = None
            return False
        self._tray_log("tray started")
        return True


def _acquire_single_instance():
    """One resident process. A second launch reveals the first."""
    if os.name != "nt":
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, "Local\\VibeDownloader.SingleInstance")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:           # ERROR_ALREADY_EXISTS
        return False
    return True


def _notify_existing():
    port = 8765
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            port = int(json.load(handle).get("port") or 8765)
    except Exception:                            # noqa: BLE001
        port = 8765
    import urllib.request
    payload = json.dumps({"action": "show"}).encode("utf-8")
    candidates = [port] + [item for item in range(8765, 8777) if item != port]
    for candidate in candidates:
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{candidate}/download",
                data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except Exception:                        # noqa: BLE001
            continue
    return False


def main():
    # A release-runner check must not acquire the user's singleton, register
    # startup, check online updates, or launch the normal download scheduler.
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from bundle_self_test import run_self_test
        raise SystemExit(run_self_test(sys.argv[2]))
    if not _acquire_single_instance():
        for _ in range(10):
            if _notify_existing():
                return
            time.sleep(0.25)
        return
    # --startup is the tray launch from Windows sign-in. A normal double-click,
    # including the installed exe, must show the window.
    startup = "--startup" in sys.argv
    updated = "--updated" in sys.argv
    app = VibeDownloaderApp(startup_launch=startup)

    # When starting from Windows startup the window stays hidden in tray.
    # Only lift/topmost when the user launched the app manually.
    if not startup:
        app.lift()
        app.attributes("-topmost", True)
        app.after(200, lambda: app.attributes("-topmost", False))
    if updated:
        app.after(900, lambda: messagebox.showinfo(
            "Update complete", f"{APP_DISPLAY_NAME} was updated successfully to version {APP_VERSION}."))
    app.mainloop()


if __name__ == "__main__":
    main()

"""
VibeDownloader - YouTube / media support through yt-dlp.

yt-dlp does the "magic" for YouTube, Vimeo, TikTok, Facebook, Instagram,
Twitter/X, SoundCloud and ~1800 other sites. It is shipped with the app as
yt-dlp.exe; if it is missing we also look for a pip-installed one.
"""

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

import requests

APP_NAME = "VibeDownloader"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "vimeo.com", "dailymotion.com", "vimeo.com",
    "facebook.com", "fb.watch", "instagram.com",
    "tiktok.com", "twitter.com", "x.com",
    "soundcloud.com", "twitch.tv", "reddit.com", "redd.it",
    "bilibili.com", "rumble.com", "odysee.com",
    "pinterest.com", "linkedin.com", "vk.com", "ok.ru",
    "kick.com", "streamable.com", "bitchute.com",
    "bandcamp.com", "mixcloud.com", "audiomack.com",
)

HEIGHTS = {
    "2160p": 2160, "1440p": 1440, "1080p": 1080,
    "720p": 720, "480p": 480, "360p": 360,
}

FFMPEG_URLS = [
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]


# --------------------------------------------------------------------- paths
def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.dirname(os.path.abspath(__file__))
    return path


def resource_dir():
    """Folder that holds bundled files (works for PyInstaller one-file)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def installed_dir():
    """Folder where the .exe (or main.py) lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------- child process env
def child_env():
    """Clean environment for launching yt-dlp.exe / ffmpeg.exe.

    This app is a PyInstaller exe and yt-dlp.exe is a PyInstaller exe too.
    If the parent's PyInstaller variables leak into the child, the child tries
    to load the parent's DLLs and dies with "0xc0000142". Removing them (and
    asking PyInstaller to reset) fixes it.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("_PYI") or key in ("_MEIPASS2", "_MEIPASS",
                                              "PYTHONHOME", "PYTHONPATH"):
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    # drop the parent's temp extraction folder from PATH (one-file builds)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass = os.path.normcase(os.path.abspath(meipass))
        parts = [p for p in env.get("PATH", "").split(os.pathsep)
                 if os.path.normcase(os.path.abspath(p)) != meipass]
        env["PATH"] = os.pathsep.join(parts)
    return env


# ------------------------------------------------------------------- yt-dlp
def find_ytdlp():
    names = ["yt-dlp.exe", "yt-dlp"] if os.name == "nt" else ["yt-dlp"]
    for folder in (installed_dir(), app_data_dir(), resource_dir()):
        for name in names:
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate):
                return candidate
    return shutil.which("yt-dlp")


def ensure_ytdlp():
    """Return a runnable yt-dlp path, copying the bundled one if needed."""
    found = find_ytdlp()
    if found:
        return found

    name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    for folder in (resource_dir(), installed_dir()):
        source = os.path.join(folder, name)
        if os.path.isfile(source):
            target = os.path.join(app_data_dir(), name)
            try:
                shutil.copy2(source, target)
                return target
            except OSError:
                return source
    return None


def ytdlp_version(path=None):
    path = path or ensure_ytdlp()
    if not path:
        return ""
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True,
            timeout=15, creationflags=CREATE_NO_WINDOW, env=child_env(),
        )
        return (result.stdout or "").strip().splitlines()[0]
    except Exception:                            # noqa: BLE001
        return ""


def update_ytdlp(progress_cb=None):
    path = ensure_ytdlp()
    if not path:
        return False, "yt-dlp is not installed"
    try:
        if progress_cb:
            progress_cb("Updating yt-dlp...")
        result = subprocess.run(
            [path, "-U"], capture_output=True, text=True, timeout=180,
            creationflags=CREATE_NO_WINDOW, env=child_env(),
        )
        text = ((result.stdout or "") + (result.stderr or "")).strip()
        return result.returncode == 0, (text.splitlines()[-1] if text else "")
    except Exception as exc:                     # noqa: BLE001
        return False, str(exc)


# --------------------------------------------------------------- app updates
APP_REPO = "jhfarhanyt20-coder/VibeDownloader"
APP_UPDATE_URL = f"https://api.github.com/repos/{APP_REPO}/releases/latest"


def _parse_version(text):
    """Return a tuple of ints from a version string like '2.3.0'."""
    nums = re.findall(r"\d+", (text or ""))
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def current_version():
    """Return the running app version tuple."""
    try:
        from main import APP_VERSION
        return _parse_version(APP_VERSION)
    except Exception:                        # noqa: BLE001
        return (0,)


def check_app_update():
    """Return (latest_version_str, download_url, asset_size) or None on failure."""
    try:
        req = requests.get(
            APP_UPDATE_URL,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "VibeDownloader-updater"},
            timeout=20,
        )
        if req.status_code != 200:
            return None
        data = req.json()
        tag = (data.get("tag_name") or "").lstrip("v")
        if not tag:
            return None
        latest = _parse_version(tag)
        if latest <= current_version():
            return None
        assets = data.get("assets") or []
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".exe") and "Installer" in name:
                return (tag, asset.get("browser_download_url"), asset.get("size"))
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".exe"):
                return (tag, asset.get("browser_download_url"), asset.get("size"))
        return (tag, data.get("html_url"), None)
    except Exception:                        # noqa: BLE001
        return None


def download_app_update(url, dest, progress_cb=None):
    """Stream the update installer to dest. Returns True on success."""
    try:
        with requests.get(url, stream=True, timeout=(20, 300)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as handle:
                for chunk in resp.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(f"Downloading update... {done * 100 // total}%")
        return os.path.isfile(dest) and os.path.getsize(dest) > 1024 * 1024
    except Exception:                        # noqa: BLE001
        return False


def install_app_update(installer_path):
    """Launch the new installer with /SILENT and exit the current process."""
    if not os.path.isfile(installer_path):
        return False
    try:
        subprocess.Popen(
            [installer_path, "/SILENT", "/SP-", "/DIR=" + installed_dir()],
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return True
    except Exception:                        # noqa: BLE001
        return False


def update_ytdlp_secure(progress_cb=None):
    """Download the official yt-dlp Windows build, verify it, replace with rollback."""
    target = ensure_ytdlp() or os.path.join(installed_dir(), "yt-dlp.exe")
    backup = target + ".bak"
    temp = target + ".new"
    url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    try:
        if os.path.isfile(target):
            try:
                shutil.copy2(target, backup)
            except OSError:
                pass
        if progress_cb:
            progress_cb("Downloading yt-dlp update...")
        with requests.get(url, stream=True, timeout=(20, 120)) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(temp, "wb") as handle:
                for chunk in resp.iter_content(1024 * 256):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(f"Downloading yt-dlp... {done * 100 // total}%")
        # validate
        if not os.path.isfile(temp) or os.path.getsize(temp) < 1024 * 1024:
            raise RuntimeError("Downloaded yt-dlp is too small")
        with open(temp, "rb") as handle:
            if handle.read(2) != b"MZ":
                raise RuntimeError("Downloaded yt-dlp is not a valid Windows executable")
        # replace
        try:
            os.replace(temp, target)
        except OSError:
            # fallback: remove then move
            if os.path.isfile(target):
                os.remove(target)
            os.replace(temp, target)
        if progress_cb:
            progress_cb("yt-dlp updated successfully")
        # cleanup backup on success? keep for rollback? remove to save space but keep one
        return True, "yt-dlp updated"
    except Exception as exc:                     # noqa: BLE001
        # rollback
        try:
            if os.path.isfile(backup):
                os.replace(backup, target)
        except OSError:
            pass
        try:
            if os.path.isfile(temp):
                os.remove(temp)
        except OSError:
            pass
        return False, str(exc)


# ------------------------------------------------------------------- ffmpeg
def find_js_runtime():
    """Return (name, path) for a JS runtime yt-dlp can use, or None."""
    # 1) a runtime shipped with the app (works on any PC, nothing to install)
    for folder in (installed_dir(), resource_dir(),
                   os.path.join(installed_dir(), "tools"),
                   os.path.join(resource_dir(), "tools"),
                   os.path.join(app_data_dir(), "tools")):
        for name in ("deno", "node", "bun"):
            candidate = os.path.join(folder, name + (".exe" if os.name == "nt" else ""))
            if os.path.isfile(candidate):
                return name, candidate
    # 2) one already installed on this PC
    for name in ("deno", "node", "bun", "quickjs"):
        found = shutil.which(name)
        if found:
            return name, found
    return None


def find_ffmpeg():
    # The release installer embeds FFmpeg so a new user does not need an
    # extra first-run download. Keep legacy/app-local locations as fallbacks.
    bundled = os.path.join(app_data_dir(), "ffmpeg", "bin", "ffmpeg.exe")
    if os.path.isfile(bundled):
        return bundled
    for folder in (os.path.join(resource_dir(), "tools"),
                   os.path.join(installed_dir(), "tools"),
                   resource_dir(), installed_dir()):
        candidate = os.path.join(folder, "ffmpeg.exe")
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("ffmpeg")


def find_ffprobe():
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        probe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
        if os.path.isfile(probe):
            return probe
    return shutil.which("ffprobe")


def install_ffmpeg(progress_cb=None):
    """Download a static ffmpeg build and keep only ffmpeg/ffprobe.exe."""
    target_dir = os.path.join(app_data_dir(), "ffmpeg", "bin")
    os.makedirs(target_dir, exist_ok=True)
    tmp_zip = os.path.join(app_data_dir(), "ffmpeg-download.zip")

    last_error = ""
    for url in FFMPEG_URLS:
        try:
            with requests.get(url, stream=True, timeout=(20, 60)) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                started = time.time()
                last_update = 0.0
                with open(tmp_zip, "wb") as handle:
                    for chunk in resp.iter_content(1024 * 256):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if progress_cb and total and now - last_update >= 0.5:
                            last_update = now
                            speed = done / max(0.1, now - started)
                            progress_cb(f"Downloading FFmpeg... "
                                        f"{done * 100 // total}% "
                                        f"({speed / 1048576:.1f} MB/s)")
            with zipfile.ZipFile(tmp_zip) as archive:
                wanted = ("bin/ffmpeg.exe", "bin/ffprobe.exe")
                for member in archive.namelist():
                    if member.replace("\\", "/").endswith(wanted):
                        filename = os.path.basename(member)
                        with archive.open(member) as source, \
                                open(os.path.join(target_dir, filename), "wb") as out:
                            shutil.copyfileobj(source, out)
            for filename in ("ffmpeg.exe", "ffprobe.exe"):
                if not os.path.isfile(os.path.join(target_dir, filename)):
                    raise RuntimeError("ffmpeg.exe was not inside the archive")
            try:
                os.remove(tmp_zip)
            except OSError:
                pass
            return True, target_dir
        except Exception as exc:                 # noqa: BLE001
            last_error = str(exc)
            continue

    return False, last_error or "FFmpeg download failed"


# ------------------------------------------------------------------- helpers
def is_media_url(url):
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == item or host.endswith("." + item)
                   for item in MEDIA_HOSTS)
    except Exception:                            # noqa: BLE001
        return False


def format_selector(quality, has_ffmpeg):
    height = HEIGHTS.get(quality or "")
    if quality == "audio":
        return "bestaudio/best"
    if height and has_ffmpeg:
        return (f"bv*[height<={height}]+ba/"
                f"b[height<={height}]/b")
    if height:
        # No ffmpeg -> must use a progressive (already muxed) stream.
        return (f"b[height<={height}][ext=mp4]/"
                f"b[height<={height}]/b[ext=mp4]/b")
    if has_ffmpeg:
        return "bv*+ba/b"
    return "b[ext=mp4]/b"


def _kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            proc.terminate()
    except Exception:                            # noqa: BLE001
        pass
    try:
        proc.wait(timeout=6)
    except Exception:                            # noqa: BLE001
        try:
            proc.kill()
        except Exception:                        # noqa: BLE001
            pass


def friendly_ytdlp_error(lines, has_ffmpeg):
    text = " ".join(lines)
    low = text.lower()
    if "sign in to confirm" in low or "bot" in low and "sign in" in low:
        return ("YouTube asked for a login check. Install the browser extension "
                "and retry (it sends your browser cookies), or update yt-dlp.")
    if "ffmpeg" in low:
        return ("FFmpeg is required for this quality. Open Settings and click "
                "'Install FFmpeg', then press Start again.")
    if "private video" in low or "login required" in low:
        return "This video is private or needs a login. Use the extension so cookies are sent."
    if "age" in low and "confirm" in low:
        return "Age-restricted video. Use the extension so your account cookies are sent."
    if "requested format is not available" in low:
        return ("That quality is not available for this video. "
                "Use 'Best available' or install FFmpeg from Options.")
    if "http error 403" in low:
        return "HTTP 403 - the video URL expired. Press Start again, or update yt-dlp."
    if "http error 404" in low or "video unavailable" in low:
        return "Video not found or not available in your region."
    if "unsupported url" in low:
        return "This site is not supported by yt-dlp."
    if "timed out" in low or "timeout" in low:
        return "Network timeout. Check your internet and press Start again."
    if "no space" in low or "disk full" in low:
        return "Not enough disk space."

    cleaned = [line for line in lines if line.strip()
               and not line.startswith("VIBE")
               and not line.startswith("WARNING")]
    if cleaned:
        return cleaned[-1][:200]
    return "yt-dlp failed"


class YtDlpRunner:
    """Run yt-dlp and translate its output into task progress."""

    def __init__(self, url, save_dir, quality="best", headers=None,
                 on_progress=None, on_file=None, speed_limit=0):
        self.url = url
        self.save_dir = save_dir
        self.quality = quality or "best"
        self.headers = dict(headers or {})
        self.on_progress = on_progress        # (downloaded, total, speed)
        self.on_file = on_file                # (final_path)
        self.speed_limit = max(0, int(speed_limit or 0))

    def _build_command(self, exe, ffmpeg):
        output = os.path.join(self.save_dir,
                              "%(title).150B [%(id)s].%(ext)s")
        command = [
            exe,
            "--newline",
            "--no-playlist",
            "--no-simulate",
            "--progress",
            "--progress-template",
            "download:VIBE|%(progress.downloaded_bytes)s|"
            "%(progress.total_bytes)s|"
            "%(progress.total_bytes_estimate)s|"
            "%(progress.speed)s",
            "--print", "after_move:VIBEFILE:%(filepath)s",
            "--windows-filenames",
            "--no-mtime",
            "--retries", "10",
            "--fragment-retries", "10",
            "--concurrent-fragments", "16",
            "--buffer-size", "64K",
            "-o", output,
            "-f", format_selector(self.quality, bool(ffmpeg)),
        ]

        if self.speed_limit:
            command += ["--limit-rate", str(int(self.speed_limit))]

        if self.quality == "audio":
            if ffmpeg:
                command += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        elif ffmpeg:
            command += ["--merge-output-format", "mp4"]

        if ffmpeg:
            command += ["--ffmpeg-location", os.path.dirname(ffmpeg)]

        js = find_js_runtime()
        if js:
            command += ["--js-runtimes", f"{js[0]}:{js[1]}"]

        for key, value in self.headers.items():
            if not value:
                continue
            if key.lower() == "user-agent":
                command += ["--user-agent", str(value)]
            elif key.lower() in ("cookie", "referer", "referrer", "origin"):
                name = "Referer" if key.lower().startswith("refer") else key
                command += ["--add-header", f"{name}: {value}"]

        command.append(self.url)
        return command

    def run(self, stop_event, pause_event):
        exe = ensure_ytdlp()
        if not exe:
            return "error", ("yt-dlp.exe was not found. Put yt-dlp.exe next to "
                             "the app or run: pip install yt-dlp")

        ffmpeg = find_ffmpeg()
        os.makedirs(self.save_dir, exist_ok=True)
        command = self._build_command(exe, ffmpeg)

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
                env=child_env(),
            )
        except Exception as exc:                 # noqa: BLE001
            return "error", str(exc)

        output_queue = queue.Queue()
        error_lines = []

        def read_pipe(pipe, is_error):
            try:
                for line in iter(pipe.readline, ""):
                    output_queue.put((is_error, line.rstrip("\r\n")))
            except Exception:                    # noqa: BLE001
                pass
            finally:
                try:
                    pipe.close()
                except Exception:                # noqa: BLE001
                    pass

        threading.Thread(target=read_pipe, args=(proc.stdout, False),
                         daemon=True).start()
        threading.Thread(target=read_pipe, args=(proc.stderr, True),
                         daemon=True).start()

        started = time.time()
        last_notify = 0.0
        result_file = None
        total = 0
        downloaded = 0
        speed = 0

        while True:
            if stop_event.is_set() or pause_event.is_set():
                _kill_tree(proc)
                if stop_event.is_set():
                    return "stopped", ""
                return "paused", ""

            drained = False
            try:
                for _ in range(50):
                    is_error, line = output_queue.get_nowait()
                    drained = True
                    if is_error:
                        if line.strip():
                            error_lines.append(line.strip())
                            if len(error_lines) > 40:
                                error_lines.pop(0)
                        continue
                    if line.startswith("VIBE|"):
                        parts = line.split("|")
                        if len(parts) >= 5:
                            downloaded = _to_int(parts[1])
                            total = _to_int(parts[2]) or _to_int(parts[3])
                            speed = _to_int(parts[4])
                    elif line.startswith("VIBEFILE:"):
                        result_file = line[len("VIBEFILE:"):].strip()
            except queue.Empty:
                pass

            now = time.time()
            if now - last_notify >= 0.35:
                last_notify = now
                if self.on_progress:
                    try:
                        self.on_progress(downloaded, total, speed)
                    except Exception:            # noqa: BLE001
                        pass

            if proc.poll() is not None:
                # give the reader threads a moment to flush the last lines
                time.sleep(0.25)
                while True:
                    try:
                        is_error, line = output_queue.get_nowait()
                    except queue.Empty:
                        break
                    if is_error:
                        if line.strip():
                            error_lines.append(line.strip())
                    else:
                        if line.startswith("VIBEFILE:"):
                            result_file = line[len("VIBEFILE:"):].strip()
                break

            time.sleep(0.08)

        if self.on_progress:
            try:
                self.on_progress(downloaded or total, total, 0)
            except Exception:                    # noqa: BLE001
                pass

        if proc.returncode == 0:
            if not result_file:
                # Fall back: newest file in save_dir
                try:
                    candidates = [os.path.join(self.save_dir, n)
                                  for n in os.listdir(self.save_dir)]
                    candidates = [p for p in candidates if os.path.isfile(p)]
                    if candidates:
                        result_file = max(candidates, key=os.path.getmtime)
                except OSError:
                    pass
            if result_file and os.path.isfile(result_file) and self.on_file:
                try:
                    self.on_file(result_file)
                except Exception:                # noqa: BLE001
                    pass
            if not result_file:
                result_file = self._find_newest_file(started)
                if result_file and self.on_file:
                    try:
                        self.on_file(result_file)
                    except Exception:            # noqa: BLE001
                        pass
            return "completed", ""

        if stop_event.is_set():
            return "stopped", ""
        if pause_event.is_set():
            return "paused", ""

        # 0xC0000142 = -1073741502 : the exe could not start (DLL init failed)
        if proc.returncode in (-1073741502, 3221225794):
            return "error", ("yt-dlp.exe could not start (0xC0000142). Install "
                             "'Microsoft Visual C++ Redistributable 2015-2022 x64' "
                             "or replace yt-dlp.exe with a fresh copy.")

        return "error", friendly_ytdlp_error(error_lines, bool(ffmpeg))

    def _find_newest_file(self, since):
        """Fallback when --print did not give us the path."""
        newest = None
        newest_time = since - 5
        try:
            for name in os.listdir(self.save_dir):
                path = os.path.join(self.save_dir, name)
                if not os.path.isfile(path) or name.endswith((".part", ".ytdl")):
                    continue
                modified = os.path.getmtime(path)
                if modified >= newest_time:
                    newest, newest_time = path, modified
        except OSError:
            pass
        return newest


def _to_int(value):
    try:
        if value in ("NA", "None", "", "null"):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def media_info(url, headers=None):
    """Quick metadata for the popup: title, thumbnail, duration, heights."""
    exe = ensure_ytdlp()
    if not exe:
        raise RuntimeError("yt-dlp not found")
    command = [exe, "-J", "--no-playlist", "--no-warnings"]
    for key, value in (headers or {}).items():
        if key.lower() == "cookie":
            command += ["--add-header", f"Cookie: {value}"]
        elif key.lower() == "user-agent":
            command += ["--user-agent", str(value)]
    command.append(url)

    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=45, creationflags=CREATE_NO_WINDOW,
                            env=child_env())
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[-300:] or "yt-dlp failed")

    import json
    data = json.loads(result.stdout)
    formats = data.get("formats") or []
    heights = sorted({f.get("height") for f in formats
                      if isinstance(f.get("height"), int)}, reverse=True)
    return {
        "title": data.get("title") or "video",
        "thumbnail": data.get("thumbnail") or "",
        "duration": data.get("duration") or 0,
        "uploader": data.get("uploader") or "",
        "heights": heights[:6],
    }

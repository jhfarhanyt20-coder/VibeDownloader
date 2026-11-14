# VibeDownloader 2.1.0 — IDM-style Windows download manager

VibeDownloader is a Windows x64 download manager with multi-connection direct downloads, pause/resume, a dark IDM-style interface, and optional Chrome/Edge integration.

## For the person using the app

Download and run **`VibeDownloader_Installer.exe`**. The full installer is designed to include the app, Python runtime and required packages, `yt-dlp`, FFmpeg/FFprobe, and the browser-extension files. An end user should not need to install Python, run `pip`, or fetch FFmpeg separately.

The installer can install the desktop application and create shortcuts. Chrome and Edge intentionally restrict silent installation of locally unpacked extensions. To let the browser capture downloads, start VibeDownloader, click **Install / Reload Extension**, then enable **Developer mode** and choose **Load unpacked** in the browser page that opens. The extension folder path is copied to the clipboard. This is a one-time browser security step; it cannot safely be removed by a normal desktop installer.

## Download speed and resume

- Direct HTTP/HTTPS file downloads use up to 16 parallel byte-range connections (8 by default, adjustable in Options).
- The engine checks that range responses match the requested byte offsets and the expected file size before writing them.
- If the server does not support byte ranges, it falls back to a single stream. It also supports pause/resume using a `.part` file and a small state file.
- Larger I/O chunks reduce Python write overhead. Multiple connections can improve throughput when a server and network permit it, but cannot exceed the connection's bandwidth and may be ignored or limited by the remote server.
- Concurrent downloads are separately configurable. More connections are not always faster; start with 8 per file and raise the value only if the server/network benefits.

No download manager can promise IDM's exact speed on every host. Speed depends on server throttling, network quality, file size, and whether HTTP Range requests are enabled.

## Build a self-contained installer (developers)

Build on **64-bit Windows** with internet access. `build_windows.bat` downloads Python 3.13.17 and portable NSIS 3.13 into `%LOCALAPPDATA%\VibeDownloaderBuildTools` if needed, so you do not need a package manager or preinstalled Python/NSIS. It does not change your system PATH or your existing Python 3.15 installation. End users do not need these build tools.

1. Extract the project ZIP to a writable folder.
2. Double-click `build_windows.bat`.
3. The script installs the build dependencies, prepares the current `yt-dlp.exe`, fetches FFmpeg binaries if they are not already under `tools\`, runs PyInstaller, and compiles `VibeDownloader_Installer.exe` with NSIS.
4. Share the generated `VibeDownloader_Installer.exe` with other Windows x64 users. Do **not** share the old installer from a previous build.

The first build needs internet to fetch build-only Python/NSIS tools plus FFmpeg assets. The Windows installer can only be built on Windows; a Linux `pyinstaller` run does not create a valid Windows executable.

GitHub Actions can also build it: push this folder to a repository, then run the **Build Windows installer** workflow. It uploads the generated installer as a workflow artifact.

### Runtime requirements bundled by the build

- `customtkinter`, `requests`, `Pillow`, and `pystray`
- `yt-dlp.exe` for supported media sites
- `ffmpeg.exe` and `ffprobe.exe` for media merging/conversion
- browser-extension assets
- Python/Tk runtime and dependency files collected by PyInstaller

The yt-dlp updater in the app remains an optional online maintenance action; a new installation does not need to download yt-dlp just to start using the app.

## Run from source (developers)

```bat
py -m pip install -r requirements.txt
py main.py
```

The direct download engine itself is in `downloader.py`; YouTube and other supported media sites are handled by `yt_helper.py` and the bundled `yt-dlp.exe`.

## Run the tests

```bat
py -m unittest discover -s tests -v
py -m py_compile main.py downloader.py yt_helper.py prepare_build.py
```

The download test starts a local HTTP server, checks that several byte ranges are requested, and verifies the output byte-for-byte. It does not require an external URL or internet access.

## Browser extension

The `extension/` folder is bundled with the desktop executable and installed beside it. The browser itself still requires the user to load the unpacked extension and grant browser permissions. This is a browser security boundary, not a missing Python package.

## Data and files

- Downloads: `%USERPROFILE%\Downloads` by default (change under Options)
- Settings/history: `%LOCALAPPDATA%\VibeDownloader`
- Temporary bundled app resources: extracted automatically by PyInstaller when the executable launches
- Browser extension: installed application folder `extension\`

## Troubleshooting

| Symptom | What to check |
|---|---|
| Extension says app is not running | Start VibeDownloader; the extension communicates through localhost port 8765 (the app can select another port if busy). |
| Download is not faster with more connections | The host may throttle connections or not support `Range`; try 8 connections or let it fall back to one stream. |
| HTTP 403/404/429 | The link may need a fresh login/cookie, may have expired, or the host may be throttling requests. |
| YouTube asks you to sign in | The site may require browser cookies or a fresh yt-dlp version. Website behavior can change independently of the app. |
| 1080p/4K or MP3 merging fails | Confirm the release was built with `tools\ffmpeg.exe` and `tools\ffprobe.exe`; use a newly generated installer. |
| Installer tool download fails | Check internet/SourceForge access, then rerun `build_windows.bat`; downloaded build tools are cached under `%LOCALAPPDATA%\VibeDownloaderBuildTools`. |

## Third-party distribution note

This project packages third-party programs. Review and preserve the relevant licenses/notices for Python packages, yt-dlp, and the specific FFmpeg build before public redistribution. The FFmpeg distribution URL used by the build provides an Essentials build with GPL-enabled components; distributors must meet the license/source obligations that apply to that exact build. Do not remove third-party notices when sharing a release.

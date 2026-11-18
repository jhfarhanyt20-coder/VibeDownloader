# VibeDownloader 2.2.0 — classic UI and Windows startup

- `build_windows.bat` can provision its own build-only Python and portable NSIS locally, without winget/choco/scoop or admin installation.
- Uses a separate Python build environment so existing Python 3.15 installations are left untouched.
- Runs Python syntax checks and the downloader unit tests before packaging.
- End-user installer is intended to bundle the app runtime, FFmpeg/FFprobe, yt-dlp, and browser-extension files.

# Changes in 2.1.0

- Added a Windows release build script that prepares FFmpeg/FFprobe and yt-dlp on the build machine and packages them into a single installer workflow.
- Bundled FFmpeg/FFprobe as PyInstaller resources so users do not need a first-run FFmpeg download.
- Added missing tray dependencies (`pystray`, `Pillow`) to the runtime requirements and PyInstaller hidden imports.
- Increased direct-download I/O chunk size to 512 KiB, capped per-file concurrency at 16, and added retries for transient HTTP 429/5xx responses.
- Validate `Content-Range` offsets, file-size consistency, and ETag changes; safely fall back to single-stream mode when the server misreports range support.
- Added local-server tests for correct parallel range downloads and fallback behavior.
- Documented the one-time Chrome/Edge extension loading step and third-party redistribution considerations.

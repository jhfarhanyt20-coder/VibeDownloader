# CHANGELOG — VibeDownloader

## 2.5.0 (2026-11-15)
- Help > Check for Updates now checks the desktop app; Update yt-dlp remains a
  separate action under Options.
- Added an update window with release notes, download progress, cancellation,
  retry, and a link to the public releases page.
- Automatic stable-release checks run at startup and while the app is resident
  in the tray, at most once every 12 hours. Offline/rate-limit errors are no
  longer reported as "up to date".
- Installer downloads are restricted to this repository's HTTPS GitHub release
  assets and trusted GitHub CDN redirects. Exact size, Windows PE header, and
  SHA-256 are verified before installation. A read lock prevents replacement
  between final verification and elevation; partial downloads are not executed.
- Fixed the NSIS update command (/S and an unquoted, final /D= path), Windows UAC
  launch, graceful download pause, installer restart, and post-update confirmation.
  Declining UAC leaves the running app unchanged.
- Upgrades retain settings, history, and downloaded files. The installer no
  longer force-kills download/yt-dlp processes. Uninstall retains user data and
  deletes only installed app resources.
- Centralized app/build/installer versions in app_info.py and added Windows EXE
  version resources.
- GitHub Actions tests commits, builds Windows x64 installers on version tags,
  and publishes installer plus SHA256SUMS.txt through an atomic draft release.
  Published releases are never overwritten.
- Added offline updater, UI-controller, and release-metadata regression tests.

## 2.4.0 (2026-11-14)
- IDM-style app updates: startup update check (at most once per 12 h) plus the
  existing "Check for App Update" button now actually downloads and runs the
  installer (it previously only showed a message).
- Fixed the update dialog: the Yes/No answer was created on a worker thread
  (silently dropped) and `_apply_app_update` was never called.
- GitHub Actions now publishes a real GitHub Release with `VibeDownloader_Installer.exe`
  on every `v*` tag — the in-app updater reads `/releases/latest`, so users only
  get updates once releases exist. `main.py` and `installer.nsi` versions match (2.4.0).
- yt-dlp bundled at 2026.10.26 (latest), FFmpeg bundled at 9.0.2 (latest).

## 2.2.0 (2026-11-01)
- Classic IDM-style main window: large toolbar, category tree, dense sortable table with Date Added/Time left/Save To columns
- Native Windows menu bar (not a custom frame)
- Tray icon menu now includes Add URL, Start All, Stop All, and Exit
- Windows startup registration: app starts minimized to tray by default
- Settings Options: added "Start with Windows", "Hide window at startup", "Close to tray instead of exiting"
- Original programmatic toolbar icons (no IDM artwork used)
- Version bump to 2.2.0

## 2.1.0
- `build_windows.bat` can provision its own build-only Python and portable NSIS locally, without winget/choco/scoop or admin installation.
- Uses a separate Python build environment so existing Python 3.15 installations are left untouched.
- Runs Python syntax checks and the downloader unit tests before packaging.
- End-user installer is intended to bundle the app runtime, FFmpeg/FFprobe, yt-dlp, and browser-extension files.

# CHANGELOG — BD Downloader (formerly VibeDownloader)

## 2.7.5 (2026-11-28)
- Fixed: downloading several videos one after another could show "Complete"
  while the folder only had the first video. The browser button sometimes sent
  the player's internal stream piece ("videoplayback"), which has no title, so
  every video got the same file name and the next one "finished" as the old file.
  Now the video page itself is downloaded.
- Every video is saved under its own online title in the folder you chose, and a
  new download never reuses an older file with the same name (it becomes
  "Title (2)").
- Tab titles lose the site name ("Song - YouTube" is saved as "Song").
- YouTube, Facebook and other supported pages are saved as "Title [video id]",
  always the video's real title and never confused with another video.
- Two downloads with the same file name (for example two "file.pdf" from one page)
  no longer write into the same file; the second becomes "file (1).pdf".
- A default folder on a USB drive, NAS or D: that is not ready when Windows starts
  is no longer replaced by Downloads for good.
- Changing the default folder in Settings now also moves the remembered
  Video/Music/... folders that were inside it.
- A "Download Later" task stays paused while the scheduler window is open.
- A channel or home-feed preview downloads one video, not the whole channel.
- Very long file names keep their extension; Windows-reserved names (CON, NUL...)
  are made safe.

## 2.7.4 (2026-11-27)
- Updates now come from the renamed repository, github.com/jhfarhanyt20-coder/BD-Downloader.

## 2.7.3 (2026-11-27)
- New name: BD Downloader (formerly VibeDownloader), with a new solid blue "B"
  icon for the app and the browser extension.
- Your downloads folder, settings and the browser extension keep working as before.

## 2.7.2 (2026-11-27)
- Update checks keep working when GitHub limits its API for your network (60
  checks an hour): VibeDownloader then checks through the normal release page,
  with the same checksum verification.

## 2.7.1 (2026-11-27)
- Quiet notifications, like every VibeCoder app: no Windows "ding" when a
  download finishes, VibeDownloader's own soft chime instead, and the tray note
  leaves by itself after a few seconds.
- The first time the window is closed to the tray, a short note says it is
  still running there.

## 2.7.0 (2026-11-19)
- Our own title bar on every window - main window, dialogs, progress, update
  and message boxes - in the theme's colors, with rounded corners. Drag to
  move, double-click to maximize, resize from the edge; the taskbar button
  minimizes and restores the window like any app.
- New near-black, glossy dark theme (the default).
- The main window opens at a medium size in the middle of the screen; columns
  line up and fit; the list is much lighter and smoother with many downloads.
- Options opens about 4x faster; a window opened from another window (such as
  the update window from Options) always appears in front of it.
- Video downloads work on more sites: the extension remembers the video
  streams a page's player loads (MP4, HLS, DASH), and when yt-dlp does not
  support a site, VibeDownloader downloads that stream instead.
- Fixed: the "Category" shown at the top of Download File Info now follows the
  category you pick.
- After updating, reload the extension once on the browser's extensions page
  (it needs one new permission to see the page's video streams).

## 2.6.0 (2026-11-18)
- New download progress window: Download status / Speed Limiter / Options on
  completion tabs, file size, transfer rate, time left, resume capability, a
  map of every connection's progress and a per-connection table.
- New "Download complete" dialog with Open, Open with..., Open folder and Close.
- Downloads now start in the background while "Download File Info" is open;
  the part already downloaded moves into the folder you choose.
- No more popups you didn't ask for: the browser extension only catches
  downloads you started with a click, and clipboard catching is off by default
  (it can be turned back on in Settings).
- Dark theme is the default. New app and extension icon; the video download
  button now shows it.
- A server that allows only a few connections no longer fails the download;
  VibeDownloader continues with fewer connections.
- Fixed: a paused multi-connection download could be marked complete while
  incomplete; small files could download twice; links the app cannot fetch now
  continue in the browser; the speed limit applies at once.
- Extension: respects "Catch all browser downloads" for link clicks, sends each
  grabbed link only its own site's cookies, finds the app on another port, and
  right-click download works on streaming (blob) videos.
- Videos with Bengali or other non-English titles keep a correct file path.
- Video progress no longer jumps backwards; playlist links show a clear
  message; a broken FFmpeg install is detected and reinstalled.
- Scheduler handles overnight windows (e.g. 23:00 to 06:00) and times like 9:00.
- Download File Info: the "…" button opens a real Save As dialog, the category
  folder box works, and a stuck file-info lookup no longer blocks the download.
- After updating, reload the extension once on the browser's extensions page.

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
- App updates: startup update check (at most once per 12 h) plus the
  existing "Check for App Update" button now actually downloads and runs the
  installer (it previously only showed a message).
- Fixed the update dialog: the Yes/No answer was created on a worker thread
  (silently dropped) and `_apply_app_update` was never called.
- GitHub Actions now publishes a real GitHub Release with `VibeDownloader_Installer.exe`
  on every `v*` tag — the in-app updater reads `/releases/latest`, so users only
  get updates once releases exist. `main.py` and `installer.nsi` versions match (2.4.0).
- yt-dlp bundled at 2026.10.26 (latest), FFmpeg bundled at 9.0.2 (latest).

## 2.2.0 (2026-11-01)
- Classic main window: large toolbar, category tree, dense sortable table with Date Added/Time left/Save To columns
- Native Windows menu bar (not a custom frame)
- Tray icon menu now includes Add URL, Start All, Stop All, and Exit
- Windows startup registration: app starts minimized to tray by default
- Settings Options: added "Start with Windows", "Hide window at startup", "Close to tray instead of exiting"
- Original programmatic toolbar icons
- Version bump to 2.2.0

## 2.1.0
- `build_windows.bat` can provision its own build-only Python and portable NSIS locally, without winget/choco/scoop or admin installation.
- Uses a separate Python build environment so existing Python 3.15 installations are left untouched.
- Runs Python syntax checks and the downloader unit tests before packaging.
- End-user installer is intended to bundle the app runtime, FFmpeg/FFprobe, yt-dlp, and browser-extension files.

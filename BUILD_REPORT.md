# Build verification — VibeDownloader 2.5.0

## Local verification

- Windows x64 build: Python 3.13.17, PyInstaller 6.22.3, NSIS.
- **48 offline regression tests passed**, including direct-download ranges,
  update metadata, trusted redirects, SHA-256, partial/corrupt downloads,
  cancellation, Windows shell/UAC error handling, and graceful update shutdown.
- Python syntax checks passed.
- GitHub Actions workflows passed `actionlint` validation.
- Source and frozen-app smoke checks passed: Tk/update window, icon, extension,
  FFmpeg 9.0.2, FFprobe 9.0.2, and yt-dlp 2026.10.26.
- NSIS installer compiled successfully with version 2.5.0.
- The pre-existing running workspace app was not stopped or overwritten.

## Release verification gate

The tagged **Build Windows installer** workflow builds a fresh installer and
must pass actual install, frozen-app/tool startup, in-place upgrade, data
retention, and uninstall checks on a disposable Windows runner before it
publishes a release.

Release: https://github.com/jhfarhanyt20-coder/BD-Downloader/releases/tag/v2.5.0

Installer checksums are per-build outputs. Use `SHA256SUMS.txt` attached to the
same GitHub Release as the installer, not a historical source-tree checksum.

## Signing and remaining manual checks

- No Authenticode certificate was provided; builds are unsigned and may show a
  Windows SmartScreen warning. SHA-256 is integrity verification, not signing.
- Interactive UAC acceptance/decline was not exercised manually; Windows API
  parameters, COM lifecycle, and error 1223 handling are covered by mocked tests.
- Live YouTube/media downloads and website-specific authentication were not
  tested as part of this installer/update task.

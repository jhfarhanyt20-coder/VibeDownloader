"""Public application metadata shared by the app and release builders.

Never put a GitHub token or another credential in this module. Update checks
only read public GitHub Releases.
"""

APP_NAME = "VibeDownloader"
APP_VERSION = "2.5.0"
APP_REPO = "jhfarhanyt20-coder/VibeDownloader"
INSTALLER_ASSET_NAME = "VibeDownloader_Installer.exe"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
APP_RELEASES_URL = f"https://github.com/{APP_REPO}/releases"
APP_UPDATE_URL = f"https://api.github.com/repos/{APP_REPO}/releases/latest"

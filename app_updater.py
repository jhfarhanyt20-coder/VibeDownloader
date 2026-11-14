"""Verified GitHub Release updates, with no GUI imports or embedded credentials."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from app_info import (
    APP_NAME, APP_REPO, APP_UPDATE_URL, APP_VERSION, CHECKSUM_ASSET_NAME,
    INSTALLER_ASSET_NAME,
)

USER_AGENT = f"{APP_NAME}/{APP_VERSION} (Windows updater)"
MIN_INSTALLER_SIZE = 1024 * 1024
MAX_INSTALLER_SIZE = 1024 * 1024 * 1024
MAX_CHECKSUM_SIZE = 64 * 1024
CHECK_INTERVAL = 12 * 3600
RETRY_INTERVAL = 3600
_VERSION_RE = re.compile(r"v?([0-9]{1,5})\.([0-9]{1,5})\.([0-9]{1,5})")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_DOWNLOAD_HOSTS = {
    "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
}


class UpdateError(RuntimeError):
    """An update could not be checked, verified, downloaded, or installed."""


class UpdateCancelled(UpdateError):
    """The user cancelled a download or the Windows permission prompt."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    download_url: str
    size: int
    sha256: str
    release_url: str
    notes: str = ""
    published_at: str = ""


def parse_version(text: str) -> tuple[int, int, int]:
    """Only stable three-component versions are eligible for app updates."""
    match = _VERSION_RE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise UpdateError("The release has an invalid stable version number.")
    return tuple(int(part) for part in match.groups())


def _validate_download_origin(url: str) -> None:
    try:
        parsed = urlparse(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in _DOWNLOAD_HOSTS
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise UpdateError("The update download did not come from a trusted GitHub HTTPS address.")


def _asset_url(asset: dict, tag: str, name: str) -> str:
    expected = f"https://github.com/{APP_REPO}/releases/download/{tag}/{name}"
    url = asset.get("browser_download_url")
    if url != expected:
        raise UpdateError("The release contains an unexpected installer or checksum address.")
    _validate_download_origin(url)
    return url


def _open_asset(url: str):
    """Follow only HTTPS GitHub/CDN redirects, validating before each request."""
    for _attempt in range(6):
        _validate_download_origin(url)
        response = requests.get(
            url, stream=True, allow_redirects=False, timeout=(15, 30),
            headers={
                "User-Agent": USER_AGENT, "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
            },
        )
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise UpdateError("GitHub returned an incomplete download redirect.")
            url = urljoin(url, location)
            continue
        try:
            response.raise_for_status()
        except Exception:
            response.close()
            raise
        return response
    raise UpdateError("GitHub returned too many download redirects. Try again later.")


def _read_checksum(url: str) -> str:
    content = bytearray()
    with _open_asset(url) as response:
        for chunk in response.iter_content(8192):
            content.extend(chunk)
            if len(content) > MAX_CHECKSUM_SIZE:
                raise UpdateError("The release checksum file is unexpectedly large.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UpdateError("The release checksum file is not readable.") from exc
    matches = []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?(.+)", line)
        if match and match.group(2) == INSTALLER_ASSET_NAME:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise UpdateError("The release must contain exactly one checksum for the Windows installer.")
    return matches[0]


def check_for_updates(current: str = APP_VERSION) -> UpdateInfo | None:
    """Return a verified newer stable release; distinguish errors from up to date."""
    installed_version = parse_version(current)
    try:
        with requests.get(
            APP_UPDATE_URL, allow_redirects=False, timeout=(10, 25),
            headers={
                "Accept": "application/vnd.github+json", "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as response:
            if response.status_code == 404:
                raise UpdateError("No public app release is available yet. Check the releases page.")
            if response.status_code in (403, 429):
                raise UpdateError("GitHub temporarily limited update checks. Try again later.")
            if response.status_code != 200:
                raise UpdateError(f"GitHub could not check for updates (HTTP {response.status_code}).")
            data = response.json()
        if not isinstance(data, dict):
            raise UpdateError("GitHub returned unreadable release information.")
        if data.get("draft") or data.get("prerelease"):
            return None
        tag = data.get("tag_name")
        latest_version = parse_version(tag)
        if latest_version <= installed_version:
            return None
        version = tag[1:] if tag.startswith("v") else tag
        assets = data.get("assets")
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise UpdateError("The release does not contain a Windows installer.")
        installers = [asset for asset in assets if asset.get("name") == INSTALLER_ASSET_NAME]
        if len(installers) != 1:
            raise UpdateError("The release does not contain the expected Windows installer.")
        installer = installers[0]
        url = _asset_url(installer, tag, INSTALLER_ASSET_NAME)
        size = installer.get("size")
        if type(size) is not int or not MIN_INSTALLER_SIZE <= size <= MAX_INSTALLER_SIZE:
            raise UpdateError("The release installer has an unexpected file size.")
        digest = installer.get("digest")
        api_checksum = None
        if digest is not None:
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                raise UpdateError("GitHub returned an invalid installer checksum.")
            api_checksum = digest.split(":", 1)[1].lower()
        manifests = [asset for asset in assets if asset.get("name") == CHECKSUM_ASSET_NAME]
        if len(manifests) > 1:
            raise UpdateError("The release contains ambiguous checksum files.")
        checksum = (
            _read_checksum(_asset_url(manifests[0], tag, CHECKSUM_ASSET_NAME))
            if manifests else api_checksum
        )
        if not checksum:
            raise UpdateError("This release has no verified installer checksum. Contact the publisher.")
        if api_checksum and not hmac.compare_digest(checksum, api_checksum):
            raise UpdateError("The release checksum does not match GitHub's installer checksum.")
        release_url = f"https://github.com/{APP_REPO}/releases/tag/{tag}"
        if data.get("html_url") != release_url:
            raise UpdateError("The release page has an unexpected address.")
        notes = data.get("body") or ""
        if not isinstance(notes, str):
            raise UpdateError("The release notes are unreadable.")
        return UpdateInfo(
            version, tag, url, size, checksum, release_url, notes[:16000],
            str(data.get("published_at") or "")[:64],
        )
    except requests.RequestException as exc:
        raise UpdateError("Could not connect to GitHub. Check your internet connection and try again.") from exc
    except (ValueError, TypeError) as exc:
        raise UpdateError("GitHub returned unreadable release information. Try again later.") from exc


def _validate_update(info: UpdateInfo) -> None:
    if parse_version(info.tag) != parse_version(info.version):
        raise UpdateError("The installer version does not match the release.")
    _asset_url({"browser_download_url": info.download_url}, info.tag, INSTALLER_ASSET_NAME)
    if type(info.size) is not int or not MIN_INSTALLER_SIZE <= info.size <= MAX_INSTALLER_SIZE:
        raise UpdateError("The installer has an unexpected file size.")
    if not isinstance(info.sha256, str) or not _SHA256_RE.fullmatch(info.sha256):
        raise UpdateError("The installer has no valid SHA-256 checksum.")


def _verify_installer_stream(handle, info: UpdateInfo) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() != info.size:
        raise UpdateError("The update download is incomplete or has an unexpected size.")
    handle.seek(0)
    header = handle.read(64)
    pe_offset = int.from_bytes(header[60:64], "little")
    if header[:2] != b"MZ" or not 64 <= pe_offset <= min(info.size - 4, 1024 * 1024):
        raise UpdateError("The update is not a Windows installer.")
    handle.seek(pe_offset)
    if handle.read(4) != b"PE\0\0":
        raise UpdateError("The update is not a valid Windows executable.")
    handle.seek(0)
    digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if not hmac.compare_digest(digest, info.sha256.lower()):
        raise UpdateError("Installer verification failed. The file was not installed; download it again.")


def verify_installer(path: str | Path, info: UpdateInfo) -> Path:
    """Check exact length, PE header, and SHA-256 again before execution."""
    _validate_update(info)
    path = Path(path)
    try:
        with path.open("rb") as handle:
            _verify_installer_stream(handle, info)
        return path
    except OSError as exc:
        raise UpdateError("The downloaded installer could not be read. Download it again.") from exc


@contextmanager
def _locked_verified_installer(path: str | Path, info: UpdateInfo):
    """Verify while holding a Windows read lock through elevated process creation."""
    _validate_update(info)
    path = Path(path).resolve()
    if os.name != "nt":
        yield verify_installer(path, info)
        return
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    raw_handle = kernel32.CreateFileW(
        str(path), 0x80000000, 0x00000001, None, 3, 0x00000080, None,
    )  # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
    if raw_handle == ctypes.c_void_p(-1).value:
        raise UpdateError("The downloaded installer could not be locked for verification.")
    try:
        descriptor = msvcrt.open_osfhandle(
            raw_handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as exc:
        kernel32.CloseHandle(raw_handle)
        raise UpdateError("The downloaded installer could not be locked for verification.") from exc
    try:
        with os.fdopen(descriptor, "rb") as handle:
            _verify_installer_stream(handle, info)
            # The lock denies write/delete sharing until ShellExecuteEx has
            # opened and mapped this exact verified executable.
            yield path
    except OSError as exc:
        raise UpdateError("The downloaded installer could not be read. Download it again.") from exc


def download_update(
    info: UpdateInfo, destination: str | Path, progress_cb=None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Download atomically; never execute or leave a successful-looking partial EXE."""
    _validate_update(info)
    destination = Path(destination)
    if destination.suffix.lower() != ".exe":
        raise UpdateError("The update must be saved as a Windows installer.")
    cancel_event = cancel_event or threading.Event()
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
    try:
        if cancel_event.is_set():
            raise UpdateCancelled("Update download cancelled.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            try:
                verified = verify_installer(destination, info)
            except UpdateError:
                pass
            else:
                if progress_cb:
                    progress_cb(info.size, info.size)
                return verified
        if shutil.disk_usage(destination.parent).free < info.size + 10 * 1024 * 1024:
            raise UpdateError("Not enough free disk space to download the update.")
        done = 0
        if progress_cb:
            progress_cb(done, info.size)
        with _open_asset(info.download_url) as response, temporary.open("xb") as handle:
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) != info.size):
                raise UpdateError("GitHub returned an unexpected installer size. Try again later.")
            for chunk in response.iter_content(256 * 1024):
                if cancel_event.is_set():
                    raise UpdateCancelled("Update download cancelled.")
                if not chunk:
                    continue
                done += len(chunk)
                if done > info.size:
                    raise UpdateError("The update download is larger than its release metadata.")
                handle.write(chunk)
                if progress_cb:
                    progress_cb(done, info.size)
        if cancel_event.is_set():
            raise UpdateCancelled("Update download cancelled.")
        verify_installer(temporary, info)
        os.replace(temporary, destination)
        return destination
    except requests.RequestException as exc:
        raise UpdateError("The update download failed. Check your connection and try again.") from exc
    except OSError as exc:
        raise UpdateError("The update could not be saved. Check free space and folder permissions.") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_state(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _timestamp(value) -> float:
    try:
        value = float(value or 0)
        return value if math.isfinite(value) and value >= 0 else 0
    except (ValueError, TypeError):
        return 0


def should_check_automatically(path: str | Path, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    data = _read_state(path)
    elapsed = now - _timestamp(data.get("checked_at"))
    attempted = now - _timestamp(data.get("attempted_at"))
    return not (0 <= elapsed < CHECK_INTERVAL or 0 <= attempted < RETRY_INTERVAL)


def record_check(path: str | Path, success: bool, now: float | None = None) -> None:
    """Preserve the last successful check; failed checks retry after an hour."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    data = _read_state(path)
    now = time.time() if now is None else now
    data["attempted_at"] = now
    if success:
        data["checked_at"] = now
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def installer_parameters(install_dir: str, parent_pid: int) -> str:
    """NSIS /D= must be LAST and must NOT be surrounded with quotes."""
    if (
        not os.path.isabs(install_dir) or any(char in install_dir for char in '"\r\n\0')
        or type(parent_pid) is not int or parent_pid <= 0
    ):
        raise UpdateError("The installed application path or process ID is invalid.")
    return f"/S /UPDATE /WAITPID={parent_pid} /D={install_dir}"


def _shell_execute_elevated(installer: Path, parameters: str) -> None:
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # keep process handle; finish the shell request synchronously
    info.lpVerb = "runas"
    info.lpFile = str(installer.resolve())
    info.lpParameters = parameters
    info.lpDirectory = str(installer.parent.resolve())
    info.nShow = 1
    # The updater runs on a worker thread; initialize COM before invoking the
    # Windows shell rather than relying on the GUI thread's COM apartment.
    result = ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    initialized = result in (0, 1)
    if not initialized and result != -2147417850:  # RPC_E_CHANGED_MODE
        raise UpdateError("Windows could not initialize the update installer.")
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:  # ERROR_CANCELLED: declining UAC must not close the app
                raise UpdateCancelled("Windows permission was cancelled. The app has not been changed.")
            raise UpdateError(f"Windows could not start the update installer (error {error}).")
        if info.hProcess:
            kernel32.CloseHandle(info.hProcess)
    finally:
        if initialized:
            ole32.CoUninitialize()


def launch_installer(
    installer: str | Path, info: UpdateInfo, install_dir: str, parent_pid: int,
) -> None:
    if os.name != "nt":
        raise UpdateError("Automatic installer updates are only available on Windows.")
    if Path(installer).suffix.lower() != ".exe":
        raise UpdateError("Only a verified Windows installer can be started.")
    parameters = installer_parameters(install_dir, parent_pid)
    with _locked_verified_installer(installer, info) as verified:
        _shell_execute_elevated(verified, parameters)

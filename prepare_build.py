"""Fetch all release-time assets so end users only download one installer.

Run on Windows x64:
    py prepare_build.py
    py prepare_build.py --offline   # use yt-dlp.exe and tools binaries already present
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from app_info import APP_VERSION
from release_tools import write_windows_version_info

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
YTDLP = ROOT / "yt-dlp.exe"
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
USER_AGENT = f"VibeDownloader-release-builder/{APP_VERSION}"


def download(url: str, target: Path, label: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temp = target.with_suffix(target.suffix + ".download")
    done = 0
    try:
        with urllib.request.urlopen(request, timeout=45) as response, temp.open("wb") as out:
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header and total_header.isdigit() else 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r{label}: {done / total * 100:5.1f}% ({done / 1048576:.1f} MiB)", end="", flush=True)
                else:
                    print(f"\r{label}: {done / 1048576:.1f} MiB", end="", flush=True)
        print()
        if done < 1024 * 1024:
            raise RuntimeError(f"Downloaded file is suspiciously small ({done} bytes): {url}")
        os.replace(temp, target)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def valid_windows_exe(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"MZ" and path.stat().st_size > 1024 * 1024
    except OSError:
        return False


def prepare_ytdlp(offline: bool) -> None:
    if offline:
        if not valid_windows_exe(YTDLP):
            raise RuntimeError("Offline build needs a valid Windows yt-dlp.exe in the project folder.")
        print(f"Using bundled yt-dlp.exe ({YTDLP.stat().st_size / 1048576:.1f} MiB).")
        return
    with tempfile.TemporaryDirectory(prefix="vibe-ytdlp-") as tmp:
        candidate = Path(tmp) / "yt-dlp.exe"
        print("Fetching the current yt-dlp Windows standalone build...")
        download(YTDLP_URL, candidate, "yt-dlp")
        if not valid_windows_exe(candidate):
            raise RuntimeError("Downloaded yt-dlp file did not pass the basic Windows EXE check.")
        shutil.copy2(candidate, YTDLP)
    print(f"Prepared yt-dlp.exe ({YTDLP.stat().st_size / 1048576:.1f} MiB).")


def prepare_ffmpeg(offline: bool) -> None:
    ffmpeg = TOOLS / "ffmpeg.exe"
    ffprobe = TOOLS / "ffprobe.exe"
    license_dir = TOOLS / "licenses"
    license_dir.mkdir(parents=True, exist_ok=True)
    if valid_windows_exe(ffmpeg) and valid_windows_exe(ffprobe):
        print("FFmpeg + FFprobe are already present; no FFmpeg download needed.")
        notice = license_dir / "FFmpeg-build-source.txt"
        if not notice.exists():
            notice.write_text(
                "FFmpeg binaries supplied to this build by the release builder.\n"
                f"Build download source used by the default builder: {FFMPEG_ZIP_URL}\n"
                "Verify the exact binary build, its license, notices, and corresponding-source obligations before redistribution.\n",
                encoding="utf-8",
            )
        return
    if offline:
        raise RuntimeError("Offline build needs tools\\ffmpeg.exe and tools\\ffprobe.exe.")

    TOOLS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vibe-ffmpeg-") as tmp:
        archive_path = Path(tmp) / "ffmpeg-essentials.zip"
        print("Fetching FFmpeg for the installer build (end users will not download it separately)...")
        download(FFMPEG_ZIP_URL, archive_path, "FFmpeg package")
        with zipfile.ZipFile(archive_path) as archive:
            matches: dict[str, str] = {}
            for member in archive.namelist():
                normalized = member.replace("\\", "/")
                if normalized.endswith("/bin/ffmpeg.exe"):
                    matches["ffmpeg.exe"] = member
                elif normalized.endswith("/bin/ffprobe.exe"):
                    matches["ffprobe.exe"] = member
            if set(matches) != {"ffmpeg.exe", "ffprobe.exe"}:
                raise RuntimeError("FFmpeg archive is missing ffmpeg.exe or ffprobe.exe.")
            for filename, member in matches.items():
                target = TOOLS / filename
                temp_target = target.with_suffix(".exe.download")
                with archive.open(member) as source, temp_target.open("wb") as out:
                    shutil.copyfileobj(source, out, length=1024 * 1024)
                os.replace(temp_target, target)

            # Keep any readme/license material supplied with the chosen archive.
            license_names = {
                "readme.txt", "license.txt", "license", "copying", "copying.txt",
                "copying.gplv2", "copying.gplv3", "copying.lgplv2.1", "copying.lgplv3",
            }
            for member in archive.namelist():
                basename = Path(member.replace("\\", "/")).name
                if basename.lower() in license_names and not member.endswith("/"):
                    destination = license_dir / basename
                    with archive.open(member) as source, destination.open("wb") as out:
                        shutil.copyfileobj(source, out, length=256 * 1024)

    (license_dir / "FFmpeg-build-source.txt").write_text(
        "Bundled FFmpeg source package URL: " + FFMPEG_ZIP_URL + "\n"
        "Inspect the archived FFmpeg README/license files in this folder. The Essentials build may include GPL-enabled components.\n"
        "The publisher must separately ensure that the exact binary's applicable license/source obligations are met before redistribution.\n",
        encoding="utf-8",
    )
    if not valid_windows_exe(ffmpeg) or not valid_windows_exe(ffprobe):
        raise RuntimeError("FFmpeg binaries failed validation after extraction.")
    print(f"Prepared FFmpeg ({ffmpeg.stat().st_size / 1048576:.1f} MiB) and FFprobe ({ffprobe.stat().st_size / 1048576:.1f} MiB).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Do not download release assets; validate existing files only.")
    args = parser.parse_args()

    if os.name != "nt":
        print("ERROR: release assets are Windows executables; run this script on Windows x64.", file=sys.stderr)
        return 2
    if sys.maxsize < 2**32:
        print("ERROR: use 64-bit Python on Windows to build the x64 installer.", file=sys.stderr)
        return 2

    try:
        write_windows_version_info()
        prepare_ytdlp(args.offline)
        prepare_ffmpeg(args.offline)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    required = [YTDLP, TOOLS / "ffmpeg.exe", TOOLS / "ffprobe.exe", ROOT / "VibeDownloader.ico", ROOT / "extension" / "manifest.json", TOOLS / "licenses" / "FFmpeg-build-source.txt"]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        print("ERROR: missing release assets: " + ", ".join(missing), file=sys.stderr)
        return 1

    print("\nRelease assets are ready. The installer build will bundle FFmpeg, FFprobe, yt-dlp, Python, UI dependencies and the browser extension.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

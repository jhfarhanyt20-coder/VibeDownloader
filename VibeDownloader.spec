# -*- mode: python ; coding: utf-8 -*-
"""Windows one-file bundle. Run prepare_build.py before PyInstaller."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)
required_files = [
    ROOT / "VibeDownloader.ico",
    ROOT / "tools" / "ffmpeg.exe",
    ROOT / "tools" / "ffprobe.exe",
    ROOT / "tools" / "licenses" / "FFmpeg-build-source.txt",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "extension" / "manifest.json",
]
missing = [str(path.relative_to(ROOT)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(
        "Missing release assets: " + ", ".join(missing) +
        ". Run: py prepare_build.py"
    )

datas = [
    (str(ROOT / "extension"), "extension"),
    (str(ROOT / "VibeDownloader.ico"), "."),
    (str(ROOT / "tools" / "ffmpeg.exe"), "tools"),
    (str(ROOT / "tools" / "ffprobe.exe"), "tools"),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    (str(ROOT / "tools" / "licenses"), "licenses"),
]
datas += collect_data_files("customtkinter")
hiddenimports = [
    "downloader", "yt_helper", "pystray", "pystray._win32",
    "PIL", "PIL.Image", "requests", "certifi",
    "windows_startup", "classic_icons",
]
hiddenimports += collect_submodules("pystray")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VibeDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "VibeDownloader.ico"),
)

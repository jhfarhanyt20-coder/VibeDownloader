"""Offline frozen-app smoke test, used only by the Windows release workflow."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from app_info import APP_NAME, APP_VERSION
from app_updater import UpdateInfo
from update_dialog import AppUpdateDialog
import yt_helper


def run_self_test(report_path: str) -> int:
    report = {
        "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
        "architecture_bits": struct.calcsize("P") * 8, "checks": {},
    }
    root = None
    try:
        root = ctk.CTk()
        root.withdraw()
        root.post = lambda callback: callback()
        palette = {
            "bg": "#F3F3F3", "panel": "#FFFFFF", "border": "#C8C8C8",
            "text": "#161616", "muted": "#5B5B5B", "accent": "#1769AA",
            "accent_hover": "#0E5C98", "error": "#C43B32", "success": "#2E8B57",
        }
        window = AppUpdateDialog(
            root, palette=palette, data_dir=yt_helper.app_data_dir(),
            on_check=lambda: None, on_install=lambda *_args: None, on_close=lambda _window: None,
        )
        window.withdraw()
        window.show_current()
        window.show_error("Offline test")
        window.show_available(UpdateInfo(
            APP_VERSION, f"v{APP_VERSION}", "", 123456789, "",
            "", "Offline update-window smoke test.",
        ))
        root.update_idletasks()
        window.close()
        report["checks"]["tk_and_update_window"] = True
        resources = Path(yt_helper.resource_dir())
        with Image.open(resources / f"{APP_NAME}.ico") as icon:
            icon.load()
        report["checks"]["icon"] = True
        extension = Path(yt_helper.installed_dir()) / "extension" / "manifest.json"
        if not extension.exists():
            extension = resources / "extension" / "manifest.json"
        if not extension.is_file():
            raise RuntimeError("The browser extension was not bundled.")
        report["checks"]["extension"] = True
        for name, path in (
            ("ffmpeg", yt_helper.find_ffmpeg()), ("ffprobe", yt_helper.find_ffprobe()),
            ("yt-dlp", yt_helper.find_ytdlp()),
        ):
            if not path:
                raise RuntimeError(f"The installer is missing {name}.")
            option = "--version" if name == "yt-dlp" else "-version"
            process = subprocess.run(
                [path, option], capture_output=True, text=True, timeout=30,
                env=yt_helper.child_env(), creationflags=yt_helper.CREATE_NO_WINDOW,
            )
            if process.returncode != 0:
                raise RuntimeError(f"The bundled {name} could not start.")
            report["checks"][name] = (process.stdout or process.stderr).splitlines()[0]
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    finally:
        if root is not None:
            root.destroy()
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1

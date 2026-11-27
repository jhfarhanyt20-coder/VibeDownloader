"""Small software update window in VibeDownloader's own window frame."""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import customtkinter as ctk

import app_updater
import window_frame
from app_info import APP_DISPLAY_NAME, APP_NAME, APP_RELEASES_URL, APP_VERSION


class AppUpdateDialog(ctk.CTkToplevel):
    def __init__(self, master, *, palette, data_dir, on_check, on_install, on_close):
        super().__init__(master)
        self.app = master
        self.palette = palette
        self.data_dir = Path(data_dir)
        self.on_check = on_check
        self.on_install = on_install
        self.on_close = on_close
        self.info = None
        self.installer_path = None
        self.busy = False
        self.state_name = "checking"
        self._closed = False
        self._cancel = threading.Event()
        self.title(f"{APP_DISPLAY_NAME} updates")
        self.geometry("580x490")
        self.resizable(False, False)
        self.configure(fg_color=palette["bg"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        window_frame.apply(self, minimize=False, maximize=False)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(20, 12))
        self.headline = ctk.CTkLabel(
            body, text="Checking for updates", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=19, weight="bold"),
            text_color=palette["text"],
        )
        self.headline.pack(fill="x")
        self.version_label = ctk.CTkLabel(
            body, text=f"Installed version: {APP_VERSION}", anchor="w", justify="left",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color=palette["muted"],
        )
        self.version_label.pack(fill="x", pady=(4, 12))
        self.notes = ctk.CTkTextbox(
            body, height=180, wrap="word", corner_radius=3, border_width=1,
            border_color=palette["border"], fg_color=palette["panel"],
            text_color=palette["text"], font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.notes.pack(fill="both", expand=True)
        self.progress = ctk.CTkProgressBar(
            body, height=8, corner_radius=2, progress_color=palette["accent"],
            fg_color=palette["border"],
        )
        self.progress.pack(fill="x", pady=(16, 6))
        self.status = ctk.CTkLabel(
            body, text="", anchor="w", justify="left", wraplength=532, height=54,
            text_color=palette["muted"], font=ctk.CTkFont(family="Segoe UI", size=11),
        )
        self.status.pack(fill="x")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(
            footer, text="Releases page", width=112, height=32,
            fg_color="transparent", hover_color=palette["panel"],
            text_color=palette["accent"], command=lambda: webbrowser.open(APP_RELEASES_URL),
        ).pack(side="left")
        self.primary = ctk.CTkButton(
            footer, text="Check again", width=155, height=34, state="disabled",
            fg_color=palette["accent"], hover_color=palette["accent_hover"],
            text_color=palette.get("accent_text", "#FFFFFF"), command=self._primary_action,
        )
        self.primary.pack(side="right")
        self.secondary = ctk.CTkButton(
            footer, text="Close", width=100, height=34,
            fg_color=palette["panel"], hover_color=palette["border"],
            text_color=palette["text"], command=self.close,
        )
        self.secondary.pack(side="right", padx=(0, 8))
        self.show_checking()
        self.after(100, self.lift)

    @property
    def alive(self):
        try:
            return not self._closed and bool(self.winfo_exists())
        except Exception:
            return False

    def _set_notes(self, text):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")

    def _stop_progress(self):
        self.progress.stop()
        self.progress.configure(mode="determinate")

    def show_checking(self):
        self.state_name = "checking"
        self.info = None
        self.installer_path = None
        self.headline.configure(text="Checking for updates")
        self.version_label.configure(text=f"Installed version: {APP_VERSION}")
        self._set_notes("Looking for the latest stable Windows release on GitHub.")
        self.status.configure(text="No update is installed without your approval.",
                              text_color=self.palette["muted"])
        self.primary.configure(state="disabled", text="Checking...")
        self.secondary.configure(state="normal", text="Close")
        self.progress.configure(mode="indeterminate")
        self.progress.start()

    def show_current(self):
        if not self.alive:
            return
        self.info = None
        self.installer_path = None
        self.state_name = "current"
        self._stop_progress()
        self.progress.set(1)
        self.headline.configure(text="You're up to date")
        self._set_notes(f"{APP_DISPLAY_NAME} {APP_VERSION} is the newest version available to this app.")
        self.status.configure(text="Automatic checks use stable releases only.",
                              text_color=self.palette["success"])
        self.primary.configure(state="normal", text="Check again")

    def show_error(self, message):
        if not self.alive:
            return
        self.info = None
        self.installer_path = None
        self.state_name = "error"
        self._stop_progress()
        self.progress.set(0)
        self.headline.configure(text="Update check couldn't finish")
        self._set_notes(message + "\n\nYou can retry or open the releases page.")
        self.status.configure(text="Your installed app has not been changed.",
                              text_color=self.palette["error"])
        self.primary.configure(state="normal", text="Try again")

    def show_available(self, info):
        if not self.alive:
            return
        self.info = info
        self.state_name = "available"
        self._stop_progress()
        self.progress.set(0)
        self.headline.configure(text=f"Version {info.version} is available")
        self.version_label.configure(
            text=f"Installed version: {APP_VERSION}\nUpdate size: {info.size / 1048576:.1f} MB")
        self._set_notes(info.notes or "A new stable Windows installer is available.")
        text = ("Your files, settings, and history are kept. After you approve Windows "
                "permission, downloads pause and the app restarts.")
        if not getattr(sys, "frozen", False):
            text = "Running from source: download the installer, then run it to install the desktop app."
        self.status.configure(text=text, text_color=self.palette["muted"])
        self.primary.configure(
            state="normal", text="Update now" if getattr(sys, "frozen", False) else "Download installer")
        self.secondary.configure(state="normal", text="Later")

    def _primary_action(self):
        if self.busy:
            return
        if self.state_name == "ready":
            if getattr(sys, "frozen", False):
                self.on_install(self.info, self.installer_path)
            elif os.name == "nt":
                os.startfile(str(self.installer_path.parent))
            else:
                webbrowser.open(self.installer_path.parent.as_uri())
        elif self.info is not None:
            self._start_download()
        else:
            self.on_check()

    def _start_download(self):
        info = self.info
        self.busy = True
        self.state_name = "downloading"
        self._cancel.clear()
        self.headline.configure(text=f"Downloading version {info.version}")
        self.status.configure(text="Downloading the installer. It will be verified before it is run.",
                              text_color=self.palette["muted"])
        self.primary.configure(state="disabled", text="Downloading...")
        self.secondary.configure(text="Cancel download")
        destination = self.data_dir / "updates" / f"{APP_NAME}-{info.version}-Installer.exe"

        def worker():
            last_progress = 0.0

            def progress(done, total):
                nonlocal last_progress
                now = time.monotonic()
                if done in (0, total) or now - last_progress >= 0.1:
                    last_progress = now
                    self.app.post(lambda d=done, t=total: self._show_progress(d, t))

            try:
                path = app_updater.download_update(info, destination, progress, self._cancel)
            except app_updater.UpdateError as exc:
                self.app.post(lambda message=str(exc): self._download_failed(message))
            else:
                self.app.post(lambda: self._download_finished(path))

        threading.Thread(target=worker, daemon=True).start()

    def _show_progress(self, done, total):
        if not self.alive:
            return
        self.progress.set(done / total)
        self.status.configure(
            text=f"Downloading update: {done / 1048576:.1f} of {total / 1048576:.1f} MB "
                 f"({done * 100 // total}%)")

    def _download_failed(self, message):
        if not self.alive:
            return
        self.busy = False
        self.state_name = "available"
        self.headline.configure(text="Update was not installed")
        self.status.configure(text=message, text_color=self.palette["error"])
        self.primary.configure(state="normal", text="Retry download")
        self.secondary.configure(text="Close")

    def _download_finished(self, path):
        if not self.alive:
            return
        self.installer_path = path
        self.busy = False
        self.state_name = "ready"
        self.progress.set(1)
        self.headline.configure(text="Installer verified")
        self.primary.configure(
            state="normal",
            text="Install and restart" if getattr(sys, "frozen", False) else "Open installer folder")
        self.secondary.configure(text="Close")
        self.status.configure(text=f"SHA-256 verified. Installer saved to:\n{path}",
                              text_color=self.palette["success"])
        if getattr(sys, "frozen", False):
            self.on_install(self.info, path)

    def show_installing(self):
        self.busy = True
        self.state_name = "installing"
        self.headline.configure(text="Waiting for Windows permission")
        self.status.configure(text="Approve the installer in the Windows permission prompt to continue.",
                              text_color=self.palette["muted"])
        self.primary.configure(state="disabled", text="Installing...")
        self.secondary.configure(state="disabled")

    def show_install_error(self, message):
        if not self.alive:
            return
        self.busy = False
        self.state_name = "ready"
        self.headline.configure(text="Update was not installed")
        self.status.configure(text=message, text_color=self.palette["error"])
        self.primary.configure(state="normal", text="Install and restart")
        self.secondary.configure(state="normal", text="Close")

    def close(self):
        if self.state_name == "installing" or self._closed:
            return
        self._cancel.set()
        self._closed = True
        self.progress.stop()
        self.destroy()
        self.on_close(self)

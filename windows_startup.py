"""Windows startup registration helpers for VibeDownloader.

The per-user Run key does not require administrator rights and is easy to
disable from either VibeDownloader or Windows Task Manager's Startup Apps UI.
"""

from __future__ import annotations

import os
import sys


APP_RUN_NAME = "VibeDownloader"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command(executable=None, script_path=None):
    """Return the command Windows should execute at sign-in."""
    executable = os.path.abspath(executable or sys.executable)
    if getattr(sys, "frozen", False) or executable.lower().endswith(".exe") and os.path.basename(
            executable).lower() == "vibedownloader.exe":
        return f'"{executable}" --startup'

    script_path = os.path.abspath(
        script_path or os.path.join(os.path.dirname(__file__), "main.py"))
    python_dir = os.path.dirname(executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    launcher = pythonw if os.path.isfile(pythonw) else executable
    return f'"{launcher}" "{script_path}" --startup'


def get_startup_command():
    """Read the current per-user startup command, or return an empty string."""
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, APP_RUN_NAME)
        return str(value or "")
    except (OSError, ImportError):
        return ""


def is_startup_enabled():
    return bool(get_startup_command())


def set_startup_enabled(enabled, executable=None, script_path=None):
    """Enable/disable sign-in startup. Returns ``(success, message)``."""
    if os.name != "nt":
        return False, "Windows startup is only available on Windows."
    try:
        import winreg

        if enabled:
            command = startup_command(executable, script_path)
            with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, command)
            return True, "VibeDownloader will start with Windows."

        try:
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_RUN_NAME)
        except FileNotFoundError:
            pass
        return True, "Windows startup disabled."
    except (OSError, ImportError) as exc:
        return False, f"Could not update Windows startup: {exc}"

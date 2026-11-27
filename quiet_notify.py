"""Quiet notes, the same in every VibeCoder app.

The Windows tray note is shown without the system sound (NIIF_NOSOUND), the app
plays its own soft two-note chime instead, and the note leaves by itself after
a few seconds so it never sits over the user's work.
"""
import math
import os
import struct
import tempfile
import threading

NIM_MODIFY = 1
NIF_INFO = 0x10
NIIF_INFO = 0x1
NIIF_NOSOUND = 0x10

_chime_path = None


def chime_wav_bytes(rate=22050):
    """Two soft sine notes (E5 then B5) with a gentle fade, as a 16-bit WAV."""
    total = int(rate * 0.75)
    samples = [0.0] * total
    for freq, at, length in ((659.25, 0.0, 0.42), (987.77, 0.11, 0.55)):
        start = int(at * rate)
        for i in range(int(length * rate)):
            if start + i >= total:
                break
            t = i / rate
            samples[start + i] += math.sin(2 * math.pi * freq * t) * 0.22 * min(1.0, t / 0.018) * math.exp(-t * 7.5)
    data = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in samples)
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
              struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(data)))
    return header + data


def play_chime():
    """Play the chime without blocking (Windows only; silently does nothing elsewhere)."""
    global _chime_path
    if os.name != "nt":
        return False
    try:
        import winsound
        if not _chime_path or not os.path.exists(_chime_path):
            path = os.path.join(tempfile.gettempdir(), "vibedownloader-chime.wav")
            with open(path, "wb") as handle:
                handle.write(chime_wav_bytes())
            _chime_path = path
        winsound.PlaySound(_chime_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception:  # noqa: BLE001
        return False


def quiet_notify(icon, message, title, hide_after=4.0):
    """Show a tray note without the Windows sound, then take it away again."""
    if icon is None:
        return False
    shown = False
    try:
        send = getattr(icon, "_message", None)
        if callable(send):  # pystray's Windows backend: same call as notify(), plus NIIF_NOSOUND
            send(NIM_MODIFY, NIF_INFO, szInfo=str(message)[:255], szInfoTitle=str(title)[:63],
                 dwInfoFlags=NIIF_INFO | NIIF_NOSOUND)
            shown = True
    except Exception:  # noqa: BLE001
        shown = False
    if not shown:
        try:
            icon.notify(message, title)
            shown = True
        except Exception:  # noqa: BLE001
            return False

    def _hide():
        try:
            icon.remove_notification()
        except Exception:  # noqa: BLE001
            pass

    timer = threading.Timer(hide_after, _hide)
    timer.daemon = True
    timer.start()
    return True

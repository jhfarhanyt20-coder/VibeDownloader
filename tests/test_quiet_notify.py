import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import quiet_notify  # noqa: E402


class FakeIcon:
    def __init__(self):
        self.sent = []
        self.notified = []
        self.removed = 0

    def _message(self, code, flags, **kwargs):
        self.sent.append((code, flags, kwargs))

    def notify(self, message, title):
        self.notified.append((message, title))

    def remove_notification(self):
        self.removed += 1


class QuietNotifyTest(unittest.TestCase):
    def test_chime_is_a_short_soft_wav(self):
        data = quiet_notify.chime_wav_bytes()
        self.assertTrue(data.startswith(b"RIFF") and data[8:12] == b"WAVE")
        self.assertLess(len(data), 40000)

    def test_note_is_silent_and_leaves_by_itself(self):
        icon = FakeIcon()
        self.assertTrue(quiet_notify.quiet_notify(icon, "Download complete: a.zip", "VibeDownloader", hide_after=0.05))
        code, flags, kwargs = icon.sent[0]
        self.assertEqual(code, quiet_notify.NIM_MODIFY)
        self.assertEqual(flags, quiet_notify.NIF_INFO)
        self.assertTrue(kwargs["dwInfoFlags"] & quiet_notify.NIIF_NOSOUND, "no Windows sound")
        self.assertEqual(icon.notified, [], "the noisy notify() is not used")
        import time
        time.sleep(0.2)
        self.assertEqual(icon.removed, 1, "the note is taken away again")

    def test_no_icon_is_fine(self):
        self.assertFalse(quiet_notify.quiet_notify(None, "x", "y"))


if __name__ == "__main__":
    unittest.main()

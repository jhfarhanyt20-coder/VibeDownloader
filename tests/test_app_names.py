"""Save paths: Windows-safe names, and no two downloads share one file."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import DownloadTask, sanitize_filename, unique_path  # noqa: E402


class SanitizeTests(unittest.TestCase):
    def test_long_names_keep_their_extension(self):
        name = sanitize_filename("a" * 300 + ".pdf")
        self.assertTrue(name.endswith(".pdf"))
        self.assertLessEqual(len(name), 180)

    def test_reserved_windows_names(self):
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("nul.zip"), "_nul.zip")
        self.assertEqual(sanitize_filename("console.zip"), "console.zip")

    def test_no_trailing_dot_or_space(self):
        self.assertEqual(sanitize_filename("report . "), "report")


class UniquePathTests(unittest.TestCase):
    def test_paths_of_other_tasks_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "file.pdf")
            self.assertEqual(unique_path(path), path)
            self.assertEqual(unique_path(path, [path]), os.path.join(folder, "file (1).pdf"))


class SavedTaskTests(unittest.TestCase):
    def test_old_paused_video_keeps_its_old_naming(self):
        task = DownloadTask.from_dict({"url": "https://x.com/a.m3u8", "kind": "media",
                                       "downloaded": 5000, "status": "paused"})
        self.assertTrue(task.legacy_naming)
        fresh = DownloadTask.from_dict(dict(task.to_dict()))
        self.assertFalse(fresh.legacy_naming)


if __name__ == "__main__":
    unittest.main()

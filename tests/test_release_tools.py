import hashlib
import tempfile
import unittest
from pathlib import Path

from app_info import APP_VERSION, INSTALLER_ASSET_NAME
import release_tools


class ReleaseMetadataTests(unittest.TestCase):
    def test_tag_must_match_the_app_version(self):
        release_tools.validate_version(f"v{APP_VERSION}")
        for tag in ("v0.0.0", APP_VERSION, f"v{APP_VERSION}-beta"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_tools.validate_version(tag)

    def test_windows_file_version_is_generated_from_app_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = release_tools.write_windows_version_info(Path(folder) / "version_info.txt")
            text = path.read_text(encoding="utf-8")
        self.assertIn(f"StringStruct('FileVersion', '{APP_VERSION}')", text)
        self.assertIn(str(tuple(map(int, APP_VERSION.split("."))) + (0,)), text)

    def test_release_manifest_has_the_exact_installer_name_and_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            installer = root / INSTALLER_ASSET_NAME
            payload = b"MZ" + b"x" * 1024 * 1024
            installer.write_bytes(payload)
            checksums = root / "SHA256SUMS.txt"
            notes = root / "RELEASE_NOTES.md"
            digest = release_tools.write_release_files(installer, checksums, notes)
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(checksums.read_text(), f"{digest}  {INSTALLER_ASSET_NAME}\n")
            self.assertIn(f"VibeDownloader {APP_VERSION}", notes.read_text())

    def test_invalid_or_wrong_named_installer_cannot_be_released(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wrong_name = root / "Other.exe"
            wrong_name.write_bytes(b"MZ" + b"x" * 1024 * 1024)
            with self.assertRaises(ValueError):
                release_tools.write_release_files(wrong_name, root / "sha.txt", root / "notes.md")
            invalid = root / INSTALLER_ASSET_NAME
            invalid.write_bytes(b"<html>not an installer</html>")
            with self.assertRaises(ValueError):
                release_tools.write_release_files(invalid, root / "sha.txt", root / "notes.md")


if __name__ == "__main__":
    unittest.main()

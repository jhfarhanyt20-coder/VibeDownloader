import hashlib
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import app_updater as updater
from app_info import APP_REPO, CHECKSUM_ASSET_NAME, INSTALLER_ASSET_NAME


def windows_payload():
    payload = bytearray(updater.MIN_INSTALLER_SIZE + 128)
    payload[:2] = b"MZ"
    payload[60:64] = (128).to_bytes(4, "little")
    payload[128:132] = b"PE\0\0"
    payload[-32:] = b"vibe verified update test payload"
    return bytes(payload)


PAYLOAD = windows_payload()
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
TAG = "v2.6.0"
DOWNLOAD_URL = f"https://github.com/{APP_REPO}/releases/download/{TAG}/{INSTALLER_ASSET_NAME}"
CHECKSUM_URL = f"https://github.com/{APP_REPO}/releases/download/{TAG}/{CHECKSUM_ASSET_NAME}"
INFO = updater.UpdateInfo(
    "2.6.0", TAG, DOWNLOAD_URL, len(PAYLOAD), DIGEST,
    f"https://github.com/{APP_REPO}/releases/tag/{TAG}", "A verified update.",
)


class Response:
    def __init__(self, *, data=None, body=b"", status=200, headers=None):
        self.data = data
        self.body = body
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.closed = True

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]


def release_data():
    return {
        "tag_name": TAG, "draft": False, "prerelease": False,
        "html_url": INFO.release_url, "body": INFO.notes,
        "assets": [
            {"name": INSTALLER_ASSET_NAME, "browser_download_url": DOWNLOAD_URL,
             "size": len(PAYLOAD), "digest": f"sha256:{DIGEST}"},
            {"name": CHECKSUM_ASSET_NAME, "browser_download_url": CHECKSUM_URL, "size": 94},
        ],
    }


def checksum_response(digest=DIGEST):
    return Response(body=f"{digest}  {INSTALLER_ASSET_NAME}\n".encode())


class ReleaseCheckTests(unittest.TestCase):
    def test_only_stable_versions_are_accepted(self):
        self.assertEqual(updater.parse_version("v2.10.0"), (2, 10, 0))
        self.assertGreater(updater.parse_version("2.10.0"), updater.parse_version("2.9.0"))
        for value in ("release-2.6.0", "2.6.0-beta.1", "2.6", "../../2.6.0", "2.6.0\n", None):
            with self.subTest(value=value), self.assertRaises(updater.UpdateError):
                updater.parse_version(value)

    def test_new_release_uses_exact_installer_and_checksum(self):
        with patch("app_updater.requests.get", side_effect=[
            Response(data=release_data()), checksum_response(),
        ]) as get:
            self.assertEqual(updater.check_for_updates("2.5.0"), INFO)
        for call in get.call_args_list:
            self.assertNotIn("Authorization", call.kwargs["headers"])
            self.assertFalse(call.kwargs["allow_redirects"])

    def test_same_or_older_release_is_up_to_date_without_asset_downloads(self):
        for current in ("2.6.0", "2.7.0"):
            with self.subTest(current=current), patch(
                    "app_updater.requests.get", return_value=Response(data=release_data())) as get:
                self.assertIsNone(updater.check_for_updates(current))
                get.assert_called_once()

    def test_drafts_and_prereleases_are_not_offered(self):
        for flag in ("draft", "prerelease"):
            data = release_data()
            data[flag] = True
            with self.subTest(flag=flag), patch(
                    "app_updater.requests.get", return_value=Response(data=data)):
                self.assertIsNone(updater.check_for_updates("2.5.0"))

    def test_offline_and_http_errors_are_not_reported_as_up_to_date(self):
        for status in (404, 403, 429, 500):
            with self.subTest(status=status), patch(
                    "app_updater.requests.get", return_value=Response(status=status)):
                with self.assertRaises(updater.UpdateError):
                    updater.check_for_updates("2.5.0")
        with patch("app_updater.requests.get", side_effect=requests.Timeout):
            with self.assertRaisesRegex(updater.UpdateError, "internet"):
                updater.check_for_updates("2.5.0")

    def test_no_fallback_to_an_arbitrary_exe_or_html_page(self):
        data = release_data()
        data["assets"][0]["name"] = "Other.exe"
        with patch("app_updater.requests.get", return_value=Response(data=data)):
            with self.assertRaisesRegex(updater.UpdateError, "expected Windows installer"):
                updater.check_for_updates("2.5.0")

    def test_rejects_wrong_repository_or_non_https_asset_url(self):
        for url in (
            DOWNLOAD_URL.replace(APP_REPO, "someone/another-app"),
            DOWNLOAD_URL.replace("https:", "http:"),
            DOWNLOAD_URL.replace("github.com", "github.com.evil.example"),
        ):
            data = release_data()
            data["assets"][0]["browser_download_url"] = url
            with self.subTest(url=url), patch(
                    "app_updater.requests.get", return_value=Response(data=data)):
                with self.assertRaises(updater.UpdateError):
                    updater.check_for_updates("2.5.0")

    def test_rejects_missing_or_mismatched_checksums(self):
        data = release_data()
        data["assets"] = data["assets"][:1]
        data["assets"][0]["digest"] = None
        with patch("app_updater.requests.get", return_value=Response(data=data)):
            with self.assertRaisesRegex(updater.UpdateError, "no verified installer checksum"):
                updater.check_for_updates("2.5.0")
        with patch("app_updater.requests.get", side_effect=[
            Response(data=release_data()), checksum_response("0" * 64),
        ]):
            with self.assertRaisesRegex(updater.UpdateError, "does not match"):
                updater.check_for_updates("2.5.0")

    def test_github_asset_digest_is_a_valid_checksum_fallback(self):
        data = release_data()
        data["assets"] = data["assets"][:1]
        with patch("app_updater.requests.get", return_value=Response(data=data)):
            self.assertEqual(updater.check_for_updates("2.5.0").sha256, DIGEST)

    def test_manifest_alone_works_for_github_without_asset_digest(self):
        data = release_data()
        data["assets"][0]["digest"] = None
        with patch("app_updater.requests.get", side_effect=[
            Response(data=data), checksum_response(),
        ]):
            self.assertEqual(updater.check_for_updates("2.5.0").sha256, DIGEST)

    def test_duplicate_or_oversized_checksum_files_are_rejected(self):
        bodies = (
            (f"{DIGEST}  {INSTALLER_ASSET_NAME}\n" * 2).encode(),
            b"x" * (updater.MAX_CHECKSUM_SIZE + 1),
        )
        for body in bodies:
            with self.subTest(length=len(body)), patch("app_updater.requests.get", side_effect=[
                Response(data=release_data()), Response(body=body),
            ]):
                with self.assertRaises(updater.UpdateError):
                    updater.check_for_updates("2.5.0")

    def test_invalid_size_and_release_page_are_rejected(self):
        for size in (0, True, "123", updater.MAX_INSTALLER_SIZE + 1):
            data = release_data()
            data["assets"][0]["size"] = size
            with self.subTest(size=size), patch(
                    "app_updater.requests.get", return_value=Response(data=data)):
                with self.assertRaises(updater.UpdateError):
                    updater.check_for_updates("2.5.0")
        data = release_data()
        data["html_url"] = "https://example.com/release"
        with patch("app_updater.requests.get", side_effect=[
            Response(data=data), checksum_response(),
        ]):
            with self.assertRaisesRegex(updater.UpdateError, "release page"):
                updater.check_for_updates("2.5.0")


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="vibe-update-test-")
        self.addCleanup(self.folder.cleanup)
        self.destination = Path(self.folder.name) / INSTALLER_ASSET_NAME

    def assert_no_partial_files(self):
        self.assertEqual(list(self.destination.parent.glob("*.part")), [])

    def test_download_is_verified_and_atomically_saved(self):
        progress = []
        response = Response(body=PAYLOAD, headers={"Content-Length": str(len(PAYLOAD))})
        with patch("app_updater.requests.get", return_value=response):
            path = updater.download_update(INFO, self.destination, lambda d, t: progress.append((d, t)))
        self.assertEqual(path, self.destination)
        self.assertEqual(path.read_bytes(), PAYLOAD)
        self.assertEqual(progress[-1], (len(PAYLOAD), len(PAYLOAD)))
        self.assertTrue(response.closed)
        self.assert_no_partial_files()

    def test_verified_cached_installer_does_not_download_again(self):
        self.destination.write_bytes(PAYLOAD)
        with patch("app_updater.requests.get") as get:
            self.assertEqual(updater.download_update(INFO, self.destination), self.destination)
        get.assert_not_called()

    def test_failure_preserves_existing_file_and_removes_partial_download(self):
        self.destination.write_bytes(b"previous cached file")
        with patch("app_updater.requests.get", return_value=Response(body=PAYLOAD[:-32])):
            with self.assertRaises(updater.UpdateError):
                updater.download_update(INFO, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"previous cached file")
        self.assert_no_partial_files()

    def test_wrong_hash_is_never_saved_as_installer(self):
        damaged = bytearray(PAYLOAD)
        damaged[-1] ^= 1
        with patch("app_updater.requests.get", return_value=Response(body=bytes(damaged))):
            with self.assertRaisesRegex(updater.UpdateError, "verification failed"):
                updater.download_update(INFO, self.destination)
        self.assertFalse(self.destination.exists())
        self.assert_no_partial_files()

    def test_non_pe_file_with_correct_hash_is_still_rejected(self):
        html = b"x" * len(PAYLOAD)
        info = replace(INFO, sha256=hashlib.sha256(html).hexdigest())
        with patch("app_updater.requests.get", return_value=Response(body=html)):
            with self.assertRaisesRegex(updater.UpdateError, "Windows installer"):
                updater.download_update(info, self.destination)
        self.assert_no_partial_files()

    def test_oversized_and_incorrect_content_length_are_rejected(self):
        for response in (
            Response(body=PAYLOAD + b"unexpected"),
            Response(body=PAYLOAD, headers={"Content-Length": "999"}),
        ):
            with self.subTest(headers=response.headers), patch(
                    "app_updater.requests.get", return_value=response):
                with self.assertRaises(updater.UpdateError):
                    updater.download_update(INFO, self.destination)
            self.assert_no_partial_files()

    def test_network_failure_leaves_no_partial_installer(self):
        with patch("app_updater.requests.get", side_effect=requests.Timeout):
            with self.assertRaisesRegex(updater.UpdateError, "connection"):
                updater.download_update(INFO, self.destination)
        self.assert_no_partial_files()

    def test_cancel_before_or_during_download_removes_partial_file(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("app_updater.requests.get") as get:
            with self.assertRaises(updater.UpdateCancelled):
                updater.download_update(INFO, self.destination, cancel_event=cancelled)
        get.assert_not_called()
        cancelled.clear()
        with patch("app_updater.requests.get", return_value=Response(body=PAYLOAD)):
            with self.assertRaises(updater.UpdateCancelled):
                updater.download_update(
                    INFO, self.destination,
                    lambda done, _total: cancelled.set() if done else None, cancelled)
        self.assertFalse(self.destination.exists())
        self.assert_no_partial_files()

    def test_redirect_to_github_cdn_is_allowed(self):
        redirect = Response(status=302, headers={
            "Location": "https://release-assets.githubusercontent.com/github-production-release-asset/test",
        })
        with patch("app_updater.requests.get", side_effect=[redirect, Response(body=PAYLOAD)]) as get:
            updater.download_update(INFO, self.destination)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(redirect.closed)

    def test_untrusted_or_http_redirect_is_rejected_before_following(self):
        for url in ("https://evil.example/update.exe", "http://github.com/update.exe"):
            with self.subTest(url=url), patch("app_updater.requests.get", return_value=Response(
                    status=302, headers={"Location": url})) as get:
                with self.assertRaisesRegex(updater.UpdateError, "trusted GitHub HTTPS"):
                    updater.download_update(INFO, self.destination)
            get.assert_called_once()
            self.assert_no_partial_files()

    def test_installer_is_reverified_before_windows_launch(self):
        self.destination.write_bytes(PAYLOAD[:-1] + b"z")
        with patch("app_updater._shell_execute_elevated") as launch:
            with self.assertRaises(updater.UpdateError):
                updater.launch_installer(self.destination, INFO, r"C:\Program Files\VibeDownloader", 123)
        launch.assert_not_called()

    def test_installer_launch_uses_nsis_parameters_and_handles_uac_cancellation(self):
        self.destination.write_bytes(PAYLOAD)
        lock_observed = []

        def launch_while_locked(path, parameters):
            with self.assertRaises(OSError):
                with open(path, "r+b"):
                    pass
            lock_observed.append(True)

        with patch("app_updater._shell_execute_elevated", side_effect=launch_while_locked) as launch:
            updater.launch_installer(self.destination, INFO, r"C:\Program Files\VibeDownloader", 123)
        self.assertEqual(lock_observed, [True])
        self.assertEqual(
            launch.call_args.args[1],
            r"/S /UPDATE /WAITPID=123 /D=C:\Program Files\VibeDownloader")
        with patch("app_updater._shell_execute_elevated", side_effect=updater.UpdateCancelled("Cancelled")):
            with self.assertRaises(updater.UpdateCancelled):
                updater.launch_installer(self.destination, INFO, r"C:\Program Files\VibeDownloader", 123)

    def test_unsafe_installer_parameters_are_rejected(self):
        for path, pid in (
            ("relative-folder", 123), ('C:\\App" /S', 123),
            ("C:\\App\ninjected", 123), (r"C:\App", 0), (r"C:\App", True),
        ):
            with self.subTest(path=path, pid=pid), self.assertRaises(updater.UpdateError):
                updater.installer_parameters(path, pid)


class AutomaticCheckTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "update_state.json"
        self.now = 100000.0

    def test_successful_check_is_throttled_for_twelve_hours(self):
        updater.record_check(self.path, True, self.now)
        self.assertFalse(updater.should_check_automatically(self.path, self.now + 3600))
        self.assertTrue(updater.should_check_automatically(self.path, self.now + updater.CHECK_INTERVAL))

    def test_failed_check_retries_after_an_hour_without_marking_success(self):
        updater.record_check(self.path, False, self.now)
        self.assertNotIn("checked_at", json.loads(self.path.read_text()))
        self.assertFalse(updater.should_check_automatically(self.path, self.now + 60))
        self.assertTrue(updater.should_check_automatically(self.path, self.now + updater.RETRY_INTERVAL))

    def test_corrupt_or_future_state_does_not_disable_checks(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertTrue(updater.should_check_automatically(self.path, self.now))
        self.path.write_text(json.dumps({"checked_at": self.now + 999999, "attempted_at": "NaN"}))
        self.assertTrue(updater.should_check_automatically(self.path, self.now))


class WindowsShellTests(unittest.TestCase):
    def test_elevated_shell_launch_initializes_and_releases_com(self):
        shell, kernel, ole = Mock(), Mock(), Mock()
        ole.CoInitializeEx.return_value = 0
        captured = []

        def execute(pointer):
            info = pointer._obj
            captured.append((info.lpVerb, info.lpFile, info.lpParameters))
            info.hProcess = 55
            return True

        shell.ShellExecuteExW.side_effect = execute
        dlls = {"shell32": shell, "kernel32": kernel, "ole32": ole}
        with patch("app_updater.ctypes.WinDLL", side_effect=lambda name, **_kwargs: dlls[name]):
            updater._shell_execute_elevated(Path(r"C:\Updates\Installer.exe"), "/S /UPDATE")
        self.assertEqual(captured[0][0], "runas")
        self.assertEqual(captured[0][2], "/S /UPDATE")
        kernel.CloseHandle.assert_called_once_with(55)
        ole.CoInitializeEx.assert_called_once_with(None, 2)
        ole.CoUninitialize.assert_called_once_with()

    def test_real_shell_error_code_for_declined_uac_becomes_cancellation(self):
        shell, kernel, ole = Mock(), Mock(), Mock()
        ole.CoInitializeEx.return_value = 0
        shell.ShellExecuteExW.return_value = False
        dlls = {"shell32": shell, "kernel32": kernel, "ole32": ole}
        with patch("app_updater.ctypes.WinDLL", side_effect=lambda name, **_kwargs: dlls[name]), \
                patch("app_updater.ctypes.get_last_error", return_value=1223):
            with self.assertRaises(updater.UpdateCancelled):
                updater._shell_execute_elevated(Path(r"C:\Updates\Installer.exe"), "/S")
        kernel.CloseHandle.assert_not_called()
        ole.CoUninitialize.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

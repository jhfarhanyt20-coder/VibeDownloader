import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import DownloadTask, VibeDownloaderApp, main
from test_app_updater import INFO
from update_dialog import AppUpdateDialog


class UpdateControllerTests(unittest.TestCase):
    def fake_app(self, dialog=None):
        return SimpleNamespace(
            running=True, _update_dialog=dialog, _update_check_running=True,
            _pending_update=None, _ensure_update_dialog=Mock(return_value=dialog),
            _show_window=Mock(),
        )

    def test_help_menu_checks_the_app_not_ytdlp(self):
        app = SimpleNamespace(_check_app_update=Mock())
        VibeDownloaderApp.check_for_updates(app)
        app._check_app_update.assert_called_once_with()

    def test_check_error_is_not_displayed_as_up_to_date(self):
        dialog = Mock(alive=True, busy=False)
        app = self.fake_app(dialog)
        VibeDownloaderApp._finish_update_check(app, None, "Offline", False)
        dialog.show_error.assert_called_once_with("Offline")
        dialog.show_current.assert_not_called()
        self.assertFalse(app._update_check_running)

    def test_closed_manual_check_does_not_reopen_a_dialog(self):
        app = self.fake_app()
        VibeDownloaderApp._finish_update_check(app, INFO, None, False)
        app._ensure_update_dialog.assert_not_called()

    def test_silent_new_release_is_offered_but_silent_current_release_is_not(self):
        dialog = Mock(alive=True, busy=False)
        app = self.fake_app()
        app._ensure_update_dialog.return_value = dialog
        VibeDownloaderApp._finish_update_check(app, None, None, True)
        app._ensure_update_dialog.assert_not_called()
        VibeDownloaderApp._finish_update_check(app, INFO, None, True)
        dialog.show_available.assert_called_once_with(INFO)
        self.assertEqual(app._pending_update, INFO)

    def test_declined_uac_leaves_the_app_running(self):
        dialog = Mock(alive=True, busy=False)
        app = self.fake_app(dialog)
        app._update_install_running = True
        VibeDownloaderApp._update_install_failed(app, "Windows permission was cancelled")
        self.assertTrue(app.running)
        self.assertFalse(app._update_install_running)
        dialog.show_install_error.assert_called_once()

    def test_update_pauses_downloads_before_full_exit(self):
        active = DownloadTask(url="https://example.com/file")
        active.status = "downloading"
        active.pause_event = threading.Event()
        queued = DownloadTask(url="https://example.com/next")
        queued.status = "queued"
        callbacks = []
        app = SimpleNamespace(
            tasks={active.id: active, queued.id: queued}, lock=threading.RLock(),
            _update_shutdown=False, _queue_action_fired=False,
            show_status=Mock(), after=lambda _delay, callback: callbacks.append(callback),
            _real_close=Mock(),
        )
        VibeDownloaderApp._close_for_update(app)
        self.assertTrue(app._update_shutdown)
        self.assertTrue(active.pause_event.is_set())
        self.assertEqual(queued.status, "paused")
        app._real_close.assert_not_called()
        active.status = "paused"
        callbacks.pop(0)()
        app._real_close.assert_called_once()
        self.assertEqual(DownloadTask.from_dict(active.to_dict()).status, "paused")

    def test_source_run_cannot_launch_an_updater_installer(self):
        app = SimpleNamespace(_update_install_running=False)
        with patch("main.sys.frozen", False, create=True), patch("main.app_updater.launch_installer") as launch:
            VibeDownloaderApp._install_app_update(app, INFO, "installer.exe")
        launch.assert_not_called()

    def test_background_check_cannot_interrupt_an_update_download(self):
        dialog = Mock(alive=True, busy=True)
        app = self.fake_app(dialog)
        VibeDownloaderApp._finish_update_check(app, INFO, None, True)
        dialog.show_available.assert_not_called()
        dialog.show_current.assert_not_called()

    def test_current_or_error_dialog_clears_old_update_metadata(self):
        for method, arguments in (
            (AppUpdateDialog.show_current, ()), (AppUpdateDialog.show_error, ("Offline",)),
        ):
            window = SimpleNamespace(
                alive=True, info=INFO, installer_path="old.exe",
                _stop_progress=Mock(), progress=Mock(), headline=Mock(), _set_notes=Mock(),
                status=Mock(), primary=Mock(), palette={"success": "green", "error": "red"},
            )
            method(window, *arguments)
            self.assertIsNone(window.info)
            self.assertIsNone(window.installer_path)

    def test_one_file_update_waits_for_the_bootloader_parent(self):
        dialog = Mock(alive=True, busy=False)
        app = SimpleNamespace(
            _update_install_running=False, _ensure_update_dialog=Mock(return_value=dialog),
            post=Mock(), _close_for_update=Mock(),
        )

        def thread(target, **_kwargs):
            return SimpleNamespace(start=target)

        with patch("main.sys.frozen", True, create=True), \
                patch("main.threading.Thread", side_effect=thread), \
                patch("main.os.getppid", return_value=1234), \
                patch("main.yt_helper.installed_dir", return_value=r"C:\Program Files\VibeDownloader"), \
                patch("main.app_updater.launch_installer") as launch:
            VibeDownloaderApp._install_app_update(app, INFO, "installer.exe")
        launch.assert_called_once_with(
            "installer.exe", INFO, r"C:\Program Files\VibeDownloader", 1234)
        app.post.assert_called_once_with(app._close_for_update)

    def test_bundle_self_test_does_not_touch_the_resident_app_or_startup(self):
        with patch("main.sys.argv", ["VibeDownloader.exe", "--self-test", "report.json"]), \
                patch("bundle_self_test.run_self_test", return_value=0) as self_test, \
                patch("main._acquire_single_instance") as singleton, \
                patch("main.windows_startup.set_startup_enabled") as startup:
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        self_test.assert_called_once_with("report.json")
        singleton.assert_not_called()
        startup.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Each video is saved under its own title and never "finishes" as an older file."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_helper  # noqa: E402

CHUNK = ("https://rr3---sn-abc.googlevideo.com/videoplayback?expire=1&mime=video%2Fmp4"
         "&vprv=1&rqh=1&dur=8.000")


class StreamChunkTests(unittest.TestCase):
    def test_player_pieces_are_recognised(self):
        self.assertTrue(yt_helper.is_stream_chunk_url(CHUNK))
        self.assertTrue(yt_helper.is_stream_chunk_url("https://cdn.example.com/a/videoplayback?x=1"))

    def test_normal_links_are_not_pieces(self):
        for url in ("https://www.youtube.com/watch?v=abc", "https://example.com/movie.mp4",
                    "https://youtu.be/abc", ""):
            self.assertFalse(yt_helper.is_stream_chunk_url(url), url)


class TitleTests(unittest.TestCase):
    def test_made_up_titles_are_generic(self):
        self.assertTrue(yt_helper.is_generic_title("videoplayback", CHUNK))
        self.assertTrue(yt_helper.is_generic_title("videoplayback [mp4&vprv=1&rqh=1&dur=8]"))
        self.assertTrue(yt_helper.is_generic_title("index", "https://x.com/hls/index.m3u8"))
        self.assertTrue(yt_helper.is_generic_title("clip42", "https://x.com/v/clip42.mp4"))
        self.assertTrue(yt_helper.is_generic_title(""))

    def test_real_titles_are_kept(self):
        self.assertFalse(yt_helper.is_generic_title("Amar Sonar Bangla (Official Video)",
                                                    "https://www.youtube.com/watch?v=abc"))

    def test_tab_title_loses_the_site_name(self):
        self.assertEqual(yt_helper.clean_page_title("Song Name - YouTube"), "Song Name")
        self.assertEqual(yt_helper.clean_page_title("(3) Song Name - YouTube"), "Song Name")
        self.assertEqual(yt_helper.clean_page_title("Plain title"), "Plain title")


class UniqueStemTests(unittest.TestCase):
    def test_new_name_when_a_finished_file_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(yt_helper.unique_media_stem(folder, "Song"), "Song")
            open(os.path.join(folder, "Song.mp4"), "w").close()
            self.assertEqual(yt_helper.unique_media_stem(folder, "Song"), "Song (2)")
            open(os.path.join(folder, "Song (2).mp3"), "w").close()
            self.assertEqual(yt_helper.unique_media_stem(folder, "Song"), "Song (3)")

    def test_leftover_parts_of_another_video_are_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "Live.f137.mp4.part"), "w").close()
            self.assertEqual(yt_helper.unique_media_stem(folder, "Live"), "Live (2)")

    def test_names_other_tasks_use_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(yt_helper.unique_media_stem(folder, "Live", ["live"]), "Live (2)")

    def test_long_titles_keep_their_number(self):
        with tempfile.TemporaryDirectory() as folder:
            title = "x" * 140
            open(os.path.join(folder, title + ".mp4"), "w").close()
            stem = yt_helper.unique_media_stem(folder, title)
            self.assertEqual(stem, title + " (2)")
            runner = yt_helper.YtDlpRunner("https://x.com/a.m3u8", folder, output_name=stem)
            command = runner._build_command("yt-dlp.exe", None)
            self.assertTrue(command[command.index("-o") + 1].endswith(" (2).%(ext)s"))

    def test_raw_links_and_pages(self):
        self.assertTrue(yt_helper.is_raw_media_link("https://x.com/hls/index.m3u8?t=1"))
        self.assertTrue(yt_helper.is_raw_media_link("https://x.com/v/clip.mp4"))
        self.assertTrue(yt_helper.is_raw_media_link(CHUNK))
        self.assertFalse(yt_helper.is_raw_media_link("https://www.youtube.com/watch?v=abc"))

    def test_one_video_per_page_link(self):
        runner = yt_helper.YtDlpRunner("https://www.youtube.com/@channel", "C:/x")
        command = runner._build_command("yt-dlp.exe", None)
        self.assertEqual(command[command.index("--playlist-items") + 1], "1")

    def test_other_titles_are_not_confused(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "Song Two.mp4"), "w").close()
            self.assertEqual(yt_helper.unique_media_stem(folder, "Song"), "Song")

    def test_runner_writes_under_the_given_name(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = yt_helper.YtDlpRunner("https://www.youtube.com/watch?v=abc", folder,
                                           output_name="Song (2)")
            command = runner._build_command("yt-dlp.exe", None)
            self.assertEqual(command[command.index("-o") + 1],
                             os.path.join(folder, "Song (2).%(ext)s"))


if __name__ == "__main__":
    unittest.main()

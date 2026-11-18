import hashlib
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from downloader import COMPLETED, MultiConnectionDownloader, Segment

PAYLOAD = bytes((i * 37 + (i // 251)) % 256 for i in range(4 * 1024 * 1024 + 123))


class RangeHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        header = self.headers.get("Range", "")
        if header.startswith("bytes="):
            try:
                spec = header[6:].split(",", 1)[0]
                start_s, end_s = spec.split("-", 1)
                start = int(start_s or 0)
                end = int(end_s) if end_s else len(PAYLOAD) - 1
            except (ValueError, TypeError):
                self.send_error(400)
                return
            self.__class__.requests.append((start, end))
            if start >= len(PAYLOAD):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(PAYLOAD)}")
                self.end_headers()
                return
            end = min(end, len(PAYLOAD) - 1)
            body = PAYLOAD[start:end + 1]
            self.send_response(206)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(PAYLOAD)


class LyingRangeHandler(BaseHTTPRequestHandler):
    """Claims to support ranges in headers but ignores the Range request."""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        try:
            self.wfile.write(PAYLOAD)
        except (BrokenPipeError, ConnectionResetError):
            # The client intentionally closes rejected multi-range responses.
            pass


class LimitedConnectionHandler(RangeHandler):
    """Serves ranges, but only 2 at a time; extra connections get 503."""
    slots = threading.BoundedSemaphore(2)

    def do_GET(self):
        if not self.__class__.slots.acquire(blocking=False):
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            super().do_GET()
        finally:
            self.__class__.slots.release()


class DownloaderRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RangeHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/sample.bin"

        cls.lying_server = ThreadingHTTPServer(("127.0.0.1", 0), LyingRangeHandler)
        cls.lying_thread = threading.Thread(target=cls.lying_server.serve_forever, daemon=True)
        cls.lying_thread.start()
        cls.lying_url = f"http://127.0.0.1:{cls.lying_server.server_port}/sample.bin"

        cls.limited_server = ThreadingHTTPServer(("127.0.0.1", 0), LimitedConnectionHandler)
        cls.limited_thread = threading.Thread(target=cls.limited_server.serve_forever,
                                              daemon=True)
        cls.limited_thread.start()
        cls.limited_url = f"http://127.0.0.1:{cls.limited_server.server_port}/sample.bin"

    @classmethod
    def tearDownClass(cls):
        for server, thread in ((cls.server, cls.thread), (cls.lying_server, cls.lying_thread),
                               (cls.limited_server, cls.limited_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def _assert_file_matches(self, path):
        with open(path, "rb") as downloaded:
            result = downloaded.read()
        self.assertEqual(len(result), len(PAYLOAD))
        self.assertEqual(hashlib.sha256(result).digest(), hashlib.sha256(PAYLOAD).digest())

    def test_parallel_ranges_produce_exact_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sample.bin")
            engine = MultiConnectionDownloader(self.url, path, connections=4)
            status, error = engine.run(threading.Event(), threading.Event())
            self.assertEqual(status, COMPLETED, error)
            self._assert_file_matches(path)
            ranged = [request for request in RangeHandler.requests if request != (0, 0)]
            self.assertGreaterEqual(len(ranged), 2, "Expected parallel range requests beyond the probe request")

    def test_dynamic_steal_covers_file_without_overlap(self):
        engine = MultiConnectionDownloader("http://127.0.0.1/unused", "unused.bin",
                                           connections=2, dynamic=True)
        engine.total_size = 8 * 1024 * 1024
        engine.segments = [
            Segment(0, 4 * 1024 * 1024 - 1, 0),
            Segment(4 * 1024 * 1024, engine.total_size - 1, 1),
        ]
        engine.segments[0].done = engine.segments[0].length
        engine.segments[0].complete = True
        engine.segments[1].done = 1000
        stolen = engine._steal_tail()
        self.assertIsNotNone(stolen)
        ranges = sorted((seg.start, seg.end) for seg in engine.segments)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], engine.total_size - 1)
        for left, right in zip(ranges, ranges[1:]):
            self.assertEqual(left[1] + 1, right[0])
        covered = sum(end - start + 1 for start, end in ranges)
        self.assertEqual(covered, engine.total_size)

    def test_server_connection_limit_does_not_fail_download(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "limited.bin")
            engine = MultiConnectionDownloader(self.limited_url, path, connections=8)
            status, error = engine.run(threading.Event(), threading.Event())
            self.assertEqual(status, COMPLETED, error)
            self._assert_file_matches(path)

    def test_presized_part_is_not_resumed_as_single_stream(self):
        # A paused multi-connection download leaves a full-size .part with holes
        # plus a state file. If the next run can't use ranges, it must restart
        # instead of treating the full-size .part as finished.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "resume.bin")
            with open(path + ".part", "wb") as handle:
                handle.truncate(len(PAYLOAD))
            with open(path + ".vibe.json", "w", encoding="utf-8") as handle:
                handle.write('{"url": "x", "size": 0, "segments": []}')
            engine = MultiConnectionDownloader(self.lying_url, path, connections=4)
            engine.total_size = len(PAYLOAD)
            engine.stop_event = threading.Event()
            engine.pause_event = threading.Event()
            status, error = engine._run_single()
            self.assertEqual(status, COMPLETED, error)
            self._assert_file_matches(path)
            self.assertFalse(os.path.exists(path + ".vibe.json"))

    def test_server_that_lies_about_ranges_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "fallback.bin")
            engine = MultiConnectionDownloader(self.lying_url, path, connections=4)
            status, error = engine.run(threading.Event(), threading.Event())
            self.assertEqual(status, COMPLETED, error)
            self._assert_file_matches(path)


if __name__ == "__main__":
    unittest.main()

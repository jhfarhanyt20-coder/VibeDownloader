"""
VibeDownloader - IDM-style multi-connection download engine.

Split the file into N byte ranges, download them in parallel and write
each range straight into its own offset of a single .part file.
Supports pause / resume / cancel and keeps a small state file next to
the download so a paused file can continue where it stopped.
"""

import json
import os
import re
import threading
import time

import requests

CHUNK_SIZE = 512 * 1024                  # fewer Python writes / progress callbacks
MIN_PARALLEL_SIZE = 1024 * 1024          # below 1 MB parallel is pointless
MIN_SEGMENT_SIZE = 256 * 1024
MAX_CONNECTIONS = 16                     # protect servers and weaker PCs
# Idle connections take the tail of a slow segment once this much is left.
STEAL_MIN = 768 * 1024


class RateLimiter:
    """Shared bandwidth cap for one download (IDM-style speed limiter)."""

    def __init__(self, limit_bps=0):
        self.limit = max(0, int(limit_bps or 0))
        self._started = time.time()
        self._budget = 0.0
        self._lock = threading.Lock()

    def set_limit(self, bps):
        self.limit = max(0, int(bps or 0))

    def reset_window(self):
        with self._lock:
            self._started = time.time()
            self._budget = 0.0

    def throttle(self, nbytes):
        """Call after writing nbytes; sleeps to keep the aggregate rate <= limit."""
        if not self.limit:
            return
        with self._lock:
            self._budget += nbytes
            target = (time.time() - self._started) * self.limit
            behind = self._budget - target
            if behind > 0:
                sleep_for = behind / self.limit
        # sleep outside the lock so set_limit() can react instantly
        if behind > 0:
            time.sleep(sleep_for)
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Return values of run()
COMPLETED = "completed"
PAUSED = "paused"
STOPPED = "stopped"
ERROR = "error"


def friendly_error(exc):
    """Turn a requests exception into something a human can read."""
    text = str(exc)
    low = text.lower()
    if "403" in text:
        return "Access denied (403). The link expired or needs a login/cookie."
    if "404" in text:
        return "Not found (404). The file was removed or the link is wrong."
    if "429" in text:
        return "Too many requests (429). Wait a bit and press Start."
    if "timed out" in low or "timeout" in low:
        return "Connection timed out. Check the internet and retry."
    if "certificate" in low or "ssl" in low:
        return "SSL certificate problem for this server."
    if "name resolution" in low or "getaddrinfo" in low or "failed to establish" in low:
        return "Could not reach the server. Check the URL / internet."
    if "connection" in low:
        return "Connection was closed by the server."
    return text[:180] if text else "Unknown error"


class Segment:
    """One byte range of the file = one connection."""

    def __init__(self, start, end, index):
        self.start = start
        self.end = end
        self.index = index
        self.done = 0            # bytes already written by this segment
        self.complete = False
        self.error = None

    @property
    def length(self):
        return self.end - self.start + 1


class MultiConnectionDownloader:
    def __init__(self, url, save_path, connections=8, headers=None, on_progress=None,
                 rate_limiter=None, on_segments=None, dynamic=True):
        self.url = url
        self.save_path = save_path
        self.part_path = save_path + ".part"
        self.state_path = save_path + ".vibe.json"
        self.connections = max(1, int(connections or 8))
        self.headers = dict(headers or {})
        self.on_progress = on_progress    # callback(downloaded, total, speed_bps)
        self.on_segments = on_segments    # callback(list of segment dicts)
        self.limiter = rate_limiter       # optional RateLimiter for a bandwidth cap
        # IDM dynamic segmentation: a finished connection steals the tail of a slow one.
        self.dynamic = bool(dynamic)

        self.total_size = 0
        self.downloaded = 0
        self.speed = 0.0
        self.ranges_ok = False
        self.etag = ""
        self._probe_etag = ""
        self.error = ""

        self.stop_event = None
        self.pause_event = None
        self.segments = []

        self._lock = threading.Lock()
        self._last_notify = 0.0
        self._last_save = 0.0
        self._last_err = ""
        self._range_fallback_done = False

    # ------------------------------------------------------------------ public
    def run(self, stop_event=None, pause_event=None):
        """Blocking. Returns (status, error_message)."""
        self.stop_event = stop_event or threading.Event()
        self.pause_event = pause_event or threading.Event()

        try:
            self._probe()
        except Exception as exc:                 # noqa: BLE001
            return ERROR, friendly_error(exc)

        if not self.total_size:
            return self._run_single()

        if self.ranges_ok and self.total_size >= MIN_PARALLEL_SIZE:
            return self._run_parallel()

        return self._run_single()

    # ------------------------------------------------------------------ helpers
    def _headers(self):
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        }
        headers.update(self.headers)
        return headers

    def _probe(self):
        """Find out size + whether the server accepts byte ranges."""
        headers = self._headers()
        headers["Range"] = "bytes=0-0"

        with requests.get(self.url, headers=headers, stream=True,
                          timeout=(15, 30), allow_redirects=True) as resp:
            status = resp.status_code
            if status == 206:
                self.ranges_ok = True
                content_range = resp.headers.get("Content-Range", "")
                match = re.search(r"/\s*(\d+)\s*$", content_range)
                if match:
                    self.total_size = int(match.group(1))
            elif status == 200:
                self.total_size = int(resp.headers.get("Content-Length") or 0)
                self.ranges_ok = ("bytes" in
                                  resp.headers.get("Accept-Ranges", "").lower()
                                  and self.total_size > 0)
            elif status in (401, 403, 404, 410):
                raise RuntimeError(f"HTTP {status}")
            else:
                # try a plain request as a last resort
                self.ranges_ok = False

            self._probe_etag = resp.headers.get("ETag", "")
            self.etag = (self._probe_etag
                         or resp.headers.get("Last-Modified") or "")
            self._accept_ranges = resp.headers.get("Accept-Ranges", "")
            self._content_type = resp.headers.get("Content-Type", "")

    # --------------------------------------------------------------- state file
    def _load_state(self):
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:                        # noqa: BLE001
            return None

        if state.get("url") != self.url:
            return None
        if int(state.get("size", -1)) != self.total_size:
            return None
        if self.etag and state.get("etag") and state["etag"] != self.etag:
            return None                       # file changed on the server
        return state

    def _save_state(self):
        if not self.segments:
            return
        state = {
            "url": self.url,
            "size": self.total_size,
            "etag": self.etag,
            "connections": len(self.segments),
            "segments": [
                {"start": seg.start, "end": seg.end, "done": seg.done}
                for seg in self.segments
            ],
            "saved_at": time.time(),
        }
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
            os.replace(tmp, self.state_path)
        except Exception:                        # noqa: BLE001
            pass

    def _delete_state(self):
        for path in (self.state_path, self.state_path + ".tmp"):
            try:
                os.remove(path)
            except OSError:
                pass

    def _finish(self):
        """Move .part -> final file."""
        try:
            if os.path.exists(self.part_path):
                os.replace(self.part_path, self.save_path)
            self._delete_state()
        except OSError as exc:
            return ERROR, friendly_error(exc)
        self.downloaded = self.total_size or self.downloaded
        self._notify(force=True)
        return COMPLETED, ""

    def _notify(self, force=False):
        now = time.time()
        if not force and now - self._last_notify < 0.2:
            return
        self._last_notify = now
        if self.on_progress:
            try:
                self.on_progress(self.downloaded, self.total_size, int(self.speed))
            except Exception:                    # noqa: BLE001
                pass
        if self.on_segments:
            try:
                self.on_segments(self.segment_snapshot())
            except Exception:                    # noqa: BLE001
                pass

    def segment_snapshot(self):
        """Ranges the progress window draws. Safe to call from the UI thread."""
        with self._lock:
            out = []
            for seg in self.segments:
                length = seg.length
                out.append({
                    "index": seg.index,
                    "start": seg.start,
                    "end": seg.end,
                    "done": seg.done,
                    "complete": seg.complete,
                    "ratio": (seg.done / length) if length else 1.0,
                })
            return out

    def _interrupted(self):
        return (self.stop_event.is_set() or self.pause_event.is_set())

    def _result_when_interrupted(self):
        if self.stop_event.is_set():
            return STOPPED, ""
        return PAUSED, ""

    # ------------------------------------------------------------------ parallel
    def _run_parallel(self):
        state = self._load_state()
        connections = self.connections
        if state:
            try:
                connections = max(1, int(state.get("connections") or connections))
            except (TypeError, ValueError):
                connections = self.connections
        connections = max(1, min(connections, MAX_CONNECTIONS,
                                 max(1, self.total_size // MIN_SEGMENT_SIZE)))

        # Make sure the .part file is exactly the size of the final file.
        try:
            os.makedirs(os.path.dirname(self.part_path) or ".", exist_ok=True)
            with open(self.part_path, "a+b") as handle:
                handle.truncate(self.total_size)
        except OSError as exc:
            return ERROR, friendly_error(exc)

        saved = (state or {}).get("segments") or []
        self.segments = self._segments_from_state(saved, connections)

        self.downloaded = sum(seg.done for seg in self.segments)
        self._notify(force=True)

        threads = []
        for seg in list(self.segments):
            if not seg.complete:
                self._spawn_segment(seg, threads)

        last_time = time.time()
        last_bytes = self.downloaded
        while any(thread.is_alive() for thread in threads):
            if self._interrupted():
                break
            time.sleep(0.2)
            now = time.time()
            elapsed = now - last_time
            if elapsed >= 0.5:
                measured = (self.downloaded - last_bytes) / elapsed
                self.speed = (measured if self.speed <= 0
                              else self.speed * 0.6 + measured * 0.4)
                last_time, last_bytes = now, self.downloaded
                self._notify(force=True)
            if now - self._last_save >= 2:
                self._save_state()
                self._last_save = now
            self._rebalance(threads)

        for thread in threads:
            thread.join(timeout=5)

        self._save_state()
        self.speed = 0
        self._notify(force=True)

        errors = [seg.error for seg in self.segments if seg.error]
        if errors and not self._interrupted() and not self._range_fallback_done:
            if any("range" in str(err).lower() for err in errors):
                # Server lied about range support - restart as one stream.
                self._range_fallback_done = True
                try:
                    os.remove(self.part_path)
                except OSError:
                    pass
                self._delete_state()
                self.downloaded = 0
                self.segments = []
                self.speed = 0
                return self._run_single()

        if all(seg.complete for seg in self.segments):
            return self._finish()

        if self._interrupted():
            return self._result_when_interrupted()

        return ERROR, (friendly_error(errors[0]) if errors
                       else "Download stopped unexpectedly")

    def _segments_from_state(self, saved, connections):
        """Restore exact ranges (including stolen tails) or rebuild equal splits."""
        restored = []
        if saved and isinstance(saved[0], dict):
            for index, item in enumerate(saved):
                try:
                    start = int(item["start"])
                    end = int(item["end"])
                    done = int(item.get("done") or 0)
                except (KeyError, TypeError, ValueError):
                    restored = []
                    break
                if end < start or start < 0 or end >= self.total_size:
                    restored = []
                    break
                seg = Segment(start, end, index)
                seg.done = max(0, min(done, seg.length))
                if seg.done >= seg.length:
                    seg.done = seg.length
                    seg.complete = True
                restored.append(seg)
            if restored and restored[0].start == 0 and restored[-1].end == self.total_size - 1:
                return restored

        segment_size = self.total_size // connections
        segments = []
        for index in range(connections):
            start = index * segment_size
            end = (self.total_size - 1 if index == connections - 1
                   else (index + 1) * segment_size - 1)
            seg = Segment(start, end, index)
            if index < len(saved) and not isinstance(saved[index], dict):
                try:
                    seg.done = max(0, min(int(saved[index]), seg.length))
                except (TypeError, ValueError):
                    seg.done = 0
            if seg.done >= seg.length:
                seg.done = seg.length
                seg.complete = True
            segments.append(seg)
        return segments

    def _spawn_segment(self, seg, threads):
        thread = threading.Thread(target=self._segment_worker, args=(seg,),
                                  daemon=True)
        thread.start()
        threads.append(thread)

    def _rebalance(self, threads):
        """Give a free connection the unfinished tail of the slowest segment."""
        if not self.dynamic or self._interrupted():
            return
        if len(self.segments) >= MAX_CONNECTIONS:
            return
        alive = sum(1 for thread in threads if thread.is_alive())
        if alive >= self.connections:
            return
        stolen = self._steal_tail()
        if stolen is not None:
            self._spawn_segment(stolen, threads)

    def _steal_tail(self):
        """Split the fattest in-flight segment. Ranges never overlap."""
        with self._lock:
            candidates = []
            for seg in self.segments:
                if seg.complete or seg.error:
                    continue
                remaining = seg.length - seg.done
                if remaining > STEAL_MIN * 2:
                    candidates.append(seg)
            if not candidates:
                return None
            victim = max(candidates, key=lambda seg: seg.length - seg.done)
            cursor = victim.start + victim.done
            split_at = cursor + max(STEAL_MIN, (victim.end - cursor) // 2)
            if victim.end - split_at < STEAL_MIN:
                return None
            old_end = victim.end
            victim.end = split_at
            stolen = Segment(split_at + 1, old_end, len(self.segments))
            self.segments.append(stolen)
            return stolen

    def _segment_worker(self, seg):
        attempts = 0
        while not self._interrupted():
            with self._lock:
                if seg.done >= seg.length:
                    seg.complete = True
                    return
                start = seg.start + seg.done
                requested_end = seg.end
            if attempts >= 4:
                seg.error = self._last_err or "Connection failed"
                return
            headers = self._headers()
            headers["Range"] = f"bytes={start}-{requested_end}"
            if self._probe_etag and not self._probe_etag.strip().startswith("W/"):
                headers["If-Range"] = self._probe_etag
            try:
                with requests.get(self.url, headers=headers, stream=True,
                                  timeout=(15, 30), allow_redirects=True) as resp:
                    if resp.status_code != 206:
                        if resp.status_code in (200, 416):
                            # Range was ignored or rejected; the coordinator will
                            # safely restart as a single stream instead of keeping
                            # a possibly corrupt partially-written file.
                            seg.error = f"range-not-supported (HTTP {resp.status_code})"
                            return
                        if resp.status_code in (429, 500, 502, 503, 504):
                            attempts += 1
                            if attempts < 4 and not self._interrupted():
                                time.sleep(min(2 * attempts, 6))
                                continue
                        # Preserve useful HTTP errors rather than misclassifying
                        # access/rate/server errors as a range limitation.
                        seg.error = f"HTTP {resp.status_code}"
                        return

                    response_etag = resp.headers.get("ETag", "")
                    if (self._probe_etag and response_etag
                            and response_etag != self._probe_etag):
                        seg.error = "range-response-mismatch (ETag changed)"
                        return

                    content_range = resp.headers.get("Content-Range", "")
                    range_match = re.match(
                        r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$",
                        content_range.strip(), re.IGNORECASE)
                    if not range_match:
                        seg.error = "range-response-mismatch (missing Content-Range)"
                        return
                    response_start, response_end = int(range_match.group(1)), int(range_match.group(2))
                    response_total = range_match.group(3)
                    if response_start != start or response_end > requested_end:
                        seg.error = "range-response-mismatch (unexpected byte offsets)"
                        return
                    if (self.total_size and response_total != "*"
                            and int(response_total) != self.total_size):
                        seg.error = "range-response-mismatch (file size changed)"
                        return

                    with open(self.part_path, "r+b") as handle:
                        handle.seek(start)
                        finished = False
                        for chunk in resp.iter_content(CHUNK_SIZE):
                            if self._interrupted():
                                return
                            if not chunk:
                                continue
                            with self._lock:
                                remaining = seg.length - seg.done
                                if remaining <= 0:
                                    finished = True
                                    break
                                if len(chunk) > remaining:
                                    chunk = chunk[:remaining]
                                handle.seek(seg.start + seg.done)
                                handle.write(chunk)
                                seg.done += len(chunk)
                                self.downloaded += len(chunk)
                                finished = seg.done >= seg.length
                            if self.limiter:
                                self.limiter.throttle(len(chunk))
                            if finished:
                                break
            except Exception as exc:             # noqa: BLE001
                self._last_err = friendly_error(exc)
                attempts += 1
                if self._interrupted():
                    return
                time.sleep(min(2 * attempts, 6))
                continue

            attempts = 0
            with self._lock:
                if seg.done >= seg.length:
                    seg.complete = True
                    return

    # -------------------------------------------------------------------- single
    def _run_single(self):
        try:
            os.makedirs(os.path.dirname(self.part_path) or ".", exist_ok=True)
        except OSError as exc:
            return ERROR, friendly_error(exc)

        offset = 0
        if os.path.exists(self.part_path) and self.total_size:
            offset = min(os.path.getsize(self.part_path), self.total_size)
        elif os.path.exists(self.part_path):
            offset = os.path.getsize(self.part_path)

        if self.total_size and offset >= self.total_size:
            return self._finish()

        headers = self._headers()
        if offset:
            headers["Range"] = f"bytes={offset}-"

        try:
            resp = requests.get(self.url, headers=headers, stream=True,
                                timeout=(15, 30), allow_redirects=True)
        except Exception as exc:                 # noqa: BLE001
            return ERROR, friendly_error(exc)

        if resp.status_code not in (200, 206):
            resp.close()
            return ERROR, f"Server returned HTTP {resp.status_code}"

        if offset and resp.status_code == 200:
            # Server ignored our Range header -> start from scratch.
            offset = 0

        if not self.total_size:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit():
                self.total_size = int(length) + offset

        mode = "r+b" if offset else "wb"
        self.downloaded = offset
        self._notify(force=True)

        last_time = time.time()
        last_bytes = self.downloaded
        try:
            with open(self.part_path, mode) as handle:
                if offset:
                    handle.seek(offset)
                for chunk in resp.iter_content(CHUNK_SIZE):
                    if self._interrupted():
                        resp.close()
                        self.speed = 0
                        self._notify(force=True)
                        return self._result_when_interrupted()
                    if not chunk:
                        continue
                    handle.write(chunk)
                    self.downloaded += len(chunk)
                    if self.limiter:
                        self.limiter.throttle(len(chunk))

                    now = time.time()
                    if now - last_time >= 0.5:
                        measured = (self.downloaded - last_bytes) / (now - last_time)
                        self.speed = (measured if self.speed <= 0
                                      else self.speed * 0.6 + measured * 0.4)
                        last_time, last_bytes = now, self.downloaded
                        self._notify(force=True)
        except Exception as exc:                 # noqa: BLE001
            resp.close()
            self.speed = 0
            if self._interrupted():
                return self._result_when_interrupted()
            return ERROR, friendly_error(exc)
        finally:
            try:
                resp.close()
            except Exception:                    # noqa: BLE001
                pass

        self.speed = 0
        if self._interrupted():
            return self._result_when_interrupted()

        if self.total_size and self.downloaded < self.total_size:
            self._notify(force=True)
            return ERROR, "Connection closed before the file finished"

        return self._finish()

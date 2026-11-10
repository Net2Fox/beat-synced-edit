"""Decode fallback for sources that OpenCV's bundled FFmpeg cannot read.

The opencv-python wheels ship an FFmpeg without a software AV1 decoder (only
the hardware-accelerated ``av1`` wrapper), so ``cv2.VideoCapture`` opens an
AV1 WebM/MP4 but never returns a frame. Rendering is unaffected because it
decodes with the system ``ffmpeg``; analysis (scene detection, thumbnails) and
subject tracking are not. ``decodable_path`` returns the source itself when
OpenCV can read it, otherwise a cached H.264 proxy made with the system
``ffmpeg``. The proxy keeps every frame and its timestamp (constant and
variable frame rate), is at most 540 px high, is used only for measurements
and thumbnails, and never replaces the source in a project.

Proxies live in a per-user cache shared by all projects (the folder that also
holds the speech models, ``.../beat-sync-edit/decode-proxies``);
``BEAT_SYNC_PROXY_DIR`` moves it. They are safe to delete: a proxy unused for
``PROXY_MAX_AGE_DAYS`` is removed the next time another one is built.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

import cv2

# Part of every proxy name and of the analysis-cache identity. Change it with
# the FFmpeg arguments below, so proxies and measurements made by an older
# recipe are not reused.
PROXY_RECIPE = "h264-540p-every-frame-source-timestamps-2"
PROXY_MAX_AGE_DAYS = 30
# The only names this module writes: "<20 hex>.mp4" and, while building, "<20 hex>.<pid>.partial.mp4".
_OWN_NAME = re.compile(r"[0-9a-f]{20}(\.\d+)?(\.partial)?\.mp4")
_CHECKED = {}


def _opencv_can_decode(path):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return False
        ok, frame = capture.read()
        return bool(ok and frame is not None)
    finally:
        capture.release()


def _candidates():
    root = os.environ.get("BEAT_SYNC_PROXY_DIR")
    if root:
        yield Path(root).expanduser()
    try:
        from speech_transcribe import _user_cache_dir  # standard library only at import time
        yield _user_cache_dir() / "beat-sync-edit" / "decode-proxies"
    except RuntimeError:  # the home directory cannot be determined
        pass
    yield Path(tempfile.gettempdir()) / "beat-sync-edit-decode-proxies"


def _proxy_dir():
    for folder in _candidates():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            # An existing folder can still be read-only (agent sandbox, another user's folder).
            with tempfile.TemporaryFile(dir=folder):
                pass
            return folder.resolve()
        except OSError:
            continue
    raise OSError("No writable folder for decode proxies; set BEAT_SYNC_PROXY_DIR to one")


def _prune(folder, keep):
    """Remove proxies unused for PROXY_MAX_AGE_DAYS and builds abandoned more than a day ago.

    BEAT_SYNC_PROXY_DIR may point at a folder that holds other things, even the
    footage itself, so only files named by this module are ever deleted.
    """
    now = time.time()
    for path in folder.glob("*.mp4"):
        if path == keep or not _OWN_NAME.fullmatch(path.name):
            continue
        try:
            limit = 1 if path.name.endswith(".partial.mp4") else PROXY_MAX_AGE_DAYS
            if now - path.stat().st_mtime > limit * 86400:
                path.unlink()
        except OSError:
            continue


def _build(source, proxy):
    """Encode the proxy under a private name and publish it atomically.

    The final name only ever points at a finished file, so two runs that need
    the same proxy at the same time cannot read each other's half-written one.
    """
    partial = proxy.with_name(f"{proxy.stem}.{os.getpid()}.partial.mp4")
    head = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(source), "-map", "0:v:0", "-an",
            # Even width and height (libx264 needs both), never upscaled.
            "-vf", "scale=-2:'2*trunc(min(540,ih)/2)'"]
    tail = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-f", "mp4", str(partial)]
    # Keep every frame on the source's own timestamps, also for variable frame rate. The options
    # were renamed over time: "-fps_mode" replaced "-vsync" in FFmpeg 5.1 (9.0 dropped "-vsync"),
    # and the source time base is "demux" since 6.1 and "-1" before (9.0 rejects "-1").
    sync, time_base = ["-fps_mode", "passthrough"], "demux"
    try:
        while True:
            try:
                result = subprocess.run(head + sync + ["-enc_time_base", time_base] + tail, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace")
            except OSError as exc:
                raise RuntimeError(f"OpenCV cannot decode {source} and FFmpeg could not be started "
                                   f"to read it instead: {exc}") from exc
            detail = (result.stderr or "").strip()[-2000:]
            if result.returncode == 0 and partial.is_file() and partial.stat().st_size > 0:
                break
            if sync[0] == "-fps_mode" and "fps_mode" in detail and "nrecognized option" in detail:
                sync, time_base = ["-vsync", "0"], "-1"      # FFmpeg older than 5.1
            elif time_base == "demux" and "Invalid time base" in detail:
                time_base = "-1"                              # FFmpeg 5.1 to 6.0
            else:
                raise RuntimeError(f"Cannot decode video with OpenCV or FFmpeg: {source}\n{detail}")
        if not _opencv_can_decode(partial):
            raise ValueError(f"Cannot decode video: {source}")
        try:
            os.replace(partial, proxy)
        except OSError:
            # Another run published the same proxy first and has it open (Windows): use that one.
            if not _opencv_can_decode(proxy):
                raise
    finally:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass


def decodable_path(path):
    """Return a path OpenCV can decode: the source, or a cached H.264 proxy."""
    source = Path(path).resolve(strict=True)
    stat = source.stat()
    key = (str(source), stat.st_size, stat.st_mtime_ns)
    known = _CHECKED.get(key)
    if known and Path(known).is_file():
        return known
    if _opencv_can_decode(source):
        _CHECKED[key] = str(source)
        return _CHECKED[key]
    folder = _proxy_dir()
    digest = hashlib.sha256(repr((key, PROXY_RECIPE)).encode("utf-8")).hexdigest()[:20]
    proxy = folder / f"{digest}.mp4"
    for _ in range(2):
        try:
            ready = proxy.is_file() and proxy.stat().st_size > 0 and _opencv_can_decode(proxy)
        except OSError:
            ready = False
        if not ready:
            _build(source, proxy)
            _prune(folder, proxy)
        try:
            os.utime(proxy)  # mark as used, so pruning keeps it
        except FileNotFoundError:
            continue         # another run pruned it between the check and now: build it again
        except OSError:
            pass
        break
    _CHECKED[key] = str(proxy)
    return _CHECKED[key]

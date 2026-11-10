"""Decode fallback for sources that OpenCV's bundled FFmpeg cannot read.

The opencv-python wheels ship an FFmpeg without a software AV1 decoder (only
the hardware-accelerated ``av1`` wrapper), so ``cv2.VideoCapture`` opens an
AV1 WebM/MP4 but never returns a frame. Rendering is unaffected because it
decodes with the system ``ffmpeg``; analysis (scene detection, thumbnails) and
subject tracking are not. ``decodable_path`` returns the source itself when
OpenCV can read it, otherwise a cached, frame-for-frame H.264 proxy made with
the system ``ffmpeg``. The proxy keeps frame rate, frame count and timestamps,
is used only for measurements and thumbnails, and never replaces the source in
a project.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import cv2

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


def _proxy_dir():
    root = os.environ.get("BEAT_SYNC_PROXY_DIR")
    candidates = [Path(root)] if root else []
    candidates += [Path.home() / ".cache" / "beat-sync-edit" / "decode-proxies",
                   Path(tempfile.gettempdir()) / "beat-sync-edit-decode-proxies"]
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        except OSError:
            continue
    raise OSError("No writable folder for decode proxies")


def decodable_path(path):
    """Return a path OpenCV can decode: the source, or a cached H.264 proxy."""
    source = Path(path).resolve(strict=True)
    stat = source.stat()
    key = (str(source), stat.st_size, stat.st_mtime_ns)
    if key in _CHECKED:
        return _CHECKED[key]
    if _opencv_can_decode(source):
        _CHECKED[key] = str(source)
        return _CHECKED[key]
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:20]
    proxy = _proxy_dir() / f"{digest}.mp4"
    if not (proxy.is_file() and proxy.stat().st_size > 0 and _opencv_can_decode(proxy)):
        partial = proxy.with_suffix(".partial.mp4")
        # Same frames and timestamps, at most 540 px high (thumbnails and
        # tracking work on smaller images anyway), no audio.
        result = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(source), "-map", "0:v:0", "-an",
            "-vf", "scale=-2:'min(540,ih)'", "-fps_mode", "passthrough",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(partial)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not partial.is_file():
            partial.unlink(missing_ok=True)
            raise ValueError(f"Cannot decode video with OpenCV or FFmpeg: {source}\n{result.stderr.strip()}")
        os.replace(partial, proxy)
        if not _opencv_can_decode(proxy):
            raise ValueError(f"Cannot decode video: {source}")
    _CHECKED[key] = str(proxy)
    return _CHECKED[key]

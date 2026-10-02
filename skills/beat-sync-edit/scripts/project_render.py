#!/usr/bin/env python3
"""Frame-exact project renderer with smooth retiming and reusable shot caches.

The project is a JSON version-2 plan. FFmpeg handles oriented, square-pixel
decoding and H.264/AAC encoding; NumPy/OpenCV handle retiming, tracking crops
and effects. Explicitly authorized slow motion uses optical-flow interpolation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

import cv2
import numpy as np

from text_overlay import TextCompositor, validate_text_tracks

RENDER_VERSION = 2


def _run(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed:\n{result.stderr[-4000:]}")
    return result.stdout


def probe(path, count_frames=False):
    args = ["ffprobe", "-v", "error"]
    if count_frames:
        args += ["-count_frames"]
    args += ["-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(_run(args))


def _positive_float(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _integer(value, name):
    numeric = float(value)
    if not math.isfinite(numeric) or int(numeric) != numeric:
        raise ValueError(f"{name} must be an integer")
    return int(numeric)


def _ratio(value, default=1.0):
    try:
        a, b = str(value).replace(":", "/").split("/")
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return default


def _integrated_speed(points, positions):
    """Integrate a positive curve with zero slope at every control point."""
    if not points:
        points = [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]
    points = sorted((float(p["at"]), _positive_float(p["speed"], "speed")) for p in points)
    if any(not math.isfinite(p[0]) or not 0 <= p[0] <= 1 for p in points):
        raise ValueError("Speed point positions must be between 0 and 1")
    if any(a[0] == b[0] for a, b in zip(points, points[1:])):
        raise ValueError("Speed point positions must be unique")
    if points[0][0] > 0:
        points.insert(0, (0, points[0][1]))
    if points[-1][0] < 1:
        points.append((1, points[-1][1]))
    values = np.zeros_like(positions, dtype=np.float64)
    total = 0.0
    for (a, sa), (b, sb) in zip(points, points[1:]):
        width = b - a
        x = np.clip(positions - a, 0, width)
        values += sa * x + (sb - sa) * (x / 2 - width * np.sin(np.pi * x / width) / (2 * np.pi))
        total += width * (sa + sb) / 2
    if total <= 0:
        raise ValueError("Speed curve must span a positive interval")
    return values / total


def _anchor_warp(progress, at, target):
    """Monotone C1 interpolation of (0,0), (at,target), (1,1)."""
    left = target / at
    right = (1 - target) / (1 - at)
    middle = 2 * left * right / (left + right)
    result = np.empty_like(progress)
    for mask, x0, x1, y0, y1, m0, m1 in (
        (progress <= at, 0, at, 0, target, left, middle),
        (progress > at, at, 1, target, 1, middle, right),
    ):
        t = (progress[mask] - x0) / (x1 - x0)
        result[mask] = ((2*t**3 - 3*t**2 + 1)*y0 + (t**3 - 2*t**2 + t)*(x1-x0)*m0
                        + (-2*t**3 + 3*t**2)*y1 + (t**3-t**2)*(x1-x0)*m1)
    return result


def source_times(edit, positions):
    """Map normalized output times to absolute source seconds, including an anchor.

    Speed points are relative speed weights; the integral is scaled to exactly
    consume the selected source span. Anchoring smoothly redistributes that span
    and guarantees the action's source_time at its output_fraction.
    """
    positions = np.asarray(positions, dtype=np.float64)
    if np.any(~np.isfinite(positions)) or np.any((positions < 0) | (positions > 1)):
        raise ValueError("Output positions must be between 0 and 1")
    start, end = float(edit.get("source_start", 0)), float(edit.get("source_end", 0))
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Video source_start/source_end must form a positive finite span")
    points = edit.get("speed_points")
    progress = _integrated_speed(points, positions)
    anchor = edit.get("action_anchor")
    if anchor:
        fraction = float(anchor["output_fraction"])
        target = (float(anchor["source_time"]) - start) / (end - start)
        if not math.isfinite(fraction) or not math.isfinite(target):
            raise ValueError("Action anchor must be finite")
        if fraction in (0, 1) and abs(target - fraction) < 1e-8:
            pass
        elif 0 < fraction < 1 and 0 < target < 1:
            at = float(_integrated_speed(points, np.array([fraction]))[0])
            progress = _anchor_warp(progress, at, target)
        else:
            raise ValueError("An interior action anchor must lie inside the selected source span")
    return start + (end - start) * progress


def _display_size(stream):
    sar = _ratio(stream.get("sample_aspect_ratio", "1:1"))
    if sar <= 0:
        sar = 1
    w, h = int(round(int(stream["width"]) * sar)), int(stream["height"])
    rotations = [x.get("rotation", 0) for x in stream.get("side_data_list", [])]
    angle = float(rotations[0] if rotations else stream.get("tags", {}).get("rotate", 0))
    if round(angle / 90) % 2:
        w, h = h, w
    return max(2, w), max(2, h)


class _OpticalFlowPair:
    """Bidirectional motion interpolation, with one flow estimate per frame pair.

    Estimate motion at a bounded resolution, then warp the original-resolution
    frames. Both endpoints are brought to the intermediate time before blending;
    this is motion interpolation rather than a crossfade of stationary frames.
    """

    def __init__(self, first, second, max_dimension=640):
        if first.shape != second.shape or first.ndim != 3:
            raise ValueError("Optical-flow endpoints must have matching image dimensions")
        self.first, self.second = first, second
        height, width = first.shape[:2]
        factor = min(1, max_dimension / max(height, width))
        size = (max(2, round(width * factor)), max(2, round(height * factor)))
        gray = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in (first, second)]
        if size != (width, height):
            gray = [cv2.resize(frame, size, interpolation=cv2.INTER_AREA) for frame in gray]
        try:
            fields = [cv2.calcOpticalFlowFarneback(a, b, None, .5, 5, 25, 5, 7, 1.5, 0)
                      for a, b in ((gray[0], gray[1]), (gray[1], gray[0]))]
        except cv2.error as exc:
            raise RuntimeError(f"Optical-flow interpolation failed: {exc}") from exc
        self.flows = []
        for flow in fields:
            if flow is None or flow.shape != (*gray[0].shape, 2) or not np.isfinite(flow).all():
                raise RuntimeError("Optical-flow interpolation returned an invalid motion field")
            if size != (width, height):
                flow = cv2.resize(flow, (width, height), interpolation=cv2.INTER_LINEAR)
                flow[..., 0] *= width / size[0]
                flow[..., 1] *= height / size[1]
            self.flows.append(flow)
        self.grid_x, self.grid_y = np.meshgrid(np.arange(width, dtype=np.float32),
                                              np.arange(height, dtype=np.float32))

    def _warp(self, frame, flow, fraction):
        # Invert the forward displacement with fixed-point refinement. Sampling
        # flow at the unwarped target alone leaves moving object edges behind.
        map_x, map_y = self.grid_x - fraction*flow[..., 0], self.grid_y - fraction*flow[..., 1]
        for _ in range(3):
            sampled = cv2.remap(flow, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            map_x = self.grid_x - fraction*sampled[..., 0]
            map_y = self.grid_y - fraction*sampled[..., 1]
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def frame(self, fraction):
        if not math.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("Interpolation fraction must be between zero and one")
        if fraction == 0:
            return self.first.copy()
        if fraction == 1:
            return self.second.copy()
        try:
            earlier = self._warp(self.first, self.flows[0], fraction)
            later = self._warp(self.second, self.flows[1], 1-fraction)
            return cv2.addWeighted(earlier, 1-fraction, later, fraction, 0)
        except cv2.error as exc:
            raise RuntimeError(f"Optical-flow interpolation failed: {exc}") from exc


class _VideoReader:
    """Sequential fixed-rate FFmpeg decoder; keeps only two source frames in RAM."""

    def __init__(self, path, start, end, stream, interpolation="none"):
        if interpolation not in ("none", "optical_flow"):
            raise ValueError("Interpolation must be none or optical_flow")
        self.interpolation = interpolation
        self.flow_pair = None
        self.w, self.h = _display_size(stream)
        self.fps = min(120.0, max(1.0, _ratio(stream.get("avg_frame_rate"), 30)))
        self.start = start
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen([
            "ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-ss", f"{start:.9f}", "-i", str(path),
            "-t", f"{end-start+2/self.fps:.9f}", "-an", "-sn", "-dn", "-vf",
            f"scale={self.w}:{self.h},setsar=1,fps={self.fps:.9f}", "-threads", "1", "-f", "rawvideo",
            "-pix_fmt", "bgr24", "pipe:1"], stdout=subprocess.PIPE, stderr=self.log)
        self.index = 0
        self.first = self._read()
        if self.first is None:
            self.close()
            raise ValueError(f"No decodable frames in {path}")
        self.second = self._read()

    def _read(self):
        size = self.w * self.h * 3
        data = self.process.stdout.read(size)
        if not data:
            return None
        if len(data) != size:
            raise RuntimeError("Incomplete decoded video frame")
        return np.frombuffer(data, np.uint8).reshape(self.h, self.w, 3)

    def frame(self, time):
        position = max(0, (time - self.start) * self.fps)
        wanted = int(math.floor(position))
        while self.index < wanted and self.second is not None:
            self.first, self.second = self.second, self._read()
            self.index += 1
            self.flow_pair = None
        fraction = position - self.index
        if self.second is None:
            if self.interpolation == "optical_flow" and fraction > 1e-7:
                raise RuntimeError("Optical-flow interpolation needs a following source frame; "
                                   "trim source_end before the final native frame")
            return self.first.copy()
        if self.interpolation == "optical_flow":
            if fraction < 1e-7:
                return self.first.copy()
            if self.flow_pair is None:
                self.flow_pair = _OpticalFlowPair(self.first, self.second)
            return self.flow_pair.frame(fraction)
        return cv2.addWeighted(self.first, 1-fraction, self.second, fraction, 0)

    def close(self):
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait()
        self.log.close()


def _read_image(path):
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        return cv2.cvtColor(np.asarray(ImageOps.exif_transpose(image).convert("RGB")), cv2.COLOR_RGB2BGR)


def _effect_frame(frame, effects, index, count, fps):
    """Effects are contained in each shot and never alter its frame count."""
    grade = effects.get("grade", "none")
    arr = frame.astype(np.float32) / 255
    if grade == "warm":
        arr *= np.array([.96, 1.01, 1.06], np.float32)
    elif grade == "cool":
        arr *= np.array([1.08, 1.01, .97], np.float32)
    elif grade == "vivid":
        gray = np.sum(arr * np.array([.114, .587, .299]), axis=2, keepdims=True)
        arr = (gray + (arr-gray)*1.22 - .5)*1.07 + .5
    elif grade == "cinematic":
        gray = np.sum(arr * np.array([.114, .587, .299]), axis=2, keepdims=True)
        arr = (gray + (arr-gray)*.86 - .5)*1.12 + .51
        arr[..., 0] += .025*(1-arr[..., 0])
        arr[..., 2] += .02*arr[..., 2]
    elif grade not in ("none", "neutral", None):
        raise ValueError(f"Unknown color grade: {grade}")
    flash = float(effects.get("flash", 0))
    # 80 ms fade from white: a transition on this cut, with no overlap shortening.
    amount = flash * max(0, 1-index/max(1, fps*.08))
    arr = arr*(1-amount) + amount
    return (np.clip(arr, 0, 1)*255).astype(np.uint8)


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_cache_value(value):
    """Give numerically equivalent JSON plans identical cache signatures.

    User revisions commonly replace 0.0 with 0. Numeric spelling is not a
    rendering change. Keep booleans distinct, and reject nonfinite numbers
    rather than creating unstable JSON keys.
    """
    if isinstance(value, dict):
        return {key: _canonical_cache_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_cache_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Cache settings must contain finite numbers")
        return int(value) if value.is_integer() else value
    return value


def _center(track, source_time, reframe):
    if reframe.get("mode") in ("center", "contain"):
        return .5, .5
    subject = reframe.get("subject")
    if track:
        times = [p["time"] for p in track]
        return (float(np.interp(source_time, times, [p["cx"] for p in track])),
                float(np.interp(source_time, times, [p["cy"] for p in track])))
    if subject is not None:
        x, y, w, h = map(float, subject)
        return x+w/2, y+h/2
    return .5, .5


def _render_shot(edit, output, width, height, fps, preview, media, interpolation="none"):
    from smart_reframe import crop_frame, track_subject
    count = int(edit["duration_frames"])
    source = Path(edit["source"])
    reframe = edit.get("reframe", {})
    kind = edit.get("kind", "video")
    start, end = float(edit.get("source_start", 0)), float(edit.get("source_end", 0))
    reader = None
    track = []
    if kind == "image":
        image = _read_image(source)
        times = np.zeros(count)
        if reframe.get("mode", "auto") == "auto":
            track = track_subject(str(source), 0, 0, subject=reframe.get("subject"), sample_fps=5)
    else:
        times = source_times(edit, np.arange(count, dtype=float)/count)
        stream = next(s for s in media["streams"] if s["codec_type"] == "video")
        duration = float(stream.get("duration") or media["format"].get("duration", 0))
        if start < 0 or end > duration + 1/max(1, _ratio(stream.get("avg_frame_rate"), 30)):
            raise ValueError(f"Source span {start}–{end} exceeds {source.name} ({duration}s)")
        if reframe.get("mode", "auto") == "auto":
            subject_start = float(reframe.get("subject_start", start)) if reframe.get("subject") else start
            if not math.isfinite(subject_start) or not 0 <= subject_start <= start:
                raise ValueError("reframe.subject_start must be between zero and source_start")
            track = track_subject(str(source), subject_start, end, subject=reframe.get("subject"), sample_fps=5)
        reader = _VideoReader(source, start, end, stream, interpolation=interpolation)
    effects = edit.get("effects", {})
    zoom = _positive_float(effects.get("zoom", 1), "zoom")
    if zoom < 1:
        raise ValueError("Zoom must be at least 1")
    shake = float(effects.get("shake", 0))
    flash = float(effects.get("flash", 0))
    if not 0 <= shake <= 1 or not 0 <= flash <= 1:
        raise ValueError("Flash and shake strengths must be between 0 and 1")
    with tempfile.TemporaryFile() as log:
        encoder = subprocess.Popen([
            "ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s:v", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-an", "-frames:v", str(count),
            "-c:v", "libx264", "-preset", "ultrafast" if preview else "fast", "-crf", "27" if preview else "18",
            "-pix_fmt", "yuv420p", "-vf", "setsar=1", "-video_track_timescale", str(fps*1000),
            "-movflags", "+faststart", str(output)], stdin=subprocess.PIPE, stderr=log)
        try:
            for i, source_time in enumerate(times):
                frame = image if kind == "image" else reader.frame(float(source_time))
                cx, cy = _center(track, source_time, reframe)
                # A quick punch decays over 180 ms. Still-image zoom grows gently.
                if kind == "image":
                    amount = 1+(zoom-1)*(i/max(1, count-1))
                else:
                    amount = 1+(zoom-1)*max(0, 1-i/max(1, fps*.18))**2
                amount += shake*.025
                t = i/fps
                cx += shake*.012*math.sin(t*43)
                cy += shake*.012*math.cos(t*37)
                if amount > 1:
                    fh, fw = frame.shape[:2]
                    zw, zh = max(2, int(fw/amount)), max(2, int(fh/amount))
                    x = int(np.clip(cx*fw-zw/2, 0, fw-zw))
                    y = int(np.clip(cy*fh-zh/2, 0, fh-zh))
                    frame = frame[y:y+zh, x:x+zw]
                    cx, cy = ((cx*fw-x)/zw, (cy*fh-y)/zh)
                fit = "contain" if reframe.get("mode") == "contain" else reframe.get("fit", "cover")
                frame = crop_frame(frame, width, height, center=(cx, cy), fit=fit)
                frame = _effect_frame(frame, effects, i, count, fps)
                encoder.stdin.write(np.ascontiguousarray(frame).tobytes())
            encoder.stdin.close()
            code = encoder.wait()
            if code:
                log.seek(0)
                raise RuntimeError(log.read().decode("utf-8", "replace"))
        except Exception:
            if encoder.stdin and not encoder.stdin.closed:
                encoder.stdin.close()
            if encoder.poll() is None:
                encoder.terminate()
            encoder.wait()
            raise
        finally:
            if reader:
                reader.close()


def _validate_plan(plan):
    version = plan.get("schema_version", plan.get("version", 2))
    if version not in (2, "2"):
        raise ValueError("Expected a version-2 project plan")
    output = plan.get("output", {})
    width, height, fps = (_integer(output.get(k, d), k) for k, d in (("width", 1080), ("height", 1920), ("fps", 30)))
    if min(width, height) < 2 or width % 2 or height % 2 or not 1 <= fps <= 120:
        raise ValueError("Output dimensions must be positive even integers; fps must be 1–120")
    edits = plan.get("edits", [])
    if not edits:
        raise ValueError("The plan has no edits")
    cursor = 0
    for edit in edits:
        count = _integer(edit["duration_frames"], "duration_frames")
        if count <= 0:
            raise ValueError("Every edit needs a positive frame count")
        if _integer(edit.get("timeline_start_frame", cursor), "timeline_start_frame") != cursor:
            raise ValueError("Edit timeline contains an overlap or gap")
        cursor += count
        if _integer(edit.get("timeline_end_frame", cursor), "timeline_end_frame") != cursor:
            raise ValueError("Edit timeline end does not match duration_frames")
        path = Path(edit["source"])
        if not path.is_absolute() or not path.is_file():
            raise FileNotFoundError(f"Source must be an existing absolute file: {path}")
        if edit.get("kind", "video") not in ("video", "image"):
            raise ValueError("Edit kind must be video or image")
        reframe = edit.get("reframe", {})
        if reframe.get("mode", "auto") not in ("auto", "manual", "center", "contain"):
            raise ValueError("Reframe mode must be auto, manual, center or contain")
        subject = reframe.get("subject")
        if subject is not None:
            if len(subject) != 4 or any(not math.isfinite(float(x)) for x in subject):
                raise ValueError("Subject must be normalized [x,y,width,height]")
            x, y, w, h = map(float, subject)
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1.000001 or y+h > 1.000001:
                raise ValueError("Subject box must fit inside the normalized frame")
    if cursor != _integer(plan["duration_frames"], "duration_frames"):
        raise ValueError("Edit durations do not sum to the requested duration_frames")
    # This entry point also accepts minimal hand-authored plans. Never rely on
    # the planner/CLI having checked authorization or hidden ramp/anchor slows.
    from project_plan import validate_slow_motion_policy
    validate_slow_motion_policy(plan)
    validate_text_tracks(plan)
    return width, height, fps, cursor


def _composite_tracks(manifest, output, compositor, width, height, fps, count, preview):
    """Burn text after cached shots, so changing a caption never rerenders shots."""
    with tempfile.TemporaryFile() as decode_log, tempfile.TemporaryFile() as encode_log:
        decoder = subprocess.Popen([
            "ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-f", "concat", "-safe", "0",
            "-i", str(manifest), "-an", "-sn", "-dn", "-vsync", "0", "-threads", "1",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], stdout=subprocess.PIPE, stderr=decode_log)
        encoder = None
        try:
            encoder = subprocess.Popen([
                "ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s:v", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-an", "-frames:v", str(count),
                "-c:v", "libx264", "-preset", "ultrafast" if preview else "fast", "-crf", "27" if preview else "18",
                "-pix_fmt", "yuv420p", "-vf", "setsar=1", "-video_track_timescale", str(fps*1000),
                "-movflags", "+faststart", str(output)], stdin=subprocess.PIPE, stderr=encode_log)
            size = width*height*3
            for index in range(count):
                data = decoder.stdout.read(size)
                if len(data) != size:
                    raise RuntimeError(f"Text assembly decoded only {index} complete frames; expected {count}")
                frame = np.frombuffer(data, np.uint8).reshape(height, width, 3)
                composed = compositor.apply(frame, index)
                encoder.stdin.write(np.ascontiguousarray(composed).tobytes())
            if decoder.stdout.read(1):
                raise RuntimeError("Text assembly decoded more frames than the project timeline")
            decoder.stdout.close()
            encoder.stdin.close()
            for process, log, label in ((decoder, decode_log, "decode"), (encoder, encode_log, "encode")):
                if process.wait():
                    log.seek(0)
                    raise RuntimeError(f"Text assembly {label} failed: {log.read().decode('utf-8', 'replace')[-4000:]}")
        finally:
            for process in (decoder, encoder):
                if process is None:
                    continue
                for stream in (process.stdin, process.stdout):
                    if stream is not None and not stream.closed:
                        stream.close()
                if process.poll() is None:
                    process.terminate()
                process.wait()


def render_project(plan, output_path, preview=False, cache_dir=None):
    """Render a validated plan and return independently probed output metadata."""
    if isinstance(plan, (str, Path)):
        plan = json.loads(Path(plan).read_text(encoding="utf-8"))
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is required on PATH")
    width, height, fps, total_frames = _validate_plan(plan)
    if preview:
        # Keep the exact aspect ratio when its integer representation fits an
        # even-pixel H.264 frame (e.g. 352x198 for a horizontal 16:9 preview).
        divisor = math.gcd(width, height)
        unit_w, unit_h = width//divisor, height//divisor
        multiplier = min(divisor, 360//unit_w, 640//unit_h)
        if unit_w % 2 or unit_h % 2:
            multiplier -= multiplier % 2
        if multiplier > 0:
            width, height = unit_w*multiplier, unit_h*multiplier
        else:  # Unusual relatively-prime aspect ratios require pixel rounding.
            factor = min(1, 360/width, 640/height)
            width, height = max(2, int(width*factor)//2*2), max(2, int(height*factor)//2*2)
    compositor = TextCompositor(plan, width, height) if plan.get("titles") or plan.get("subtitles") else None
    duration = total_frames/fps
    output_path = Path(output_path).resolve()
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("Output must be an .mp4 file")
    if output_path in [Path(e["source"]).resolve() for e in plan["edits"]]:
        raise ValueError("Output cannot overwrite a source")
    audio = plan.get("audio") or {}
    audio_path = Path(audio.get("path", ""))
    if not audio_path.is_absolute() or not audio_path.is_file():
        raise FileNotFoundError("Plan audio.path must be an existing absolute file")
    if output_path == audio_path.resolve():
        raise ValueError("Output cannot overwrite the soundtrack")
    audio_info = probe(audio_path)
    audio_stream = next((s for s in audio_info["streams"] if s["codec_type"] == "audio"), None)
    if audio_stream is None:
        raise ValueError("The soundtrack has no audio stream")
    audio_duration = float(audio_stream.get("duration") or audio_info["format"].get("duration", 0))
    audio_start = float(audio.get("start", 0))
    if not math.isfinite(audio_start) or not 0 <= audio_start < audio_duration:
        raise ValueError("Soundtrack start is outside the available audio")
    if not audio.get("loop", False) and audio_start+duration > audio_duration+.002:
        raise ValueError("The soundtrack is shorter than the edit; choose an earlier start or explicitly enable audio.loop")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir).resolve() if cache_dir else output_path.parent/".beat-sync-cache"
    cache.mkdir(parents=True, exist_ok=True)
    shots, hashes, media_by_path = [], {}, {}
    cache_hits = 0
    from project_plan import speed_bounds
    for edit in plan["edits"]:
        path = str(Path(edit["source"]).resolve())
        if path not in hashes:
            hashes[path] = _file_digest(path)
            media_by_path[path] = probe(path) if edit.get("kind", "video") == "video" else {}
        interpolation = ("optical_flow" if edit.get("kind", "video") == "video"
                         and speed_bounds(edit, edit["duration_frames"]/fps)[0] < 1-1e-5 else "none")
        signature = {k: edit.get(k) for k in ("kind", "source_start", "source_end", "duration_frames", "effects", "speed_points", "reframe", "action_anchor")}
        signature["interpolation"] = interpolation
        signature.update(renderer=RENDER_VERSION, source_sha256=hashes[path], width=width, height=height, fps=fps, preview=bool(preview))
        key = hashlib.sha256(json.dumps(_canonical_cache_value(signature), sort_keys=True,
                                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        shot = cache/f"{key}.mp4"
        valid = False
        if shot.is_file():
            try:
                info = probe(shot, count_frames=True)
                video = next(s for s in info["streams"] if s["codec_type"] == "video")
                valid = (int(video["nb_read_frames"]) == int(edit["duration_frames"])
                         and video["width"] == width and video["height"] == height
                         and abs(_ratio(video["avg_frame_rate"])-fps) < .001)
            except (RuntimeError, ValueError, KeyError, StopIteration):
                valid = False
        if valid:
            cache_hits += 1
        else:
            temporary = cache/f"{key}.{uuid.uuid4().hex}.tmp.mp4"
            try:
                _render_shot(edit, temporary, width, height, fps, preview, media_by_path[path], interpolation=interpolation)
                os.replace(temporary, shot)
            finally:
                temporary.unlink(missing_ok=True)
        shots.append(shot)
    with tempfile.TemporaryDirectory(prefix="assemble-", dir=cache) as scratch:
        manifest = Path(scratch)/"shots.txt"
        manifest.write_text("".join("file '"+p.as_posix().replace("'", "'\\''")+"'\n" for p in shots), encoding="utf-8")
        temporary = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.tmp.mp4")
        try:
            args = ["ffmpeg", "-y", "-v", "error", "-nostdin"]
            if compositor is not None:
                composed = Path(scratch)/"composited.mp4"
                _composite_tracks(manifest, composed, compositor, width, height, fps, total_frames, preview)
                args += ["-i", str(composed)]
            else:
                args += ["-f", "concat", "-safe", "0", "-i", str(manifest)]
            if audio.get("loop", False):
                args += ["-stream_loop", "-1"]
            args += ["-ss", f"{audio_start:.9f}", "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "copy", "-af", f"atrim=duration={duration:.9f},asetpts=PTS-STARTPTS,aresample=48000",
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{duration:.9f}",
                     "-video_track_timescale", str(fps*1000), "-movflags", "+faststart", str(temporary)]
            _run(args)
            info = probe(temporary, count_frames=True)
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
            actual_frames = int(video["nb_read_frames"])
            actual_duration = float(video["duration"])
            if actual_frames != total_frames or abs(actual_duration-duration) > 1/(fps*100):
                raise RuntimeError(f"Render verification failed: expected {total_frames} frames/{duration}s, got {actual_frames}/{actual_duration}s")
            if abs(float(sound.get("duration", 0))-duration) > .05 or sound.get("sample_rate") != "48000":
                raise RuntimeError("Rendered soundtrack has an unexpected duration or sample rate")
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"path": str(output_path), "duration": actual_duration, "frames": actual_frames,
            "width": video["width"], "height": video["height"], "fps": fps, "audio": True,
            "audio_sample_rate": 48000, "preview": bool(preview), "cache_hits": cache_hits, "shots": len(shots)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    try:
        result = render_project(args.project, args.output, args.preview, args.cache_dir)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

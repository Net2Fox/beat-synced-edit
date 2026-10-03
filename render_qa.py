"""Inspect the encoded deliverable, retaining measured facts and review gaps."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont


def _run(args, timeout=1800):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def referenced_files(plan):
    """All supplied project file resources, including hidden B-roll audio/fonts."""
    result = set()

    def visit(value, key=None):
        if isinstance(value, dict):
            for name, item in value.items():
                visit(item, name)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, str) and key in {"source", "path", "font", "library", "beatmap", "project", "transcript", "words_path"}:
            path = Path(value)
            if path.is_absolute():
                result.add(path.resolve())
    visit(plan or {})
    return result


def guard_export_outputs(plan, video, output_dir=None, extra_protected=()):
    """Check automatically named reports/images before any export mutation."""
    video = Path(video).resolve()
    directory = Path(output_dir).resolve() if output_dir else video.parent
    protected = referenced_files(plan) | {Path(p).resolve() for p in extra_protected}
    named = {video, video.with_suffix(".audio.json"), video.with_suffix(".verification.json"), directory/f"{video.stem}.qa.json"}
    pattern = re.compile(re.escape(video.stem)+r"\.review-\d+\.png$", re.IGNORECASE)
    conflicts = protected & named
    conflicts.update(p for p in protected if p.parent == directory and pattern.fullmatch(p.name))
    if conflicts:
        raise ValueError(f"Export/report would overwrite an input: {sorted(str(p) for p in conflicts)}")


def _allowed(start, end, ranges):
    for interval in ranges:
        if start >= interval[0] - .06 and end <= interval[1] + .06:
            return True
    return False


def _intentional(plan, kind, duration):
    ranges = plan.get("qa", {}).get("intentional_" + kind, []) if plan else []
    if not isinstance(ranges, list):
        raise ValueError(f"qa.intentional_{kind} must be a list of [start,end] seconds")
    for pair in ranges:
        if not isinstance(pair, list) or len(pair) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pair) or not 0 <= pair[0] < pair[1] <= duration + .05:
            raise ValueError(f"Invalid qa.intentional_{kind} interval")
    return ranges


def contact_sheet(video, output, times, safe_area=None):
    """Read actual encoded frames; label source timestamps and optional safe area."""
    import cv2
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot inspect frames from {video}")
    columns, tile_w, tile_h = 3, 320, 220
    sheet = Image.new("RGB", (columns * tile_w, math.ceil(len(times) / columns) * tile_h), "#121822")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    observed = []
    try:
        for index, time in enumerate(times):
            capture.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Could not decode requested review frame at {time:.4f}s")
            picture = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            picture.thumbnail((tile_w - 12, tile_h - 30))
            x = (index % columns) * tile_w + (tile_w - picture.width) // 2
            y = (index // columns) * tile_h + 5
            sheet.paste(picture, (x, y))
            if safe_area:
                left, top, right, bottom = (safe_area.get(k, 0) for k in ("left", "top", "right", "bottom"))
                draw.rectangle((x + left * picture.width, y + top * picture.height,
                                x + (1 - right) * picture.width, y + (1 - bottom) * picture.height), outline="#FFCC55", width=2)
            draw.text(((index % columns) * tile_w + 8, (index // columns + 1) * tile_h - 22), f"{time:.3f} s", font=font, fill="white")
            observed.append(time)
    finally:
        capture.release()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return {"path": str(output), "timestamps": observed, "pixels_inspected_at_generation": False}


def verify_export(video, plan=None, output_dir=None, make_sheet=True, protected_paths=None):
    video = Path(video).resolve(strict=True)
    directory = Path(output_dir).resolve() if output_dir else video.parent
    # The encoded video itself may legitimately be listed as a reviewed asset;
    # only generated sidecars are written by this read/inspect operation.
    protected = referenced_files(plan) | {Path(p).resolve() for p in (protected_paths or [])}
    guard_export_outputs({}, video, directory, protected - {video})
    directory.mkdir(parents=True, exist_ok=True)
    metadata = _run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(video)])
    if metadata.returncode:
        raise RuntimeError(f"ffprobe failed: {metadata.stderr[-2000:]}")
    info = json.loads(metadata.stdout)
    picture = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    sound = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if picture is None:
        raise ValueError("Export has no video stream")
    duration = float(picture.get("duration", info["format"]["duration"]))
    numerator, denominator = picture.get("avg_frame_rate", "0/1").split("/")
    fps = float(numerator) / float(denominator)
    if not math.isfinite(duration) or duration <= 0 or fps <= 0:
        raise ValueError("Export has invalid duration or frame rate")
    checks = []

    def check(name, passed, observed, expected=None):
        checks.append({"name": name, "status": "pass" if passed else "fail", "observed": observed, "expected": expected})

    check("codec", picture.get("codec_name") == "h264", picture.get("codec_name"), "h264")
    check("pixel_format", picture.get("pix_fmt") == "yuv420p", picture.get("pix_fmt"), "yuv420p")
    check("audio_present", sound is not None, sound is not None, True)
    frames = int(picture.get("nb_read_frames", 0))
    check("readable_frames", frames > 0, frames)
    if plan:
        expected = plan["output"]
        check("dimensions", (picture["width"], picture["height"]) == (expected["width"], expected["height"]), [picture["width"], picture["height"]], [expected["width"], expected["height"]])
        check("frame_count", frames == plan["duration_frames"], frames, plan["duration_frames"])
        check("fps", abs(fps - expected["fps"]) < .001, fps, expected["fps"])
        check("duration", abs(duration - plan["duration_frames"] / expected["fps"]) < 1 / expected["fps"] / 10, duration, plan["duration_frames"] / expected["fps"])
    if sound:
        audio_duration = float(sound.get("duration", duration))
        check("audio_duration", abs(audio_duration - duration) <= .08, audio_duration, duration)
        check("audio_sample_rate", int(sound.get("sample_rate", 0)) == 48000, sound.get("sample_rate"), "48000")
    measured_audio = None
    loudness_notes = []
    if sound:
        from audio_mix import measure_loudness
        targets = (plan or {}).get("audio_mix", {}).get("loudness", {})
        measured_audio = measure_loudness(video, targets)
        measured_audio["status"] = "measured" if measured_audio["measurable"] else "not_measurable"
        if measured_audio["true_peak_dbtp"] is not None and measured_audio["true_peak_dbtp"] >= 0:
            loudness_notes.append("Decoded true peak reaches or exceeds 0 dBTP; inspect possible clipping")
        if (plan or {}).get("audio_mix") and targets.get("enabled", True):
            if measured_audio["measurable"]:
                check("integrated_loudness", abs(measured_audio["integrated_lufs"]-targets.get("integrated", -16)) <= 1,
                      measured_audio["integrated_lufs"], targets.get("integrated", -16))
                check("true_peak", measured_audio["true_peak_dbtp"] <= targets.get("true_peak", -1.5)+.5,
                      measured_audio["true_peak_dbtp"], targets.get("true_peak", -1.5))
            else:
                intentional = _allowed(0, duration, _intentional(plan, "silence", duration))
                if not intentional:
                    loudness_notes.append("Integrated loudness is unmeasurable (silence or insufficient gated audio); no normalization compliance claim")
    decode = _run(["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"])
    check("full_decode", decode.returncode == 0, {"returncode": decode.returncode, "errors": decode.stderr[-2000:]})
    detection_args = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf", "blackdetect=d=0.08:pix_th=0.08"]
    if sound:
        detection_args += ["-af", "silencedetect=noise=-45dB:d=0.25"]
    detection = _run([*detection_args, "-f", "null", "-"])
    check("interval_detection", detection.returncode == 0, detection.returncode)
    black = [{"start": float(a), "end": float(b)} for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", detection.stderr)]
    silence = []
    pending = None
    for line in detection.stderr.splitlines():
        start = re.search(r"silence_start: ([\d.eE+-]+)", line)
        end = re.search(r"silence_end: ([\d.eE+-]+)", line)
        if start:
            pending = max(0, float(start.group(1)))
        if end and pending is not None:
            silence.append({"start": pending, "end": min(duration, float(end.group(1)))})
            pending = None
    if pending is not None:
        silence.append({"start": pending, "end": duration})
    for kind, ranges in (("black", black), ("silence", silence)):
        allowed = _intentional(plan, kind, duration)
        for interval in ranges:
            interval["intentional"] = _allowed(interval["start"], interval["end"], allowed)
    review = loudness_notes
    if any(not i["intentional"] for i in black):
        review.append("Inspect unexplained black intervals")
    if any(not i["intentional"] for i in silence):
        review.append("Inspect unexplained silent intervals")
    report = {"schema_version": "beat-sync.verification.v1", "path": str(video), "sha256": file_hash(video),
              "technical_pass": all(c["status"] == "pass" for c in checks), "checks": checks,
              "duration": duration, "frames": frames, "fps": fps, "width": picture["width"], "height": picture["height"],
              "black_intervals": black, "silent_intervals": silence, "review_notes": review,
              "audio_measurements": measured_audio,
              "visual_review": "not_reviewed", "editorial_review": "not_reviewed", "playback_review": "not_reviewed"}
    if make_sheet:
        times = {0.0, max(0, duration - 1 / fps), duration / 2}
        if plan:
            for shot in plan["edits"]:
                boundary = shot["timeline_start_frame"] / fps
                times.update([max(0, boundary - 1 / fps), boundary, min(duration - 1 / fps, boundary + 1 / fps)])
            for cue in plan.get("titles", []) + plan.get("subtitles", []) + plan.get("graphics", []):
                times.add((cue["start_frame"] + cue["end_frame"] - 1) / (2 * fps))
        else:
            times.update(duration * i / 6 for i in range(1, 6))
        times = sorted({round(min(duration - 1 / fps, max(0, t)), 6) for t in times})
        pages = []
        for index in range(0, len(times), 24):
            pages.append(contact_sheet(video, directory / f"{video.stem}.review-{index // 24 + 1:02}.png", times[index:index + 24],
                                       (plan or {}).get("style", {}).get("safe_area")))
        report["contact_sheets"] = pages
    from project_workspace import write_json
    path = directory / f"{video.stem}.qa.json"
    report["report"] = str(path)
    write_json(path, report)
    return report

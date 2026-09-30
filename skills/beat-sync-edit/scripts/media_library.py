#!/usr/bin/env python3
"""Persistent mixed-media ingestion and reviewable scene metadata.

Semantic annotations are supplied by the editor after viewing contact sheets.
The automatic pass measures image properties; it does not guess object labels.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import zipfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scenedetect import ContentDetector, detect


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".mts", ".m2ts"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
SHOT_TYPES = {"unknown", "wide", "establishing", "medium", "closeup", "close-up", "detail", "action"}


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_zip(path, work_dir, max_bytes=20 * 1024 ** 3):
    """Extract into a stable project folder, rejecting escapes and symlinks.

    Kept files remain available to later rendering sessions. Archives are keyed
    by content so importing a modified ZIP cannot silently reuse stale footage.
    """
    archive = Path(path).resolve(strict=True)
    target = Path(work_dir).resolve() / "imports" / _hash_file(archive)[:20]
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        total = 0
        destinations = set()
        validated = []
        for entry in entries:
            name = entry.filename.replace("\\", "/")
            member = PurePosixPath(name)
            # Windows drive names, ADS streams and device-name aliases must not
            # become valid filesystem targets even when checked on Linux.
            if member.is_absolute() or any(part in {"..", "."} or ":" in part for part in member.parts):
                raise ValueError(f"Unsafe ZIP member: {entry.filename}")
            if any(part.rstrip(" .") != part or part.split(".")[0].upper() in
                   {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                   for part in member.parts):
                raise ValueError(f"Unsafe ZIP member: {entry.filename}")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"ZIP symlinks are not supported: {entry.filename}")
            destination = target.joinpath(*member.parts).resolve()
            if not destination.is_relative_to(target) or destination == target:
                raise ValueError(f"Unsafe ZIP member: {entry.filename}")
            key = str(destination).casefold()
            if key in destinations and not entry.is_dir():
                raise ValueError(f"Duplicate ZIP destination: {entry.filename}")
            destinations.add(key)
            total += entry.file_size
            if total > max_bytes:
                raise ValueError(f"ZIP expands beyond the {max_bytes}-byte import limit")
            validated.append((entry, destination))
        # Validate the complete archive before writing any member.
        for entry, destination in validated:
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".importing")
            with zipped.open(entry) as source, temporary.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            temporary.replace(destination)
    return target


def discover_media(inputs, work_dir):
    """Resolve mixed files, recursively scanned folders and ZIPs exactly once."""
    found = {}
    for value in inputs:
        source = Path(value).expanduser().resolve(strict=True)
        candidates = sorted(source.rglob("*")) if source.is_dir() else [source]
        # Avoid recursively consuming this run's imports when work is nested
        # inside an input folder, without rejecting directly provided files.
        work = Path(work_dir).resolve()
        for candidate in candidates:
            if not candidate.is_file():
                continue
            candidate = candidate.resolve()
            if source.is_dir() and candidate.is_relative_to(work):
                continue
            if candidate.suffix.lower() == ".zip":
                extracted = extract_zip(candidate, work_dir)
                for item in sorted(extracted.rglob("*")):
                    if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS:
                        found[os.path.normcase(str(item.resolve()))] = item.resolve()
            elif candidate.suffix.lower() in MEDIA_EXTENSIONS:
                found[os.path.normcase(str(candidate))] = candidate
    if not found:
        raise ValueError("No supported image or video files were found")
    return list(found.values())


def load_image(path):
    """Read Unicode paths and apply EXIF orientation, returning BGR pixels."""
    with Image.open(path) as image:
        rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def probe_media(path):
    source = Path(path).resolve(strict=True)
    asset_id = "asset_" + hashlib.sha256(os.path.normcase(str(source)).encode("utf-8")).hexdigest()[:12]
    base = {"id": asset_id, "path": str(source)}
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        image = load_image(source)
        return {**base, "kind": "image", "duration": 0.0, "width": image.shape[1],
                "height": image.shape[0], "fps": 0.0, "rotation": 0, "has_audio": False}
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
                            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    data = json.loads(result.stdout)
    videos = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"
              and not stream.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise ValueError(f"No video stream: {source}")
    stream = videos[0]
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate", "0/1")
    numerator, denominator = (float(part) for part in rate.split("/")) if "/" in rate else (float(rate), 1)
    fps = numerator / denominator if denominator else 0.0
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    rotation = float(stream.get("tags", {}).get("rotate", 0))
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            rotation = float(side["rotation"])
    raw_width, raw_height = int(stream["width"]), int(stream["height"])
    rotated = int(round(rotation)) % 180 == 90
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Invalid video duration/frame rate: {source}")
    return {**base, "kind": "video", "duration": duration,
            "width": raw_height if rotated else raw_width, "height": raw_width if rotated else raw_height,
            "encoded_width": raw_width, "encoded_height": raw_height,
            "fps": fps, "rotation": rotation,
            "has_audio": any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))}


def _visual_hash(frame):
    gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (9, 8))
    bits = (gray[:, 1:] >= gray[:, :-1]).flatten()
    return f"{sum(int(bit) << index for index, bit in enumerate(bits)):016x}"


def _analyze_frames(frames):
    small = [cv2.GaussianBlur(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90)), (5, 5), 0)
             for frame in frames]
    motion = min(1.0, float(np.mean([np.mean(cv2.absdiff(a, b)) / 255 for a, b in zip(small, small[1:])])) / 0.15) if len(small) > 1 else 0.0
    brightness = float(np.mean([np.mean(frame) / 255 for frame in small]))
    return {"motion": round(motion, 4), "brightness": round(brightness, 4),
            "energy": round(motion * 0.8 + brightness * 0.2, 4),
            "visual_hash": _visual_hash(frames[len(frames) // 2])}


def _clips_for_asset(asset, thumb_dir):
    source = asset["path"]
    if asset["kind"] == "image":
        scenes = [(0.0, 0.0)]
        capture = None
        still = load_image(source)
    else:
        detected = detect(source, ContentDetector(threshold=27, min_scene_len=max(1, round(asset["fps"] * .25))))
        scenes = [(a.get_seconds(), b.get_seconds()) for a, b in detected] or [(0.0, asset["duration"])]
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise ValueError(f"Cannot decode video: {source}")
    clips = []
    try:
        for index, (start, end) in enumerate(scenes):
            end = min(end, asset["duration"]) if asset["kind"] == "video" else end
            if capture is None:
                frames = [still]
                sampled_times = [0.0]
            else:
                frames = []
                sampled_times = []
                last = max(start, end - 1 / asset["fps"])
                for time in np.linspace(start, last, 7):
                    capture.set(cv2.CAP_PROP_POS_MSEC, float(time * 1000))
                    ok, frame = capture.read()
                    if ok:
                        frames.append(frame)
                        decoded_time = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                        if not math.isfinite(decoded_time) or (decoded_time == 0 and time > 1 / asset["fps"]):
                            decoded_time = max(0, capture.get(cv2.CAP_PROP_POS_FRAMES) - 1) / asset["fps"]
                        sampled_times.append(decoded_time)
            if not frames:
                raise ValueError(f"Cannot decode scene {index} in {source}")
            clip_id = f"{asset['id']}:{index:04d}"
            thumb = thumb_dir / f"{asset['id']}_{index:04d}.jpg"
            representative = frames[len(frames) // 2]
            rgb = cv2.cvtColor(representative, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            image.thumbnail((640, 360))
            image.save(thumb, quality=85)
            subject_thumb = thumb_dir / f"{asset['id']}_{index:04d}_subject.jpg"
            subject_image = Image.fromarray(cv2.cvtColor(frames[0], cv2.COLOR_BGR2RGB))
            subject_image.thumbnail((960, 540))
            subject_image.save(subject_thumb, quality=90)
            metrics = _analyze_frames(frames)
            clips.append({"id": clip_id, "asset_id": asset["id"], "source": source, "kind": asset["kind"],
                          "start": round(start, 6), "end": round(end, 6), "duration": round(end - start, 6),
                          **metrics, "tags": [], "shot_type": "unknown", "subject": None,
                          "semantic_source": "unannotated", "thumb": str(thumb.resolve()),
                          "thumb_time": round(sampled_times[len(frames) // 2], 6),
                          "subject_thumb": str(subject_thumb.resolve()),
                          "subject_thumb_time": round(sampled_times[0], 6)})
    finally:
        if capture is not None:
            capture.release()
    return clips


def validate_subject(subject):
    if not isinstance(subject, (list, tuple)) or len(subject) != 4:
        raise ValueError("subject must be a normalized [x, y, width, height] bounding box")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in subject):
        raise ValueError("subject coordinates must be finite numbers")
    x, y, width, height = subject
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1 + 1e-8 or y + height > 1 + 1e-8:
        raise ValueError("subject bounding box must fit within the image")
    return [float(value) for value in subject]


def apply_annotations(clips, annotations):
    """Apply validated editor observations keyed by clip id (no source edits)."""
    if not isinstance(annotations, dict):
        raise ValueError("Annotations must be an object keyed by clip id")
    records = annotations.get("clips", annotations.get("annotations", annotations))
    if not isinstance(records, dict):
        raise ValueError("Annotations must be an object keyed by clip id")
    known = {clip["id"]: clip for clip in clips}
    unknown = set(records) - set(known)
    if unknown:
        raise ValueError(f"Unknown annotation clip ids: {sorted(unknown)}")
    allowed = {"tags", "shot_type", "subject", "action_time", "exclude", "notes", "quality"}
    for clip_id, values in records.items():
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError(f"Invalid annotation fields for {clip_id}; allowed: {sorted(allowed)}")
        clip = known[clip_id]
        if "tags" in values and (not isinstance(values["tags"], list) or any(not isinstance(tag, str) or not tag.strip() for tag in values["tags"])):
            raise ValueError(f"tags must contain nonempty strings: {clip_id}")
        if "shot_type" in values and values["shot_type"] not in SHOT_TYPES:
            raise ValueError(f"Unknown shot_type for {clip_id}: {values['shot_type']}")
        if values.get("subject") is not None:
            validate_subject(values["subject"])
        if "action_time" in values:
            time = values["action_time"]
            if isinstance(time, bool) or not isinstance(time, (float, int)) or not math.isfinite(time) or not clip["start"] <= time <= clip["end"]:
                raise ValueError(f"action_time must be absolute source seconds within clip {clip_id}")
        if "exclude" in values and not isinstance(values["exclude"], bool):
            raise ValueError(f"exclude must be true or false: {clip_id}")
        if "notes" in values and not isinstance(values["notes"], str):
            raise ValueError(f"notes must be a string: {clip_id}")
        if "quality" in values and (isinstance(values["quality"], bool) or not isinstance(values["quality"], (int, float)) or not 0 <= values["quality"] <= 1):
            raise ValueError(f"quality must be a number between zero and one: {clip_id}")
        clip.update(values)
        clip["semantic_source"] = "annotation"
    return clips


def _contact_sheets(clips, work):
    font = None
    for font_name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(font_name, 13)
            break
        except OSError:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=13)
        except TypeError:  # Pillow 10.0 still supports the rest of this module.
            font = ImageFont.load_default()
    files = []
    for page_start in range(0, len(clips), 48):
        page = clips[page_start:page_start + 48]
        cell_w, cell_h, columns = 320, 240, 4
        sheet = Image.new("RGB", (cell_w * columns, cell_h * math.ceil(len(page) / columns)), "#151515")
        draw = ImageDraw.Draw(sheet)
        for index, clip in enumerate(page):
            x, y = (index % columns) * cell_w, (index // columns) * cell_h
            with Image.open(clip["thumb"]) as thumb:
                image = ImageOps.contain(thumb, (cell_w - 8, 176))
                sheet.paste(image, (x + (cell_w - image.width) // 2, y))
            label = f"{clip['id']}\n{Path(clip['source']).name[:38]}\n{clip['kind']} {clip['start']:.2f}-{clip['end']:.2f}s"
            try:
                draw.multiline_text((x + 4, y + 178), label, font=font, fill="white", spacing=3)
            except UnicodeEncodeError:
                # Only old bitmap fallback fonts lack Unicode; full paths in
                # JSON remain untouched and the ASCII clip id stays readable.
                draw.multiline_text((x + 4, y + 178), label.encode("ascii", "replace").decode("ascii"), font=font, fill="white", spacing=3)
        target = work / f"contact_sheet_{len(files) + 1:03d}.jpg"
        sheet.save(target, quality=90)
        files.append(str(target.resolve()))
    return files


def analyze_library(inputs, work_dir, annotations_path=None):
    work = Path(work_dir).expanduser().resolve()
    thumb_dir = work / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    files = discover_media(inputs, work)
    assets = [probe_media(path) for path in files]
    clips = []
    for asset in assets:
        clips.extend(_clips_for_asset(asset, thumb_dir))
    if annotations_path is not None:
        with Path(annotations_path).open(encoding="utf-8-sig") as source:
            annotations = json.load(source)
        apply_annotations(clips, annotations)
    sheets = _contact_sheets(clips, work)
    result = {"schema_version": 2, "assets": assets, "clips": clips,
              "contact_sheet": sheets[0], "contact_sheets": sheets,
              "semantic_review": "complete" if all(clip["semantic_source"] == "annotation" for clip in clips) else "needed"}
    (work / "library.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Video/image files, folders or ZIP archives")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--annotations", help="JSON observations keyed by contact-sheet clip id")
    parser.add_argument("-o", "--output", help="Optional additional library JSON path")
    args = parser.parse_args()
    result = analyze_library(args.inputs, args.work_dir, args.annotations)
    if args.output:
        path = Path(args.output).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assets": len(result["assets"]), "clips": len(result["clips"]), "contact_sheets": result["contact_sheets"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

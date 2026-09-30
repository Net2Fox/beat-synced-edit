#!/usr/bin/env python3
"""Offline end-to-end title/subtitle smoke test with generated media only.

Run with the skill's Python environment. --scripts-dir can point to the repo
root, a built skill's scripts directory, or an installed skill's scripts. This
test never downloads models, calls speech recognition, or opens a browser.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import cv2
import numpy as np
from PIL import Image, ImageDraw


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def make_fixture(work, run):
    """Two shots exercise image/video paths and a real audible soundtrack."""
    photo, video, audio = (work/name for name in ("фото.png", "видео.mp4", "звук.wav"))
    image = Image.new("RGB", (320, 180), (65, 90, 115))
    ImageDraw.Draw(image).ellipse((135, 65, 185, 115), fill=(140, 180, 210))
    image.save(photo)
    run("generate-video", ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=0x406050:s=320x180:r=30:d=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)])
    sample_rate = 22050
    samples = (np.sin(2*np.pi*440*np.arange(sample_rate*3)/sample_rate)*5000).astype("<i2")
    with wave.open(str(audio), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(sample_rate)
        sound.writeframes(samples.tobytes())
    assets, edits = [], []
    for index, (source, kind) in enumerate(((photo, "image"), (video, "video"))):
        asset_id = f"asset-{index+1}"
        assets.append({"id": asset_id, "path": str(source), "kind": kind,
                       "width": 320, "height": 180, "duration": 1.5 if kind == "video" else 0})
        edits.append({"id": f"shot-{index+1:03d}", "asset_id": asset_id, "source": str(source), "kind": kind,
                      "source_start": 0, "source_end": 1.5 if kind == "video" else 0,
                      "average_speed": 1 if kind == "video" else 0,
                      "timeline_start_frame": 45*index, "timeline_end_frame": 45*(index+1),
                      "duration_frames": 45, "section": "intro", "effects": {}, "reframe": {"mode": "center"},
                      "speed_points": [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]})
    return {"schema_version": 2, "duration_frames": 90, "duration": 3,
            "output": {"width": 1080, "height": 1920, "fps": 30},
            "audio": {"path": str(audio), "start": 0, "duration": 3},
            "assets": assets, "clips": [], "edits": edits,
            "sections": [{"name": "intro", "start_frame": 0, "end_frame": 90}], "revision": 0}


def check_pixels(work):
    """Check actual encoded frames at cue boundaries against a text-free render."""
    frame_numbers = [5, 6, 12, 15, 32, 33, 35, 36, 39, 62, 63, 66, 80, 81, 89]
    captures = [cv2.VideoCapture(str(work/name)) for name in ("baseline.mp4", "final.mp4")]
    require(all(capture.isOpened() for capture in captures), "Rendered MP4 could not be opened")
    sheet = Image.new("RGB", (3*180, 5*340), "#202020")
    draw = ImageDraw.Draw(sheet)
    results = {}
    try:
        for index, number in enumerate(frame_numbers):
            frames = []
            for capture in captures:
                capture.set(cv2.CAP_PROP_POS_FRAMES, number)
                ok, frame = capture.read()
                require(ok, f"Missing decoded frame {number}")
                frames.append(frame)
            changed = np.abs(frames[0].astype(np.int16)-frames[1].astype(np.int16)).max(axis=2) > 20
            top = int(np.count_nonzero(changed[150:650]))
            bottom = int(np.count_nonzero(changed[1300:1770]))
            title_active = 6 <= number < 33
            caption_active = any(start <= number < end for start, end in ((15, 36), (39, 63), (66, 81)))
            require(top > 100 if title_active else top < 100,
                    f"Title frame boundary failed at {number}: {top} changed pixels")
            require(bottom > 100 if caption_active else bottom < 100,
                    f"Caption frame boundary failed at {number}: {bottom} changed pixels")
            results[number] = {"title_pixels": top, "caption_pixels": bottom}
            x, y = index % 3*180, index // 3*340
            sheet.paste(Image.fromarray(frames[1][..., ::-1]).resize((180, 320)), (x, y+20))
            draw.text((x+5, y+3), f"frame {number} / {number/30:.3f}s", fill="white")
    finally:
        for capture in captures:
            capture.release()
    sheet.save(work/"frame-boundaries.jpg", quality=95)
    return results


def main():
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts-dir", type=Path, default=repository,
                        help="Directory containing edit_project.py and its companion modules")
    parser.add_argument("--work-dir", type=Path, default=repository/"work/text-smoke",
                        help="Directory for synthetic inputs, outputs, cache and logs")
    args = parser.parse_args()
    scripts = args.scripts_dir.resolve()
    if not (scripts/"edit_project.py").is_file():
        parser.error("--scripts-dir must contain edit_project.py")
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            parser.error(f"{executable} must be on PATH")
    work = args.work_dir.resolve()/"титры и субтитры"
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    reports = {}

    def run(label, command):
        print(f"Running {label}...", flush=True)
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (work/f"{label}.log").write_text(result.stdout+"\n"+result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{label} failed ({result.returncode}):\n{result.stdout[-1000:]}\n{result.stderr[-3000:]}")
        return result.stdout

    def cli(label, *arguments):
        value = json.loads(run(label, [sys.executable, "-X", "utf8", "-B", str(scripts/"edit_project.py"),
                                      *map(str, arguments)]))
        reports[label] = value
        return value

    plan = make_fixture(work, run)
    project, baseline = work/"project.json", work/"baseline.json"
    save_json(project, plan)
    save_json(baseline, plan)
    captions = work/"captions.srt"
    captions.write_text("1\n00:00:00,300 --> 00:00:01,000\nНовый сезон начинается\n\n"
                        "2\n00:00:01,100 --> 00:00:01,900\nВнимание к деталям\n\n"
                        "3\n00:00:02,000 --> 00:00:02,500\nСоздавай свой ритм\n", encoding="utf-8")
    cli("title", "title", project, "--text", "Новый сезон 2026", "--start", .2, "--end", 1.1,
        "--position", "top", "--animation", "fade", "--fade-frames", 3)
    cli("import", "subtitles-import", project, captions)
    cli("style", "text-style", project, "--track", "subtitles", "--color", "#FFFFFF", "--background", "#000000CC")
    cache = work/"cache"
    cli("preview-first", "preview", project, "-o", work/"preview-first.mp4", "--cache", cache)
    initial = json.loads(project.read_text(encoding="utf-8"))
    operations = [{"op": "subtitle_update", "id": initial["subtitles"][1]["id"],
                   "values": {"text": "Каждая деталь создаёт настроение нового сезона"}},
                  {"op": "subtitles_shift", "seconds": .2}]
    save_json(work/"operations.json", operations)
    cli("revise", "revise", project, "--operations", work/"operations.json")
    for extension in ("srt", "vtt"):
        cli("export-"+extension, "subtitles-export", project, "-o", work/f"captions-final.{extension}")
    revised = cli("preview-revised", "preview", project, "-o", work/"preview-revised.mp4", "--cache", cache)
    cli("baseline-render", "render", baseline, "-o", work/"baseline.mp4", "--cache", cache)
    final = cli("final-render", "render", project, "-o", work/"final.mp4", "--cache", cache)
    require(revised["cache_hits"] == final["cache_hits"] == 2, "Text revisions must reuse all two shot caches")
    require((final["width"], final["height"], final["frames"], final["duration"]) == (1080, 1920, 90, 3),
            "Final dimensions, duration or frame count changed")
    require(final["audio"] and final["audio_sample_rate"] == 48000, "Final audio missing or wrong sample rate")
    updated = json.loads(project.read_text(encoding="utf-8"))
    require(updated["edits"] == plan["edits"] and updated["audio"] == plan["audio"], "Text revision changed picture/audio")
    expected = [(cue["text"], cue["start_frame"], cue["end_frame"]) for cue in updated["subtitles"]]
    require([item[1:] for item in expected] == [(15, 36), (39, 63), (66, 81)], "Caption shift changed timing unexpectedly")
    # Import the selected installation's module, not an accidentally available
    # repository copy, to exercise the --scripts-dir target's exporter/parser.
    sys.path.insert(0, str(scripts))
    from subtitle_tools import import_subtitles
    from text_overlay import TextCompositor
    for extension in ("srt", "vtt"):
        returned = import_subtitles(work/f"captions-final.{extension}", updated)
        require([(cue["text"], cue["start_frame"], cue["end_frame"]) for cue in returned] == expected,
                f"{extension.upper()} roundtrip changed text or frame times")
    # The long second phrase must wrap instead of clipping or truncating.
    compositor = TextCompositor(updated, 360, 640)
    long_cue = next(cue for cue in compositor.cues if cue.start == 39)
    require(len(long_cue.lines) >= 2, "Long Cyrillic caption did not wrap")
    preserved = {index for line, *_ in long_cue.lines for _, index in line}
    require(all(index in preserved for index, character in enumerate(expected[1][0]) if not character.isspace()),
            "Caption wrapping lost characters")
    reports["pixel_checks"] = check_pixels(work)
    reports["status"] = "passed"
    reports["scripts_dir"] = str(scripts)
    save_json(work/"verification.json", reports)
    print(json.dumps({"status": "PASS", "frames": 90, "duration": 3, "dimensions": [1080, 1920],
                      "audio": True, "cached_shots": "2/2", "sidecars": "SRT and VTT roundtrip exact",
                      "boundary_frames": "15 decoded frames verified", "work_dir": str(work)},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

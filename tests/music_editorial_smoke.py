#!/usr/bin/env python3
"""Render an automatic accelerating edit and verify decoded source timing.

Uses synthetic grayscale timecode and pulse audio; no real-media quality claim.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts-dir", type=Path, default=ROOT)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work" / "music-editorial-smoke")
    args = parser.parse_args()
    scripts, work = args.scripts_dir.resolve(), args.work_dir.resolve()
    sys.path.insert(0, str(scripts))
    from project_plan import speed_bounds
    from timeline_map import source_times
    work.mkdir(parents=True, exist_ok=True)
    events = []

    def cli(*command):
        argv = [sys.executable, "-X", "utf8", "-B", str(scripts/"edit_project.py"), *map(str, command)]
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        events.append({"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (work/"commands.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"CLI failed: {command}\n{result.stderr}\n{result.stdout}")
        return result.stdout

    video = work/"source.avi"
    fps = 12
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), fps, (96, 64))
    if not writer.isOpened():
        raise RuntimeError("Cannot create synthetic MJPG source")
    for index in range(fps*10):
        writer.write(np.full((64, 96, 3), index*2, dtype=np.uint8))
    writer.release()
    song = work/"pulses.wav"
    sr = 22050
    samples = np.zeros(sr*8)
    for beat in np.arange(.5, 8, .5):
        count = round(.08*sr)
        time = np.arange(count)/sr
        samples[round(beat*sr):round(beat*sr)+count] += .8*np.sin(2*np.pi*440*time)*np.exp(-time/.02)
    with wave.open(str(song), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sr)
        stream.writeframes((samples*30000).astype("<i2").tobytes())
    library = {"schema_version": 2, "assets": [{"id": "source", "path": str(video), "duration": 10., "kind": "video", "fps": fps}],
               "clips": [{"id": "timecode", "asset_id": "source", "source": str(video), "kind": "video", "start": 0., "end": 10.,
                          "quality": .8, "tags": ["fixture"], "energy": .7}]}
    (work/"library.json").write_text(json.dumps(library))
    (work/"sections.json").write_text(json.dumps([{"name": "drop", "start": 0, "end": 4}]))
    cli("music", song, "--duration", 4, "-o", work/"beats.json")
    beatmap = json.loads((work/"beats.json").read_text(encoding="utf-8"))
    assert beatmap["music_structure"]["pacing"]["mode"] == "beat_cut", beatmap["music_structure"]["pacing"]
    cli("plan", "--library", work/"library.json", "--beats", work/"beats.json", "--duration", 4,
        "--preset", "car", "--size", "96x64", "--fps", fps, "--audio-start", 0,
        "--sections", work/"sections.json", "--grade", "none", "--reframe", "center", "-o", work/"project.json")
    plan = json.loads((work/"project.json").read_text(encoding="utf-8"))
    # Disable effects so grayscale intensities independently reveal source timing.
    for shot in plan["edits"]:
        shot["effects"] = {"grade": "none", "flash": 0., "shake": 0., "zoom": 1.}
    (work/"project.json").write_text(json.dumps(plan), encoding="utf-8")
    curves = [s for s in plan["edits"] if len(s["speed_points"]) > 2]
    assert curves, "Automatic plan did not create an acceleration curve"
    assert all(speed_bounds(s, s["duration_frames"]/fps)[0] >= 1-1e-7 for s in curves)
    cli("render", work/"project.json", "-o", work/"render.mp4", "--cache", work/"cache")
    expected = np.concatenate([source_times(s, np.arange(s["duration_frames"])/s["duration_frames"]) for s in plan["edits"]]) * fps * 2
    capture = cv2.VideoCapture(str(work/"render.mp4"))
    observed = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        observed.append(float(np.median(frame)))
    capture.release()
    assert len(observed) == 48, len(observed)
    error = np.abs(np.asarray(observed)-expected)
    assert np.max(error) <= 8, {"max_error": float(np.max(error)), "expected": expected.tolist(), "actual": observed}
    cli("feedback", work/"library.json", "--profile", work/"preferences.json", "--clip", "timecode", "--decision", "accept", "--reason", "Synthetic timing verified")
    cli("candidates", work/"library.json", "--preferences", work/"preferences.json", "--query", "fixture", "-o", work/"candidates.json")
    report = {"status": "passed", "frames": len(observed), "accelerating_shots": len(curves),
              "max_gray_timing_error": float(np.max(error)), "beat_confidence": beatmap["music_structure"]["beat_confidence"],
              "scope": "Synthetic waveform analysis, automatic acceleration, CLI persistence and decoded source-time mapping only"}
    (work/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

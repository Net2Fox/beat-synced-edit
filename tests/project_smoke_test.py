#!/usr/bin/env python3
"""Exercise the complete project CLI with generated media, including revisions.

Run with the dependency environment; use --scripts-dir to test an installed skill.
All generated assets and reports are kept in ignored work/project-smoke by default.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts-dir", type=Path, default=ROOT)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work" / "project-smoke")
    args = parser.parse_args()
    scripts, work = args.scripts_dir.resolve(), args.work_dir.resolve()
    source = work / "исходники"
    source.mkdir(parents=True, exist_ok=True)
    events = []

    def run(*command):
        result = subprocess.run(list(map(str, command)), capture_output=True, text=True, encoding="utf-8", errors="replace")
        events.append({"command": list(map(str, command)), "returncode": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr})
        (work / "commands.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"Command failed: {command}\n{result.stderr[-3000:]}\n{result.stdout[-1000:]}")
        return result.stdout

    def cli(*command):
        return run(sys.executable, "-X", "utf8", "-B", scripts / "edit_project.py", *command)

    for i, (size, fps) in enumerate((("320x180", 24), ("180x320", 30), ("240x240", 60), ("320x240", 25))):
        folder = source / f"камера {i + 1}"
        folder.mkdir(exist_ok=True)
        run("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"testsrc2=size={size}:rate={fps}:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", folder / "кадр.mp4")
    image = Image.new("RGB", (400, 300), "#153347")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((145, 40, 255, 265), 14, fill="#eac84a")
    draw.text((165, 145), "DETAIL", fill="#101010")
    image.save(source / "предмет.png")
    sample_rate, song_seconds = 22050, 9
    samples = np.zeros(sample_rate * song_seconds, np.float32)
    pulse = np.sin(np.arange(int(.045 * sample_rate)) * 2 * np.pi * 900 / sample_rate)
    pulse *= np.exp(-np.arange(len(pulse)) / (sample_rate * .012))
    for beat in np.arange(.25, song_seconds - .1, .5):
        offset = int(beat * sample_rate)
        amplitude = .9 if 3 < beat < 7 else .35
        samples[offset:offset + len(pulse)] += pulse * amplitude
    song = work / "музыка.wav"
    with wave.open(str(song), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((samples * 30000).astype("<i2").tobytes())
    cli("analyze", source, "--work", work / "library")
    library_file = work / "library" / "library.json"
    library = json.loads(library_file.read_text(encoding="utf-8"))
    assert len(library["assets"]) == 5
    assert len({a["id"] for a in library["assets"]}) == 5
    annotations = {"clips": {c["id"]: {"tags": ["product" if c["kind"] == "image" else "test-pattern"],
                                        "shot_type": "detail" if c["kind"] == "image" else "wide",
                                        "quality": .8} for c in library["clips"]}}
    annotation_file = work / "annotations.json"
    annotation_file.write_text(json.dumps(annotations), encoding="utf-8")
    cli("annotate", library_file, "--annotations", annotation_file)
    cli("music", song, "--duration", "6", "-o", work / "beats.json")
    sections = [{"name": name, "start": start, "end": end} for name, start, end in
                (("intro", 0, 1.5), ("build", 1.5, 3), ("drop", 3, 5), ("outro", 5, 6))]
    section_file = work / "sections.json"
    section_file.write_text(json.dumps(sections), encoding="utf-8")
    project = work / "project.json"
    cli("plan", "--library", library_file, "--beats", work / "beats.json", "--duration", "6",
        "--preset", "product", "--size", "360x640", "--fps", "30", "--audio-start", "0",
        "--sections", section_file, "--section-stride", "drop=1", "--min-shot", ".25", "-o", project)
    plan = json.loads(project.read_text(encoding="utf-8"))
    assert plan["duration_frames"] == 180
    assert {e["section"] for e in plan["edits"]} == {"intro", "build", "drop", "outro"}
    intro = [e["duration_frames"] for e in plan["edits"] if e["section"] == "intro"]
    drop = [e["duration_frames"] for e in plan["edits"] if e["section"] == "drop"]
    assert np.mean(drop) < np.mean(intro), (intro, drop)
    cli("preview", project, "-o", work / "preview.mp4")
    shot = next(e for e in plan["edits"] if e["kind"] == "video")
    alternative = next(c for c in library["clips"] if c["kind"] == "video" and c["source"] != shot["source"])
    operations = [
        {"op": "replace", "shot": shot["id"], "clip_id": alternative["id"]},
        {"op": "effects", "all": True, "values": {"flash": 0, "grade": "none"}},
        {"op": "reframe", "shot": shot["id"], "mode": "center"},
        {"op": "speed", "shot": shot["id"], "points": [{"at": 0, "speed": 1.4}, {"at": .5, "speed": .9}, {"at": 1, "speed": 1.4}]},
    ]
    revisions = work / "revisions.json"
    revisions.write_text(json.dumps(operations), encoding="utf-8")
    cli("revise", project, "--operations", revisions)
    cli("preview", project, "-o", work / "preview-v2.mp4")
    # Lengthen one shot by a frame and borrow from the next; total stays exact.
    revised = json.loads(project.read_text(encoding="utf-8"))
    index = next(i for i in range(len(revised["edits"]) - 1) if revised["edits"][i + 1]["duration_frames"] > 3)
    revisions.write_text(json.dumps([{"op": "duration", "shot": index + 1,
                                       "seconds": (revised["edits"][index]["duration_frames"] + 1) / 30}]), encoding="utf-8")
    cli("revise", project, "--operations", revisions)
    cli("inspect", project)
    cli("render", project, "-o", work / "final.mp4")
    verified = json.loads((work / "final.verification.json").read_text(encoding="utf-8"))
    assert verified["frames"] == 180 and verified["duration"] == 6 and verified["audio"]
    assert (verified["width"], verified["height"]) == (360, 640)
    assert (work / "preview.html").is_file()
    assert len(list((work / ".history").glob("*.json"))) >= 2
    (work / "summary.json").write_text(json.dumps(verified, indent=2), encoding="utf-8")
    print(json.dumps(verified, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

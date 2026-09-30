#!/usr/bin/env python3
"""Create, preview, revise and render persistent music-synced editing projects."""

import argparse
import json
import os
from pathlib import Path
import sys

from project_workspace import read_json, review_html, revise_file, write_json


def size(value):
    try:
        width, height = map(int, value.lower().split("x"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from exc
    if min(width, height) < 2 or width % 2 or height % 2:
        raise argparse.ArgumentTypeError("width and height must be positive even integers")
    return width, height


def section_stride(value):
    try:
        name, stride = value.split("=", 1)
        stride = int(stride)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("section stride must be NAME=N, for example drop=1") from exc
    if name not in ("intro", "build", "drop", "outro") or stride < 1:
        raise argparse.ArgumentTypeError("section must be intro/build/drop/outro and stride must be positive")
    return name, stride


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Index folders, files and ZIPs; generate scene contact sheets")
    analyze.add_argument("inputs", nargs="+")
    analyze.add_argument("--work", required=True, help="Persistent analysis/output directory")
    analyze.add_argument("--annotations", help="Semantic annotations keyed by clip id")
    analyze.add_argument("-o", "--output")
    annotate = sub.add_parser("annotate", help="Apply visual observations to an indexed library without re-decoding")
    annotate.add_argument("library")
    annotate.add_argument("--annotations", required=True)
    annotate.add_argument("-o", "--output", help="Omit to update library atomically")
    music = sub.add_parser("music", help="Analyze beats and energy for the requested duration")
    music.add_argument("audio")
    music.add_argument("--duration", type=float, default=25)
    music.add_argument("-o", "--output", required=True)
    plan = sub.add_parser("plan", help="Plan exact duration with musical structure and a style preset")
    plan.add_argument("--library", required=True)
    plan.add_argument("--beats", required=True)
    plan.add_argument("--duration", type=float, default=25)
    plan.add_argument("--preset", choices=["cinematic", "car", "gaming", "product"], default="cinematic")
    plan.add_argument("--size", type=size, default=(1080, 1920))
    plan.add_argument("--fps", type=int, default=30)
    plan.add_argument("--audio-start", type=float)
    plan.add_argument("--allow-repeats", action="store_true")
    plan.add_argument("--shortage", choices=["extend", "error", "repeat"], default="extend")
    plan.add_argument("--min-speed", type=float, default=.5)
    plan.add_argument("--max-speed", type=float, default=3)
    plan.add_argument("--tags", nargs="*", help="Prefer these reviewed subject tags")
    plan.add_argument("--exclude", nargs="*", help="Exclude these clip IDs")
    plan.add_argument("--beat-stride", type=int, help="Override cut spacing across all sections")
    plan.add_argument("--section-stride", type=section_stride, action="append", help="Override one section's cut spacing, e.g. drop=1; repeat as needed")
    plan.add_argument("--min-shot", type=float, help="Minimum planned shot length in seconds")
    plan.add_argument("--max-shot", type=float, help="Maximum planned shot length in seconds")
    plan.add_argument("--grade", choices=["none", "neutral", "cinematic", "cool", "vivid", "warm"])
    plan.add_argument("--sections", help="JSON array with explicit musical section ranges")
    plan.add_argument("--reframe", choices=["auto", "center", "manual", "contain"], default="auto")
    plan.add_argument("--subject", type=float, nargs=4, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    plan.add_argument("-o", "--output", required=True)
    for command in ("render", "preview"):
        render = sub.add_parser(command, help="Render final output" if command == "render" else "Render fast review video and interactive HTML")
        render.add_argument("project")
        render.add_argument("-o", "--output", required=True)
        render.add_argument("--cache", help="Reusable shot cache; defaults to project folder/cache")
        if command == "preview":
            render.add_argument("--html", help="Review page path; defaults to preview filename.html")
    revise = sub.add_parser("revise", help="Apply targeted revisions and keep the previous project in .history")
    revise.add_argument("project")
    revise.add_argument("--operations", required=True, help="JSON revision operations")
    revise.add_argument("-o", "--output", help="Omit to update the project atomically")
    inspect = sub.add_parser("inspect", help="Validate a saved project and summarize its timeline")
    inspect.add_argument("project")
    sub.add_parser("presets", help="List the actual pace, effect and color settings")
    return p


def run(args):
    if args.command == "analyze":
        from media_library import analyze_library
        work = Path(args.work).resolve()
        work.mkdir(parents=True, exist_ok=True)
        result = analyze_library(args.inputs, str(work), annotations_path=args.annotations)
        output = Path(args.output).resolve() if args.output else work / "library.json"
        write_json(output, result)
        return {"library": str(output), "assets": len(result["assets"]), "clips": len(result["clips"]),
                "contact_sheet": result.get("contact_sheet"),
                "contact_sheets": result.get("contact_sheets", []),
                "next": "Inspect contact sheets and annotate subject tags, shot types and actions before planning."}
    if args.command == "annotate":
        from media_library import apply_annotations
        library = read_json(args.library)
        apply_annotations(library["clips"], read_json(args.annotations))
        library["semantic_review"] = "complete" if all(c.get("semantic_source") == "annotation" for c in library["clips"]) else "needed"
        output = args.output or args.library
        write_json(output, library)
        return {"library": str(Path(output).resolve()), "semantic_review": library["semantic_review"]}
    if args.command == "music":
        import math
        if not math.isfinite(args.duration) or args.duration <= 0:
            raise ValueError("duration must be positive and finite")
        work = Path(args.output).resolve().parent
        work.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("NUMBA_CACHE_DIR", str(work / "numba-cache"))
        from beat_map import analyze_audio
        audio = Path(args.audio).resolve(strict=True)
        result = analyze_audio(str(audio), segment_duration=args.duration)
        write_json(args.output, result)
        return {"beatmap": str(Path(args.output).resolve()), "tempo": result["tempo"], "beats": len(result["beats"])}
    if args.command == "plan":
        from project_plan import build_plan, validate_plan
        library, beatmap = read_json(args.library), read_json(args.beats)
        width, height = args.size
        overrides = {key: getattr(args, key) for key in
                     ("min_speed", "max_speed", "tags", "exclude", "beat_stride", "min_shot", "max_shot", "grade", "reframe", "subject")
                     if getattr(args, key) is not None}
        if args.section_stride:
            overrides["section_stride"] = dict(args.section_stride)
        result = build_plan(beatmap, library, duration=args.duration, preset=args.preset, fps=args.fps,
                            width=width, height=height, audio_start=args.audio_start,
                            allow_repeats=args.allow_repeats, shortage=args.shortage,
                            sections=read_json(args.sections) if args.sections else None, **overrides)
        for shot in result["edits"]:
            shot.setdefault("reframe", {})["mode"] = args.reframe
        result["revision"] = 0
        result["inputs"] = {"library": str(Path(args.library).resolve()), "beatmap": str(Path(args.beats).resolve())}
        validate_plan(result)
        write_json(args.output, result)
        return {"project": str(Path(args.output).resolve()), "duration": result["duration"],
                "frames": result["duration_frames"], "shots": len(result["edits"]), "preset": result["preset"]}
    if args.command in ("render", "preview"):
        from project_plan import validate_plan
        from project_render import render_project
        project = Path(args.project).resolve()
        plan = read_json(project)
        validate_plan(plan)
        cache = str(Path(args.cache).resolve() if args.cache else project.parent / "cache")
        result = render_project(plan, str(Path(args.output).resolve()), preview=args.command == "preview", cache_dir=cache)
        if args.command == "preview":
            page = args.html or str(Path(args.output).with_suffix(".html"))
            result["review_page"] = review_html(plan, args.output, page)
        write_json(str(Path(args.output).with_suffix(".verification.json")), result)
        return result
    if args.command == "revise":
        result = revise_file(args.project, read_json(args.operations), args.output)
        return {"project": str(Path(args.output or args.project).resolve()), "revision": result["revision"],
                "duration": result["duration"], "shots": len(result["edits"])}
    if args.command == "inspect":
        from project_plan import validate_plan
        result = read_json(args.project)
        validate_plan(result)
        return {key: result.get(key) for key in ("schema_version", "revision", "duration", "duration_frames", "preset", "output", "sections", "diagnostics", "timing_manually_revised")}
    if args.command == "presets":
        from edit_presets import PRESETS
        return PRESETS
    raise ValueError(f"Unknown command: {args.command}")


def main():
    args = parser().parse_args()
    try:
        result = run(args)
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

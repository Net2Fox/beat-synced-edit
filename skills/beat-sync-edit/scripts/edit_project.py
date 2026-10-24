#!/usr/bin/env python3
"""Create, preview, revise and render persistent music-synced editing projects."""

import argparse
import contextlib
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


def effect_override(value):
    from edit_effects import parse_effect_override
    try:
        return parse_effect_override(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parser():
    from edit_effects import GRADES
    from edit_presets import PRESETS
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
    plan.add_argument("--preset", choices=tuple(PRESETS), default="cinematic")
    plan.add_argument("--size", type=size, default=(1080, 1920))
    plan.add_argument("--fps", type=int, default=30)
    plan.add_argument("--audio-start", type=float)
    plan.add_argument("--allow-repeats", action="store_true")
    plan.add_argument("--shortage", choices=["extend", "error", "repeat"], default="extend")
    plan.add_argument("--min-speed", type=float)
    plan.add_argument("--slow-motion-prompt", default="", help="Exact user request explicitly authorizing interpolated slow motion")
    plan.add_argument("--interpolation", choices=("none", "optical_flow"), default="none")
    plan.add_argument("--max-speed", type=float, default=3)
    plan.add_argument("--tags", nargs="*", help="Prefer these reviewed subject tags")
    plan.add_argument("--exclude", nargs="*", help="Exclude these clip IDs")
    plan.add_argument("--beat-stride", type=int, help="Override cut spacing across all sections")
    plan.add_argument("--section-stride", type=section_stride, action="append", help="Override one section's cut spacing, e.g. drop=1; repeat as needed")
    plan.add_argument("--min-shot", type=float, help="Minimum planned shot length in seconds")
    plan.add_argument("--max-shot", type=float, help="Maximum planned shot length in seconds")
    plan.add_argument("--grade", choices=GRADES)
    plan.add_argument("--effect", type=effect_override, action="append", metavar="NAME=VALUE",
                      help="Override one preset effect, e.g. rgb_split=0.6 or grain=0.3; repeat as needed (see the effects command)")
    plan.add_argument("--sections", help="JSON array with explicit musical section ranges")
    plan.add_argument("--pacing-mode", choices=("auto", "beat_cut", "phrase_flow"), default="auto")
    plan.add_argument("--music-overrides", help="Reviewed musical events/phrases JSON")
    plan.add_argument("--preferences", help="Editorial preferences JSON")
    plan.add_argument("--query", default="", help="Requested content for reviewed semantic candidates")
    plan.add_argument("--editorial-model", help="Calibrated feature-weight model JSON")
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
    sub.add_parser("effects", help="List per-shot effects, grades and transitions with their value ranges")
    sub.add_parser("tool", help="Run a bundled helper script: tool TOOL.py [ARGS...] (beat_map.py, flash_montage.py, ...)")
    doctor = sub.add_parser("doctor", help="Check Python packages, FFmpeg encoders, fonts and optional speech recognition")
    doctor.add_argument("--strict", action="store_true", help="Also fail when optional components are missing")
    from text_commands import register_text_commands
    register_text_commands(sub)
    from audio_commands import register_audio_commands
    from speech_commands import register_speech_commands
    from editorial_commands import register_editorial_commands
    from graphics_commands import register_graphics_commands
    from workflow_commands import register_workflow_commands
    for register in (register_audio_commands, register_speech_commands, register_editorial_commands,
                     register_graphics_commands, register_workflow_commands):
        register(sub)
    sub.add_parser("contract", help="Describe every command and the structured CLI protocol")
    execute = sub.add_parser("execute-plan", help="Recheck inputs and execute a previously prepared CLI plan")
    execute.add_argument("manifest")
    from cli_contract import add_common_options
    add_common_options(sub)
    return p


def run(args):
    from cli_contract import guard_command_outputs
    guard_command_outputs(args)
    from audio_commands import AUDIO_COMMANDS, run_audio_command
    from speech_commands import SPEECH_COMMANDS, run_speech_command
    from editorial_commands import EDITORIAL_COMMANDS, run_editorial_command
    from graphics_commands import GRAPHICS_COMMANDS, run_graphics_command
    from workflow_commands import WORKFLOW_COMMANDS, run_workflow_command
    for commands, runner in ((AUDIO_COMMANDS, run_audio_command), (SPEECH_COMMANDS, run_speech_command),
                             (EDITORIAL_COMMANDS, run_editorial_command), (GRAPHICS_COMMANDS, run_graphics_command),
                             (WORKFLOW_COMMANDS, run_workflow_command)):
        if args.command in commands:
            return runner(args)
    if args.command == "contract":
        from cli_contract import contract
        return contract(parser())
    if args.command == "execute-plan":
        from cli_contract import execute_saved
        return execute_saved(args.manifest, parser(), run)
    from text_commands import TEXT_COMMANDS, run_text_command
    if args.command in TEXT_COMMANDS:
        return run_text_command(args)
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
                     ("min_speed", "max_speed", "tags", "exclude", "beat_stride", "min_shot", "max_shot", "grade", "reframe", "subject", "slow_motion_prompt", "interpolation")
                     if getattr(args, key) is not None}
        if args.section_stride:
            overrides["section_stride"] = dict(args.section_stride)
        if args.effect:
            overrides["effects"] = dict(args.effect)
        result = build_plan(beatmap, library, duration=args.duration, preset=args.preset, fps=args.fps,
                            width=width, height=height, audio_start=args.audio_start,
                            allow_repeats=args.allow_repeats, shortage=args.shortage,
                            pacing_mode=args.pacing_mode, query=args.query,
                            music_overrides=read_json(args.music_overrides) if args.music_overrides else None,
                            preferences=read_json(args.preferences) if args.preferences else None,
                            editorial_model=read_json(args.editorial_model) if args.editorial_model else None,
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
        from workflow_commands import render_with_qa
        project = Path(args.project).resolve()
        plan = read_json(project)
        from speech_project import refresh_source_captions
        from timeline_map import refresh_anchors
        refresh_source_captions(plan)
        refresh_anchors(plan)
        validate_plan(plan)
        cache = str(Path(args.cache).resolve() if args.cache else project.parent / "cache")
        result = render_with_qa(plan, str(Path(args.output).resolve()), preview=args.command == "preview", cache_dir=cache, project_path=project)
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
    if args.command == "effects":
        from edit_effects import catalog
        return catalog()
    if args.command == "doctor":
        from env_doctor import diagnose
        return diagnose(strict=args.strict)
    raise ValueError(f"Unknown command: {args.command}")


def bundled_tools():
    """Standalone helper scripts shipped beside this CLI (the legacy pipeline and utilities)."""
    here = Path(__file__).resolve().parent
    return {path.name: path for path in sorted(here.glob("*.py"))
            if path.name != Path(__file__).name and 'if __name__ == "__main__"' in path.read_text(encoding="utf-8")}


def run_tool(argv):
    tools = bundled_tools()
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: edit_project.py tool TOOL.py [ARGS...]\n\nBundled tools:\n  " + "\n  ".join(tools))
        return 0 if argv else 2
    name = argv[0] if argv[0].endswith(".py") else argv[0] + ".py"
    if name not in tools:
        print(f"Error: unknown tool {argv[0]!r}; choose one of: {', '.join(tools)}", file=sys.stderr)
        return 2
    import runpy
    previous = sys.argv
    sys.argv = [str(tools[name]), *argv[1:]]
    try:
        runpy.run_path(str(tools[name]), run_name="__main__")
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        sys.argv = previous
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["tool"]:
        return run_tool(argv[1:])
    if argv[:1] == ["doctor"]:
        # The environment check must work before NumPy/OpenCV are installed,
        # so it bypasses the full parser and its heavy command modules.
        from env_doctor import main as doctor_main
        return doctor_main(argv[1:])
    structured = "--json" in argv or "--json-brief" in argv
    brief = "--json-brief" in argv
    # Permit machine-output flags before or after the subcommand.
    argv = [a for a in argv if a not in ("--json", "--json-brief")] + (["--json-brief"] if brief else ["--json"] if structured else [])
    from cli_contract import prepare_plan, envelope
    args = None
    try:
        try:
            args = parser().parse_args(argv)
        except SystemExit as exc:
            if not structured or exc.code == 0:
                raise
            raise ValueError("Invalid command arguments; inspect the usage message on stderr") from exc
        if args.plan_file and not args.dry_run:
            raise ValueError("--plan is only valid with --dry-run")
        with contextlib.redirect_stdout(sys.stderr):
            result = prepare_plan(args, argv) if args.dry_run else run(args)
        failed = (isinstance(result, dict) and (result.get("technical_pass") is False or result.get("all_succeeded") is False
                                                or result.get("verified") is False or result.get("ready") is False))
        if failed:
            raise RuntimeError("Validation failed: " + json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        code, category = (3, "input_io") if isinstance(exc, OSError) else (4, "execution_failed") if isinstance(exc, RuntimeError) else (2, "invalid_argument")
        if structured:
            payload = envelope(getattr(args, "command", None), error={"code": category, "message": str(exc)})
            print(json.dumps(payload, ensure_ascii=False, indent=None if brief else 2, allow_nan=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return code
    payload = envelope(args.command, result=result) if structured else result
    print(json.dumps(payload, ensure_ascii=False, indent=None if brief else 2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

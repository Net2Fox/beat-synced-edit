"""Project styles, editable graphics, camera corrections and local motion clips."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from graphics_layers import STYLES, apply_style, validate_graphics
from project_workspace import read_json, write_json, revise_file

GRAPHICS_OPERATIONS = {"style", "graphics_set", "graphics_remove", "qa_policy"}
GRAPHICS_COMMANDS = {"style", "graphics", "graphics-remove", "graphic-template", "motion-project", "tracking-report", "reframe-keyframes", "font-check", "remotion-export"}


def apply_graphics_operation(plan, operation):
    kind = operation["op"]
    if kind == "style":
        plan.update(apply_style(plan, operation.get("preset"), operation.get("values")))
    elif kind == "graphics_set":
        plan["graphics"] = copy.deepcopy(operation["layers"])
    elif kind == "graphics_remove":
        if operation["id"] not in {layer["id"] for layer in plan.get("graphics", [])}:
            raise ValueError("Unknown graphic ID")
        plan["graphics"] = [layer for layer in plan["graphics"] if layer["id"] != operation["id"]]
    elif kind == "qa_policy":
        values = operation.get("values", {})
        if set(values) - {"intentional_black", "intentional_silence"}:
            raise ValueError("QA policy accepts intentional_black and intentional_silence ranges")
        from render_qa import _intentional
        plan["qa"] = values
        for name in ("black", "silence"):
            _intentional(plan, name, plan["duration"])
    validate_graphics(plan)


def register_graphics_commands(sub):
    style = sub.add_parser("style", help="Apply reusable typography, colors and safe areas to a project")
    style.add_argument("project")
    style.add_argument("--preset", choices=tuple(STYLES))
    style.add_argument("--config", help="JSON style overrides")
    style.add_argument("-o", "--output")
    graphics = sub.add_parser("graphics", help="Replace graphic layers in a recoverable project revision")
    graphics.add_argument("project")
    graphics.add_argument("--layers", required=True)
    graphics.add_argument("-o", "--output")
    remove = sub.add_parser("graphics-remove", help="Remove one graphic by stable ID")
    remove.add_argument("project")
    remove.add_argument("--id", required=True)
    remove.add_argument("-o", "--output")
    template = sub.add_parser("graphic-template", help="Create an editable local graphic layer JSON")
    template.add_argument("--kind", choices=("lower-third", "hook-card", "counter", "progress-bar"), required=True)
    template.add_argument("--text", default="")
    template.add_argument("--start-frame", type=int, default=0)
    template.add_argument("--end-frame", type=int, required=True)
    template.add_argument("-o", "--output", required=True)
    motion = sub.add_parser("motion-project", help="Build a local motion-graphics project from a JSON composition")
    motion.add_argument("spec")
    motion.add_argument("-o", "--output", required=True)
    track = sub.add_parser("tracking-report", help="Save source-time tracking confidence and camera path for review")
    track.add_argument("project")
    track.add_argument("--shot", required=True)
    track.add_argument("-o", "--output", required=True)
    reframe = sub.add_parser("reframe-keyframes", help="Apply explicit source-time camera-center keyframes")
    reframe.add_argument("project")
    reframe.add_argument("--shot", required=True)
    reframe.add_argument("--keyframes", required=True)
    reframe.add_argument("-o", "--output")
    font = sub.add_parser("font-check", help="Check actual font character coverage for a project")
    font.add_argument("project")
    remotion = sub.add_parser("remotion-export", help="Export an editable local React graphics composition; optionally render with installed Remotion")
    remotion.add_argument("spec")
    remotion.add_argument("--work", required=True)
    remotion.add_argument("--render", help="Render path using locally installed Node dependencies")


def motion_project(spec, destination):
    from PIL import Image
    from project_plan import validate_plan
    from graphics_layers import _number
    destination = Path(destination).resolve()
    fps = int(_number(spec.get("fps", 30), "fps", 1, 120, True))
    width = int(_number(spec.get("width", 1080), "width", 2, 8192, True))
    height = int(_number(spec.get("height", 1920), "height", 2, 8192, True))
    if width % 2 or height % 2:
        raise ValueError("Motion canvas dimensions must be even")
    duration = _number(spec.get("duration", 10), "duration", 1 / fps, 3600)
    frames = round(duration * fps)
    folder = destination.parent / "motion-assets"
    folder.mkdir(parents=True, exist_ok=True)
    color = spec.get("background", spec.get("style", {}).get("background", "#10151E"))
    # Use a content-derived filename, so revising a composition never changes an older source.
    signature = hashlib.sha256(f"{width}:{height}:{color}".encode()).hexdigest()[:16]
    source = folder / f"background-{signature}.png"
    if not source.exists():
        Image.new("RGB", (width, height), color).save(source)
    shot = {"id": "shot-001", "asset_id": "motion-background", "kind": "image", "source": str(source),
            "source_start": 0, "source_end": 0, "duration_frames": frames, "timeline_start_frame": 0,
            "timeline_end_frame": frames, "section": "intro", "effects": {"grade": "none"},
            "reframe": {"mode": "contain"}, "speed_points": [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]}
    plan = {"schema_version": 2, "mode": "motion", "revision": 0,
            "output": {"width": width, "height": height, "fps": fps}, "duration": frames / fps,
            "requested_duration": duration, "duration_frames": frames, "preset": "motion",
            "sections": [{"name": "intro", "start_frame": 0, "end_frame": frames}], "beat_frames": [],
            "assets": [{"id": "motion-background", "kind": "image", "path": str(source)}], "clips": [], "edits": [shot],
            "policies": {"allow_repeats": False, "min_speed": 1, "max_speed": 3},
            "audio_mix": spec.get("audio_mix", {"replace_legacy": True, "source_audio": {"enabled": False}, "tracks": [], "allow_silence": True}),
            "graphics": copy.deepcopy(spec.get("graphics", [])), "titles": copy.deepcopy(spec.get("titles", [])),
            "subtitles": copy.deepcopy(spec.get("subtitles", [])), "qa": copy.deepcopy(spec.get("qa", {}))}
    if spec.get("audio"):
        plan["audio"] = copy.deepcopy(spec["audio"])
        if "audio_mix" not in spec:
            plan.pop("audio_mix", None)
    elif "audio_mix" not in spec:
        plan["qa"].setdefault("intentional_silence", [[0, frames / fps]])
    plan = apply_style(plan, values=spec.get("style", {}))
    validate_plan(plan)
    write_json(destination, plan)
    return plan


def run_graphics_command(args):
    if args.command == "graphic-template":
        rects = {"lower-third": [.06, .66, .82, .15], "hook-card": [.08, .10, .80, .23],
                 "counter": [.16, .22, .66, .30], "progress-bar": [.07, .79, .78, .025]}
        layer = {"id": args.kind + "-001", "kind": {"counter": "counter", "progress-bar": "bar"}.get(args.kind, "card"),
                 "text": args.text, "start_frame": args.start_frame, "end_frame": args.end_frame,
                 "rect": rects[args.kind], "animation": "fade" if args.kind == "progress-bar" else "slide"}
        validate_graphics({"duration_frames": args.end_frame, "graphics": [layer]})
        write_json(args.output, [layer])
        return {"layers": str(Path(args.output).resolve()), "count": 1}
    if args.command == "motion-project":
        plan = motion_project(read_json(args.spec), args.output)
        return {"project": str(Path(args.output).resolve()), "frames": plan["duration_frames"], "mode": "motion"}
    if args.command == "remotion-export":
        from remotion_adapter import export_composition
        return export_composition(read_json(args.spec), args.work, args.render)
    plan = read_json(args.project)
    if args.command == "font-check":
        from font_diagnostics import inspect_project_fonts
        reports = inspect_project_fonts(plan)
        return {"fonts": reports, "verified": all(report["status"] == "pass" for report in reports)}
    if args.command == "tracking-report":
        from tracking_review import resolve_track, tracking_report
        shot = next((s for s in plan["edits"] if s["id"] == args.shot), None)
        if shot is None:
            raise ValueError("Unknown shot ID")
        result = tracking_report(shot, resolve_track(shot))
        write_json(args.output, result)
        return {"report": str(Path(args.output).resolve()), **result}
    if args.command == "style":
        operations = [{"op": "style", "preset": args.preset, "values": read_json(args.config) if args.config else {}}]
    elif args.command == "graphics":
        operations = [{"op": "graphics_set", "layers": read_json(args.layers)}]
    elif args.command == "graphics-remove":
        operations = [{"op": "graphics_remove", "id": args.id}]
    elif args.command == "reframe-keyframes":
        operations = [{"op": "reframe", "shot": args.shot, "mode": "auto", "keyframes": read_json(args.keyframes)}]
    else:
        raise ValueError(f"Unknown graphics command {args.command}")
    result = revise_file(args.project, operations, args.output)
    return {"project": str(Path(args.output or args.project).resolve()), "revision": result["revision"]}

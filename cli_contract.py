"""Machine-readable CLI contract and content-bound, non-shell execution plans."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

from project_workspace import read_json, write_json
from render_qa import file_hash

SCHEMA = "beat-sync.cli.v1"
PLAN_SCHEMA = "beat-sync.execution-plan.v1"
OUTPUT_KEYS = {"output", "work", "cache", "html", "download_root", "model_dir", "beats_output", "render", "plan_file"}
INPUT_KEYS = {"project", "library", "beats", "audio", "media", "video", "source", "file", "spec", "inputs", "projects", "manifest",
              "annotations", "operations", "config", "layers", "keyframes", "sections", "words", "transcript", "translations",
              "glossary", "preferences", "music_overrides", "editorial_model", "feedback", "candidates", "segments", "corrections", "report", "observations", "labels", "beatmap", "profile", "overrides", "font", "anchor"}
PATH_KEYS = {"source", "path", "font", "library", "beatmap", "project", "transcript", "words_path", "file", "audio_path", "render"}


def add_common_options(sub):
    for command in dict.fromkeys(sub.choices.values()):
        command.add_argument("--json", action="store_true", help="Emit the versioned JSON success/error envelope")
        command.add_argument("--json-brief", action="store_true", help="Emit compact JSON (also enables the envelope)")
        command.add_argument("--dry-run", action="store_true", help="Validate syntax and fingerprint inputs without running the command")
        command.add_argument("--plan", dest="plan_file", help="With --dry-run, save a content-bound execution plan")


def contract(parser):
    sub = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    commands = {}
    for name, child in sub.choices.items():
        commands[name] = [{"name": a.dest, "flags": a.option_strings, "required": a.required,
                           "nargs": a.nargs, "choices": list(a.choices) if a.choices is not None else None,
                           "type": getattr(a.type, "__name__", "string"), "help": a.help}
                          for a in child._actions if a.dest != "help"]
    return {"schema": SCHEMA, "commands": commands,
            "errors": {"invalid_argument": 2, "input_io": 3, "execution_failed": 4},
            "dry_run": "Syntax, input existence, saved-project validation and hashes; no decoding or model execution.",
            "execution_plan": "Rechecks input content and tool sources before executing one parsed CLI command. Not an approval token."}


def tool_signature():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(bytes.fromhex(file_hash(path)))
    return {"source_sha256": digest.hexdigest(), "python": platform.python_version()}


def fingerprint_inputs(args, hash_files=True):
    files, directories, visited = {}, {}, set()

    def visit(path, required=False):
        path = Path(path).expanduser().resolve()
        if not path.exists():
            if required:
                raise FileNotFoundError(f"Input does not exist: {path}")
            return
        key = str(path)
        if key in visited:
            return
        visited.add(key)
        if path.is_dir():
            members = sorted(str(p.resolve()) for p in path.rglob("*") if p.is_file())
            directories[key] = members
            for item in members:
                visit(item)
            return
        files[key] = {"sha256": file_hash(path) if hash_files else None, "bytes": path.stat().st_size}
        if path.suffix.lower() == ".json":
            try:
                data = read_json(path)
            except (ValueError, UnicodeError):
                return

            def nested(value, field=None):
                if isinstance(value, dict):
                    for k, v in value.items():
                        nested(v, k)
                elif isinstance(value, list):
                    for v in value:
                        nested(v, field)
                elif isinstance(value, str) and field in PATH_KEYS:
                    candidate = Path(value)
                    if not candidate.is_absolute():
                        candidate = path.parent / candidate
                    visit(candidate)
            nested(data)

    for key, value in vars(args).items():
        if key == "render" and getattr(args, "command", None) == "review-manifest":
            for path in value or []:
                visit(path, required=True)
            continue
        if key == "model" and value:
            # Editorial models are JSON inputs. Whisper also accepts a model
            # name; only an existing local model is a file/directory input.
            local = Path(value).expanduser()
            if getattr(args, "command", None) == "candidates" or local.exists() or local.is_absolute() or str(value).startswith((".", "~")):
                visit(local, required=True)
            continue
        if key == "transcript" and getattr(args, "command", None) in ("transcribe", "subtitles-transcribe"):
            continue
        if key == "profile" and getattr(args, "command", None) == "feedback" and value and not Path(value).exists():
            continue
        if key == "model_dir" and value and Path(value).exists():
            visit(value)
        if key in INPUT_KEYS and key not in OUTPUT_KEYS and value:
            for path in value if isinstance(value, list) else [value]:
                if isinstance(path, (str, Path)):
                    visit(path, required=True)
    return {"files": files, "directories": directories}


def guard_command_outputs(args):
    """Preflight explicit products before commands can modify any input."""
    protected = {Path(p) for p in fingerprint_inputs(args, hash_files=False)["files"]}
    revision_commands = {"revise", "title", "text-style", "subtitles-import", "subtitles-transcribe", "audio-config",
                         "speech-import", "speech-correct", "speech-translate", "speech-captions", "speech-broll", "speech-retry",
                         "anchor", "action", "style", "graphics", "graphics-remove", "reframe-keyframes"}
    allowed = set()
    if args.command in revision_commands and getattr(args, "project", None):
        allowed.add(Path(args.project).resolve())
    if args.command == "annotate":
        allowed.add(Path(args.library).resolve())
    if args.command == "review-export":
        allowed.add(Path(args.report).resolve())
    destinations = [(key, Path(value).resolve()) for key, value in vars(args).items()
                    if key in {"output", "html", "render", "beats_output"} and value
                    and not (key == "render" and args.command == "review-manifest")]
    if args.command == "preview" and not args.html:
        destinations.append(("html", Path(args.output).resolve().with_suffix(".html")))
    if args.command == "feedback":
        target = Path(args.profile).resolve()
        if target == Path(args.library).resolve():
            raise ValueError("Feedback profile cannot overwrite its library")
    for key, target in destinations:
        if target in protected and not (key == "output" and target in allowed):
            raise ValueError(f"Output cannot overwrite an input: {target}")
    if len({p for _, p in destinations}) < len(destinations):
        raise ValueError("Different outputs must use distinct paths")


def clean_argv(argv):
    result, skip = [], False
    for item in argv:
        if skip:
            skip = False
            continue
        if item == "--plan":
            skip = True
        elif item in ("--dry-run", "--json", "--json-brief") or item.startswith("--plan="):
            continue
        else:
            result.append(item)
    return result


def prepare_plan(args, argv):
    if args.command in ("execute-plan", "contract"):
        raise ValueError("dry-run requires a concrete work command")
    guard_command_outputs(args)
    if getattr(args, "project", None):
        from project_plan import validate_plan
        validate_plan(read_json(args.project))
    inputs = fingerprint_inputs(args)
    result = {"schema": PLAN_SCHEMA, "cwd": str(Path.cwd()), "argv": clean_argv(argv),
              "command": args.command, "tool": tool_signature(), "inputs": inputs,
              "execution_status": "not_executed", "validation": "syntax, saved project and input fingerprints",
              "outputs": {k: v for k, v in vars(args).items() if k in OUTPUT_KEYS and k != "plan_file" and v
                          and not (k == "render" and args.command == "review-manifest")}}
    if getattr(args, "plan_file", None):
        destination = Path(args.plan_file).resolve()
        if str(destination) in inputs["files"]:
            raise ValueError("An execution plan cannot overwrite its own input")
        if any(destination.is_relative_to(Path(d)) for d in inputs["directories"]):
            raise ValueError("Save the execution plan outside an input directory")
        write_json(destination, result)
        result["plan"] = str(destination)
    return result


def execute_saved(path, parser, runner):
    saved = read_json(path)
    if saved.get("schema") != PLAN_SCHEMA or not isinstance(saved.get("argv"), list):
        raise ValueError("Unsupported execution plan")
    if saved.get("tool") != tool_signature():
        raise ValueError("Tool sources or Python changed; prepare a fresh execution plan")
    original = Path.cwd()
    try:
        os.chdir(saved["cwd"])
        try:
            args = parser.parse_args(saved["argv"])
        except SystemExit as exc:
            raise ValueError("Saved execution plan contains invalid command arguments") from exc
        if args.command in ("execute-plan", "contract") or args.dry_run or args.plan_file:
            raise ValueError("Nested execution plans are not allowed")
        if fingerprint_inputs(args) != saved.get("inputs"):
            raise ValueError("An input changed after planning; prepare a fresh execution plan")
        return runner(args)
    finally:
        os.chdir(original)


def envelope(command, result=None, error=None):
    value = {"schema": SCHEMA, "ok": error is None, "command": command}
    value["error" if error else "result"] = error if error else result
    if not error:
        value["provenance"] = tool_signature()
    return value

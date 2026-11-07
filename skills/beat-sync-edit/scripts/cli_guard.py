"""Overwrite protection for CLI commands, and the tool signature for provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path
import platform

from project_workspace import read_json
from render_qa import file_hash

# Argument names that hold input paths, and JSON keys inside input files that
# name further inputs (media referenced by a project, a library or a beat map).
INPUT_KEYS = {"project", "library", "beats", "audio", "media", "video", "source", "file", "spec", "inputs", "manifest",
              "annotations", "operations", "config", "layers", "keyframes", "sections", "words", "transcript", "translations",
              "glossary", "preferences", "music_overrides", "feedback", "candidates", "segments", "corrections", "report",
              "observations", "beatmap", "profile", "overrides", "font"}
PATH_KEYS = {"source", "path", "font", "library", "beatmap", "project", "transcript", "words_path", "file", "audio_path"}


def tool_signature():
    """Hash of the runtime modules and the Python version, recorded with each render."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(bytes.fromhex(file_hash(path)))
    return {"source_sha256": digest.hexdigest(), "python": platform.python_version()}


def input_files(args):
    """Every existing file a command reads, including paths named inside its JSON inputs.

    A missing required input raises FileNotFoundError before anything runs.
    """
    files, visited = set(), set()

    def visit(path, required=False):
        path = Path(path).expanduser().resolve()
        if not path.exists():
            if required:
                raise FileNotFoundError(f"Input does not exist: {path}")
            return
        if path in visited:
            return
        visited.add(path)
        if path.is_dir():
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    visit(item)
            return
        files.add(path)
        if path.suffix.lower() == ".json":
            try:
                data = read_json(path)
            except (ValueError, UnicodeError):
                return

            def nested(value, field=None):
                if isinstance(value, dict):
                    for key, item in value.items():
                        nested(item, key)
                elif isinstance(value, list):
                    for item in value:
                        nested(item, field)
                elif isinstance(value, str) and field in PATH_KEYS:
                    candidate = Path(value)
                    visit(candidate if candidate.is_absolute() else path.parent / candidate)
            nested(data)

    command = getattr(args, "command", None)
    for key, value in vars(args).items():
        if key == "model" and value:
            # Whisper accepts a model name; only a local model folder is an input.
            local = Path(value).expanduser()
            if local.exists() or local.is_absolute() or str(value).startswith((".", "~")):
                visit(local, required=True)
            continue
        if key == "transcript" and command == "subtitles-transcribe":
            continue  # an output path for this command
        if key == "profile" and command == "feedback" and value and not Path(value).exists():
            continue  # feedback creates the profile
        if key == "model_dir" and value and Path(value).exists():
            visit(value)
        if key in INPUT_KEYS and value:
            for path in value if isinstance(value, list) else [value]:
                if isinstance(path, (str, Path)):
                    visit(path, required=True)
    return files


def guard_command_outputs(args):
    """Refuse outputs that would overwrite an input, before the command runs."""
    protected = input_files(args)
    revision_commands = {"revise", "title", "text-style", "subtitles-import", "subtitles-transcribe", "audio-config",
                         "speech-import", "speech-correct", "speech-translate", "speech-captions", "speech-broll", "speech-retry",
                         "action", "style", "graphics", "graphics-remove", "reframe-keyframes"}
    allowed = set()
    if args.command in revision_commands and getattr(args, "project", None):
        allowed.add(Path(args.project).resolve())
    if args.command == "annotate":
        allowed.add(Path(args.library).resolve())
    if args.command == "review-export":
        allowed.add(Path(args.report).resolve())
    destinations = [(key, Path(value).resolve()) for key, value in vars(args).items()
                    if key in {"output", "html", "beats_output"} and value]
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

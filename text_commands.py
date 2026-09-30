"""CLI entry points for titles, caption files and optional local speech recognition."""

import argparse
import math
from pathlib import Path
import subprocess
import tempfile

from project_workspace import read_json, revise_file, write_json

TEXT_COMMANDS = {"title", "text-style", "subtitles-import", "subtitles-export", "subtitles-transcribe"}


def _color_or_none(value):
    return None if value.lower() in ("none", "transparent") else value


def _add_style(parser, preset=False):
    if preset:
        parser.add_argument("--preset", choices=["clean", "boxed", "karaoke"])
    parser.add_argument("--font", help="Absolute path to a .ttf/.otf font with the required glyphs")
    parser.add_argument("--font-size", type=float, help="Font size in full-resolution pixels")
    parser.add_argument("--color")
    parser.add_argument("--highlight-color")
    parser.add_argument("--background", help="Hex RGB/RGBA color, or none")
    parser.add_argument("--stroke-color")
    parser.add_argument("--stroke-width", type=float)
    parser.add_argument("--position", choices=["top", "center", "bottom"])
    parser.add_argument("--align", choices=["left", "center", "right"])
    parser.add_argument("--max-width", type=float, help="Maximum text block width as a frame fraction")
    parser.add_argument("--margin", type=float, help="Safe margin as a frame fraction")
    parser.add_argument("--max-lines", type=int)
    parser.add_argument("--opacity", type=float)
    parser.add_argument("--animation", choices=["none", "fade", "slide"])
    parser.add_argument("--fade-frames", type=int)
    parser.add_argument("--highlight", action=argparse.BooleanOptionalAction, default=None)


def _style(args):
    names = ("font", "font_size", "color", "highlight_color", "stroke_color", "stroke_width",
             "position", "align", "max_width", "margin", "max_lines", "opacity", "animation", "fade_frames", "highlight")
    result = {key: getattr(args, key) for key in names if getattr(args, key, None) is not None}
    if getattr(args, "background", None) is not None:
        result["background"] = _color_or_none(args.background)
    if "font" in result:
        result["font"] = str(Path(result["font"]).expanduser().resolve(strict=True))
    return result


def register_text_commands(sub):
    title = sub.add_parser("title", help="Add a title to the saved project with output-relative times")
    title.add_argument("project")
    title.add_argument("--text", required=True)
    title.add_argument("--id", help="Optional stable cue id")
    title.add_argument("--start", type=float, default=0)
    until = title.add_mutually_exclusive_group(required=True)
    until.add_argument("--end", type=float)
    until.add_argument("--duration", type=float)
    title.add_argument("-o", "--output", help="Save a new project instead of updating it")
    _add_style(title)
    style = sub.add_parser("text-style", help="Set the global title/subtitle style")
    style.add_argument("project")
    style.add_argument("--track", choices=["titles", "subtitles"], required=True)
    style.add_argument("-o", "--output")
    _add_style(style, preset=True)
    incoming = sub.add_parser("subtitles-import", help="Import an SRT or WebVTT caption track")
    incoming.add_argument("project")
    incoming.add_argument("file")
    incoming.add_argument("--offset", type=float, default=0, help="Additional timing shift in seconds")
    incoming.add_argument("--timebase", choices=["project", "soundtrack"], default="project")
    incoming.add_argument("-o", "--output")
    _add_style(incoming, preset=True)
    outgoing = sub.add_parser("subtitles-export", help="Export subtitles as an SRT or WebVTT sidecar")
    outgoing.add_argument("project")
    outgoing.add_argument("-o", "--output", required=True)
    outgoing.add_argument("--format", choices=["srt", "vtt"])
    speech = sub.add_parser("subtitles-transcribe", aliases=["transcribe"], help="Transcribe the audible soundtrack locally and add timed captions")
    speech.set_defaults(command="subtitles-transcribe")
    speech.add_argument("project")
    speech.add_argument("--audio", help="Optional aligned audio/video to transcribe instead of the project's soundtrack")
    speech.add_argument("--audio-start", type=float, help="Start in the supplied recording; defaults to zero, or the project's audio start")
    speech.add_argument("--offset", type=float, default=0, help="Shift resulting captions in the output timeline")
    speech.add_argument("--model", default="small", help="Whisper model name or an existing converted model directory")
    speech.add_argument("--language", help="Language code such as ru/en; omit for detection")
    speech.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    speech.add_argument("--compute-type", default="int8")
    speech.add_argument("--model-dir", help="Local model download/cache directory")
    speech.add_argument("--local-files-only", action="store_true", help="Use cached models without downloading")
    speech.add_argument("--max-chars", type=int, default=42)
    speech.add_argument("--max-words", type=int, default=7)
    speech.add_argument("--max-duration", type=float, default=3)
    speech.add_argument("--transcript", help="Save the raw timed transcript JSON here")
    speech.add_argument("-o", "--output", help="Save a new project instead of updating it")
    _add_style(speech, preset=True)


def _save(args, operations):
    result = revise_file(args.project, operations, args.output)
    return {"project": str(Path(args.output or args.project).resolve()), "revision": result["revision"],
            "titles": len(result.get("titles", [])), "subtitles": len(result.get("subtitles", [])),
            "duration": result["duration"]}


def _style_operation(args, track):
    style = _style(args)
    preset = getattr(args, "preset", None)
    return [{"op": "text_style", "track": track, "values": style, "preset": preset}] if style or preset else []


def _input_paths(args, plan):
    paths = [plan["audio"]["path"]]
    paths.extend(e["source"] for e in plan["edits"])
    paths.extend(a["path"] for a in plan.get("assets", []))
    paths.extend(c["source"] for c in plan.get("clips", []))
    paths.extend(getattr(args, key, None) for key in ("audio", "file"))
    return {Path(path).expanduser().resolve() for path in paths if path}


def run_text_command(args):
    from project_plan import validate_plan
    plan = read_json(args.project)
    validate_plan(plan)
    protected = _input_paths(args, plan)
    if args.output and Path(args.output).expanduser().resolve() in protected:
        raise ValueError("Output cannot overwrite source media or the imported subtitle file")
    if args.command == "title":
        end = args.end if args.end is not None else args.start + args.duration
        values = {"text": args.text, "start": args.start, "end": end, "style": _style(args)}
        if args.id:
            values["id"] = args.id
        return _save(args, [{"op": "title_add", "values": values}])
    if args.command == "text-style":
        operations = _style_operation(args, args.track)
        if not operations:
            raise ValueError("Specify a style preset or at least one style setting")
        return _save(args, operations)
    if args.command == "subtitles-import":
        from subtitle_tools import import_subtitles
        cues = import_subtitles(args.file, plan, offset=args.offset, timebase=args.timebase)
        if not cues:
            raise ValueError("No imported cues fall inside this project; check timebase and offset")
        return _save(args, [{"op": "subtitles_replace", "cues": cues}] + _style_operation(args, "subtitles"))
    if args.command == "subtitles-export":
        from subtitle_tools import export_subtitles
        cues = plan.get("subtitles", [])
        if not cues:
            raise ValueError("The project has no subtitles to export")
        output = Path(args.output).resolve()
        if output == Path(args.project).resolve():
            raise ValueError("Subtitle output cannot overwrite the project or source media")
        export_subtitles(cues, plan["output"]["fps"], str(output), format=args.format)
        return {"subtitles": len(cues), "path": str(output)}
    if args.command == "subtitles-transcribe":
        from speech_transcribe import transcribe_audio
        from subtitle_tools import segment_transcript
        source = Path(args.audio or plan["audio"]["path"]).expanduser().resolve(strict=True)
        start = args.audio_start if args.audio_start is not None else (0 if args.audio else plan["audio"].get("start", 0))
        if not math.isfinite(start) or start < 0 or not math.isfinite(args.offset):
            raise ValueError("Audio start must be nonnegative and offset must be finite")
        work = Path(args.project).resolve().parent
        transcript_file = Path(args.transcript).resolve() if args.transcript else work / "transcript.json"
        protected.update((Path(args.project).resolve(), Path(args.output or args.project).resolve()))
        if transcript_file in protected:
            raise ValueError("Transcript path cannot overwrite the project, output project, subtitles or source media")
        if args.max_chars < 1 or args.max_words < 1 or not math.isfinite(args.max_duration) or args.max_duration <= 0:
            raise ValueError("Caption character, word and duration limits must be positive")
        model_dir = Path(args.model_dir).resolve() if args.model_dir else work / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        # Recognize only the portion that will be audible. No media is uploaded.
        with tempfile.TemporaryDirectory(prefix="speech-", dir=work) as temporary:
            wav = Path(temporary) / "speech.wav"
            command = ["ffmpeg", "-y", "-v", "error", "-nostdin"]
            if not args.audio and plan["audio"].get("loop", False):
                command += ["-stream_loop", "-1"]
            command += ["-ss", str(start), "-i", str(source), "-t", str(plan["duration"]),
                        "-vn", "-map", "0:a:0", "-af",
                        f"asetpts=N/SR/TB,atrim=duration={plan['duration']},asetpts=PTS-STARTPTS",
                        "-ac", "1", "-ar", "16000", str(wav)]
            extracted = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if extracted.returncode:
                raise ValueError("Cannot extract speech audio: " + extracted.stderr[-1500:])
            transcript = transcribe_audio(str(wav), model=args.model, language=args.language,
                                          device=args.device, compute_type=args.compute_type,
                                          model_dir=str(model_dir), local_files_only=args.local_files_only)
        transcript["source"] = str(source)
        transcript["audio_path"] = str(source)
        transcript["source_start"] = start
        transcript["project_offset"] = args.offset
        cues = segment_transcript(transcript, plan, offset=args.offset, timebase="project",
                                  max_chars=args.max_chars, max_words=args.max_words, max_duration=args.max_duration)
        write_json(transcript_file, transcript)
        if not cues:
            return {"status": "no_speech", "project_unchanged": True, "transcript": str(transcript_file)}
        result = _save(args, [{"op": "subtitles_replace", "cues": cues}] + _style_operation(args, "subtitles"))
        result.update(transcript=str(transcript_file), language=transcript.get("language"))
        return result
    raise ValueError(f"Unknown text command: {args.command}")

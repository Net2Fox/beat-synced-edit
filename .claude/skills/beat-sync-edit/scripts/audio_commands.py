"""Public local audio CLI; all mutation validates before an atomic save."""
import copy
from pathlib import Path
import shutil

from project_workspace import read_json, write_json

AUDIO_COMMANDS = {"audio-config", "audio-mix", "audio-report", "arrange-music"}


def register_audio_commands(sub):
    config = sub.add_parser("audio-config", help="Set tracks, source audio, ducking and loudness from a JSON object")
    config.add_argument("project")
    config.add_argument("--config", required=True)
    config.add_argument("-o", "--output")
    mix = sub.add_parser("audio-mix", help="Render and measure the project's audible soundtrack as a lossless WAV")
    mix.add_argument("project")
    mix.add_argument("-o", "--output", required=True)
    mix.add_argument("--cache")
    measure = sub.add_parser("audio-report", help="Measure decoded audio loudness and true peak, including encoded MP4")
    measure.add_argument("media")
    measure.add_argument("-o", "--output")
    arrange = sub.add_parser("arrange-music", help="Arrange supplied music by explicit bar ranges; regenerate beat map")
    arrange.add_argument("audio")
    arrange.add_argument("--beats", required=True)
    arrange.add_argument("--segments", required=True, help="JSON array; bars one-based and end-exclusive")
    arrange.add_argument("--beats-per-bar", type=int, default=4)
    arrange.add_argument("--first-downbeat", type=int, default=0, help="Zero-based first downbeat index in beat array")
    arrange.add_argument("-o", "--output", required=True)
    arrange.add_argument("--beats-output")


def protected_paths(plan):
    result = {Path(e["source"]).resolve() for e in plan.get("edits", [])}
    result.update(Path(e["audio_source"]["source"]).resolve() for e in plan.get("edits", []) if e.get("audio_source"))
    result.update(Path(t["path"]).resolve() for t in plan.get("audio_mix", {}).get("tracks", []))
    if plan.get("audio", {}).get("path"):
        result.add(Path(plan["audio"]["path"]).resolve())
    return result


def run_audio_command(args):
    from audio_mix import audio_info, encoded_audio_report, measure_loudness, mix_project_audio, validate_audio_mix
    if args.command == "audio-report":
        media = Path(args.media).resolve(strict=True)
        result = {"path": str(media), "audio": audio_info(media), "measurements": measure_loudness(media)}
        if args.output:
            if Path(args.output).resolve() == media:
                raise ValueError("Report cannot overwrite its source")
            write_json(args.output, result)
        return result
    if args.command == "arrange-music":
        from music_arrangement import arrange_music
        protected = {Path(x).resolve() for x in (args.audio, args.beats, args.segments)}
        destinations = {Path(args.output).resolve(), Path(args.beats_output).resolve() if args.beats_output else Path(args.output).resolve().with_suffix(".beats.json")}
        if protected & destinations:
            raise ValueError("Arrangement outputs cannot overwrite inputs")
        return arrange_music(args.audio, read_json(args.beats), read_json(args.segments), args.output,
                             args.beats_per_bar, args.first_downbeat, args.beats_output)
    project_path = Path(args.project).resolve(strict=True)
    project = read_json(project_path)
    if args.command == "audio-config":
        updated = copy.deepcopy(project)
        updated["audio_mix"] = read_json(args.config)
        validate_audio_mix(updated, check_files=True)
        destination = Path(args.output).resolve() if args.output else project_path
        if destination in protected_paths(updated) | {Path(args.config).resolve()}:
            raise ValueError("Project output cannot overwrite audio or configuration inputs")
        # Same history convention as targeted picture/text revisions.
        if destination == project_path:
            history = project_path.parent/".history"
            history.mkdir(exist_ok=True)
            import uuid
            write_json(history/f"{project_path.stem}.audio.{uuid.uuid4().hex}.json", project)
        updated["revision"] = int(updated.get("revision", 0))+1
        write_json(destination, updated)
        return {"project": str(destination), "revision": updated["revision"], "audio_mix": updated["audio_mix"]}
    output = Path(args.output).resolve()
    if output.suffix.lower() != ".wav":
        raise ValueError("Audio mix output must be .wav")
    report_path = output.with_suffix(".audio.json")
    if {output, report_path} & (protected_paths(project) | {project_path}):
        raise ValueError("Audio mix/report output cannot overwrite project sources")
    cache = Path(args.cache).resolve() if args.cache else project_path.parent/"cache"
    stem, result = mix_project_audio(project, cache)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output != stem:
        shutil.copyfile(stem, output)
    result = encoded_audio_report(output, result)
    write_json(report_path, result)
    return {"path": str(output), "report": str(report_path), "audio": result}

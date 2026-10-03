"""Public local transcript, speech montage, B-roll and anchor workflows."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np

from project_workspace import read_json, write_json, revise_file
from speech_project import (normalize_transcript, import_transcript, phrase_candidates,
                            build_speech_plan, refresh_source_captions, recognized_intervals)

SPEECH_COMMANDS = {"speech-analyze", "speech-plan", "speech-import", "speech-correct", "speech-translate",
                  "speech-captions", "speech-broll", "speech-gaps", "speech-retry", "speech-batch", "anchor", "action"}


def _asr_args(parser):
    parser.add_argument("--model", default="small")
    parser.add_argument("--language")
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--model-dir")
    parser.add_argument("--local-files-only", action="store_true")


def register_speech_commands(sub):
    for name in ("speech-analyze", "speech-plan"):
        p = sub.add_parser(name, help="Analyze source speech" if name.endswith("analyze") else "Build a speech-first montage with original audio")
        p.add_argument("source", help="Local video with an audio stream")
        p.add_argument("--transcript", help="Existing SRT/VTT or real word-timed JSON; otherwise local Whisper is used")
        p.add_argument("-o", "--output", required=True)
        _asr_args(p)
        if name == "speech-plan":
            p.add_argument("--select", nargs="+", help="Candidate IDs from speech-analyze, in desired order")
            p.add_argument("--fps", type=int, default=30)
            p.add_argument("--width", type=int, default=1080)
            p.add_argument("--height", type=int, default=1920)
            p.add_argument("--pause-limit", type=float, default=.5, help="Maximum retained pause after each chosen phrase, seconds")
            p.add_argument("--keep-pauses", action="store_true", help="Preserve all pauses between chronological selections")
            p.add_argument("--padding", type=float, default=.1)
    p = sub.add_parser("speech-import", help="Add a source-timed transcript to an existing project")
    p.add_argument("project"); p.add_argument("file"); p.add_argument("--source-id", required=True); p.add_argument("-o", "--output")
    p = sub.add_parser("speech-correct", help="Correct stable word/segment IDs or apply supplied terminology")
    p.add_argument("project"); p.add_argument("--file", help="JSON mapping word/segment IDs to corrected text")
    p.add_argument("--glossary", help="JSON mapping misspelled terms to corrected terms")
    p.add_argument("--transcript-id"); p.add_argument("-o", "--output")
    p = sub.add_parser("speech-translate", help="Import supplied translations; this command does not generate translations")
    p.add_argument("project"); p.add_argument("file", help="JSON mapping stable segment IDs to translated text")
    p.add_argument("--language", required=True); p.add_argument("--mode", choices=["translated", "bilingual"], default="bilingual")
    p.add_argument("--transcript-id"); p.add_argument("-o", "--output")
    p = sub.add_parser("speech-captions", help="Choose original, translated or bilingual source-aware captions")
    p.add_argument("project"); p.add_argument("--mode", choices=["original", "translated", "bilingual"], default="original")
    p.add_argument("--language"); p.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=True); p.add_argument("-o", "--output")
    p = sub.add_parser("speech-broll", help="Replace one picture shot while retaining its continuous original speech")
    p.add_argument("project"); p.add_argument("--shot", required=True)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--clip", help="Existing project clip ID"); source.add_argument("--media", help="Local B-roll video/still")
    p.add_argument("--source-start", type=float, default=0)
    p.add_argument("--offset", type=float, default=0, help="Insert begins this many seconds into the selected picture shot")
    p.add_argument("--duration", type=float, help="Optional bounded insert; underlying speech remains continuous")
    p.add_argument("--reframe", choices=["auto", "center", "contain"], default="auto"); p.add_argument("-o", "--output")
    p = sub.add_parser("speech-gaps", help="Report uncovered energetic source intervals for manual ASR review")
    p.add_argument("project"); p.add_argument("--source-id"); p.add_argument("--min-gap", type=float, default=.8)
    p.add_argument("--threshold-db", type=float, default=-40); p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("speech-retry", help="Retry a specified uncovered gap locally without disturbing stable existing words")
    p.add_argument("project"); p.add_argument("--source-id"); p.add_argument("--start", type=float, required=True); p.add_argument("--end", type=float, required=True)
    p.add_argument("--file", help="Optional human-aligned retry JSON in absolute source times")
    p.add_argument("-o", "--output"); _asr_args(p)
    p = sub.add_parser("speech-batch", help="Analyze local recordings with one reused recognizer per model configuration")
    p.add_argument("manifest", help="JSON {items:[{id,source,transcript?}]}; relative paths resolve beside manifest")
    p.add_argument("-o", "--output", required=True, help="Analysis JSON report"); _asr_args(p)
    p = sub.add_parser("anchor", help="Persist a source/word/beat/event/shot/action anchor and its resolution")
    p.add_argument("project"); p.add_argument("--id", required=True); p.add_argument("--spec", required=True, help="Anchor JSON object")
    p.add_argument("-o", "--output")
    p = sub.add_parser("action", help="Persist a named source action usable by titles, graphics and audio")
    p.add_argument("project"); p.add_argument("--id", required=True); p.add_argument("--source-id", required=True)
    p.add_argument("--time", type=float, required=True); p.add_argument("-o", "--output")


def probe_asset(path, require_speech=True):
    from project_render import probe
    from media_library import _hash_file, IMAGE_EXTENSIONS
    path = Path(path).expanduser().resolve(strict=True)
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        if require_speech:
            raise ValueError("Speech source must be video with audio")
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
        digest = _hash_file(path)
        return {"id": "asset-"+digest[:16], "sha256": digest, "path": str(path), "kind": "image", "width": width, "height": height, "duration": 0}
    data = probe(path)
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not videos or (require_speech and not audio):
        raise ValueError("Speech source requires video and an audio stream" if require_speech else "B-roll must be video or image")
    duration = float(videos[0].get("duration") or data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Source duration must be positive")
    digest = _hash_file(path)
    return {"id": "asset-"+digest[:16], "sha256": digest, "path": str(path), "kind": "video", "duration": duration,
            "width": int(videos[0]["width"]), "height": int(videos[0]["height"]), "has_audio": bool(audio)}


def _asr(args, path, work):
    from speech_transcribe import transcribe_audio
    model_dir = Path(args.model_dir).resolve() if args.model_dir else Path(work)/"models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return transcribe_audio(path, model=args.model, language=args.language, device=args.device,
                            compute_type=args.compute_type, model_dir=model_dir, local_files_only=args.local_files_only)


def _get_transcript(args, asset, work):
    if getattr(args, "transcript", None):
        return import_transcript(args.transcript, asset["id"], asset["duration"])
    return normalize_transcript(_asr(args, asset["path"], work), asset["id"], asset["duration"])


def gap_report(source, transcript, duration, min_gap=.8, threshold_db=-40):
    """Energy finds suspicious gaps, never labels noise/music as recognized speech."""
    if not math.isfinite(min_gap) or min_gap <= 0 or not math.isfinite(threshold_db) or not -120 <= threshold_db <= 0:
        raise ValueError("Gap size/energy threshold invalid")
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(source), "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"]
    process = subprocess.run(cmd, capture_output=True)
    if process.returncode:
        raise RuntimeError("Gap analysis decode failed: "+process.stderr.decode(errors="replace")[-1200:])
    pcm = np.frombuffer(process.stdout, dtype="<f4")
    covered = recognized_intervals(transcript)
    gaps, cursor = [], 0
    for start, end in covered+[(duration, duration)]:
        if start-cursor >= min_gap:
            samples = pcm[round(cursor*8000):round(start*8000)]
            rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64)))) if len(samples) else 0
            db = 20*math.log10(max(1e-12, rms))
            suspect = db >= threshold_db
            gaps.append({"start": round(cursor, 6), "end": round(start, 6), "rms_dbfs": round(db, 2),
                         "suspected_missing_speech": suspect, "status": "review_required" if suspect else "quiet_gap",
                         "reason": "Untranscribed audio has measurable energy; may be speech, music or noise" if suspect else "Low measured energy; not proof that no speech exists"})
        cursor = max(cursor, end)
    return {"source_id": transcript["source_id"], "source": str(source), "gaps": gaps,
            "suspect_count": sum(g["suspected_missing_speech"] for g in gaps), "threshold_dbfs": threshold_db,
            "min_gap": min_gap, "recognition_accuracy": "not_reviewed"}


def _protected_output(output, inputs):
    target = Path(output).expanduser().resolve()
    if target in {Path(p).expanduser().resolve() for p in inputs if p}:
        raise ValueError("Output cannot overwrite input media/transcript")
    return target


def _project_source(plan, source_id):
    transcripts = plan.get("speech", {}).get("transcripts", [])
    if source_id is None and len(transcripts) == 1:
        source_id = transcripts[0]["source_id"]
    transcript = next((t for t in transcripts if t["source_id"] == source_id), None)
    asset = next((a for a in plan["assets"] if a["id"] == source_id), None)
    if asset is None or transcript is None:
        raise ValueError("Specify a source-id with an imported transcript")
    return asset, transcript


def run_speech_command(args):
    command = args.command
    if command in ("speech-analyze", "speech-plan"):
        output = _protected_output(args.output, [args.source, args.transcript])
        output.parent.mkdir(parents=True, exist_ok=True)
        asset = probe_asset(args.source)
        transcript = _get_transcript(args, asset, output.parent)
        if command == "speech-analyze":
            report = {"asset": asset, "transcript": transcript, "candidates": phrase_candidates(transcript),
                      "gap_report": gap_report(asset["path"], transcript, asset["duration"]), "review_status": "not_reviewed"}
            write_json(output, report)
            return {"path": str(output), "candidates": len(report["candidates"]), "transcript_id": transcript["id"],
                    "source_id": asset["id"], "suspect_gaps": report["gap_report"]["suspect_count"]}
        plan = build_speech_plan(asset, transcript, selected=args.select, fps=args.fps, width=args.width,
                height=args.height, pause_limit=None if args.keep_pauses else args.pause_limit, padding=args.padding)
        write_json(output, plan)
        return {"project": str(output), "mode": "speech", "shots": len(plan["edits"]), "duration": plan["duration"],
                "subtitles": len(plan["subtitles"]), "source_id": asset["id"], "review_status": "not_reviewed"}
    if command == "speech-batch":
        manifest = Path(args.manifest).resolve()
        data = read_json(manifest)
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("Batch manifest must contain nonempty items")
        output = _protected_output(args.output, [manifest]+[manifest.parent/i["source"] for i in items]+[manifest.parent/i["transcript"] for i in items if i.get("transcript")])
        output.parent.mkdir(parents=True, exist_ok=True)
        results, ids = [], set()
        for index, item in enumerate(items):
            identifier = item.get("id", f"item-{index+1:03d}")
            if not isinstance(identifier, str) or not identifier or identifier in ids:
                raise ValueError("Batch item IDs must be unique nonempty strings")
            ids.add(identifier)
            try:
                local = argparse.Namespace(**vars(args))
                source = (manifest.parent/item["source"]).resolve()
                local.transcript = str((manifest.parent/item["transcript"]).resolve()) if item.get("transcript") else None
                asset = probe_asset(source)
                transcript = _get_transcript(local, asset, output.parent)
                results.append({"id": identifier, "status": "analyzed", "asset": asset, "transcript": transcript,
                                "candidates": phrase_candidates(transcript), "gap_report": gap_report(source, transcript, asset["duration"]),
                                "review_status": "not_reviewed"})
            except (ValueError, RuntimeError, OSError) as error:
                results.append({"id": identifier, "status": "failed", "error": str(error)})
        write_json(output, {"items": results, "model_reuse": True, "review_status": "not_reviewed"})
        return {"path": str(output), "analyzed": sum(r["status"] == "analyzed" for r in results),
                "failed": sum(r["status"] == "failed" for r in results),
                "all_succeeded": all(r["status"] == "analyzed" for r in results)}
    from project_plan import validate_plan
    plan = read_json(args.project)
    validate_plan(plan)
    protected = [a["path"] for a in plan["assets"]]+[t.get("import_path") for t in plan.get("speech", {}).get("transcripts", [])]
    protected += [getattr(args, "file", None), getattr(args, "glossary", None), getattr(args, "media", None)]
    if args.output:
        _protected_output(args.output, protected)
    operation = None
    if command == "speech-import":
        asset = next((a for a in plan["assets"] if a["id"] == args.source_id), None)
        if asset is None:
            raise ValueError("source-id must match an existing project asset")
        operation = {"op": "speech_transcript", "source_id": args.source_id,
                     "transcript": import_transcript(args.file, args.source_id, asset["duration"])}
    elif command == "speech-correct":
        operation = {"op": "speech_correct", "transcript_id": args.transcript_id,
                     "corrections": read_json(args.file) if args.file else {}, "glossary": read_json(args.glossary) if args.glossary else {}}
    elif command == "speech-translate":
        operation = {"op": "speech_translate", "transcript_id": args.transcript_id, "language": args.language,
                     "translations": read_json(args.file), "mode": args.mode}
    elif command == "speech-captions":
        operation = {"op": "speech_captions", "mode": args.mode, "language": args.language, "enabled": args.enabled}
    elif command == "speech-broll":
        operation = {"op": "speech_broll", "shot_id": args.shot, "clip_id": args.clip,
                     "source_start": args.source_start, "reframe": args.reframe, "offset": args.offset, "duration": args.duration}
        if args.media:
            asset = probe_asset(args.media, require_speech=False)
            clip = {"id": asset["id"]+"-broll", "asset_id": asset["id"], "source": asset["path"], "kind": asset["kind"],
                    "start": 0, "end": asset["duration"], "duration": asset["duration"]}
            operation.update(asset=asset, clip=clip, clip_id=clip["id"])
    elif command == "speech-gaps":
        _protected_output(args.output, protected+[args.project])
        asset, transcript = _project_source(plan, args.source_id)
        report = gap_report(asset["path"], transcript, asset["duration"], args.min_gap, args.threshold_db)
        write_json(args.output, report)
        return {"path": str(Path(args.output).resolve()), "suspect_gaps": report["suspect_count"]}
    elif command == "speech-retry":
        asset, transcript = _project_source(plan, args.source_id)
        if not (math.isfinite(args.start) and math.isfinite(args.end) and 0 <= args.start < args.end <= asset["duration"]):
            raise ValueError("Retry range must lie inside source")
        if any(a < args.end and b > args.start for a, b in recognized_intervals(transcript)):
            raise ValueError("Retry range must be an uncovered gap; existing transcript is never overwritten")
        if args.file:
            incoming = import_transcript(args.file, asset["id"], asset["duration"])
        else:
            work = Path(args.project).resolve().parent
            with tempfile.TemporaryDirectory(prefix="retry-", dir=work) as tmp:
                wav = Path(tmp)/"gap.wav"
                process = subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", str(args.start), "-i", asset["path"],
                     "-t", str(args.end-args.start), "-vn", "-ac", "1", "-ar", "16000", str(wav)], capture_output=True, text=True)
                if process.returncode:
                    raise RuntimeError("Retry audio extraction failed: "+process.stderr[-1500:])
                data = _asr(args, wav, work)
            if not data["segments"]:
                return {"project": str(Path(args.project).resolve()), "segments_added": 0, "status": "no_speech_recognized", "review_required": True}
            for segment in data["segments"]:
                segment["start"] += args.start; segment["end"] += args.start
                for word in segment.get("words", []):
                    word["start"] += args.start; word["end"] += args.start
            incoming = normalize_transcript(data, asset["id"])
        # Retry IDs must never collide with existing stable words.
        salt = hashlib.sha256(json.dumps(incoming, sort_keys=True).encode()).hexdigest()[:10]
        for index, segment in enumerate(incoming["segments"]):
            segment["id"] = f"{transcript['id']}-retry-{salt}-s{index+1}"
            for word_index, word in enumerate(segment.get("words", [])):
                word["id"] = f"{segment['id']}-w{word_index+1}"
        operation = {"op": "speech_retry_result", "transcript_id": transcript["id"], "start": args.start,
                     "end": args.end, "transcript": incoming}
    elif command == "anchor":
        operation = {"op": "anchor_set", "value": {"id": args.id, "anchor": json.loads(args.spec)}}
    elif command == "action":
        operation = {"op": "action_set", "value": {"id": args.id, "source_id": args.source_id, "time": args.time}}
    if operation is None:
        raise ValueError(f"Unknown speech command: {command}")
    revised = revise_file(args.project, [operation], args.output)
    return {"project": str(Path(args.output or args.project).resolve()), "revision": revised["revision"],
            "subtitles": len(revised.get("subtitles", [])), "anchors": revised.get("anchors", [])}

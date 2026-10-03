"""Speech-first planning, stable transcripts, source captions and B-roll.

No text is translated or guessed by this module. Sentence completeness is a
punctuation heuristic and every candidate retains an explicit review status.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re

from subtitle_tools import _join_words, _coalesce_words
from timeline_map import inverse_source_times, mapping_edit, source_matches, refresh_anchors

SPEECH_OPERATIONS = {"speech_transcript", "speech_correct", "speech_translate", "speech_captions",
                     "speech_broll", "anchor_set", "action_set", "speech_retry_result"}


def _positive_span(start, end):
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)) or start < 0 or end <= start:
        raise ValueError("Transcript times must form a positive finite source interval")


def normalize_transcript(data, source_id, source_duration=None):
    """Keep imported real word timestamps; cue-only imports never invent them."""
    if isinstance(data, list):
        data = {"segments": data}
    result = deepcopy(data)
    if "segments" not in result and "words" in result:
        words = result["words"]
        if not words:
            raise ValueError("Empty word transcript")
        result["segments"] = [{"start": words[0]["start"], "end": words[-1]["end"],
                               "text": _join_words([{**w, "text": w.get("text", w.get("word"))} for w in words]), "words": words}]
    if not isinstance(result.get("segments"), list):
        raise ValueError("Transcript needs segments or words")
    result["source_id"] = str(source_id)
    result.setdefault("id", "transcript-"+hashlib.sha256(str(source_id).encode()).hexdigest()[:12])
    identifiers, previous = set(), -1
    for i, segment in enumerate(result["segments"]):
        segment.setdefault("id", f"{result['id']}-s{i+1:04d}")
        _positive_span(segment.get("start"), segment.get("end"))
        if segment["start"] < previous-1e-8:
            raise ValueError("Transcript segments must be ordered and cannot overlap")
        previous = segment["end"]
        if source_duration is not None and segment["end"] > source_duration+.05:
            raise ValueError("Transcript extends beyond its source media")
        if not isinstance(segment.get("text"), str) or not segment["text"].strip():
            raise ValueError("Transcript segment text must be nonempty")
        last = segment["start"]
        for j, word in enumerate(segment.get("words", [])):
            word["text"] = word.get("text", word.get("word"))
            if not isinstance(word["text"], str) or not word["text"].strip():
                raise ValueError("Transcript word text must be nonempty")
            word.setdefault("id", f"{segment['id']}-w{j+1:03d}")
            _positive_span(word.get("start"), word.get("end"))
            if word["start"] < last-1e-6 or word["end"] > segment["end"]+1e-6:
                raise ValueError("Words must be ordered, nonoverlapping and inside their segment")
            last = word["end"]
            if word["id"] in identifiers:
                raise ValueError("Transcript IDs must be unique")
            identifiers.add(word["id"])
        if segment["id"] in identifiers:
            raise ValueError("Transcript IDs must be unique")
        identifiers.add(segment["id"])
    result.setdefault("corrections", [])
    result.setdefault("review_required", True)
    return result


def import_transcript(path, source_id, source_duration):
    path = Path(path)
    if path.suffix.lower() in (".srt", ".vtt"):
        from subtitle_tools import import_subtitles
        # Preserve milliseconds in the source domain, independent of output FPS.
        plan = {"output": {"fps": 100}, "duration_frames": math.ceil(source_duration*100), "audio": {"start": 0}}
        cues = import_subtitles(path, plan, preserve_source_times=True)
        data = {"segments": [{"start": c["start"], "end": c["end"],
                               "text": c["text"]} for c in cues], "origin": "subtitle_file", "word_timing": "unavailable"}
    else:
        from project_workspace import read_json
        data = read_json(path)
        if isinstance(data, dict) and "transcript" in data:
            data = data["transcript"]
        elif isinstance(data, dict) and "speech" in data:
            data = next((t for t in data["speech"].get("transcripts", []) if t["source_id"] == source_id), None)
            if data is None:
                raise ValueError("The supplied project has no transcript for this source")
    result = normalize_transcript(data, source_id, source_duration)
    result["import_path"] = str(path.resolve())
    return result


def phrase_candidates(transcript, max_duration=45, pause_boundary=.8):
    if not math.isfinite(max_duration) or max_duration <= 0 or not math.isfinite(pause_boundary) or pause_boundary < 0:
        raise ValueError("Candidate duration and pause boundary must be valid")
    sentences, current = [], []
    # Use actual timed words where present. Sentence boundaries inside Whisper
    # segments remain selectable; cue-only transcripts retain intact cues.
    units = []
    for segment in transcript["segments"]:
        if segment.get("words"):
            units.extend({**word, "segment_id": segment["id"]} for word in segment["words"])
        else:
            units.append({**segment, "segment_id": segment["id"]})
    def emit(reason):
        if not current:
            return
        text = _join_words(current)
        complete = bool(re.search(r'[.!?。！？…][\"\'»”’)]*$', text))
        ids = [u["id"] for u in current]
        sentences.append({"id": "phrase-"+hashlib.sha256("|".join(ids).encode()).hexdigest()[:12],
            "source_id": transcript["source_id"], "start": current[0]["start"], "end": current[-1]["end"],
            "text": text, "word_ids": [u["id"] for u in current if "words" not in u and u["id"] != u["segment_id"]],
            "segment_ids": list(dict.fromkeys(u["segment_id"] for u in current)),
            "complete_thought": complete, "reason": reason + ("; sentence-ending punctuation" if complete else "; no sentence ending: review context"),
            "over_duration": current[-1]["end"]-current[0]["start"] > max_duration,
            "review_status": "not_reviewed"})
        current.clear()
    for unit in units:
        if current and unit["start"]-current[-1]["end"] >= pause_boundary:
            emit("Pause boundary")
        current.append(unit)
        if re.search(r'[.!?。！？…][\"\'»”’)]*$', unit["text"].strip()):
            emit("Complete sentence candidate")
        # No forced mid-sentence duration cut: flag long thoughts for review.
    emit("End of transcript")
    return sentences


def _clip_for_source(asset):
    return {"id": f"{asset['id']}-speech", "asset_id": asset["id"], "source": asset["path"],
            "kind": "video", "start": 0, "end": asset["duration"], "duration": asset["duration"],
            "tags": ["speech"], "shot_type": "medium"}


def build_speech_plan(asset, transcript, selected=None, fps=30, width=1080, height=1920,
                      pause_limit=.5, padding=.1, captions=True):
    from project_plan import validate_plan
    transcript = normalize_transcript(transcript, asset["id"], asset["duration"])
    if asset.get("kind") != "video":
        raise ValueError("Speech-first picture source must be a video with audible speech")
    if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in (fps, width, height)):
        raise ValueError("Output dimensions and FPS must be positive integers")
    if not math.isfinite(padding) or padding < 0 or (pause_limit is not None and (not math.isfinite(pause_limit) or pause_limit < 0)):
        raise ValueError("Padding/pause limit must be nonnegative; None preserves all pauses")
    candidates = phrase_candidates(transcript)
    if selected:
        by_id = {c["id"]: c for c in candidates}
        if len(selected) != len(set(selected)) or set(selected)-set(by_id):
            raise ValueError("Selected candidate IDs must be known and unique")
        chosen = [by_id[c] for c in selected]
    else:
        chosen = candidates
    if not chosen:
        raise ValueError("No speech candidates to plan")
    ranges = []
    for i, candidate in enumerate(chosen):
        begin, end = max(0, candidate["start"]-padding), min(asset["duration"], candidate["end"]+padding)
        # Preserve meaningful pauses between chronologically adjacent selections.
        if i+1 < len(chosen) and chosen[i+1]["start"] >= candidate["end"]:
            gap = chosen[i+1]["start"]-candidate["end"]
            preserve = gap if pause_limit is None else min(gap, pause_limit)
            end = min(asset["duration"], max(end, candidate["end"]+preserve))
        if ranges and candidate["start"] >= chosen[i-1]["end"]:
            begin = max(begin, ranges[-1][1]/fps)
        first = max(0, math.floor(begin*fps))
        last = min(math.floor(asset["duration"]*fps), math.ceil(end*fps))
        if ranges and candidate["start"] >= chosen[i-1]["end"]:
            first = max(first, ranges[-1][1])
        if last <= first:
            raise ValueError("Selected speech has less than one output frame")
        ranges.append([first, last, candidate])
    # Padding must not reuse footage when the requested sentence order differs
    # from source order. Resolve neighboring padding at their source gap.
    ordered_ranges = sorted(ranges, key=lambda value: value[2]["start"])
    for previous, following in zip(ordered_ranges, ordered_ranges[1:]):
        if previous[1] > following[0]:
            boundary = math.floor((previous[2]["end"]+following[2]["start"])*fps/2+.5)
            previous[1], following[0] = boundary, boundary
        if previous[1] <= previous[0] or following[1] <= following[0]:
            raise ValueError("Adjacent speech candidates cannot fit distinct output frames")
    clip = _clip_for_source(asset)
    edits, cursor = [], 0
    for first, last, candidate in ranges:
        count = last-first
        edits.append({"id": "speech-"+candidate["id"], "asset_id": asset["id"], "clip_id": clip["id"],
            "source": asset["path"], "kind": "video", "source_start": first/fps, "source_end": last/fps,
            "duration_frames": count, "timeline_start_frame": cursor, "timeline_end_frame": cursor+count,
            "speed_points": [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}], "average_speed": 1,
            "section": "speech", "effects": {"flash": 0, "shake": 0, "zoom": 1, "grade": "none"},
            "reframe": {"mode": "auto"}, "tags": ["speech"], "shot_type": "medium",
            "selection_reason": candidate["reason"], "candidate_id": candidate["id"]})
        cursor += count
    plan = {"schema_version": 2, "mode": "speech", "revision": 0,
        "audio": {"path": asset["path"], "start": 0, "duration": max(asset["duration"], cursor/fps)},
        "audio_mix": {"version": 1, "replace_legacy": True,
            "source_audio": {"enabled": True, "role": "speech", "gain_db": 0}, "tracks": [],
            "ducking": {"enabled": True, "threshold_db": -35, "reduction_db": 12, "attack": .03, "release": .3}},
        "output": {"fps": fps, "width": width, "height": height}, "duration_frames": cursor,
        "duration": cursor/fps, "requested_duration": cursor/fps, "preset": "speech",
        "sections": [{"name": "speech", "start_frame": 0, "end_frame": cursor}], "beat_frames": [],
        "assets": [deepcopy(asset)], "clips": [clip], "edits": edits, "diagnostics": [],
        "policies": {"allow_repeats": False, "min_speed": 1, "max_speed": 4,
            "allow_slow_motion": False, "slow_motion_prompt": "", "interpolation": "none"},
        "speech": {"transcripts": [transcript], "candidates": candidates,
            "selected": [c["id"] for c in chosen], "pause_limit": pause_limit, "padding": padding,
            "caption_mode": "original", "captions_enabled": captions, "review_status": "not_reviewed"}}
    refresh_source_captions(plan)
    validate_plan(plan)
    return plan


def _mapped_frame(edit, source_time):
    fraction = float(inverse_source_times(edit, [source_time])[0])
    return math.floor(edit["timeline_start_frame"]+fraction*edit["duration_frames"]+.5)


def _caption_segments(transcript, mode):
    for segment in transcript["segments"]:
        if mode != "original" or not segment.get("words"):
            yield segment
            continue
        groups, group = [], []
        for word in segment["words"]:
            if group and (len(group) >= 7 or len(_join_words(group+[word])) > 42
                          or word["end"]-group[0]["start"] > 3 or word["start"]-group[-1]["end"] > .6):
                groups.append(group)
                group = []
            group.append(word)
        if group:
            groups.append(group)
        for words in groups:
            if len(groups) == 1:
                yield segment
            else:
                yield {**segment, "id": segment["id"]+":"+words[0]["id"], "segment_id": segment["id"],
                       "words": words, "text": _join_words(words), "start": words[0]["start"], "end": words[-1]["end"]}


def _caption_mapping_edits(plan):
    """Visual B-roll cuts must not restart a continuous spoken caption."""
    spans = []
    for shot in plan["edits"]:
        edit = deepcopy(mapping_edit(shot, "speech"))
        edit.pop("audio_source", None)
        prior = spans[-1] if spans else None
        flat = lambda e: not e.get("action_anchor") and len({p["speed"] for p in e.get("speed_points", [])}) <= 1
        if (prior and edit["kind"] == prior["kind"] == "video" and edit["asset_id"] == prior["asset_id"]
                and abs(prior["source_end"]-edit["source_start"]) < 1e-7 and flat(prior) and flat(edit)
                and abs((prior["source_end"]-prior["source_start"])/prior["duration_frames"]
                        -(edit["source_end"]-edit["source_start"])/edit["duration_frames"]) < 1e-9):
            prior.update(source_end=edit["source_end"], timeline_end_frame=edit["timeline_end_frame"],
                         duration_frames=prior["duration_frames"]+edit["duration_frames"])
        else:
            spans.append(edit)
    return spans


def refresh_source_captions(plan):
    speech = plan.get("speech", {})
    # Output-timed captions remain unchanged after picture revisions.
    manual = [c for c in plan.get("subtitles", []) if not c.get("source_caption")]
    if not speech.get("captions_enabled", False):
        if "speech" in plan:
            plan["subtitles"] = manual
        return
    mode, language = speech.get("caption_mode", "original"), speech.get("caption_language")
    cues = []
    mappings = _caption_mapping_edits(plan)
    for transcript in speech.get("transcripts", []):
        for segment in _caption_segments(transcript, mode):
            for shot in mappings:
                edit = shot
                if edit.get("kind") != "video" or not source_matches(edit, transcript["source_id"]):
                    continue
                start, end = max(segment["start"], edit["source_start"]), min(segment["end"], edit["source_end"])
                if end <= start:
                    continue
                begin_frame, end_frame = _mapped_frame(edit, start), _mapped_frame(edit, end)
                if end_frame <= begin_frame:
                    continue
                visible, mapped = [], []
                for word in segment.get("words", []):
                    first, last = max(start, word["start"]), min(end, word["end"])
                    if last <= first:
                        continue
                    a, b = max(begin_frame, _mapped_frame(edit, first)), min(end_frame, _mapped_frame(edit, last))
                    if b > a:
                        visible.append(word)
                        mapped.append({"id": word["id"], "text": word["text"].strip(), "start_frame": a, "end_frame": b})
                original = _join_words(visible) if visible else segment["text"]
                translation = segment.get("translations", {}).get(language)
                if mode != "original" and not translation:
                    raise ValueError(f"Missing supplied {language} translation for {segment['id']}")
                text = original if mode == "original" else translation if mode == "translated" else original+"\n"+translation
                cue = {"id": f"src-{segment['id']}@{shot['id']}", "source_caption": True,
                       "source_id": transcript["source_id"], "segment_id": segment.get("segment_id", segment["id"]), "shot_id": shot["id"],
                       "text": text, "start_frame": begin_frame, "end_frame": end_frame,
                       "source_start": start, "source_end": end,
                       "translation_review_required": bool(translation and (segment.get("translations_stale") or start > segment["start"] or end < segment["end"]))}
                if cue["id"] in speech.get("detached_captions", []):
                    continue
                if mapped and mode != "translated":
                    cue["words"] = _coalesce_words(mapped, original)
                cues.append(cue)
    plan["subtitles"] = sorted(manual+cues, key=lambda c: (c["start_frame"], c["end_frame"]))


def _transcript(plan, identifier=None):
    items = plan.get("speech", {}).get("transcripts", [])
    if identifier is None and len(items) == 1:
        return items[0]
    return next((t for t in items if t["id"] == identifier), None)


def recognized_intervals(transcript):
    """Actual words expose ASR holes even inside a long recognizer segment."""
    return sorted((item["start"], item["end"]) for segment in transcript["segments"]
                  for item in (segment.get("words") or [segment]))


def _split_segments_around_gap(transcript, start, end):
    result = []
    for segment in transcript["segments"]:
        if segment["start"] >= end or segment["end"] <= start:
            result.append(segment)
            continue
        words = segment.get("words", [])
        parts = [[w for w in words if w["end"] <= start], [w for w in words if w["start"] >= end]]
        for index, part in enumerate(p for p in parts if p):
            item = deepcopy(segment)
            item.update(start=part[0]["start"], end=part[-1]["end"], words=part, text=_join_words(part))
            if index:
                item["id"] += "-gap-tail-"+hashlib.sha256(f"{start}:{end}".encode()).hexdigest()[:8]
            if item.get("translations"):
                item["superseded_translations"] = item.pop("translations")
                item["translations_stale"] = True
            result.append(item)
    return result


def _broll_interval(plan, shot, offset=0, duration=None):
    """Split a speech shot for a bounded B-roll insert, retaining voice ranges.

    Speech plans use natural speed. A cut through an existing nonlinear warp
    needs a new explicit retime plan and is rejected instead of approximated.
    """
    fps, count = plan["output"]["fps"], shot["duration_frames"]
    if not isinstance(offset, (int, float)) or not math.isfinite(offset) or offset < 0:
        raise ValueError("B-roll offset must be nonnegative seconds within the shot")
    start = math.floor(offset*fps+.5)
    finish = count if duration is None else start+math.floor(duration*fps+.5)
    if not 0 <= start < finish <= count:
        raise ValueError("B-roll insert must fit within the selected shot")
    if start == 0 and finish == count:
        return shot
    from timeline_map import source_times
    for mapping in (shot, shot.get("audio_source")):
        if mapping and (mapping.get("action_anchor") or len({p["speed"] for p in mapping.get("speed_points", [])}) > 1):
            raise ValueError("Bounded B-roll insertion requires a constant-speed shot; use a whole-shot insert for nonlinear edits")
    pieces, inserted = [], None
    boundaries = sorted(set([0, start, finish, count]))
    for a, b in zip(boundaries, boundaries[1:]):
        part = deepcopy(shot)
        part["id"] = shot["id"] if a == 0 else f"{shot['id']}@{a}-{b}"
        part["duration_frames"] = b-a
        part["timeline_start_frame"] = shot["timeline_start_frame"]+a
        part["timeline_end_frame"] = shot["timeline_start_frame"]+b
        if part["kind"] == "video":
            begin, end = source_times(shot, [a/count, b/count])
            part.update(source_start=float(begin), source_end=float(end))
        if part.get("audio_source"):
            begin, end = source_times(shot["audio_source"], [a/count, b/count])
            part["audio_source"].update(source_start=float(begin), source_end=float(end))
        if a == start and b == finish:
            inserted = part
        pieces.append(part)
    index = plan["edits"].index(shot)
    plan["edits"][index:index+1] = pieces
    return inserted


def apply_speech_operation(plan, operation):
    kind = operation["op"]
    speech = plan.setdefault("speech", {"transcripts": [], "captions_enabled": True, "caption_mode": "original"})
    if kind == "speech_transcript":
        transcript = normalize_transcript(operation["transcript"], operation["source_id"])
        existing = speech.setdefault("transcripts", [])
        existing[:] = [t for t in existing if t["source_id"] != transcript["source_id"]]+[transcript]
        speech["captions_enabled"] = True
    elif kind == "speech_correct":
        transcript = _transcript(plan, operation.get("transcript_id"))
        if transcript is None:
            raise ValueError("Specify a known transcript_id")
        updates = operation.get("corrections", {})
        glossary = operation.get("glossary", {})
        if not isinstance(updates, dict) or not isinstance(glossary, dict) or not (updates or glossary):
            raise ValueError("Corrections/glossary must be nonempty text mappings")
        known = {x["id"] for s in transcript["segments"] for x in [s]+s.get("words", [])}
        if set(updates)-known:
            raise ValueError(f"Unknown correction IDs: {sorted(set(updates)-known)}")
        for key, value in {**updates, **glossary}.items():
            if not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip():
                raise ValueError("Corrections must map IDs/terms to nonempty text")
        for segment in transcript["segments"]:
            for word in segment.get("words", []):
                before = word["text"]
                after = updates.get(word["id"], before)
                for old, new in glossary.items():
                    after = re.sub(r"(?<!\w)"+re.escape(old)+r"(?!\w)", lambda m: new, after, flags=re.IGNORECASE)
                if after != before:
                    word.setdefault("original_text", before)
                    word["text"] = after
                    transcript["corrections"].append({"id": word["id"], "before": before, "after": after})
            before = segment["text"]
            if segment["id"] in updates:
                segment["text"] = updates[segment["id"]]
                # A free phrase rewrite cannot keep allegedly aligned old words.
                segment["superseded_words"] = segment.pop("words", [])
            elif segment.get("words"):
                segment["text"] = _join_words(segment["words"])
            else:
                for old, new in glossary.items():
                    segment["text"] = re.sub(r"(?<!\w)"+re.escape(old)+r"(?!\w)", lambda m: new, segment["text"], flags=re.IGNORECASE)
            if segment["text"] != before:
                transcript["corrections"].append({"id": segment["id"], "before": before, "after": segment["text"]})
                if segment.get("translations"):
                    segment["translations_stale"] = True
    elif kind == "speech_translate":
        transcript = _transcript(plan, operation.get("transcript_id"))
        if transcript is None:
            raise ValueError("Specify a known transcript_id")
        language, values = operation.get("language"), operation.get("translations")
        if not isinstance(language, str) or not language.strip() or not isinstance(values, dict) or not values:
            raise ValueError("Supply target language and a segment-ID to translated-text mapping")
        known = {s["id"] for s in transcript["segments"]}
        if set(values)-known:
            raise ValueError("Translations reference unknown segment IDs")
        for segment in transcript["segments"]:
            if segment["id"] in values:
                value = values[segment["id"]]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Supplied translation must be nonempty text")
                segment.setdefault("translations", {})[language] = value
                segment.pop("translations_stale", None)
        speech.update(caption_mode=operation.get("mode", "bilingual"), caption_language=language)
    elif kind == "speech_captions":
        speech.update(captions_enabled=operation.get("enabled", True), caption_mode=operation.get("mode", "original"))
        if operation.get("language"):
            speech["caption_language"] = operation["language"]
    elif kind == "speech_broll":
        if operation.get("asset") and operation.get("clip"):
            asset, incoming = deepcopy(operation["asset"]), deepcopy(operation["clip"])
            if asset["id"] not in {a["id"] for a in plan["assets"]}:
                plan["assets"].append(asset)
            if incoming["id"] not in {c["id"] for c in plan["clips"]}:
                plan["clips"].append(incoming)
        shot = next((e for e in plan["edits"] if e["id"] == operation.get("shot_id")), None)
        clip = next((c for c in plan.get("clips", []) if c["id"] == operation.get("clip_id")), None)
        if shot is None or clip is None:
            raise ValueError("B-roll needs a known shot_id and clip_id")
        shot = _broll_interval(plan, shot, operation.get("offset", 0), operation.get("duration"))
        begin = operation.get("source_start", clip["start"])
        duration = shot["duration_frames"]/plan["output"]["fps"]
        end = begin+duration if clip["kind"] == "video" else clip["end"]
        if begin < clip["start"] or (clip["kind"] == "video" and end > clip["end"]+1e-7):
            raise ValueError("B-roll source is too short; shorten/split the shot or use a still")
        if "audio_source" not in shot:
            shot["audio_source"] = {key: deepcopy(shot[key]) for key in
                ("source", "asset_id", "kind", "source_start", "source_end", "speed_points", "action_anchor") if key in shot}
        shot.update(source=clip["source"], asset_id=clip["asset_id"], clip_id=clip["id"], kind=clip["kind"],
                    source_start=begin, source_end=end, speed_points=[{"at": 0, "speed": 1}, {"at": 1, "speed": 1}],
                    reframe={"mode": operation.get("reframe", "auto")}, average_speed=1)
        shot.pop("action_anchor", None)
        shot["broll"] = True
    elif kind in ("anchor_set", "action_set"):
        key = "anchors" if kind == "anchor_set" else "actions"
        value = deepcopy(operation["value"])
        if not value.get("id"):
            raise ValueError("An anchor/action needs a stable id")
        plan.setdefault(key, [])[:] = [v for v in plan.get(key, []) if v["id"] != value["id"]]+[value]
    elif kind == "speech_retry_result":
        transcript = _transcript(plan, operation.get("transcript_id"))
        if transcript is None:
            raise ValueError("Unknown transcript")
        start, end = operation["start"], operation["end"]
        _positive_span(start, end)
        existing = transcript["segments"]
        if any(a < end and b > start for a, b in recognized_intervals(transcript)):
            raise ValueError("Retry range overlaps existing recognized words; choose an uncovered gap")
        incoming = normalize_transcript(operation["transcript"], transcript["source_id"])
        if any(s["start"] < start-1e-6 or s["end"] > end+1e-6 for s in incoming["segments"]):
            raise ValueError("Retry transcript lies outside requested source gap")
        existing = _split_segments_around_gap(transcript, start, end)
        existing.extend(incoming["segments"])
        existing.sort(key=lambda s: s["start"])
        transcript["segments"] = existing
        transcript.setdefault("retry_history", []).append({"start": start, "end": end, "segments_added": len(incoming["segments"])})
    else:
        raise ValueError(f"Unknown speech operation: {kind}")
    for transcript in speech.get("transcripts", []):
        normalize_transcript(transcript, transcript["source_id"])
    speech["candidates"] = [c for t in speech.get("transcripts", []) for c in phrase_candidates(t)]


def validate_speech(plan):
    speech = plan.get("speech")
    if speech is None:
        return
    if not isinstance(speech, dict) or not isinstance(speech.get("transcripts", []), list):
        raise ValueError("speech must contain a transcripts list")
    assets = {str(a["id"]): a for a in plan["assets"]}
    ids = set()
    for transcript in speech.get("transcripts", []):
        if transcript["source_id"] not in assets:
            raise ValueError("Transcript source_id must reference an asset")
        normalize_transcript(transcript, transcript["source_id"], assets[transcript["source_id"]].get("duration"))
        if transcript["id"] in ids:
            raise ValueError("Transcript IDs must be unique")
        ids.add(transcript["id"])
    if speech.get("caption_mode", "original") not in ("original", "translated", "bilingual"):
        raise ValueError("caption mode must be original, translated or bilingual")
    for shot in plan["edits"]:
        source = shot.get("audio_source")
        if source:
            asset = assets.get(str(source.get("asset_id")))
            if asset is None or source.get("source") != asset.get("path"):
                raise ValueError("B-roll audio_source must reference the original asset")
            _positive_span(source.get("source_start"), source.get("source_end"))
            if source["source_end"] > asset.get("duration", float("inf"))+1e-6:
                raise ValueError("B-roll audio_source exceeds its media")
            from timeline_map import source_times
            source_times(source, [0, .5, 1])

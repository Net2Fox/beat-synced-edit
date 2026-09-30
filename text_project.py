"""Editing operations for persistent, output-timed title and caption tracks."""

from copy import deepcopy
import math


STYLE_PRESETS = {
    "clean": {"color": "#FFFFFF", "background": None, "stroke_color": "#000000", "highlight": False},
    "boxed": {"color": "#FFFFFF", "background": "#10151ECC", "stroke_color": "#000000", "highlight": False},
    "karaoke": {"color": "#FFFFFF", "highlight_color": "#FFE34D", "background": "#10151ECC", "highlight": True},
}

TEXT_OPERATIONS = {"title_add", "title_update", "title_remove", "subtitle_add", "subtitle_update",
                   "subtitle_remove", "subtitles_replace", "subtitles_shift", "text_style", "text_clear"}


def _frame(seconds, fps):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        raise ValueError("Text start/end times must be finite seconds")
    return math.floor(seconds * fps + .5)


def _values(values, fps):
    if not isinstance(values, dict):
        raise ValueError("Text values must be an object")
    allowed = {"id", "text", "start", "end", "start_frame", "end_frame", "style", "words"}
    if set(values) - allowed:
        raise ValueError(f"Unknown text fields: {sorted(set(values) - allowed)}")
    result = deepcopy(values)
    for key in ("start", "end"):
        if key in result:
            if key + "_frame" in result:
                raise ValueError(f"Specify {key} seconds or {key}_frame, not both")
            result[key + "_frame"] = _frame(result.pop(key), fps)
    return result


def _find(track, identifier):
    for cue in track:
        if cue["id"] == identifier:
            return cue
    raise ValueError(f"Unknown text cue id: {identifier!r}")


def apply_text_operation(plan, operation):
    """Mutate a working copy; caller validates and writes the complete transaction."""
    kind = operation["op"]
    fps = plan["output"]["fps"]
    if kind in ("text_style", "text_clear"):
        track = operation.get("track")
        if track not in ("titles", "subtitles"):
            raise ValueError("track must be titles or subtitles")
        if kind == "text_clear":
            plan[track] = []
            return
        values = operation.get("values", {})
        if not isinstance(values, dict):
            raise ValueError("Text style values must be an object")
        preset = operation.get("preset")
        if preset is not None and preset not in STYLE_PRESETS:
            raise ValueError(f"Unknown text style preset: {preset!r}")
        key = "title_style" if track == "titles" else "subtitle_style"
        plan.setdefault(key, {}).update(deepcopy(STYLE_PRESETS.get(preset, {})))
        plan[key].update(deepcopy(values))
        return
    if kind == "subtitles_replace":
        cues = operation.get("cues")
        if not isinstance(cues, list):
            raise ValueError("subtitles_replace requires a cues array")
        plan["subtitles"] = [_values(cue, fps) for cue in cues]
        return
    if kind == "subtitles_shift":
        delta = _frame(operation.get("seconds"), fps)
        limit = plan["duration_frames"]
        shifted = []
        for original in plan.get("subtitles", []):
            cue = deepcopy(original)
            start, end = cue["start_frame"] + delta, cue["end_frame"] + delta
            if end <= 0 or start >= limit:
                continue
            cue["start_frame"], cue["end_frame"] = max(0, start), min(limit, end)
            words = []
            for original_word in cue.get("words", []):
                word = deepcopy(original_word)
                word["start_frame"] = max(cue["start_frame"], word["start_frame"] + delta)
                word["end_frame"] = min(cue["end_frame"], word["end_frame"] + delta)
                if word["end_frame"] > word["start_frame"]:
                    words.append(word)
            if "words" in cue:
                cue["words"] = words
            shifted.append(cue)
        plan["subtitles"] = shifted
        return
    track_name = "titles" if kind.startswith("title_") else "subtitles"
    track = plan.setdefault(track_name, [])
    action = kind.rsplit("_", 1)[-1]
    if action == "add":
        cue = _values(operation.get("values"), fps)
        if "id" not in cue:
            prefix = "title" if track_name == "titles" else "sub"
            existing = {c["id"] for c in track}
            number = 1
            while f"{prefix}-{number:03d}" in existing:
                number += 1
            cue["id"] = f"{prefix}-{number:03d}"
        track.append(cue)
    elif action == "update":
        cue = _find(track, operation.get("id"))
        values = _values(operation.get("values"), fps)
        if "id" in values and values["id"] != cue["id"]:
            raise ValueError("Updating text must preserve its stable id")
        if "text" in values and "words" not in values:
            # Editing a phrase invalidates its old per-word alignment.
            cue.pop("words", None)
        elif "words" in cue and "words" not in values and any(k in values for k in ("start_frame", "end_frame")):
            old_start, old_end = cue["start_frame"], cue["end_frame"]
            new_start, new_end = values.get("start_frame", old_start), values.get("end_frame", old_end)
            if new_end <= new_start:
                raise ValueError("Updated caption end must be after its start")
            ratio = (new_end - new_start) / (old_end - old_start)
            for word in cue["words"]:
                word["start_frame"] = max(new_start, round(new_start + (word["start_frame"] - old_start) * ratio))
                word["end_frame"] = min(new_end, round(new_start + (word["end_frame"] - old_start) * ratio))
            cue["words"] = [word for word in cue["words"] if word["end_frame"] > word["start_frame"]]
        if "style" in values:
            style = values.pop("style")
            if not isinstance(style, dict):
                raise ValueError("Cue style must be an object")
            cue.setdefault("style", {}).update(style)
        cue.update(values)
    elif action == "remove":
        track.remove(_find(track, operation.get("id")))
    else:
        raise ValueError(f"Unknown text operation: {kind}")
    track.sort(key=lambda cue: (cue.get("start_frame", -1), cue.get("end_frame", -1)))

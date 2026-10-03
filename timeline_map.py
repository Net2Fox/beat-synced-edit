"""Canonical source/output mapping and persistent semantic anchors.

Source intervals are half open. Mapping endpoints is allowed for cue boundaries.
The inverse solves the exact monotone render curve, not a linear approximation.
"""
from copy import deepcopy
import math
import numpy as np


def _positive_float(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _integrated_speed(points, positions):
    """Integrate a positive curve with zero slope at every control point."""
    if not points:
        points = [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]
    points = sorted((float(p["at"]), _positive_float(p["speed"], "speed")) for p in points)
    if any(not math.isfinite(p[0]) or not 0 <= p[0] <= 1 for p in points):
        raise ValueError("Speed point positions must be between 0 and 1")
    if any(a[0] == b[0] for a, b in zip(points, points[1:])):
        raise ValueError("Speed point positions must be unique")
    if points[0][0] > 0:
        points.insert(0, (0, points[0][1]))
    if points[-1][0] < 1:
        points.append((1, points[-1][1]))
    values = np.zeros_like(positions, dtype=np.float64)
    total = 0.0
    for (a, sa), (b, sb) in zip(points, points[1:]):
        width = b - a
        x = np.clip(positions - a, 0, width)
        values += sa * x + (sb - sa) * (x / 2 - width * np.sin(np.pi * x / width) / (2 * np.pi))
        total += width * (sa + sb) / 2
    if total <= 0:
        raise ValueError("Speed curve must span a positive interval")
    return values / total


def _anchor_warp(progress, at, target):
    """Monotone C1 interpolation of (0,0), (at,target), (1,1)."""
    left = target / at
    right = (1 - target) / (1 - at)
    middle = 2 * left * right / (left + right)
    result = np.empty_like(progress)
    for mask, x0, x1, y0, y1, m0, m1 in (
        (progress <= at, 0, at, 0, target, left, middle),
        (progress > at, at, 1, target, 1, middle, right),
    ):
        t = (progress[mask] - x0) / (x1 - x0)
        result[mask] = ((2*t**3 - 3*t**2 + 1)*y0 + (t**3 - 2*t**2 + t)*(x1-x0)*m0
                        + (-2*t**3 + 3*t**2)*y1 + (t**3-t**2)*(x1-x0)*m1)
    return result


def source_times(edit, positions):
    """Map normalized output times to absolute source seconds, including an anchor.

    Speed points are relative speed weights; the integral is scaled to exactly
    consume the selected source span. Anchoring smoothly redistributes that span
    and guarantees the action's source_time at its output_fraction.
    """
    positions = np.asarray(positions, dtype=np.float64)
    if np.any(~np.isfinite(positions)) or np.any((positions < 0) | (positions > 1)):
        raise ValueError("Output positions must be between 0 and 1")
    start, end = float(edit.get("source_start", 0)), float(edit.get("source_end", 0))
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Video source_start/source_end must form a positive finite span")
    points = edit.get("speed_points")
    progress = _integrated_speed(points, positions)
    anchor = edit.get("action_anchor")
    if anchor:
        fraction = float(anchor["output_fraction"])
        target = (float(anchor["source_time"]) - start) / (end - start)
        if not math.isfinite(fraction) or not math.isfinite(target):
            raise ValueError("Action anchor must be finite")
        if fraction in (0, 1) and abs(target - fraction) < 1e-8:
            pass
        elif 0 < fraction < 1 and 0 < target < 1:
            at = float(_integrated_speed(points, np.array([fraction]))[0])
            progress = _anchor_warp(progress, at, target)
        else:
            raise ValueError("An interior action anchor must lie inside the selected source span")
    return start + (end - start) * progress


def inverse_source_times(edit, times):
    """Return normalized output positions for absolute source seconds."""
    times = np.asarray(times, dtype=np.float64)
    start, end = float(edit["source_start"]), float(edit["source_end"])
    if np.any(~np.isfinite(times)) or np.any((times < start-1e-8) | (times > end+1e-8)):
        raise ValueError("Source times must lie inside the edit")
    low, high = np.zeros_like(times), np.ones_like(times)
    for _ in range(48):
        middle = (low+high)/2
        before = source_times(edit, middle) < times
        low, high = np.where(before, middle, low), np.where(before, high, middle)
    return (low+high)/2


def mapping_edit(shot, domain="picture"):
    if domain not in ("picture", "speech"):
        raise ValueError("mapping domain must be picture or speech")
    if domain == "speech" and shot.get("audio_source"):
        return {**shot, **shot["audio_source"], **{k: shot[k] for k in
                ("id", "timeline_start_frame", "timeline_end_frame", "duration_frames")}}
    return shot


def source_matches(edit, source_id):
    return str(source_id) in (str(edit.get("asset_id")), str(edit.get("source_id")), str(edit.get("source")))


def source_to_output(plan, source_id, source_time, domain="picture", shot_id=None):
    """All occurrences, never silently choosing one when footage is repeated."""
    found = []
    for shot in plan["edits"]:
        edit = mapping_edit(shot, domain)
        if shot_id is not None and shot["id"] != shot_id:
            continue
        if edit.get("kind") != "video" or not source_matches(edit, source_id):
            continue
        if edit["source_start"]-1e-8 <= source_time <= edit["source_end"]+1e-8:
            fraction = float(inverse_source_times(edit, [source_time])[0])
            frame = edit["timeline_start_frame"] + fraction*edit["duration_frames"]
            found.append({"shot_id": shot["id"], "frame": frame, "seconds": frame/plan["output"]["fps"]})
    return found


def output_to_source(plan, frame, domain="picture"):
    if not math.isfinite(frame) or not 0 <= frame < plan["duration_frames"]:
        raise ValueError("Output frame must lie inside the project")
    shot = next(e for e in plan["edits"] if e["timeline_start_frame"] <= frame < e["timeline_end_frame"])
    edit = mapping_edit(shot, domain)
    fraction = (frame-edit["timeline_start_frame"])/edit["duration_frames"]
    time = float(source_times(edit, [fraction])[0]) if edit["kind"] == "video" else 0
    return {"source_id": edit["asset_id"], "source": edit["source"], "time": time, "shot_id": shot["id"]}


def resolve_anchor(plan, anchor):
    """Resolve a semantic anchor to zero or more output frame positions.

    Missing/trimmed anchors resolve to [], and persisted state records that fact.
    offset_frames is applied after resolution, never reinterpreted as seconds.
    """
    if not isinstance(anchor, dict):
        raise ValueError("anchor must be an object")
    kind = anchor.get("type")
    if kind in ("word", "shot", "action", "event") and (not isinstance(anchor.get("id"), str) or not anchor["id"]):
        raise ValueError("Semantic anchors require a nonempty stable id")
    edge = anchor.get("edge", "start")
    if edge not in ("start", "end"):
        raise ValueError("anchor edge must be start or end")
    values = []
    if kind == "source":
        time = anchor.get("time")
        if not isinstance(time, (int, float)) or isinstance(time, bool) or not math.isfinite(time) or time < 0 or anchor.get("source_id") is None:
            raise ValueError("Source anchors need source_id and nonnegative finite time")
        values = [x["frame"] for x in source_to_output(plan, anchor["source_id"], float(anchor["time"]),
                  anchor.get("domain", "picture"), anchor.get("shot_id"))]
    elif kind == "shot":
        values = [e[f"timeline_{edge}_frame"] for e in plan["edits"] if e["id"] == anchor.get("id")]
    elif kind == "beat":
        index = anchor.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("beat anchor index must be a nonnegative integer")
        if index < len(plan.get("beat_frames", [])):
            values = [plan["beat_frames"][index]]
    elif kind == "event":
        values = [e["output_frame"] for e in plan.get("music_structure", {}).get("events", [])
                  if e.get("id") == anchor.get("id") and "output_frame" in e]
    elif kind == "word":
        for transcript in plan.get("speech", {}).get("transcripts", []):
            for segment in transcript["segments"]:
                for word in segment.get("words", []):
                    if word["id"] == anchor.get("id"):
                        values += [x["frame"] for x in source_to_output(plan, transcript["source_id"], word[edge],
                                   "speech", anchor.get("shot_id"))]
    elif kind == "action":
        for action in plan.get("actions", []):
            if action.get("id") == anchor.get("id"):
                values += [x["frame"] for x in source_to_output(plan, action["source_id"], action["time"],
                                   anchor.get("domain", "picture"), anchor.get("shot_id"))]
    else:
        raise ValueError("anchor type must be source, word, beat, event, shot or action")
    offset = anchor.get("offset_frames", 0)
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
        raise ValueError("anchor offset_frames must be finite")
    return sorted(set(float(frame)+offset for frame in values))


def refresh_anchors(plan):
    for item in plan.get("anchors", []):
        item["resolved_frames"] = resolve_anchor(plan, item["anchor"])
        item["status"] = "resolved" if item["resolved_frames"] else "unresolved"
    for track in ("titles", "graphics"):
        for cue in plan.get(track, []):
            if cue.get("anchor"):
                values = resolve_anchor(plan, cue["anchor"])
                if len(values) != 1:
                    raise ValueError(f"{track} anchor must resolve uniquely; specify shot_id: {cue.get('id')}")
                duration = cue.get("anchor_duration_frames", cue["end_frame"]-cue["start_frame"])
                cue["anchor_duration_frames"] = duration
                cue["start_frame"] = math.floor(values[0]+.5)
                cue["end_frame"] = cue["start_frame"]+duration


def validate_timeline_metadata(plan):
    ids = set()
    for item in plan.get("anchors", []):
        if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
            raise ValueError("Persistent anchor IDs must be unique nonempty strings")
        ids.add(item["id"])
        resolve_anchor(plan, item.get("anchor"))
    ids = set()
    for action in plan.get("actions", []):
        if not action.get("id") or action["id"] in ids:
            raise ValueError("Action IDs must be unique nonempty strings")
        ids.add(action["id"])
        if action.get("source_id") is None or not isinstance(action.get("time"), (int, float)) or not math.isfinite(action["time"]) or action["time"] < 0:
            raise ValueError("Actions need source_id and nonnegative finite time")
        if str(action["source_id"]) not in {str(a["id"]) for a in plan.get("assets", [])}:
            raise ValueError("Action source_id must reference a project asset")

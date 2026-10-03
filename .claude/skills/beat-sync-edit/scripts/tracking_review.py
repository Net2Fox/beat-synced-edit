"""Reviewable camera paths in source time, including explicit user corrections."""
from __future__ import annotations

import math


def validate_reframe(reframe, source_start=0, source_end=None):
    if not isinstance(reframe, dict):
        raise ValueError("reframe must be an object")
    sample = reframe.get("sample_fps", 5)
    threshold = reframe.get("confidence_threshold", .55)
    for value, name, low, high in ((sample, "sample_fps", .1, 60), (threshold, "confidence_threshold", 0, 1)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"reframe.{name} must be between {low} and {high}")
    points = reframe.get("keyframes", [])
    if not isinstance(points, list):
        raise ValueError("reframe.keyframes must be a list")
    previous = -1
    for point in points:
        if not isinstance(point, dict) or not {"time", "cx", "cy"} <= point.keys():
            raise ValueError("Camera keyframes require time, cx and cy")
        for key in ("time", "cx", "cy"):
            value = point[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Camera keyframes must contain finite numbers")
        if point["time"] <= previous or point["time"] < 0:
            raise ValueError("Camera keyframe times must be nonnegative and strictly increasing")
        if source_end is not None and point["time"] > source_end + 1e-6:
            raise ValueError("Camera keyframe time exceeds selected source end")
        if not 0 <= point["cx"] <= 1 or not 0 <= point["cy"] <= 1:
            raise ValueError("Camera keyframe centers must lie in the normalized image")
        previous = point["time"]


def resolve_track(edit):
    from smart_reframe import track_subject
    reframe = edit.get("reframe", {})
    start, end = float(edit.get("source_start", 0)), float(edit.get("source_end", 0))
    validate_reframe(reframe, start, end)
    if reframe.get("keyframes"):
        points = [{**point, "method": "manual_keyframe", "confidence": 1.0} for point in reframe["keyframes"]]
        return points
    if reframe.get("mode", "auto") != "auto":
        return []
    beginning = float(reframe.get("subject_start", start)) if reframe.get("subject") else start
    if beginning > start or beginning < 0:
        raise ValueError("reframe.subject_start must precede the selected source range")
    return track_subject(edit["source"], beginning, end, subject=reframe.get("subject"),
                         sample_fps=reframe.get("sample_fps", 5))


def tracking_report(edit, track):
    """Low confidence is a review signal, never proof of tracking identity."""
    threshold = edit.get("reframe", {}).get("confidence_threshold", .55)
    start, end = edit.get("source_start", 0), edit.get("source_end", 0)
    relevant = [p for p in track if start - 1e-6 <= p["time"] <= end + 1e-6]
    low = [p for p in relevant if p.get("confidence", 0) < threshold]
    intervals = []
    for index, point in enumerate(relevant):
        if point.get("confidence", 0) >= threshold:
            continue
        until = relevant[index + 1]["time"] if index + 1 < len(relevant) else end
        if intervals and abs(intervals[-1]["end"] - point["time"]) < 1e-5:
            intervals[-1]["end"] = until
        else:
            intervals.append({"start": point["time"], "end": until})
    return {"shot_id": edit.get("id"), "source": edit["source"], "timebase": "source_seconds",
            "method": "manual_keyframes" if edit.get("reframe", {}).get("keyframes") else edit.get("reframe", {}).get("mode", "auto"),
            "confidence_threshold": threshold, "samples": len(relevant), "low_confidence_samples": len(low),
            "low_confidence_intervals": intervals, "review_required": bool(low),
            "identity_verified": False, "visual_review": "not_reviewed", "keyframes": track}

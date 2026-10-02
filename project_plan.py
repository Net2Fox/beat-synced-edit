#!/usr/bin/env python3
"""Plan exact-frame, beat-aware edits from a portable media library.

No source interval is repeated without explicit consent. Musical section guesses
are inspectable and may be replaced by manual sections in seconds or frames.
This module is deliberately independent of video/ML dependencies.
"""

import argparse
import bisect
from copy import deepcopy
import json
import math
from pathlib import Path, PureWindowsPath

from edit_presets import get_preset


SECTION_NAMES = ("intro", "build", "drop", "outro")
GRADES = ("none", "neutral", "cinematic", "cool", "vivid", "warm")


def _number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return float(value)


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _absolute(path):
    return isinstance(path, str) and (Path(path).is_absolute() or PureWindowsPath(path).is_absolute())


def _assets(library):
    assets = library.get("assets", [])
    if isinstance(assets, dict):
        return {str(key): {"id": str(key), **item} for key, item in assets.items()}
    return {str(item["id"]): item for item in assets}


def _energy_points(beatmap):
    points = []
    for point in beatmap.get("energy_curve", beatmap.get("energy", [])):
        if isinstance(point, dict):
            time, energy = point.get("time"), point.get("energy")
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            time, energy = point
        else:
            continue
        points.append((_number(time, "energy time", 0), _number(energy, "energy", 0)))
    return sorted(points)


def _energy_at(points, time):
    if not points:
        return 0.5
    index = bisect.bisect_right([item[0] for item in points], time)
    if index == 0:
        return points[0][1]
    if index == len(points):
        return points[-1][1]
    left, right = points[index - 1], points[index]
    if right[0] == left[0]:
        return right[1]
    fraction = (time - left[0]) / (right[0] - left[0])
    return left[1] + fraction * (right[1] - left[1])


def _sections(manual, beatmap, start, frame_count, fps, beat_frames):
    if manual is not None:
        if not isinstance(manual, list) or not manual:
            raise ValueError("sections must be a nonempty list of {name,start,end} in output seconds")
        result = []
        for item in manual:
            if not isinstance(item, dict):
                raise ValueError("Each section must be an object")
            begin = item.get("start_frame")
            end = item.get("end_frame")
            if begin is None:
                begin = round(_number(item.get("start"), "section start", 0) * fps)
            if end is None:
                end = round(_number(item.get("end"), "section end", 0) * fps)
            result.append({"name": item.get("name"), "start_frame": begin, "end_frame": end,
                           "start": begin / fps, "end": end / fps, "method": "manual"})
        _validate_sections(result, frame_count)
        return result

    # Tiny edits need not contain four one-frame musical sections.
    if frame_count < 4:
        return [{"name": "drop", "start_frame": 0, "end_frame": frame_count,
                 "start": 0.0, "end": frame_count / fps, "method": "short-edit"}]
    points = _energy_points(beatmap)
    candidates = [frame for frame in beat_frames if frame_count * .25 <= frame <= frame_count * .72]
    default_drop = round(frame_count * .45)
    drop = min(candidates, key=lambda frame: abs(frame - default_drop)) if candidates else default_drop
    method = "beat-fractions"
    if points and candidates:
        lookback = max(.25, min(2.0, frame_count / fps * .15))
        # Prefer a sustained rise over a single high sample or already loud intro.
        def drop_score(frame):
            time = start + frame / fps
            before = sum(_energy_at(points, time - lookback * n / 4) for n in range(1, 5)) / 4
            after = sum(_energy_at(points, time + lookback * n / 4) for n in range(4)) / 4
            return after - before + .15 * after - .02 * abs(frame - default_drop) / frame_count
        drop = max(candidates, key=drop_score)
        method = "energy-rise-and-beats"
    intro_target = max(1, round(drop * .42))
    intro_candidates = [frame for frame in beat_frames if 0 < frame < drop]
    intro = min(intro_candidates, key=lambda frame: abs(frame - intro_target)) if intro_candidates else intro_target
    outro_target = round(frame_count * .86)
    outro_candidates = [frame for frame in beat_frames if drop < frame < frame_count]
    outro = min(outro_candidates, key=lambda frame: abs(frame - outro_target)) if outro_candidates else outro_target
    boundaries = [0, max(1, min(intro, frame_count - 3)),
                  max(2, min(drop, frame_count - 2)), max(3, min(outro, frame_count - 1)), frame_count]
    for i in range(1, 4):
        boundaries[i] = max(boundaries[i], boundaries[i - 1] + 1)
    result = [{"name": name, "start_frame": boundaries[i], "end_frame": boundaries[i + 1],
               "start": boundaries[i] / fps, "end": boundaries[i + 1] / fps, "method": method}
              for i, name in enumerate(SECTION_NAMES)]
    _validate_sections(result, frame_count)
    return result


def _validate_sections(sections, frame_count):
    position = 0
    for section in sections:
        if section.get("name") not in SECTION_NAMES:
            raise ValueError(f"Unknown section name {section.get('name')!r}; use {SECTION_NAMES}")
        begin = _integer(section.get("start_frame"), "section start_frame", 0)
        end = _integer(section.get("end_frame"), "section end_frame", 1)
        if begin != position or end <= begin or end > frame_count:
            raise ValueError("Sections must cover the complete output contiguously without overlap")
        position = end
    if position != frame_count:
        raise ValueError("Sections must end at duration_frames")


def _slots(sections, beats, recipe, fps):
    result = []
    min_frames = max(1, round(recipe["min_shot"] * fps))
    max_frames = max(min_frames, round(recipe["max_shot"] * fps))
    for section in sections:
        begin, end = section["start_frame"], section["end_frame"]
        interior = [frame for frame in beats if begin < frame < end]
        stride = recipe["beat_stride"][section["name"]]
        boundaries = [begin]
        for frame in interior[stride - 1::stride]:
            if frame - boundaries[-1] >= min_frames and end - frame >= min_frames:
                while frame - boundaries[-1] > max_frames:
                    choices = [beat for beat in interior if boundaries[-1] + min_frames <= beat <= boundaries[-1] + max_frames]
                    boundaries.append(choices[-1] if choices else boundaries[-1] + max_frames)
                if frame > boundaries[-1]:
                    boundaries.append(frame)
        while end - boundaries[-1] > max_frames:
            choices = [beat for beat in interior if boundaries[-1] + min_frames <= beat <= boundaries[-1] + max_frames]
            boundaries.append(choices[-1] if choices else boundaries[-1] + max_frames)
        boundaries.append(end)
        result.extend((left, right, section["name"]) for left, right in zip(boundaries, boundaries[1:]) if right > left)
    return result


def _subtract(interval, used):
    fragments = [interval]
    for used_start, used_end in sorted(used):
        next_fragments = []
        for start, end in fragments:
            if used_end <= start or used_start >= end:
                next_fragments.append((start, end))
            else:
                if used_start > start:
                    next_fragments.append((start, used_start))
                if used_end < end:
                    next_fragments.append((used_end, end))
        fragments = next_fragments
    return fragments


def _union_length(intervals):
    end, total = -math.inf, 0.0
    for begin, stop in sorted(intervals):
        total += max(0.0, stop - max(begin, end))
        end = max(end, stop)
    return total


def _unique_intervals(clips):
    """Split overlapping analysis ranges once, preserving scene boundaries."""
    already, result = {}, []
    for clip in clips:
        if clip["kind"] != "video":
            continue
        pieces = _subtract((clip["start"], clip["end"]), already.get(clip["source"], []))
        result.extend(pieces)
        already.setdefault(clip["source"], []).extend(pieces)
    return result


def _remaining_intervals(clips, used):
    covered = {source: list(intervals) for source, intervals in used.items()}
    remaining = []
    for clip in clips:
        if clip["kind"] != "video":
            continue
        pieces = _subtract((clip["start"], clip["end"]), covered.get(clip["source"], []))
        remaining.extend(pieces)
        covered.setdefault(clip["source"], []).extend(pieces)
    return remaining


def _hash_distance(first, second):
    if not first or not second:
        return None
    try:
        if len(str(first)) != len(str(second)):
            return None
        return (int(str(first), 16) ^ int(str(second), 16)).bit_count()
    except ValueError:
        return 0 if first == second else None


def _shot_type(value):
    value = str(value).casefold().replace("-", "").replace("_", "").replace(" ", "")
    return {"closeup": "close", "extremecloseup": "detail", "macro": "detail",
            "establishing": "wide", "long": "wide", "mediumshot": "medium",
            "wideshot": "wide"}.get(value, value)


def _curve_area(points, until=1.0):
    area = 0.0
    for left, right in zip(points, points[1:]):
        end = min(until, right["at"])
        if end <= left["at"]:
            break
        width = right["at"] - left["at"]
        fraction = (end - left["at"]) / width
        # Raised-cosine interpolation matches project_render.source_times:
        # continuously changing playback speed with zero slope at each key.
        delta = right["speed"] - left["speed"]
        area += width * (left["speed"] * fraction + delta * (fraction / 2 - math.sin(math.pi * fraction) / (2 * math.pi)))
        if end == until:
            break
    return area


def _curve_speed(points, at):
    for left, right in zip(points, points[1:]):
        if left["at"] <= at <= right["at"]:
            fraction = (at - left["at"]) / (right["at"] - left["at"])
            return left["speed"] + (right["speed"] - left["speed"]) * (1 - math.cos(math.pi * fraction)) / 2
    return points[-1]["speed"]


def _warp_derivative(progress, anchor, target):
    """Derivative of the renderer's monotone C1 Hermite anchor warp."""
    left, right = target / anchor, (1 - target) / (1 - anchor)
    middle = 2 * left * right / (left + right)
    if progress <= anchor:
        local, width, rise, slope_start, slope_end = progress / anchor, anchor, target, left, middle
    else:
        width = 1 - anchor
        local, rise, slope_start, slope_end = (progress - anchor) / width, 1 - target, middle, right
    return ((-6 * local * local + 6 * local) * rise / width
            + (3 * local * local - 4 * local + 1) * slope_start
            + (3 * local * local - 2 * local) * slope_end)


def speed_bounds(edit, output_duration):
    """Numerically bound the rendered continuous speed, including anchor warping.

    Sample every authored smooth interval and its endpoints, independently of
    frame rate. A small tolerance in validate_plan allows floating-point noise.
    """
    points = edit.get("speed_points") or [{"at": 0.0, "speed": 1.0}, {"at": 1.0, "speed": 1.0}]
    area = _curve_area(points)
    span = edit["source_end"] - edit["source_start"]
    anchor = edit.get("action_anchor")
    divisions = sorted({point["at"] for point in points} | ({anchor["output_fraction"]} if anchor else set()))
    positions = {left + (right - left) * n / 128 for left, right in zip(divisions, divisions[1:]) for n in range(129)}
    if anchor:
        anchor_progress = _curve_area(points, anchor["output_fraction"]) / area
        target = (anchor["source_time"] - edit["source_start"]) / span
    values = []
    for at in positions:
        derivative = _warp_derivative(_curve_area(points, at) / area, anchor_progress, target) if anchor else 1.0
        values.append(span / output_duration * _curve_speed(points, at) / area * derivative)
    return min(values), max(values)


def _slow_motion_authorized(policies):
    if not isinstance(policies, dict):
        raise ValueError("policies must be an object")
    enabled = policies.get("allow_slow_motion", False)
    if not isinstance(enabled, bool):
        raise ValueError("allow_slow_motion must be boolean")
    prompt = policies.get("slow_motion_prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("slow_motion_prompt must contain the exact user request as text")
    interpolation = policies.get("interpolation", "none")
    if interpolation not in ("none", "optical_flow"):
        raise ValueError("interpolation must be none or optical_flow")
    if enabled and (not prompt.strip() or interpolation != "optical_flow"):
        raise ValueError("Slow motion requires an explicit user prompt in slow_motion_prompt and optical_flow interpolation")
    if prompt.strip() and not enabled:
        raise ValueError("slow_motion_prompt requires allow_slow_motion=true and optical_flow interpolation")
    return enabled


def validate_slow_motion_policy(plan):
    """Enforce consent and interpolation against actual speed, including anchors.

    Missing policy fields fail closed. A prompt is provenance copied from the
    user's request, never a permission generated by the editing agent itself.
    This focused check is also usable by renderer entry points.
    """
    enabled = _slow_motion_authorized(plan.get("policies", {}))
    fps = _integer(plan.get("output", {}).get("fps", 30), "fps")
    for edit in plan.get("edits", []):
        if edit.get("kind", "video") == "video":
            begin = _number(edit.get("source_start"), "source_start", 0)
            end = _number(edit.get("source_end"), "source_end", begin)
            if end <= begin:
                raise ValueError("Video source interval must have positive duration")
            points = edit.get("speed_points") or [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]
            if not isinstance(points, list) or len(points) < 2 or any(not isinstance(p, dict) for p in points):
                raise ValueError("speed_points needs at least two points")
            previous = -1
            for point in points:
                at = _number(point.get("at"), "speed point at", 0, 1)
                _number(point.get("speed"), "speed point value", .0001)
                if at <= previous:
                    raise ValueError("speed_points must be strictly ordered")
                previous = at
            if points[0]["at"] != 0 or points[-1]["at"] != 1:
                raise ValueError("speed_points must start at 0 and end at 1")
            anchor = edit.get("action_anchor")
            if anchor:
                if not isinstance(anchor, dict):
                    raise ValueError("action_anchor must be an object")
                action = _number(anchor.get("source_time"), "action source_time", begin, end)
                _number(anchor.get("output_fraction"), "action output_fraction", .0001, .9999)
                if not begin < action < end:
                    raise ValueError("Action anchor must be strictly inside its source interval")
            slowest, _ = speed_bounds(edit, _integer(edit.get("duration_frames"), "duration_frames") / fps)
            if slowest < 1 - 1e-5 and not enabled:
                raise ValueError(f"{edit.get('id', 'shot')}: slow motion is forbidden without an explicit user prompt and optical_flow interpolation")
    return enabled


def _clip_score(clip, section, recipe, selected, recent, requested_tags, slot_index):
    tags = {str(tag).casefold() for tag in clip.get("tags", [])}
    target = recipe["energy"][section]
    score = 2.0 - abs(float(clip.get("energy", .5)) - target) * 2
    score += float(clip.get("quality", .5)) * 2
    score += len(tags.intersection(recipe["preferred_tags"])) * .25
    score += len(tags.intersection(requested_tags)) * 2.0
    shot_type = _shot_type(clip.get("shot_type", "unknown"))
    cycle = recipe["shot_cycle"]
    if shot_type == cycle[slot_index % len(cycle)]:
        score += 1.0
    if selected and shot_type != "unknown" and shot_type == _shot_type(selected[-1].get("shot_type")):
        score -= 1.25
    if selected and clip["kind"] == "image" and selected[-1]["source"] == clip["source"]:
        score -= 3.0
    if section == "drop" and clip.get("action_time") is not None:
        score += .8
    for previous in recent[-3:]:
        distance = _hash_distance(clip.get("visual_hash"), previous.get("visual_hash"))
        if distance is not None:
            score -= 3.0 if distance <= 4 else (1.0 if distance <= 10 else 0.0)
        if str(previous["asset_id"]) == str(clip["asset_id"]):
            score -= .3
    return score


def build_plan(beatmap, library, duration=25, preset="cinematic", fps=30,
               width=1080, height=1920, audio_start=None, allow_repeats=False,
               sections=None, **config):
    """Build a serializable v2 project with explicit source and output timing.

    Config: audio_path, shortage ('extend', 'error', 'repeat'), min_speed
    (default 1, or .5 only with an explicit slow_motion_prompt and optical_flow
    interpolation), max_speed (default 4), tags (preferred semantic labels),
    exclude (clip IDs), reframe ('auto', 'center', 'manual'), subject (normalized
    bbox), grade, effects, beat_stride (integer or per-section mapping).
    'extend' may use slower unused intervals only with that explicit permission;
    it never freezes/repeats video secretly. Still images can be held longer.
    """
    fps = _integer(fps, "fps")
    if fps > 120:
        raise ValueError("fps must be between 1 and 120")
    width, height = _integer(width, "width"), _integer(height, "height")
    duration = _number(duration, "duration", 1 / fps)
    frame_count = round(duration * fps)
    actual_duration = frame_count / fps
    recipe = get_preset(preset)
    for name in ("min_shot", "max_shot"):
        if name in config and config[name] is not None:
            recipe[name] = _number(config[name], name, 1 / fps)
    if recipe["max_shot"] < recipe["min_shot"]:
        raise ValueError("max_shot must be at least min_shot")
    if not isinstance(allow_repeats, bool):
        raise ValueError("allow_repeats must be true or false")
    shortage = config.get("shortage", "extend")
    if shortage not in ("extend", "error", "repeat"):
        raise ValueError("shortage must be extend, error, or repeat")
    if shortage == "repeat" and not allow_repeats:
        raise ValueError("shortage='repeat' requires allow_repeats=True")
    prompt = config.get("slow_motion_prompt", "")
    slow_policy = {"allow_slow_motion": bool(prompt), "slow_motion_prompt": prompt,
                   "interpolation": config.get("interpolation", "none")}
    authorized = _slow_motion_authorized(slow_policy)
    min_speed = config.get("min_speed")
    min_speed = _number(min_speed if min_speed is not None else (.5 if authorized else 1), "min_speed", .01, 1)
    if min_speed < 1 and not authorized:
        raise ValueError("min_speed below 1 requires an explicit slow_motion_prompt and optical_flow interpolation")
    max_speed = _number(config.get("max_speed", 4), "max_speed", 1)
    if "beat_stride" in config:
        stride = config["beat_stride"]
        if isinstance(stride, int) and not isinstance(stride, bool):
            recipe["beat_stride"] = {name: _integer(stride, "beat_stride") for name in SECTION_NAMES}
        elif isinstance(stride, dict):
            for name, value in stride.items():
                if name not in SECTION_NAMES:
                    raise ValueError(f"Unknown section in beat_stride: {name}")
                recipe["beat_stride"][name] = _integer(value, "beat_stride")
        else:
            raise ValueError("beat_stride must be an integer or a section mapping")
    for name, value in config.get("section_stride", {}).items():
        if name not in SECTION_NAMES:
            raise ValueError(f"Unknown section in section_stride: {name}")
        recipe["beat_stride"][name] = _integer(value, "section_stride")
    if "grade" in config:
        recipe["effects"]["grade"] = config["grade"]
    recipe["effects"].update(config.get("effects", {}))
    audio_path = config.get("audio_path") or beatmap.get("file") or beatmap.get("audio_file") or beatmap.get("source") or beatmap.get("path")
    if not _absolute(audio_path):
        raise ValueError("Provide an absolute audio_path (or beatmap.file)")
    song_duration = _number(beatmap.get("duration"), "beatmap duration", 0)
    if actual_duration > song_duration + 1e-7:
        raise ValueError(f"Requested {actual_duration:.3f}s exceeds music duration {song_duration:.3f}s; choose a shorter edit or longer track")
    if audio_start is None:
        suggested = beatmap.get("best_segment", {}).get("start", 0)
        audio_start = min(_number(suggested, "best segment start", 0), song_duration - actual_duration)
    audio_start = _number(audio_start, "audio_start", 0)
    if audio_start + actual_duration > song_duration + 1e-7:
        raise ValueError("Selected audio range exceeds the track; reduce audio_start or duration")
    beats = sorted({_number(beat, "beat timestamp", 0) for beat in beatmap.get("beats", [])})
    beat_frames = sorted({round((beat - audio_start) * fps) for beat in beats if audio_start <= beat <= audio_start + actual_duration})
    beat_frames = [frame for frame in beat_frames if 0 <= frame <= frame_count]
    # Silence/unmetered audio still produces a complete project, using tempo as a fallback.
    fallback_beats = not beat_frames
    if fallback_beats:
        interval = max(1, round(fps * 60 / _number(beatmap.get("tempo", 120) or 120, "tempo", 1)))
        beat_frames = list(range(0, frame_count + 1, interval))
    musical_sections = _sections(sections, beatmap, audio_start, frame_count, fps, beat_frames)
    assets = _assets(library)
    if not assets:
        raise ValueError("Media library contains no assets")
    clips = deepcopy(library.get("clips", []))
    excluded = {str(item) for item in config.get("exclude", [])}
    usable = []
    for clip in clips:
        if str(clip.get("id")) in excluded or clip.get("exclude") is True:
            continue
        asset_id = str(clip.get("asset_id"))
        if asset_id not in assets:
            raise ValueError(f"Clip {clip.get('id')} references unknown asset {asset_id}")
        asset = assets[asset_id]
        clip["asset_id"] = asset_id
        clip["source"] = clip.get("source") or asset.get("path") or asset.get("source")
        if not _absolute(clip["source"]):
            raise ValueError(f"Clip {clip.get('id')} needs an absolute source path")
        clip["kind"] = clip.get("kind", asset.get("kind", "video"))
        if clip["kind"] not in ("video", "image"):
            raise ValueError(f"Unsupported media kind: {clip['kind']}")
        clip["start"] = _number(clip.get("start", 0), "clip start", 0)
        clip["end"] = _number(clip.get("end", clip["start"] + clip.get("duration", 0)), "clip end", clip["start"])
        _number(clip.get("energy", .5), "clip energy", 0)
        _number(clip.get("quality", .5), "clip quality", 0, 1)
        if clip["kind"] == "video":
            if clip["end"] <= clip["start"]:
                continue
            if "duration" in asset and clip["end"] > _number(asset["duration"], "asset duration", 0) + 1e-6:
                raise ValueError(f"Clip {clip.get('id')} exceeds its asset duration")
            if authorized and asset.get("fps") and asset.get("duration"):
                # Interpolation needs a later real frame, including at the source
                # tail. Preserve the full catalog; reserve only the usable range.
                clip = deepcopy(clip)
                clip["end"] = min(clip["end"], float(asset["duration"]) - 1 / _number(asset["fps"], "asset fps", .001))
                if clip["end"] <= clip["start"]:
                    continue
        usable.append(clip)
    if not usable:
        raise ValueError("No usable clips remain; import footage or remove exclusions")

    source_intervals = {}
    for clip in usable:
        if clip["kind"] == "video":
            source_intervals.setdefault(clip["source"], []).append((clip["start"], clip["end"]))
    total_unique = sum(_union_length(intervals) for intervals in source_intervals.values())
    has_images = any(clip["kind"] == "image" for clip in usable)
    source_rate = 1.0
    diagnostics = []
    if not allow_repeats and not has_images and total_unique < actual_duration - 1e-7:
        if shortage != "extend" or total_unique / actual_duration < min_speed - 1e-7:
            raise ValueError(f"Only {total_unique:.3f}s of unused video for {actual_duration:.3f}s output. Add footage/photos, shorten the edit, or explicitly enable allow_repeats")
        source_rate = total_unique / actual_duration
        # Each scene contributes a whole number of output frames. Reserve those
        # rounding losses here rather than discovering a few missing frames at
        # the end of an otherwise complete edit.
        intervals = _unique_intervals(usable)
        capacity = lambda rate: sum(math.floor((end - begin) / rate * fps + 1e-7) for begin, end in intervals)
        if capacity(min_speed) < frame_count:
            raise ValueError("Unused footage cannot cover the exact frame count at the permitted speed after scene-boundary rounding; add footage/photos, shorten the edit, or explicitly enable allow_repeats")
        if capacity(source_rate) < frame_count:
            low, high = min_speed, source_rate
            for _ in range(48):
                middle = (low + high) / 2
                if capacity(middle) >= frame_count:
                    low = middle
                else:
                    high = middle
            source_rate = low
        diagnostics.append(f"Unused source intervals are extended at {source_rate:.4f}x to meet the exact duration without repetition.")
    if fallback_beats:
        diagnostics.append("No detected beats in the selected audio range; the tempo grid is a fallback, not measured beat alignment.")

    requested_tags = {str(tag).casefold() for tag in config.get("tags", [])}
    used, image_used, selected, edits = {}, set(), [], []
    position = 0
    for slot_begin, slot_end, section in _slots(musical_sections, beat_frames, recipe, fps):
        while position < slot_end:
            wanted_frames = slot_end - position
            effective_rate = source_rate
            forced_image = None
            image_hold_needed = 0
            if not allow_repeats and not any(c["kind"] == "image" and c["source"] not in image_used for c in usable):
                remaining = _remaining_intervals(usable, used)
                remaining_frames = frame_count - position
                capacity_at = lambda rate: sum(math.floor((end - begin) / rate * fps + 1e-7) for begin, end in remaining)
                reserve_rate = min_speed if shortage == "extend" else source_rate
                if capacity_at(reserve_rate) < remaining_frames and edits and edits[-1]["kind"] == "image":
                    forced_image = edits[-1]["source"]
                    image_hold_needed = remaining_frames - capacity_at(reserve_rate)
                elif shortage == "extend" and capacity_at(effective_rate) < remaining_frames <= capacity_at(min_speed):
                    low, high = min_speed, effective_rate
                    for _ in range(32):
                        middle = (low + high) / 2
                        if capacity_at(middle) >= remaining_frames:
                            low = middle
                        else:
                            high = middle
                    effective_rate = low
            options = []
            for index, clip in enumerate(usable):
                if forced_image is not None and clip["source"] != forced_image:
                    continue
                if clip["kind"] == "image":
                    continuing = bool(edits and edits[-1]["source"] == clip["source"])
                    intervals = [(0.0, float("inf"))] if clip["source"] not in image_used or allow_repeats or continuing else []
                else:
                    intervals = _subtract((clip["start"], clip["end"]), used.get(clip["source"], []))
                    if not intervals and allow_repeats:
                        intervals = [(clip["start"], clip["end"])]
                for begin, end in intervals:
                    capacity_rate = min_speed if shortage == "extend" else source_rate
                    capacity = wanted_frames if clip["kind"] == "image" else math.floor((end - begin) / capacity_rate * fps + 1e-6)
                    if capacity <= 0:
                        continue
                    score = _clip_score(clip, section, recipe, selected, selected, requested_tags, len(edits))
                    ideal_capacity = wanted_frames if clip["kind"] == "image" else math.floor((end - begin) / effective_rate * fps + 1e-6)
                    options.append((ideal_capacity >= wanted_frames, capacity >= wanted_frames, score, min(capacity, wanted_frames), -index, clip, begin, end))
            if not options:
                # Tiny fractional source tails can combine to less than one output frame.
                # Stretch the previous contiguous shot by the exact remaining frames,
                # but only when the declared minimum playback rate remains valid.
                remaining = frame_count - position
                if shortage == "extend" and edits and remaining > 0:
                    last = edits[-1]
                    resulting_frames = last["duration_frames"] + remaining
                    resulting_rate = (last["source_end"] - last["source_start"]) / (resulting_frames / fps)
                    if last["kind"] == "image" or resulting_rate >= min_speed - 1e-6:
                        # Extending over later musical sections would silently erase the
                        # promised structure, so only the final section may be extended.
                        if last["section"] == musical_sections[-1]["name"]:
                            last["duration_frames"] = resulting_frames
                            last["timeline_end_frame"] = frame_count
                            last["average_speed"] = resulting_rate
                            last["speed_points"] = [{"at": 0.0, "speed": 1.0}, {"at": 1.0, "speed": 1.0}]
                            last.pop("action_anchor", None)
                            position = frame_count
                            diagnostics.append("Extended the final shot to absorb sub-frame source fragments.")
                            break
                raise ValueError(f"Footage is exhausted at {position / fps:.3f}s. Add unused scenes/photos, shorten duration, or enable allow_repeats explicitly")
            _, _, _, take_frames, _, clip, available_start, available_end = max(options, key=lambda option: option[:5])
            # A sole unused still may cover several following slots. Keep it as one
            # continuous hold across the section, without pretending it is a new shot.
            if clip["kind"] == "image" and not allow_repeats:
                other_available = any(option[5]["source"] != clip["source"] for option in options)
                if image_hold_needed:
                    section_end = next(item["end_frame"] for item in musical_sections if item["start_frame"] <= position < item["end_frame"])
                    take_frames = min(image_hold_needed, section_end - position)
                elif not other_available:
                    section_end = next(item["end_frame"] for item in musical_sections if item["start_frame"] <= position < item["end_frame"])
                    take_frames = section_end - position
            output_duration = take_frames / fps
            span = output_duration * effective_rate if clip["kind"] == "video" else 0.0
            begin = available_start
            end = min(available_end, begin + span) if clip["kind"] == "video" else 0.0
            span = end - begin
            actual_rate = span / output_duration
            curve = [{"at": 0.0, "speed": 1.0}, {"at": 1.0, "speed": 1.0}]
            anchor = None
            interior_beats = [frame for frame in beat_frames if position < frame < position + take_frames]
            action = clip.get("action_time")
            if clip["kind"] == "video" and section in ("build", "drop") and output_duration >= .25:
                action_fraction = ((min(interior_beats, key=lambda frame: abs(frame - position - take_frames / 2)) - position) / take_frames) if interior_beats else .5
                entry, slow, exit_speed = recipe["speed_ramp"]
                proposed = [{"at": 0.0, "speed": entry}, {"at": action_fraction, "speed": slow}, {"at": 1.0, "speed": exit_speed}]
                area = _curve_area(proposed)
                rates = [point["speed"] * actual_rate / area for point in proposed]
                if min(rates) >= min_speed - 1e-7 and max(rates) <= max_speed + 1e-7:
                    curve = proposed
                if action is not None and interior_beats and effective_rate == 1.0:
                    action = _number(action, "action_time", 0)
                    proposed_start = action - span * _curve_area(curve, action_fraction) / _curve_area(curve)
                    if available_start - 1e-7 <= proposed_start and proposed_start + span <= available_end + 1e-7:
                        begin = max(available_start, proposed_start)
                        end = min(available_end, begin + span)
                        anchor = {"source_time": action, "output_fraction": action_fraction}
            on_accent = section == "drop" and position in beat_frames and (not edits or position == next(item["start_frame"] for item in musical_sections if item["start_frame"] <= position < item["end_frame"]) or len(edits) % 4 == 0)
            effects = deepcopy(recipe["effects"])
            if not on_accent:
                effects["flash"] = 0.0
                effects["shake"] = 0.0
                effects["zoom"] = 1.0 + (effects["zoom"] - 1.0) * (.35 if section != "outro" else .15)
            reframe = {"mode": config.get("reframe", "auto")}
            subject = config.get("subject") or clip.get("subject")
            if subject is not None:
                reframe["subject"] = deepcopy(subject)
                reframe["subject_start"] = clip["start"]
            if clip.get("subject_track"):
                reframe["subject_track"] = deepcopy(clip["subject_track"])
            item = {"id": f"shot-{len(edits) + 1:03d}", "clip_id": str(clip["id"]),
                    "asset_id": clip["asset_id"], "source": clip["source"], "kind": clip["kind"],
                    "source_start": begin, "source_end": end, "duration_frames": take_frames,
                    "timeline_start_frame": position, "timeline_end_frame": position + take_frames,
                    "section": section, "effects": effects, "speed_points": curve,
                    "average_speed": (end - begin) / output_duration, "reframe": reframe,
                    "tags": deepcopy(clip.get("tags", [])), "shot_type": _shot_type(clip.get("shot_type", "unknown"))}
            if anchor:
                item["action_anchor"] = anchor
            if clip["kind"] == "video":
                lower, upper = speed_bounds(item, output_duration)
                if lower < min_speed - 1e-7 or upper > max_speed + 1e-7:
                    # Optional musical accents must never weaken the speed policy.
                    item.pop("action_anchor", None)
                    lower, upper = speed_bounds(item, output_duration)
                    if lower < min_speed - 1e-7 or upper > max_speed + 1e-7:
                        item["speed_points"] = [{"at": 0.0, "speed": 1.0}, {"at": 1.0, "speed": 1.0}]
            edits.append(item)
            selected.append(clip)
            if clip["kind"] == "image":
                image_used.add(clip["source"])
            else:
                used.setdefault(clip["source"], []).append((begin, end))
            position += take_frames
    plan = {"schema_version": 2, "audio": {"path": audio_path, "start": audio_start, "duration": song_duration},
            "output": {"width": width, "height": height, "fps": fps}, "duration_frames": frame_count,
            "duration": actual_duration, "requested_duration": duration, "preset": preset,
            "sections": musical_sections, "beat_frames": beat_frames, "assets": deepcopy(library["assets"]),
            "clips": clips, "edits": edits, "diagnostics": diagnostics,
            "policies": {"allow_repeats": allow_repeats, "shortage": shortage,
                         "min_speed": min_speed, "max_speed": max_speed, **slow_policy}}
    validate_plan(plan)
    return plan


def validate_plan(plan):
    """Raise ValueError on an invalid/unrenderable plan; return it unchanged otherwise."""
    if not isinstance(plan, dict) or plan.get("schema_version") != 2:
        raise ValueError("Expected a schema_version 2 project")
    output = plan.get("output", {})
    fps = _integer(output.get("fps"), "fps")
    if fps > 120:
        raise ValueError("fps must be between 1 and 120")
    for name in ("width", "height"):
        size = _integer(output.get(name), name, 2)
        if size % 2:
            raise ValueError(f"{name} must be even for yuv420p MP4")
    frames = _integer(plan.get("duration_frames"), "duration_frames")
    if abs(_number(plan.get("duration"), "duration", 0) - frames / fps) > 1e-7:
        raise ValueError("duration must equal duration_frames / fps")
    audio = plan.get("audio", {})
    if not _absolute(audio.get("path")):
        raise ValueError("audio.path must be absolute")
    start = _number(audio.get("start"), "audio.start", 0)
    if "duration" in audio and start + frames / fps > _number(audio["duration"], "audio.duration", 0) + 1e-7:
        raise ValueError("Audio segment exceeds the source track")
    _validate_sections(plan.get("sections", []), frames)
    assets = _assets(plan)
    if not assets:
        raise ValueError("Project requires an asset manifest")
    policies = plan.get("policies", {})
    slow_motion_allowed = _slow_motion_authorized(policies)
    repeats = policies.get("allow_repeats", False)
    if not isinstance(repeats, bool):
        raise ValueError("allow_repeats must be boolean")
    min_speed = _number(policies.get("min_speed", .01), "min_speed", .001)
    max_speed = _number(policies.get("max_speed", 100), "max_speed", min_speed)
    edits = plan.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("Project requires at least one shot")
    clips = {str(clip["id"]): clip for clip in plan.get("clips", [])}
    position, identifiers, used, images = 0, set(), {}, set()
    for edit in edits:
        identifier = edit.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Shot IDs must be unique nonempty strings")
        identifiers.add(identifier)
        count = _integer(edit.get("duration_frames"), f"{identifier} duration_frames")
        begin_frame = _integer(edit.get("timeline_start_frame"), f"{identifier} timeline_start_frame", 0)
        end_frame = _integer(edit.get("timeline_end_frame"), f"{identifier} timeline_end_frame")
        if begin_frame != position or end_frame != begin_frame + count or end_frame > frames:
            raise ValueError(f"{identifier}: timeline must be contiguous and match duration_frames")
        section = next((item for item in plan["sections"] if item["start_frame"] <= begin_frame < item["end_frame"]), None)
        if section is None or edit.get("section") != section["name"] or end_frame > section["end_frame"]:
            raise ValueError(f"{identifier}: shot must stay inside its declared musical section")
        position = end_frame
        asset_id = str(edit.get("asset_id"))
        if asset_id not in assets:
            raise ValueError(f"{identifier}: unknown asset_id")
        asset = assets[asset_id]
        source = edit.get("source")
        asset_path = asset.get("path") or asset.get("source")
        if not _absolute(source) or (asset_path is not None and source != asset_path):
            raise ValueError(f"{identifier}: source must match the absolute asset path")
        kind = edit.get("kind")
        if kind not in ("video", "image") or asset.get("kind", kind) != kind:
            raise ValueError(f"{identifier}: invalid or mismatched media kind")
        begin = _number(edit.get("source_start"), f"{identifier} source_start", 0)
        end = _number(edit.get("source_end"), f"{identifier} source_end", begin)
        if "clip_id" in edit:
            clip = clips.get(str(edit["clip_id"]))
            if clip is None or str(clip.get("asset_id")) != asset_id or clip.get("kind", kind) != kind:
                raise ValueError(f"{identifier}: clip_id is missing or inconsistent with the asset")
            if clip.get("source", source) != source:
                raise ValueError(f"{identifier}: clip source differs from edit source")
            if kind == "video" and (begin < clip.get("start", 0) - 1e-6 or end > clip.get("end", end) + 1e-6):
                raise ValueError(f"{identifier}: source range exceeds analyzed clip bounds")
        if kind == "video":
            if end <= begin:
                raise ValueError(f"{identifier}: video source interval must have positive duration")
            if "duration" in asset and end > _number(asset["duration"], "asset duration", 0) + 1e-6:
                raise ValueError(f"{identifier}: source_end exceeds asset duration")
            if not repeats and any(min(end, prior_end) - max(begin, prior_begin) > 1e-6 for prior_begin, prior_end in used.get(source, [])):
                raise ValueError(f"{identifier}: repeated source interval requires allow_repeats=True")
            used.setdefault(source, []).append((begin, end))
        else:
            # Contiguous still holds may be divided at section boundaries without
            # constituting another use of the image. Separated uses are repeats.
            if not repeats and source in images and (len(identifiers) < 2 or edits[len(identifiers) - 2]["source"] != source):
                raise ValueError(f"{identifier}: repeated image requires allow_repeats=True")
            images.add(source)
        points = edit.get("speed_points", [])
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"{identifier}: speed_points needs at least two points")
        previous_at = -1
        for point in points:
            at = _number(point.get("at"), "speed point at", 0, 1)
            _number(point.get("speed"), "speed point value", .0001)
            if at <= previous_at:
                raise ValueError("speed_points must be strictly ordered")
            previous_at = at
        if points[0]["at"] != 0 or points[-1]["at"] != 1:
            raise ValueError("speed_points must start at 0 and end at 1")
        anchor = edit.get("action_anchor")
        if anchor:
            action = _number(anchor.get("source_time"), "action source_time", begin, end)
            fraction = _number(anchor.get("output_fraction"), "action output_fraction", .0001, .9999)
            if action <= begin or action >= end:
                raise ValueError("Action anchor must be strictly inside its source interval")
        if kind == "video":
            slowest, fastest = speed_bounds(edit, count / fps)
            if slowest < 1 - 1e-5 and not slow_motion_allowed:
                raise ValueError(f"{identifier}: slow motion is forbidden without an explicit user prompt and optical_flow interpolation")
            if slowest < min_speed - 1e-5 or fastest > max_speed + 1e-5:
                raise ValueError(f"{identifier}: normalized speed curve violates min_speed/max_speed policy")
        effects = edit.get("effects", {})
        for effect in ("flash", "shake"):
            _number(effects.get(effect, 0), effect, 0, 1)
        _number(effects.get("zoom", 1), "zoom", 1, 4)
        if effects.get("grade", "none") not in GRADES:
            raise ValueError(f"Unknown grade; choose {GRADES}")
        reframe = edit.get("reframe", {})
        if reframe.get("mode", "auto") not in ("auto", "center", "manual", "contain"):
            raise ValueError("reframe.mode must be auto, center, manual, or contain")
        box = reframe.get("subject")
        if "subject_start" in reframe:
            _number(reframe["subject_start"], "reframe.subject_start", 0, begin)
        if reframe.get("mode") == "manual" and box is None:
            raise ValueError("Manual reframing requires a normalized subject bbox [x,y,w,h]")
        if box is not None:
            if not isinstance(box, (tuple, list)) or len(box) != 4:
                raise ValueError("subject must be [x,y,width,height] normalized to 0..1")
            for index, coordinate in enumerate(box):
                _number(coordinate, "subject coordinate", 0 if index < 2 else .00001, 1)
            if box[0] + box[2] > 1.00001 or box[1] + box[3] > 1.00001:
                raise ValueError("subject bbox exceeds frame bounds")
    if position != frames:
        raise ValueError("Shots do not cover duration_frames exactly")
    validate_slow_motion_policy(plan)
    if any(key in plan for key in ("titles", "subtitles", "title_style", "subtitle_style")):
        from text_overlay import validate_text_tracks
        validate_text_tracks(plan)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("beatmap")
    parser.add_argument("library")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--duration", type=float, default=25)
    parser.add_argument("--preset", choices=("cinematic", "car", "gaming", "product"), default="cinematic")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--audio-start", type=float)
    parser.add_argument("--audio-path")
    parser.add_argument("--allow-repeats", action="store_true")
    parser.add_argument("--shortage", choices=("extend", "error", "repeat"), default="extend")
    parser.add_argument("--min-speed", type=float)
    parser.add_argument("--slow-motion-prompt", default="", help="Exact user request explicitly authorizing interpolated slow motion")
    parser.add_argument("--interpolation", choices=("none", "optical_flow"), default="none")
    parser.add_argument("--max-speed", type=float, default=4)
    parser.add_argument("--beat-stride", type=int)
    parser.add_argument("--section-stride", action="append", default=[], metavar="NAME=N")
    parser.add_argument("--min-shot", type=float)
    parser.add_argument("--max-shot", type=float)
    parser.add_argument("--sections", help="JSON list of relative music section boundaries")
    parser.add_argument("--tags", nargs="*", default=[])
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--reframe", choices=("auto", "center", "manual", "contain"), default="auto")
    parser.add_argument("--subject", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--grade", choices=GRADES)
    args = parser.parse_args(argv)
    config = {key: getattr(args, key) for key in ("shortage", "min_speed", "max_speed", "tags", "exclude", "reframe", "slow_motion_prompt", "interpolation")}
    for key in ("audio_path", "subject", "grade", "beat_stride", "min_shot", "max_shot"):
        if getattr(args, key) is not None:
            config[key] = getattr(args, key)
    config["section_stride"] = {}
    for spec in args.section_stride:
        try:
            name, number = spec.split("=", 1)
            config["section_stride"][name] = int(number)
        except ValueError as exc:
            raise ValueError("--section-stride expects NAME=N, for example drop=1") from exc
    manual = json.loads(Path(args.sections).read_text(encoding="utf-8")) if args.sections else None
    plan = build_plan(json.loads(Path(args.beatmap).read_text(encoding="utf-8")),
                      json.loads(Path(args.library).read_text(encoding="utf-8")),
                      args.duration, args.preset, args.fps, args.width, args.height,
                      args.audio_start, args.allow_repeats, manual, **config)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(plan['edits'])} shots, {plan['duration_frames']} frames, {plan['duration']:.3f}s to {destination}")


if __name__ == "__main__":
    main()

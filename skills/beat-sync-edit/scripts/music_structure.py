"""Inspectable musical measurements and conservative pacing hypotheses.

This is signal analysis, not semantic recognition of verses, choruses or drops.
All times refer to the original music. Manual corrections retain an audit trail.
"""
from copy import deepcopy
import hashlib
import json
import math


def _number(value, label, lower=0, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if value < lower or (upper is not None and value > upper):
        raise ValueError(f"{label} out of range")
    return float(value)


def _intervals(mask, times, duration, minimum=.25):
    result, begin = [], None
    for index, enabled in enumerate(mask):
        if enabled and begin is None:
            begin = float(times[index])
        if begin is not None and (not enabled or index == len(mask) - 1):
            end = float(times[index]) if not enabled else duration
            if end - begin >= minimum:
                result.append({"start": round(begin, 6), "end": round(end, 6)})
            begin = None
    return result


def analyze_structure(times, rms, onset_times, onset_strengths, beats, duration):
    """Build features from measured RMS and onset peaks, without forcing a meter."""
    import numpy as np
    times, rms = np.asarray(times, dtype=float), np.asarray(rms, dtype=float)
    if len(times) != len(rms) or not len(times) or not np.isfinite(rms).all() or (rms < 0).any():
        raise ValueError("RMS and times must be finite nonempty arrays of equal length")
    duration = _number(duration, "duration", .000001)
    if not np.isfinite(times).all() or (np.diff(times) <= 0).any() or times[0] < 0:
        raise ValueError("Measurement times must be ordered and nonnegative")
    onsets = sorted((float(t), float(s)) for t, s in zip(onset_times, onset_strengths) if 0 <= t < duration)
    beat_times = sorted(set(float(t) for t in beats if 0 <= t <= duration))
    peak = float(np.max(rms))
    normalized = rms / max(peak, 1e-12)
    silence = _intervals(rms < 10 ** (-50 / 20), times, duration)
    active_fraction = 1 - sum(i["end"] - i["start"] for i in silence) / duration
    # Uniform beat tracker output alone is not evidence of a real pulse.
    intervals = np.diff([t for t, _ in onsets])
    regularity = float(max(0, 1 - np.median(np.abs(intervals - np.median(intervals))) / max(.05, np.median(intervals)))) if len(intervals) >= 3 else 0.0
    alignment = sum(min((abs(t - b) for b in beat_times), default=duration) <= .1 for t, _ in onsets) / max(1, len(onsets))
    density = len(onsets) / duration
    contrast = float(np.quantile(normalized, .95) - np.quantile(normalized, .20))
    pulse_support = min(1., density / .8) * min(1., contrast / .25)
    confidence = min(1., (.5 * regularity + .5 * alignment) * pulse_support * min(1., len(onsets) / 8))
    # Silence can coexist with a strong pulse; only wholly silent audio is rejected.
    if peak < 10 ** (-50 / 20) or len(beat_times) < 3:
        confidence = 0.
    mode = "beat_cut" if confidence >= .55 else "phrase_flow"
    events = []
    step = float(np.median(np.diff(times))) if len(times) > 1 else duration
    context = max(1, round(.3 / step))
    changes = []
    for index in range(context, len(times) - context):
        before = float(np.mean(normalized[index-context:index]))
        after = float(np.mean(normalized[index:index+context]))
        delta = after - before
        if abs(delta) >= .25:
            changes.append((abs(delta), float(times[index]), delta, before, after))
    chosen = []
    for strength, time, delta, before, after in sorted(changes, reverse=True):
        if all(abs(time - prior["time"]) >= .75 for prior in chosen):
            kind = "hard_stop" if delta < 0 and after < .08 and before > .3 else ("energy_rise" if delta > 0 else "energy_fall")
            chosen.append({"type": kind, "time": round(time, 6), "confidence": round(min(.9, strength), 4),
                           "method": "rms-change", "evidence": {"before": round(before, 4), "after": round(after, 4), "window": .3}})
    events.extend(chosen)
    for item in silence:
        events.extend({"type": kind, "time": item[key], "confidence": .95, "method": "absolute-rms-below-minus50dbfs"}
                      for kind, key in (("silence_start", "start"), ("silence_end", "end")) if item[key] < duration)
    events.sort(key=lambda item: (item["time"], item["type"]))
    for index, event in enumerate(events):
        event["id"] = f"event-{index:04d}-{event['type']}"
    # Phases describe a measured one-second energy envelope, not song semantics.
    energy_phases, onset_density = [], []
    for begin in np.arange(0, duration, 1.):
        end = min(duration, float(begin) + 1.)
        mask = (times >= begin) & (times < end)
        energy = float(np.mean(normalized[mask])) if mask.any() else 0.
        previous = energy_phases[-1]["energy"] if energy_phases else energy
        trend = "rise" if energy - previous > .15 else "fall" if previous - energy > .15 else "stable"
        energy_phases.append({"start": round(float(begin), 6), "end": round(end, 6), "energy": round(energy, 4), "trend": trend})
        onset_density.append({"start": round(float(begin), 6), "end": round(end, 6), "count": int(sum(begin <= t < end for t, _ in onsets))})
    boundaries = [0.]
    proposed = [event["time"] for event in events if event["type"] in ("hard_stop", "energy_rise", "silence_start", "silence_end")]
    if mode == "beat_cut":
        proposed += beat_times[::8]  # eight beats is a pacing hypothesis, not detected bars
    for time in sorted(set(proposed)):
        if time - boundaries[-1] >= 2 and duration - time >= 1:
            boundaries.append(time)
    boundaries.append(duration)
    phrases = [{"id": f"phrase-{index:04d}", "start": left, "end": right,
                "confidence": round(confidence * .6 if mode == "beat_cut" else .35, 4),
                "method": "energy-events-and-eight-beat-hypothesis" if mode == "beat_cut" else "energy-event-hypothesis"}
               for index, (left, right) in enumerate(zip(boundaries, boundaries[1:]))]
    return {"version": 1, "onsets": [{"time": round(t, 6), "strength": round(s, 5)} for t, s in onsets],
            "onset_density": onset_density, "energy_phases": energy_phases, "silence": silence,
            "events": events, "phrases": phrases, "beat_confidence": round(confidence, 4),
            "evidence": {"onset_regularity": round(regularity, 4), "beat_onset_alignment": round(alignment, 4),
                         "energy_contrast": round(contrast, 4), "active_fraction": round(active_fraction, 4)},
            "pacing": {"mode": mode, "confidence": round(confidence if mode == "beat_cut" else 1-confidence, 4),
                       "reason": "Repeated onsets support beat cuts" if mode == "beat_cut" else "Weak or absent pulse: use phrase/energy changes and longer holds"},
            "warnings": ["Phrase and section hypotheses require listening; analysis does not identify semantic song structure."]}


def analyze_waveform(samples, sample_rate, beats=()):
    """Lightweight reference path used for reproducible PCM fixtures and diagnostics."""
    import numpy as np
    samples = np.asarray(samples, dtype=float)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError("samples must be a finite mono/stereo waveform")
    sample_rate = int(_number(sample_rate, "sample rate", 1))
    hop = max(1, round(sample_rate * .02))
    count = math.ceil(len(samples) / hop)
    padded = np.pad(samples, (0, count * hop - len(samples))).reshape(count, hop)
    rms = np.sqrt(np.mean(padded * padded, axis=1))
    times = np.arange(count) * hop / sample_rate
    flux = np.maximum(0, np.diff(rms, prepend=rms[0]))
    threshold = max(float(np.quantile(flux, .8)) * 1.5, float(np.max(flux)) * .15, .001)
    selected = []
    for index in np.argsort(flux)[::-1]:
        if flux[index] >= threshold and all(abs(times[index] - times[j]) >= .12 for j in selected):
            selected.append(int(index))
    selected.sort()
    return analyze_structure(times, rms, times[selected], flux[selected], beats, len(samples) / sample_rate)


def structure_for_map(beatmap):
    """Keep old beat maps usable while exposing their missing confidence evidence."""
    if isinstance(beatmap.get("music_structure"), dict):
        return deepcopy(beatmap["music_structure"])
    beats = beatmap.get("beats", [])
    return {"version": 1, "events": [], "phrases": [], "energy_phases": [], "silence": [],
            "onsets": [], "onset_density": [], "beat_confidence": .35 if beats else 0.,
            "pacing": {"mode": "beat_cut" if beats else "phrase_flow", "confidence": .35,
                       "reason": "Legacy map has beats but no onset evidence" if beats else "No measured beats; use longer holds"},
            "warnings": ["Legacy map: run music analysis again to measure pulse confidence."]}


def apply_overrides(beatmap, overrides):
    """Return a corrected map. Explicit reason and bounded times make edits reviewable."""
    if not isinstance(overrides, dict) or set(overrides) - {"reason", "beats", "phrases", "events", "pacing_mode"}:
        raise ValueError("Music overrides allow reason, beats, phrases, events, pacing_mode")
    if not isinstance(overrides.get("reason"), str) or not overrides["reason"].strip():
        raise ValueError("Music overrides require a nonempty reason")
    result = deepcopy(beatmap)
    structure = structure_for_map(result)
    duration = _number(result.get("duration"), "duration", .000001)
    if "beats" in overrides:
        if not isinstance(overrides["beats"], list):
            raise ValueError("beats must be a list")
        beats = [_number(t, "beat", 0, duration) for t in overrides["beats"]]
        if beats != sorted(set(beats)):
            raise ValueError("Manual beats must be strictly ordered")
        result["beats"], result["beat_count"] = beats, len(beats)
        structure["beat_method"] = "manual"
    for key in ("events", "phrases"):
        if key not in overrides:
            continue
        if not isinstance(overrides[key], list):
            raise ValueError(f"{key} must be a list")
        records, seen = [], set()
        for index, entry in enumerate(overrides[key]):
            if not isinstance(entry, dict):
                raise ValueError(f"{key} entries must be objects")
            item = deepcopy(entry)
            item["id"] = str(item.get("id", f"manual-{key}-{index:04d}"))
            if not item["id"] or item["id"] in seen:
                raise ValueError("Music event/phrase ids must be unique")
            seen.add(item["id"])
            if key == "events":
                item["time"] = _number(item.get("time"), "event time", 0, duration)
                if not isinstance(item.get("type"), str) or not item["type"]:
                    raise ValueError("event type is required")
            else:
                item["start"] = _number(item.get("start"), "phrase start", 0, duration)
                item["end"] = _number(item.get("end"), "phrase end", item["start"], duration)
                if item["end"] <= item["start"]:
                    raise ValueError("phrases must have positive duration")
            item["method"] = "manual"
            item["confidence"] = _number(item.get("confidence", .5), "confidence", 0, 1)
            records.append(item)
        records.sort(key=lambda i: i.get("time", i.get("start")))
        if key == "phrases" and any(a["end"] > b["start"] for a, b in zip(records, records[1:])):
            raise ValueError("Manual phrases must not overlap")
        structure[key] = records
    if "pacing_mode" in overrides:
        if overrides["pacing_mode"] not in ("beat_cut", "phrase_flow"):
            raise ValueError("pacing_mode must be beat_cut or phrase_flow")
        structure["pacing"] = {"mode": overrides["pacing_mode"], "method": "manual", "reason": overrides["reason"], "confidence": None}
    before = hashlib.sha256(json.dumps(beatmap, sort_keys=True).encode()).hexdigest()
    structure.setdefault("overrides", []).append({"input_sha256": before, "changes": deepcopy(overrides)})
    result["music_structure"] = structure
    return result


def segment_structure(beatmap, start, duration, fps, mode="auto"):
    if mode not in ("auto", "beat_cut", "phrase_flow"):
        raise ValueError("pacing_mode must be auto, beat_cut or phrase_flow")
    structure = structure_for_map(beatmap)
    if mode != "auto":
        structure["pacing"] = {"mode": mode, "method": "requested", "reason": "Explicit planning mode", "confidence": None}
    for key in ("events", "onsets"):
        structure[key] = [{**item, "output_frame": round((item["time"]-start)*fps)}
                          for item in structure.get(key, []) if start <= item["time"] < start+duration]
    for key in ("phrases", "energy_phases", "silence", "onset_density"):
        structure[key] = [{**item, "output_start_frame": round(max(0, item["start"]-start)*fps),
                           "output_end_frame": round(min(duration, item["end"]-start)*fps)}
                          for item in structure.get(key, []) if item["start"] < start+duration and item["end"] > start]
    if mode == "auto" and "music_structure" in beatmap and structure.get("pacing", {}).get("method") != "manual":
        # A pulsed chorus cannot certify a silent/ambient excerpt elsewhere in
        # the same track. Reconsider the mode using this selected interval.
        selected_onsets = structure.get("onsets", [])
        selected_beats = [t for t in beatmap.get("beats", []) if start <= t < start+duration]
        if len(selected_onsets) < 3 or len(selected_beats) < 3:
            structure["beat_confidence"] = 0.
            structure["pacing"] = {"mode": "phrase_flow", "confidence": .8,
                                   "reason": "Selected excerpt has too few measured onsets/beats to support a pulse"}
        else:
            alignment = sum(min(abs(item["time"]-beat) for beat in selected_beats) <= .1 for item in selected_onsets)/len(selected_onsets)
            local_confidence = min(structure.get("beat_confidence", 0), alignment, min(1., len(selected_onsets)/duration/.8))
            structure["beat_confidence"] = round(local_confidence, 4)
            if local_confidence < .55:
                structure["pacing"] = {"mode": "phrase_flow", "confidence": round(1-local_confidence, 4),
                                       "reason": "Pulse support is weak in the selected excerpt; use phrase flow"}
    return structure

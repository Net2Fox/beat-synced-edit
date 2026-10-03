"""Arrange supplied music by explicit bar ranges, with PCM timing verification."""
from __future__ import annotations

import contextlib
import io
import math
from pathlib import Path

import numpy as np

from audio_mix import SAMPLE_RATE, audio_info, configure_numba_cache, decode_audio, digest, number, write_audio


def _integer(value, name, minimum=0):
    result = number(value, name, minimum)
    if int(result) != result:
        raise ValueError(f"{name} must be an integer")
    return int(result)


def arrangement_plan(audio, beatmap, segments, beats_per_bar=4, first_downbeat=0):
    """Bars are one-based, half-open: [1, 3) means bars 1 and 2.

    The first downbeat is an explicit index into the supplied beat array. We do
    not pretend that a beat tracker detects meter or the first musical bar.
    """
    path = Path(audio).resolve(strict=True)
    info = audio_info(path)
    if info is None:
        raise ValueError("Arrangement input has no audio")
    declared = beatmap.get("file") or beatmap.get("audio_path")
    if declared and Path(declared).resolve() != path:
        raise ValueError("Beat map belongs to a different audio file")
    beats = np.asarray(beatmap.get("beats", []), dtype=float)
    if len(beats) < 2 or not np.all(np.isfinite(beats)) or np.any(np.diff(beats) <= 0) or beats[0] < 0:
        raise ValueError("Arrangement needs a finite, increasing beat grid with at least two beats")
    if beats[-1] > info["duration"] + .002:
        raise ValueError("Beat map extends beyond the source audio")
    meter = _integer(beats_per_bar, "beats_per_bar", 1)
    downbeat = _integer(first_downbeat, "first_downbeat")
    if downbeat >= len(beats):
        raise ValueError("first_downbeat is outside the beat grid")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Arrangement segments must be a non-empty array")
    result, cursor = [], 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError("Arrangement segments must be objects")
        if "start_beat" in segment:
            first = _integer(segment["start_beat"], "start_beat")
            last = _integer(segment["end_beat"], "end_beat")
        else:
            first = downbeat+(_integer(segment["start_bar"], "start_bar", 1)-1)*meter
            last = downbeat+(_integer(segment["end_bar"], "end_bar", 1)-1)*meter
        if first >= len(beats) or last <= first or last > len(beats):
            raise ValueError("Selected bar/beat range is empty or outside the supplied grid")
        # The only boundary after the last known beat is the recording end.
        # No constant-BPM extrapolation is used across an unknown ending.
        begin = round(float(beats[first])*SAMPLE_RATE)
        end = round((float(beats[last]) if last < len(beats) else info["duration"])*SAMPLE_RATE)
        length = end-begin
        if length <= 0:
            raise ValueError("Selected bar range has no available audio samples")
        gap = round(number(segment.get("gap_before", 0), "gap_before", 0)*SAMPLE_RATE)
        crossfade = round(number(segment.get("crossfade", 0), "crossfade", 0)*SAMPLE_RATE)
        if index == 0 and crossfade:
            raise ValueError("First segment cannot crossfade with a preceding segment")
        if gap and crossfade:
            raise ValueError("A segment cannot have both gap_before and crossfade")
        if crossfade >= length or (result and crossfade >= result[-1]["length_samples"]):
            raise ValueError("Crossfade must be shorter than both adjoining segments")
        if result and crossfade+result[-1]["crossfade_samples"] >= result[-1]["length_samples"]:
            raise ValueError("Crossfades cannot overlap three segments")
        start = cursor+gap-crossfade
        result.append({"id": str(segment.get("id", f"segment-{index+1}")), "source_start_sample": begin,
                       "source_end_sample": end, "length_samples": length, "start_sample": start,
                       "end_sample": start+length, "crossfade_samples": crossfade, "gap_samples": gap,
                       "start_beat": first, "end_beat": last})
        cursor = start+length
    if len({s["id"] for s in result}) != len(result):
        raise ValueError("Arrangement segment IDs must be unique")
    return {"source": str(path), "source_sha256": digest(path), "sample_rate": SAMPLE_RATE,
            "beats_per_bar": meter, "first_downbeat": downbeat, "segments": result,
            "samples": cursor, "duration": cursor/SAMPLE_RATE}


def verify_arrangement(rendered, source_segments, plan, max_shift_samples=96):
    """Measure shift using signal correlation outside crossfades.

    Silence/constant signals are unmeasurable rather than a fabricated pass.
    Exact PCM comparison proves copied material even when correlation is
    ambiguous for periodic waveforms. This tests splicing, not beat detection.
    """
    from scipy.signal import correlate
    reports = []
    for index, segment in enumerate(plan["segments"]):
        left = segment["crossfade_samples"]
        right = plan["segments"][index+1]["crossfade_samples"] if index+1 < len(plan["segments"]) else 0
        length = segment["length_samples"]-left-right
        if length < 256:
            reports.append({"id": segment["id"], "status": "unmeasurable", "reason": "No untouched correlation window"})
            continue
        count = min(length, SAMPLE_RATE*2)
        reference = source_segments[index][left:left+count].astype(float).mean(axis=1)
        actual = rendered[segment["start_sample"]+left:segment["start_sample"]+left+count].astype(float).mean(axis=1)
        error = float(np.max(np.abs(actual-reference)))
        exact = error <= 1e-6
        if np.std(reference) < 1e-7:
            reports.append({"id": segment["id"], "status": "unmeasurable", "reason": "Silent or constant signal",
                            "exact_pcm": exact, "maximum_error": error})
            continue
        a, b = actual-actual.mean(), reference-reference.mean()
        correlations = correlate(a, b, mode="full", method="fft")
        center = len(reference)-1
        low, high = max(0, center-max_shift_samples), min(len(correlations), center+max_shift_samples+1)
        shift = int(np.argmax(correlations[low:high])+low-center)
        coefficient = float(np.dot(a, b)/math.sqrt(np.dot(a, a)*np.dot(b, b))) if np.any(a) else 0.
        reports.append({"id": segment["id"], "status": "verified" if exact and shift == 0 else "failed",
                        "exact_pcm": exact, "maximum_error": error, "shift_samples": shift,
                        "shift_ms": 1000*shift/SAMPLE_RATE, "zero_shift_correlation": coefficient})
    return {"samples_expected": plan["samples"], "samples_actual": len(rendered),
            "exact_duration": len(rendered) == plan["samples"], "segments": reports,
            "timing_verified": all(r["status"] == "verified" for r in reports),
            "scope": "Placement of supplied audio segments; does not certify beat detection accuracy"}


def arrange_music(audio, beatmap, segments, output, beats_per_bar=4, first_downbeat=0, beats_output=None):
    plan = arrangement_plan(audio, beatmap, segments, beats_per_bar, first_downbeat)
    output = Path(output).resolve()
    if output == Path(plan["source"]):
        raise ValueError("Arrangement cannot overwrite its source")
    if output.suffix.lower() != ".wav":
        raise ValueError("Arrangement output must be .wav for lossless timing verification")
    map_path = Path(beats_output).resolve() if beats_output else output.with_suffix(".beats.json")
    if map_path in (Path(plan["source"]), output):
        raise ValueError("Beat-map output cannot overwrite audio")
    mixed = np.zeros((plan["samples"], 2), np.float32)
    sources = []
    for segment in plan["segments"]:
        samples = decode_audio(plan["source"], segment["source_start_sample"]/SAMPLE_RATE, segment["length_samples"]/SAMPLE_RATE)
        if abs(len(samples)-segment["length_samples"]) > 1:
            raise RuntimeError("Decoded arrangement segment has an unexpected sample count")
        if len(samples) != segment["length_samples"]:
            samples = np.pad(samples, ((0, segment["length_samples"]-len(samples)), (0, 0)))
        sources.append(samples.copy())
        start, end, crossfade = segment["start_sample"], segment["end_sample"], segment["crossfade_samples"]
        if crossfade:
            ramp = np.linspace(0, 1, crossfade, dtype=np.float32)[:, None]
            mixed[start:start+crossfade] *= 1-ramp
            samples[:crossfade] *= ramp
        mixed[start:end] += samples
    write_audio(output, mixed)
    verification = verify_arrangement(decode_audio(output), sources, plan)
    if not verification["exact_duration"] or any(s["status"] == "failed" for s in verification["segments"]):
        raise RuntimeError("Arrangement PCM verification failed")
    # Reanalyze actual rendered audio, while retaining the deterministic mapped
    # grid separately so a beat detector cannot silently redefine user choices.
    configure_numba_cache(output.parent/".beat-sync-cache"/"numba")
    from beat_map import analyze_audio
    with contextlib.redirect_stdout(io.StringIO()):
        new_map = analyze_audio(str(output), segment_duration=plan["duration"])
    transformed = []
    for segment in plan["segments"]:
        for beat in beatmap["beats"][segment["start_beat"]:segment["end_beat"]]:
            transformed.append((segment["start_sample"]-segment["source_start_sample"])/SAMPLE_RATE+float(beat))
    new_map["arranged_beats"] = sorted(set(round(t, 9) for t in transformed))
    new_map["arrangement"] = {**plan, "verification": verification, "output_sha256": digest(output)}
    from project_workspace import write_json
    write_json(map_path, new_map)
    return {"path": str(output), "beatmap": str(map_path), "duration": plan["duration"], "samples": plan["samples"],
            "verification": verification, "segments": plan["segments"], "sha256": digest(output)}

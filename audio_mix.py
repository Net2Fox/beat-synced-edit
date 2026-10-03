"""Sample-exact local audio stems, source retiming, ducking and loudness QA.

The mixer uses stereo float PCM at 48 kHz. Source sound follows the same mapping
as picture; ``pitch_mode=preserve`` uses a variable-step phase vocoder, while
``resample`` intentionally changes pitch with speed. Natural-speed audio is copied.
No sound is synthesized and no remote services are used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import numpy as np

SAMPLE_RATE = 48000
MIX_VERSION = 1


def configure_numba_cache(directory=None):
    """Avoid Numba probing unwritable site-packages under agent sandboxes."""
    if "NUMBA_CACHE_DIR" not in os.environ:
        destination = Path(directory) if directory else Path(tempfile.gettempdir())/"beat-sync-numba-cache"
        destination.mkdir(parents=True, exist_ok=True)
        os.environ["NUMBA_CACHE_DIR"] = str(destination.resolve())


def number(value, label, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise ValueError(f"{label} is outside its finite allowed range [{minimum}, {maximum}]")
    return result


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        error = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"{Path(args[0]).name} failed: {error[-4000:]}")
    return result


def audio_info(path):
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise FileNotFoundError(f"Audio source must be an existing absolute file: {path}")
    data = json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout)
    stream = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if stream is None:
        return None
    duration = number(stream.get("duration") or data.get("format", {}).get("duration", 0), "audio duration", 0)
    return {"duration": duration, "sample_rate": int(stream.get("sample_rate", SAMPLE_RATE)),
            "channels": int(stream.get("channels", 2))}


def decode_audio(path, start=0, duration=None):
    """Accurate seeking/decoding; return stereo float32 without clipping."""
    args = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.12f}", "-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.12f}"]
    args += ["-map", "0:a:0", "-vn", "-ar", str(SAMPLE_RATE), "-ac", "2", "-f", "f32le", "pipe:1"]
    pcm = np.frombuffer(_run(args).stdout, dtype="<f4")
    if len(pcm) % 2 or not np.all(np.isfinite(pcm)):
        raise ValueError("Decoded audio contains malformed or non-finite samples")
    return pcm.reshape(-1, 2).copy()


def write_audio(path, samples):
    """Atomic float WAV write, retaining headroom for the normalization stage."""
    path = Path(path).resolve()
    if path.suffix.lower() != ".wav":
        raise ValueError("Audio stem/arrangement output must be .wav")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.wav")
    try:
        _run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "2",
              "-i", "pipe:0", "-c:a", "pcm_f32le", str(temporary)], input=np.asarray(samples, dtype="<f4").tobytes())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _length(samples, count):
    result = np.zeros((count, 2), np.float32)
    result[:min(len(samples), count)] = samples[:count]
    return result


def _track_options(track):
    if track.get("role", "sfx") not in ("music", "voice", "sfx", "speech", "ambient"):
        raise ValueError("Audio role must be music, voice, sfx, speech or ambient")
    for key, default, low, high in (("gain_db", 0, -96, 36), ("fade_in", 0, 0, None), ("fade_out", 0, 0, None)):
        number(track.get(key, default), key, low, high)
    if track.get("pitch_mode", "preserve") not in ("preserve", "resample"):
        raise ValueError("pitch_mode must be preserve or resample")
    if "loop" in track and not isinstance(track["loop"], bool):
        raise ValueError("audio.loop must be boolean")


def _envelope(samples, track):
    samples = samples * np.float32(10 ** (number(track.get("gain_db", 0), "gain_db", -96, 36) / 20))
    for key, reverse in (("fade_in", False), ("fade_out", True)):
        n = min(len(samples), round(number(track.get(key, 0), key, 0) * SAMPLE_RATE))
        if n:
            envelope = np.linspace(0, 1, n, dtype=np.float32)
            if reverse:
                samples[-n:] *= envelope[::-1, None]
            else:
                samples[:n] *= envelope[:, None]
    return samples


def _positions(plan, track):
    if "anchor" not in track:
        return [number(track.get("start", 0), "track start", 0)]
    from timeline_map import resolve_anchor
    values = resolve_anchor(plan, track["anchor"])
    if not values:
        raise ValueError(f"Audio anchor did not resolve: {track['anchor']}")
    # Repeated source occurrences require an explicit policy; never silently pick.
    if len(values) > 1 and track.get("occurrences") != "all":
        if "occurrence" not in track:
            raise ValueError("Audio anchor is ambiguous; set occurrence (zero based) or occurrences=all")
        index = number(track["occurrence"], "occurrence", 0)
        if int(index) != index or index >= len(values):
            raise ValueError("Audio anchor occurrence is outside its matches")
        values = [values[int(index)]]
    offset = number(track.get("offset", 0), "anchor offset")
    return [float(frame) / plan["output"]["fps"] + offset for frame in values]


def expanded_tracks(plan, check_files=True):
    """Resolve all placements afresh, so anchors follow timeline revisions."""
    duration = number(plan["duration_frames"], "duration_frames", 1) / number(plan["output"]["fps"], "fps", 1)
    config = plan.get("audio_mix") or {}
    if not isinstance(config, dict):
        raise ValueError("audio_mix must be an object")
    tracks = copy.deepcopy(config.get("tracks", []))
    if not isinstance(tracks, list):
        raise ValueError("audio_mix.tracks must be an array")
    legacy = plan.get("audio") or {}
    if legacy.get("path") and not config.get("replace_legacy", False):
        tracks.insert(0, {"id": "legacy-music", "role": "music", "path": legacy["path"],
                          "source_start": legacy.get("start", 0), "duration": duration,
                          "loop": legacy.get("loop", False), "gain_db": legacy.get("gain_db", 0)})
    expanded, identities = [], set()
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise ValueError("Each audio track must be an object")
        _track_options(track)
        identity = str(track.get("id", f"audio-{index + 1}"))
        if identity in identities:
            raise ValueError(f"Duplicate audio track id: {identity}")
        identities.add(identity)
        track["id"] = identity
        track.setdefault("role", "sfx")
        track["source_start"] = number(track.get("source_start", 0), "source_start", 0)
        path = Path(track.get("path", ""))
        if not path.is_absolute():
            raise ValueError("Audio track paths must be absolute")
        info = audio_info(path) if check_files else None
        if check_files and info is None:
            raise ValueError(f"Audio track has no audio stream: {path}")
        available = info["duration"] if info else track.get("source_end")
        end = number(track.get("source_end", available), "source_end", track["source_start"]) if available is not None else None
        if end is not None and end <= track["source_start"]:
            raise ValueError("Audio source_start/source_end must select a positive span")
        if info and end > info["duration"] + .002:
            raise ValueError("Audio source_end exceeds the recording")
        for occurrence, start in enumerate(_positions(plan, track)):
            if not 0 <= start < duration:
                raise ValueError(f"Audio placement {identity} starts outside the project")
            length = number(track.get("duration", min(end-track["source_start"], duration-start) if end is not None else duration-start), "track duration", .00001)
            if start + length > duration + 1 / SAMPLE_RATE:
                raise ValueError("Audio track extends beyond the project; shorten its duration")
            if end is not None and not track.get("loop", False) and length > end-track["source_start"] + .002:
                raise ValueError("The soundtrack is shorter than the edit; choose an earlier start or explicitly enable audio.loop")
            expanded.append({**track, "start": start, "duration": length, "source_end": end,
                             "placement_id": f"{identity}:{occurrence}"})
    return expanded


def validate_audio_mix(plan, check_files=False):
    config = plan.get("audio_mix") or {}
    if not isinstance(config, dict):
        raise ValueError("audio_mix must be an object")
    if config.get("version", 1) != 1:
        raise ValueError("Unsupported audio_mix version")
    source = config.get("source_audio", {})
    if isinstance(source, bool):
        source = {"enabled": source}
    if not isinstance(source, dict):
        raise ValueError("source_audio must be an object or boolean")
    _track_options(source)
    if "enabled" in source and not isinstance(source["enabled"], bool):
        raise ValueError("source_audio.enabled must be boolean")
    for label in ("replace_legacy", "allow_silence"):
        if label in config and not isinstance(config[label], bool):
            raise ValueError(f"{label} must be boolean")
    duck = config.get("ducking", {})
    if not isinstance(duck, dict) or ("enabled" in duck and not isinstance(duck["enabled"], bool)):
        raise ValueError("ducking must be an object with boolean enabled")
    for key, default, lo, hi in (("threshold_db", -35, -96, 0), ("reduction_db", 12, 0, 60),
                                 ("attack", .03, .001, 10), ("release", .3, .001, 10)):
        number(duck.get(key, default), key, lo, hi)
    loud = config.get("loudness", {})
    if not isinstance(loud, dict) or ("enabled" in loud and not isinstance(loud["enabled"], bool)):
        raise ValueError("loudness must be an object with boolean enabled")
    for key, default, lo, hi in (("integrated", -16, -70, -5), ("true_peak", -1.5, -9, 0), ("lra", 11, 1, 50)):
        number(loud.get(key, default), key, lo, hi)
    return expanded_tracks(plan, check_files)


def retime_source(samples, edit, count, pitch_mode="preserve"):
    from timeline_map import source_times
    duration = count / SAMPLE_RATE
    start = float(edit["source_start"])
    # Identical source/output spans are only copyable if mapping itself is linear.
    grid = np.linspace(0, 1, 129)
    linear = np.max(np.abs(source_times(edit, grid) - (start + duration * grid))) < 1e-7
    if linear:
        return _length(samples, count)
    if pitch_mode == "resample":
        positions = (source_times(edit, np.arange(count) / count) - start) * SAMPLE_RATE
        return np.column_stack([np.interp(positions, np.arange(len(samples)), samples[:, c], right=0) for c in range(2)]).astype(np.float32)
    configure_numba_cache()
    import librosa
    n_fft, hop = 2048, 256
    output = []
    positions = np.minimum(np.arange(1 + count // hop) * hop / count, 1)
    steps = (source_times(edit, positions) - start) * SAMPLE_RATE / hop
    phase_advance = np.linspace(0, np.pi * hop, 1 + n_fft // 2)
    for channel in range(2):
        stft = librosa.stft(samples[:, channel], n_fft=n_fft, hop_length=hop)
        padded = np.pad(stft, ((0, 0), (0, 2)))
        result = np.zeros((stft.shape[0], len(steps)), dtype=np.complex64)
        phase = np.angle(stft[:, 0]).astype(np.float64)
        for i, step in enumerate(steps):
            index = min(int(step), stft.shape[1]-1)
            fraction = min(1, step-index)
            a, b = padded[:, index], padded[:, index+1]
            magnitude = (1-fraction)*np.abs(a) + fraction*np.abs(b)
            result[:, i] = magnitude * np.exp(1j * phase)
            difference = np.angle(b)-np.angle(a)-phase_advance
            difference -= 2*np.pi*np.round(difference/(2*np.pi))
            phase += phase_advance+difference
        output.append(librosa.istft(result, hop_length=hop, length=count))
    return np.column_stack(output).astype(np.float32)


def duck_envelope(voice, config):
    """10 ms RMS detector, sample-continuous attack/release, bounded gain."""
    count = len(voice)
    if not count:
        return np.zeros(0, np.float32)
    block = 480
    pad = (-count) % block
    blocks = np.pad(voice, ((0, pad), (0, 0))).reshape(-1, block, 2)
    rms = np.sqrt(np.mean(blocks.astype(np.float64)**2, axis=(1, 2)))
    threshold = 10**(float(config.get("threshold_db", -35))/20)
    reduction = 10**(-float(config.get("reduction_db", 12))/20)
    targets = np.where(rms >= threshold, reduction, 1.)
    gains = np.empty_like(targets)
    gain = 1.
    for i, target in enumerate(targets):
        tau = float(config.get("attack", .03) if target < gain else config.get("release", .3))
        coefficient = math.exp(-block/(SAMPLE_RATE*tau))
        gain = target+(gain-target)*coefficient
        gains[i] = gain
    # Continuous interpolation avoids zipper noise at detector block boundaries.
    return np.interp(np.arange(count), np.arange(len(gains))*block, gains).astype(np.float32)


def measure_loudness(path, targets=None):
    targets = targets or {}
    integrated, peak, lra = (float(targets.get(k, d)) for k, d in (("integrated", -16), ("true_peak", -1.5), ("lra", 11)))
    result = _run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af",
                   f"loudnorm=I={integrated}:TP={peak}:LRA={lra}:print_format=json", "-f", "null", "-"])
    stderr = result.stderr.decode("utf-8", "replace")
    begin, end = stderr.rfind("{"), stderr.rfind("}")
    if begin < 0 or end < begin:
        raise RuntimeError("FFmpeg did not return loudness measurements")
    raw = json.loads(stderr[begin:end+1])
    measured = {}
    for key, source in (("integrated_lufs", "input_i"), ("true_peak_dbtp", "input_tp"), ("lra_lu", "input_lra"), ("threshold_lufs", "input_thresh")):
        value = float(raw[source])
        measured[key] = value if math.isfinite(value) else None
    measured.update(measurable=measured["integrated_lufs"] is not None, raw=raw)
    return measured


def normalize_loudness(source, output, targets, count):
    measurement = measure_loudness(source, targets)
    if not measurement["measurable"]:
        write_audio(output, decode_audio(source))
        return {"method": "skipped_unmeasurable", "before": measurement}
    raw = measurement["raw"]
    expression = (f"loudnorm=I={targets.get('integrated', -16)}:TP={targets.get('true_peak', -1.5)}:LRA={targets.get('lra', 11)}"
                  f":measured_I={raw['input_i']}:measured_TP={raw['input_tp']}:measured_LRA={raw['input_lra']}"
                  f":measured_thresh={raw['input_thresh']}:offset={raw['target_offset']}:linear=true:print_format=json"
                  f",aresample={SAMPLE_RATE},apad,atrim=end_sample={count}")
    _run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(source), "-af", expression,
          "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_f32le", str(output)])
    return {"method": "two_pass_loudnorm", "before": measurement, "after": measure_loudness(output, targets)}


def mix_project_audio(plan, cache_dir):
    """Return (48 kHz WAV, provenance report). Cached files are hash-verified."""
    tracks = validate_audio_mix(plan, check_files=True)
    config = plan.get("audio_mix") or {}
    source_config = config.get("source_audio") or {}
    if isinstance(source_config, bool):
        source_config = {"enabled": source_config}
    if not tracks and not source_config.get("enabled", False) and not config.get("allow_silence", False):
        raise ValueError("Project has no audio; enable source_audio, add a track or explicitly set allow_silence=true")
    count = round(plan["duration_frames"] / plan["output"]["fps"] * SAMPLE_RATE)
    sources = {str(Path(t["path"]).resolve()) for t in tracks}
    if source_config.get("enabled", False):
        sources.update(str(Path(e.get("audio_source", e)["source"]).resolve()) for e in plan["edits"]
                       if e.get("audio_source", e).get("kind", "video") == "video")
    hashes = {path: digest(path) for path in sorted(sources)}
    signature = {"version": MIX_VERSION, "config": config, "tracks": tracks, "count": count,
                 "fps": plan["output"]["fps"], "edits": plan["edits"] if source_config.get("enabled", False) else [], "sources": hashes}
    key = hashlib.sha256(json.dumps(signature, sort_keys=True, allow_nan=False).encode()).hexdigest()
    cache = Path(cache_dir).resolve() / "audio"
    cache.mkdir(parents=True, exist_ok=True)
    configure_numba_cache(cache / "numba")
    output, metadata = cache / f"{key}.wav", cache / f"{key}.json"
    if output.is_file() and metadata.is_file():
        try:
            report = json.loads(metadata.read_text(encoding="utf-8"))
            stems_valid = all(Path(s["path"]).is_file() and digest(s["path"]) == s["sha256"] for s in report.get("grouped_stems", []))
            if stems_valid and report["sha256"] == digest(output) and len(decode_audio(output)) == count:
                return output, {**report, "cache_hit": True}
        except (ValueError, KeyError, RuntimeError):
            pass
    music, voice, other = (np.zeros((count, 2), np.float32) for _ in range(3))
    stems, warnings = [], []
    if source_config.get("enabled", False):
        for edit in plan["edits"]:
            audio_edit = {**edit, **edit.get("audio_source", {})}
            if audio_edit.get("kind", "video") != "video":
                continue
            path = audio_edit["source"]
            info = audio_info(path)
            if info is None:
                warnings.append(f"Shot {edit['id']} has no source audio")
                continue
            start, end = float(audio_edit["source_start"]), float(audio_edit["source_end"])
            if start < 0 or end <= start or end > info["duration"]+.05:
                raise ValueError(f"Source audio range outside recording: {edit['id']}")
            first = round(edit["timeline_start_frame"]/plan["output"]["fps"]*SAMPLE_RATE)
            last = round(edit["timeline_end_frame"]/plan["output"]["fps"]*SAMPLE_RATE)
            options = {**source_config, **edit.get("audio", {})}
            _track_options(options)
            if options.get("muted", False):
                continue
            samples = retime_source(decode_audio(path, start, end-start), audio_edit, last-first, options.get("pitch_mode", "preserve"))
            samples = _envelope(samples, options)
            destination = voice if options.get("role", "speech") in ("speech", "voice") else other
            destination[first:last] += samples
            stems.append({"id": "source:"+edit["id"], "role": options.get("role", "speech"), "path": path,
                          "source_start": start, "source_end": end, "start_sample": first, "end_sample": last,
                          "pitch_mode": options.get("pitch_mode", "preserve"), "source_sha256": hashes[str(Path(path).resolve())]})
    for track in tracks:
        first = round(track["start"]*SAMPLE_RATE)
        length = min(round(track["duration"]*SAMPLE_RATE), count-first)
        span = track["source_end"]-track["source_start"]
        samples = decode_audio(track["path"], track["source_start"], min(span, track["duration"]))
        if track.get("loop", False):
            if len(samples) == 0:
                raise ValueError("Cannot loop empty audio")
            samples = np.tile(samples, (math.ceil(length/len(samples)), 1))
        samples = _envelope(_length(samples, length), track)
        destination = music if track["role"] == "music" else voice if track["role"] in ("voice", "speech") else other
        destination[first:first+length] += samples
        stems.append({**track, "start_sample": first, "end_sample": first+length,
                      "source_sha256": hashes[str(Path(track["path"]).resolve())]})
    duck = config.get("ducking", {})
    if duck.get("enabled", True) and np.any(voice) and np.any(music):
        envelope = duck_envelope(voice, duck)
        music *= envelope[:, None]
        duck_report = {"applied": True, "minimum_gain": float(envelope.min()), **duck}
    else:
        duck_report = {"applied": False, **duck}
    mixed = music+voice+other
    if not np.all(np.isfinite(mixed)):
        raise ValueError("Audio mix produced non-finite samples")
    raw = cache / f"{key}.raw.wav"
    grouped_stems = []
    for name, samples in (("music", music), ("voice", voice), ("effects_ambient", other)):
        if np.any(samples):
            stem_path = cache / f"{key}.{name}.wav"
            write_audio(stem_path, samples)
            grouped_stems.append({"role": name, "path": str(stem_path), "sha256": digest(stem_path), "samples": count})
    write_audio(raw, mixed)
    loudness = config.get("loudness", {})
    # Preserve old projects' gain until the user opts into the expanded mixer.
    normalize = loudness.get("enabled", bool(plan.get("audio_mix")))
    if normalize:
        normalization = normalize_loudness(raw, output, loudness, count)
    else:
        os.replace(raw, output)
        normalization = {"method": "disabled"}
    raw.unlink(missing_ok=True)
    report = {"version": MIX_VERSION, "path": str(output), "samples": count, "sample_rate": SAMPLE_RATE,
              "channels": 2, "duration": count/SAMPLE_RATE, "sha256": digest(output), "cache_hit": False,
              "sources": hashes, "stems": stems, "grouped_stems": grouped_stems, "ducking": duck_report, "normalization": normalization,
              "targets": loudness if normalize else None, "pre_normalization_peak": float(np.max(np.abs(mixed))),
              "silent": not bool(np.any(mixed)), "warnings": warnings}
    from project_workspace import write_json
    write_json(metadata, report)
    return output, report


def encoded_audio_report(path, mix_report):
    targets = mix_report.get("targets")
    measured = measure_loudness(path, targets)
    result = {**mix_report, "encoded_path": str(Path(path).resolve()), "encoded_measurements": measured}
    if targets is not None and measured["measurable"]:
        result["loudness_within_tolerance"] = (abs(measured["integrated_lufs"]-targets.get("integrated", -16)) <= 1
                                               and measured["true_peak_dbtp"] <= targets.get("true_peak", -1.5)+.5)
    else:
        result["loudness_within_tolerance"] = None
    return result

"""Music analysis for beat-synced editing.

analyze_audio() measures tempo, beats, the energy curve, the most energetic
segments and the musical structure used by ``edit_project.py music``.
"""

import json
import os
import subprocess
import tempfile

import numpy as np

# Numba must not attempt to cache into an installed, read-only skill/dependency
# directory. Respect an explicit cache setting, otherwise use the user's temp.
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "beat-sync-numba-cache"))

try:
    import librosa
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise RuntimeError("librosa is required for music analysis; install the skill's requirements.txt") from exc


def find_top_segments(times, energy, target_duration=15.0, num_segments=3):
    """
    Find the top N most energetic non-overlapping segments.

    Uses a sliding window approach with exclusion zones to find windows with
    highest average energy that don't overlap with each other.
    Returns list of segments sorted by energy (highest first).
    """
    if len(times) < 2:
        return [{"rank": 1, "start": 0, "end": 0, "duration": 0, "avg_energy": 0}]

    # Calculate time step between samples
    time_step = times[1] - times[0] if len(times) > 1 else 0.1
    window_size = int(target_duration / time_step)

    # If audio too short for even one segment, return the whole thing
    if window_size >= len(energy):
        return [{
            "rank": 1,
            "start": round(float(times[0]), 2),
            "end": round(float(times[-1]), 2),
            "duration": round(float(times[-1] - times[0]), 2),
            "avg_energy": round(float(np.mean(energy)), 3)
        }]

    segments = []
    used_ranges = []
    cumsum = np.cumsum(energy)

    for seg_num in range(num_segments):
        best_start_idx = None
        best_avg_energy = 0

        for i in range(len(energy) - window_size):
            window_start = times[i]
            window_end = times[min(i + window_size, len(times) - 1)]

            # Check overlap with already used ranges
            overlaps = any(
                not (window_end <= used_start or window_start >= used_end)
                for used_start, used_end in used_ranges
            )
            if overlaps:
                continue

            # Calculate avg energy using cumsum
            if i == 0:
                window_sum = cumsum[window_size - 1]
            else:
                window_sum = cumsum[i + window_size - 1] - cumsum[i - 1]
            avg_energy = window_sum / window_size

            if avg_energy > best_avg_energy:
                best_avg_energy = avg_energy
                best_start_idx = i

        if best_start_idx is None:
            break  # No more non-overlapping segments fit

        start_time = times[best_start_idx]
        end_idx = min(best_start_idx + window_size, len(times) - 1)
        end_time = times[end_idx]
        used_ranges.append((start_time, end_time))

        segments.append({
            "rank": len(segments) + 1,
            "start": round(float(start_time), 2),
            "end": round(float(end_time), 2),
            "duration": round(float(end_time - start_time), 2),
            "avg_energy": round(float(best_avg_energy), 3)
        })

    return segments


def _load_audio(audio_path, sample_rate=22050):
    """Load mono audio at librosa's default rate, also from video containers.

    soundfile reads WAV/FLAC/OGG/MP3 only and librosa 1.0 has no audioread
    fallback, so a song inside MP4/M4A/WebM/MKV fails with "Format not
    recognised". Those are decoded with the system FFmpeg, which the skill
    already requires for rendering, to the same signal librosa would return:
    22050 Hz, float32, channels averaged.
    """
    try:
        return librosa.load(audio_path)
    except Exception as load_error:  # soundfile.LibsndfileError, NoBackendError, ...
        if not os.path.isfile(audio_path):
            raise

        def run(arguments):
            try:
                return subprocess.run(arguments, capture_output=True)
            except OSError as exc:
                raise RuntimeError(f"Cannot read audio from {audio_path}: {load_error}. "
                                   f"Decoding it needs FFmpeg and ffprobe on PATH ({exc})") from load_error

        probe = run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                     "stream=start_time,duration:stream_tags=DURATION:format=start_time,duration,format_name",
                     "-of", "json", str(audio_path)])
        try:
            info = json.loads(probe.stdout or b"{}")
        except ValueError:
            info = {}
        streams = info.get("streams") or []
        if probe.returncode == 0 and not streams:
            raise RuntimeError(f"No audio stream in {audio_path}") from load_error

        def seconds(value):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if np.isfinite(number) else None

        stream = streams[0] if streams else {}
        stream_start = seconds(stream.get("start_time"))
        container_start = seconds((info.get("format") or {}).get("start_time"))
        if stream_start is not None and container_start is not None and stream_start - container_start > .05:
            # These samples start at the first audio sample; the renderer seeks the song on the
            # container's timeline (audio_mix.decode_audio). A late audio stream would shift every beat.
            raise RuntimeError(f"The audio in {audio_path} starts {stream_start - container_start:.3f}s after the "
                               "file itself, so measured beat times would not match the render. Extract the song "
                               "first (ffmpeg -i <file> -vn song.wav) and analyze that file.") from load_error

        result = run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio_path), "-map", "0:a:0", "-vn",
                      # Average the channels like librosa; plain -ac 1 sums stereo 3 dB hotter.
                      "-af", "aresample=rematrix_maxval=1.0", "-ac", "1", "-ar", str(sample_rate),
                      "-f", "f32le", "pipe:1"])
        samples = np.frombuffer(result.stdout[:len(result.stdout) // 4 * 4], dtype="<f4")
        detail = result.stderr.decode("utf-8", "replace").strip()[-2000:]
        if result.returncode != 0 or not len(samples):
            raise RuntimeError(f"Cannot decode audio from {audio_path}: {detail or load_error}") from load_error
        if not np.all(np.isfinite(samples)):
            raise RuntimeError(f"Decoded audio from {audio_path} contains non-finite samples") from load_error
        # FFmpeg exits 0 after a truncated or damaged container; do not analyze half a song. Only
        # containers that record the real length are checked: a raw AAC/MP3 stream's duration is an estimate.
        container = set(str((info.get("format") or {}).get("format_name") or "").split(","))
        expected = seconds(stream.get("duration"))
        if expected is None and "matroska" in container:
            # Matroska/WebM keep a stream's length in a DURATION tag ("00:03:25.481000000").
            try:
                hours, minutes, rest = str((stream.get("tags") or {}).get("DURATION")).split(":")
                expected = seconds(int(hours) * 3600 + int(minutes) * 60 + float(rest))
            except ValueError:
                expected = seconds((info.get("format") or {}).get("duration"))
        decoded = len(samples) / sample_rate
        # MP4/MOV: the length comes from the sample index and a cut inside a video frame ends
        # silently. Matroska: only when FFmpeg reported a problem, since the audio may simply be
        # shorter than the picture.
        checked = "mov" in container or ("matroska" in container and detail)
        if checked and expected and decoded < expected - max(.5, .02 * expected):
            raise RuntimeError(f"Only {decoded:.2f}s of the {expected:.2f}s of audio in {audio_path} could be "
                               f"decoded: {detail or 'the file ends early (truncated download or copy?)'}") from load_error
        return samples.astype(np.float32, copy=True), sample_rate


def analyze_audio(audio_path, hop_length=512, segment_duration=15.0, overrides=None):
    """
    Analyze audio file for beats, tempo, and energy.

    Returns a dict with tempo (BPM), beat_count, beats (seconds), energy_curve,
    energy peaks/valleys, best_segment and top_segments (the most energetic
    windows of segment_duration seconds) and music_structure (sections, pulse
    confidence and phrase candidates).
    """
    y, sr = _load_audio(audio_path)
    duration = librosa.get_duration(y=y, sr=sr)

    # Detect tempo and beats
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    # Handle tempo as array or scalar
    if hasattr(tempo, '__len__'):
        tempo = float(tempo[0])
    else:
        tempo = float(tempo)

    # Calculate RMS energy over time
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

    # Normalize energy to 0-1 range
    rms_normalized = (rms - rms.min()) / (rms.max() - rms.min() + 1e-10)

    # Smooth the energy curve, then find energy peaks (hills) and valleys.
    from scipy.ndimage import gaussian_filter1d
    rms_smooth = gaussian_filter1d(rms_normalized, sigma=5)

    # Find local maxima (peaks/hills)
    peaks = []
    valleys = []

    window = 10  # frames to look around
    threshold_high = 0.6  # energy level for peaks
    threshold_low = 0.3   # energy level for valleys

    for i in range(window, len(rms_smooth) - window):
        local_max = rms_smooth[i] == max(rms_smooth[i-window:i+window+1])
        local_min = rms_smooth[i] == min(rms_smooth[i-window:i+window+1])

        if local_max and rms_smooth[i] > threshold_high:
            peaks.append({
                "time": round(float(times[i]), 3),
                "energy": round(float(rms_smooth[i]), 3)
            })
        elif local_min and rms_smooth[i] < threshold_low:
            valleys.append({
                "time": round(float(times[i]), 3),
                "energy": round(float(rms_smooth[i]), 3)
            })

    # Downsample energy curve for output (every 0.1 seconds)
    sample_interval = int(0.1 * sr / hop_length)
    energy_curve = [
        {
            "time": round(float(times[i]), 2),
            "energy": round(float(rms_normalized[i]), 3)
        }
        for i in range(0, len(times), max(1, sample_interval))
    ]

    # The three most energetic non-overlapping segments of the requested duration.
    top_segments = find_top_segments(
        np.array(times),
        rms_smooth,  # Use smoothed energy for more stable results
        target_duration=segment_duration,
        num_segments=3
    )

    best_segment = top_segments[0] if top_segments else {"start": 0, "end": 0, "duration": 0, "avg_energy": 0}

    from music_structure import analyze_structure, apply_overrides
    onset_envelope = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_envelope, sr=sr, hop_length=hop_length)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    structure = analyze_structure(times, rms, onset_times, onset_envelope[onset_frames], beat_times, duration)
    result = {
        "file": os.path.abspath(audio_path),
        "duration": round(duration, 9),
        "tempo": round(tempo, 1),
        "beat_count": len(beat_times),
        "beats": [round(float(t), 3) for t in beat_times],
        "energy_curve": energy_curve,
        "peaks": peaks,
        "valleys": valleys,
        "best_segment": best_segment,
        "top_segments": top_segments,
        "music_structure": structure,
    }
    return apply_overrides(result, overrides) if overrides is not None else result

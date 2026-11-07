#!/usr/bin/env python3
"""Optional local faster-whisper speech transcription with real word timings.

The first call may download model weights; audio is decoded and recognized on
this computer, never uploaded. Pass a local CTranslate2 model path and
local_files_only=True to run without model downloads.
"""

import math
import os
from pathlib import Path
import sys

_MODEL_CACHE = {}


def clear_model_cache():
    """Explicitly release batch recognizers (normal CLI lifetime is one run)."""
    _MODEL_CACHE.clear()


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Recognizer returned invalid {name}")
    return float(value)


def _user_cache_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def default_model_dir(project_dir):
    """Folder for Whisper model downloads when --model-dir is not given.

    BEAT_SYNC_MODEL_DIR wins. A non-empty ``models`` folder beside the project
    (from an earlier run) is reused. Otherwise one shared per-user cache keeps a
    model to a single download for every project; if that folder cannot be
    written (for example inside an agent sandbox), the project's own
    ``models`` folder is used.
    """
    configured = os.environ.get("BEAT_SYNC_MODEL_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local = Path(project_dir).resolve() / "models"
    if local.is_dir() and any(local.iterdir()):
        return local
    shared = _user_cache_dir() / "beat-sync-edit" / "models"
    try:
        shared.mkdir(parents=True, exist_ok=True)
        probe = shared / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return shared.resolve()
    except OSError:
        return local


def transcribe_audio(audio_path, model="small", language=None, device="cpu",
                     compute_type="int8", model_dir=None, **kwargs):
    """Return JSON-safe segments from a local audio/video file.

    ``model_dir`` is the model download/cache directory. ``model`` may instead
    be an existing converted model folder. Extra keyword arguments are passed
    to WhisperModel.transcribe, except local_files_only/cpu_threads/num_workers,
    which configure the model. VAD and word timestamps are enabled by default.
    """
    source = Path(audio_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("audio_path must be a local audio or video file")
    if not isinstance(model, (str, Path)) or not str(model).strip():
        raise ValueError("model must be a model name or local converted model directory")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        requirements = Path(__file__).resolve().parents[1] / "requirements-transcription.txt"
        raise RuntimeError("Automatic subtitles require the optional faster-whisper package. "
                           f'Install it with: "{sys.executable}" -m pip install -r "{requirements}". '
                           "Manual titles and SRT/VTT import do not require this package.") from exc
    model_options = {"device": device, "compute_type": compute_type}
    if model_dir is not None:
        model_options["download_root"] = str(Path(model_dir).expanduser().resolve())
    for key in ("local_files_only", "cpu_threads", "num_workers"):
        if key in kwargs:
            model_options[key] = kwargs.pop(key)
    options = {"language": language, "beam_size": 5, "vad_filter": True,
               "vad_parameters": {"min_silence_duration_ms": 500},
               "word_timestamps": True, "condition_on_previous_text": False, **kwargs}
    if options.get("task", "transcribe") != "transcribe":
        raise ValueError("Only transcription is supported; translate text separately without changing its timings")
    try:
        key = (WhisperModel, str(model), tuple(sorted(model_options.items())))
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = WhisperModel(str(model), **model_options)
        recognizer = _MODEL_CACHE[key]
        raw_segments, info = recognizer.transcribe(str(source), **options)
        result = []
        # Recognition is lazy: iterating here completes it before reporting success.
        for item in raw_segments:
            text = str(item.text).strip()
            if not text:
                continue
            start, end = _time(item.start, "segment start"), _time(item.end, "segment end")
            if end <= start:
                continue
            words, pending = [], ""
            for word in getattr(item, "words", None) or []:
                first, last = _time(word.start, "word start"), _time(word.end, "word end")
                value = str(word.word)
                # Whisper occasionally returns zero-length punctuation tokens.
                # Keep their text on the prior timed word rather than inventing
                # a word duration or passing an invalid highlight to the renderer.
                if not value.strip():
                    continue
                if last <= first:
                    if words:
                        words[-1]["text"] += value
                    else:
                        pending += value
                    continue
                first, last = max(start, first), min(end, last)
                if last > first:
                    words.append({"start": first, "end": last, "text": pending + value})
                    pending = ""
            result.append({"start": start, "end": end, "text": text, "words": words})
    except (OSError, RuntimeError, TypeError, ImportError) as exc:
        raise RuntimeError(f"Local speech transcription failed: {exc}. Check the model/cache path; "
                           "for an offline run pass a local converted model and local_files_only=True. "
                           "For package/API errors reinstall requirements-transcription.txt in the skill environment. "
                           "If GPU initialization failed, use device='cpu', compute_type='int8'.") from exc
    return {"segments": result, "language": getattr(info, "language", language),
            "language_probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None), "model": str(model),
            "audio_path": str(source), "engine": "faster-whisper", "local": True,
            "review_required": True}

#!/usr/bin/env python3
"""Optional local faster-whisper speech transcription with real word timings.

The first call may download model weights; audio is decoded and recognized on
this computer, never uploaded. Pass a local CTranslate2 model path and
local_files_only=True to run without model downloads.
"""

import math
from pathlib import Path


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Recognizer returned invalid {name}")
    return float(value)


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
        raise RuntimeError("Automatic subtitles require the optional faster-whisper package. "
                           "Install into the skill's Python environment with: "
                           "python -m pip install -r requirements-transcription.txt "
                           "(or python -m pip install 'faster-whisper>=1.1,<2' 'av>=11,<19'). "
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
        recognizer = WhisperModel(str(model), **model_options)
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

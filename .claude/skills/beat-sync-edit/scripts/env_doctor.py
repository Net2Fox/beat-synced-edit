"""Check the editing environment: Python packages, FFmpeg encoders, fonts and options.

Uses only the standard library at import time, so it reports exactly what is
missing before the dependencies are installed. Run it with the interpreter the
skill will use, the skill's .venv: `edit_project.py doctor`. With another
Python it warns and prints the commands that create and fill that .venv.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

# (import name, pip package, submodules the skill imports). Importing only the
# top-level package is not enough: librosa loads numba and soundfile lazily and
# `import PIL` does not load Pillow's native module.
REQUIRED_MODULES = (
    ("numpy", "numpy", ()),
    ("scipy", "scipy", ("scipy.signal", "scipy.ndimage")),
    ("cv2", "opencv-python", ()),
    ("librosa", "librosa", ("librosa.beat", "librosa.onset", "librosa.feature")),
    ("soundfile", "soundfile", ()),
    ("PIL", "pillow", ("PIL.Image", "PIL.ImageFont")),
    ("scenedetect", "scenedetect", ()),
)
OPTIONAL_MODULES = (("faster_whisper", "faster-whisper", "local speech recognition"),
                    ("av", "av", "audio decoding for faster-whisper"))
FONT_SAMPLE = "Aa Zz Яя Ёё Жж 0123456789 !?"
MINIMUM_PYTHON = (3, 12)
SKILL = Path(__file__).resolve().parents[1]
VENV = SKILL / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _command(argv, windows=None):
    """Format a command for the user's shell: PowerShell on Windows, POSIX sh elsewhere."""
    if not (os.name == "nt" if windows is None else windows):
        return shlex.join(str(part) for part in argv)
    quote = lambda part: part if re.fullmatch(r"[\w.-]+", part) else "'" + part.replace("'", "''") + "'"
    return "& " + " ".join(quote(str(part)) for part in argv)  # a quoted program needs the call operator


def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _in_skill_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def _skill_setup(requirements):
    """Commands that create the skill's .venv when missing and install into it."""
    steps = [] if VENV_PYTHON.exists() else [_command([sys.executable, "-m", "venv", VENV])]
    steps.append(_command([VENV_PYTHON, "-m", "pip", "install", "-r", SKILL / requirements]))
    return "; ".join(steps)


def _install(requirements):
    # Inside a virtual environment install there; never into a system Python.
    if _in_venv():
        return _command([sys.executable, "-m", "pip", "install", "-r", SKILL / requirements])
    return _skill_setup(requirements)


def _check(name, status, detail, hint=None, required=True):
    item = {"name": name, "status": status, "required": required, "detail": detail}
    if hint:
        item["hint"] = hint
    return item


def _version(module):
    return str(getattr(module, "__version__", getattr(module, "VERSION", "unknown")))


def _python_check():
    detail = f"{platform.python_implementation()} {platform.python_version()} at {sys.executable}"
    if sys.version_info[:2] < MINIMUM_PYTHON:
        return _check("python", "fail", detail, f"Use Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer")
    return _check("python", "pass", detail)


def _venv_check():
    if _in_skill_venv():
        return _check("venv", "pass", f"running in the skill environment {VENV}", required=False)
    if VENV_PYTHON.exists():
        hint = f"Run doctor and every skill command with {VENV_PYTHON}"
    else:
        hint = f"Create the skill environment and install its requirements: {_skill_setup('requirements.txt')}"
    return _check("venv", "warn", f"running with {sys.executable}, not the skill environment {VENV}", hint, required=False)


def _module_checks():
    # As in beat_map.py: numba must not try to cache inside a read-only install.
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(tempfile.gettempdir(), "beat-sync-numba-cache"))
    checks = []
    for module_name, package, submodules in REQUIRED_MODULES:
        try:
            module = importlib.import_module(module_name)
            for name in submodules:
                importlib.import_module(name)
            checks.append(_check(f"package:{package}", "pass", _version(module)))
        except Exception as exc:  # ImportError, OSError from native libraries and broken wheels alike
            hint = f"Install the base requirements: {_install('requirements.txt')}"
            if package == "soundfile":
                hint += " (if soundfile is installed, the libsndfile system library is missing)"
            checks.append(_check(f"package:{package}", "fail", f"{type(exc).__name__}: {exc}", hint))
    for module_name, package, purpose in OPTIONAL_MODULES:
        try:
            module = importlib.import_module(module_name)
            version = _version(module)
            status, hint = "pass", None
            major = version.split(".")[0]
            if module_name == "av" and major.isdigit() and int(major) >= 19:
                status, hint = "warn", f"PyAV 19+ is incompatible with faster-whisper 1.2: {_install('requirements-transcription.txt')}"
            checks.append(_check(f"optional:{package}", status, f"{version} ({purpose})", hint, required=False))
        except Exception:
            checks.append(_check(f"optional:{package}", "missing", f"not installed ({purpose})",
                                 f"Only needed to transcribe speech without a transcript: {_install('requirements-transcription.txt')}",
                                 required=False))
    return checks


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    return result, None


def _encoder_names(listing):
    """Encoder names from `ffmpeg -encoders`; legend lines carry '=' as the second token."""
    return {line.split()[1] for line in listing.splitlines()
            if line.startswith(" ") and len(line.split()) > 1 and line.split()[1] != "="}


def _ffmpeg_checks():
    checks = []
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path:
            checks.append(_check(tool, "fail", "not found on PATH",
                                 "Install FFmpeg (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)"))
            continue
        result, error = _run([path, "-hide_banner", "-version"])
        first = (result.stdout.splitlines() or ["unknown version"])[0] if result else error
        checks.append(_check(tool, "pass" if result and result.returncode == 0 else "fail", f"{first} ({path})"))
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        result, error = _run([ffmpeg, "-hide_banner", "-encoders"])
        if result is None or result.returncode != 0:
            reason = error or (result.stderr.strip().splitlines() or [f"exit code {result.returncode}"])[-1]
            checks.append(_check("encoders", "fail", f"ffmpeg -encoders failed: {reason}",
                                 "Reinstall FFmpeg; a working build lists its encoders with `ffmpeg -encoders`"))
            return checks
        names = _encoder_names(result.stdout)
        for encoder, purpose in (("libx264", "H.264 video"), ("aac", "AAC audio")):
            found = encoder in names
            checks.append(_check(f"encoder:{encoder}", "pass" if found else "fail",
                                 f"{purpose} encoder {'available' if found else 'missing'}",
                                 None if found else "Install an FFmpeg build with libx264 and the native AAC encoder"))
    return checks


def _font_check():
    try:
        from text_overlay import _font_path
        from font_diagnostics import inspect_font
        path = _font_path()
    except Exception as exc:
        return _check("font:default", "warn", f"default font unavailable: {exc}",
                      "Pass an absolute .ttf/.otf path with --font for titles and captions", required=False)
    report = inspect_font(path, FONT_SAMPLE)
    if report["status"] == "pass":
        return _check("font:default", "pass", f"{report['font']} covers Latin, Cyrillic and digits", required=False)
    if report["status"] == "unavailable":
        detail = f"{report.get('font', path)} is unreadable: {report.get('error', 'unknown error')}"
    else:
        detail = f"{report.get('font', path)} lacks: {''.join(item['character'] for item in report.get('missing', []))}"
    return _check("font:default", "warn", detail,
                  "Pass an absolute .ttf/.otf font that covers the caption script with --font", required=False)


def _line(item):
    return f"{item['name']}: {item['detail']}" + (f" -> {item['hint']}" if item.get("hint") else "")


def diagnose(strict=False):
    """Return a readiness report; `ready` covers required components (and optional ones with strict)."""
    checks = [_python_check(), _venv_check(), *_module_checks(), *_ffmpeg_checks()]
    if all(item["status"] == "pass" for item in checks if item["name"] in ("package:numpy", "package:pillow")):
        checks.append(_font_check())
    required_ok = all(item["status"] == "pass" for item in checks if item["required"])
    optional_ok = all(item["status"] == "pass" for item in checks if not item["required"])
    return {
        "ready": required_ok and (optional_ok or not strict),
        "required_ready": required_ok,
        "optional_ready": optional_ok,
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "interpreter": sys.executable,
        "checks": checks,
        "problems": [_line(item) for item in checks
                     if item["status"] == "fail" or (strict and item["status"] != "pass")],
        "warnings": [_line(item) for item in checks if item["status"] == "warn"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="edit_project.py doctor", description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="Also fail on optional items: speech recognition, the caption font, the skill .venv")
    args = parser.parse_args(argv)
    report = diagnose(strict=args.strict)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

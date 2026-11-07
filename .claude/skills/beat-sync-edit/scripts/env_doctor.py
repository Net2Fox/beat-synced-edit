"""Check the editing environment: Python packages, FFmpeg encoders, fonts and options.

Uses only the standard library at import time, so it reports exactly what is
missing before the dependencies are installed. Run it with the interpreter the
skill will use, the skill's .venv: `edit_project.py doctor`. With another
Python it warns and prints the commands that create and fill that .venv.
Hints are written for PowerShell on Windows and for POSIX sh elsewhere (Git
Bash included); `fix_argv` holds the same commands as argument lists.
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
MINIMUM_TEXT = ".".join(map(str, MINIMUM_PYTHON))
SKILL = Path(__file__).resolve().parents[1]
VENV = SKILL / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _powershell(windows=None):
    """Windows hints use PowerShell syntax, unless doctor runs in a POSIX shell such as Git Bash."""
    if not (os.name == "nt" if windows is None else windows):
        return False
    return not (os.environ.get("MSYSTEM") or os.environ.get("SHELL"))


def _command(argv, windows=None):
    """Format one command for the user's shell (PowerShell, or POSIX sh including Git Bash)."""
    if not _powershell(windows):
        return shlex.join(str(part) for part in argv)
    quote = lambda part: part if re.fullmatch(r"[\w.-]+", part) else "'" + part.replace("'", "''") + "'"
    return "& " + " ".join(quote(str(part)) for part in argv)  # a quoted program needs the call operator


def _in_skill_venv():
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def _too_old(version):
    return tuple(version[:2]) < MINIMUM_PYTHON


def _venv_version():
    """(major, minor) of the Python the skill .venv was created with, from pyvenv.cfg."""
    try:
        text = (VENV / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\s*version(?:_info)?\s*=\s*(\d+)\.(\d+)", text, re.MULTILINE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _setup(requirements):
    """(hint, argv steps) that install `requirements` into the skill .venv, creating it if needed.

    Always the skill's own .venv, the interpreter SKILL.md runs every command
    with: never a system Python or another environment. Steps are None when a
    person has to act first (install a newer Python, delete an old .venv).
    """
    install = [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(SKILL / requirements)]
    if VENV_PYTHON.exists():
        old = _venv_version()
        if old and _too_old(old):
            return (f"the skill environment {VENV} uses Python {old[0]}.{old[1]}: delete it, recreate it with "
                    f"Python {MINIMUM_TEXT} or newer, then run {_command(install)}"), None
        return _command(install), [install]
    if _too_old(sys.version_info):
        example = "py -3.12" if os.name == "nt" else "python3.12"
        return (f"install Python {MINIMUM_TEXT} or newer, create the skill environment with it "
                f"({example} -m venv {VENV}), then run {_command(install)}"), None
    create = [sys.executable, "-m", "venv", str(VENV)]
    return "; ".join(_command(step) for step in (create, install)), [create, install]


def _check(name, status, detail, hint=None, required=True, fix_argv=None):
    item = {"name": name, "status": status, "required": required, "detail": detail}
    if hint:
        item["hint"] = hint
    if fix_argv:
        item["fix_argv"] = fix_argv  # the hint's commands as argument lists, free of shell quoting
    return item


def _version(module):
    return str(getattr(module, "__version__", getattr(module, "VERSION", "unknown")))


def _python_check():
    detail = f"{platform.python_implementation()} {platform.python_version()} at {sys.executable}"
    if _too_old(sys.version_info):
        if _in_skill_venv():
            hint, steps = _setup("requirements.txt")
        else:
            hint, steps = f"Use Python {MINIMUM_TEXT} or newer", None
        return _check("python", "fail", detail, hint, fix_argv=steps)
    return _check("python", "pass", detail)


def _venv_check():
    old = _venv_version() if VENV_PYTHON.exists() else None
    if _in_skill_venv() and not (old and _too_old(old)):
        return _check("venv", "pass", f"running in the skill environment {VENV}", required=False)
    if VENV_PYTHON.exists() and not (old and _too_old(old)):
        hint, steps = f"Run doctor and every skill command with {VENV_PYTHON}", None
    else:
        hint, steps = _setup("requirements.txt")
        hint = f"Set up the skill environment: {hint}"
    detail = (f"the skill environment {VENV} uses Python {old[0]}.{old[1]}" if old and _too_old(old)
              else f"running with {sys.executable}, not the skill environment {VENV}")
    return _check("venv", "warn", detail, hint, required=False, fix_argv=steps)


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
            hint, steps = _setup("requirements.txt")
            hint = f"Install the base requirements: {hint}"
            if package == "soundfile":
                hint += " (if soundfile is installed, the libsndfile system library is missing)"
            checks.append(_check(f"package:{package}", "fail", f"{type(exc).__name__}: {exc}", hint, fix_argv=steps))
    for module_name, package, purpose in OPTIONAL_MODULES:
        try:
            module = importlib.import_module(module_name)
            version = _version(module)
            status, hint = "pass", None
            major = version.split(".")[0]
            steps = None
            if module_name == "av" and major.isdigit() and int(major) >= 19:
                hint, steps = _setup("requirements-transcription.txt")
                status, hint = "warn", f"PyAV 19+ is incompatible with faster-whisper 1.2: {hint}"
            checks.append(_check(f"optional:{package}", status, f"{version} ({purpose})", hint, required=False, fix_argv=steps))
        except Exception:
            hint, steps = _setup("requirements-transcription.txt")
            checks.append(_check(f"optional:{package}", "missing", f"not installed ({purpose})",
                                 f"Only needed to transcribe speech without a transcript: {hint}",
                                 required=False, fix_argv=steps))
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

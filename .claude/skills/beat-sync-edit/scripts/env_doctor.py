"""Check the editing environment: Python packages, FFmpeg encoders, fonts and options.

Uses only the standard library at import time, so it reports exactly what is
missing before the dependencies are installed. Run it with the interpreter the
skill will use (normally the skill's .venv): `edit_project.py doctor`.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

REQUIRED_MODULES = (("numpy", "numpy"), ("scipy", "scipy"), ("cv2", "opencv-python"), ("librosa", "librosa"),
                    ("PIL", "pillow"), ("scenedetect", "scenedetect"))
OPTIONAL_MODULES = (("faster_whisper", "faster-whisper", "local speech recognition"),
                    ("av", "av", "audio decoding for faster-whisper"))
FONT_SAMPLE = "Aa Zz Яя Ёё Жж 0123456789 !?"
MINIMUM_PYTHON = (3, 10)
SKILL = Path(__file__).resolve().parents[1]


def _install(requirements):
    return f'"{sys.executable}" -m pip install -r "{SKILL / requirements}"'


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
        return _check("python", "fail", detail, f"Use Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}+ (3.12 or newer recommended)")
    return _check("python", "pass", detail)


def _module_checks():
    checks = []
    for module_name, package in REQUIRED_MODULES:
        try:
            module = importlib.import_module(module_name)
            checks.append(_check(f"package:{package}", "pass", _version(module)))
        except Exception as exc:  # ImportError and broken native wheels alike
            checks.append(_check(f"package:{package}", "fail", f"{type(exc).__name__}: {exc}",
                                 f"Install the base requirements: {_install('requirements.txt')}"))
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
        result, _ = _run([ffmpeg, "-hide_banner", "-encoders"])
        listing = result.stdout if result else ""
        names = {line.split()[1] for line in listing.splitlines() if len(line.split()) > 1 and line.startswith(" ")}
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
    missing = "".join(item["character"] for item in report.get("missing", []))
    return _check("font:default", "warn", f"{report.get('font', path)} lacks: {missing or report.get('error', 'unknown')}",
                  "Pass an absolute .ttf/.otf font that covers the caption script with --font", required=False)


def diagnose(strict=False):
    """Return a readiness report; `ready` covers required components (and optional ones with strict)."""
    checks = [_python_check(), *_module_checks(), *_ffmpeg_checks()]
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
        "problems": [f"{item['name']}: {item['detail']}" + (f" -> {item['hint']}" if item.get("hint") else "")
                     for item in checks if item["status"] == "fail" or (strict and item["status"] != "pass")],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="edit_project.py doctor", description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Also fail when optional components are missing")
    args = parser.parse_args(argv)
    report = diagnose(strict=args.strict)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

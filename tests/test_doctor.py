"""`edit_project.py doctor` reports readiness, even before dependencies are installed."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401  (makes the skill's scripts importable)
import env_doctor

CLI = Path(_paths.SCRIPTS) / "edit_project.py"


def doctor(*flags, args=(), env=None):
    return subprocess.run([sys.executable, *flags, "-X", "utf8", str(CLI), "doctor", *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


class DoctorCommandTests(unittest.TestCase):
    def test_reports_every_required_component(self):
        result = doctor()
        report = json.loads(result.stdout)
        names = {item["name"] for item in report["checks"]}
        self.assertTrue({"python", "venv", "package:numpy", "package:scipy", "package:librosa", "package:soundfile",
                         "ffmpeg", "ffprobe"} <= names)
        self.assertEqual(result.returncode, 0 if report["ready"] else 4)
        self.assertEqual(report["warnings"], [f"{c['name']}: {c['detail']}" + (f" -> {c['hint']}" if c.get("hint") else "")
                                              for c in report["checks"] if c["status"] == "warn"])
        if shutil.which("ffmpeg"):
            self.assertTrue({"encoder:libx264", "encoder:aac"} <= names)

    def test_strict_also_fails_on_optional_items(self):
        report = json.loads(doctor().stdout)
        strict = doctor(args=["--strict"])
        expected = 0 if report["required_ready"] and report["optional_ready"] else 4
        self.assertEqual(strict.returncode, expected, strict.stderr)

    def test_works_without_third_party_packages_and_says_how_to_install(self):
        result = doctor("-S")  # no site-packages: numpy, OpenCV and friends are missing
        self.assertEqual(result.returncode, 4, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        problem = next(p for p in report["problems"] if p.startswith("package:numpy"))
        self.assertIn(str(Path(_paths.SCRIPTS).parent / "requirements.txt"), problem)

    def test_a_broken_lazily_loaded_dependency_is_not_ready(self):
        # librosa imports numba only when its beat tracker loads; a top-level
        # `import librosa` would pass with a numba that cannot load.
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / "numba"
            fake.mkdir()
            (fake / "__init__.py").write_text("raise ImportError('Numba needs a different NumPy')\n", encoding="utf-8")
            env = {**os.environ, "PYTHONPATH": temp}
            result = doctor(env=env)
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 4, result.stdout)
        check = next(c for c in report["checks"] if c["name"] == "package:librosa")
        self.assertEqual(check["status"], "fail")
        self.assertIn("Numba needs", check["detail"])


class DoctorUnitTests(unittest.TestCase):
    def test_missing_ffmpeg_fails_both_tools_and_skips_encoders(self):
        with patch.object(env_doctor.shutil, "which", return_value=None):
            checks = env_doctor._ffmpeg_checks()
        self.assertEqual([(c["name"], c["status"]) for c in checks], [("ffmpeg", "fail"), ("ffprobe", "fail")])

    def test_encoder_listing_ignores_the_legend(self):
        listing = ("Encoders:\n V..... = Video\n A..... = Audio\n ------\n"
                   " V....D libx264              libx264 H.264 / AVC\n A....D aac                  AAC (Advanced Audio Coding)\n")
        self.assertEqual(env_doctor._encoder_names(listing), {"libx264", "aac"})

    def test_a_failing_encoder_listing_is_reported_as_such(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="ffmpeg: error while loading shared libraries")
        with patch.object(env_doctor.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                patch.object(env_doctor, "_run", return_value=(failed, None)):
            checks = env_doctor._ffmpeg_checks()
        self.assertEqual(checks[-1]["name"], "encoders")
        self.assertIn("shared libraries", checks[-1]["detail"])

    def test_pyav_19_is_a_warning_with_a_fix(self):
        real = env_doctor.importlib.import_module

        def fake(name):
            if name == "av":
                return type("av", (), {"__version__": "19.0.0"})
            return real(name)
        with patch.object(env_doctor.importlib, "import_module", side_effect=fake):
            checks = env_doctor._module_checks()
        av = next(c for c in checks if c["name"] == "optional:av")
        self.assertEqual(av["status"], "warn")
        self.assertIn("requirements-transcription.txt", av["hint"])

    def test_a_broken_submodule_fails_its_package(self):
        real = env_doctor.importlib.import_module

        def fake(name):
            if name == "PIL.Image":
                raise ImportError("_imaging: undefined symbol")
            return real(name)
        with patch.object(env_doctor.importlib, "import_module", side_effect=fake):
            checks = env_doctor._module_checks()
        pillow = next(c for c in checks if c["name"] == "package:pillow")
        self.assertEqual(pillow["status"], "fail")
        self.assertIn("requirements.txt", pillow["hint"])

    def test_install_hints_target_the_skill_venv_outside_a_virtual_environment(self):
        with patch.object(env_doctor.sys, "prefix", env_doctor.sys.base_prefix):
            hint = env_doctor._install("requirements.txt")
        self.assertIn(str(env_doctor.VENV_PYTHON), hint)
        if not env_doctor.VENV_PYTHON.exists():
            self.assertIn("-m venv", hint)

    def test_commands_are_quoted_for_the_shell(self):
        argv = ["/opt/My Python/python", "-m", "pip", "install", "-r", "/skills/it's/requirements.txt"]
        self.assertEqual(env_doctor.shlex.split(env_doctor._command(argv, windows=False)), argv)
        windows = env_doctor._command([r"C:\Users\Ann Lee\.venv\Scripts\python.exe", "-m", "pip", "install", "-r",
                                       r"C:\skills\it's\requirements.txt"], windows=True)
        self.assertEqual(windows, r"& 'C:\Users\Ann Lee\.venv\Scripts\python.exe' -m pip install -r 'C:\skills\it''s\requirements.txt'")

    def test_an_unreadable_font_is_not_called_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "bad.ttf"
            bad.write_bytes(b"not a font")
            with patch("text_overlay._font_path", return_value=str(bad)):
                check = env_doctor._font_check()
        self.assertEqual(check["status"], "warn")
        self.assertIn("unreadable", check["detail"])


if __name__ == "__main__":
    unittest.main()

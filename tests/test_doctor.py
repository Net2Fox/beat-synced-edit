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

    def skill(self, version=None):
        """Point the doctor at a temporary skill folder, optionally with a .venv of that Python version."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / "beat-sync-edit"
        venv = root / ".venv"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if version:
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            (venv / "pyvenv.cfg").write_text(f"home = /usr/bin\nversion = {version}\n", encoding="utf-8")
        for name, value in (("SKILL", root), ("VENV", venv), ("VENV_PYTHON", python)):
            patcher = patch.object(env_doctor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return root, python

    def test_hints_create_and_fill_the_skill_venv(self):
        root, python = self.skill()
        hint, steps = env_doctor._setup("requirements.txt")
        self.assertEqual(steps, [[sys.executable, "-m", "venv", str(root / ".venv")],
                                 [str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")]])
        self.assertEqual(hint, "; ".join(env_doctor._command(step) for step in steps))
        check = env_doctor._venv_check()
        self.assertEqual((check["status"], check["fix_argv"]), ("warn", steps))

    def test_an_existing_skill_venv_is_used_even_from_another_environment(self):
        root, python = self.skill("3.13.1")
        hint, steps = env_doctor._setup("requirements.txt")
        self.assertEqual(steps, [[str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")]])
        self.assertIn(str(python), env_doctor._venv_check()["hint"])

    def test_a_too_old_python_is_never_used_for_the_skill_venv(self):
        root, _ = self.skill()
        with patch.object(env_doctor.sys, "version_info", (3, 11, 9)):
            hint, steps = env_doctor._setup("requirements.txt")
            self.assertEqual(env_doctor._python_check()["status"], "fail")
        self.assertIsNone(steps)
        self.assertIn("Python 3.12 or newer", hint)
        self.assertNotIn(f"{sys.executable} -m venv", hint)
        newer = ["py", "-3.12"] if os.name == "nt" else ["python3.12"]
        self.assertIn(env_doctor._command([*newer, "-m", "venv", str(root / ".venv")]), hint)  # quoted path

    def test_a_skill_venv_made_with_an_old_python_is_recreated_in_place(self):
        root, python = self.skill("3.11.9")
        hint, steps = env_doctor._setup("requirements.txt")
        self.assertEqual(steps[0], [sys.executable, "-m", "venv", "--clear", str(root / ".venv")])
        self.assertIn("uses Python 3.11; recreate it", hint)
        check = env_doctor._venv_check()
        self.assertEqual((check["status"], check["fix_argv"]), ("warn", steps))

    def test_commands_are_quoted_for_the_shell(self):
        argv = ["/opt/My Python/python", "-m", "pip", "install", "-r", "/skills/it's/requirements.txt"]
        self.assertEqual(env_doctor.shlex.split(env_doctor._command(argv, windows=False)), argv)
        windows = [r"C:\Users\Ann Lee\.venv\Scripts\python.exe", "-m", "pip", "install", "-r", r"C:\skills\it's\requirements.txt"]
        powershell = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "SHELL")}
        with patch.dict(os.environ, powershell, clear=True):
            self.assertEqual(env_doctor._command(windows, windows=True),
                             r"& 'C:\Users\Ann Lee\.venv\Scripts\python.exe' -m pip install -r 'C:\skills\it''s\requirements.txt'")
        with patch.dict(os.environ, {**powershell, "MSYSTEM": "MINGW64"}, clear=True):  # Git Bash
            self.assertEqual(env_doctor.shlex.split(env_doctor._command(windows, windows=True)), windows)

    def test_a_missing_libsndfile_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "soundfile.py").write_text("raise OSError('sndfile library not found')\n", encoding="utf-8")
            result = doctor(env={**os.environ, "PYTHONPATH": temp})
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 4)
        check = next(c for c in report["checks"] if c["name"] == "package:soundfile")
        self.assertEqual(check["status"], "fail")
        self.assertIn("libsndfile", check["hint"])

    def test_a_font_without_cyrillic_lists_what_it_lacks(self):
        report = {"font": "/fonts/latin.ttf", "status": "fail", "missing": [{"character": "Я"}, {"character": "Ж"}]}
        with patch("font_diagnostics.inspect_font", return_value=report):
            check = env_doctor._font_check()
        self.assertEqual((check["status"], check["detail"]), ("warn", "/fonts/latin.ttf lacks: ЯЖ"))

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

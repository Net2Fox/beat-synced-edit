"""`edit_project.py doctor` reports readiness, even before dependencies are installed."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import _paths  # noqa: F401  (makes the skill's scripts importable)

CLI = Path(_paths.SCRIPTS) / "edit_project.py"


def doctor(*flags):
    return subprocess.run([sys.executable, *flags, "-X", "utf8", str(CLI), "doctor"],
                          capture_output=True, text=True, encoding="utf-8")


class DoctorTests(unittest.TestCase):
    def test_reports_every_required_component(self):
        result = doctor()
        report = json.loads(result.stdout)
        names = {item["name"] for item in report["checks"]}
        self.assertTrue({"python", "package:numpy", "package:scipy", "package:librosa", "ffmpeg", "ffprobe"} <= names)
        self.assertEqual(result.returncode, 0 if report["ready"] else 4)
        if shutil.which("ffmpeg"):
            self.assertTrue({"encoder:libx264", "encoder:aac"} <= names)

    def test_works_without_third_party_packages_and_says_how_to_install(self):
        result = doctor("-S")  # no site-packages: numpy, OpenCV and friends are missing
        self.assertEqual(result.returncode, 4, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        problem = next(p for p in report["problems"] if p.startswith("package:numpy"))
        self.assertIn(str(Path(_paths.SCRIPTS).parent / "requirements.txt"), problem)


if __name__ == "__main__":
    unittest.main()

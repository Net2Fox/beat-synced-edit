"""Both agents receive the complete runtime and identical maintained instructions."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class SkillBundleTests(unittest.TestCase):
    def test_new_dependencies_resources_and_instruction_drift_are_checked(self):
        source = Path(__file__).resolve().parents[1]/"tools"/"build_codex_skill.py"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"tools").mkdir()
            script = root/"tools"/"build_codex_skill.py"
            shutil.copyfile(source, script)
            (root/"entry.py").write_text("import dependency\n")
            (root/"dependency.py").write_text("VALUE = 42\n")
            for name in ("LICENSE", "requirements.txt", "requirements.lock.txt", "requirements-transcription.txt", "UPSTREAM.json"):
                (root/name).write_text("fixture\n")
            for name in ("edit", "edit.cmd"):
                (root/name).write_text("launcher\n")
            (root/"edit").chmod(0o755)
            canonical = root/"skills"/"beat-sync-edit"
            for directory in (canonical/"references", canonical/"assets"):
                directory.mkdir(parents=True)
            (canonical/"SKILL.md").write_text("canonical instructions\n")
            (canonical/"references"/"workflow.md").write_text("reference\n")
            (canonical/"assets"/"style.json").write_text("{}\n")

            def build(*flags):
                return subprocess.run([sys.executable, str(script), *flags], capture_output=True, text=True)

            self.assertEqual(build().returncode, 0)
            self.assertEqual(build("--check").returncode, 0)
            mirror = root/".claude"/"skills"/"beat-sync-edit"
            for name in ("scripts/entry.py", "scripts/dependency.py", "scripts/edit", "scripts/edit.cmd",
                         "references/workflow.md", "assets/style.json", "SKILL.md", "LICENSE"):
                self.assertEqual((canonical/name).read_bytes(), (mirror/name).read_bytes())
            if os.name != "nt":
                self.assertTrue(os.access(mirror/"scripts"/"edit", os.X_OK))
            (mirror/"SKILL.md").write_text("outdated old workflow\n")
            self.assertNotEqual(build("--check").returncode, 0)
            self.assertEqual(build().returncode, 0)
            (root/"new_runtime.py").write_text("NEW = True\n")
            self.assertNotEqual(build("--check").returncode, 0)
            self.assertEqual(build().returncode, 0)
            (mirror/"scripts"/"stale.py").write_text("stale\n")
            self.assertNotEqual(build("--check").returncode, 0)
            self.assertEqual(build().returncode, 0)
            self.assertFalse((mirror/"scripts"/"stale.py").exists())
            self.assertEqual(build("--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()

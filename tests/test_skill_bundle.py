"""The Claude Code copy of the skill stays identical to the canonical package."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sync_skill.py"


def sync(root, *flags):
    return subprocess.run([sys.executable, str(root / "tools" / "sync_skill.py"), *flags], capture_output=True, text=True)


class SkillBundleTests(unittest.TestCase):
    def test_repository_claude_copy_matches_the_canonical_skill(self):
        result = sync(ROOT, "--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sync_detects_drift_new_and_stale_files_and_keeps_environments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tools").mkdir()
            shutil.copyfile(TOOL, root / "tools" / "sync_skill.py")
            (root / "LICENSE").write_text("license\n")
            skill = root / "skills" / "beat-sync-edit"
            for directory in ("scripts", "references", "assets"):
                (skill / directory).mkdir(parents=True)
            (skill / "SKILL.md").write_text("instructions\n")
            (skill / "scripts" / "edit_project.py").write_text("import dependency\n")
            (skill / "scripts" / "dependency.py").write_text("VALUE = 42\n")
            (skill / "references" / "workflow.md").write_text("reference\n")
            (skill / "assets" / "style.json").write_text("{}\n")
            for name in ("requirements.txt", "requirements.lock.txt", "requirements-transcription.txt"):
                (skill / name).write_text("fixture\n")

            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(sync(root, "--check").returncode, 0)
            mirror = root / ".claude" / "skills" / "beat-sync-edit"
            for name in ("scripts/edit_project.py", "scripts/dependency.py", "references/workflow.md",
                         "assets/style.json", "SKILL.md", "requirements.txt"):
                self.assertEqual((skill / name).read_bytes(), (mirror / name).read_bytes())
            self.assertEqual((mirror / "LICENSE").read_text(), "license\n")
            self.assertEqual((skill / "LICENSE").read_text(), "license\n")

            (mirror / "SKILL.md").write_text("outdated old workflow\n")
            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            (skill / "scripts" / "new_runtime.py").write_text("NEW = True\n")
            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)

            (mirror / "scripts" / "stale.py").write_text("stale\n")
            (mirror / "UPSTREAM.json").write_text("{}\n")
            (mirror / ".venv").mkdir()
            (mirror / ".venv" / "keep.txt").write_text("environment\n")
            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertFalse((mirror / "scripts" / "stale.py").exists())
            self.assertFalse((mirror / "UPSTREAM.json").exists())
            self.assertTrue((mirror / ".venv" / "keep.txt").exists())
            self.assertEqual(sync(root, "--check").returncode, 0)

            # New top-level files are copied; editor and OS junk is ignored.
            (skill / "NOTICE.md").write_text("notice\n")
            (skill / "scripts" / "edit_project.py~").write_text("backup\n")
            (skill / "references" / ".DS_Store").write_text("junk\n")
            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual((mirror / "NOTICE.md").read_text(), "notice\n")
            self.assertFalse((mirror / "scripts" / "edit_project.py~").exists())
            self.assertFalse((mirror / "references" / ".DS_Store").exists())
            self.assertEqual(sync(root, "--check").returncode, 0)

            # A symlinked target is replaced, never written through.
            outside = root / "outside.txt"
            outside.write_text("untouched\n")
            (mirror / "SKILL.md").unlink()
            (mirror / "SKILL.md").symlink_to(outside)
            self.assertNotEqual(sync(root, "--check").returncode, 0)
            self.assertEqual(sync(root).returncode, 0)
            self.assertEqual(outside.read_text(), "untouched\n")
            self.assertFalse((mirror / "SKILL.md").is_symlink())
            self.assertEqual(sync(root, "--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()

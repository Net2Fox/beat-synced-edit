"""Regression checks for automatically named reports and damaged tracking cache."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from graphics_commands import motion_project
from project_workspace import write_json
from project_render import render_project
from render_qa import guard_export_outputs, verify_export
from workflow_commands import render_with_qa


def composition():
    return {"duration": .5, "fps": 24, "width": 64, "height": 64, "background": "#205080"}


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class ExportSafeguardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root/"project.json"
        self.plan = motion_project(composition(), self.project)

    def test_derived_report_and_review_images_cannot_overwrite_resources(self):
        for name in ("out.verification.json", "out.qa.json", "out.audio.json", "out.review-01.png"):
            with self.subTest(name=name):
                resource = self.root/name
                resource.write_bytes(b"original supplied resource")
                self.plan["assets"].append({"path": str(resource)})
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    render_with_qa(self.plan, self.root/"out.mp4")
                self.assertEqual(resource.read_bytes(), b"original supplied resource")
                self.assertFalse((self.root/"out.mp4").exists())
                self.plan["assets"].pop()

    def test_renderer_path_preserves_project_if_it_matches_audio_sidecar(self):
        project = self.root/"out.audio.json"
        write_json(project, self.plan)
        before = project.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            render_project(project, self.root/"out.mp4")
        self.assertEqual(project.read_bytes(), before)

    def test_revise_file_cannot_replace_its_source_picture(self):
        from project_workspace import revise_file
        picture = Path(self.plan["edits"][0]["source"])
        before = picture.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            revise_file(self.project, [{"op": "effects", "all": True, "values": {"flash": 0}}], picture)
        self.assertEqual(picture.read_bytes(), before)

    def test_qa_preserves_supplied_project_file(self):
        video = self.root/"source.mp4"
        render_project(self.plan, video)
        protected = self.root/"source.qa.json"
        protected.write_bytes(b"existing project")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            verify_export(video, self.plan, protected_paths=[protected])
        self.assertEqual(protected.read_bytes(), b"existing project")

    def test_corrupt_tracking_cache_rebuilds_and_preserves_diagnostics(self):
        cache = self.root/"cache"
        first = render_project(self.plan, self.root/"a.mp4", cache_dir=cache)
        tracking = next(cache.glob("*.tracking.json"))
        original = json.loads(tracking.read_text())
        original["identity_verified"] = True
        tracking.write_text(json.dumps(original))
        second = render_project(self.plan, self.root/"b.mp4", cache_dir=cache)
        self.assertEqual(second["cache_hits"], 0)
        self.assertFalse(second["tracking"][0]["identity_verified"])
        third = render_project(self.plan, self.root/"c.mp4", cache_dir=cache)
        self.assertEqual(third["cache_hits"], 1)


if __name__ == "__main__":
    unittest.main()

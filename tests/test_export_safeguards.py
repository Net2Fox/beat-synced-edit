"""Regression checks for automatically named reports and damaged tracking cache."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import _paths  # noqa: F401  (makes the skill's scripts importable)
from graphics_commands import motion_project
from project_workspace import write_json
from project_render import render_project
from render_qa import verify_export
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

    def test_render_cli_keeps_reports_out_of_the_delivery_folder(self):
        from edit_project import parser, run
        outputs = self.root/"outputs"
        result = run(parser().parse_args(["render", str(self.project), "-o", str(outputs/"final.mp4")]))
        self.assertEqual(sorted(p.name for p in outputs.iterdir()), ["final.mp4"])
        reports = self.root/"reports"
        self.assertEqual(Path(result["verification"]), reports/"final.verification.json")
        self.assertEqual(Path(result["qa"]["report"]), reports/"final.qa.json")
        for name in ("final.verification.json", "final.qa.json", "final.audio.json", "final.review-01.png"):
            self.assertTrue((reports/name).is_file(), name)
        from cli_guard import tool_signature
        from render_qa import file_hash
        self.assertEqual(result["provenance"]["tool"], tool_signature())
        self.assertEqual(result["provenance"]["output_sha256"], file_hash(outputs/"final.mp4"))

    def test_same_file_name_in_another_folder_cannot_replace_existing_reports(self):
        from edit_project import parser, run
        run(parser().parse_args(["render", str(self.project), "-o", str(self.root/"vertical"/"final.mp4")]))
        with self.assertRaisesRegex(ValueError, "different file name"):
            run(parser().parse_args(["render", str(self.project), "-o", str(self.root/"square"/"final.mp4")]))
        self.assertFalse((self.root/"square"/"final.mp4").exists())
        (self.root/"vertical"/"final.mp4").unlink()  # reports of a deleted video may be replaced
        run(parser().parse_args(["render", str(self.project), "-o", str(self.root/"square"/"final.mp4")]))

    def test_batch_refuses_two_jobs_with_the_same_output_name(self):
        from edit_project import parser, run
        jobs = self.root/"jobs.json"
        write_json(jobs, {"jobs": [{"project": "project.json", "output": "a/final.mp4"},
                                   {"project": "project.json", "output": "b/final.mp4"}]})
        with self.assertRaisesRegex(ValueError, "distinct file name"):
            run(parser().parse_args(["batch-render", str(jobs), "--work", str(self.root/"batch")]))
        self.assertFalse((self.root/"a").exists() or (self.root/"b").exists())

    def test_failed_export_qa_exits_4_with_empty_stdout(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from unittest import mock
        import render_qa
        from edit_project import main
        real = render_qa.verify_export
        def failing(*args, **kwargs):
            report = real(*args, **kwargs)
            report["technical_pass"] = False
            return report
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(render_qa, "verify_export", failing), redirect_stdout(out), redirect_stderr(err):
            code = main(["render", str(self.project), "-o", str(self.root/"outputs"/"final.mp4")])
        self.assertEqual(code, 4)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Error: Export failed technical QA", err.getvalue())

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

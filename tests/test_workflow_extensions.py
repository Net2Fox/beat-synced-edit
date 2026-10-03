"""Exercise graphics, input-bound execution, review integrity and actual export QA."""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_workspace import read_json, write_json
from graphics_commands import motion_project
from graphics_layers import ProjectCompositor, validate_graphics
from cli_contract import prepare_plan, execute_saved
from edit_project import main, parser, run
from tracking_review import resolve_track, tracking_report
from font_diagnostics import inspect_font
from text_overlay import _font_path


def spec():
    return {"duration": 1, "fps": 24, "width": 120, "height": 160, "background": "#205080",
            "graphics": [{"id": "bar", "kind": "bar", "start_frame": 0, "end_frame": 24,
                          "rect": [.1, .7, .8, .1], "animation": "none", "background": "#000000", "accent": "#FFFFFF"}]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_dry_run_has_no_generated_media_then_executes_one_parsed_command(self):
        source = self.root / "spec.json"
        write_json(source, spec())
        output = self.root / "project.json"
        manifest = self.root / "execution.json"
        argv = ["motion-project", str(source), "-o", str(output), "--dry-run", "--plan", str(manifest)]
        result = prepare_plan(parser().parse_args(argv), argv)
        self.assertEqual(result["execution_status"], "not_executed")
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "motion-assets").exists())
        execute_saved(manifest, parser(), run)
        self.assertEqual(read_json(output)["duration_frames"], 24)

    def test_execution_plan_rejects_changed_nested_source_content(self):
        plan = motion_project(spec(), self.root / "project.json")
        manifest = self.root / "execution.json"
        argv = ["render", str(self.root / "project.json"), "-o", str(self.root / "out.mp4"), "--dry-run", "--plan", str(manifest)]
        prepare_plan(parser().parse_args(argv), argv)
        image = Path(plan["edits"][0]["source"])
        old = image.read_bytes()
        image.write_bytes(old[:-1] + bytes([old[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, "input changed"):
            execute_saved(manifest, parser(), lambda args: self.fail("Changed input must never execute"))

    def test_machine_parse_error_is_valid_json(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(["plan", "--json-brief"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_argument")

    def test_graphic_progress_changes_measured_pixels_and_preserves_input(self):
        plan = motion_project(spec(), self.root / "project.json")
        frame = np.zeros((160, 120, 3), np.uint8)
        compositor = ProjectCompositor(plan, 120, 160)
        before, after = compositor.apply(frame, 0), compositor.apply(frame, 23)
        self.assertGreater(after[115:122, 20:100].mean(), before[115:122, 20:100].mean() + 150)
        self.assertEqual(frame.sum(), 0)
        compositor.close()
        invalid = copy.deepcopy(plan)
        invalid["graphics"][0]["end_frame"] = 25
        with self.assertRaises(ValueError):
            validate_graphics(invalid)

    def test_manual_tracking_is_honest_about_identity_verification(self):
        shot = {"id": "s", "source": "unused", "kind": "video", "source_start": 0, "source_end": 3,
                "reframe": {"mode": "auto", "keyframes": [{"time": 0, "cx": .2, "cy": .5}, {"time": 3, "cx": .8, "cy": .5}]}}
        track = resolve_track(shot)
        self.assertEqual([point["cx"] for point in track], [.2, .8])
        report = tracking_report(shot, track)
        self.assertFalse(report["identity_verified"])
        self.assertEqual(report["visual_review"], "not_reviewed")

    def test_font_checks_actual_unicode_coverage(self):
        font = _font_path(None)
        self.assertEqual(inspect_font(font, "Hello Привет 123")["status"], "pass")
        self.assertEqual(inspect_font(font, chr(0x10ffff))["status"], "fail")

    def test_public_review_manifest_binds_export_and_graphic_inputs(self):
        from editorial_commands import evaluate_manifest
        plan = motion_project(spec(), self.root / "project.json")
        image = self.root / "overlay.png"
        image.write_bytes(Path(plan["edits"][0]["source"]).read_bytes())
        plan["graphics"] = [{"id": "overlay", "kind": "image", "source": str(image), "start_frame": 0, "end_frame": 24}]
        write_json(self.root / "project.json", plan)
        exported = self.root / "export.mp4"
        exported.write_bytes(b"hash fixture only; no claim of decodable video")
        destination = self.root / "manifest.json"
        args = parser().parse_args(["review-manifest", str(self.root / "project.json"), "--kind", "synthetic",
                                    "--render", str(exported), "-o", str(destination)])
        result = run(args)
        self.assertEqual(evaluate_manifest(result)["cases"][0]["status"], "not_reviewed")
        image.write_bytes(image.read_bytes() + b"changed")
        self.assertEqual(evaluate_manifest(result)["cases"][0]["status"], "stale")

    def test_remotion_exports_editable_source_and_protects_edits(self):
        from remotion_adapter import export_composition
        folder = self.root / "react"
        result = export_composition(spec(), folder)
        self.assertFalse(result["rendered"])
        source = Path(result["source"])
        self.assertIn("useCurrentFrame", source.read_text(encoding="utf-8"))
        source.write_text("// My edited composition", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Preserve edited"):
            export_composition(spec(), folder)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools required")
class ActualExportTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    def test_render_resolves_anchored_title_without_mutating_saved_plan(self):
        import cv2
        from project_render import render_project
        plan = motion_project(spec(), self.root / "project.json")
        plan["graphics"] = []
        plan["titles"] = [{"id": "anchored", "text": "HELLO", "start_frame": 0, "end_frame": 6,
                           "anchor": {"type": "shot", "id": "shot-001", "offset_frames": 12},
                           "anchor_duration_frames": 6, "style": {"font_size": 16, "animation": "none"}}]
        output = self.root / "anchored.mp4"
        render_project(plan, output)
        cap = cv2.VideoCapture(str(output))
        images = []
        for frame in (0, 14):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, picture = cap.read()
            self.assertTrue(ok)
            images.append(picture)
        cap.release()
        self.assertEqual(plan["titles"][0]["start_frame"], 0)
        self.assertGreater(np.count_nonzero(images[1].min(axis=2) > 200), np.count_nonzero(images[0].min(axis=2) > 200) + 10)

    def test_decode_black_silence_review_and_hash_guard(self):
        from render_qa import verify_export
        from workflow_commands import record_review
        video = self.root / "black.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=120x160:r=24:d=1",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True, capture_output=True)
        report = verify_export(video, make_sheet=True)
        self.assertTrue(report["technical_pass"])
        self.assertTrue(report["black_intervals"])
        self.assertTrue(report["silent_intervals"])
        self.assertTrue(report["review_notes"])
        self.assertEqual(report["visual_review"], "not_reviewed")
        with self.assertRaisesRegex(ValueError, "evidence"):
            record_review(report, {"reviewer": "test", "visual": {"status": "pass"}})
        video.write_bytes(video.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            record_review(report, {"reviewer": "test"})

    def test_local_motion_exports_exact_frames_and_reuses_shot_cache(self):
        from workflow_commands import render_with_qa
        plan = motion_project(spec(), self.root / "project.json")
        plan["qa"] = {"intentional_silence": [[0, 1]]}
        first = render_with_qa(plan, self.root / "first.mp4", cache_dir=self.root / "cache")
        second = render_with_qa(plan, self.root / "second.mp4", cache_dir=self.root / "cache")
        self.assertEqual(first["frames"], 24)
        self.assertTrue(first["qa"]["technical_pass"])
        self.assertEqual(second["cache_hits"], 1)
        self.assertEqual(second["qa"]["review_notes"], [])


if __name__ == "__main__":
    unittest.main()

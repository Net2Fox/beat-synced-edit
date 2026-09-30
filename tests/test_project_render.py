"""Renderer integration tests use actual FFmpeg and generated, rights-free media."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_render import _display_size, _effect_frame, _read_image, probe, render_project, source_times


class RetimingTests(unittest.TestCase):
    def test_ramp_is_monotone_smooth_and_action_hits_exact_time(self):
        edit = {"source_start": 2, "source_end": 7,
                "speed_points": [{"at": 0, "speed": 2}, {"at": .5, "speed": .3}, {"at": 1, "speed": 2}],
                "action_anchor": {"source_time": 4, "output_fraction": .6}}
        values = source_times(edit, np.linspace(0, 1, 10001))
        self.assertEqual(values[0], 2)
        self.assertEqual(values[-1], 7)
        self.assertTrue(np.all(np.diff(values) > 0))
        self.assertAlmostEqual(float(source_times(edit, [.6])[0]), 4, places=9)
        epsilon = 1e-5
        before, center, after = source_times(edit, [.6-epsilon, .6, .6+epsilon])
        self.assertAlmostEqual((center-before)/epsilon, (after-center)/epsilon, places=3)
        # Acceleration changes continuously at speed controls, without hard jumps.
        before, center, after = source_times(edit, [.5-epsilon, .5, .5+epsilon])
        self.assertAlmostEqual((center-before)/epsilon, (after-center)/epsilon, places=3)

    def test_invalid_curve_and_anchor_fail(self):
        edit = {"source_start": 0, "source_end": 2, "speed_points": [{"at": 0, "speed": -1}]}
        with self.assertRaisesRegex(ValueError, "positive"):
            source_times(edit, [0, .5])
        edit["speed_points"] = []
        edit["action_anchor"] = {"source_time": 3, "output_fraction": .5}
        with self.assertRaisesRegex(ValueError, "anchor"):
            source_times(edit, [0, .5])

    def test_rotation_and_pixel_aspect_display_size(self):
        self.assertEqual(_display_size({"width": 320, "height": 180, "sample_aspect_ratio": "2:1", "side_data_list": [{"rotation": 90}]}), (180, 640))

    def test_flash_fades_and_grades_change_pixels(self):
        frame = np.full((20, 20, 3), 100, np.uint8)
        first = _effect_frame(frame, {"flash": 1}, 0, 30, 30)
        last = _effect_frame(frame, {"flash": 1}, 10, 30, 30)
        self.assertEqual(first.min(), 255)
        self.assertTrue(np.array_equal(last, frame))
        for grade in ("warm", "cool", "vivid", "cinematic"):
            self.assertFalse(np.array_equal(_effect_frame(frame, {"grade": grade}, 0, 30, 30), frame), grade)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class RenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="beat-render-")
        cls.work = Path(cls.temporary.name)/"тест видео"
        cls.work.mkdir()
        cls.a, cls.b, cls.photo, cls.music = (cls.work/name for name in ("wide.mp4", "tall.mp4", "left.png", "song.wav"))
        for path, size, fps in ((cls.a, "320x180", 24), (cls.b, "180x320", 60)):
            cls.ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
        cls.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=3", str(cls.music)])
        picture = np.full((100, 400, 3), [0, 0, 255], np.uint8)
        picture[:, :100] = [255, 0, 0]
        Image.fromarray(picture).save(cls.photo)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def ffmpeg(args):
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True, capture_output=True)

    def make_plan(self):
        edits = []
        cursor = 0
        for i, (path, kind, frames, span) in enumerate(((self.a, "video", 13, 1.2), (self.b, "video", 17, 1.1), (self.photo, "image", 15, 0))):
            edits.append({"id": f"e{i}", "source": str(path), "asset_id": f"a{i}", "kind": kind,
                          "source_start": 0.0, "source_end": span, "duration_frames": frames,
                          "timeline_start_frame": cursor, "timeline_end_frame": cursor+frames,
                          "effects": {"flash": .3 if i == 1 else 0.0, "zoom": 1.1, "shake": .1, "grade": "cool"},
                          "reframe": {"mode": "center"},
                          "speed_points": [{"at": 0, "speed": 1.8}, {"at": .5, "speed": .5}, {"at": 1, "speed": 1.8}]})
            cursor += frames
        return {"schema_version": 2, "audio": {"path": str(self.music), "start": .2},
                "output": {"width": 160, "height": 284, "fps": 30}, "duration_frames": cursor, "edits": edits}

    def test_mixed_media_exact_frames_audio_and_revision_cache(self):
        plan = self.make_plan()
        cache = self.work/"cache-mixed"
        result = render_project(plan, self.work/"mixed.mp4", cache_dir=cache)
        self.assertEqual((result["frames"], result["width"], result["height"]), (45, 160, 284))
        self.assertAlmostEqual(result["duration"], 1.5)
        self.assertEqual(result["audio_sample_rate"], 48000)
        self.assertEqual(result["cache_hits"], 0)
        # Remove-all-flashes revisions spell zero as an integer. Previously
        # unchanged shots with a floating-point zero incorrectly missed cache.
        for edit in plan["edits"]:
            edit["effects"]["flash"] = 0
            edit["source_start"] = 0  # Equivalent timeline numbers also reuse cache.
        revised = render_project(plan, self.work/"revised.mp4", cache_dir=cache)
        self.assertEqual(revised["cache_hits"], 2)
        self.assertEqual(revised["frames"], 45)

    def test_preview_manual_subject_crop_and_contain(self):
        plan = self.make_plan()
        edit = copy.deepcopy(plan["edits"][-1])
        edit.update(timeline_start_frame=0, timeline_end_frame=15, effects={},
                    reframe={"mode": "manual", "subject": [0, 0, .25, 1]})
        plan.update(edits=[edit], duration_frames=15, output={"width": 1080, "height": 1920, "fps": 30})
        result = render_project(plan, self.work/"manual.mp4", preview=True)
        self.assertEqual((result["width"], result["height"]), (360, 640))
        cap = cv2.VideoCapture(str(self.work/"manual.mp4"))
        ok, frame = cap.read()
        cap.release()
        self.assertTrue(ok)
        self.assertGreater(float(frame[..., 2].mean()), 230)  # Red target at left stays in crop.
        self.assertLess(float(frame[..., 0].mean()), 20)
        edit["reframe"] = {"mode": "contain"}
        render_project(plan, self.work/"contain.mp4", preview=True)
        cap = cv2.VideoCapture(str(self.work/"contain.mp4"))
        ok, frame = cap.read()
        cap.release()
        self.assertTrue(ok)
        self.assertLess(float(frame[:100].mean()), 3)  # Landscape photo letterboxed.
        plan["output"] = {"width": 1920, "height": 1080, "fps": 30}
        horizontal = render_project(plan, self.work/"horizontal-preview.mp4", preview=True)
        self.assertLessEqual(horizontal["width"], 360)
        self.assertEqual(horizontal["width"]*9, horizontal["height"]*16)

    def test_full_hd_rotated_source_two_seconds(self):
        rotated = self.work/"rotated.mp4"
        try:
            self.ffmpeg(["-display_rotation", "90", "-i", str(self.a), "-c", "copy", str(rotated)])
        except subprocess.CalledProcessError:  # Older FFmpeg uses output rotate metadata.
            self.ffmpeg(["-i", str(self.a), "-c", "copy", "-metadata:s:v:0", "rotate=90", str(rotated)])
        plan = self.make_plan()
        edit = copy.deepcopy(plan["edits"][0])
        edit.update(source=str(rotated), source_end=2, duration_frames=60, timeline_end_frame=60,
                    effects={}, speed_points=[])
        plan.update(edits=[edit], duration_frames=60, output={"width": 1080, "height": 1920, "fps": 30})
        result = render_project(plan, self.work/"full-hd.mp4")
        self.assertEqual((result["width"], result["height"], result["frames"], result["duration"]), (1080, 1920, 60, 2))
        cap = cv2.VideoCapture(str(rotated))
        ok, original = cap.read()
        cap.release()
        self.assertTrue(ok)
        self.assertEqual(original.shape[:2], (320, 180))
        cap = cv2.VideoCapture(str(self.work/"full-hd.mp4"))
        ok, rendered = cap.read()
        cap.release()
        self.assertTrue(ok)
        reduced = cv2.resize(rendered, (180, 320), interpolation=cv2.INTER_AREA)
        self.assertLess(float(np.mean(np.abs(reduced.astype(float)-original.astype(float)))), 10)

    def test_image_exif_orientation(self):
        photo = self.work/"exif.jpg"
        image = Image.new("RGB", (20, 10), "red")
        exif = image.getexif()
        exif[274] = 6
        image.save(photo, exif=exif)
        self.assertEqual(_read_image(photo).shape[:2], (20, 10))

    def test_tracking_roi_before_trim_keeps_moving_subject(self):
        moving = self.work/"moving.mp4"
        writer = cv2.VideoWriter(str(moving), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180))
        for i in range(60):
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            x = 20+3*i
            cv2.rectangle(frame, (x, 65), (x+30, 105), (0, 0, 255), -1)
            # Stable internal features make the explicitly selected subject identifiable.
            cv2.line(frame, (x+5, 70), (x+25, 100), (255, 255, 255), 2)
            writer.write(frame)
        writer.release()
        plan = self.make_plan()
        edit = copy.deepcopy(plan["edits"][0])
        edit.update(source=str(moving), source_start=1, source_end=2, duration_frames=30, timeline_end_frame=30,
                    effects={}, speed_points=[], reframe={"mode": "auto", "subject": [20/320, 65/180, 30/320, 40/180], "subject_start": 0})
        plan.update(edits=[edit], duration_frames=30, output={"width": 100, "height": 180, "fps": 30})
        render_project(plan, self.work/"tracked.mp4", preview=True)
        cap = cv2.VideoCapture(str(self.work/"tracked.mp4"))
        centers = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            red = (frame[..., 2] > 150) & (frame[..., 1] < 90)
            xs = np.where(red)[1]
            self.assertGreater(len(xs), 400)
            centers.append(float(xs.mean()))
        cap.release()
        self.assertEqual(len(centers), 30)
        self.assertLess(max(abs(x-50) for x in centers), 14)

    def test_short_audio_requires_explicit_loop(self):
        plan = self.make_plan()
        plan["audio"]["start"] = 2.8
        with self.assertRaisesRegex(ValueError, "shorter"):
            render_project(plan, self.work/"short.mp4", preview=True)
        plan["audio"]["loop"] = True
        result = render_project(plan, self.work/"loop.mp4", preview=True)
        self.assertEqual(result["frames"], 45)

    def test_missing_media_and_timeline_gap_fail_before_render(self):
        plan = self.make_plan()
        plan["edits"][0]["source"] = str(self.work/"missing.mp4")
        with self.assertRaises(FileNotFoundError):
            render_project(plan, self.work/"missing-result.mp4")
        plan = self.make_plan()
        plan["edits"][1]["timeline_start_frame"] += 1
        with self.assertRaisesRegex(ValueError, "gap"):
            render_project(plan, self.work/"gap.mp4")


if __name__ == "__main__":
    unittest.main()

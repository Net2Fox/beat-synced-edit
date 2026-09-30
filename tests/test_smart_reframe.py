"""Tracking and crop checks against a real moving synthetic subject."""

from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smart_reframe import crop_frame, track_subject


class SmartReframeTests(unittest.TestCase):
    def test_manual_subject_follows_horizontal_motion(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "движущийся объект.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 180))
            self.assertTrue(writer.isOpened())
            for frame_index in range(60):
                frame = np.full((180, 320, 3), 20, np.uint8)
                left = 20 + frame_index * 3
                cv2.rectangle(frame, (left, 55), (left + 40, 125), (240, 240, 240), -1)
                cv2.line(frame, (left, 55), (left + 40, 125), (0, 0, 0), 4)
                cv2.circle(frame, (left + 28, 70), 6, (40, 40, 40), -1)
                writer.write(frame)
            writer.release()
            track = track_subject(path, 0, 3, subject=[20 / 320, 55 / 180, 40 / 320, 70 / 180], sample_fps=5)
            self.assertGreaterEqual(len(track), 15)
            self.assertGreater(track[-1]["cx"] - track[0]["cx"], .45)
            for point in track:
                expected = (40 + round(point["time"] * 20) * 3) / 320
                self.assertLess(abs(point["cx"] - expected), .065, point)
                self.assertLess(abs(point["cy"] - .5), .06)
                self.assertTrue(point["method"].startswith("manual_"))
            partial = track_subject(path, 1, 2, subject=[80 / 320, 55 / 180, 40 / 320, 70 / 180])
            self.assertAlmostEqual(partial[0]["time"], 1)
            self.assertGreater(partial[-1]["cx"], partial[0]["cx"])

    def test_no_subject_reports_fallback_and_nonzero_motion(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "motion.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (200, 100))
            for index in range(20):
                frame = np.zeros((100, 200, 3), np.uint8)
                cv2.rectangle(frame, (10 + index * 6, 30), (30 + index * 6, 70), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()
            track = track_subject(path, 0, 2)
            self.assertTrue(any(point["method"] == "motion" for point in track))
            self.assertTrue(all(0 <= point["cx"] <= 1 and 0 <= point["cy"] <= 1 for point in track))

    def test_crop_keeps_subject_and_clamps_edges_without_distortion(self):
        frame = np.zeros((180, 320, 3), np.uint8)
        cv2.rectangle(frame, (245, 50), (280, 130), (255, 255, 255), -1)
        cropped = crop_frame(frame, 90, 160, center=(.82, .5))
        self.assertEqual(cropped.shape, (160, 90, 3))
        self.assertGreater(np.mean(cropped[:, 25:60]), 90)
        edge = crop_frame(frame, 90, 160, center=(2, -1))
        self.assertEqual(edge.shape, (160, 90, 3))
        contained = crop_frame(np.full((100, 200, 3), 255, np.uint8), 100, 100, fit="contain")
        self.assertTrue(np.all(contained[:25] == 0))
        self.assertTrue(np.all(contained[25:75] == 255))

    def test_still_uses_explicit_subject_and_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "фото.png"
            Image.new("RGB", (100, 200), "blue").save(path)
            track = track_subject(path, 0, 0, subject=[.6, .2, .2, .4])
            self.assertAlmostEqual(track[0]["cx"], .7)
            self.assertAlmostEqual(track[0]["cy"], .4)
            self.assertEqual(track[0]["method"], "manual_still")
            with self.assertRaises(ValueError):
                track_subject(path, 0, 1, subject=[-1, 0, 1, 1])
            with self.assertRaises(ValueError):
                track_subject(path, 0, 1, sample_fps=0)


if __name__ == "__main__":
    unittest.main()

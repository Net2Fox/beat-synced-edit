"""Regression coverage for the first-beat offset and Unicode thumbnails."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan_edit = load_module("plan_edit")
clip_tag = load_module("clip_tag")


class AlignmentTests(unittest.TestCase):
    def make_inputs(self, offset=0.0):
        beatmap = {
            "file": "music.wav", "duration": 3 + offset, "tempo": 120,
            "beats": [offset + 0.5, offset + 1.0, offset + 1.5, offset + 2.0],
            "best_segment": {"start": offset, "end": offset + 3.0, "duration": 3.0},
        }
        clips = {"source": "video.mp4", "clips": [
            {"id": i, "start": i * 5.0, "end": i * 5.0 + 4,
             "duration": 4.0, "energy": 0.5, "brightness": 0.5, "motion": "medium"}
            for i in range(5)
        ]}
        return beatmap, clips

    def assert_aligned(self, plan, beats):
        self.assertEqual(plan["edits"][0]["timeline_start"], 0)
        audio = plan["audio_segment"]
        self.assertAlmostEqual(audio["start"], beats[0])
        for edit, beat in zip(plan["edits"], beats):
            self.assertAlmostEqual(edit["timeline_start"] + audio["start"], beat)
        self.assertAlmostEqual(audio["end"] - audio["start"], plan["timeline_duration"])

    def test_full_song_starts_on_first_selected_beat(self):
        beats, clips = self.make_inputs()
        plan = plan_edit.match_clips_to_beats(beats, clips, use_best_segment=False)
        self.assert_aligned(plan, beats["beats"])

    def test_segment_retains_absolute_music_offset(self):
        beats, clips = self.make_inputs(offset=10.0)
        plan = plan_edit.match_clips_to_beats(beats, clips, use_best_segment=True)
        self.assert_aligned(plan, beats["beats"])

    def test_zero_offset_does_not_shift_full_song(self):
        beats, clips = self.make_inputs()
        beats["beats"] = [0.0, 0.5, 1.0, 1.5]
        plan = plan_edit.match_clips_to_beats(beats, clips, use_best_segment=False)
        self.assertEqual(plan["edits"][0]["timeline_start"], 0)
        self.assertIsNone(plan["audio_segment"])


class UnicodeThumbnailTests(unittest.TestCase):
    def test_thumbnail_and_contact_sheet_use_unicode_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "тест превью"
            root.mkdir()
            video = root / "кадр.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
            self.assertTrue(writer.isOpened())
            try:
                for _ in range(10):
                    writer.write(np.full((48, 64, 3), (30, 100, 180), dtype=np.uint8))
            finally:
                writer.release()
            clips = [{"id": 1, "start": 0.0, "end": 1.0, "motion": "static"}]
            count = clip_tag.extract_thumbnails_all(clips, {video.name: str(video)}, video.name, str(root / "миниатюры"))
            self.assertEqual(count, 1)
            self.assertTrue(Path(clips[0]["thumb"]).is_file())
            sheet = root / "контактный лист.jpg"
            clip_tag.build_contact_sheet(clips, str(sheet), cols=1, cell_w=64)
            self.assertTrue(sheet.is_file())


if __name__ == "__main__":
    unittest.main()

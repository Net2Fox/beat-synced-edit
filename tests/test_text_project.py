"""Title/caption revisions stay atomic and preserve picture/audio timing."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from project_workspace import apply_revisions, read_json, revise_file, write_json
from test_project_workspace import fixture


class TextRevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_title_add_update_remove_and_style_leave_timeline_unchanged(self):
        before = copy.deepcopy(self.plan)
        plan = apply_revisions(self.plan, [
            {"op": "title_add", "values": {"text": "Новый ролик: 100%", "start": .5, "end": 2}},
            {"op": "text_style", "track": "titles", "values": {"color": "#FFCC00", "animation": "fade"}},
        ])
        self.assertEqual(plan["titles"][0]["start_frame"], 15)
        self.assertEqual(plan["titles"][0]["end_frame"], 60)
        identifier = plan["titles"][0]["id"]
        updated = apply_revisions(plan, [{"op": "title_update", "id": identifier,
                                          "values": {"text": "Другой заголовок", "style": {"position": "center"}}}])
        self.assertEqual(updated["titles"][0]["text"], "Другой заголовок")
        self.assertEqual(updated["edits"], before["edits"])
        self.assertEqual(updated["audio"], before["audio"])
        self.assertEqual(updated["duration_frames"], before["duration_frames"])
        cleared = apply_revisions(updated, [{"op": "title_remove", "id": identifier}])
        self.assertEqual(cleared["titles"], [])
        self.assertEqual(self.plan, before)

    def caption(self):
        return {"id": "sub-001", "text": "Привет мир", "start_frame": 15, "end_frame": 60,
                "words": [{"text": "Привет", "start_frame": 15, "end_frame": 30},
                          {"text": "мир", "start_frame": 30, "end_frame": 60}]}

    def test_text_edit_clears_stale_word_alignment(self):
        plan = apply_revisions(self.plan, [{"op": "subtitles_replace", "cues": [self.caption()]}])
        changed = apply_revisions(plan, [{"op": "subtitle_update", "id": "sub-001", "values": {"text": "Исправленная фраза"}}])
        self.assertNotIn("words", changed["subtitles"][0])
        self.assertEqual(changed["subtitles"][0]["end_frame"], 60)

    def test_caption_timing_edit_moves_word_alignment(self):
        plan = apply_revisions(self.plan, [{"op": "subtitles_replace", "cues": [self.caption()]}])
        changed = apply_revisions(plan, [{"op": "subtitle_update", "id": "sub-001", "values": {"start": 1, "end": 3}}])
        cue = changed["subtitles"][0]
        self.assertEqual((cue["start_frame"], cue["end_frame"]), (30, 90))
        self.assertEqual(cue["words"][0]["start_frame"], 30)
        self.assertEqual(cue["words"][-1]["end_frame"], 90)

    def test_half_frame_uses_same_rounding_as_subtitle_import(self):
        changed = apply_revisions(self.plan, [{"op": "title_add", "values": {
            "text": "One frame", "start": 1 / 60, "end": 3 / 60}}])
        self.assertEqual((changed["titles"][0]["start_frame"], changed["titles"][0]["end_frame"]), (1, 2))

    def test_shift_clips_to_project_and_drops_fully_outside_cues(self):
        plan = apply_revisions(self.plan, [{"op": "subtitles_replace", "cues": [self.caption(),
            {"id": "sub-002", "text": "Конец", "start_frame": 165, "end_frame": 180}]}])
        changed = apply_revisions(plan, [{"op": "subtitles_shift", "seconds": 1}])
        self.assertEqual(len(changed["subtitles"]), 1)
        self.assertEqual(changed["subtitles"][0]["words"][0]["start_frame"], 45)

    def test_invalid_text_does_not_corrupt_saved_project(self):
        path = self.root / "project.json"
        write_json(path, self.plan)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            revise_file(path, [{"op": "title_add", "values": {"text": "OK", "start": 1, "end": 2}},
                               {"op": "title_add", "values": {"text": "Too late", "start": 5, "end": 8}}])
        self.assertEqual(path.read_bytes(), before)

    def test_overlapping_subtitles_are_rejected(self):
        with self.assertRaises(ValueError):
            apply_revisions(self.plan, [{"op": "subtitles_replace", "cues": [self.caption(),
                {"id": "sub-002", "text": "Overlap", "start_frame": 45, "end_frame": 75}]}])

    def test_retiming_picture_does_not_shift_output_timed_subtitles(self):
        plan = apply_revisions(self.plan, [{"op": "subtitles_replace", "cues": [self.caption()]}])
        seconds = (plan["edits"][0]["duration_frames"] + 1) / 30
        revised = apply_revisions(plan, [{"op": "duration", "shot": 1, "seconds": seconds}])
        self.assertEqual(revised["subtitles"], plan["subtitles"])


if __name__ == "__main__":
    unittest.main()

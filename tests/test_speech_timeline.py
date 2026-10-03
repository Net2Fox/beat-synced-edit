"""Meaningful timing, transcript, revision and audible speech invariants."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timeline_map import source_times, inverse_source_times, source_to_output, output_to_source, resolve_anchor
from speech_project import normalize_transcript, import_transcript, phrase_candidates, build_speech_plan, refresh_source_captions
from project_workspace import apply_revisions, write_json
from subtitle_tools import export_subtitles


def fixture(root):
    asset = {"id": "speech-source", "path": str(root/"speaker.mp4"), "kind": "video", "duration": 12,
             "width": 320, "height": 180, "has_audio": True}
    transcript = normalize_transcript({"segments": [
        {"start": 1, "end": 3, "text": "Hello world.", "words": [{"start": 1, "end": 1.8, "text": "Hello"}, {"start": 2, "end": 3, "text": "world."}]},
        {"start": 5, "end": 7, "text": "Second thought!", "words": [{"start": 5, "end": 5.8, "text": "Second"}, {"start": 6, "end": 7, "text": "thought!"}]}]}, asset["id"])
    return build_speech_plan(asset, transcript, fps=30, width=180, height=320, padding=0, pause_limit=0)


class MappingTests(unittest.TestCase):
    def test_inverse_tracks_exact_nonlinear_anchor_curve(self):
        edit = {"source_start": 4, "source_end": 12, "speed_points": [
            {"at": 0, "speed": 3}, {"at": .5, "speed": 1}, {"at": 1, "speed": 2}],
            "action_anchor": {"source_time": 7, "output_fraction": .6}}
        positions = np.linspace(0, 1, 101)
        times = source_times(edit, positions)
        np.testing.assert_allclose(inverse_source_times(edit, times), positions, atol=1e-12)
        self.assertAlmostEqual(source_times(edit, [.6])[0], 7)

    def test_repeated_source_returns_all_occurrences_and_can_choose_shot(self):
        shot = {"id": "a", "asset_id": "asset", "source": "x", "kind": "video", "source_start": 1,
                "source_end": 3, "duration_frames": 60, "timeline_start_frame": 0, "timeline_end_frame": 60}
        plan = {"output": {"fps": 30}, "edits": [shot, {**shot, "id": "b", "timeline_start_frame": 60, "timeline_end_frame": 120}], "duration_frames": 120}
        self.assertEqual([round(x["frame"]) for x in source_to_output(plan, "asset", 2)], [30, 90])
        self.assertEqual(len(source_to_output(plan, "asset", 2, shot_id="b")), 1)
        self.assertAlmostEqual(output_to_source(plan, 75)["time"], 1.5)


class SpeechProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = fixture(self.root)

    def test_speech_plan_is_natural_speed_with_original_audio(self):
        self.assertEqual(self.plan["duration"], 4)
        self.assertTrue(self.plan["audio_mix"]["source_audio"]["enabled"])
        self.assertTrue(self.plan["audio_mix"]["replace_legacy"])
        self.assertEqual([e["average_speed"] for e in self.plan["edits"]], [1, 1])
        self.assertEqual(self.plan["subtitles"][0]["start_frame"], 0)

    def test_pause_policy_preserves_specified_pause(self):
        p = build_speech_plan(self.plan["assets"][0], self.plan["speech"]["transcripts"][0], pause_limit=None, padding=0)
        self.assertEqual(p["duration"], 6)
        p = build_speech_plan(self.plan["assets"][0], self.plan["speech"]["transcripts"][0], pause_limit=.5, padding=0)
        self.assertEqual(p["duration"], 4.5)

    def test_candidates_retain_complete_thoughts_and_review_status(self):
        transcript = deepcopy(self.plan["speech"]["transcripts"][0])
        transcript["segments"][1]["words"][-1]["text"] = "thought"
        candidates = phrase_candidates(transcript, max_duration=1)
        self.assertTrue(candidates[0]["complete_thought"])
        self.assertFalse(candidates[1]["complete_thought"])
        self.assertTrue(candidates[0]["over_duration"])
        self.assertEqual(candidates[0]["review_status"], "not_reviewed")

    def test_source_captions_follow_reorder_and_output_title_stays(self):
        order = [e["id"] for e in reversed(self.plan["edits"])]
        p = apply_revisions(self.plan, [{"op": "title_add", "values": {"text": "Static", "start": 0, "end": 1}},
                                       {"op": "reorder", "order": order}])
        self.assertEqual(p["subtitles"][0]["text"], "Second thought!")
        self.assertEqual(p["subtitles"][0]["start_frame"], 0)
        self.assertEqual(p["titles"][0]["start_frame"], 0)

    def test_source_captions_follow_nonlinear_speed_and_clipping(self):
        p = deepcopy(self.plan)
        p["edits"][0]["speed_points"] = [{"at": 0, "speed": 2}, {"at": 1, "speed": 1}]
        refresh_source_captions(p)
        expected = round(inverse_source_times(p["edits"][0], [1.8])[0]*60)
        self.assertEqual(p["subtitles"][0]["words"][0]["end_frame"], expected)
        p["edits"][0]["source_start"] = 2
        refresh_source_captions(p)
        self.assertEqual(p["subtitles"][0]["text"], "world.")

    def test_broll_keeps_voice_mapping_and_source_caption(self):
        clip = {"id": "broll", "asset_id": "broll", "source": str(self.root/"broll.mp4"), "kind": "video", "start": 0, "end": 4}
        asset = {"id": "broll", "path": clip["source"], "kind": "video", "duration": 4}
        p = apply_revisions(self.plan, [{"op": "speech_broll", "shot_id": self.plan["edits"][0]["id"], "clip_id": "broll", "asset": asset, "clip": clip}])
        self.assertEqual(p["edits"][0]["source"], clip["source"])
        self.assertEqual(output_to_source(p, 0, "speech")["time"], 1)
        self.assertEqual(p["subtitles"][0]["text"], "Hello world.")

    def test_word_correction_stable_id_and_glossary_persist(self):
        word = self.plan["speech"]["transcripts"][0]["segments"][0]["words"][0]
        p = apply_revisions(self.plan, [{"op": "speech_correct", "corrections": {word["id"]: "Hi"}, "glossary": {"world": "Codex"}}])
        new = p["speech"]["transcripts"][0]["segments"][0]["words"][0]
        self.assertEqual(new["id"], word["id"])
        self.assertEqual(new["start"], word["start"])
        self.assertEqual(p["subtitles"][0]["text"], "Hi Codex.")
        self.assertTrue(p["speech"]["transcripts"][0]["corrections"])

    def test_bounded_broll_splits_picture_but_keeps_continuous_source_voice(self):
        clip = {"id": "broll", "asset_id": "broll", "source": str(self.root/"broll.mp4"), "kind": "video", "start": 0, "end": 4}
        asset = {"id": "broll", "path": clip["source"], "kind": "video", "duration": 4}
        p = apply_revisions(self.plan, [{"op": "speech_broll", "shot_id": self.plan["edits"][0]["id"], "clip_id": "broll",
             "asset": asset, "clip": clip, "offset": .5, "duration": 1}])
        self.assertEqual([e["duration_frames"] for e in p["edits"]], [15, 30, 15, 60])
        self.assertEqual(p["duration_frames"], 120)
        self.assertEqual([c["text"] for c in p["subtitles"]], ["Hello world.", "Second thought!"])
        for frame in (0, 14, 15, 44, 45, 59):
            self.assertAlmostEqual(output_to_source(p, frame, "speech")["time"], 1+frame/30)

    def test_valid_acceleration_revision_remaps_word_cues(self):
        p = deepcopy(self.plan)
        p["edits"][0].update(source_end=5, average_speed=2)
        refresh_source_captions(p)
        p = apply_revisions(p, [{"op": "speed", "shot": 1, "points": [{"at": 0, "speed": 3}, {"at": 1, "speed": 1}]}])
        expected = round(float(inverse_source_times(p["edits"][0], [1.8])[0])*60)
        self.assertEqual(p["subtitles"][0]["words"][0]["end_frame"], expected)

    def test_replaced_source_removes_its_captions_and_marks_word_anchor_unresolved(self):
        p = deepcopy(self.plan)
        p["assets"].append({"id": "new", "path": str(self.root/"new.mp4"), "kind": "video", "duration": 4})
        p["clips"].append({"id": "new-clip", "asset_id": "new", "source": str(self.root/"new.mp4"), "kind": "video", "start": 0, "end": 4})
        word = p["speech"]["transcripts"][0]["segments"][0]["words"][0]
        p = apply_revisions(p, [{"op": "anchor_set", "value": {"id": "first-word", "anchor": {"type": "word", "id": word["id"]}}},
                                 {"op": "replace", "shot": 1, "clip_id": "new-clip"}])
        self.assertEqual([c["text"] for c in p["subtitles"]], ["Second thought!"])
        self.assertEqual(p["anchors"][0]["status"], "unresolved")

    def test_free_phrase_rewrite_discards_old_word_highlights(self):
        segment = self.plan["speech"]["transcripts"][0]["segments"][0]
        p = apply_revisions(self.plan, [{"op": "speech_correct", "corrections": {segment["id"]: "A very different statement."}}])
        self.assertNotIn("words", p["subtitles"][0])
        self.assertTrue(p["speech"]["transcripts"][0]["segments"][0]["superseded_words"])

    def test_bilingual_export_uses_supplied_translations(self):
        segments = self.plan["speech"]["transcripts"][0]["segments"]
        values = {segments[0]["id"]: "Привет, мир.", segments[1]["id"]: "Вторая мысль!"}
        p = apply_revisions(self.plan, [{"op": "speech_translate", "translations": values, "language": "ru", "mode": "bilingual"}])
        self.assertEqual(p["subtitles"][0]["text"], "Hello world.\nПривет, мир.")
        for fmt in ("srt", "vtt"):
            target = self.root/f"captions.{fmt}"
            export_subtitles(p["subtitles"], 30, target)
            self.assertIn("Привет, мир.", target.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "Missing supplied"):
            apply_revisions(self.plan, [{"op": "speech_translate", "translations": {segments[0]["id"]: "One"}, "language": "ru"}])

    def test_missing_word_ids_fail_atomically(self):
        before = deepcopy(self.plan)
        with self.assertRaisesRegex(ValueError, "Unknown correction"):
            apply_revisions(self.plan, [{"op": "speech_correct", "corrections": {"bad": "x"}}])
        self.assertEqual(self.plan, before)

    def test_subtitle_removal_and_detached_text_survive_other_revisions(self):
        p = apply_revisions(self.plan, [{"op": "subtitle_update", "id": self.plan["subtitles"][0]["id"], "values": {"text": "Custom"}}])
        p = apply_revisions(p, [{"op": "effects", "all": True, "values": {"flash": 0}}])
        self.assertEqual(p["subtitles"][0]["text"], "Custom")

    def test_word_action_and_title_anchors_follow_reorder(self):
        word = self.plan["speech"]["transcripts"][0]["segments"][0]["words"][0]
        p = apply_revisions(self.plan, [{"op": "action_set", "value": {"id": "hello", "source_id": "speech-source", "time": 1}},
            {"op": "anchor_set", "value": {"id": "word-anchor", "anchor": {"type": "word", "id": word["id"]}}},
            {"op": "title_add", "values": {"text": "Here", "start": 0, "end": .5, "anchor": {"type": "action", "id": "hello"}}}])
        p = apply_revisions(p, [{"op": "reorder", "order": [e["id"] for e in reversed(p["edits"])]}])
        self.assertAlmostEqual(p["anchors"][0]["resolved_frames"][0], 60)
        self.assertEqual(p["titles"][0]["start_frame"], 60)
        self.assertEqual(resolve_anchor(p, {"type": "word", "id": "removed"}), [])

    def test_srt_import_retains_milliseconds_without_fabricating_words(self):
        path = self.root/"input.srt"
        path.write_text("1\n00:00:00,123 --> 00:00:01,789\nHello.\n", encoding="utf-8")
        transcript = import_transcript(path, "source", 3)
        self.assertEqual(transcript["segments"][0]["start"], .123)
        self.assertNotIn("words", transcript["segments"][0])

    def test_retry_adds_only_gap_without_changing_existing_word_ids(self):
        transcript = self.plan["speech"]["transcripts"][0]
        incoming = normalize_transcript({"id": "retry", "segments": [{"start": 3.5, "end": 4, "text": "Missing."}]}, "speech-source")
        p = apply_revisions(self.plan, [{"op": "speech_retry_result", "transcript_id": transcript["id"], "start": 3, "end": 5, "transcript": incoming}])
        self.assertEqual(p["speech"]["transcripts"][0]["segments"][0]["words"], transcript["segments"][0]["words"])
        self.assertEqual(len(p["speech"]["transcripts"][0]["segments"]), 3)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            apply_revisions(self.plan, [{"op": "speech_retry_result", "transcript_id": transcript["id"], "start": 2, "end": 4, "transcript": incoming}])

    def test_retry_can_fill_word_gap_inside_single_asr_segment(self):
        p = deepcopy(self.plan)
        transcript = p["speech"]["transcripts"][0]
        a, b = transcript["segments"]
        before_ids = [w["id"] for s in transcript["segments"] for w in s["words"]]
        a.update(end=b["end"], text=a["text"]+" "+b["text"], words=a["words"]+b["words"])
        transcript["segments"] = [a]
        refresh_source_captions(p)
        incoming = normalize_transcript({"id": "retry", "segments": [{"start": 3.5, "end": 4.5, "text": "Recovered."}]}, "speech-source")
        changed = apply_revisions(p, [{"op": "speech_retry_result", "transcript_id": transcript["id"], "start": 3, "end": 5, "transcript": incoming}])
        segments = changed["speech"]["transcripts"][0]["segments"]
        self.assertEqual(len(segments), 3)
        self.assertEqual([w["id"] for s in segments for w in s.get("words", [])], before_ids)


class ModelReuseTests(unittest.TestCase):
    def test_model_reused_across_multiple_files_in_batch(self):
        from speech_transcribe import transcribe_audio, clear_model_cache
        clear_model_cache()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/"voice.wav"; source.write_bytes(b"mock")
            recognizer = Mock()
            recognizer.transcribe.side_effect = lambda *a, **k: (iter([]), SimpleNamespace(language="en", duration=1))
            constructor = Mock(return_value=recognizer)
            with patch.dict("sys.modules", {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
                transcribe_audio(source); transcribe_audio(source)
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(recognizer.transcribe.call_count, 2)
        clear_model_cache()


if __name__ == "__main__":
    unittest.main()

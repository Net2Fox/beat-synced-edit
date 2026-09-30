import copy
from pathlib import Path
import tempfile
import unittest

from subtitle_tools import export_subtitles, import_subtitles, segment_transcript


class SubtitleInterchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="subtitles-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "кириллица"
        self.root.mkdir()
        self.plan = {"output": {"fps": 30}, "duration_frames": 300, "audio": {"start": 10}}

    def write(self, text, suffix="srt", encoding="utf-8"):
        path = self.root / f"титры.{suffix}"
        path.write_text(text, encoding=encoding, newline="")
        return path

    def test_utf8_bom_crlf_multiline_and_known_markup(self):
        path = self.write("1\r\n00:00:00,100 --> 00:00:02,000\r\n<b>Привет</b> &amp; мир\r\n<i>Вторая строка</i>\r\n", encoding="utf-8-sig")
        self.assertEqual(import_subtitles(path, self.plan), [{"id": "sub-001", "text": "Привет & мир\nВторая строка", "start_frame": 3, "end_frame": 60}])

    def test_vtt_header_notes_settings_classes_and_literal_text(self):
        path = self.write("WEBVTT test\n\nNOTE a comment\nignored\n\nSTYLE\n::cue { color: lime; }\n\nREGION\nid:one\n\ncustom-id\n00:01.000 --> 00:02.500 align:start position:20%\n<v Анна><c.yellow>Текст</c></v> <00:01.500>&lt;b&gt; literal <unknown>\n", "vtt")
        result = import_subtitles(path, self.plan)
        self.assertEqual(result[0]["text"], "Текст <b> literal <unknown>")
        self.assertEqual((result[0]["start_frame"], result[0]["end_frame"]), (30, 75))

    def test_soundtrack_offset_and_clip_both_edges(self):
        path = self.write("1\n00:00:08,000 --> 00:00:11,000\nBeginning\n\n2\n00:00:18,000 --> 00:00:23,000\nEnd\n\n3\n00:00:30,000 --> 00:00:32,000\nOutside\n")
        result = import_subtitles(path, self.plan, offset=.5, timebase="soundtrack")
        self.assertEqual([(cue["start_frame"], cue["end_frame"]) for cue in result], [(0, 45), (255, 300)])

    def test_negative_offset_skips_fully_outside_and_keeps_subframe_cue(self):
        path = self.write("1\n00:00:00,000 --> 00:00:00,500\nSkip\n\n2\n00:00:01,000 --> 00:00:01,001\nTiny\n")
        result = import_subtitles(path, self.plan, offset=-1)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["start_frame"], result[0]["end_frame"]), (0, 1))

    def test_overlaps_survive_and_sort_stably(self):
        path = self.write("1\n00:00:02,000 --> 00:00:04,000\nSecond\n\n2\n00:00:01,000 --> 00:00:03,000\nFirst\n")
        self.assertEqual([cue["text"] for cue in import_subtitles(path, self.plan)], ["First", "Second"])

    def test_all_frame_boundaries_roundtrip_srt_and_vtt(self):
        for fps in (24, 25, 30, 60, 120):
            plan = {"output": {"fps": fps}, "duration_frames": 3600 * fps + 4}
            cues = [{"id": f"sub-{i + 1:03d}", "text": "<b>Literal</b> & Привет\nLine 2", "start_frame": frame, "end_frame": frame + 1}
                    for i, frame in enumerate(list(range(fps * 2)) + [3600 * fps + 1])]
            for kind in ("srt", "vtt"):
                with self.subTest(fps=fps, kind=kind):
                    target = self.root / f"roundtrip.{kind}"
                    self.assertEqual(export_subtitles(cues, fps, target), str(target.resolve()))
                    self.assertEqual(import_subtitles(target, plan), cues)

    def test_empty_file_and_empty_export(self):
        self.assertEqual(import_subtitles(self.write(""), self.plan), [])
        path = self.root / "empty.vtt"
        export_subtitles([], 30, path)
        self.assertEqual(import_subtitles(path, self.plan), [])

    def test_invalid_cues_fail_with_context(self):
        cases = [
            "1\n00:00:61,000 --> 00:01:04,000\nBad seconds",
            "1\n00:00:00,00 --> 00:00:01,000\nBad milliseconds",
            "1\n00:00:02,000 --> 00:00:01,000\nBackwards",
            "1\n00:00:00,000 --> 00:00:01,000\n<b></b>",
            "1\n00:00:00,000 --> 00:00:01,000\nText\n2\n00:00:01,000 --> 00:00:02,000\nMissing gap",
            "words without timing",
        ]
        for text in cases:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "титры.srt, cue block"):
                import_subtitles(self.write(text), self.plan)

    def test_non_utf8_fails_actionably(self):
        path = self.write("1\n00:00:00,000 --> 00:00:01,000\nПривет", encoding="cp1251")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            import_subtitles(path, self.plan)

    def test_vtt_missing_header_or_timestamp_map_rejected(self):
        for text in ("00:00.000 --> 00:01.000\nText", "WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:90000,LOCAL:00:00:00.000\n\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                import_subtitles(self.write(text, "vtt"), self.plan)

    def test_invalid_options_and_output_ranges(self):
        path = self.write("1\n00:00:00,000 --> 00:00:01,000\nText")
        for kwargs in ({"offset": float("nan")}, {"timebase": "source"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                import_subtitles(path, self.plan, **kwargs)
        for cue in ({"start_frame": -1, "end_frame": 2, "text": "T"}, {"start_frame": 1, "end_frame": 1, "text": "T"},
                    {"start_frame": 0, "end_frame": 1, "text": "T\n\nBlank"}):
            with self.subTest(cue=cue), self.assertRaises(ValueError):
                export_subtitles([cue], 30, path)


class TranscriptSegmentationTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"output": {"fps": 30}, "duration_frames": 300, "audio": {"start": 10}}
        self.transcript = {"segments": [{"start": 0, "end": 4, "text": "Hello world. This is a test!", "words": [
            {"start": 0, "end": .5, "text": " Hello"}, {"start": .5, "end": 1, "text": " world."},
            {"start": 1.1, "end": 1.5, "text": " This"}, {"start": 1.5, "end": 2, "text": " is"},
            {"start": 2, "end": 2.2, "text": " a"}, {"start": 2.2, "end": 3, "text": " test!"}]}]}

    def test_phrase_boundaries_and_real_word_times(self):
        cues = segment_transcript(self.transcript, self.plan)
        self.assertEqual([cue["text"] for cue in cues], ["Hello world.", "This is a test!"])
        self.assertEqual(cues[0]["words"], [{"text": "Hello", "start_frame": 0, "end_frame": 15}, {"text": "world.", "start_frame": 15, "end_frame": 30}])
        self.assertEqual((cues[1]["start_frame"], cues[1]["end_frame"]), (33, 90))

    def test_word_character_and_duration_limits(self):
        for kwargs in ({"max_words": 1}, {"max_chars": 6}, {"max_duration": .55}):
            with self.subTest(kwargs=kwargs):
                cues = segment_transcript(self.transcript, self.plan, **kwargs)
                self.assertGreater(len(cues), 2)
                self.assertEqual(sum(len(cue["words"]) for cue in cues), 6)

    def test_shift_and_crop_remove_outside_words(self):
        cues = segment_transcript(self.transcript, self.plan, offset=9.5, timebase="soundtrack")
        self.assertEqual(cues[0]["text"], "world.")
        self.assertEqual(cues[0]["words"], [{"text": "world.", "start_frame": 0, "end_frame": 15}])

    def test_pause_splits_phrase(self):
        data = {"segments": [{"start": 0, "end": 3, "text": "one two", "words": [
            {"text": "one", "start": 0, "end": .3}, {"text": "two", "start": 1.5, "end": 2}]}]}
        self.assertEqual([cue["text"] for cue in segment_transcript(data, self.plan)], ["one", "two"])

    def test_cjk_does_not_add_spaces(self):
        data = {"segments": [{"start": 0, "end": 1, "text": "你好世界", "words": [
            {"text": "你好", "start": 0, "end": .3}, {"text": "世界", "start": .3, "end": 1}]}]}
        self.assertEqual(segment_transcript(data, self.plan)[0]["text"], "你好世界")

    def test_no_invented_word_timings_for_untimed_segment(self):
        data = {"segments": [{"start": 0, "end": 8, "text": "An untimed phrase that exceeds the requested limits"}]}
        cues = segment_transcript(data, self.plan, max_chars=8)
        self.assertEqual(len(cues), 1)
        self.assertNotIn("words", cues[0])
        self.assertEqual(cues[0]["end_frame"], 240)

    def test_words_sharing_one_frame_keep_text_without_overlapping_highlights(self):
        data = {"segments": [{"start": 0, "end": .04, "text": "A tiny phrase", "words": [
            {"text": " A", "start": 0, "end": .005},
            {"text": " tiny", "start": .005, "end": .01},
            {"text": " phrase", "start": .01, "end": .04}]}]}
        for kwargs in ({}, {"max_words": 1}):
            with self.subTest(kwargs=kwargs):
                cues = segment_transcript(data, self.plan, **kwargs)
                self.assertEqual(len(cues), 1)
                self.assertEqual(cues[0]["text"], "A tiny phrase")
                self.assertEqual(cues[0]["words"], [{"text": "A tiny phrase", "start_frame": 0, "end_frame": 1}])

    def test_empty_transcript_is_empty_and_input_not_mutated(self):
        self.assertEqual(segment_transcript({"segments": []}, self.plan), [])
        saved = copy.deepcopy(self.transcript)
        segment_transcript(self.transcript, self.plan)
        self.assertEqual(self.transcript, saved)

    def test_bad_word_and_nonfinite_time_rejected(self):
        for replacement in ({"start": -1}, {"end": 10}, {"end": float("nan")}, {"text": ""}):
            data = copy.deepcopy(self.transcript)
            data["segments"][0]["words"][0].update(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                segment_transcript(data, self.plan)


if __name__ == "__main__":
    unittest.main()

"""Waveform-verified bar splices, overlaps, gaps and fresh music maps."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from audio_mix import SAMPLE_RATE as SR, decode_audio, write_audio
from music_arrangement import arrange_music, arrangement_plan, verify_arrangement


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class ArrangementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root/"music.wav"
        random = np.random.default_rng(123)
        # Distinct aperiodic audio with exact impulse events every half-second.
        pcm = random.normal(0, .005, (4*SR, 2)).astype(np.float32)
        for i in range(8):
            start = i*SR//2
            pcm[start:start+240] += np.exp(-np.arange(240)/45)[:, None]*.25
        write_audio(cls.source, pcm)
        cls.pcm = decode_audio(cls.source)
        cls.beats = {"file": str(cls.source), "duration": 4, "tempo": 120, "beats": [i/2 for i in range(8)]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_bars_reorder_with_exact_pcm_and_reanalyzed_map(self):
        result = arrange_music(self.source, self.beats,
                               [{"start_bar": 2, "end_bar": 3}, {"start_bar": 1, "end_bar": 2}],
                               self.root/"reordered.wav")
        expected = np.vstack([self.pcm[2*SR:], self.pcm[:2*SR]])
        np.testing.assert_array_equal(decode_audio(result["path"]), expected)
        self.assertTrue(result["verification"]["timing_verified"])
        self.assertEqual(result["samples"], 4*SR)
        beatmap = json.loads(Path(result["beatmap"]).read_text())
        self.assertEqual(beatmap["arranged_beats"], [i/2 for i in range(8)])
        self.assertEqual(Path(beatmap["file"]), Path(result["path"]))
        self.assertIn("energy_curve", beatmap)
        self.assertIn("arrangement", beatmap)

    def test_crossfade_and_gap_lengths_and_windows(self):
        result = arrange_music(self.source, self.beats,
                               [{"start_bar": 1, "end_bar": 2}, {"start_bar": 2, "end_bar": 3, "crossfade": .1},
                                {"start_beat": 0, "end_beat": 2, "gap_before": .25}],
                               self.root/"overlap.wav")
        self.assertEqual(result["samples"], round(5.15*SR))
        pcm = decode_audio(result["path"])
        np.testing.assert_array_equal(pcm[round(3.9*SR):round(4.15*SR)], 0)
        self.assertTrue(result["verification"]["timing_verified"])
        self.assertLess(np.max(np.abs(pcm)), .5)

    def test_shift_detection_catches_displaced_segment(self):
        plan = arrangement_plan(self.source, self.beats, [{"start_bar": 1, "end_bar": 2}])
        expected = self.pcm[:2*SR]
        displaced = np.vstack([np.zeros((20, 2), np.float32), expected[:-20]])
        report = verify_arrangement(displaced, [expected], plan)
        self.assertEqual(report["segments"][0]["status"], "failed")
        self.assertEqual(report["segments"][0]["shift_samples"], 20)

    def test_silence_is_not_claimed_as_correlation_verification(self):
        plan = arrangement_plan(self.source, self.beats, [{"start_bar": 1, "end_bar": 2}])
        zeros = np.zeros((2*SR, 2), np.float32)
        report = verify_arrangement(zeros, [zeros], plan)
        self.assertEqual(report["segments"][0]["status"], "unmeasurable")
        self.assertTrue(report["segments"][0]["exact_pcm"])
        self.assertFalse(report["timing_verified"])

    def test_invalid_boundaries_fail_without_overwriting_source(self):
        for segment in ({"start_bar": 0, "end_bar": 2}, {"start_bar": 1, "end_bar": 7},
                        {"start_bar": 1, "end_bar": 2, "crossfade": .1},
                        {"start_bar": 1, "end_bar": 2, "gap_before": float("nan")}):
            with self.subTest(segment=segment), self.assertRaises(ValueError):
                arrangement_plan(self.source, self.beats, [segment])
        with self.assertRaisesRegex(ValueError, "overwrite"):
            arrange_music(self.source, self.beats, [{"start_bar": 1, "end_bar": 2}], self.source)


if __name__ == "__main__":
    unittest.main()

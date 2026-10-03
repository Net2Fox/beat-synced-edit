"""Real FFmpeg and waveform ground truth for source sound, ducking and exports."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from audio_mix import (SAMPLE_RATE as SR, decode_audio, duck_envelope, encoded_audio_report,
                       expanded_tracks, mix_project_audio, retime_source, validate_audio_mix, write_audio)


def tone(frequency, duration, amplitude=.1):
    values = amplitude*np.sin(2*np.pi*frequency*np.arange(round(duration*SR))/SR)
    return np.column_stack([values, values]).astype(np.float32)


def amplitude(samples, frequency):
    values = np.asarray(samples).mean(axis=1)
    time = np.arange(len(values))/SR
    return abs(np.dot(values, np.exp(-2j*np.pi*frequency*time)))*2/len(values)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioMixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.music, cls.voice, cls.sfx = [cls.work/n for n in ("music.wav", "voice.wav", "sfx.wav")]
        write_audio(cls.music, tone(300, 4))
        write_audio(cls.voice, tone(900, 1))
        write_audio(cls.sfx, tone(1800, .25))
        cls.video = cls.work/"source.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=4",
                        "-i", str(cls.music), "-c:v", "libx264", "-c:a", "aac", "-shortest", str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def plan(self):
        return {"schema_version": 2, "duration_frames": 120, "output": {"fps": 30, "width": 64, "height": 64},
                "edits": [{"id": "shot-1", "asset_id": "source-1", "kind": "video", "source": str(self.video),
                           "source_start": 0., "source_end": 4., "duration_frames": 120,
                           "timeline_start_frame": 0, "timeline_end_frame": 120, "speed_points": []}],
                "audio_mix": {"replace_legacy": True, "loudness": {"enabled": False}, "tracks": []}}

    def test_legacy_audio_preserves_levels_duration_cache_and_content_invalidation(self):
        plan = self.plan()
        del plan["audio_mix"]
        plan["audio"] = {"path": str(self.music), "start": 0}
        output, report = mix_project_audio(plan, self.work/"legacy-cache")
        self.assertEqual(len(decode_audio(output)), 4*SR)
        self.assertAlmostEqual(amplitude(decode_audio(output), 300), .1, places=4)
        self.assertEqual(report["normalization"]["method"], "disabled")
        self.assertTrue(mix_project_audio(plan, self.work/"legacy-cache")[1]["cache_hit"])
        output.write_bytes(b"corrupt cached file")
        self.assertFalse(mix_project_audio(plan, self.work/"legacy-cache")[1]["cache_hit"])

    def test_music_ducks_under_voice_and_recovers_with_sfx_and_fades(self):
        plan = self.plan()
        plan["audio_mix"].update(ducking={"enabled": True, "reduction_db": 18, "attack": .01, "release": .1}, tracks=[
            {"id": "music", "role": "music", "path": str(self.music), "duration": 4},
            {"id": "voice", "role": "voice", "path": str(self.voice), "start": 1, "duration": 1},
            {"id": "hit", "role": "sfx", "path": str(self.sfx), "start": 3, "duration": .25,
             "gain_db": -6, "fade_in": .03, "fade_out": .03}])
        path, report = mix_project_audio(plan, self.work/"duck-cache")
        pcm = decode_audio(path)
        baseline = amplitude(pcm[int(.2*SR):int(.7*SR)], 300)
        ducked = amplitude(pcm[int(1.3*SR):int(1.8*SR)], 300)
        recovered = amplitude(pcm[int(2.7*SR):int(2.9*SR)], 300)
        self.assertLess(ducked/baseline, .15)
        self.assertGreater(recovered/baseline, .99)
        self.assertAlmostEqual(amplitude(pcm[int(1.3*SR):int(1.8*SR)], 900), .1, places=3)
        self.assertTrue(report["ducking"]["applied"])
        self.assertEqual(len(report["grouped_stems"]), 3)
        self.assertLess(amplitude(pcm[int(3.0*SR):int(3.01*SR)], 1800), .02)

    def test_source_sound_survives_broll_and_has_exact_duration(self):
        plan = self.plan()
        plan["audio_mix"]["source_audio"] = {"enabled": True, "role": "speech", "gain_db": -6}
        plan["edits"][0]["audio_source"] = copy.deepcopy(plan["edits"][0])
        plan["edits"][0].update(kind="image", source="unused-broll.png")
        path, report = mix_project_audio(plan, self.work/"source-cache")
        pcm = decode_audio(path)
        self.assertEqual(len(pcm), 4*SR)
        self.assertAlmostEqual(amplitude(pcm[SR:2*SR], 300), .05, delta=.002)
        self.assertEqual(report["stems"][0]["id"], "source:shot-1")

    def test_source_reorder_and_trim_follow_timeline(self):
        source = self.work/"ordered.wav"
        write_audio(source, np.vstack([tone(200, 1), tone(800, 1), tone(1400, 1), tone(2000, 1)]))
        plan = self.plan()
        plan["duration_frames"] = 60
        first = plan["edits"][0]
        first.update(source=str(source), source_start=2, source_end=3, duration_frames=30, timeline_end_frame=30)
        second = {**first, "id": "shot-2", "source_start": 0, "source_end": 1,
                  "timeline_start_frame": 30, "timeline_end_frame": 60}
        plan["edits"].append(second)
        plan["audio_mix"]["source_audio"] = {"enabled": True}
        path, _ = mix_project_audio(plan, self.work/"order-cache")
        pcm = decode_audio(path)
        self.assertGreater(amplitude(pcm[:SR], 1400), .099)
        self.assertGreater(amplitude(pcm[SR:], 200), .099)

    def test_variable_speed_mapping_matches_action_anchor(self):
        edit = {"source_start": 0, "source_end": 2, "speed_points": [{"at": 0, "speed": 3}, {"at": .5, "speed": 1}, {"at": 1, "speed": 3}],
                "action_anchor": {"output_fraction": .6, "source_time": 1.4}}
        source = np.zeros((2*SR, 2), np.float32)
        source[round(1.4*SR)-20:round(1.4*SR)+20] = 1
        output = retime_source(source, edit, SR, "resample")
        self.assertLess(abs(np.argmax(output[:, 0])/SR-.6), .001)

    def test_pitch_preserving_ramp_retains_tone_frequency(self):
        edit = {"source_start": 0, "source_end": 2, "speed_points": [{"at": 0, "speed": 3}, {"at": .5, "speed": 1}, {"at": 1, "speed": 3}]}
        output = retime_source(tone(440, 2), edit, SR, "preserve")
        for start in (.2, .5, .7):
            self.assertGreater(amplitude(output[int(start*SR):int((start+.1)*SR)], 440), .06)

    def test_anchor_placements_follow_reorder_and_fail_ambiguity(self):
        plan = self.plan()
        plan["beat_frames"] = [0, 30, 60]
        plan["audio_mix"]["tracks"] = [{"id": "fx", "path": str(self.sfx), "role": "sfx", "anchor": {"type": "beat", "index": 2}}]
        self.assertEqual(expanded_tracks(plan)[0]["start"], 2)
        plan["beat_frames"][2] = 90
        self.assertEqual(expanded_tracks(plan)[0]["start"], 3)
        plan["audio_mix"]["tracks"][0]["anchor"] = {"type": "shot", "id": "missing"}
        with self.assertRaisesRegex(ValueError, "did not resolve"):
            expanded_tracks(plan)

    def test_explicit_silence_is_reported_unmeasurable(self):
        plan = self.plan()
        plan["audio_mix"].update(allow_silence=True, loudness={"enabled": True})
        path, report = mix_project_audio(plan, self.work/"silence-cache")
        measured = encoded_audio_report(path, report)
        self.assertTrue(report["silent"])
        self.assertFalse(measured["encoded_measurements"]["measurable"])
        self.assertIsNone(measured["loudness_within_tolerance"])

    def test_short_track_requires_explicit_loop_and_invalid_options_fail(self):
        plan = self.plan()
        track = {"path": str(self.voice), "duration": 4}
        plan["audio_mix"]["tracks"] = [track]
        with self.assertRaisesRegex(ValueError, "shorter"):
            mix_project_audio(plan, self.work/"invalid-cache")
        track["loop"] = True
        path, _ = mix_project_audio(plan, self.work/"loop-cache")
        self.assertAlmostEqual(amplitude(decode_audio(path), 900), .1, places=4)
        for key, value in (("gain_db", float("nan")), ("fade_in", -1), ("pitch_mode", "wrong")):
            with self.subTest(key=key):
                bad = copy.deepcopy(plan)
                bad["audio_mix"]["tracks"][0][key] = value
                with self.assertRaises(ValueError):
                    validate_audio_mix(bad)

    def test_two_pass_normalization_measures_final_aac(self):
        plan = self.plan()
        plan["audio_mix"].update(loudness={"enabled": True, "integrated": -18, "true_peak": -2},
                                 tracks=[{"path": str(self.music), "role": "music", "duration": 4, "gain_db": -18}])
        path, report = mix_project_audio(plan, self.work/"normalize-cache")
        encoded = self.work/"normalized.m4a"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-c:a", "aac", "-b:a", "192k", str(encoded)], check=True)
        final = encoded_audio_report(encoded, report)
        self.assertEqual(report["normalization"]["method"], "two_pass_loudnorm")
        self.assertAlmostEqual(final["encoded_measurements"]["integrated_lufs"], -18, delta=.5)
        self.assertLessEqual(final["encoded_measurements"]["true_peak_dbtp"], -1.5)
        self.assertTrue(final["loudness_within_tolerance"])

    def test_renderer_outputs_audible_source_and_encoded_report_without_music(self):
        from project_render import render_project
        plan = self.plan()
        plan["audio_mix"].update(source_audio={"enabled": True}, loudness={"enabled": True})
        result = render_project(plan, self.work/"rendered.mp4", cache_dir=self.work/"render-cache")
        self.assertEqual(result["frames"], 120)
        self.assertGreater(amplitude(decode_audio(result["path"])[SR:2*SR], 300), .05)
        report = json.loads(Path(result["audio_report"]).read_text())
        self.assertTrue(report["loudness_within_tolerance"])
        self.assertEqual(report["encoded_path"], result["path"])


if __name__ == "__main__":
    unittest.main()

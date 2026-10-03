"""Behavioral music/selection checks; synthetic mechanics are not human taste QA."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from editorial_commands import create_manifest, evaluate_manifest, register_editorial_commands, run_editorial_command
from editorial_feedback import (calibrate, candidate_features, candidate_key, evaluate_selection,
                                predict, rank_candidates, record_feedback)
from media_library import analyze_library
from music_structure import analyze_waveform, apply_overrides
from project_plan import build_plan, speed_bounds, validate_plan
from tests.test_project_plan import inputs


def pulse_fixture(seconds=12, sr=8000):
    signal = np.zeros(seconds*sr)
    beats = np.arange(.5, seconds, .5)
    for beat in beats:
        start = int(beat*sr)
        count = min(int(.08*sr), len(signal)-start)
        t = np.arange(count)/sr
        signal[start:start+count] += .8*np.sin(2*np.pi*440*t)*np.exp(-t/.02)
    return signal, sr, beats


class MusicalStructureTests(unittest.TestCase):
    def test_pulses_supported_but_constant_tone_not_forced_to_tracker_grid(self):
        signal, sr, beats = pulse_fixture()
        pulse = analyze_waveform(signal, sr, beats)
        ambient = analyze_waveform(.1*np.sin(2*np.pi*220*np.arange(len(signal))/sr), sr, beats)
        self.assertEqual(pulse["pacing"]["mode"], "beat_cut")
        self.assertGreater(pulse["beat_confidence"], .8)
        self.assertGreater(len(pulse["onsets"]), 15)
        self.assertEqual(ambient["pacing"]["mode"], "phrase_flow")
        self.assertLess(ambient["beat_confidence"], .2)
        self.assertTrue(pulse["phrases"])
        json.dumps(pulse, allow_nan=False)

    def test_silence_and_hard_stop_are_measured(self):
        sr = 8000
        signal = .4*np.sin(2*np.pi*220*np.arange(sr*5)/sr)
        signal[sr*3:] = 0
        result = analyze_waveform(signal, sr, [])
        stop = next(e for e in result["events"] if e["type"] == "hard_stop")
        self.assertAlmostEqual(stop["time"], 3, delta=.1)
        self.assertAlmostEqual(result["silence"][0]["start"], 3, delta=.05)
        silence = analyze_waveform(np.zeros(sr*2), sr, [])
        self.assertEqual(silence["silence"], [{"start": 0., "end": 2.}])
        self.assertEqual(silence["beat_confidence"], 0.)

    def test_manual_music_changes_are_bounded_and_audited(self):
        beatmap, library = inputs()
        corrected = apply_overrides(beatmap, {"reason": "Listened: accents are at these times", "beats": [0, 2, 4, 6],
                                              "pacing_mode": "phrase_flow",
                                              "phrases": [{"start": 0, "end": 3}, {"start": 3, "end": 8}]})
        self.assertEqual(corrected["beats"], [0., 2., 4., 6.])
        self.assertEqual(len(corrected["music_structure"]["overrides"]), 1)
        self.assertNotEqual(beatmap["beats"], corrected["beats"])
        plan = build_plan(corrected, library, duration=8)
        self.assertEqual(plan["music_structure"]["pacing"]["mode"], "phrase_flow")
        self.assertIn(90, [s["timeline_start_frame"] for s in plan["edits"]])
        for override in ({"beats": [1]}, {"reason": "x", "beats": [2, 1]},
                         {"reason": "x", "events": [{"type": "accent", "time": 99}]}):
            with self.assertRaises(ValueError):
                apply_overrides(beatmap, override)

    def test_no_beats_means_no_fabricated_beat_times_and_longer_holds(self):
        beatmap, library = inputs()
        beat_plan = build_plan(beatmap, library, duration=12, preset="car")
        beatmap["beats"] = []
        flow = build_plan(beatmap, library, duration=12, preset="car")
        self.assertEqual(flow["beat_frames"], [])
        self.assertEqual(flow["sections"][0]["name"], "flow")
        self.assertLess(len(flow["edits"]), len(beat_plan["edits"]))
        self.assertTrue(all(s["duration_frames"] >= 60 for s in flow["edits"]))


class AccelerationTests(unittest.TestCase):
    def test_all_presets_allocate_acceleration_and_never_repeat(self):
        for preset in ("cinematic", "car", "gaming", "product"):
            beatmap, library = inputs()
            plan = build_plan(beatmap, library, duration=25, preset=preset)
            accelerated = [e for e in plan["edits"] if len(e["speed_points"]) > 2]
            self.assertTrue(accelerated, preset)
            for shot in accelerated:
                self.assertGreater(shot["average_speed"], 1)
                low, high = speed_bounds(shot, shot["duration_frames"]/30)
                self.assertGreaterEqual(low, 1-1e-7)
                self.assertGreater(high, low)
                self.assertLessEqual(high, 4+1e-7)
            validate_plan(plan)  # Includes complete range overlap check.

    def test_no_surplus_cannot_be_spent_on_ramps(self):
        beatmap, library = inputs((12,))
        plan = build_plan(beatmap, library, duration=12, preset="car")
        self.assertAlmostEqual(sum(e["source_end"]-e["source_start"] for e in plan["edits"]), 12)
        self.assertTrue(all(len(e["speed_points"]) == 2 for e in plan["edits"]))
        self.assertEqual(plan["duration_frames"], 360)

    def test_near_capacity_and_action_fragmentation_do_not_exhaust_source(self):
        for lengths in ((6.13, 6.21), (4.3, 4.4, 4.1), (12.8,)):
            beatmap, library = inputs(lengths)
            library["clips"][0]["action_time"] = lengths[0]*.55
            plan = build_plan(beatmap, library, duration=12, preset="gaming")
            self.assertEqual(plan["duration_frames"], 360)
            validate_plan(plan)


class EditorialTests(unittest.TestCase):
    def test_preferences_query_and_rejection_change_actual_plan(self):
        beatmap, library = inputs()
        library["clips"][1].update(tags=["night", "drift"], notes="red car", semantic_source="annotation")
        basic = build_plan(beatmap, library, duration=5)
        preferred = build_plan(beatmap, library, duration=5, query="night drift", preferences={"tag_weights": {"night": 5}})
        self.assertNotEqual(basic["edits"][0]["clip_id"], preferred["edits"][0]["clip_id"])
        self.assertEqual(preferred["edits"][0]["clip_id"], "c1")
        details = preferred["edits"][0]["selection"]
        self.assertEqual(details["matched_query_terms"], ["drift", "night"])
        self.assertGreater(details["components"]["query_match"], 0)
        self.assertEqual(len(details["alternatives"]), 3)
        self.assertEqual(details["evidence"]["observation_origin"], "annotation")
        profile = record_feedback({}, library["clips"][1], "reject", "Subject obscured")
        rejected = build_plan(beatmap, library, duration=5, query="night drift", preferences=profile)
        self.assertNotIn("c1", [s["clip_id"] for s in rejected["edits"]])
        profile = record_feedback(profile, library["clips"][1], "clear", "Corrected crop reviewed")
        self.assertEqual(len(profile["events"]), 2)
        self.assertEqual(profile["events"][-1]["previous_event"], profile["events"][0]["id"])
        self.assertEqual(build_plan(beatmap, library, duration=5, query="night drift", preferences=profile)["edits"][0]["clip_id"], "c1")

    def test_feedback_identity_survives_id_change_but_not_changed_source(self):
        _, library = inputs()
        clip = library["clips"][0]
        clip["source_sha256"] = "one"
        profile = record_feedback({}, clip, "reject", "Poor moment")
        changed = deepcopy(clip)
        changed["id"] = "new-id"
        self.assertTrue(rank_candidates({"clips": [changed]}, profile)[0]["excluded"])
        changed["source_sha256"] = "two"
        self.assertFalse(rank_candidates({"clips": [changed]}, profile)[0]["excluded"])

    def test_calibration_holds_out_entire_sources_and_model_affects_ranking(self):
        profile = {}
        for index in range(8):
            for high in (False, True):
                clip = {"id": f"{index}-{high}", "source": f"source-{index}", "asset_id": str(index),
                        "start": 0 if high else 2, "end": 1 if high else 3,
                        "quality": 1. if high else 0., "tags": ["clear"] if high else ["obscured"]}
                profile = record_feedback(profile, clip, "accept" if high else "reject", "Reviewed sample")
        report = calibrate(profile)
        self.assertEqual(report["status"], "evaluated")
        self.assertFalse(set(report["model"]["training_groups"]) & set(report["split"]["holdout_groups"]))
        self.assertFalse(set(report["model"]["training_candidate_keys"]) & set(report["split"]["holdout_candidate_keys"]))
        self.assertGreater(report["metrics"]["accuracy"], report["baseline_metrics"]["accuracy"])
        good = {"id": "good", "quality": 1, "tags": ["clear"]}
        poor = {"id": "poor", "quality": 0, "tags": ["obscured"]}
        self.assertGreater(predict(report["model"], candidate_features(good)), predict(report["model"], candidate_features(poor)))
        self.assertEqual(calibrate({})["status"], "insufficient_data")

    def test_selection_evaluation_reports_missed_false_and_unknown(self):
        plan = {"edits": [{"id": "s1", "clip_id": "c1", "asset_id": "a", "source_start": 1, "source_end": 3},
                           {"id": "s2", "clip_id": "c2", "asset_id": "b", "source_start": 0, "source_end": 2},
                           {"id": "s3", "clip_id": "c3", "asset_id": "c", "source_start": 0, "source_end": 1}]}
        report = evaluate_selection(plan, [{"clip_id": "c1", "decision": "accept"},
                                           {"clip_id": "c2", "decision": "reject"},
                                           {"asset_id": "a", "start": 6, "end": 8, "decision": "accept"}])
        self.assertEqual(report["precision"], .5)
        self.assertEqual(report["recall"], .5)
        self.assertEqual(report["unreviewed_shots"], ["s3"])

    def test_selection_range_coverage_unions_fragments_and_does_not_count_repeats_twice(self):
        plan = {"edits": [{"id": "a", "asset_id": "source", "source_start": 0, "source_end": .4},
                          {"id": "b", "asset_id": "source", "source_start": .4, "source_end": .8},
                          {"id": "repeat", "asset_id": "source", "source_start": 0, "source_end": .4}]}
        labels = [{"asset_id": "source", "start": 0, "end": 1, "decision": "accept"}]
        result = evaluate_selection(plan, labels)
        self.assertEqual(result["recall"], 1.)
        self.assertAlmostEqual(result["true_selections"][0]["source_range_coverage"], .8)
        self.assertEqual(evaluate_selection(plan, labels, .9)["recall"], 0.)

    def test_public_feedback_command_persists_audit_and_candidate_result(self):
        parser = argparse.ArgumentParser()
        register_editorial_commands(parser.add_subparsers(dest="command"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, library = inputs()
            source = root / "library.json"
            source.write_text(json.dumps(library), encoding="utf-8")
            profile = root / "preferences.json"
            run_editorial_command(parser.parse_args(["feedback", str(source), "--profile", str(profile), "--clip", "c0",
                                                     "--decision", "reject", "--reason", "Reviewed blurred shot"]))
            result = run_editorial_command(parser.parse_args(["candidates", str(source), "--preferences", str(profile)]))
            self.assertTrue(next(c for c in result["candidates"] if c["clip_id"] == "c0")["excluded"])
            self.assertEqual(len(json.loads(profile.read_text())["events"]), 1)


class AnalysisCacheAndManifestTests(unittest.TestCase):
    def test_cache_avoids_decode_but_reapplies_annotations_and_invalidates_changed_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "image.png"
            Image.new("RGB", (100, 200), "red").save(source)
            cache = root / "cache"
            first = analyze_library([source], root/"work-one", cache_dir=cache)
            annotations = root/"annotations.json"
            annotations.write_text(json.dumps({first["clips"][0]["id"]: {"tags": ["red"]}}))
            with patch("media_library._clips_for_asset", side_effect=AssertionError("Cache should avoid decoding")):
                second = analyze_library([source], root/"work-two", annotations, cache_dir=cache)
            self.assertEqual(second["analysis_cache"]["hits"], 1)
            self.assertEqual(second["clips"][0]["tags"], ["red"])
            clean = analyze_library([source], root/"work-three", cache_dir=cache)
            self.assertEqual(clean["clips"][0]["tags"], [])
            old_hash = clean["assets"][0]["sha256"]
            Image.new("RGB", (100, 200), "blue").save(source)
            changed = analyze_library([source], root/"work-four", cache_dir=cache)
            self.assertEqual(changed["analysis_cache"]["misses"], 1)
            self.assertNotEqual(changed["assets"][0]["sha256"], old_hash)
            Path(changed["clips"][0]["thumb"]).write_bytes(b"broken thumbnail")
            repaired = analyze_library([source], root/"work-five", cache_dir=cache)
            self.assertEqual(repaired["analysis_cache"]["misses"], 1)
            Image.open(repaired["clips"][0]["thumb"]).verify()

    def test_manifest_never_calls_missing_or_unreviewed_real_media_passed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/"source.mp4"
            source.write_bytes(b"fixture existence only")
            project = root/"project.json"
            project.write_text(json.dumps({"output": {"fps": 30}, "edits": [], "assets": [{"path": str(source)}]}))
            manifest = create_manifest([project])
            report = evaluate_manifest(manifest)
            self.assertEqual(report["cases"][0]["status"], "not_reviewed")
            manifest["cases"][0]["review"] = {"reviewer": "fixture-test", "observations": {key: "pass" for key in manifest["cases"][0]["required_checks"]}}
            source.write_bytes(b"different content")
            self.assertEqual(evaluate_manifest(manifest)["cases"][0]["status"], "stale")
            source.unlink()
            self.assertEqual(evaluate_manifest(manifest)["cases"][0]["status"], "missing_materials")


if __name__ == "__main__":
    unittest.main()

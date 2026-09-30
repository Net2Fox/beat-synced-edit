"""Behavioral coverage for exact duration, consent, musical structure and selection."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edit_presets import get_preset, list_presets
from project_plan import build_plan, validate_plan


def inputs(lengths=(20, 20, 20, 20), image=False):
    base = Path(__file__).resolve().parent
    beatmap = {"file": str(base / "music.wav"), "duration": 40,
               "tempo": 120, "beats": [n * .5 for n in range(81)],
               "energy_curve": [{"time": n * .5, "energy": .2 if n < 20 else .9} for n in range(81)]}
    assets, clips = [], []
    for i, duration in enumerate(lengths):
        path = str(base / f"source-{i}.{'jpg' if image else 'mp4'}")
        assets.append({"id": f"a{i}", "path": path, "kind": "image" if image else "video", "duration": duration})
        clips.append({"id": f"c{i}", "asset_id": f"a{i}", "source": path,
                      "kind": "image" if image else "video", "start": 0, "end": duration,
                      "duration": duration, "energy": .5, "tags": [], "shot_type": "unknown"})
    return beatmap, {"assets": assets, "clips": clips}


class ExactDurationTests(unittest.TestCase):
    def test_frame_exact_not_rounded_to_a_beat(self):
        beatmap, library = inputs()
        plan = build_plan(beatmap, library, duration=7.43, fps=30)
        self.assertEqual(plan["duration_frames"], 223)
        self.assertEqual(sum(shot["duration_frames"] for shot in plan["edits"]), 223)
        self.assertEqual(plan["edits"][-1]["timeline_end_frame"], 223)
        self.assertEqual(validate_plan(plan), plan)

    def test_extend_uses_unused_video_without_repeating(self):
        beatmap, library = inputs((3, 3))
        plan = build_plan(beatmap, library, duration=10, fps=30)
        self.assertEqual(plan["duration_frames"], 300)
        self.assertTrue(plan["diagnostics"])
        consumed = sum(shot["source_end"] - shot["source_start"] for shot in plan["edits"])
        self.assertLessEqual(consumed, 6.000001)
        self.assertGreaterEqual(consumed, 5.0)
        for i, shot in enumerate(plan["edits"]):
            for previous in plan["edits"][:i]:
                if shot["source"] == previous["source"]:
                    overlap = min(shot["source_end"], previous["source_end"]) - max(shot["source_start"], previous["source_start"])
                    self.assertLessEqual(overlap, .000001)

    def test_exhaustion_is_actionable_not_a_short_export(self):
        beatmap, library = inputs((1,))
        with self.assertRaisesRegex(ValueError, "Add footage/photos"):
            build_plan(beatmap, library, duration=10)
        with self.assertRaisesRegex(ValueError, "requires allow_repeats"):
            build_plan(beatmap, library, duration=10, shortage="repeat")

    def test_explicit_repeats_cover_exact_length(self):
        beatmap, library = inputs((1,))
        plan = build_plan(beatmap, library, duration=10, allow_repeats=True, shortage="repeat")
        self.assertEqual(plan["edits"][-1]["timeline_end_frame"], 300)
        self.assertGreater(sum(shot["source_end"] - shot["source_start"] for shot in plan["edits"]), 1)

    def test_one_photo_is_a_continuous_hold_across_sections(self):
        beatmap, library = inputs((0,), image=True)
        plan = build_plan(beatmap, library, duration=10)
        self.assertEqual(plan["duration_frames"], 300)
        self.assertTrue(all(shot["kind"] == "image" for shot in plan["edits"]))
        self.assertEqual(len(plan["edits"]), 4)

    def test_mixed_photo_and_short_video_reserve_enough_hold_time(self):
        beatmap, library = inputs((1,))
        _, photos = inputs((0,), image=True)
        photos["assets"][0]["id"] = "still"
        photos["clips"][0].update(id="photo", asset_id="still", quality=1)
        library["assets"] += photos["assets"]
        library["clips"] += photos["clips"]
        plan = build_plan(beatmap, library, duration=15, preset="car")
        self.assertEqual(plan["duration_frames"], 450)
        self.assertTrue(any(e["kind"] == "image" for e in plan["edits"]))
        self.assertTrue(any(e["kind"] == "video" for e in plan["edits"]))

    def test_fractional_scene_lengths_still_cover_the_complete_output(self):
        beatmap, library = inputs((9.819311630365577, 4.297129940790273, 2.15837673339859, .6874612854113502))
        plan = build_plan(beatmap, library, duration=17.18652707638857, preset="car")
        self.assertEqual(sum(e["duration_frames"] for e in plan["edits"]), 516)

    def test_overlapping_analyzed_clips_do_not_inflate_available_source(self):
        beatmap, library = inputs((2,))
        duplicate = deepcopy(library["clips"][0])
        duplicate["id"] = "overlapping-analysis"
        library["clips"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "Only 2.000s"):
            build_plan(beatmap, library, duration=6)

    def test_short_music_and_selected_range_fail_early(self):
        beatmap, library = inputs()
        with self.assertRaisesRegex(ValueError, "exceeds music"):
            build_plan(beatmap, library, duration=41)
        with self.assertRaisesRegex(ValueError, "audio range"):
            build_plan(beatmap, library, duration=10, audio_start=35)


class MusicalAndSemanticTests(unittest.TestCase):
    def test_energy_rise_selects_drop_and_manual_sections_override_it(self):
        beatmap, library = inputs()
        plan = build_plan(beatmap, library, duration=20)
        drop = next(section for section in plan["sections"] if section["name"] == "drop")
        self.assertAlmostEqual(drop["start"], 10, delta=.5)
        self.assertEqual(drop["method"], "energy-rise-and-beats")
        manual = [{"name": "intro", "start": 0, "end": 2},
                  {"name": "build", "start": 2, "end": 4},
                  {"name": "drop", "start": 4, "end": 9},
                  {"name": "outro", "start": 9, "end": 10}]
        changed = build_plan(beatmap, library, duration=10, sections=manual)
        self.assertEqual([s["start"] for s in changed["sections"]], [0, 2, 4, 9])
        manual[1]["start"] = 3
        with self.assertRaisesRegex(ValueError, "contiguously"):
            build_plan(beatmap, library, duration=10, sections=manual)

    def test_four_presets_change_pace_color_and_effects(self):
        beatmap, library = inputs((100, 100, 100, 100))
        plans = {name: build_plan(beatmap, library, duration=20, preset=name) for name in list_presets()}
        self.assertGreater(len(plans["car"]["edits"]), len(plans["cinematic"]["edits"]))
        self.assertEqual(len({p["edits"][0]["effects"]["grade"] for p in plans.values()}), 4)
        self.assertGreater(max(e["effects"]["flash"] for e in plans["car"]["edits"]), max(e["effects"]["flash"] for e in plans["product"]["edits"]))
        recipe = get_preset("car")
        recipe["effects"]["zoom"] = 9
        self.assertNotEqual(get_preset("car")["effects"]["zoom"], 9)

    def test_per_section_pacing_override_makes_middle_faster(self):
        beatmap, library = inputs()
        sections = [{"name": "intro", "start": 0, "end": 2},
                    {"name": "build", "start": 2, "end": 3},
                    {"name": "drop", "start": 3, "end": 5},
                    {"name": "outro", "start": 5, "end": 6}]
        plan = build_plan(beatmap, library, duration=6, preset="product", sections=sections,
                          section_stride={"drop": 1}, min_shot=.25)
        intro = [e["duration_frames"] for e in plan["edits"] if e["section"] == "intro"]
        drop = [e["duration_frames"] for e in plan["edits"] if e["section"] == "drop"]
        self.assertLess(max(drop), min(intro))
        self.assertEqual(len(drop), 4)

    def test_semantic_tags_shot_alternation_and_duplicate_penalty(self):
        beatmap, library = inputs((20, 20, 20, 20))
        for i, clip in enumerate(library["clips"]):
            clip["tags"] = ["car"] if i < 3 else ["food"]
            clip["shot_type"] = ["wide", "detail", "wide", "detail"][i]
            clip["visual_hash"] = ["0000000000000000", "ffffffffffffffff", "0000000000000000", "aaaaaaaaaaaaaaaa"][i]
        plan = build_plan(beatmap, library, duration=8, preset="car", tags=["car"])
        self.assertEqual(plan["edits"][0]["clip_id"], "c0")
        self.assertEqual(plan["edits"][1]["clip_id"], "c1")
        self.assertNotEqual(plan["edits"][0]["shot_type"], plan["edits"][1]["shot_type"])

    def test_excluded_annotation_never_selected_and_quality_breaks_ties(self):
        beatmap, library = inputs((20, 20, 20))
        library["clips"][0].update(exclude=True, quality=1)
        library["clips"][1]["quality"] = .1
        library["clips"][2]["quality"] = 1
        plan = build_plan(beatmap, library, duration=4)
        self.assertEqual(plan["edits"][0]["clip_id"], "c2")
        self.assertNotIn("c0", {shot["clip_id"] for shot in plan["edits"]})

    def test_action_anchor_lands_on_an_interior_beat(self):
        beatmap, library = inputs((20,))
        library["clips"][0]["action_time"] = 10
        manual = [{"name": "drop", "start": 0, "end": 4}]
        plan = build_plan(beatmap, library, duration=4, preset="car", sections=manual, beat_stride=4)
        anchors = [shot for shot in plan["edits"] if "action_anchor" in shot]
        self.assertTrue(anchors)
        shot = anchors[0]
        anchor_frame = shot["timeline_start_frame"] + shot["duration_frames"] * shot["action_anchor"]["output_fraction"]
        self.assertIn(round(anchor_frame), plan["beat_frames"])
        self.assertEqual(shot["action_anchor"]["source_time"], 10)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        beatmap, library = inputs()
        self.plan = build_plan(beatmap, library, duration=5)

    def test_nonfinite_source_is_rejected(self):
        self.plan["edits"][0]["source_end"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_plan(self.plan)

    def test_source_bounds_and_timeline_gaps_are_rejected(self):
        plan = deepcopy(self.plan)
        plan["edits"][0]["source_end"] = 1000
        with self.assertRaisesRegex(ValueError, "clip bounds|asset duration"):
            validate_plan(plan)
        self.plan["edits"][1]["timeline_start_frame"] += 1
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_plan(self.plan)

    def test_source_mismatch_bad_bbox_and_effects_are_rejected(self):
        changes = [("source", str(Path(__file__).resolve())),
                   ("reframe", {"mode": "manual", "subject": [.9, 0, .5, .5]}),
                   ("effects", {"flash": 2}),
                   ("speed_points", [{"at": 0, "speed": 1}, {"at": .5, "speed": 0}])]
        for key, value in changes:
            with self.subTest(key=key):
                plan = deepcopy(self.plan)
                plan["edits"][0][key] = value
                with self.assertRaises(ValueError):
                    validate_plan(plan)

    def test_subject_origin_and_fps_must_be_renderable(self):
        self.plan["edits"][0]["reframe"] = {"mode": "auto", "subject": [0, 0, .2, .2], "subject_start": 999}
        with self.assertRaisesRegex(ValueError, "subject_start"):
            validate_plan(self.plan)
        beatmap, library = inputs()
        with self.assertRaisesRegex(ValueError, "120"):
            build_plan(beatmap, library, duration=1, fps=121)


if __name__ == "__main__":
    unittest.main()

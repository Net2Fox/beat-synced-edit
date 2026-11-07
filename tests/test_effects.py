"""Per-shot edit effects, transitions, presets and the environment entry points."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

import _paths  # noqa: F401  (makes the skill's scripts importable)
ROOT = _paths.SCRIPTS
from edit_effects import (ACCENT_EFFECTS, EFFECTS, GRADES, active_effects, catalog, flash_bursts,
                          parse_effect_override, thin_flashes, transition_effects, validate_effects)
from edit_presets import PRESETS
from effects_render import apply_frame_effects, pulse_envelope, zoom_amount
from project_workspace import apply_revisions


def pattern(height=64, width=48):
    rng = np.random.default_rng(5)
    frame = rng.integers(30, 220, (height, width, 3), dtype=np.uint8)
    frame[height//3:2*height//3, width//3:2*width//3] = 250
    return frame


def minimal_plan(source, shots=3, frames=10):
    edits = []
    for index in range(shots):
        edits.append({"id": f"shot-{index+1:03d}", "source": str(source), "asset_id": "a", "kind": "image",
                      "source_start": 0.0, "source_end": 0.0, "duration_frames": frames,
                      "timeline_start_frame": index*frames, "timeline_end_frame": (index+1)*frames,
                      "section": "drop" if index else "intro", "effects": {"grade": "none"},
                      "speed_points": [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}], "reframe": {"mode": "center"}})
    return {"schema_version": 2, "audio": {"path": str(source), "start": 0, "duration": 10},
            "output": {"width": 48, "height": 64, "fps": 30}, "duration_frames": shots*frames,
            "duration": shots*frames/30, "edits": edits, "policies": {},
            "assets": [{"id": "a", "path": str(source), "kind": "image"}],
            "sections": [{"name": "intro", "start_frame": 0, "end_frame": frames},
                         {"name": "drop", "start_frame": frames, "end_frame": shots*frames}]}


class CatalogTests(unittest.TestCase):
    def test_validation_rejects_unknown_names_ranges_and_grades(self):
        validate_effects({"rgb_split": .5, "letterbox": .12, "grade": "teal_orange", "zoom": 1.2})
        for bad in ({"sparkle": 1}, {"glitch": 1.5}, {"zoom": .5}, {"letterbox": .5},
                    {"grade": "sepia"}, {"flash": True}, {"grain": float("nan")}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_effects(bad)

    def test_command_line_overrides_are_typed(self):
        self.assertEqual(parse_effect_override("rgb_split=0.6"), ("rgb_split", .6))
        self.assertEqual(parse_effect_override("grade=mono"), ("grade", "mono"))
        for bad in ("rgb_split", "unknown=1", "grain=lots", "grain=2"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_effect_override(bad)

    def test_transitions_clear_previous_cut_effects(self):
        outgoing, incoming = transition_effects("whip", .5)
        self.assertEqual((outgoing["whip_out"], incoming["whip_in"]), (.5, .5))
        self.assertTrue(all(incoming[name] == 0 for name in ACCENT_EFFECTS))
        _, zoom = transition_effects("zoom", 1)
        self.assertAlmostEqual(zoom["zoom"], 1.3)
        out_cut, in_cut = transition_effects("cut")
        self.assertEqual(out_cut, {"whip_out": 0})
        self.assertTrue(all(value == 0 for value in in_cut.values()))
        with self.assertRaises(ValueError):
            transition_effects("spin")

    def test_catalog_and_presets_are_consistent(self):
        described = catalog()
        self.assertEqual(set(described["effects"]), set(EFFECTS))
        self.assertEqual(described["grades"], list(GRADES))
        for name, recipe in PRESETS.items():
            with self.subTest(preset=name):
                validate_effects(recipe["effects"])
                self.assertIn(recipe["effects"].get("grade", "none"), GRADES)


class PixelTests(unittest.TestCase):
    def setUp(self):
        self.frame = pattern()

    def apply(self, effects, index=0, count=30):
        return apply_frame_effects(self.frame.copy(), effects, index, count, 30)

    def test_neutral_values_leave_pixels_untouched(self):
        neutral = {name: spec[3] for name, spec in EFFECTS.items() if name != "zoom"}
        self.assertTrue(np.array_equal(self.apply(neutral), self.frame))
        self.assertTrue(np.array_equal(self.apply({}), self.frame))

    def test_accents_hit_the_cut_and_then_clear(self):
        for name in ACCENT_EFFECTS:
            with self.subTest(effect=name):
                hit, later = self.apply({name: 1}, 0), self.apply({name: 1}, 15)
                if name == "blur_in":
                    self.assertLess(hit.std(), self.frame.std())
                else:
                    self.assertFalse(np.array_equal(hit, self.frame))
                self.assertTrue(np.array_equal(later, self.frame))
        self.assertEqual(self.apply({"dip": 1}, 0).max(), 0)
        inverted = self.apply({"invert": 1}, 0).astype(int)
        self.assertLessEqual(np.abs(inverted - (255 - self.frame.astype(int))).max(), 1)
        split = self.apply({"rgb_split": 1}, 0)
        self.assertTrue(np.array_equal(split[:, :, 1], self.frame[:, :, 1]), "green stays registered")

    def test_whips_shape_only_the_shot_edges(self):
        self.assertFalse(np.array_equal(self.apply({"whip_in": 1}, 0), self.frame))
        self.assertTrue(np.array_equal(self.apply({"whip_in": 1}, 20), self.frame))
        self.assertFalse(np.array_equal(self.apply({"whip_out": 1}, 29), self.frame))
        self.assertTrue(np.array_equal(self.apply({"whip_out": 1}, 5), self.frame))

    def test_looks_apply_on_every_frame(self):
        boxed = self.apply({"letterbox": .1}, 12)
        self.assertEqual(boxed[:6].max(), 0)
        self.assertEqual(boxed[-6:].max(), 0)
        self.assertTrue(np.array_equal(boxed[8:-8], self.frame[8:-8]))
        flat = np.full((64, 48, 3), 180, np.uint8)
        vignette = apply_frame_effects(flat, {"vignette": 1}, 9, 30, 30)
        self.assertLess(int(vignette[0, 0, 0]), int(vignette[32, 24, 0]))
        grain_a, grain_b = self.apply({"grain": 1}, 4), self.apply({"grain": 1}, 4)
        self.assertTrue(np.array_equal(grain_a, grain_b), "grain is deterministic for the cache")
        self.assertFalse(np.array_equal(grain_a, self.apply({"grain": 1}, 5)))
        self.assertGreater(self.apply({"glow": 1}, 9).astype(int).sum(), self.frame.astype(int).sum())
        mono = self.apply({"grade": "mono"}, 3)
        self.assertTrue(np.array_equal(mono[..., 0], mono[..., 1]) and np.array_equal(mono[..., 1], mono[..., 2]))
        for grade in GRADES:
            if grade not in ("none", "neutral"):
                self.assertFalse(np.array_equal(self.apply({"grade": grade}, 3), self.frame), grade)

    def test_beat_pulses_bump_zoom_on_each_beat(self):
        effects = {"pulse": 1, "zoom": 1}
        beats = [0, 10]
        self.assertGreater(zoom_amount(effects, "video", 10, 30, 30, beats), zoom_amount(effects, "video", 9, 30, 30, beats))
        self.assertEqual(zoom_amount(effects, "video", 20, 30, 30, beats), 1)
        self.assertEqual(pulse_envelope(3, [], 30), 0)
        self.assertEqual(zoom_amount(effects, "video", 10, 30, 30, ()), 1, "no beats, no pulse")


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name)/"still.png"
        from PIL import Image
        Image.fromarray(pattern()).save(self.image)
        self.plan = minimal_plan(self.image)

    def test_effects_reset_and_validation(self):
        plan = apply_revisions(self.plan, [{"op": "effects", "all": True, "values": {"glitch": .5, "grade": "mono"}}])
        self.assertTrue(all(e["effects"]["glitch"] == .5 for e in plan["edits"]))
        plan = apply_revisions(plan, [{"op": "effects", "shot": 2, "reset": True}])
        self.assertEqual(plan["edits"][1]["effects"], {})
        with self.assertRaisesRegex(ValueError, "unknown effects"):
            apply_revisions(plan, [{"op": "effects", "all": True, "values": {"sparkle": 1}}])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            apply_revisions(plan, [{"op": "effects", "all": True}])

    def test_transition_targets_cuts(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "whip", "strength": .8}])
        self.assertEqual(plan["edits"][0]["effects"]["whip_out"], .8)
        self.assertEqual(plan["edits"][1]["effects"]["whip_in"], .8)
        plan = apply_revisions(plan, [{"op": "transition", "after": "shot-001", "type": "flash"}])
        self.assertEqual((plan["edits"][0]["effects"].get("whip_out", 0), plan["edits"][1]["effects"].get("whip_in", 0)), (0, 0))
        self.assertEqual(plan["edits"][1]["effects"]["flash"], 1)
        plan = apply_revisions(plan, [{"op": "transition", "all": True, "type": "glitch", "strength": .5}])
        self.assertEqual([e["effects"].get("glitch", 0) for e in plan["edits"]], [0, .5, .5])
        plan = apply_revisions(plan, [{"op": "transition", "section": "drop", "type": "cut"}])
        self.assertTrue(all(e["effects"].get("glitch", 0) == 0 for e in plan["edits"]))
        with self.assertRaisesRegex(ValueError, "final shot"):
            apply_revisions(plan, [{"op": "transition", "after": 3, "type": "dip"}])
        with self.assertRaisesRegex(ValueError, "exactly one of"):
            apply_revisions(plan, [{"op": "transition", "type": "dip"}])

    def test_grade_none_in_a_revision_removes_looks_unless_set_with_it(self):
        plan = apply_revisions(self.plan, [{"op": "effects", "all": True, "values": {"vignette": .4, "grain": .2, "grade": "moody"}}])
        natural = apply_revisions(plan, [{"op": "effects", "all": True, "values": {"grade": "none"}}])
        self.assertTrue(all("vignette" not in e["effects"] and "grain" not in e["effects"] for e in natural["edits"]))
        kept = apply_revisions(plan, [{"op": "effects", "all": True, "values": {"grade": "none", "grain": .1}}])
        self.assertTrue(all(e["effects"].get("grain") == .1 and "vignette" not in e["effects"] for e in kept["edits"]))
        neutral = apply_revisions(plan, [{"op": "effects", "all": True, "values": {"grade": "neutral"}}])
        self.assertTrue(all(e["effects"]["vignette"] == .4 for e in neutral["edits"]))

    def test_review_page_removes_every_accent_transition_and_pulse(self):
        from project_workspace import review_html
        page = Path(review_html(self.plan, str(Path(self.temp.name)/"preview.mp4"), str(Path(self.temp.name)/"preview.html")))
        text = page.read_text(encoding="utf-8")
        for name in ("flash", "glitch", "whip_in", "whip_out", "pulse", "shake"):
            self.assertIn(f'"{name}": 0', text)
        # Transitions go first, so a zoom transition's punch and its markers go too.
        self.assertIn("add({op:'transition',all:true,type:'cut'});add({op:'effects'", text)

    def test_transition_requests_are_validated(self):
        bad = [({"op": "transition", "after": 1}, "requires type"),
               ({"op": "transition", "after": 1, "all": True, "type": "dip"}, "exactly one of"),
               ({"op": "transition", "after": 1, "type": "dip", "strenght": .5}, "Unknown transition fields"),
               ({"op": "transition", "section": "chorus", "type": "dip"}, "section must be one of"),
               ({"op": "transition", "all": "yes", "type": "dip"}, "all must be true"),
               ({"op": "transition", "after": 1, "type": "swirl"}, "Unknown transition")]
        for operation, message in bad:
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, message):
                apply_revisions(self.plan, [operation])

    def test_replacing_a_zoom_transition_restores_the_shot_zoom(self):
        self.plan["assets"].append({"id": "v", "path": str(self.image), "kind": "video"})
        self.plan["edits"][1].update(kind="video", asset_id="v", source_end=1.0)
        self.plan["edits"][1]["effects"]["zoom"] = 1.06
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "zoom"}])
        self.assertAlmostEqual(plan["edits"][1]["effects"]["zoom"], 1.3)
        for kind in ("cut", "flash"):
            with self.subTest(kind=kind):
                changed = apply_revisions(plan, [{"op": "transition", "after": 1, "type": kind}])
                self.assertAlmostEqual(changed["edits"][1]["effects"]["zoom"], 1.06)
        # A zoom the user sets after the transition is the shot's own zoom from then on.
        explicit = apply_revisions(plan, [{"op": "effects", "shot": 2, "values": {"zoom": 1.5}}])
        for operations in ([{"op": "transition", "after": 1, "type": "cut"}],
                           [{"op": "transition", "after": 1, "type": "flash"}],
                           [{"op": "reorder", "order": ["shot-002", "shot-001", "shot-003"]}]):
            with self.subTest(operations=operations):
                changed = apply_revisions(explicit, operations)
                shot = next(e for e in changed["edits"] if e["id"] == "shot-002")
                self.assertAlmostEqual(shot["effects"]["zoom"], 1.5)

    def test_a_shot_that_becomes_a_still_loses_the_zoom_punch(self):
        self.plan["assets"].append({"id": "v", "path": str(self.image), "kind": "video"})
        self.plan["edits"][1].update(kind="video", asset_id="v", source_end=1.0)
        self.plan["clips"] = [{"id": "still", "asset_id": "a", "source": str(self.image), "kind": "image", "start": 0.0, "end": 0.0}]
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "zoom"},
                                           {"op": "replace", "shot": 2, "clip_id": "still"}])
        shot = plan["edits"][1]
        self.assertEqual((shot["kind"], shot["effects"].get("zoom", 1.0)), ("image", 1.0))
        self.assertAlmostEqual(shot["effects"]["blur_in"], .4)
        plan["clips"].append({"id": "moving", "asset_id": "v", "source": str(self.image), "kind": "video", "start": 0.0, "end": 1.0})
        back = apply_revisions(plan, [{"op": "replace", "shot": 2, "clip_id": "moving"}])
        self.assertAlmostEqual(back["edits"][1]["effects"]["zoom"], 1.3)  # the punch returns with motion

    def test_zoom_transition_into_a_still_only_defocuses(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "zoom"}])
        shot = plan["edits"][1]
        self.assertNotIn("zoom", shot["effects"])
        self.assertAlmostEqual(shot["effects"]["blur_in"], .4)
        cut = apply_revisions(plan, [{"op": "transition", "after": 1, "type": "cut"}])
        self.assertEqual(cut["edits"][1]["effects"].get("zoom", 1.0), 1.0)

    def test_reset_removes_the_whole_transition_on_its_cuts(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "whip", "strength": .8}])
        incoming = apply_revisions(plan, [{"op": "effects", "shot": 2, "reset": True}])
        self.assertEqual(incoming["edits"][0]["effects"].get("whip_out", 0), 0)
        self.assertNotIn("transition_out", incoming["edits"][0])
        outgoing = apply_revisions(plan, [{"op": "effects", "shot": 1, "reset": True}])
        self.assertEqual(outgoing["edits"][1]["effects"].get("whip_in", 0), 0)
        self.assertNotIn("transition_in", outgoing["edits"][1])

    def test_transition_section_accepts_the_projects_own_sections(self):
        for shot in self.plan["edits"]:
            shot["section"] = "flow"
        self.plan["sections"] = [{"name": "flow", "start_frame": 0, "end_frame": self.plan["duration_frames"]}]
        plan = apply_revisions(self.plan, [{"op": "transition", "section": "flow", "type": "blur"}])
        self.assertEqual([e["effects"].get("blur_in", 0) for e in plan["edits"]], [0, 1, 1])
        with self.assertRaisesRegex(ValueError, "lead into flow"):
            apply_revisions(self.plan, [{"op": "transition", "section": "drop", "type": "blur"}])

    def test_effect_errors_name_the_shot(self):
        from project_plan import validate_plan
        self.plan["edits"][2]["effects"]["glitch"] = 2
        with self.assertRaisesRegex(ValueError, "shot-003 effects: effect glitch must be between 0 and 1"):
            validate_plan(self.plan)

    def test_transitions_do_not_write_neutral_values(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "all": True, "type": "cut"}])
        self.assertEqual([e["effects"] for e in plan["edits"]], [{"grade": "none"}] * 3)
        self.assertEqual(active_effects({"flash": 0, "zoom": 1.0, "grade": "neutral", "glitch": .5}), {"glitch": .5})

    def test_reorder_keeps_only_transitions_whose_shots_stay_adjacent(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "all": True, "type": "whip"}])
        plan = apply_revisions(plan, [{"op": "reorder", "order": ["shot-002", "shot-001", "shot-003"]}])
        whip = [(e["effects"].get("whip_in", 0), e["effects"].get("whip_out", 0)) for e in plan["edits"]]
        # Nothing precedes the opening shot, and neither 2->1 nor 1->3 had a transition before.
        self.assertEqual(whip, [(0, 0), (0, 0), (0, 0)])
        kept = apply_revisions(self.plan, [{"op": "transition", "after": 2, "type": "whip"}])
        kept = apply_revisions(kept, [{"op": "reorder", "order": ["shot-002", "shot-003", "shot-001"]}])
        self.assertEqual((kept["edits"][0]["effects"]["whip_out"], kept["edits"][1]["effects"]["whip_in"]), (1, 1))


class FlashRateTests(unittest.TestCase):
    """Hard rule: at most three full-frame flashes, dips or inverts in any one second."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        image = Path(self.temp.name)/"still.png"
        from PIL import Image
        Image.fromarray(pattern()).save(image)
        self.dense = minimal_plan(image, shots=8, frames=6)    # five cuts per second
        self.loose = minimal_plan(image, shots=8, frames=12)   # two and a half per second

    def test_revise_refuses_new_bursts(self):
        for kind in ("flash", "dip", "invert"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "photosensitive"):
                apply_revisions(self.dense, [{"op": "transition", "all": True, "type": kind, "strength": .7}])
        with self.assertRaisesRegex(ValueError, "photosensitive"):
            apply_revisions(self.dense, [{"op": "effects", "all": True, "values": {"flash": .3}}])
        apply_revisions(self.dense, [{"op": "transition", "all": True, "type": "whip"}])
        apply_revisions(self.loose, [{"op": "transition", "all": True, "type": "flash", "strength": .7}])

    def test_an_old_project_with_bursts_can_still_be_revised(self):
        for shot in self.dense["edits"]:
            shot["effects"]["flash"] = .5
        self.assertTrue(flash_bursts(self.dense["edits"], 30))
        apply_revisions(self.dense, [{"op": "effects", "all": True, "values": {"grade": "mono"}}])
        fixed = apply_revisions(self.dense, [{"op": "effects", "all": True, "values": {"flash": 0}}])
        self.assertEqual(flash_bursts(fixed["edits"], 30), [])

    def test_an_old_burst_can_be_thinned_one_cut_at_a_time(self):
        for shot in self.dense["edits"]:
            shot["effects"]["flash"] = .5
        for operations in ([{"op": "effects", "shot": 3, "values": {"flash": 0}}],
                           [{"op": "effects", "shot": 3, "reset": True}],
                           [{"op": "transition", "after": 2, "type": "rgb"}],
                           [{"op": "transition", "after": 2, "type": "cut"}],
                           [{"op": "reorder", "order": ["shot-001", "shot-002", "shot-004", "shot-003",
                                                        "shot-005", "shot-006", "shot-007", "shot-008"]}]):
            with self.subTest(operations=operations):
                apply_revisions(self.dense, operations)

    def test_a_revision_may_not_grow_or_densify_a_burst(self):
        for shot in self.dense["edits"][:4]:
            shot["effects"]["flash"] = .5
        with self.assertRaisesRegex(ValueError, "would leave"):
            apply_revisions(self.dense, [{"op": "effects", "shot": 5, "values": {"flash": .5}}])
        # Squeezing shots that already flash too often into less time makes it worse.
        squeeze = copy.deepcopy(self.loose)
        for shot in squeeze["edits"]:
            shot["effects"]["flash"] = .5
        squeeze["edits"][0]["effects"].pop("flash")
        operations = [{"op": "duration", "shot": n, "seconds": .2, "borrow_from": 8} for n in range(2, 8)]
        with self.assertRaisesRegex(ValueError, "photosensitive"):
            apply_revisions(squeeze, operations)

    def flashing(self, frames, flashing):
        """A plan with these shot lengths whose listed shot numbers flash."""
        from project_workspace import _retime
        plan = minimal_plan(Path(self.temp.name)/"still.png", shots=len(frames), frames=1)
        for shot, count in zip(plan["edits"], frames):
            shot.update(duration_frames=count, section="drop")
        plan["duration_frames"] = sum(frames)
        plan["duration"] = plan["audio"]["duration"] = sum(frames) / 30
        plan["sections"] = [{"name": "drop", "start_frame": 0, "end_frame": sum(frames)}]
        _retime(plan, update_sections=False)
        for number in flashing:
            plan["edits"][number - 1]["effects"]["flash"] = .5
        return plan

    def test_a_revision_may_not_join_old_bursts(self):
        plan = self.flashing([8] * 24, [*range(1, 5), *range(13, 17)])
        order = [shot["id"] for shot in plan["edits"]]
        joined = order[:4] + order[12:16] + order[4:12] + order[16:]
        with self.assertRaisesRegex(ValueError, "photosensitive"):
            apply_revisions(plan, [{"op": "reorder", "order": joined}])
        plan = self.flashing([7] * 4 + [30] + [7] * 4 + [60], [1, 2, 3, 4, 6, 7, 8, 9])
        with self.assertRaisesRegex(ValueError, "photosensitive"):
            apply_revisions(plan, [{"op": "duration", "shot": 5, "seconds": 7 / 30, "borrow_from": 10}])

    def test_a_denser_burst_elsewhere_does_not_hide_a_squeeze(self):
        plan = self.flashing([6] * 5 + [120] + [8] * 5 + [60], [1, 2, 3, 4, 5, 7, 8, 9, 10, 11])
        operations = [{"op": "duration", "shot": n, "seconds": .2, "borrow_from": 12} for n in range(7, 11)]
        with self.assertRaisesRegex(ValueError, "shot-007, shot-008, shot-009, shot-010"):
            apply_revisions(plan, operations)

    def test_flash_montage_refuses_dense_flashing(self):
        from flash_montage import densest_second, flash_peaks
        self.assertEqual(densest_second(flash_peaks([60 / 200 + .5] * 8, .5)), 4)  # every beat at 200 BPM
        self.assertEqual(densest_second(flash_peaks([60 / 180 + .5] * 8, .5)), 3)
        # fadewhite is whitest 20% in, so the opening flash plus beats from 0.15 s at 176 BPM is four.
        self.assertEqual(densest_second(flash_peaks([.65] + [.84] * 5, .5)), 4)
        self.assertEqual(densest_second(flash_peaks([.65] + [.84] * 5, .5, open_flash=False)), 3)
        script = Path(ROOT) / "flash_montage.py"
        seq = Path(self.temp.name) / "seq.json"
        seq.write_text(json.dumps({"items": [{"image": str(Path(self.temp.name)/"still.png"), "dur": .8}] * 8}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-X", "utf8", str(script), "--seq", str(seq), "--audio", "unused.wav",
                                 "--out", str(Path(self.temp.name)/"m.mp4")], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("4 white flashes within one second", result.stderr)
        seq.write_text(json.dumps({"items": [{"image": str(Path(self.temp.name)/"still.png"), "dur": 2}]}), encoding="utf-8")
        result = subprocess.run([sys.executable, "-X", "utf8", str(script), "--seq", str(seq), "--audio", "unused.wav",
                                 "--out", str(Path(self.temp.name)/"m.mp4")], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("at least two items", result.stderr)

    def test_thinning_keeps_three_per_second(self):
        for shot in self.dense["edits"]:
            shot["effects"]["flash"] = .5
        thinned = thin_flashes(self.dense["edits"], 30)
        self.assertEqual(thinned, ["shot-004", "shot-005"])
        self.assertEqual(flash_bursts(self.dense["edits"], 30), [])


class NaturalLookPlanTests(unittest.TestCase):
    def test_grade_none_removes_preset_looks_but_keeps_explicit_ones(self):
        from project_plan import build_plan
        from tests.test_project_plan import inputs
        for preset in ("phonk", "anime", "travel"):
            beatmap, library = inputs()
            plan = build_plan(beatmap, library, duration=8, preset=preset, grade="none")
            for shot in plan["edits"]:
                with self.subTest(preset=preset, shot=shot["id"]):
                    self.assertEqual(shot["effects"]["grade"], "none")
                    self.assertFalse(set(shot["effects"]) & {"vignette", "grain", "glow", "letterbox"})
        beatmap, library = inputs()
        plan = build_plan(beatmap, library, duration=8, preset="phonk", grade="none", effects={"grain": .2})
        self.assertTrue(all(shot["effects"]["grain"] == .2 and "vignette" not in shot["effects"] for shot in plan["edits"]))
        beatmap, library = inputs()
        plan = build_plan(beatmap, library, duration=8, preset="phonk", grade="neutral")
        self.assertTrue(all(shot["effects"]["vignette"] == .45 for shot in plan["edits"]))
        beatmap, library = inputs()  # --effect grade=none means the same as --grade none
        plan = build_plan(beatmap, library, duration=8, preset="phonk", effects={"grade": "none"})
        self.assertTrue(all(not set(shot["effects"]) & {"vignette", "grain"} for shot in plan["edits"]))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe required")
class RenderTests(unittest.TestCase):
    def test_effect_stack_renders_exact_frames_and_beats_enter_cache_key(self):
        from PIL import Image
        from project_render import render_project
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            clip, music, still = work/"clip.mp4", work/"music.wav", work/"still.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x160:rate=30:duration=2",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=3", str(music)], check=True)
            Image.fromarray(pattern(160, 96)).save(still)
            plan = minimal_plan(still, shots=2, frames=20)
            plan["audio"]["path"] = str(music)
            plan["output"].update(width=96, height=160)
            plan["assets"].append({"id": "v", "path": str(clip), "kind": "video", "duration": 2})
            plan["edits"][0].update(kind="video", asset_id="v", source=str(clip), source_start=0.0, source_end=20/30)
            plan["beat_frames"] = [0, 10, 20, 30]
            plan = apply_revisions(plan, [
                {"op": "effects", "all": True, "values": {"pulse": .8, "vignette": .5, "grain": .3, "letterbox": .08, "grade": "teal_orange"}},
                {"op": "transition", "after": 1, "type": "whip"}])
            first = render_project(plan, work/"fx.mp4", cache_dir=work/"cache")
            self.assertEqual((first["frames"], first["width"], first["height"]), (40, 96, 160))
            again = render_project(plan, work/"fx-again.mp4", cache_dir=work/"cache")
            self.assertEqual(again["cache_hits"], 2)
            plan["beat_frames"] = [0, 5, 20, 25]
            moved = render_project(plan, work/"fx-moved.mp4", cache_dir=work/"cache")
            self.assertEqual(moved["cache_hits"], 0, "pulse shots rerender when beats move")


class EntryPointTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT/"edit_project.py"), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_effects_and_presets_commands(self):
        effects = json.loads(self.run_cli("effects").stdout)
        self.assertIn("whip_in", effects["effects"])
        self.assertIn("phonk", json.loads(self.run_cli("presets").stdout))


if __name__ == "__main__":
    unittest.main()

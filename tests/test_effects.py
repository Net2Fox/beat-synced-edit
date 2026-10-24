"""Per-shot edit effects, transitions, presets and the environment entry points."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from edit_effects import (ACCENT_EFFECTS, EFFECTS, GRADES, catalog, parse_effect_override,
                          transition_effects, validate_effects)
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
        with self.assertRaisesRegex(ValueError, "Unknown effects"):
            apply_revisions(plan, [{"op": "effects", "all": True, "values": {"sparkle": 1}}])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            apply_revisions(plan, [{"op": "effects", "all": True}])

    def test_transition_targets_cuts(self):
        plan = apply_revisions(self.plan, [{"op": "transition", "after": 1, "type": "whip", "strength": .8}])
        self.assertEqual(plan["edits"][0]["effects"]["whip_out"], .8)
        self.assertEqual(plan["edits"][1]["effects"]["whip_in"], .8)
        plan = apply_revisions(plan, [{"op": "transition", "after": "shot-001", "type": "flash"}])
        self.assertEqual((plan["edits"][0]["effects"]["whip_out"], plan["edits"][1]["effects"]["whip_in"]), (0, 0))
        self.assertEqual(plan["edits"][1]["effects"]["flash"], 1)
        plan = apply_revisions(plan, [{"op": "transition", "all": True, "type": "glitch", "strength": .5}])
        self.assertEqual([e["effects"].get("glitch", 0) for e in plan["edits"]], [0, .5, .5])
        plan = apply_revisions(plan, [{"op": "transition", "section": "drop", "type": "cut"}])
        self.assertTrue(all(e["effects"].get("glitch", 0) == 0 for e in plan["edits"]))
        with self.assertRaisesRegex(ValueError, "final shot"):
            apply_revisions(plan, [{"op": "transition", "after": 3, "type": "dip"}])
        with self.assertRaisesRegex(ValueError, "requires"):
            apply_revisions(plan, [{"op": "transition", "type": "dip"}])


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

    def test_effects_presets_and_tool_commands(self):
        effects = json.loads(self.run_cli("effects").stdout)
        self.assertIn("whip_in", effects["effects"])
        self.assertIn("phonk", json.loads(self.run_cli("presets").stdout))
        listing = self.run_cli("tool")
        self.assertEqual(listing.returncode, 2)
        self.assertIn("beat_map.py", listing.stdout)
        self.assertEqual(self.run_cli("tool", "beat_map", "--help").returncode, 0)
        self.assertEqual(self.run_cli("tool", "missing.py").returncode, 2)

    def test_doctor_reports_structured_readiness(self):
        result = self.run_cli("doctor", "--json-brief")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "doctor")
        report = payload.get("result") or payload["error"]["report"]
        names = {item["name"] for item in report["checks"]}
        self.assertTrue({"python", "package:numpy", "ffmpeg", "encoder:libx264"} <= names)
        self.assertEqual(result.returncode, 0 if payload["ok"] else 4)

    @unittest.skipIf(os.name == "nt", "POSIX launcher")
    def test_posix_launcher_reports_missing_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            scripts = Path(temp)/"skill"/"scripts"
            scripts.mkdir(parents=True)
            shutil.copy(ROOT/"edit", scripts/"edit")
            result = subprocess.run([str(scripts/"edit"), "presets"], capture_output=True, text=True,
                                    env={k: v for k, v in os.environ.items() if k != "BEAT_SYNC_PYTHON"})
            self.assertEqual(result.returncode, 3)
            self.assertIn("bootstrap.py", result.stderr)
            for name in ("edit_project.py", "env_doctor.py", "project_workspace.py"):
                shutil.copy(ROOT/name, scripts/name)
            result = subprocess.run([str(scripts/"edit"), "doctor", "--json-brief"], capture_output=True, text=True,
                                    env={**os.environ, "BEAT_SYNC_PYTHON": sys.executable})
            self.assertIn('"command": "doctor"', result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

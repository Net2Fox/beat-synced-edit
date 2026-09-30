"""Observable revision behavior: atomicity, timing preservation and safe review pages."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_workspace import apply_revisions, read_json, review_html, revise_file, write_json


def fixture(root):
    from project_plan import build_plan
    assets, clips = [], []
    for i in range(12):
        path = str(root / f"scene-{i}.mp4")
        assets.append({"id": f"a{i}", "path": path, "kind": "video", "duration": 8,
                       "width": 320, "height": 180, "fps": 30})
        clips.append({"id": f"c{i}", "asset_id": f"a{i}", "source": path, "kind": "video",
                      "start": 0, "end": 8, "duration": 8, "energy": .7, "brightness": .5,
                      "motion": "high", "tags": ["car"], "shot_type": "wide" if i % 2 else "detail",
                      "visual_hash": f"{i*71712347:016x}"})
    beatmap = {"file": str(root / "song.wav"), "duration": 12, "tempo": 120,
               "beats": [i / 2 for i in range(24)], "peaks": [{"time": 3, "energy": .9}],
               "energy_curve": [{"time": t, "energy": e} for t, e in zip([0, 2, 3, 5, 8, 12], [.2, .4, .9, .9, .5, .1])]}
    return build_plan(beatmap, {"assets": assets, "clips": clips}, duration=6, preset="car", fps=30,
                      width=180, height=320, audio_start=0)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_effect_revision_preserves_timing_and_original(self):
        before = copy.deepcopy(self.plan)
        revised = apply_revisions(self.plan, [{"op": "effects", "all": True, "values": {"flash": 0}}])
        self.assertEqual(self.plan, before)
        self.assertEqual(revised["duration_frames"], before["duration_frames"])
        self.assertTrue(all(e["effects"]["flash"] == 0 for e in revised["edits"]))
        self.assertEqual(revised["revision"], 1)

    def test_lengthen_shot_borrows_frames_without_changing_total(self):
        shots = self.plan["edits"]
        self.assertGreaterEqual(len(shots), 2)
        seconds = (shots[0]["duration_frames"] + 1) / 30
        revised = apply_revisions(self.plan, [{"op": "duration", "shot": 1, "seconds": seconds}])
        self.assertEqual(revised["edits"][0]["duration_frames"], shots[0]["duration_frames"] + 1)
        self.assertEqual(revised["edits"][1]["duration_frames"], shots[1]["duration_frames"] - 1)
        self.assertEqual(revised["edits"][-1]["timeline_end_frame"], self.plan["duration_frames"])

    def test_replacement_keeps_shot_id_and_timeline(self):
        old = self.plan["edits"][0]
        # Replacing with a disjoint source can be done without repeating footage.
        used = {s["asset_id"] for s in self.plan["edits"]}
        clip = next(c for c in self.plan["clips"] if c["asset_id"] not in used)
        revised = apply_revisions(self.plan, [{"op": "replace", "shot": old["id"], "clip_id": clip["id"]}])
        new = revised["edits"][0]
        self.assertEqual(new["source"], clip["source"])
        self.assertEqual(new["duration_frames"], old["duration_frames"])
        self.assertEqual(new["id"], old["id"])

    def test_invalid_revision_does_not_modify_file(self):
        path = self.root / "project.json"
        write_json(path, self.plan)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            revise_file(path, [{"op": "effects", "all": True, "values": {"flash": 0}},
                               {"op": "replace", "shot": 1, "clip_id": "missing"}])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / ".history").exists())

    def test_replace_finds_unused_range_in_already_used_clip(self):
        first, target = self.plan["edits"][:2]
        self.assertNotEqual(first["source"], target["source"])
        revised = apply_revisions(self.plan, [{"op": "replace", "shot": target["id"], "clip_id": first["clip_id"]}])
        replacement = revised["edits"][1]
        self.assertEqual(replacement["source"], first["source"])
        self.assertGreaterEqual(replacement["source_start"], first["source_end"])
        clip = next(c for c in self.plan["clips"] if c["id"] == first["clip_id"])
        self.assertEqual(replacement["tags"], clip["tags"])
        self.assertEqual(replacement["shot_type"], clip["shot_type"])

    def test_multiple_replacements_can_swap_source_ranges_atomically(self):
        first, second = self.plan["edits"][:2]
        operations = [{"op": "replace", "shot": target["id"], "clip_id": source["clip_id"],
                       "source_start": source["source_start"], "source_end": source["source_end"]}
                      for target, source in ((first, second), (second, first))]
        revised = apply_revisions(self.plan, operations)
        self.assertEqual(revised["edits"][0]["source"], second["source"])
        self.assertEqual(revised["edits"][1]["source"], first["source"])

    def test_revision_saves_recoverable_history(self):
        path = self.root / "проект.json"
        write_json(path, self.plan)
        revised = revise_file(path, [{"op": "effects", "all": True, "values": {"flash": 0}}])
        self.assertEqual(read_json(path), revised)
        snapshots = list((self.root / ".history").glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(read_json(snapshots[0]), self.plan)

    def test_preview_html_escapes_untrusted_names_and_works_offline(self):
        self.plan["clips"][0]["tags"] = ["</script><script>alert(1)</script>"]
        output = self.root / "preview.html"
        review_html(self.plan, self.root / "превью с пробелами.mp4", output)
        page = output.read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert", page)
        self.assertIn("\\u003c/script>", page)
        self.assertIn("Download revisions.json", page)
        self.assertNotIn('src="http', page)
        self.assertIn("%20", page)
        review_html(self.plan, self.root / "DATA VIDEO.mp4", output)
        self.assertIn('src="DATA%20VIDEO.mp4"', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

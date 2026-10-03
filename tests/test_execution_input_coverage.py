"""Actual files affecting optional command behavior remain bound to dry runs."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

from cli_contract import fingerprint_inputs
from project_workspace import write_json


class InputCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_music_override_and_nested_recording_are_fingerprinted(self):
        recording = self.root/"music.wav"
        recording.write_bytes(b"recording")
        beats, overrides = self.root/"beats.json", self.root/"overrides.json"
        write_json(beats, {"file": str(recording), "beats": [0, 1]})
        write_json(overrides, {"mode": "phrase_flow"})
        args = Namespace(command="music-override", beatmap=str(beats), overrides=str(overrides))
        before = fingerprint_inputs(args)
        self.assertEqual(set(before["files"]), {str(p) for p in (recording, beats, overrides)})
        overrides.write_text('{"mode":"beat_cut"}')
        self.assertNotEqual(before, fingerprint_inputs(args))

    def test_candidate_model_and_explicit_font_are_bound(self):
        model = self.root/"model.json"
        font = self.root/"font.ttf"
        write_json(model, {"weights": [1, 2]})
        font.write_bytes(b"font-content")
        args = Namespace(command="candidates", model=str(model), font=str(font))
        result = fingerprint_inputs(args)
        self.assertEqual(set(result["files"]), {str(model), str(font)})
        font.write_bytes(b"changed-font")
        self.assertNotEqual(result, fingerprint_inputs(args))

    def test_named_whisper_model_is_not_mistaken_for_missing_file(self):
        result = fingerprint_inputs(Namespace(command="speech-plan", model="small"))
        self.assertEqual(result["files"], {})
        model = self.root/"local-model"
        model.mkdir()
        (model/"model.bin").write_bytes(b"weights")
        result = fingerprint_inputs(Namespace(command="speech-plan", model=str(model)))
        self.assertIn(str(model/"model.bin"), result["files"])
        with self.assertRaises(FileNotFoundError):
            fingerprint_inputs(Namespace(command="speech-plan", model=str(self.root/"missing-model")))

    def test_public_commands_preserve_inputs_and_default_preview_html(self):
        from edit_project import parser, run
        from graphics_commands import motion_project
        spec = self.root/"spec.json"
        values = {"duration": .5, "fps": 24, "width": 64, "height": 64}
        write_json(spec, values)
        original = spec.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            run(parser().parse_args(["motion-project", str(spec), "-o", str(spec)]))
        self.assertEqual(spec.read_bytes(), original)
        project = self.root/"out.html"
        motion_project(values, project)
        original = project.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            run(parser().parse_args(["preview", str(project), "-o", str(self.root/"out.mp4")]))
        self.assertEqual(project.read_bytes(), original)
        self.assertFalse((self.root/"out.mp4").exists())


if __name__ == "__main__":
    unittest.main()

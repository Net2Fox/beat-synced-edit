"""Commands find every input file, including paths named inside JSON inputs, so no output overwrites one."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401  (makes the skill's scripts importable)
from cli_guard import input_files
from project_workspace import write_json


class InputCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_music_override_and_nested_recording_are_inputs(self):
        recording = self.root/"music.wav"
        recording.write_bytes(b"recording")
        beats, overrides = self.root/"beats.json", self.root/"overrides.json"
        write_json(beats, {"file": str(recording), "beats": [0, 1]})
        write_json(overrides, {"mode": "phrase_flow"})
        args = Namespace(command="music-override", beatmap=str(beats), overrides=str(overrides))
        self.assertEqual(input_files(args), {p.resolve() for p in (recording, beats, overrides)})

    def test_explicit_font_is_bound(self):
        font = self.root/"font.ttf"
        font.write_bytes(b"font-content")
        args = Namespace(command="title", font=str(font))
        self.assertEqual(input_files(args), {font.resolve()})

    def test_named_whisper_model_is_not_mistaken_for_missing_file(self):
        self.assertEqual(input_files(Namespace(command="speech-plan", model="small")), set())
        model = self.root/"local-model"
        model.mkdir()
        (model/"model.bin").write_bytes(b"weights")
        self.assertIn((model/"model.bin").resolve(), input_files(Namespace(command="speech-plan", model=str(model))))
        with self.assertRaises(FileNotFoundError):
            input_files(Namespace(command="speech-plan", model=str(self.root/"missing-model")))

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

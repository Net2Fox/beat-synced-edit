"""Public command integration and atomic configuration/history safeguards."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from audio_commands import register_audio_commands, run_audio_command
from audio_mix import write_audio
from project_workspace import read_json, write_json


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class AudioCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root/"audio.wav"
        write_audio(self.audio, np.zeros((48000, 2), np.float32))
        self.project = self.root/"project.json"
        self.config = self.root/"config.json"
        self.plan = {"duration_frames": 30, "output": {"fps": 30}, "edits": [],
                     "audio": {"path": str(self.audio), "start": 0}}
        write_json(self.project, self.plan)
        self.parser = argparse.ArgumentParser()
        register_audio_commands(self.parser.add_subparsers(dest="command", required=True))

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        return run_audio_command(self.parser.parse_args([str(x) for x in args]))

    def test_config_updates_and_saves_history_only_after_validation(self):
        write_json(self.config, {"source_audio": {"enabled": False}, "loudness": {"enabled": False}})
        result = self.invoke("audio-config", self.project, "--config", self.config)
        self.assertEqual(result["revision"], 1)
        self.assertEqual(len(list((self.root/".history").glob("*.json"))), 1)
        before = self.project.read_bytes()
        self.config.write_text(json.dumps({"tracks": [{"path": str(self.audio), "gain_db": float("nan")}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.invoke("audio-config", self.project, "--config", self.config)
        self.assertEqual(self.project.read_bytes(), before)

    def test_mix_and_report_commands_and_input_protection(self):
        output = self.root/"mix.wav"
        result = self.invoke("audio-mix", self.project, "-o", output)
        self.assertTrue(Path(result["report"]).is_file())
        self.assertEqual(read_json(result["report"])["samples"], 48000)
        measured = self.invoke("audio-report", output)
        self.assertFalse(measured["measurements"]["measurable"])
        for target in (self.audio, self.project):
            with self.assertRaises(ValueError):
                self.invoke("audio-mix", self.project, "-o", target)


if __name__ == "__main__":
    unittest.main()

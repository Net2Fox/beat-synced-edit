"""Text CLI output paths cannot destroy input media or project files."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_workspace import write_json
from test_project_workspace import fixture
from text_commands import register_text_commands, run_text_command


class TextCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = fixture(self.root)
        self.project = self.root / "project.json"
        write_json(self.project, self.plan)
        self.audio = self.root / "speech.wav"
        self.audio.write_bytes(b"original speech")
        self.parser = argparse.ArgumentParser()
        register_text_commands(self.parser.add_subparsers(dest="command"))

    def invoke(self, *args):
        return run_text_command(self.parser.parse_args(list(map(str, args))))

    def test_project_output_cannot_overwrite_any_source(self):
        for source in [self.plan["audio"]["path"], *[a["path"] for a in self.plan["assets"]]]:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "overwrite"):
                self.invoke("title", self.project, "--text", "Title", "--end", "1", "-o", source)

    def test_import_cannot_overwrite_its_subtitle_file(self):
        incoming = self.root / "captions.srt"
        incoming.write_text("1\n00:00:00,000 --> 00:00:01,000\nOriginal\n", encoding="utf-8")
        before = incoming.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.invoke("subtitles-import", self.project, incoming, "-o", incoming)
        self.assertEqual(incoming.read_bytes(), before)

    def test_transcript_paths_are_checked_before_recognition(self):
        output = self.root / "new-project.json"
        protected = [self.project, output, self.audio, self.plan["audio"]["path"],
                     *[a["path"] for a in self.plan["assets"]]]
        with patch("text_commands.subprocess.run") as extract:
            for path in protected:
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "overwrite"):
                    self.invoke("transcribe", self.project, "--audio", self.audio,
                                "--transcript", path, "-o", output)
            extract.assert_not_called()
        self.assertEqual(self.audio.read_bytes(), b"original speech")

    def test_silence_keeps_existing_project_and_saves_durable_provenance(self):
        before = self.project.read_bytes()
        with patch("text_commands.subprocess.run") as extract, patch("speech_transcribe.transcribe_audio") as recognize:
            extract.return_value.returncode = 0
            recognize.return_value = {"segments": [], "audio_path": "temporary.wav", "language": "en"}
            result = self.invoke("transcribe", self.project, "--audio", self.audio)
        self.assertEqual(result["status"], "no_speech")
        self.assertEqual(self.project.read_bytes(), before)
        import json
        saved = json.loads((self.root / "transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["audio_path"], str(self.audio))

    def test_recognition_receives_the_same_looped_soundtrack_range_as_render(self):
        import wave
        self.plan["audio"].update(path=str(self.audio), start=.2, loop=True)
        write_json(self.project, self.plan)
        with wave.open(str(self.audio), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(b"\0\0" * 16000)

        def check_audio(path, **kwargs):
            with wave.open(path, "rb") as decoded:
                self.assertEqual(decoded.getnframes(), 6 * 16000)
            return {"segments": [], "language": "en"}

        with patch("speech_transcribe.transcribe_audio", side_effect=check_audio):
            self.invoke("transcribe", self.project)


if __name__ == "__main__":
    unittest.main()

"""Public CLI smoke with real FFmpeg decoding/encoding and waveform assertions.

Generated tones and supplied text establish mechanics, not recognition accuracy.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from edit_project import main
from project_workspace import read_json, write_json
from audio_mix import decode_audio


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class SpeechWorkflowSmoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main([str(a) for a in args])
        self.assertEqual(code, 0, error.getvalue())
        return json.loads(output.getvalue())

    def media(self, name, color, frequency):
        path = self.root/name
        process = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=30:d=4",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(path)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        return path

    def test_broll_keeps_encoded_voice_bilingual_captions_and_exact_frames(self):
        source, broll = self.media("voice.mp4", "blue", 440), self.media("broll.mp4", "red", 1200)
        transcript = self.root/"transcript.json"
        write_json(transcript, {"segments": [{"start": 0, "end": 2, "text": "Hello world.", "words": [
            {"start": 0, "end": 1, "text": "Hello"}, {"start": 1, "end": 2, "text": "world."}]},
            {"start": 2.5, "end": 4, "text": "Next thought!"}]})
        project = self.root/"project.json"
        self.cli(["speech-plan", source, "--transcript", transcript, "--padding", "0", "--pause-limit", "0",
                  "--width", "160", "--height", "90", "-o", project])
        original = read_json(project)
        first = original["edits"][0]["id"]
        self.cli(["speech-broll", project, "--shot", first, "--media", broll, "--offset", ".5", "--duration", "1"])
        revised = read_json(project)
        self.assertEqual(revised["duration_frames"], original["duration_frames"])
        self.assertEqual([c["text"] for c in revised["subtitles"]], ["Hello world.", "Next thought!"])
        segments = revised["speech"]["transcripts"][0]["segments"]
        translations = self.root/"ru.json"
        write_json(translations, {segments[0]["id"]: "Привет, мир.", segments[1]["id"]: "Следующая мысль!"})
        self.cli(["speech-translate", project, translations, "--language", "ru"])
        self.cli(["text-style", project, "--track", "subtitles", "--font-size", "8", "--max-lines", "4"])
        for suffix in ("srt", "vtt"):
            output = self.root/f"captions.{suffix}"
            self.cli(["subtitles-export", project, "-o", output])
            self.assertIn("Привет, мир.", output.read_text(encoding="utf-8"))
        output = self.root/"render.mp4"
        result = self.cli(["render", project, "-o", output])
        self.assertEqual(result["frames"], 105)
        self.assertTrue(result["audio"])
        samples = decode_audio(output).mean(axis=1)[24000:72000]
        spectrum = abs(np.fft.rfft(samples))
        frequencies = np.fft.rfftfreq(len(samples), 1/48000)
        peak = frequencies[np.argmax(spectrum)]
        self.assertAlmostEqual(peak, 440, delta=2)
        energy_voice = spectrum[abs(frequencies-440) < 4].max()
        energy_broll = spectrum[abs(frequencies-1200) < 4].max()
        self.assertGreater(energy_voice, 50*energy_broll)
        video = cv2.VideoCapture(str(output)); video.set(cv2.CAP_PROP_POS_MSEC, 1000)
        ok, frame = video.read(); video.release()
        self.assertTrue(ok)
        self.assertGreater(float(frame[:30, :, 2].mean()), 220)  # B-roll picture is red.
        self.assertLess(float(frame[:30, :, 0].mean()), 20)

    def test_gap_review_targeted_retry_and_batch_manifest(self):
        source = self.media("voice.mp4", "blue", 440)
        transcript = self.root/"transcript.json"
        write_json(transcript, {"segments": [{"start": 0, "end": 1, "text": "First."}, {"start": 3, "end": 4, "text": "Last."}]})
        project = self.root/"project.json"
        self.cli(["speech-plan", source, "--transcript", transcript, "-o", project, "--width", "160", "--height", "90"])
        gap = self.root/"gaps.json"
        self.cli(["speech-gaps", project, "-o", gap])
        self.assertEqual(read_json(gap)["suspect_count"], 1)
        retry = self.root/"retry.json"
        write_json(retry, {"segments": [{"start": 1.2, "end": 2.8, "text": "Previously missing."}]})
        self.cli(["speech-retry", project, "--start", "1", "--end", "3", "--file", retry])
        updated = read_json(project)
        self.assertEqual(len(updated["speech"]["transcripts"][0]["segments"]), 3)
        manifest = self.root/"batch.json"
        write_json(manifest, {"items": [{"id": "first", "source": "voice.mp4", "transcript": "transcript.json"},
                                        {"id": "second", "source": "voice.mp4", "transcript": "transcript.json"}]})
        result = self.cli(["speech-batch", manifest, "-o", self.root/"batch-result.json"])
        self.assertEqual(result["analyzed"], 2)
        self.assertEqual(result["failed"], 0)


if __name__ == "__main__":
    unittest.main()

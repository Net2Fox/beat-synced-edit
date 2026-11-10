"""Music analysis reads a song from a video container as well as from an audio file."""

from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import soundfile

import _paths  # noqa: F401  (makes the skill's scripts importable)
from beat_map import _load_audio, analyze_audio


class ContainerAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "музыка"
        cls.root.mkdir()
        rate, seconds = 22050, 8
        samples = np.zeros(rate * seconds, np.float32)
        time = np.arange(int(.18 * rate)) / rate
        kick = (np.sin(2 * np.pi * 70 * time) * np.exp(-time * 22)).astype(np.float32)
        for beat in np.arange(0, seconds - .3, .5):         # 120 BPM
            start = int(beat * rate)
            samples[start:start + len(kick)] += kick * .9
        cls.wav = cls.root / "клик.wav"
        soundfile.write(cls.wav, samples, rate)
        cls.mp4 = cls.root / "клик в видео.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10",
                        "-i", str(cls.wav), "-shortest", "-c:v", "mpeg4", "-c:a", "aac", "-b:a", "128k", str(cls.mp4)],
                       check=True)
        cls.silent = cls.root / "без звука.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10",
                        "-t", "1", "-c:v", "mpeg4", str(cls.silent)], check=True)

    def test_container_audio_matches_the_audio_file(self):
        direct, rate = _load_audio(self.wav)
        decoded, decoded_rate = _load_audio(self.mp4)
        self.assertEqual((rate, decoded_rate), (22050, 22050))
        self.assertEqual((direct.ndim, decoded.ndim, decoded.dtype), (1, 1, np.float32))
        self.assertLess(abs(len(decoded) - len(direct)) / rate, .15)
        count = min(len(direct), len(decoded))
        # Same hits at the same times: the envelopes line up without a shift.
        envelope = lambda signal: np.abs(signal[:count]).reshape(-1, 441).max(axis=1)
        self.assertGreater(np.corrcoef(envelope(direct[:count // 441 * 441]), envelope(decoded[:count // 441 * 441]))[0, 1], .9)

    def test_song_inside_a_video_is_analyzed_like_the_audio_file(self):
        from_video = analyze_audio(str(self.mp4), segment_duration=4)
        from_audio = analyze_audio(str(self.wav), segment_duration=4)
        self.assertAlmostEqual(from_video["duration"], 8, delta=.2)
        self.assertLess(abs(from_video["tempo"] - 120), 5)
        self.assertGreaterEqual(from_video["beat_count"], 12)
        self.assertLess(abs(float(np.median(np.diff(from_video["beats"]))) - .5), .03)
        self.assertAlmostEqual(from_video["tempo"], from_audio["tempo"], delta=1)
        self.assertLessEqual(abs(from_video["beat_count"] - from_audio["beat_count"]), 1)
        for expected in from_audio["beats"][:-1]:
            self.assertLess(min(abs(beat - expected) for beat in from_video["beats"]), .06)

    def test_container_without_audio_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "без звука"):
            _load_audio(self.silent)


if __name__ == "__main__":
    unittest.main()

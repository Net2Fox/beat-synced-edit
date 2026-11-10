"""Music analysis reads a song from a video container as well as from an audio file."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import librosa
import numpy as np
import soundfile

import _paths  # noqa: F401  (makes the skill's scripts importable)
import beat_map
from beat_map import _load_audio, analyze_audio


def ffmpeg(*arguments):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", *arguments], check=True, capture_output=True)


class ContainerAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name) / "музыка"
        cls.root.mkdir()
        rate, seconds = 22050, 8
        mono = np.zeros(rate * seconds, np.float32)
        time = np.arange(int(.18 * rate)) / rate
        kick = (np.sin(2 * np.pi * 70 * time) * np.exp(-time * 22)).astype(np.float32)
        for beat in np.arange(0, seconds - .3, .5):         # 120 BPM
            start = int(beat * rate)
            mono[start:start + len(kick)] += kick * .9
        cls.wav = cls.root / "бит.wav"
        soundfile.write(cls.wav, np.stack([mono, mono * .5], axis=1), rate)   # stereo, channels differ in level
        black = ["-f", "lavfi", "-i", "color=c=black:s=64x64:r=10"]
        cls.mp4 = cls.root / "бит в видео.mp4"
        ffmpeg(*black, "-i", str(cls.wav), "-shortest", "-c:v", "mpeg4", "-c:a", "aac", "-b:a", "128k", str(cls.mp4))
        cls.silent = cls.root / "без звука.mp4"
        ffmpeg(*black, "-t", "1", "-c:v", "mpeg4", str(cls.silent))

    def test_container_audio_matches_the_audio_file(self):
        direct, rate = _load_audio(self.wav)
        self.assertTrue(np.array_equal(direct, librosa.load(self.wav)[0]), "an audio file still goes through librosa")
        decoded, decoded_rate = _load_audio(self.mp4)
        self.assertEqual((rate, decoded_rate), (22050, 22050))
        self.assertEqual((direct.ndim, decoded.ndim, decoded.dtype), (1, 1, np.float32))
        self.assertLess(abs(len(decoded) - len(direct)) / rate, .15)
        count = min(len(direct), len(decoded)) // 441 * 441
        # Same hits at the same times: the envelopes line up without a shift.
        envelope = lambda signal: np.abs(signal[:count]).reshape(-1, 441).max(axis=1)
        self.assertGreater(np.corrcoef(envelope(direct), envelope(decoded))[0, 1], .9)
        # Channels are averaged as librosa does, not summed: a plain FFmpeg downmix is 3 dB (1.41x) hotter,
        # which moves the silence and energy thresholds of the analysis.
        level = lambda signal: float(np.sqrt(np.mean(signal[:count] ** 2)))
        self.assertAlmostEqual(level(decoded) / level(direct), 1, delta=.08)

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
        with self.assertRaisesRegex(RuntimeError, "No audio stream in .*без звука"):
            _load_audio(self.silent)

    def test_audio_that_starts_after_the_container_is_refused(self):
        # The renderer seeks the song on the container timeline; beats measured from the first
        # audio sample would be 1.5 s early for this file.
        late = self.root / "звук с задержкой.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=10", "-itsoffset", "1.5", "-i", str(self.wav),
               "-c:v", "mpeg4", "-c:a", "aac", str(late))
        with self.assertRaisesRegex(RuntimeError, r"starts 1\.\d+s after the file itself"):
            _load_audio(late)

    def test_truncated_container_is_not_analyzed_as_a_shorter_song(self):
        for name, codec in (("целый.m4a", ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]),
                            ("целый.webm", ["-c:a", "libopus"])):
            with self.subTest(name):
                whole = self.root / name
                ffmpeg("-i", str(self.wav), *codec, str(whole))
                self.assertAlmostEqual(len(_load_audio(whole)[0]) / 22050, 8, delta=.15)
                damaged = self.root / ("обрезанный" + whole.suffix)
                damaged.write_bytes(whole.read_bytes()[:whole.stat().st_size // 2])
                with self.assertRaisesRegex(RuntimeError, r"Only \d+\.\d+s of the 8\.\d+s of audio"):
                    _load_audio(damaged)

    def test_mp4_cut_inside_a_video_frame_ends_silently_but_is_refused(self):
        # With large video packets the next audio packet lies far beyond the cut: FFmpeg reaches a
        # clean end of file, exits 0 and prints nothing, yet half of the song is missing.
        whole = self.root / "с картинкой.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=5:d=8,noise=alls=40:allf=t", "-i", str(self.wav),
               "-c:v", "mjpeg", "-q:v", "2", "-c:a", "aac", "-movflags", "+faststart", str(whole))
        listed = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pos",
                                 "-of", "csv=p=0", str(whole)], check=True, capture_output=True, text=True).stdout.split()
        middle = int(listed[len(listed) // 2].strip(","))
        damaged = self.root / "с картинкой, обрезан.mp4"
        damaged.write_bytes(whole.read_bytes()[:middle + 1000])
        with self.assertRaisesRegex(RuntimeError, r"Only \d+\.\d+s of the 8\.\d+s of audio.*ends early"):
            _load_audio(damaged)

    def test_shorter_audio_and_estimated_durations_are_not_mistaken_for_damage(self):
        # Audio shorter than the picture is a complete file.
        long_picture = self.root / "длинная картинка.mkv"
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=20", "-i", str(self.wav),
               "-c:v", "mpeg4", "-c:a", "aac", str(long_picture))
        self.assertAlmostEqual(len(_load_audio(long_picture)[0]) / 22050, 8, delta=.15)
        # A raw AAC stream has no recorded length (ffprobe estimates one) and a rip often ends mid-frame.
        raw = self.root / "поток.aac"
        ffmpeg("-i", str(self.wav), "-c:a", "aac", "-b:a", "128k", "-f", "adts", str(raw))
        whole_stream = len(_load_audio(raw)[0])
        raw.write_bytes(raw.read_bytes()[:-100])
        self.assertLess(whole_stream - len(_load_audio(raw)[0]), .5 * 22050)   # a few frames lost, still loads

    def test_missing_ffmpeg_names_the_song_and_the_requirement(self):
        with patch.object(beat_map.subprocess, "run", side_effect=FileNotFoundError(2, "No such file", "ffprobe")):
            with self.assertRaisesRegex(RuntimeError, "бит в видео.*FFmpeg and ffprobe on PATH"):
                _load_audio(self.mp4)

    def test_missing_song_keeps_the_original_error(self):
        with patch.object(beat_map.subprocess, "run", side_effect=AssertionError("FFmpeg must not be tried")):
            with self.assertRaises(Exception) as caught:
                _load_audio(self.root / "нет такого.mp4")
        self.assertNotIsInstance(caught.exception, AssertionError)
        self.assertNotIn("FFmpeg", str(caught.exception))

    def test_long_ffmpeg_output_is_cut_in_the_error(self):
        real = subprocess.run

        def noisy_decoder(arguments, **options):
            if arguments[0] != "ffmpeg":
                return real(arguments, **options)
            noise = b"[mp3float] Header missing\n" * 4000 + b"the last line names the cause\n"
            return subprocess.CompletedProcess(arguments, 1, b"", noise)

        with patch.object(beat_map.subprocess, "run", side_effect=noisy_decoder):
            with self.assertRaises(RuntimeError) as caught:
                _load_audio(self.mp4)
        message = str(caught.exception)
        self.assertLess(len(message), 2300)
        self.assertIn("the last line names the cause", message)
        self.assertIn("бит в видео", message)


if __name__ == "__main__":
    unittest.main()

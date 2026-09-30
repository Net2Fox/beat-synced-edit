from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from speech_transcribe import transcribe_audio


class SpeechTranscribeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="speech-")
        self.addCleanup(self.temp.cleanup)
        self.audio = Path(self.temp.name) / "речь.wav"
        self.audio.write_bytes(b"mock audio")
        self.info = SimpleNamespace(language="ru", language_probability=.99, duration=2)
        word = SimpleNamespace(start=.1, end=.9, word=" Привет")
        self.segment = SimpleNamespace(start=0, end=1, text=" Привет", words=[word])
        self.model = Mock()
        self.model.transcribe.return_value = (iter([self.segment]), self.info)
        self.constructor = Mock(return_value=self.model)
        self.package = SimpleNamespace(WhisperModel=self.constructor)

    def test_cpu_defaults_complete_lazy_generator_and_preserve_words(self):
        with patch.dict("sys.modules", {"faster_whisper": self.package}):
            result = transcribe_audio(self.audio)
        self.constructor.assert_called_once_with("small", device="cpu", compute_type="int8")
        args, kwargs = self.model.transcribe.call_args
        self.assertEqual(args, (str(self.audio.resolve()),))
        self.assertTrue(kwargs["vad_filter"])
        self.assertTrue(kwargs["word_timestamps"])
        self.assertFalse(kwargs["condition_on_previous_text"])
        self.assertEqual(result["segments"][0]["words"], [{"start": .1, "end": .9, "text": " Привет"}])
        self.assertEqual(result["language"], "ru")
        self.assertTrue(result["review_required"])
        self.assertTrue(result["local"])

    def test_local_model_and_cache_options_are_routed(self):
        cache = Path(self.temp.name) / "models"
        local = Path(self.temp.name) / "converted-model"
        with patch.dict("sys.modules", {"faster_whisper": self.package}):
            transcribe_audio(self.audio, model=local, model_dir=cache, language="en", local_files_only=True,
                             cpu_threads=2, num_workers=1, beam_size=2)
        kwargs = self.constructor.call_args.kwargs
        self.assertEqual(kwargs["download_root"], str(cache.resolve()))
        self.assertTrue(kwargs["local_files_only"])
        self.assertEqual(kwargs["cpu_threads"], 2)
        transcribe_kwargs = self.model.transcribe.call_args.kwargs
        self.assertEqual(transcribe_kwargs["language"], "en")
        self.assertEqual(transcribe_kwargs["beam_size"], 2)
        self.assertNotIn("local_files_only", transcribe_kwargs)

    def test_optional_package_error_has_install_guidance(self):
        with patch.dict("sys.modules", {"faster_whisper": None}), self.assertRaisesRegex(RuntimeError, "requirements-transcription.txt"):
            transcribe_audio(self.audio)

    def test_missing_audio_fails_before_loading_package(self):
        with patch.dict("sys.modules", {"faster_whisper": self.package}), self.assertRaises(FileNotFoundError):
            transcribe_audio(Path(self.temp.name) / "missing.wav")
        self.constructor.assert_not_called()

    def test_empty_speech_returns_no_cues(self):
        self.model.transcribe.return_value = (iter([]), self.info)
        with patch.dict("sys.modules", {"faster_whisper": self.package}):
            self.assertEqual(transcribe_audio(self.audio)["segments"], [])

    def test_lazy_inference_failure_not_reported_as_success(self):
        def fails():
            yield self.segment
            raise RuntimeError("inference failed")
        self.model.transcribe.return_value = (fails(), self.info)
        with patch.dict("sys.modules", {"faster_whisper": self.package}), self.assertRaisesRegex(RuntimeError, "Local speech transcription failed"):
            transcribe_audio(self.audio)

    def test_zero_duration_punctuation_attaches_to_previous_word(self):
        self.segment.words.append(SimpleNamespace(start=.9, end=.9, word="!"))
        with patch.dict("sys.modules", {"faster_whisper": self.package}):
            words = transcribe_audio(self.audio)["segments"][0]["words"]
        self.assertEqual(words, [{"start": .1, "end": .9, "text": " Привет!"}])

    def test_zero_duration_initial_token_is_retained(self):
        self.segment.words.insert(0, SimpleNamespace(start=0, end=0, word=" Ну"))
        with patch.dict("sys.modules", {"faster_whisper": self.package}):
            words = transcribe_audio(self.audio)["segments"][0]["words"]
        self.assertEqual(words, [{"start": .1, "end": .9, "text": " Ну Привет"}])

    def test_backend_api_error_is_actionable(self):
        self.model.transcribe.side_effect = TypeError("incompatible decoder argument")
        with patch.dict("sys.modules", {"faster_whisper": self.package}), self.assertRaisesRegex(RuntimeError, "reinstall requirements-transcription.txt"):
            transcribe_audio(self.audio)

    def test_translation_not_silently_enabled(self):
        with patch.dict("sys.modules", {"faster_whisper": self.package}), self.assertRaisesRegex(ValueError, "Only transcription"):
            transcribe_audio(self.audio, task="translate")


if __name__ == "__main__":
    unittest.main()

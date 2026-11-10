"""Sources OpenCV cannot decode are measured through a frame-identical FFmpeg proxy."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import _paths  # noqa: F401  (makes the skill's scripts importable)
import speech_transcribe
import video_decode
from media_library import analyze_library
from smart_reframe import track_subject
from video_decode import decodable_path


class VideoDecodeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proxies = self.root / "прокси"
        environment = patch.dict(os.environ, {"BEAT_SYNC_PROXY_DIR": str(self.proxies)})
        environment.start()
        self.addCleanup(environment.stop)
        video_decode._CHECKED.clear()
        self.addCleanup(video_decode._CHECKED.clear)

    def make_video(self, path, frames=30, fps=15, size=(320, 180)):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
        self.assertTrue(writer.isOpened())
        for number in range(frames):
            frame = np.full((size[1], size[0], 3), 25, np.uint8)
            left = 10 + number * (size[0] - 70) // frames
            cv2.rectangle(frame, (left, size[1] // 3), (left + 50, 2 * size[1] // 3), (240, 240, 240), -1)
            writer.write(frame)
        writer.release()
        return path

    def unreadable(self, source):
        """Pretend OpenCV cannot decode `source`, as with AV1 in the opencv-python wheels."""
        real = video_decode._opencv_can_decode
        blocked = Path(source).resolve()
        return patch.object(video_decode, "_opencv_can_decode",
                            side_effect=lambda path: Path(path).resolve() != blocked and real(path))

    @staticmethod
    def frames(path):
        capture = cv2.VideoCapture(str(path))
        try:
            count, fps = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), capture.get(cv2.CAP_PROP_FPS)
            images = []
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                images.append(frame)
            return count, fps, images
        finally:
            capture.release()

    def test_readable_source_is_used_as_is(self):
        source = self.make_video(self.root / "обычный.avi")
        self.assertEqual(decodable_path(source), str(source.resolve()))
        self.assertFalse(self.proxies.exists() and any(self.proxies.iterdir()))

    def test_unreadable_source_gets_a_frame_identical_cached_proxy(self):
        source = self.make_video(self.root / "без декодера.avi")
        with self.unreadable(source):
            proxy = Path(decodable_path(source))
            self.assertEqual(proxy.parent, self.proxies.resolve())
            self.assertNotEqual(proxy, source.resolve())
            count, fps, images = self.frames(source)
            proxy_count, proxy_fps, proxy_images = self.frames(proxy)
            self.assertEqual((proxy_count, len(proxy_images)), (count, len(images)))
            self.assertAlmostEqual(proxy_fps, fps, places=3)
            for index in (0, len(images) // 2, len(images) - 1):
                self.assertEqual(proxy_images[index].shape, images[index].shape)
                difference = np.mean(cv2.absdiff(proxy_images[index], images[index]))
                self.assertLess(difference, 6, f"frame {index} of the proxy shows other content")
            # A later process finds the proxy on disk and does not encode again.
            video_decode._CHECKED.clear()
            with patch.object(video_decode.subprocess, "run", side_effect=AssertionError("proxy was rebuilt")):
                self.assertEqual(Path(decodable_path(source)), proxy)

    def test_changed_source_gets_a_new_proxy(self):
        source = self.make_video(self.root / "clip.avi")
        with self.unreadable(source):
            first = decodable_path(source)
            self.make_video(source, frames=12)
            os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 5_000_000_000))
            second = decodable_path(source)
            self.assertNotEqual(first, second)
            self.assertEqual(self.frames(second)[0], 12)

    def test_tall_source_is_downscaled_without_losing_frames(self):
        source = self.make_video(self.root / "tall.avi", frames=8, fps=8, size=(404, 720))
        with self.unreadable(source):
            count, _, images = self.frames(decodable_path(source))
        self.assertEqual((count, len(images)), (8, 8))
        self.assertEqual(images[0].shape[0], 540)
        self.assertEqual(images[0].shape[1] % 2, 0)
        self.assertAlmostEqual(images[0].shape[1] / 540, 404 / 720, delta=.01)

    def test_undecodable_file_is_an_ffmpeg_failure_with_its_path(self):
        broken = self.root / "сломан.mp4"
        broken.write_bytes(b"not a video")
        # RuntimeError is what the CLI reports as an FFmpeg failure (exit code 4).
        with self.unreadable(broken), self.assertRaisesRegex(RuntimeError, "сломан"):
            decodable_path(broken)
        self.assertFalse(any(self.proxies.iterdir()), "a failed build must not leave a partial proxy")

    def test_missing_ffmpeg_is_reported_with_the_source(self):
        source = self.make_video(self.root / "clip.avi")
        with self.unreadable(source), patch.object(video_decode.subprocess, "run", side_effect=FileNotFoundError("ffmpeg")):
            with self.assertRaisesRegex(RuntimeError, "FFmpeg could not be started"):
                decodable_path(source)

    def ffmpeg(self, *arguments):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", *arguments], check=True, capture_output=True)

    @staticmethod
    def timestamps(path):
        listed = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                 "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path)],
                                check=True, capture_output=True, text=True).stdout
        return [float(line.strip(",")) for line in listed.split() if line.strip(",")]

    def test_odd_height_source_gets_a_proxy_with_every_frame(self):
        source = self.root / "нечётный.avi"   # cv2.VideoWriter would round 181 down, FFmpeg does not
        self.ffmpeg("-f", "lavfi", "-i", "testsrc=s=320x181:r=10:d=1", "-c:v", "mjpeg", str(source))
        with self.unreadable(source):
            count, _, images = self.frames(decodable_path(source))
        self.assertEqual((count, len(images)), (10, 10))
        self.assertEqual(images[0].shape[:2], (180, 318))

    def test_variable_frame_rate_keeps_source_timestamps(self):
        source = self.root / "переменная частота.mkv"
        listed = subprocess.run(["ffmpeg", "-hide_banner", "-h", "full"], capture_output=True, text=True).stdout
        sync = ["-fps_mode", "vfr"] if "-fps_mode" in listed else ["-vsync", "vfr"]
        # Frames 0-9 of a 30 fps clip, then every fifth, each odd one 12 ms late: gaps of about 22/45 ms,
        # then 155-179 ms, off any 1/30 s grid, so a proxy on the encoder's own time base would move them.
        self.ffmpeg("-f", "lavfi", "-i", "testsrc=s=160x90:r=30:d=2", "-vf",
                    "select='lt(n,10)+not(mod(n,5))',settb=1/1000,setpts='PTS+12*mod(N,2)'",
                    *sync, "-enc_time_base", "1/1000", "-c:v", "mjpeg", str(source))
        expected = self.timestamps(source)
        self.assertGreater(max(np.diff(expected)) / min(np.diff(expected)), 3, "fixture is not variable frame rate")
        with self.unreadable(source):
            measured = self.timestamps(decodable_path(source))
        self.assertEqual(len(measured), len(expected))
        self.assertLess(max(abs(a - b) for a, b in zip(measured, expected)), .0015)

    def build_with(self, answers):
        """Build a proxy with an FFmpeg that rejects some options, as other releases do."""
        source = self.make_video(self.root / "clip.avi")
        real, calls = subprocess.run, []

        def other_release(arguments, **options):
            calls.append(arguments)
            for rejected, message in answers:
                if all(part in arguments for part in rejected):
                    return subprocess.CompletedProcess(arguments, 1, "", message)
            return real(arguments, **options)

        with self.unreadable(source), patch.object(video_decode.subprocess, "run", side_effect=other_release):
            proxy = decodable_path(source)
        self.assertEqual(self.frames(proxy)[0], 30)
        return calls

    def test_current_ffmpeg_gets_only_options_it_still_accepts(self):
        # FFmpeg 9 removed "-vsync" and rejects "-enc_time_base -1".
        removed = [(["-vsync"], "Unrecognized option 'vsync'.\n"), (["-enc_time_base", "-1"], "Invalid time base: -1\n")]
        calls = self.build_with(removed)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("-enc_time_base") + 1], "demux")
        self.assertIn("-fps_mode", calls[0])

    def test_ffmpeg_before_6_1_is_retried_with_the_numeric_time_base(self):
        calls = self.build_with([(["-enc_time_base", "demux"], "Invalid time base: demux\n")])
        self.assertEqual([call[call.index("-enc_time_base") + 1] for call in calls], ["demux", "-1"])
        self.assertTrue(all("-fps_mode" in call for call in calls))

    def test_ffmpeg_before_5_1_is_retried_with_vsync(self):
        unknown = "Unrecognized option 'fps_mode'.\nError splitting the argument list: Option not found\n"
        calls = self.build_with([(["-fps_mode"], unknown), (["-enc_time_base", "demux"], "Invalid time base: demux\n")])
        self.assertEqual(["-fps_mode" in call for call in calls], [True, False])
        self.assertEqual(calls[1][calls[1].index("-vsync") + 1], "0")
        self.assertEqual(calls[1][calls[1].index("-enc_time_base") + 1], "-1")

    def test_two_runs_building_the_same_proxy_do_not_share_a_partial_file(self):
        source = self.make_video(self.root / "clip.avi")
        seen = []

        def other_run_wins(partial, proxy):
            seen.append(Path(partial).name)
            shutil.copyfile(partial, proxy)          # the other run published its finished proxy first...
            raise PermissionError("in use")           # ...and keeps it open, so this rename fails (Windows)

        with self.unreadable(source), patch.object(video_decode.os, "replace", side_effect=other_run_wins):
            proxy = Path(decodable_path(source))
        self.assertIn(f".{os.getpid()}.partial.mp4", seen[0])
        self.assertEqual(self.frames(proxy)[0], 30)
        self.assertEqual([path.name for path in self.proxies.iterdir()], [proxy.name])

    def test_unwritable_folder_falls_back_to_the_user_cache(self):
        cache = self.root / "кеш"
        real = tempfile.TemporaryFile

        def read_only_first(*arguments, **options):
            if Path(options["dir"]) == self.proxies:
                raise PermissionError("read-only")
            return real(*arguments, **options)

        with patch.object(speech_transcribe, "_user_cache_dir", return_value=cache), \
                patch.object(video_decode.tempfile, "TemporaryFile", side_effect=read_only_first):
            self.assertEqual(video_decode._proxy_dir(), (cache / "beat-sync-edit" / "decode-proxies").resolve())

    def test_building_prunes_only_stale_proxies_of_its_own(self):
        self.proxies.mkdir()
        day = 86400
        stale, abandoned = "0" * 20 + ".mp4", "1" * 20 + ".123.partial.mp4"
        recent, running = "2" * 20 + ".mp4", "3" * 20 + ".456.partial.mp4"
        # The folder may be one the user also keeps footage in: nothing but this module's files may go.
        foreign = ["отпуск 2019.mp4", "final_export.7.partial.mp4", "0123456789abcdef0123.MP4", "заметка.txt"]
        ages = {stale: 40 * day, abandoned: 2 * day, recent: day, running: 60, **{name: 400 * day for name in foreign}}
        for name, age in ages.items():
            (self.proxies / name).write_bytes(b"x")
            os.utime(self.proxies / name, (time.time() - age,) * 2)
        source = self.make_video(self.root / "clip.avi")
        with self.unreadable(source):
            proxy = Path(decodable_path(source))
        self.assertEqual({path.name for path in self.proxies.iterdir()}, {proxy.name, recent, running, *foreign})

    def test_proxy_pruned_by_another_run_is_built_again(self):
        source = self.make_video(self.root / "clip.avi")
        with self.unreadable(source):
            proxy = Path(decodable_path(source))
            video_decode._CHECKED.clear()
            real, state = os.utime, {"pruned": False}

            def pruned_meanwhile(path, *arguments, **options):
                if not state["pruned"]:        # the other run deletes the stale proxy right after our check
                    state["pruned"] = True
                    Path(path).unlink()
                    raise FileNotFoundError(path)
                return real(path, *arguments, **options)

            with patch.object(video_decode.os, "utime", side_effect=pruned_meanwhile):
                again = Path(decodable_path(source))
        self.assertEqual(again, proxy)
        self.assertEqual(self.frames(again)[0], 30)

    def test_changed_recipe_does_not_reuse_older_proxies(self):
        source = self.make_video(self.root / "clip.avi")
        with self.unreadable(source):
            first = decodable_path(source)
            video_decode._CHECKED.clear()
            with patch.object(video_decode, "PROXY_RECIPE", "another recipe"):
                self.assertNotEqual(decodable_path(source), first)

    def test_real_av1_source_is_analyzed_and_tracked(self):
        listed = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        options = {"libsvtav1": ["-preset", "12"], "librav1e": ["-speed", "10"], "libaom-av1": ["-cpu-used", "8"]}
        encoder = next((name for name in options if f" {name} " in listed), None)
        if encoder is None:
            self.skipTest("this FFmpeg has no AV1 encoder")
        source = self.root / "запись.webm"
        self.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-c:v", encoder, *options[encoder], str(source))
        # OpenCV's FFmpeg prints three lines to the real stderr for every AV1 file it cannot decode.
        saved, null = os.dup(2), os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 2)
        try:
            library = analyze_library([str(source)], str(self.root / "work"))
            track = track_subject(source, 0, 2, sample_fps=5)
        finally:
            os.dup2(saved, 2)
            os.close(saved)
            os.close(null)
        self.assertEqual({clip["source"] for clip in library["clips"]}, {str(source.resolve())})
        self.assertAlmostEqual(max(clip["end"] for clip in library["clips"]), 2, delta=.1)
        self.assertTrue(all(Path(clip["thumb"]).is_file() for clip in library["clips"]))
        self.assertGreaterEqual(len(track), 5)

    def test_library_and_tracking_measure_the_proxy_but_keep_the_source(self):
        source = self.make_video(self.root / "исходник.avi", frames=45)
        with self.unreadable(source):
            library = analyze_library([str(source)], str(self.root / "work"))
            track = track_subject(source, 0, 3, subject=[10 / 320, 60 / 180, 50 / 320, 60 / 180], sample_fps=5)
        self.assertEqual([clip["source"] for clip in library["clips"]], [str(source.resolve())])
        self.assertEqual(library["assets"][0]["path"], str(source.resolve()))
        self.assertTrue(Path(library["clips"][0]["thumb"]).is_file())
        self.assertTrue(any(self.proxies.iterdir()))
        self.assertGreater(track[-1]["cx"] - track[0]["cx"], .4)


if __name__ == "__main__":
    unittest.main()

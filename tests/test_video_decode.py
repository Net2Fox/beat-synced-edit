"""Sources OpenCV cannot decode are measured through a frame-identical FFmpeg proxy."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import _paths  # noqa: F401  (makes the skill's scripts importable)
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
            self.assertEqual(proxy.parent, self.proxies)
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

    def test_undecodable_file_fails_with_its_path(self):
        broken = self.root / "сломан.mp4"
        broken.write_bytes(b"not a video")
        with self.unreadable(broken), self.assertRaisesRegex(ValueError, "сломан"):
            decodable_path(broken)
        self.assertFalse(any(self.proxies.iterdir()), "a failed build must not leave a partial proxy")

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

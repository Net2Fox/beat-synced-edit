"""Real mixed-media ingestion, stable identities, ZIP safety and annotations."""

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_library import analyze_library, apply_annotations, discover_media, extract_zip, probe_media


class MediaLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "исходники"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def make_video(self, path, fps=10, size=(160, 90)):
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
        self.assertTrue(writer.isOpened())
        for number in range(fps):
            frame = np.full((size[1], size[0], 3), (30, 70, 140), np.uint8)
            cv2.rectangle(frame, (10 + number * 5, 25), (35 + number * 5, 60), (240, 240, 240), -1)
            writer.write(frame)
        writer.release()

    def test_unicode_mixed_sources_duplicate_basenames_and_annotations(self):
        first = self.root / "камера 1" / "кадр.avi"
        second = self.root / "камера 2" / "кадр.avi"
        self.make_video(first, fps=10)
        self.make_video(second, fps=20, size=(128, 96))
        photo = self.root / "фото.png"
        Image.new("RGB", (120, 200), (30, 80, 190)).save(photo)
        work = self.root / "работа"
        library = analyze_library([str(self.root), str(first)], str(work))
        self.assertEqual(len(library["assets"]), 3)
        self.assertEqual(len({asset["id"] for asset in library["assets"]}), 3)
        self.assertEqual({asset["fps"] for asset in library["assets"]}, {0.0, 10.0, 20.0})
        self.assertTrue(all(Path(asset["path"]).is_absolute() for asset in library["assets"]))
        self.assertTrue(all(Path(clip["thumb"]).is_file() for clip in library["clips"]))
        self.assertTrue(all(Path(clip["subject_thumb"]).is_file() for clip in library["clips"]))
        self.assertTrue(all(clip["start"] <= clip["subject_thumb_time"] <= clip["thumb_time"] <= clip["end"]
                            for clip in library["clips"]))
        self.assertTrue(Path(library["contact_sheet"]).is_file())
        self.assertTrue(all(clip["tags"] == [] and clip["shot_type"] == "unknown" for clip in library["clips"]))
        self.assertTrue(all(len(clip["visual_hash"]) == 16 for clip in library["clips"]))
        video = next(clip for clip in library["clips"] if clip["kind"] == "video")
        notes = {"clips": {video["id"]: {"tags": ["car", "driving"], "shot_type": "wide", "subject": [.1, .2, .2, .5], "action_time": .5}}}
        annotations = self.root / "annotations.json"
        annotations.write_text(json.dumps(notes), encoding="utf-8")
        annotated = analyze_library([str(self.root)], str(work), str(annotations))
        found = next(clip for clip in annotated["clips"] if clip["id"] == video["id"])
        self.assertEqual(found["tags"], ["car", "driving"])
        self.assertEqual(found["subject"], [.1, .2, .2, .5])
        self.assertEqual(len(annotated["assets"]), 3, "Generated thumbnails must not be reimported")

    def test_zip_is_persistent_and_stable(self):
        zip_path = self.root / "сцены.zip"
        photo = self.root / "источник.png"
        Image.new("RGB", (120, 80), "orange").save(photo)
        with zipfile.ZipFile(zip_path, "w") as zipped:
            zipped.write(photo, "набор/фото.png")
        work = self.root / "work"
        files = discover_media([str(zip_path)], str(work))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].is_relative_to(work))
        self.assertTrue(files[0].is_file())
        self.assertEqual(files, discover_media([str(zip_path)], str(work)))

    def test_archive_rejects_escaping_members_before_writing_files(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/escape.txt", "..\\escape.txt", "safe/CON.txt"):
            with self.subTest(name=name):
                archive = self.root / "bad.zip"
                with zipfile.ZipFile(archive, "w") as zipped:
                    zipped.writestr("normal.txt", "should not be extracted")
                    zipped.writestr(name, "no")
                with self.assertRaises(ValueError):
                    extract_zip(archive, self.root / "work")
        self.assertFalse(list((self.root / "work").rglob("normal.txt")))

    def test_zip_rejects_symlink_and_declared_size_limit(self):
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(entry, "../../outside")
        with self.assertRaises(ValueError):
            extract_zip(archive, self.root / "work")
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("large.txt", "123456789")
        with self.assertRaises(ValueError):
            extract_zip(archive, self.root / "work", max_bytes=8)

    def test_image_exif_orientation_is_display_orientation(self):
        path = self.root / "повернуто.jpg"
        image = Image.new("RGB", (160, 90), "red")
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, exif=exif)
        asset = probe_media(path)
        self.assertEqual((asset["width"], asset["height"]), (90, 160))

    def test_rotated_video_probe_and_subject_thumbnail_match_display(self):
        source = self.root / "source.avi"
        self.make_video(source)
        base = self.root / "base.mp4"
        rotated = self.root / "rotated.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", str(base), "-c", "copy", str(rotated)], check=True)
        library = analyze_library([str(rotated)], self.root / "work")
        asset = library["assets"][0]
        self.assertEqual((asset["width"], asset["height"]), (90, 160))
        self.assertEqual(abs(asset["rotation"]), 90)
        with Image.open(library["clips"][0]["subject_thumb"]) as image:
            self.assertEqual(image.size, (90, 160))

    def test_missing_and_corrupt_sources_fail_clearly(self):
        with self.assertRaises(FileNotFoundError):
            discover_media([str(self.root / "missing.mp4")], self.root / "work")
        (self.root / "not-media.txt").write_text("hi", encoding="utf-8")
        with self.assertRaises(ValueError):
            discover_media([str(self.root)], self.root / "work")
        broken = self.root / "broken.mp4"
        broken.write_bytes(b"not a video")
        with self.assertRaises(subprocess.CalledProcessError):
            probe_media(broken)

    def test_annotations_reject_invalid_geometry_and_source_replacement(self):
        clip = {"id": "a:0", "start": 3.0, "end": 5.0, "source": "/original"}
        bad_values = [{"subject": [.9, .2, .3, .4]}, {"action_time": 1}, {"source": "/other"}, {"tags": "car"}, {"exclude": "false"}]
        for values in bad_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                apply_annotations([dict(clip)], {"a:0": values})
        with self.assertRaises(ValueError):
            apply_annotations([clip], {"unknown": {"tags": []}})
        with self.assertRaises(ValueError):
            apply_annotations([clip], [])


if __name__ == "__main__":
    unittest.main()

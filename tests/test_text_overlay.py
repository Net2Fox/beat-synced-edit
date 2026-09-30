"""Pixel-level Unicode typography, safe-area and cue-timing regression tests."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from text_overlay import TextCompositor, validate_text_tracks


class TextOverlayTests(unittest.TestCase):
    def plan(self, text="Привет, мир!", track="subtitles", style=None):
        cue = {"id": "cue-1", "text": text, "start_frame": 5, "end_frame": 25}
        if style is not None:
            cue["style"] = style
        return {"output": {"width": 1080, "height": 1920, "fps": 30}, "duration_frames": 60, track: [cue]}

    @staticmethod
    def bounds(frame):
        yy, xx = np.where(frame.max(axis=2) > 0)
        return xx.min(), yy.min(), xx.max(), yy.max()

    def test_unicode_visible_only_in_end_exclusive_frame_range(self):
        plan = self.plan()
        renderer = TextCompositor(plan, 360, 640)
        black = np.zeros((640, 360, 3), np.uint8)
        self.assertIs(renderer.apply(black, 4), black)
        self.assertGreater(renderer.apply(black, 5).max(), 200)
        self.assertGreater(renderer.apply(black, 24).max(), 200)
        self.assertIs(renderer.apply(black, 25), black)
        # Different Cyrillic letters produce different glyph pixels, not a
        # repeated missing-glyph box from an ASCII-only fallback font.
        first = TextCompositor(self.plan("ШЩШЩ"), 360, 640).apply(black, 10)
        second = TextCompositor(self.plan("АБАБ"), 360, 640).apply(black, 10)
        self.assertFalse(np.array_equal(first, second))

    def test_long_line_and_long_unbroken_word_fit_without_truncating(self):
        text = "Очень длинный заголовок " + "Длинноесловобезпробелов"*5
        renderer = TextCompositor(self.plan(text, "titles", {"max_lines": 4}), 360, 640)
        rendered = renderer.apply(np.zeros((640, 360, 3), np.uint8), 10)
        x0, y0, x1, y1 = self.bounds(rendered)
        self.assertGreaterEqual(x0, 360*.09-1)
        self.assertLessEqual(x1, 360*.91+1)
        self.assertGreaterEqual(y0, 640*.09-1)
        self.assertLessEqual(y1, 640*.91+1)
        all_indexes = {index for line, *_ in renderer.cues[0].lines for _, index in line}
        self.assertTrue(all(i in all_indexes for i, c in enumerate(text) if not c.isspace()))

    def test_preview_typography_scales_with_full_resolution(self):
        plan = self.plan("Hello / Привет", style={"font_size": 60, "stroke_width": 3})
        full = TextCompositor(plan, 1080, 1920).apply(np.zeros((1920, 1080, 3), np.uint8), 10)
        preview = TextCompositor(plan, 360, 640).apply(np.zeros((640, 360, 3), np.uint8), 10)
        for a, b in zip(self.bounds(full), self.bounds(preview)):
            self.assertLess(abs(a/3-b), 4)

    def test_titles_and_subtitles_default_to_separate_safe_areas(self):
        plan = self.plan("Это субтитр")
        plan["titles"] = [{"id": "same-id-other-track", "text": "Это титр", "start_frame": 0, "end_frame": 60}]
        renderer = TextCompositor(plan, 360, 640)
        frame = renderer.apply(np.zeros((640, 360, 3), np.uint8), 10)
        self.assertGreater(frame[:200].sum(), 0)
        self.assertEqual(frame[220:400].sum(), 0)
        self.assertGreater(frame[420:].sum(), 0)
        self.assertEqual(frame[590:].sum(), 0)

    def test_literal_markup_backslashes_percent_and_quotes_are_glyphs(self):
        text = "<b>Hi</b> {\\an8} 50% ' : & \\n"
        renderer = TextCompositor(self.plan(text, "titles"), 360, 640)
        joined = "".join(content for _, content, *_ in renderer.cues[0].lines)
        self.assertIn("<b>Hi</b>", joined)
        self.assertIn("{\\an8}", joined)
        self.assertIn("50%", joined)
        self.assertGreater(renderer.apply(np.zeros((640, 360, 3), np.uint8), 10).sum(), 0)

    def test_fade_slide_and_opacity_change_actual_pixels(self):
        black = np.zeros((640, 360, 3), np.uint8)
        for animation in ("fade", "slide"):
            renderer = TextCompositor(self.plan("Motion", "titles", {"animation": animation, "fade_frames": 5}), 360, 640)
            early, middle, late = (renderer.apply(black, i) for i in (5, 12, 24))
            self.assertLess(early.sum(), middle.sum())
            self.assertLess(late.sum(), middle.sum())
            if animation == "slide":
                self.assertGreater(self.bounds(early)[1], self.bounds(middle)[1])
        invisible = TextCompositor(self.plan(style={"opacity": 0}), 360, 640)
        self.assertEqual(invisible.apply(black, 10).sum(), 0)

    def test_word_highlight_follows_supplied_word_timing_and_gaps(self):
        plan = self.plan("Первое второе", style={"highlight": True, "stroke_width": 0, "background": None})
        plan["subtitles"][0]["words"] = [{"text": "Первое", "start_frame": 5, "end_frame": 10},
                                                {"text": "второе", "start_frame": 12, "end_frame": 20}]
        compositor = TextCompositor(plan, 360, 640)
        black = np.zeros((640, 360, 3), np.uint8)
        first, gap, second = (compositor.apply(black, i) for i in (6, 11, 14))
        def colored_x(image):
            mask = (image[..., 2].astype(int)-image[..., 0].astype(int)) > 80
            return np.where(mask)[1]
        self.assertGreater(len(colored_x(first)), 10)
        self.assertEqual(len(colored_x(gap)), 0)
        self.assertGreater(colored_x(second).mean(), colored_x(first).mean())

    def test_subtitle_overlap_rejected_but_titles_can_overlap(self):
        plan = self.plan()
        plan["subtitles"].append({"id": "cue-2", "text": "Overlap", "start_frame": 24, "end_frame": 30})
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_text_tracks(plan)
        plan["titles"] = plan.pop("subtitles")
        validate_text_tracks(plan)

    def test_bad_styles_and_ranges_fail_with_actionable_errors(self):
        for style, message in (({"font_size": float("nan")}, "finite"), ({"animation": "spin"}, "animation"),
                ({"color": "red"}, "#RRGGBB"), ({"max_lines": 1.5}, "integer"), ({"opacity": 3}, "opacity"),
                ({"unknown": 1}, "Unknown"), ({"font": "missing.ttf"}, "absolute")):
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, message):
                validate_text_tracks(self.plan(style=style))
        for field, value in (("start_frame", -1), ("start_frame", True), ("end_frame", 61),
                             ("end_frame", 5), ("text", " \n"), ("id", "")):
            plan = self.plan()
            plan["subtitles"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_text_tracks(plan)
        plan = self.plan()
        plan["subtitles"].append(copy.deepcopy(plan["subtitles"][0]))
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_text_tracks(plan)

    def test_words_must_be_ordered_within_cue_and_present_in_text(self):
        for words in ([{"text": "Nope", "start_frame": 5, "end_frame": 10}],
                      [{"text": "Привет", "start_frame": 3, "end_frame": 10}],
                      [{"text": "Привет", "start_frame": 5, "end_frame": 27}],
                      [{"text": "Привет", "start_frame": 5, "end_frame": 15},
                       {"text": "мир", "start_frame": 14, "end_frame": 25}]):
            plan = self.plan()
            plan["subtitles"][0]["words"] = words
            with self.assertRaises(ValueError):
                validate_text_tracks(plan)

    def test_text_absent_is_noop(self):
        validate_text_tracks({})
        blank = np.zeros((64, 36, 3), np.uint8)
        self.assertIs(TextCompositor({}, 36, 64).apply(blank, 0), blank)


if __name__ == "__main__":
    unittest.main()

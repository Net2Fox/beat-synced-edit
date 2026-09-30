#!/usr/bin/env python3
"""Validated, literal Unicode title/caption tracks composited with Pillow.

All timing is in project frames, with an inclusive start and exclusive end.
Pixel font sizes are relative to the project's full output size; previews scale
them automatically. No caption text is passed to a shell, FFmpeg filter or HTML.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

STYLE_KEYS = {"font", "font_size", "color", "highlight_color", "background",
              "stroke_color", "stroke_width", "position", "align", "max_width",
              "margin", "max_lines", "opacity", "animation", "fade_frames", "highlight"}


def _number(value, label, minimum, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label} must be between {minimum} and {maximum or 'infinity'}")
    if integer and int(value) != value:
        raise ValueError(f"{label} must be an integer")
    return int(value) if integer else float(value)


def _color(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        raise ValueError(f"{label} must be #RRGGBB or #RRGGBBAA")
    rgba = tuple(int(value[i:i+2], 16) for i in range(1, len(value), 2))
    return rgba if len(rgba) == 4 else (*rgba, 255)


def _style(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - STYLE_KEYS
    if unknown:
        raise ValueError(f"Unknown {label} keys: {', '.join(sorted(unknown))}")
    for key in ("color", "highlight_color", "stroke_color", "background"):
        if key in value and not (key == "background" and value[key] is None):
            _color(value[key], f"{label}.{key}")
    for key in ("position", "align", "animation"):
        allowed = {"position": ("top", "center", "bottom"), "align": ("left", "center", "right"),
                   "animation": ("none", "fade", "slide")}[key]
        if key in value and value[key] not in allowed:
            raise ValueError(f"{label}.{key} must be one of {', '.join(allowed)}")
    for key, low, high, integer in (("font_size", 1, 4096, False), ("stroke_width", 0, 100, False),
            ("max_width", .01, 1, False), ("margin", 0, .4, False), ("max_lines", 1, 100, True),
            ("opacity", 0, 1, False), ("fade_frames", 0, None, True)):
        if key in value:
            _number(value[key], f"{label}.{key}", low, high, integer)
    if "highlight" in value and not isinstance(value["highlight"], bool):
        raise ValueError(f"{label}.highlight must be a boolean")
    if "font" in value:
        font = value["font"]
        if not isinstance(font, str) or not Path(font).is_absolute() or not Path(font).is_file():
            raise ValueError(f"{label}.font must be an existing absolute font-file path")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise ValueError(f"{label} contains unsupported control characters")


def validate_text_tracks(plan):
    """Fail early for invalid cues/styles; existing plans need no text fields."""
    if not any(key in plan for key in ("titles", "subtitles", "title_style", "subtitle_style")):
        return
    duration = _number(plan.get("duration_frames"), "duration_frames", 1, integer=True)
    for track, global_key in (("titles", "title_style"), ("subtitles", "subtitle_style")):
        _style(plan.get(global_key, {}), global_key)
        cues = plan.get(track, [])
        if not isinstance(cues, list):
            raise ValueError(f"{track} must be a list")
        ids, ranges = set(), []
        for cue in cues:
            if not isinstance(cue, dict):
                raise ValueError(f"Each {track} cue must be an object")
            identifier = cue.get("id")
            if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
                raise ValueError(f"{track} cue ids must be nonempty unique strings")
            ids.add(identifier)
            label = f"{track}[{identifier}]"
            _text(cue.get("text"), f"{label}.text")
            start = _number(cue.get("start_frame"), f"{label}.start_frame", 0, duration-1, True)
            end = _number(cue.get("end_frame"), f"{label}.end_frame", start+1, duration, True)
            _style(cue.get("style", {}), f"{label}.style")
            ranges.append((start, end, identifier))
            words = cue.get("words", [])
            if not isinstance(words, list):
                raise ValueError(f"{label}.words must be a list")
            cursor, last_end = 0, start
            for word in words:
                if not isinstance(word, dict):
                    raise ValueError(f"{label} words must be objects")
                _text(word.get("text"), f"{label} word text")
                word_start = _number(word.get("start_frame"), f"{label} word start_frame", last_end, end-1, True)
                last_end = _number(word.get("end_frame"), f"{label} word end_frame", word_start+1, end, True)
                found = cue["text"].find(word["text"].strip(), cursor)
                if found < 0:
                    raise ValueError(f"{label} word text must appear in cue text in order")
                cursor = found + len(word["text"].strip())
        if track == "subtitles":
            ordered = sorted(ranges)
            for previous, following in zip(ordered, ordered[1:]):
                if following[0] < previous[1]:
                    raise ValueError(f"Subtitles overlap: {previous[2]} and {following[2]}; adjust their frame ranges")


def _font_path(explicit=None):
    if explicit:
        return explicit
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts/arial.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts/segoeui.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    try:
        ImageFont.truetype("DejaVuSans.ttf", 16)
        return "DejaVuSans.ttf"
    except OSError as exc:
        raise ValueError("No Unicode font found; set style.font to an absolute TrueType/OpenType font path") from exc


def _wrap(text, font, max_width):
    """Wrap without truncation, retaining original indexes for word highlighting."""
    lines, current = [], []
    for index, character in enumerate(text):
        if character == "\r":
            continue
        if character == "\n":
            lines.append(current)
            current = []
            continue
        character = " " if character.isspace() else character
        if not current and character == " ":
            continue
        current.append((character, index))
        if font.getlength("".join(c for c, _ in current)) > max_width:
            split = max((i for i, (c, _) in enumerate(current[:-1]) if c == " "), default=-1)
            if split >= 0:
                lines.append(current[:split])
                current = current[split+1:]
            elif len(current) > 1:
                lines.append(current[:-1])
                current = current[-1:]
    if current or not lines:
        lines.append(current)
    return [line[:next((i+1 for i in range(len(line)-1, -1, -1) if line[i][0] != " "), 0)] for line in lines]


class _Cue:
    def __init__(self, cue, style, width, height, scale, fps):
        self.start, self.end = int(cue["start_frame"]), int(cue["end_frame"])
        self.style = style
        self.fade = min((self.end-self.start)//2, int(style.get("fade_frames", max(1, round(fps*.15)))))
        self.height = height
        margin = style["margin"]
        safe_width = max(1, math.floor(width*min(style["max_width"], 1-2*margin)))
        safe_height = max(1, math.floor(height*(1-2*margin)))
        font_path = _font_path(style.get("font"))
        initial_size = max(1, round(style["font_size"]*scale))
        stroke = max(0, round(style["stroke_width"]*scale))
        # Shrink the complete cue when wrapping exceeds its safe area; never
        # discard a word or let a long unbroken token run off the screen.
        for size in range(initial_size, 0, -1):
            font = ImageFont.truetype(font_path, size)
            padding = max(1, round(size*.32)) + stroke
            max_text_width = safe_width-2*padding
            if max_text_width <= 0:
                continue
            lines = _wrap(cue["text"], font, max_text_width)
            line_height = max(round(size*1.3), font.getbbox("ÁgjЙр", anchor="lt")[3])+2*stroke
            widest = max((font.getlength("".join(c for c, _ in line)) for line in lines), default=0)
            if len(lines) <= style["max_lines"] and widest <= max_text_width and len(lines)*line_height+2*padding <= safe_height:
                break
        else:
            raise ValueError(f"Text cue {cue['id']} cannot fit its safe area; shorten it, increase max_lines or reduce margins/stroke")
        self.width = min(safe_width, math.ceil(widest)+2*padding)
        self.h = len(lines)*line_height+2*padding
        self.base = Image.new("RGBA", (self.width, self.h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(self.base)
        if style["background"] is not None:
            draw.rounded_rectangle((0, 0, self.width-1, self.h-1), radius=max(1, size//4), fill=_color(style["background"], "background"))
        self.lines = []
        for row, chars in enumerate(lines):
            content = "".join(c for c, _ in chars)
            line_width = font.getlength(content)
            x = {"left": padding, "center": (self.width-line_width)/2,
                 "right": self.width-padding-line_width}[style["align"]]
            y = padding+row*line_height
            draw.text((x, y), content, font=font, anchor="lt", fill=_color(style["color"], "color"),
                      stroke_width=stroke, stroke_fill=_color(style["stroke_color"], "stroke_color"))
            self.lines.append((chars, content, x, y))
        self.x = {"left": round(width*margin), "center": (width-self.width)//2,
                  "right": round(width*(1-margin))-self.width}[style["align"]]
        self.y = {"top": round(height*margin), "center": (height-self.h)//2,
                  "bottom": min(round(height*.82-self.h/2), math.floor(height*(1-margin))-self.h)}[style["position"]]
        self.y = max(math.ceil(height*margin), min(self.y, math.floor(height*(1-margin))-self.h))
        self.words, cursor = [], 0
        for word in cue.get("words", []):
            text = word["text"].strip()
            offset = cue["text"].find(text, cursor)
            self.words.append((int(word["start_frame"]), int(word["end_frame"]), offset, offset+len(text)))
            cursor = offset+len(text)
        self.font, self.stroke = font, stroke
        self.cached_word, self.cached_image = None, None

    def image(self, index):
        active = next((i for i, word in enumerate(self.words) if word[0] <= index < word[1]), None) if self.style["highlight"] else None
        if active is None:
            result = self.base
        elif active == self.cached_word:
            result = self.cached_image
        else:
            result = self.base.copy()
            _, _, start, end = self.words[active]
            for chars, content, x, y in self.lines:
                marked = [i for i, (_, original_index) in enumerate(chars) if start <= original_index < end]
                if not marked:
                    continue
                # Clip a full-line colored raster to the word, preserving the
                # font's shaping/kerning instead of re-laying out each word.
                painted = Image.new("RGBA", result.size, (0, 0, 0, 0))
                ImageDraw.Draw(painted).text((x, y), content, font=self.font, anchor="lt",
                    fill=_color(self.style["highlight_color"], "highlight_color"), stroke_width=self.stroke,
                    stroke_fill=_color(self.style["stroke_color"], "stroke_color"))
                left = max(0, math.floor(x+self.font.getlength(content[:marked[0]]))-self.stroke)
                right = min(self.width, math.ceil(x+self.font.getlength(content[:marked[-1]+1]))+self.stroke)
                top, bottom = max(0, math.floor(y)-self.stroke), min(self.h, math.ceil(y+self.font.size*1.5)+self.stroke)
                result.alpha_composite(painted.crop((left, top, right, bottom)), (left, top))
            self.cached_word, self.cached_image = active, result
        alpha = self.style["opacity"]
        progress = min(1, (index-self.start+1)/max(1, self.fade), (self.end-index)/max(1, self.fade))
        animated = self.style["animation"] != "none" and self.fade > 0
        if animated:
            alpha *= progress
        if alpha < 1:
            result = result.copy()
            result.putalpha(result.getchannel("A").point(lambda value: round(value*alpha)))
        dy = round(self.height*.025*(1-progress)) if self.style["animation"] == "slide" and animated else 0
        # Slide motion stays inside the safe area even for bottom-aligned text.
        bottom_limit = math.floor(self.height*(1-self.style["margin"]))-self.h
        return result, self.x, min(self.y+dy, bottom_limit)


class TextCompositor:
    """Compile track typography once, then overlay active cues on BGR frames."""

    def __init__(self, plan, width, height):
        validate_text_tracks(plan)
        self.width, self.height = width, height
        output = plan.get("output", {})
        full_width, full_height = output.get("width", 1080), output.get("height", 1920)
        base = min(full_width, full_height)
        scale = min(width/full_width, height/full_height)
        fps = output.get("fps", 30)
        self.cues = []
        for track, key in (("titles", "title_style"), ("subtitles", "subtitle_style")):
            subtitle = track == "subtitles"
            defaults = {"font_size": base*(.055 if subtitle else .065), "color": "#FFFFFF",
                        "highlight_color": "#FFD633", "background": "#00000099" if subtitle else None,
                        "stroke_color": "#000000", "stroke_width": max(1, base*.0025),
                        "position": "bottom" if subtitle else "top", "align": "center",
                        "max_width": .82, "margin": .09, "max_lines": 3 if subtitle else 4,
                        "opacity": 1, "animation": "none", "highlight": False}
            for cue in plan.get(track, []):
                style = {**defaults, **plan.get(key, {}), **cue.get("style", {})}
                self.cues.append(_Cue(cue, style, width, height, scale, fps))

    def apply(self, frame_bgr, global_frame_index):
        if frame_bgr.shape != (self.height, self.width, 3) or frame_bgr.dtype != np.uint8:
            raise ValueError("Text compositor expects an output-sized uint8 BGR frame")
        active = [cue for cue in self.cues if cue.start <= global_frame_index < cue.end]
        if not active:
            return frame_bgr
        frame = Image.fromarray(frame_bgr[..., ::-1], "RGB").convert("RGBA")
        for cue in active:
            overlay, x, y = cue.image(global_frame_index)
            frame.alpha_composite(overlay, (x, y))
        return np.asarray(frame.convert("RGB"))[..., ::-1].copy()

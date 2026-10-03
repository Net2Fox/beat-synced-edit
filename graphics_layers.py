"""Frame-driven local graphic/video layers and reusable style data."""
from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from text_overlay import TextCompositor, _font_path, _color, _wrap

STYLES = {
    "clean": {"background": "#10151E", "foreground": "#FFFFFF", "accent": "#FFD633",
              "font_size": 58, "safe_area": {"left": .06, "right": .10, "top": .06, "bottom": .16}, "animation": "fade"},
    "editorial": {"background": "#F3EFE5", "foreground": "#122132", "accent": "#185CE5",
                  "font_size": 58, "safe_area": {"left": .07, "right": .07, "top": .06, "bottom": .14}, "animation": "slide"},
    "energetic": {"background": "#12101E", "foreground": "#FFFFFF", "accent": "#DDFF55",
                  "font_size": 64, "safe_area": {"left": .06, "right": .12, "top": .07, "bottom": .18}, "animation": "pop"},
}


def _number(value, name, low=0, high=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < low or (high is not None and value > high) or (integer and int(value) != value):
        raise ValueError(f"{name} must be a finite {'integer' if integer else 'number'} in {low}..{high}")
    return value


def validate_safe_area(area):
    if not isinstance(area, dict) or set(area) - {"left", "right", "top", "bottom"}:
        raise ValueError("safe_area accepts left/right/top/bottom fractions")
    for key, value in area.items():
        _number(value, f"safe_area.{key}", 0, .49)
    if area.get("left", 0) + area.get("right", 0) >= .9 or area.get("top", 0) + area.get("bottom", 0) >= .9:
        raise ValueError("safe_area leaves too little usable space")


def validate_style(style):
    if not isinstance(style, dict):
        raise ValueError("style must be an object")
    allowed = {"name", "background", "foreground", "accent", "font", "font_size", "safe_area", "animation"}
    if set(style) - allowed:
        raise ValueError(f"Unknown style keys: {sorted(set(style) - allowed)}")
    for key in ("background", "foreground", "accent"):
        if key in style:
            _color(style[key], key)
    if "font" in style and (not Path(style["font"]).is_absolute() or not Path(style["font"]).is_file()):
        raise ValueError("style.font must be an existing absolute font path")
    if "font_size" in style:
        _number(style["font_size"], "style.font_size", 1, 4096)
    if style.get("animation", "none") not in ("none", "fade", "slide", "pop"):
        raise ValueError("Unsupported style animation")
    validate_safe_area(style.get("safe_area", {}))


def apply_style(plan, name=None, values=None):
    if name is not None and name not in STYLES:
        raise ValueError(f"Unknown style: {name}")
    style = {**copy.deepcopy(STYLES.get(name, plan.get("style", STYLES["clean"]))), **(values or {})}
    if name:
        style["name"] = name
    validate_style(style)
    result = copy.deepcopy(plan)
    result["style"] = style
    for key in ("title_style", "subtitle_style"):
        result.setdefault(key, {}).update(color=style.get("foreground", "#FFFFFF"), highlight_color=style.get("accent", "#FFD633"),
                                         safe_area=style.get("safe_area", {}))
        for field in ("font", "font_size"):
            if field in style:
                result[key][field] = style[field]
    return result


def validate_graphics(plan):
    validate_style(plan.get("style", {}))
    layers = plan.get("graphics", [])
    if not isinstance(layers, list):
        raise ValueError("graphics must be a list")
    ids = set()
    duration = plan["duration_frames"]
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError("Each graphic must be an object")
        identity = layer.get("id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Graphics need unique nonempty IDs")
        ids.add(identity)
        kind = layer.get("kind", "card")
        if kind not in ("card", "image", "video", "counter", "bar", "rectangle"):
            raise ValueError(f"Unsupported graphic kind: {kind}")
        begin = _number(layer.get("start_frame"), "graphic start_frame", 0, duration - 1, True)
        _number(layer.get("end_frame"), "graphic end_frame", begin + 1, duration, True)
        rect = layer.get("rect", [.08, .12, .78, .25])
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError("graphic.rect must be normalized [x,y,width,height]")
        for i, value in enumerate(rect):
            _number(value, "graphic rect", 0 if i < 2 else .0001, 1)
        if rect[0] + rect[2] > 1.000001 or rect[1] + rect[3] > 1.000001:
            raise ValueError("Graphic rectangle lies outside the canvas")
        _number(layer.get("opacity", 1), "graphic.opacity", 0, 1)
        _number(layer.get("fade_frames", 6), "graphic.fade_frames", 0, None, True)
        _number(layer.get("font_size", plan.get("style", {}).get("font_size", 58)), "graphic.font_size", 1, 4096)
        for key in ("color", "background", "accent"):
            if key in layer:
                _color(layer[key], key)
        if layer.get("animation", plan.get("style", {}).get("animation", "fade")) not in ("none", "fade", "slide", "pop"):
            raise ValueError("Graphic animation must be none/fade/slide/pop")
        if kind in ("image", "video"):
            source = Path(layer.get("source", ""))
            if not source.is_absolute() or not source.is_file():
                raise ValueError("Graphic source must be an existing absolute image/video path")
        if kind == "video":
            _number(layer.get("source_start", 0), "graphic.source_start", 0)
            _number(layer.get("speed", 1), "graphic.speed", 1, 16)
        if kind in ("card", "counter") and not isinstance(layer.get("text", ""), str):
            raise ValueError("graphic.text must be text")
        if kind in ("counter", "bar"):
            for key, default in (("value_from", 0), ("value_to", 100)):
                _number(layer.get(key, default), "graphic." + key, -1e12, 1e12)
        if layer.get("fit", "contain") not in ("contain", "cover"):
            raise ValueError("graphic.fit must be contain or cover")
        if "font" in layer and (not Path(layer["font"]).is_absolute() or not Path(layer["font"]).is_file()):
            raise ValueError("graphic.font must be an existing absolute file")


def _text(canvas, text, font_path, size, fill):
    draw = ImageDraw.Draw(canvas)
    padding = max(4, min(canvas.size) // 12)
    for current in range(max(1, int(size)), 0, -1):
        font = ImageFont.truetype(font_path, current)
        lines = ["".join(c for c, _ in line) for line in _wrap(text, font, max(1, canvas.width - 2 * padding))]
        height = max(1, round(current * 1.35))
        if len(lines) * height <= canvas.height - 2 * padding:
            break
    else:
        raise ValueError("Graphic text cannot fit its rectangle")
    y = (canvas.height - len(lines) * height) // 2
    for line in lines:
        draw.text(((canvas.width - font.getlength(line)) / 2, y), line, font=font, anchor="lt", fill=fill)
        y += height


class GraphicsCompositor:
    def __init__(self, plan, width, height):
        validate_graphics(plan)
        self.plan, self.width, self.height = plan, width, height
        self.fps = plan["output"]["fps"]
        self.layers = copy.deepcopy(plan.get("graphics", []))
        self.images, self.readers = {}, {}
        self.scale = min(width / plan["output"]["width"], height / plan["output"]["height"])

    def _content(self, layer, index, width, height):
        kind = layer.get("kind", "card")
        style = self.plan.get("style", {})
        length = layer["end_frame"] - layer["start_frame"]
        progress = (index - layer["start_frame"]) / max(1, length - 1)
        if kind in ("image", "video"):
            if kind == "image":
                if layer["id"] not in self.images:
                    with Image.open(layer["source"]) as picture:
                        self.images[layer["id"]] = ImageOps.exif_transpose(picture).convert("RGBA")
                picture = self.images[layer["id"]]
            else:
                if layer["id"] not in self.readers:
                    from project_render import _VideoReader, probe
                    info = probe(layer["source"])
                    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
                    start = layer.get("source_start", 0)
                    stop = start + length / self.fps * layer.get("speed", 1)
                    source_duration = float(stream.get("duration") or info["format"].get("duration", 0))
                    if stop > source_duration + 1e-6:
                        raise ValueError(f"Graphic {layer['id']} exceeds source video duration")
                    self.readers[layer["id"]] = _VideoReader(layer["source"], start, stop, stream)
                frame = self.readers[layer["id"]].frame(layer.get("source_start", 0) + (index - layer["start_frame"]) / self.fps * layer.get("speed", 1))
                picture = Image.fromarray(frame[..., ::-1]).convert("RGBA")
            if layer.get("fit", "contain") == "cover":
                return ImageOps.fit(picture, (width, height), method=Image.Resampling.LANCZOS)
            fit = ImageOps.contain(picture, (width, height), method=Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            canvas.alpha_composite(fit, ((width - fit.width) // 2, (height - fit.height) // 2))
            return canvas
        background = _color(layer.get("background", style.get("background", "#10151E")), "background")
        canvas = Image.new("RGBA", (width, height), background)
        if kind == "bar":
            ratio = np.clip((layer.get("value_from", 0) + progress * (layer.get("value_to", 100) - layer.get("value_from", 0))) / 100, 0, 1)
            if ratio > 0:
                ImageDraw.Draw(canvas).rectangle((0, 0, max(0, round((width - 1) * ratio)), height - 1), fill=_color(layer.get("accent", style.get("accent", "#FFD633")), "accent"))
        elif kind in ("card", "counter"):
            text = layer.get("text", "")
            if kind == "counter":
                value = layer.get("value_from", 0) + progress * (layer.get("value_to", 100) - layer.get("value_from", 0))
                text = text.replace("{value}", str(round(value))) if "{value}" in text else f"{text}{round(value)}"
            _text(canvas, text, _font_path(layer.get("font", style.get("font"))),
                  layer.get("font_size", style.get("font_size", 58)) * self.scale,
                  _color(layer.get("color", style.get("foreground", "#FFFFFF")), "color"))
        return canvas

    def apply(self, frame, index):
        active = [layer for layer in self.layers if layer["start_frame"] <= index < layer["end_frame"]]
        if not active:
            return frame
        canvas = Image.fromarray(frame[..., ::-1]).convert("RGBA")
        for layer in active:
            x, y, w, h = layer.get("rect", [.08, .12, .78, .25])
            x, y, w, h = round(x * self.width), round(y * self.height), max(1, round(w * self.width)), max(1, round(h * self.height))
            content = self._content(layer, index, w, h)
            animation = layer.get("animation", self.plan.get("style", {}).get("animation", "fade"))
            fade = min(layer.get("fade_frames", 6), (layer["end_frame"] - layer["start_frame"]) // 2)
            progress = min(1, (index - layer["start_frame"] + 1) / max(1, fade), (layer["end_frame"] - index) / max(1, fade)) if animation != "none" and fade else 1
            alpha = layer.get("opacity", 1) * progress
            if animation == "slide":
                y = min(self.height - h, y + round((1 - progress) * self.height * .035))
            elif animation == "pop":
                factor = .85 + .15 * (1 - (1 - progress) ** 3)
                resized = content.resize((max(1, round(w * factor)), max(1, round(h * factor))), Image.Resampling.LANCZOS)
                x, y = x + (w - resized.width) // 2, y + (h - resized.height) // 2
                content = resized
            if alpha < 1:
                content.putalpha(content.getchannel("A").point(lambda v: round(v * alpha)))
            canvas.alpha_composite(content, (x, y))
        return np.asarray(canvas.convert("RGB"))[..., ::-1].copy()

    def close(self):
        for reader in self.readers.values():
            reader.close()
        self.readers.clear()


class ProjectCompositor:
    def __init__(self, plan, width, height):
        self.graphics = GraphicsCompositor(plan, width, height)
        self.text = TextCompositor(plan, width, height)

    def apply(self, frame, index):
        return self.text.apply(self.graphics.apply(frame, index), index)

    def close(self):
        self.graphics.close()

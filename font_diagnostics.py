"""Check a TrueType/OpenType Unicode cmap without adding a font-tool dependency."""
from __future__ import annotations

from pathlib import Path
import struct


def font_codepoints(path):
    data = Path(path).read_bytes()
    if data[:4] == b"ttcf":
        raise ValueError("Choose a single .ttf/.otf font; font collections need an explicit face")
    count = struct.unpack_from(">H", data, 4)[0]
    tables = {}
    for i in range(count):
        tag, checksum, offset, length = struct.unpack_from(">4sIII", data, 12 + i * 16)
        tables[tag] = (offset, length)
    if b"cmap" not in tables:
        raise ValueError("Font has no character map")
    base, length = tables[b"cmap"]
    maps = struct.unpack_from(">H", data, base + 2)[0]
    supported = set()
    found = False
    for i in range(maps):
        platform, encoding, relative = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
        if platform not in (0, 3) or (platform == 3 and encoding not in (1, 10)):
            continue
        offset = base + relative
        form = struct.unpack_from(">H", data, offset)[0]
        if form == 12:
            found = True
            groups = struct.unpack_from(">I", data, offset + 12)[0]
            for j in range(groups):
                start, end, glyph = struct.unpack_from(">III", data, offset + 16 + j * 12)
                if end > 0x10ffff or end < start:
                    raise ValueError("Invalid font cmap range")
                supported.update(range(start + (1 if glyph == 0 else 0), end + 1))
        elif form == 4:
            found = True
            segments = struct.unpack_from(">H", data, offset + 6)[0] // 2
            ends_at, starts_at = offset + 14, offset + 16 + segments * 2
            delta_at, ranges_at = starts_at + segments * 2, starts_at + segments * 4
            for j in range(segments):
                end = struct.unpack_from(">H", data, ends_at + j * 2)[0]
                start = struct.unpack_from(">H", data, starts_at + j * 2)[0]
                delta = struct.unpack_from(">h", data, delta_at + j * 2)[0]
                shift = struct.unpack_from(">H", data, ranges_at + j * 2)[0]
                for cp in range(start, min(end, 0xfffe) + 1):
                    glyph = ((cp + delta) & 0xffff) if not shift else struct.unpack_from(">H", data, ranges_at + j * 2 + shift + 2 * (cp - start))[0]
                    if shift and glyph:
                        glyph = (glyph + delta) & 0xffff
                    if glyph:
                        supported.add(cp)
    if not found:
        raise ValueError("No supported Unicode cmap (format 4 or 12) in font")
    return supported


def inspect_font(path, text):
    try:
        if not Path(path).is_file():
            from PIL import ImageFont
            path = ImageFont.truetype(str(path), 16).path
        points = font_codepoints(path)
    except (ValueError, OSError, struct.error) as exc:
        return {"font": str(path), "status": "unavailable", "error": str(exc), "missing": []}
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in points})
    return {"font": str(Path(path).resolve()), "status": "fail" if missing else "pass",
            "checked_characters": len({c for c in text if not c.isspace()}),
            "missing": [{"character": c, "codepoint": f"U+{ord(c):04X}"} for c in missing]}


def inspect_project_fonts(plan):
    from text_overlay import _font_path
    groups = {}
    for track, style in (("titles", "title_style"), ("subtitles", "subtitle_style")):
        for cue in plan.get(track, []):
            path = _font_path(cue.get("style", {}).get("font", plan.get(style, {}).get("font")))
            groups.setdefault(path, []).append(cue["text"])
    for graphic in plan.get("graphics", []):
        text = graphic.get("text", "")
        if graphic.get("kind") == "counter":
            text = text.replace("{value}", "") + "-0123456789"
        if text:
            path = _font_path(graphic.get("font", plan.get("style", {}).get("font")))
            groups.setdefault(path, []).append(text)
    return [inspect_font(path, "\n".join(texts)) for path, texts in groups.items()]

#!/usr/bin/env python3
"""Plain-text SRT/WebVTT interchange and frame-accurate subtitle segmentation.

Imported formatting is removed; cue text is data, never renderer instructions.
All cue ranges are half-open [start_frame, end_frame) on the project timeline.
"""

import html
import math
from pathlib import Path
import re


_TIMESTAMP = re.compile(r"^(?:(\d{2,}):)?(\d{2}):(\d{2})[.,](\d{3})$")
_STYLE_TAG = re.compile(
    r"</?(?:b|i|u|s|ruby|rt)\s*>|</?font(?:\s+[^<>]*)?>|"
    r"</?c(?:\.[^<>\s]+)*(?:\s+[^<>]*)?>|</?(?:v|lang)(?:\s+[^<>]*)?>|"
    r"<(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}>", re.IGNORECASE)
_PHRASE_END = re.compile(r"[.!?。！？;:…][\"'»”’)]*$")


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _timeline(plan, offset, timebase):
    if not isinstance(plan, dict):
        raise ValueError("plan must be a project object")
    fps = _positive_int(plan.get("output", {}).get("fps"), "project fps")
    count = _positive_int(plan.get("duration_frames"), "project duration_frames")
    if fps > 120:
        raise ValueError("project fps must not exceed 120")
    shift = _finite(offset, "offset")
    if timebase not in ("project", "soundtrack"):
        raise ValueError("timebase must be project or soundtrack")
    if timebase == "soundtrack":
        start = _finite(plan.get("audio", {}).get("start", 0), "audio.start")
        if start < 0:
            raise ValueError("audio.start must be nonnegative")
        shift -= start
    return fps, count, shift


def _time(value, context):
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError(f"{context}: invalid timestamp {value!r}; expected HH:MM:SS,mmm or MM:SS.mmm")
    hours, minutes, seconds, milliseconds = match.groups()
    if int(minutes) > 59 or int(seconds) > 59:
        raise ValueError(f"{context}: minutes and seconds must be in 00..59")
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def _text(value, context, markup=False):
    if not isinstance(value, str):
        raise ValueError(f"{context}: text must be a string")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if markup:
        # Strip only recognized presentation tags before decoding entities. This
        # preserves literal encoded angle brackets and unrecognized tags as text.
        text = html.unescape(_STYLE_TAG.sub("", text))
    text = "\n".join(line.strip() for line in text.strip().split("\n"))
    if not text or any(ord(char) < 32 and char not in "\n\t" for char in text):
        raise ValueError(f"{context}: subtitle text is empty or contains control characters")
    return text


def _frame_range(start, end, fps, count, shift=0):
    start, end = start + shift, end + shift
    if end <= 0 or start >= count / fps:
        return None
    # Round to the closest output frame (half up), keeping subframe cues visible
    # for at least one frame without extending beyond the project.
    first = min(count - 1, max(0, math.floor(start * fps + .5)))
    last = min(count, max(first + 1, math.floor(end * fps + .5)))
    return first, last


def import_subtitles(path, plan, offset=0, timebase="project"):
    """Import UTF-8 SRT/VTT, shift seconds, and clip cues to a project's frames.

    ``soundtrack`` timestamps refer to the untrimmed music source; its selected
    audio.start is subtracted before applying offset. Overlapping cues are kept.
    WebVTT NOTE/STYLE/REGION blocks and positioning settings are not imported.
    """
    fps, count, shift = _timeline(plan, offset, timebase)
    source = Path(path)
    try:
        content = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source.name}: subtitle file must be saved as UTF-8") from exc
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    is_vtt = bool(re.match(r"^WEBVTT(?:[ \t].*)?(?:\n|$)", content))
    if source.suffix.lower() == ".vtt" and not is_vtt:
        raise ValueError(f"{source.name}: WebVTT must begin with WEBVTT")
    if not content:
        return []
    blocks = re.split(r"\n[ \t]*\n", content)
    if is_vtt:
        header = blocks.pop(0)
        if "-->" in header:
            raise ValueError(f"{source.name}: WEBVTT header must be separated from cues by a blank line")
        if "X-TIMESTAMP-MAP" in header:
            raise ValueError("WebVTT X-TIMESTAMP-MAP is unsupported; convert to project-relative timestamps first")
    cues = []
    for index, block in enumerate(blocks, 1):
        lines = block.strip().split("\n")
        context = f"{source.name}, cue block {index}"
        if is_vtt and re.match(r"^(?:NOTE(?:[ \t]|$)|STYLE$|REGION$)", lines[0]):
            continue
        timing_line = 0 if "-->" in lines[0] else 1
        if timing_line >= len(lines) or "-->" not in lines[timing_line]:
            raise ValueError(f"{context}: missing timestamp range")
        if not is_vtt and timing_line == 1 and not lines[0].strip().isdigit():
            raise ValueError(f"{context}: SRT cue identifier must be numeric")
        timing = re.fullmatch(r"\s*(\S+)\s+-->\s+(\S+)(?:[ \t]+(.*))?\s*", lines[timing_line])
        if not timing:
            raise ValueError(f"{context}: malformed timestamp range")
        begin, end = _time(timing.group(1), context), _time(timing.group(2), context)
        if end <= begin:
            raise ValueError(f"{context}: cue end must be later than its start")
        if timing.group(3) and not is_vtt:
            # Old SRT coordinate extensions are presentation metadata, too.
            if not re.fullmatch(r"(?:[XY][12]:\d+[ \t]*)+", timing.group(3)):
                raise ValueError(f"{context}: unexpected data after SRT timestamp")
        body = lines[timing_line + 1:]
        if any(re.match(r"^\s*\d[\d:.,]*\s+-->", line) for line in body):
            raise ValueError(f"{context}: missing blank line between cues or unexpected timestamp in text")
        text = _text("\n".join(body), context, markup=True)
        frame_range = _frame_range(begin, end, fps, count, shift)
        if frame_range:
            cues.append({"text": text, "start_frame": frame_range[0], "end_frame": frame_range[1]})
    cues.sort(key=lambda cue: (cue["start_frame"], cue["end_frame"]))
    return [{"id": f"sub-{index:03d}", **cue} for index, cue in enumerate(cues, 1)]


def _stamp(frame, fps, separator):
    milliseconds = (frame * 1000 * 2 + fps) // (fps * 2)
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"


def export_subtitles(cues, fps, path, format=None):
    """Export UTF-8 plain-text cues to SRT or WebVTT; return the absolute path.

    Millisecond quantization roundtrips to the same frames at supported frame
    rates. Word highlights and styling are project data, not SRT/VTT metadata.
    """
    _positive_int(fps, "fps")
    if fps > 120:
        raise ValueError("fps must not exceed 120")
    target = Path(path)
    kind = (format or target.suffix.lstrip(".")).lower()
    if kind == "webvtt":
        kind = "vtt"
    if kind not in ("srt", "vtt"):
        raise ValueError("subtitle format must be srt or vtt")
    if not isinstance(cues, list):
        raise ValueError("cues must be a list")
    checked = []
    for index, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise ValueError(f"cue {index} must be an object")
        start, end = cue.get("start_frame"), cue.get("end_frame")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise ValueError(f"cue {index}: start_frame must be a nonnegative integer")
        if isinstance(end, bool) or not isinstance(end, int) or end <= start:
            raise ValueError(f"cue {index}: end_frame must be an integer after start_frame")
        text = _text(cue.get("text"), f"cue {index}")
        if any(not line for line in text.split("\n")):
            raise ValueError(f"cue {index}: blank lines cannot be represented inside SRT/VTT cues")
        checked.append((start, end, text))
    checked.sort(key=lambda item: (item[0], item[1]))
    blocks = ["WEBVTT"] if kind == "vtt" else []
    for index, (start, end, text) in enumerate(checked, 1):
        separator = "." if kind == "vtt" else ","
        # Escape markup rather than letting players interpret literal user text.
        text = html.escape(text, quote=False)
        blocks.append(f"{index}\n{_stamp(start, fps, separator)} --> {_stamp(end, fps, separator)}\n{text}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n".join(blocks) + ("\n\n" if blocks else ""), encoding="utf-8", newline="\n")
    return str(target.resolve())


def _join_words(words):
    # Whisper prefixes Latin words with whitespace, while CJK tokens generally
    # have no spaces. Retain those boundaries; handwritten word arrays without
    # leading spaces use normal word separation.
    raw = [word["text"] for word in words]
    if any(value[:1].isspace() for value in raw):
        return "".join(raw).strip()
    if any(re.search(r"[\u3000-\u9fff\uac00-\ud7af]", value) for value in raw):
        return "".join(raw).strip()
    return re.sub(r"\s+([,.;:!?%…])", r"\1", " ".join(raw).strip())


def _coalesce_words(words, text):
    """Keep colliding subframe tokens visible as one highlight group."""
    result, cursor = [], 0
    for word in words:
        start = text.find(word["text"], cursor)
        if start < 0:
            raise ValueError("Transcript word text does not match its caption")
        cursor = start + len(word["text"])
        if result and word["start_frame"] < result[-1]["end_frame"]:
            previous = result[-1]
            previous["text"] = text[previous["_offset"]:cursor]
            previous["end_frame"] = max(previous["end_frame"], word["end_frame"])
        else:
            result.append({**word, "_offset": start})
    return [{key: value for key, value in word.items() if key != "_offset"} for word in result]


def segment_transcript(transcript, plan, offset=0, timebase="project", max_chars=42,
                       max_words=7, max_duration=3):
    """Group recognized words into short cues, retaining real highlight timings.

    Phrase boundaries, pauses longer than 0.6s and limits split cues. A word is
    never cut in half to satisfy a character/duration limit. Tokens that share
    an output frame are highlighted together. Segments without word timestamps
    remain intact: fabricated word timing is never introduced.
    """
    fps, count, shift = _timeline(plan, offset, timebase)
    _positive_int(max_chars, "max_chars")
    _positive_int(max_words, "max_words")
    limit = _finite(max_duration, "max_duration")
    if limit <= 0:
        raise ValueError("max_duration must be positive")
    if not isinstance(transcript, dict) or not isinstance(transcript.get("segments"), list):
        raise ValueError("transcript must contain a segments list")
    cues = []

    def emit(group):
        if not group:
            return
        begin, end = group[0]["start"], max(word["end"] for word in group)
        frame_range = _frame_range(begin, end, fps, count, shift)
        if not frame_range:
            return
        visible = []
        for word in group:
            span = _frame_range(word["start"], word["end"], fps, count, shift)
            if span:
                visible.append({"text": word["text"].strip(), "start_frame": max(span[0], frame_range[0]),
                                "end_frame": min(span[1], frame_range[1])})
        if visible:
            # Cropping removes words entirely outside the selected soundtrack.
            audible = [word for word in group if _frame_range(word["start"], word["end"], fps, count, shift)]
            text = _join_words(audible)
            cues.append({"text": text, "start_frame": frame_range[0],
                         "end_frame": frame_range[1], "words": _coalesce_words(visible, text)})

    previous_segment = -1
    for index, segment in enumerate(transcript["segments"], 1):
        if not isinstance(segment, dict):
            raise ValueError(f"transcript segment {index} must be an object")
        begin = _finite(segment.get("start"), f"segment {index} start")
        end = _finite(segment.get("end"), f"segment {index} end")
        if begin < 0 or end <= begin or begin < previous_segment:
            raise ValueError(f"segment {index}: timestamps must be ordered, nonnegative, and have positive duration")
        previous_segment = begin
        words = segment.get("words")
        if words is not None and not isinstance(words, list):
            raise ValueError(f"segment {index}: words must be a list")
        if not words:
            text = _text(segment.get("text"), f"segment {index}")
            span = _frame_range(begin, end, fps, count, shift)
            if span:
                cues.append({"text": text, "start_frame": span[0], "end_frame": span[1]})
            continue
        group = []
        previous_word = begin
        for word_index, word in enumerate(words, 1):
            if not isinstance(word, dict):
                raise ValueError(f"segment {index}, word {word_index}: expected an object")
            start = _finite(word.get("start"), "word start")
            finish = _finite(word.get("end"), "word end")
            value = word.get("text", word.get("word"))
            _text(value, "word")
            if start < begin - 1e-6 or finish > end + 1e-6 or finish <= start or start < previous_word - 1e-6:
                raise ValueError(f"segment {index}, word {word_index}: word times must be ordered and inside the segment")
            previous_word = start
            current = {"text": value, "start": start, "end": finish}
            if group and (len(group) >= max_words or len(_join_words(group + [current])) > max_chars
                          or finish - group[0]["start"] > limit or start - group[-1]["end"] > .6):
                emit(group)
                group = []
            group.append(current)
            if _PHRASE_END.search(value.strip()):
                emit(group)
                group = []
        emit(group)
    cues.sort(key=lambda cue: (cue["start_frame"], cue["end_frame"]))
    merged = []
    for cue in cues:
        if merged and cue["start_frame"] < merged[-1]["end_frame"]:
            previous = merged[-1]
            previous["text"] = _join_words([previous, cue])
            previous["end_frame"] = max(previous["end_frame"], cue["end_frame"])
            if "words" in previous and "words" in cue:
                previous["words"] = _coalesce_words(previous["words"] + cue["words"], previous["text"])
            else:
                previous.pop("words", None)
        else:
            merged.append(cue)
    return [{"id": f"sub-{index:03d}", **cue} for index, cue in enumerate(merged, 1)]

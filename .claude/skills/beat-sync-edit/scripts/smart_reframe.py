#!/usr/bin/env python3
"""Track an explicit subject or use labelled face/motion fallbacks for reframing."""

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from media_library import IMAGE_EXTENSIONS, load_image, validate_subject


def crop_frame(frame, width, height, center=(0.5, 0.5), fit="cover"):
    """Resize BGR pixels without distortion, clamping cover crops to the frame."""
    if frame is None or frame.size == 0 or width < 1 or height < 1:
        raise ValueError("A nonempty frame and positive output dimensions are required")
    if fit not in {"cover", "contain"}:
        raise ValueError("fit must be cover or contain")
    width, height = int(width), int(height)
    source_h, source_w = frame.shape[:2]
    if len(center) != 2 or not all(math.isfinite(float(value)) for value in center):
        raise ValueError("center must be two finite normalized coordinates")
    if fit == "contain":
        scale = min(width / source_w, height / source_h)
        resized_w, resized_h = max(1, round(source_w * scale)), max(1, round(source_h * scale))
        resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        output = np.zeros((height, width, frame.shape[2]), dtype=frame.dtype)
        left, top = (width - resized_w) // 2, (height - resized_h) // 2
        output[top:top + resized_h, left:left + resized_w] = resized
        return output
    ratio = width / height
    crop_w = min(source_w, max(1, round(source_h * ratio)))
    crop_h = min(source_h, max(1, round(source_w / ratio)))
    left = int(round(float(center[0]) * source_w - crop_w / 2))
    top = int(round(float(center[1]) * source_h - crop_h / 2))
    left = max(0, min(left, source_w - crop_w))
    top = max(0, min(top, source_h - crop_h))
    cropped = frame[top:top + crop_h, left:left + crop_w]
    return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_AREA if crop_w > width else cv2.INTER_LINEAR)


def _clamp_box(box, width, height):
    x, y, w, h = box
    w, h = max(2, min(float(w), width)), max(2, min(float(h), height))
    return np.array([max(0, min(float(x), width - w)), max(0, min(float(y), height - h)), w, h], dtype=float)


def _features(gray, box):
    x, y, w, h = [int(round(value)) for value in box]
    mask = np.zeros_like(gray)
    mask[y:y + h, x:x + w] = 255
    return cv2.goodFeaturesToTrack(gray, maxCorners=100, qualityLevel=.01, minDistance=3, mask=mask, blockSize=3)


def _template_track(gray, template, box):
    """Search a bounded region so a repeated pattern cannot jump across frame."""
    x, y, w, h = box
    radius_x, radius_y = max(w * 2, gray.shape[1] * .18), max(h * 2, gray.shape[0] * .18)
    left = max(0, int(x - radius_x))
    top = max(0, int(y - radius_y))
    right = min(gray.shape[1], int(x + w + radius_x))
    bottom = min(gray.shape[0], int(y + h + radius_y))
    search = gray[top:bottom, left:right]
    if min(template.shape) < 2 or search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return box, 0.0
    # SQDIFF remains meaningful for an almost uniform subject patch.
    result = cv2.matchTemplate(search, template, cv2.TM_SQDIFF_NORMED)
    error, _, location, _ = cv2.minMaxLoc(result)
    return np.array([left + location[0], top + location[1], w, h]), float(max(0, 1 - error))


def _manual_step(previous, gray, box, template):
    points = _features(previous, box)
    flow_box, flow_confidence = None, 0.0
    if points is not None and len(points) >= 3:
        following, status, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None, winSize=(31, 31), maxLevel=3)
        if following is not None:
            good = status.reshape(-1) == 1
            old, new = points.reshape(-1, 2)[good], following.reshape(-1, 2)[good]
            if len(new) >= 3:
                # Forward/back consistency filters points lost to occlusion.
                back, back_status, _ = cv2.calcOpticalFlowPyrLK(gray, previous, following, None, winSize=(31, 31), maxLevel=3)
                consistent = (back_status.reshape(-1)[good] == 1) & (np.linalg.norm(back.reshape(-1, 2)[good] - old, axis=1) < 2)
                if consistent.sum() >= 3:
                    delta = np.median(new[consistent] - old[consistent], axis=0)
                    flow_box = box.copy()
                    flow_box[:2] += delta
                    flow_confidence = float(consistent.sum() / max(len(points), 1))
    candidate, confidence = _template_track(gray, template, flow_box if flow_box is not None else box)
    if confidence >= .7:
        return candidate, "manual_template", confidence
    if flow_box is not None and flow_confidence >= .25:
        return flow_box, "manual_optical_flow", flow_confidence
    return box, "manual_hold", confidence


def _face_box(gray, detector, previous_box):
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24)) if detector is not None else []
    if len(faces) == 0:
        return None
    if previous_box is None:
        return np.array(max(faces, key=lambda box: box[2] * box[3]), dtype=float)
    cx, cy = previous_box[:2] + previous_box[2:] / 2
    return np.array(min(faces, key=lambda box: ((box[0] + box[2] / 2 - cx) ** 2 + (box[1] + box[3] / 2 - cy) ** 2)), dtype=float)


def _motion_box(previous, gray, previous_box):
    delta = cv2.absdiff(cv2.GaussianBlur(previous, (5, 5), 0), cv2.GaussianBlur(gray, (5, 5), 0))
    threshold = max(15, float(np.mean(delta) + 2 * np.std(delta)))
    mask = (delta > threshold).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), dtype=np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
    area = gray.shape[0] * gray.shape[1]
    choices = [index for index in range(1, count) if max(30, area * .001) <= stats[index, cv2.CC_STAT_AREA] <= area * .45]
    if not choices:
        return None
    if previous_box is None:
        chosen = max(choices, key=lambda index: stats[index, cv2.CC_STAT_AREA])
    else:
        center = previous_box[:2] + previous_box[2:] / 2
        chosen = min(choices, key=lambda index: np.linalg.norm(centers[index] - center) / max(1, math.sqrt(stats[index, cv2.CC_STAT_AREA])))
    return stats[chosen, :4].astype(float)


def _smooth(records, seconds=.35):
    """Symmetric local smoothing avoids a following camera's persistent lag."""
    if len(records) < 3:
        return records
    times = np.array([record["time"] for record in records])
    coordinates = np.array([[record["cx"], record["cy"]] for record in records])
    confidences = np.array([max(.15, record["confidence"]) for record in records])
    smoothed = []
    for index, time in enumerate(times):
        left = int(np.searchsorted(times, time - seconds, side="left"))
        right = int(np.searchsorted(times, time + seconds, side="right"))
        distance = np.abs(times[left:right] - time)
        weights = np.maximum(0, 1 - distance / seconds)
        weights *= confidences[left:right]
        point = np.average(coordinates[left:right], axis=0, weights=weights)
        # A camera may ease toward an object, but never smooth it far away.
        point = coordinates[index] + np.clip(point - coordinates[index], -.04, .04)
        smoothed.append(point)
    for record, point in zip(records, smoothed):
        record["cx"], record["cy"] = [round(float(np.clip(value, 0, 1)), 6) for value in point]
    return records


def track_subject(path, start, end, subject=None, sample_fps=5):
    """Return a smoothed display-oriented camera path in source seconds.

    An explicit normalized ROI is tracked by optical flow/template matching.
    Without one, faces take priority, then frame-difference motion, then center.
    Every keyframe names its method and confidence; motion is not an object
    recognizer. The renderer clamps the camera with ``crop_frame`` for its own
    target aspect ratio. Annotation coordinates refer to the first frame.
    """
    path = Path(path).resolve(strict=True)
    if not all(math.isfinite(float(value)) for value in (start, end, sample_fps)) or start < 0 or end < start or not 0 < sample_fps <= 60:
        raise ValueError("Require 0 <= start <= end and 0 < sample_fps <= 60")
    if subject is not None:
        subject = validate_subject(subject)
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        load_image(path)  # Fail early for undecodable files.
        bbox = subject or [0, 0, 1, 1]
        return [{"time": float(start), "cx": bbox[0] + bbox[2] / 2, "cy": bbox[1] + bbox[3] / 2,
                 "bbox": bbox, "method": "manual_still" if subject else "center_still", "confidence": 1.0 if subject else 0.0}]
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot decode video: {path}")
    detector_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(detector_path)) if detector_path.is_file() and subject is None else None
    if detector is not None and detector.empty():
        detector = None
    previous = None
    box = None
    template = None
    records = []
    fps = capture.get(cv2.CAP_PROP_FPS)
    duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps > 0 else end
    if start >= duration and duration > 0:
        capture.release()
        raise ValueError("Tracking starts beyond the video duration")
    stop = min(float(end), max(float(start), duration - 1 / max(fps, 1)))
    times = list(np.arange(float(start), stop, 1 / sample_fps)) + [stop]
    try:
        for time in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, time * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            scale = min(1.0, 640 / max(frame.shape[:2]))
            gray = cv2.cvtColor(cv2.resize(frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale))), cv2.COLOR_BGR2GRAY)
            height, width = gray.shape
            if subject is not None:
                if previous is None:
                    box = _clamp_box(np.array(subject) * [width, height, width, height], width, height)
                    x, y, w, h = [int(round(value)) for value in box]
                    template = gray[y:y + h, x:x + w].copy()
                    method, confidence = "manual_initial", 1.0
                else:
                    box, method, confidence = _manual_step(previous, gray, box, template)
                    box = _clamp_box(box, width, height)
                    if confidence > .9:
                        x, y, w, h = [int(round(value)) for value in box]
                        replacement = gray[y:y + h, x:x + w]
                        if replacement.shape == template.shape:
                            template = cv2.addWeighted(template, .9, replacement, .1, 0)
            else:
                face = _face_box(gray, detector, box)
                motion = _motion_box(previous, gray, box) if previous is not None and face is None else None
                if face is not None:
                    box, method, confidence = face, "face", .85
                elif motion is not None:
                    box, method, confidence = motion, "motion", .45
                else:
                    method, confidence = ("hold", .1) if box is not None else ("center", 0.0)
                    box = box if box is not None else np.array([width * .4, height * .4, width * .2, height * .2])
            normalized = box / [width, height, width, height]
            records.append({"time": round(float(time), 6), "cx": float(normalized[0] + normalized[2] / 2),
                            "cy": float(normalized[1] + normalized[3] / 2), "bbox": [round(float(value), 6) for value in normalized],
                            "method": method, "confidence": round(float(confidence), 3)})
            previous = gray
    finally:
        capture.release()
    if not records:
        raise ValueError(f"No frames could be tracked: {path}")
    return _smooth(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--subject", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--sample-fps", type=float, default=5)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    records = track_subject(args.source, args.start, args.end, args.subject, args.sample_fps)
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} camera keyframes to {target}")


if __name__ == "__main__":
    main()

"""Pixel implementation of the per-shot effect catalog in edit_effects.py.

All effects are deterministic functions of the frame, the shot-local frame
index and the output rate, so cached shots are reproducible. Nothing here
reads neighbouring shots: transitions are built from an outgoing tail effect
and an incoming head effect, and every shot keeps its exact frame count.
"""

import math

import cv2
import numpy as np

from edit_effects import effect_value

_LUMA = np.array([.114, .587, .299], np.float32)  # BGR weights
_VIGNETTE_CACHE = {}


def _envelope(index, frames, power=1.0):
    """1 on the cut frame, decaying to 0 after `frames` output frames."""
    return max(0.0, 1 - index / max(1.0, frames)) ** power


def pulse_envelope(index, pulse_frames, fps):
    """Strength of the most recent beat bump at this shot-local frame."""
    previous = [beat for beat in pulse_frames if beat <= index]
    if not previous:
        return 0.0
    return _envelope(index - max(previous), fps * .16, 2)


def zoom_amount(effects, kind, index, count, fps, pulse_frames=()):
    """Crop magnification before reframing: punch-in, shake headroom and beat pulses."""
    zoom = effect_value(effects, "zoom")
    if kind == "image":
        amount = 1 + (zoom - 1) * (index / max(1, count - 1))
    else:
        amount = 1 + (zoom - 1) * max(0, 1 - index / max(1, fps * .18)) ** 2
    amount += effect_value(effects, "shake") * .025
    pulse = effect_value(effects, "pulse")
    if pulse and pulse_frames:
        amount += pulse * .08 * pulse_envelope(index, pulse_frames, fps)
    return amount


def _shift_horizontal(frame, dx):
    if not dx:
        return frame
    matrix = np.float32([[1, 0, dx], [0, 1, 0]])
    return cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]), borderMode=cv2.BORDER_REFLECT)


def _motion_blur(frame, length):
    length = int(length)
    if length < 2:
        return frame
    return cv2.blur(frame, (length, 1), borderType=cv2.BORDER_REFLECT)


def _stretch(frame, amount):
    height, width = frame.shape[:2]
    wide = max(width, int(round(width * (1 + .3 * amount))))
    if wide == width:
        return frame
    resized = cv2.resize(frame, (wide, height), interpolation=cv2.INTER_LINEAR)
    left = (wide - width) // 2
    return resized[:, left:left + width]


def _whip(frame, index, count, fps, entering, strength):
    width = frame.shape[1]
    frames = min(count, max(2, round(fps * .2)))
    position = index if entering else count - 1 - index
    if position >= frames:
        return frame
    remain = 1 - position / frames
    offset = strength * .45 * width * remain ** 2
    frame = _shift_horizontal(frame, offset if entering else -offset)
    return _motion_blur(frame, strength * .3 * width * remain)


def _grade(arr, grade):
    if grade == "warm":
        arr *= np.array([.96, 1.01, 1.06], np.float32)
    elif grade == "cool":
        arr *= np.array([1.08, 1.01, .97], np.float32)
    elif grade == "vivid":
        gray = np.sum(arr * np.array([.114, .587, .299]), axis=2, keepdims=True)
        arr = (gray + (arr-gray)*1.22 - .5)*1.07 + .5
    elif grade == "cinematic":
        gray = np.sum(arr * np.array([.114, .587, .299]), axis=2, keepdims=True)
        arr = (gray + (arr-gray)*.86 - .5)*1.12 + .51
        arr[..., 0] += .025*(1-arr[..., 0])
        arr[..., 2] += .02*arr[..., 2]
    elif grade == "mono":
        gray = np.sum(arr * _LUMA, axis=2, keepdims=True)
        arr = np.repeat((gray - .5) * 1.12 + .5, 3, axis=2)
    elif grade == "teal_orange":
        luma = np.sum(arr * _LUMA, axis=2, keepdims=True)
        arr = luma + (arr - luma) * 1.08
        shadow = 1 - luma
        arr = arr + np.concatenate((.07*shadow - .05*luma, .02*shadow - .005*luma, -.04*shadow + .07*luma), axis=2)
        arr = (arr - .5) * 1.06 + .5
    elif grade == "vintage":
        luma = np.sum(arr * _LUMA, axis=2, keepdims=True)
        arr = luma + (arr - luma) * .78
        arr = arr * .84 + .08
        arr *= np.array([.92, 1.0, 1.05], np.float32)
    elif grade == "moody":
        luma = np.sum(arr * _LUMA, axis=2, keepdims=True)
        arr = luma + (arr - luma) * .7
        arr = np.power(np.clip(arr, 0, 1), 1.18)
        arr = (arr - .5) * 1.08 + .5
        arr[..., 0] += .035 * (1 - luma[..., 0])
    elif grade not in ("none", "neutral", None):
        raise ValueError(f"Unknown color grade: {grade}")
    return arr


def _glow(arr, strength):
    height, width = arr.shape[:2]
    small = cv2.resize(arr, (max(2, width // 4), max(2, height // 4)), interpolation=cv2.INTER_AREA)
    bright = np.clip((small - .55) * 2.2, 0, 1)
    sigma = max(1.0, min(width, height) / 4 * .04)
    bloom = cv2.resize(cv2.GaussianBlur(bright, (0, 0), sigma), (width, height), interpolation=cv2.INTER_LINEAR)
    return 1 - (1 - arr) * (1 - strength * .6 * bloom)


def _vignette_mask(height, width):
    key = (height, width)
    if key not in _VIGNETTE_CACHE:
        y, x = np.ogrid[:height, :width]
        dx = (x - (width - 1) / 2) / (width / 2)
        dy = (y - (height - 1) / 2) / (height / 2)
        radius = np.sqrt(dx * dx + dy * dy) / math.sqrt(2)
        _VIGNETTE_CACHE.clear()
        _VIGNETTE_CACHE[key] = np.clip((radius - .3) / .7, 0, 1).astype(np.float32) ** 1.6
    return _VIGNETTE_CACHE[key]


def _grain(arr, strength, index):
    height, width = arr.shape[:2]
    rng = np.random.default_rng(7919 * index + 13)
    noise = rng.standard_normal((max(2, height // 2), max(2, width // 2))).astype(np.float32)
    noise = cv2.resize(noise, (width, height), interpolation=cv2.INTER_LINEAR)
    return arr + strength * .09 * noise[..., None]


def _rgb_split(frame, amount):
    dx = int(round(amount * .012 * frame.shape[1]))
    if dx < 1:
        return frame
    out = frame.copy()
    out[:, dx:, 2] = frame[:, :-dx, 2]
    out[:, :dx, 2] = frame[:, :1, 2]
    out[:, :-dx, 0] = frame[:, dx:, 0]
    out[:, -dx:, 0] = frame[:, -1:, 0]
    return out


def _glitch(frame, amount, index):
    height, width = frame.shape[:2]
    rng = np.random.default_rng(104729 * index + 7)
    out = frame.copy()
    for _ in range(6):
        band = max(1, int(height * rng.uniform(.02, .08)))
        top = int(rng.integers(0, max(1, height - band)))
        shift = int(round(rng.uniform(-1, 1) * .08 * width * amount))
        out[top:top + band] = np.roll(out[top:top + band], shift, axis=1)
        if rng.random() < .5:
            channel = int(rng.integers(0, 3))
            out[top:top + band, :, channel] = np.roll(out[top:top + band, :, channel], shift // 2, axis=1)
    return out


def apply_frame_effects(frame, effects, index, count, fps):
    """Apply every non-geometric-crop effect to one output-sized BGR frame."""
    effects = effects or {}
    stretch = effect_value(effects, "stretch") * _envelope(index, fps * .15, 2)
    if stretch > 1e-4:
        frame = _stretch(frame, stretch)
    for name, entering in (("whip_in", True), ("whip_out", False)):
        strength = effect_value(effects, name)
        if strength:
            frame = _whip(frame, index, count, fps, entering, strength)
    blur = effect_value(effects, "blur_in") * _envelope(index, fps * .25, 1.5)
    if blur > 1e-3:
        sigma = blur * .02 * min(frame.shape[:2])
        if sigma >= .3:
            frame = cv2.GaussianBlur(frame, (0, 0), sigma)

    arr = frame.astype(np.float32) / 255
    arr = _grade(arr, effects.get("grade", "none"))
    glow = effect_value(effects, "glow")
    if glow:
        arr = _glow(np.clip(arr, 0, 1).astype(np.float32), glow)
    vignette = effect_value(effects, "vignette")
    if vignette:
        arr = arr * (1 - vignette * .7 * _vignette_mask(*arr.shape[:2]))[..., None]
    grain = effect_value(effects, "grain")
    if grain:
        arr = _grain(arr, grain, index)
    # 80 ms fade from white: a transition on this cut, with no overlap shortening.
    flash = effect_value(effects, "flash")
    amount = flash * max(0, 1-index/max(1, fps*.08))
    arr = arr*(1-amount) + amount
    dip = effect_value(effects, "dip") * _envelope(index, fps * .16)
    if dip:
        arr = arr * (1 - dip)
    invert = effect_value(effects, "invert")
    if invert and index < max(1, round(fps / 15)):
        arr = np.clip(arr, 0, 1)
        arr = arr * (1 - invert) + (1 - arr) * invert
    frame = (np.clip(arr, 0, 1)*255).astype(np.uint8)

    split = effect_value(effects, "rgb_split") * _envelope(index, fps * .2)
    if split > 1e-3:
        frame = _rgb_split(frame, split)
    glitch = effect_value(effects, "glitch")
    if glitch and index < max(2, round(fps * .13)):
        frame = _glitch(frame, glitch * _envelope(index, max(2, round(fps * .13)) + 1), index)
    letterbox = effect_value(effects, "letterbox")
    if letterbox:
        bar = int(round(letterbox * frame.shape[0]))
        if bar:
            frame = frame.copy() if not frame.flags.writeable else frame
            frame[:bar] = 0
            frame[frame.shape[0] - bar:] = 0
    return frame

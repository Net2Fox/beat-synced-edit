"""Editable, deterministic style recipes for the version 2 editing engine."""

from copy import deepcopy


PRESETS = {
    "cinematic": {
        "description": "Patient establishing shots, gentle build and restrained accents.",
        "beat_stride": {"intro": 8, "build": 4, "drop": 2, "outro": 8},
        "min_shot": 0.8, "max_shot": 6.0,
        "energy": {"intro": 0.2, "build": 0.45, "drop": 0.75, "outro": 0.2},
        "preferred_tags": ["landscape", "travel", "nature", "portrait"],
        "shot_cycle": ["wide", "medium", "close"],
        "effects": {"flash": 0.08, "zoom": 1.04, "shake": 0.0, "grade": "cinematic"},
        "speed_ramp": [1.4, 1.0, 1.4],
    },
    "car": {
        "description": "Wide/detail alternation, accelerating pace and punchy drop accents.",
        "beat_stride": {"intro": 4, "build": 2, "drop": 1, "outro": 4},
        "min_shot": 0.2, "max_shot": 3.0,
        "energy": {"intro": 0.3, "build": 0.65, "drop": 0.95, "outro": 0.35},
        "preferred_tags": ["car", "vehicle", "wheel", "driving", "drift", "detail"],
        "shot_cycle": ["wide", "detail", "action", "close"],
        "effects": {"flash": 0.65, "zoom": 1.15, "shake": 0.25, "grade": "cool"},
        "speed_ramp": [2.0, 1.0, 2.0],
    },
    "gaming": {
        "description": "Action-focused rapid cuts, vivid color and timed impact accents.",
        "beat_stride": {"intro": 4, "build": 2, "drop": 1, "outro": 2},
        "min_shot": 0.15, "max_shot": 2.0,
        "energy": {"intro": 0.45, "build": 0.75, "drop": 1.0, "outro": 0.4},
        "preferred_tags": ["game", "gaming", "action", "kill", "win", "highlight"],
        "shot_cycle": ["wide", "action", "close", "action"],
        "effects": {"flash": 0.45, "zoom": 1.12, "shake": 0.15, "grade": "vivid"},
        "speed_ramp": [2.4, 1.0, 2.4],
    },
    "product": {
        "description": "Clean overview/detail sequences with gentle motion and warm color.",
        "beat_stride": {"intro": 4, "build": 4, "drop": 2, "outro": 4},
        "min_shot": 0.6, "max_shot": 4.0,
        "energy": {"intro": 0.2, "build": 0.4, "drop": 0.6, "outro": 0.15},
        "preferred_tags": ["product", "detail", "fashion", "texture", "packaging"],
        "shot_cycle": ["wide", "detail", "close", "medium"],
        "effects": {"flash": 0.1, "zoom": 1.06, "shake": 0.0, "grade": "warm"},
        "speed_ramp": [1.2, 1.0, 1.2],
    },
    "phonk": {
        "description": "Dark, aggressive phonk/drift edit: hard drop cuts, glitch and RGB hits, shake and beat pulses.",
        "beat_stride": {"intro": 4, "build": 2, "drop": 1, "outro": 2},
        "min_shot": 0.15, "max_shot": 2.0,
        "energy": {"intro": 0.4, "build": 0.75, "drop": 1.0, "outro": 0.45},
        "preferred_tags": ["car", "drift", "night", "street", "fight", "action", "sport"],
        "shot_cycle": ["action", "close", "detail", "action"],
        "effects": {"flash": 0.3, "zoom": 1.14, "shake": 0.35, "rgb_split": 0.7, "glitch": 0.5,
                    "pulse": 0.5, "vignette": 0.45, "grain": 0.25, "grade": "moody"},
        "speed_ramp": [2.2, 1.0, 2.2],
        "accent_every": 2,
    },
    "anime": {
        "description": "Bright anime/AMV edit: white flashes, stretch hits, zoom pulses on beats and soft glow.",
        "beat_stride": {"intro": 4, "build": 2, "drop": 1, "outro": 4},
        "min_shot": 0.2, "max_shot": 2.5,
        "energy": {"intro": 0.35, "build": 0.7, "drop": 1.0, "outro": 0.35},
        "preferred_tags": ["anime", "character", "face", "fight", "action", "sky"],
        "shot_cycle": ["close", "action", "wide", "close"],
        "effects": {"flash": 0.7, "zoom": 1.12, "shake": 0.15, "rgb_split": 0.4, "stretch": 0.35,
                    "pulse": 0.6, "glow": 0.35, "grade": "vivid"},
        "speed_ramp": [2.0, 1.0, 2.0],
        "accent_every": 2,
    },
    "travel": {
        "description": "Calm travel/vlog montage: long holds, soft dips from black, gentle push-ins and a warm vintage look.",
        "beat_stride": {"intro": 8, "build": 4, "drop": 2, "outro": 8},
        "min_shot": 0.9, "max_shot": 6.0,
        "energy": {"intro": 0.2, "build": 0.4, "drop": 0.6, "outro": 0.2},
        "preferred_tags": ["travel", "landscape", "nature", "city", "people", "food"],
        "shot_cycle": ["wide", "medium", "detail", "wide"],
        "effects": {"dip": 0.5, "zoom": 1.05, "vignette": 0.25, "grain": 0.12, "grade": "vintage"},
        "speed_ramp": [1.3, 1.0, 1.3],
    },
}


def get_preset(name="cinematic"):
    """Return an independent recipe so one project's overrides never leak to another."""
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}; choose {', '.join(PRESETS)}")
    return deepcopy(PRESETS[name])


def list_presets():
    return {name: value["description"] for name, value in PRESETS.items()}

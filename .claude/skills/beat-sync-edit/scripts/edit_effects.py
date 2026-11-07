"""Per-shot effect catalog shared by the planner, revisions and the renderer.

Every effect is contained in its own shot and never changes the frame count.
Accent effects start at the cut and decay within a fraction of a second;
transition effects shape the first or last frames of a shot; looks apply to
every frame. This module is deliberately independent of video/ML dependencies.
"""

import math


GRADES = ("none", "neutral", "cinematic", "cool", "vivid", "warm",
          "mono", "teal_orange", "vintage", "moody")

# name: (group, minimum, maximum, neutral value, description)
EFFECTS = {
    "flash": ("accent", 0, 1, 0, "White flash fading out over 80 ms from the cut"),
    "dip": ("accent", 0, 1, 0, "Fade up from black over 160 ms from the cut"),
    "invert": ("accent", 0, 1, 0, "Negative-image hit on the first frames (about 70 ms)"),
    "rgb_split": ("accent", 0, 1, 0, "Chromatic channel offset decaying over 200 ms"),
    "glitch": ("accent", 0, 1, 0, "Displaced horizontal slices and color offset for about 130 ms"),
    "stretch": ("accent", 0, 1, 0, "Horizontal stretch hit settling over 150 ms"),
    "blur_in": ("accent", 0, 1, 0, "Defocus clearing over 250 ms"),
    "whip_in": ("transition", 0, 1, 0, "Motion-blurred horizontal slide into the shot (first 200 ms)"),
    "whip_out": ("transition", 0, 1, 0, "Motion-blurred horizontal slide out of the shot (last 200 ms)"),
    "zoom": ("motion", 1, 4, 1, "Punch-in that settles over 180 ms; a slow push on stills"),
    "shake": ("motion", 0, 1, 0, "Camera shake for the whole shot"),
    "pulse": ("motion", 0, 1, 0, "Zoom bump on every music beat inside the shot"),
    "vignette": ("look", 0, 1, 0, "Darkened frame edges"),
    "grain": ("look", 0, 1, 0, "Film grain"),
    "glow": ("look", 0, 1, 0, "Soft bloom around highlights"),
    "letterbox": ("look", 0, .35, 0, "Black bars; height of each bar as a fraction of the frame height"),
}
NUMERIC_EFFECTS = tuple(EFFECTS)
ACCENT_EFFECTS = tuple(name for name, spec in EFFECTS.items() if spec[0] == "accent")
LOOK_EFFECTS = tuple(name for name, spec in EFFECTS.items() if spec[0] == "look")
# Grade "none" means a natural look: no colour grade and none of the looks above.
# "neutral" is no colour grade while keeping any looks.
NATURAL_GRADE = "none"
EFFECT_NAMES = frozenset(EFFECTS) | {"grade"}
# Full-frame brightness hits at a cut. More than three in one second can
# trigger photosensitive seizures, so plans and revisions are kept below that.
FLASH_EFFECTS = ("flash", "dip", "invert")
MAX_FLASHES_PER_SECOND = 3

# Every effect a transition may set on the incoming/outgoing side of one cut.
_CUT_IN = ACCENT_EFFECTS + ("whip_in",)
_CUT_OUT = ("whip_out",)
TRANSITIONS = {
    "cut": ({}, {}),
    "flash": ({}, {"flash": 1.0}),
    "dip": ({}, {"dip": 1.0}),
    "invert": ({}, {"invert": 1.0}),
    "whip": ({"whip_out": 1.0}, {"whip_in": 1.0}),
    "glitch": ({}, {"glitch": 1.0, "rgb_split": .6}),
    "rgb": ({}, {"rgb_split": 1.0, "stretch": .4}),
    "blur": ({}, {"blur_in": 1.0}),
    "zoom": ({}, {"zoom": None, "blur_in": .4}),
}


def _number(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"effect {name} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"effect {name} must be between {minimum} and {maximum}")
    return float(value)


def validate_effects(effects, label="effects"):
    """Raise ValueError for unknown effects, invalid grades or out-of-range values.

    Messages start with `label` (for example "shot-003 effects") so an error in
    a long project names the shot it comes from.
    """
    if effects is None:
        return {}
    if not isinstance(effects, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(effects) - EFFECT_NAMES
    if unknown:
        raise ValueError(f"{label}: unknown effects {sorted(unknown)}; supported: {sorted(EFFECT_NAMES)}")
    for name, value in effects.items():
        if name == "grade":
            if value not in GRADES and value is not None:
                raise ValueError(f"{label}: unknown grade {value!r}; choose {', '.join(GRADES)}")
            continue
        _, minimum, maximum, _, _ = EFFECTS[name]
        try:
            _number(value, name, minimum, maximum)
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
    return effects


def effect_value(effects, name):
    """Return a numeric effect strength, using the catalog's neutral default."""
    value = (effects or {}).get(name)
    return float(EFFECTS[name][3] if value is None else value)


def is_active(effects, name):
    return effect_value(effects, name) != EFFECTS[name][3]


def active_effects(effects):
    """Only the values that change a frame: neutral numbers and "no grade" are dropped."""
    return {name: value for name, value in (effects or {}).items()
            if (value not in (None, "none", "neutral") if name == "grade" else is_active(effects, name))}


def _flash_starts(edits):
    return [(shot["timeline_start_frame"], shot["id"]) for shot in edits
            if any(is_active(shot.get("effects"), name) for name in FLASH_EFFECTS)]


def flash_bursts(edits, fps):
    """Each run of more than MAX_FLASHES_PER_SECOND flash/dip/invert cuts inside one second.

    Returns (start frame, shot IDs) pairs, in timeline order.
    """
    starts, limit = _flash_starts(edits), MAX_FLASHES_PER_SECOND
    return [(starts[i][0], tuple(shot_id for _, shot_id in starts[i:i + limit + 1]))
            for i in range(len(starts) - limit) if starts[i + limit][0] - starts[i][0] < fps]


def flash_peak(edits, fps):
    """The most flash/dip/invert cuts that start inside any one second."""
    starts = [frame for frame, _ in _flash_starts(edits)]
    return max((sum(0 <= other - frame < fps for other in starts) for frame in starts), default=0)


def flash_burst_shots(edits, fps):
    """IDs of every shot that takes part in a burst."""
    return {shot_id for _, shots in flash_bursts(edits, fps) for shot_id in shots}


def thin_flashes(edits, fps):
    """Zero flash/dip/invert on every shot that would be the fourth inside one second."""
    kept, thinned = [], []
    for shot in edits:
        effects = shot.get("effects") or {}
        if not any(is_active(effects, name) for name in FLASH_EFFECTS):
            continue
        start = shot["timeline_start_frame"]
        if sum(start - frame < fps for frame in kept) >= MAX_FLASHES_PER_SECOND:
            for name in FLASH_EFFECTS:
                effects.pop(name, None)
            thinned.append(shot["id"])
        else:
            kept.append(start)
    return thinned


def flash_burst_message(bursts, fps):
    start, shots = bursts[0]
    return (f"more than {MAX_FLASHES_PER_SECOND} full-frame flashes, dips or inverts within one second "
            f"(shots {', '.join(shots)} from {start / fps:.2f} s); rapid flashing can trigger photosensitive "
            "seizures. On dense cuts use whip, rgb or blur, or put flashes on fewer cuts")


def parse_effect_override(text):
    """Parse NAME=VALUE from the command line (grade takes a name, others a number)."""
    try:
        name, value = text.split("=", 1)
    except ValueError as exc:
        raise ValueError("effect override must be NAME=VALUE, for example rgb_split=0.6") from exc
    name = name.strip()
    if name not in EFFECT_NAMES:
        raise ValueError(f"Unknown effect {name!r}; supported: {', '.join(sorted(EFFECT_NAMES))}")
    if name == "grade":
        parsed = value.strip()
    else:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValueError(f"effect {name} needs a number") from exc
    validate_effects({name: parsed})
    return name, parsed


def transition_effects(kind, strength=1.0):
    """Return (outgoing, incoming) effect updates for one cut.

    Both sides first clear every transition-related value, so replacing a whip
    with a flash does not leave half of the previous transition behind.
    """
    if kind not in TRANSITIONS:
        raise ValueError(f"Unknown transition {kind!r}; choose {', '.join(TRANSITIONS)}")
    strength = _number(strength, "transition strength", 0, 1)
    out_values = {name: EFFECTS[name][3] for name in _CUT_OUT}
    in_values = {name: EFFECTS[name][3] for name in _CUT_IN}
    outgoing, incoming = TRANSITIONS[kind]
    for target, values in ((out_values, outgoing), (in_values, incoming)):
        for name, value in values.items():
            if name == "zoom":
                target[name] = round(1 + .3 * strength, 6)
            else:
                target[name] = round(value * strength, 6)
    return out_values, in_values


def natural_look(effects, keep=()):
    """Remove every look from an effects dict, except names listed in keep."""
    for name in LOOK_EFFECTS:
        if name not in keep:
            effects.pop(name, None)
    return effects


def catalog():
    """Machine-readable description for the `effects` command and documentation."""
    return {
        "effects": {name: {"group": group, "minimum": minimum, "maximum": maximum,
                           "neutral": neutral, "description": description}
                    for name, (group, minimum, maximum, neutral, description) in EFFECTS.items()},
        "grades": list(GRADES),
        "transitions": {name: {"outgoing": sorted(k for k in out), "incoming": sorted(k for k in incoming)}
                        for name, (out, incoming) in TRANSITIONS.items()},
        "notes": [
            "Accent and transition effects never overlap shots or change frame counts.",
            "The planner keeps accent effects only on accent cuts; use revise effects/transition to place them elsewhere.",
            "pulse uses the project's measured beat_frames; it has no effect without beats.",
            "grade none removes the colour grade and every look (vignette, grain, glow, letterbox); neutral keeps the looks.",
            "At most three flash, dip or invert cuts fit in one second: plan drops the extra ones, revise refuses them.",
        ],
    }

"""Persistent, atomic project revisions and a local interactive review page."""

import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

from editorial_feedback import normalize_shot_type


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    """Never replace a valid project with a partially written JSON document."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _number(value, label, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{label} must be finite and >= {minimum}")
    return value


def _selected(edits, operation):
    if "shot" in operation:
        target = operation["shot"]
        if isinstance(target, int) and not isinstance(target, bool):
            if 1 <= target <= len(edits):
                return [edits[target - 1]]
        else:
            found = [e for e in edits if e["id"] == target]
            if found:
                return found
        raise ValueError(f"Unknown shot: {target!r}; numeric shot positions start at 1")
    if "section" in operation:
        found = [e for e in edits if e.get("section") == operation["section"]]
        if not found:
            raise ValueError(f"No shots in section {operation['section']!r}")
        return found
    if operation.get("all") is True:
        return edits
    raise ValueError("Specify shot, section, or all: true for each revision")


def _retime(plan, update_sections=False):
    cursor = 0
    fps = plan["output"]["fps"]
    for shot in plan["edits"]:
        shot["timeline_start_frame"] = cursor
        cursor += shot["duration_frames"]
        shot["timeline_end_frame"] = cursor
        if shot["kind"] == "video":
            shot["average_speed"] = (shot["source_end"] - shot["source_start"]) / (shot["duration_frames"] / fps)
    if cursor != plan["duration_frames"]:
        raise ValueError("Revision changed total duration; duration changes must borrow frames from another shot")
    if update_sections:
        plan.setdefault("original_sections", copy.deepcopy(plan["sections"]))
        sections = []
        for shot in plan["edits"]:
            if sections and sections[-1]["name"] == shot["section"]:
                sections[-1]["end_frame"] = shot["timeline_end_frame"]
            else:
                sections.append({"name": shot["section"], "start_frame": shot["timeline_start_frame"],
                                 "end_frame": shot["timeline_end_frame"], "source": "manual_revision"})
        plan["sections"] = sections
        plan["timing_manually_revised"] = True


def _slowest(shot, fps):
    """Slowest playback speed within a shot (1 for photos)."""
    if shot.get("kind") != "video":
        return 1.0
    from project_plan import speed_bounds
    return speed_bounds(shot, shot["duration_frames"] / fps)[0]


def _replacement_span(plan, shot, clip):
    """Find unused footage for a replacement, preferring normal-speed playback."""
    if clip["kind"] == "image":
        return float(clip["start"]), float(clip["end"])
    intervals = [(float(clip["start"]), float(clip["end"]))]
    if not plan.get("policies", {}).get("allow_repeats", False):
        occupied = [(e["source_start"], e["source_end"]) for e in plan["edits"]
                    if e is not shot and e["kind"] == "video" and e["source"] == clip["source"]]
        for used_start, used_end in sorted(occupied):
            remaining = []
            for start, end in intervals:
                if used_end <= start or used_start >= end:
                    remaining.append((start, end))
                else:
                    if used_start > start:
                        remaining.append((start, used_start))
                    if used_end < end:
                        remaining.append((used_end, end))
            intervals = remaining
    required = shot["duration_frames"] / plan["output"]["fps"]
    enough = [interval for interval in intervals if interval[1] - interval[0] >= required - 1e-7]
    if enough:
        start, _ = enough[0]
        return start, start + required
    # Without an explicit source range a replacement never slows its shot, even
    # when slow motion is allowed: slowing must be asked for with a range.
    minimum = required * max(1, plan.get("policies", {}).get("min_speed", 1))
    if intervals:
        start, end = max(intervals, key=lambda span: span[1] - span[0])
        if end - start >= minimum - 1e-7:
            return start, end
    raise ValueError("No unused replacement range is long enough; choose another clip or shorten the shot")


_TRANSITION_FIELDS = {"op", "type", "strength", "after", "section", "all"}


def _clear_transition_in(shot):
    """Undo the incoming side of a transition: its accents, whip_in and its zoom.

    Cleared values are removed rather than written as 0, so a cut that had no
    transition keeps its cache key.
    """
    from edit_effects import transition_effects
    marker = shot.pop("transition_in", None)
    effects = shot.setdefault("effects", {})
    for name in transition_effects("cut")[1]:
        effects.pop(name, None)
    if marker and "zoom_before" in marker:
        effects["zoom"] = marker["zoom_before"]


def _clear_transition_out(shot):
    from edit_effects import transition_effects
    shot.pop("transition_out", None)
    effects = shot.setdefault("effects", {})
    for name in transition_effects("cut")[0]:
        effects.pop(name, None)


def _set_transition(before, after, kind, strength):
    from edit_effects import EFFECTS, transition_effects
    outgoing, incoming = transition_effects(kind, strength)
    _clear_transition_in(after)
    _clear_transition_out(before)
    if kind == "cut":
        return
    before["effects"].update({k: v for k, v in outgoing.items() if v != EFFECTS[k][3]})
    marker = {"type": kind, "from": before["id"]}
    if "zoom" in incoming:
        # zoom_before is restored when the transition changes. A photo's zoom is
        # a slow push over the whole shot, not a punch at the cut, so a still
        # keeps only the defocus; the punch returns if it becomes video again.
        marker.update(zoom_before=after["effects"].get("zoom", 1.0), zoom=incoming["zoom"])
        if after.get("kind") == "image":
            incoming.pop("zoom")
    after["effects"].update({k: v for k, v in incoming.items() if v != EFFECTS[k][3]})
    after["transition_in"] = marker
    before["transition_out"] = {"type": kind, "to": after["id"]}


def _clear_neighbour_transitions(edits, shot):
    """Clear the far side of every transition on this shot's cuts (used by reset)."""
    by_id = {item["id"]: item for item in edits}
    marker = shot.get("transition_in")
    neighbour = by_id.get(marker.get("from")) if marker else None
    if neighbour is not None and (neighbour.get("transition_out") or {}).get("to") == shot["id"]:
        _clear_transition_out(neighbour)
    marker = shot.get("transition_out")
    neighbour = by_id.get(marker.get("to")) if marker else None
    if neighbour is not None and (neighbour.get("transition_in") or {}).get("from") == shot["id"]:
        _clear_transition_in(neighbour)


def _apply_transition(edits, operation):
    """Set the transition of one or more cuts; `type: cut` removes it."""
    from project_plan import SECTION_NAMES
    unknown = set(operation) - _TRANSITION_FIELDS
    if unknown:
        raise ValueError(f"Unknown transition fields: {sorted(unknown)}")
    if "type" not in operation:
        raise ValueError("transition requires type (cut removes a transition)")
    selectors = [key for key in ("after", "section", "all") if key in operation]
    if len(selectors) != 1:
        raise ValueError("transition takes exactly one of after (shot number or id), section, or all: true")
    if len(edits) < 2:
        raise ValueError("A transition needs at least two shots")
    if "after" in operation:
        shot = _selected(edits, {"shot": operation["after"]})[0]
        index = edits.index(shot)
        if index == len(edits) - 1:
            raise ValueError("transition after the final shot has no following cut")
        cuts = [index]
    elif "section" in operation:
        names = list(dict.fromkeys([*SECTION_NAMES, *(shot.get("section") for shot in edits if shot.get("section"))]))
        if operation["section"] not in names:
            raise ValueError(f"transition section must be one of {', '.join(names)}")
        cuts = [index for index in range(len(edits) - 1) if edits[index + 1].get("section") == operation["section"]]
        if not cuts:
            present = sorted({shot.get("section") for shot in edits[1:] if shot.get("section")})
            raise ValueError(f"No cuts lead into shots of section {operation['section']!r}; "
                             f"this project's cuts lead into {', '.join(present) or 'no named sections'} "
                             "(use after or all: true)")
    else:
        if operation["all"] is not True:
            raise ValueError("transition all must be true")
        cuts = list(range(len(edits) - 1))
    for index in cuts:
        _set_transition(edits[index], edits[index + 1], operation["type"], operation.get("strength", 1.0))


def _repair_transitions(edits):
    """After any edit, drop transitions whose two shots are no longer adjacent.

    A zoom transition's punch follows the shot's kind (replace, B-roll): a
    still gets the zoom it had before, a video the punch, unless an explicit
    zoom has replaced both (that removes zoom_before).
    """
    for index, shot in enumerate(edits):
        marker = shot.get("transition_in")
        if marker and "zoom_before" in marker and "zoom" in marker:
            effects = shot.setdefault("effects", {})
            current = effects.get("zoom", 1.0)
            if shot.get("kind") == "image" and current == marker["zoom"]:
                effects["zoom"] = marker["zoom_before"]
            elif shot.get("kind") != "image" and current == marker["zoom_before"]:
                effects["zoom"] = marker["zoom"]
        marker = shot.get("transition_in")
        if marker and (index == 0 or edits[index - 1]["id"] != marker.get("from")):
            _clear_transition_in(shot)
        marker = shot.get("transition_out")
        if marker and (index == len(edits) - 1 or edits[index + 1]["id"] != marker.get("to")):
            _clear_transition_out(shot)


def apply_revisions(plan, operations):
    """Apply deterministic edits to a copy; errors leave the original untouched.

    Supported operations: replace, effects, transition, reframe, speed,
    duration, reorder, plus the text, speech and graphics operations.
    A duration edit borrows frames from the following shot, or an explicit donor.
    """
    from project_plan import validate_plan, _slow_motion_authorized
    from text_project import TEXT_OPERATIONS, apply_text_operation
    from speech_project import SPEECH_OPERATIONS, apply_speech_operation, refresh_source_captions
    from timeline_map import refresh_anchors
    from graphics_commands import GRAPHICS_OPERATIONS, apply_graphics_operation
    from edit_effects import validate_effects

    if not isinstance(operations, list) or not operations:
        raise ValueError("revisions must be a non-empty list of operations")
    if any(not isinstance(operation, dict) for operation in operations):
        raise ValueError("Each revision must be an object")
    result = copy.deepcopy(plan)
    policy_changes = [operation for operation in operations if operation.get("op") == "slow_motion_policy"]
    if len(policy_changes) > 1:
        raise ValueError("Only one slow_motion_policy change is allowed per revision")
    if policy_changes:
        operation = policy_changes[0]
        prompt = operation.get("prompt", "")
        policy = result.setdefault("policies", {})
        policy.update(allow_slow_motion=bool(prompt), slow_motion_prompt=prompt,
                      interpolation=operation.get("interpolation", "none"))
        enabled = _slow_motion_authorized(policy)
        policy["min_speed"] = _number(operation.get("min_speed", .5 if enabled else 1), "min_speed", .001)
        if not enabled and policy["min_speed"] < 1:
            raise ValueError("min_speed below 1 requires an explicit user prompt and optical_flow interpolation")
    # An explicitly requested policy upgrade can make an old slow project valid.
    # No media edit implicitly grants this permission or fabricates prompt text.
    validate_plan(result)
    edits = result["edits"]
    fps = result["output"]["fps"]
    from edit_effects import flash_burst_message, flash_runs
    # An older project may already flash too often; a revision may keep, shrink
    # or move those bursts, but not pull another shot into one, join two, or
    # make one denser. Each run is compared with the one run it came from.
    runs_before = [(shots, peak) for _, shots, peak in flash_runs(edits, fps)]
    catalog = {str(c["id"]): c for c in result.get("clips", [])}
    slowest_before = {shot["id"]: _slowest(shot, fps) for shot in edits}
    explicitly_retimed = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Each revision must be an object")
        kind = operation.get("op")
        if kind == "slow_motion_policy":
            continue
        elif kind in TEXT_OPERATIONS:
            apply_text_operation(result, operation)
        elif kind in SPEECH_OPERATIONS:
            apply_speech_operation(result, operation)
        elif kind in GRAPHICS_OPERATIONS:
            apply_graphics_operation(result, operation)
        elif kind == "transition":
            _apply_transition(edits, operation)
        elif kind == "reorder":
            order = operation.get("order", [])
            if len(order) != len(edits) or set(order) != {e["id"] for e in edits}:
                raise ValueError("reorder must contain every shot id exactly once")
            by_id = {e["id"]: e for e in edits}
            edits[:] = [by_id[i] for i in order]
            _repair_transitions(edits)
        else:
            selected = _selected(edits, operation)
            if kind == "replace":
                if len(selected) != 1:
                    raise ValueError("replace requires one shot")
                clip = catalog.get(str(operation.get("clip_id")))
                if clip is None:
                    raise ValueError("replace requires a clip_id from the project's clip catalog")
                shot = selected[0]
                default_start, default_end = _replacement_span(result, shot, clip) if "source_start" not in operation and "source_end" not in operation else (clip["start"], None)
                start = _number(operation.get("source_start", default_start), "source_start")
                available = float(clip["end"]) - start
                required = shot["duration_frames"] / fps
                end = _number(operation.get("source_end", default_end if default_end is not None else start + min(available, required)), "source_end")
                ranged = "source_start" in operation or "source_end" in operation
                if clip["kind"] == "image":
                    if ranged and (abs(start - float(clip["start"])) > 1e-6 or abs(end - float(clip["end"])) > 1e-6):
                        raise ValueError("A photo has no motion to slow or trim; omit source_start/source_end for an image clip")
                    start, end = float(clip["start"]), float(clip["end"])
                elif not (clip["start"] <= start < end <= clip["end"] + 1e-6):
                    raise ValueError("Replacement source range must fit inside the selected clip")
                if ranged:
                    explicitly_retimed.add(shot["id"])
                shot.update(asset_id=clip["asset_id"], clip_id=clip["id"], source=clip["source"],
                            kind=clip["kind"], source_start=start, source_end=end,
                            tags=copy.deepcopy(clip.get("tags", [])), shot_type=normalize_shot_type(clip.get("shot_type")))
                shot["speed_points"] = [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]
                shot.pop("action_anchor", None)
                shot["reframe"] = {"mode": "auto", "subject": clip.get("subject"), "subject_start": clip["start"]}
            elif kind == "effects":
                effects = operation.get("values", {})
                reset = operation.get("reset", False)
                if not isinstance(reset, bool):
                    raise ValueError("effects reset must be true or false")
                if not isinstance(effects, dict) or (not effects and not reset):
                    raise ValueError("effects requires a non-empty values object or reset: true")
                validate_effects(effects, "effects values")
                from edit_effects import NATURAL_GRADE, natural_look
                if reset:
                    # A reset removes the whole transition on each of the shot's cuts,
                    # not only this shot's half. Neighbours first, before any reset.
                    for shot in selected:
                        _clear_neighbour_transitions(edits, shot)
                for shot in selected:
                    if reset:
                        shot["effects"] = {}
                        shot.pop("transition_in", None)
                        shot.pop("transition_out", None)
                    if "zoom" in effects:
                        # An explicit zoom replaces the one a zoom transition would restore.
                        (shot.get("transition_in") or {}).pop("zoom_before", None)
                    shot.setdefault("effects", {}).update(copy.deepcopy(effects))
                    if effects.get("grade") == NATURAL_GRADE:
                        natural_look(shot["effects"], keep=effects)
            elif kind == "reframe":
                mode = operation.get("mode", "manual")
                if mode not in ("auto", "center", "manual", "contain"):
                    raise ValueError("reframe mode must be auto, center, manual, or contain")
                if mode == "manual" and not operation.get("subject") and not operation.get("keyframes"):
                    raise ValueError("manual reframe requires normalized subject bbox [x,y,w,h]")
                for shot in selected:
                    shot["reframe"] = {"mode": mode, "subject": operation.get("subject"),
                                       "subject_start": operation.get("subject_start", shot["source_start"])}
                    for key in ("keyframes", "sample_fps", "confidence_threshold"):
                        if key in operation:
                            shot["reframe"][key] = copy.deepcopy(operation[key])
            elif kind == "speed":
                points = operation.get("points")
                if not isinstance(points, list) or len(points) < 2:
                    raise ValueError("speed requires at least two {at, speed} points")
                for shot in selected:
                    explicitly_retimed.add(shot["id"])
                    shot["speed_points"] = copy.deepcopy(points)
                    if "anchor" in operation:
                        shot["action_anchor"] = copy.deepcopy(operation["anchor"])
                    else:
                        shot.pop("action_anchor", None)
            elif kind == "duration":
                if len(selected) != 1:
                    raise ValueError("duration requires one shot")
                shot = selected[0]
                frames = round(_number(operation["seconds"], "seconds", 1 / fps) * fps)
                delta = frames - shot["duration_frames"]
                donor_target = operation.get("borrow_from")
                if donor_target is None:
                    index = edits.index(shot)
                    if len(edits) == 1:
                        raise ValueError("A single-shot project cannot redistribute duration")
                    donor = edits[index + 1 if index + 1 < len(edits) else index - 1]
                else:
                    donor = _selected(edits, {"shot": donor_target})[0]
                if donor is shot or donor["duration_frames"] - delta < 1:
                    raise ValueError("Not enough frames in donor shot; choose another borrow_from shot")
                shot["duration_frames"] = frames
                donor["duration_frames"] -= delta
                explicitly_retimed.add(shot["id"])  # the named shot, never its donor
            else:
                raise ValueError(f"Unknown revision operation: {kind!r}")
        _retime(result, update_sections=kind in ("duration", "reorder"))
        _repair_transitions(result["edits"])
    for shot in edits:
        if shot["id"] not in explicitly_retimed and _slowest(shot, fps) < 1 - 1e-6 <= slowest_before.get(shot["id"], 1):
            raise ValueError(f"{shot['id']} would play at {shot['average_speed']:.2f}x. Slow motion only applies to the shot "
                             "a revision names (duration, speed, or replace with source_start/source_end); give this "
                             "shot more source with a ranged replace in the same list, or choose another borrow_from")
    if any(operation.get("op") not in TEXT_OPERATIONS for operation in operations):
        refresh_source_captions(result)
    refresh_anchors(result)
    validate_plan(result)
    for bursts, shots, peak in flash_runs(result["edits"], fps):
        if not any(shots <= old and peak <= old_peak for old, old_peak in runs_before):
            raise ValueError("This revision would leave " + flash_burst_message(bursts, fps))
    result["revision"] = int(plan.get("revision", 0)) + 1
    result.setdefault("revision_log", []).append({
        "revision": result["revision"], "at": datetime.now(timezone.utc).isoformat(),
        "operations": copy.deepcopy(operations),
    })
    return result


def revise_file(path, operations, output=None):
    path = Path(path).resolve()
    original = read_json(path)
    revised = apply_revisions(original, operations)
    destination = Path(output).resolve() if output else path
    from render_qa import referenced_files
    protected = referenced_files(original) | referenced_files(revised) | referenced_files(operations)
    if destination in protected and destination != path:
        raise ValueError("Revised project cannot overwrite a source resource")
    # Retain an immutable copy of the prior project before replacing it.
    digest = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()[:12]
    history = destination.parent / ".history" / f"{destination.stem}-{digest}.json"
    if history in protected or history == path:
        raise ValueError("Revision history cannot overwrite a source resource")
    if not history.exists():
        write_json(history, original)
    write_json(destination, revised)
    return revised


def review_html(plan, video_path, output_path):
    """Standalone player/timeline and revision editor; no service or CDN needed."""
    out = Path(output_path).resolve()
    video = Path(video_path).resolve()
    try:
        media_url = quote(os.path.relpath(video, out.parent).replace(os.sep, "/"), safe="/:")
    except ValueError:
        media_url = video.as_uri()
    data = json.dumps({"fps": plan["output"]["fps"], "edits": plan["edits"],
                       "titles": plan.get("titles", []), "subtitles": plan.get("subtitles", []),
                       "clips": [{k: c.get(k) for k in ("id", "source", "start", "end", "tags", "shot_type")}
                                 for c in plan.get("clips", [])]}, ensure_ascii=False).replace("<", "\\u003c")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beat-Sync Edit · Review</title><style>
:root{color-scheme:dark;font:16px system-ui;background:#10151e;color:#e8eef8}
body{max-width:1120px;margin:32px auto;padding:0 24px}h1{font-size:28px}
main{display:grid;grid-template-columns:minmax(240px,1fr) minmax(320px,1fr);gap:24px}
video{width:100%;max-height:70vh;background:#000;border-radius:12px}
button,input,select,textarea{font:inherit;background:#202c3d;color:inherit;border:1px solid #465873;border-radius:6px;padding:8px}
button{cursor:pointer}button:hover{background:#315170}label{display:block;margin:14px 0 5px}
#shots{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0}#shots button{font-size:13px}
textarea{width:95%;height:180px;font:13px monospace}.muted{color:#a6b8cf}#status{min-height:24px;color:#8bd9b1}
@media(max-width:750px){main{display:block}}</style>
<h1>Beat-Sync Edit · Review</h1><p class="muted">Select a shot to inspect it. Queue changes and download the revision file, or describe your changes to your agent (Claude Code or Codex).</p>
<main><section><video id="player" controls preload="metadata" src="VIDEO"></video><div id="shots"></div></section>
<section><label for="shot">Shot</label><select id="shot"></select><p id="details" class="muted"></p>
<label for="replacement">Replacement clip</label><select id="replacement"></select><button id="replace">Queue replacement</button>
<label for="seconds">Shot duration (seconds; borrow from adjacent shot)</label><input id="seconds" type="number" min="0.1" step="0.1"><button id="duration">Queue duration</button>
<p><button id="flash">Remove all flashes</button> <button id="accents">Remove all accent effects</button> <button id="download">Download revisions.json</button></p>
<details><summary>Edit titles and subtitles</summary>
<label for="textcue">Text cue</label><select id="textcue"></select>
<label for="cuetext">Text</label><textarea id="cuetext" style="height:80px"></textarea>
<label for="cuestart">Start / end (seconds)</label><input id="cuestart" type="number" min="0" step="0.01"><input id="cueend" type="number" min="0" step="0.01">
<p><button id="textsave">Queue text change</button> <button id="textremove">Remove text cue</button></p></details>
<label for="operations">Queued revisions</label><textarea id="operations" readonly>[]</textarea><p id="status" role="status"></p>
<p class="muted">Changes apply on the next render. Give revisions.json to your agent, or run:<br><code>edit_project.py revise project.json --operations revisions.json</code><br>Then render a new preview.</p></section></main>
<script>const data=DATA,player=document.getElementById('player'),shot=document.getElementById('shot'),queue=[];
const el=id=>document.getElementById(id),add=op=>{queue.push(op);el('operations').value=JSON.stringify(queue,null,2);el('status').textContent='Change queued. Download revisions to apply.'};
data.edits.forEach((e,i)=>{let o=new Option(`${i+1}. ${e.id} · ${e.section}`,e.id);shot.add(o);let b=document.createElement('button');b.textContent=`${i+1} · ${(e.duration_frames/data.fps).toFixed(2)}s`;b.onclick=()=>{shot.value=e.id;selectShot(true)};el('shots').append(b)});
data.clips.forEach(c=>el('replacement').add(new Option(`${c.id} · ${(c.tags||[]).join(', ')} · ${c.shot_type||''}`,c.id)));
function selectShot(seek){let e=data.edits.find(e=>e.id===shot.value);if(!e)return;el('seconds').value=(e.duration_frames/data.fps).toFixed(3);el('details').textContent=`${e.source} | source ${e.source_start.toFixed(2)}–${e.source_end.toFixed(2)}s`;if(seek)player.currentTime=e.timeline_start_frame/data.fps}
shot.onchange=()=>selectShot(true);selectShot(false);
el('replace').onclick=()=>{if(el('replacement').value)add({op:'replace',shot:shot.value,clip_id:el('replacement').value})};
el('duration').onclick=()=>{let seconds=Number(el('seconds').value);if(Number.isFinite(seconds)&&seconds>0)add({op:'duration',shot:shot.value,seconds});else el('status').textContent='Enter a positive duration.'};
el('flash').onclick=()=>add({op:'effects',all:true,values:{flash:0}});
el('accents').onclick=()=>{if(data.edits.length>1)add({op:'transition',all:true,type:'cut'});add({op:'effects',all:true,values:ACCENTS})};
const cues=[...data.titles.map(c=>({...c,track:'title'})),...data.subtitles.map(c=>({...c,track:'subtitle'}))];
cues.forEach((c,i)=>el('textcue').add(new Option(`${c.track} · ${c.id} · ${c.text.slice(0,36)}`,String(i))));
function selectCue(seek){let c=cues[Number(el('textcue').value)];if(!c)return;el('cuetext').value=c.text;el('cuestart').value=(c.start_frame/data.fps).toFixed(3);el('cueend').value=(c.end_frame/data.fps).toFixed(3);if(seek)player.currentTime=c.start_frame/data.fps}
el('textcue').onchange=()=>selectCue(true);selectCue(false);
el('textsave').onclick=()=>{let c=cues[Number(el('textcue').value)];if(!c)return;let start=Number(el('cuestart').value),end=Number(el('cueend').value),text=el('cuetext').value;if(!text.trim()||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start){el('status').textContent='Enter text and a valid start/end range.';return}let values={start,end};if(text!==c.text)values.text=text;add({op:c.track+'_update',id:c.id,values})};
el('textremove').onclick=()=>{let c=cues[Number(el('textcue').value)];if(c)add({op:c.track+'_remove',id:c.id})};
el('download').onclick=()=>{if(!queue.length){el('status').textContent='Queue a change first.';return}let u=URL.createObjectURL(new Blob([JSON.stringify(queue,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=u;a.download='revisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};</script></html>'''
    # Substitute the JSON first so a filename containing DATA cannot become JS.
    # The distinct marker also avoids replacing user-controlled annotation text.
    from edit_effects import ACCENT_EFFECTS
    accents = json.dumps({name: 0 for name in ACCENT_EFFECTS + ("shake", "whip_in", "whip_out", "pulse")})
    page = page.replace("values:ACCENTS}", "values:" + accents + "}")
    page = page.replace("const data=DATA,", "const data=" + data + ",")
    page = page.replace('src="VIDEO"', 'src="' + html.escape(media_url, quote=True) + '"')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return str(out)

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
    minimum = required * plan.get("policies", {}).get("min_speed", .5)
    if intervals:
        start, end = max(intervals, key=lambda span: span[1] - span[0])
        if end - start >= minimum - 1e-7:
            return start, end
    raise ValueError("No unused replacement range is long enough; choose another clip or shorten the shot")


def apply_revisions(plan, operations):
    """Apply deterministic edits to a copy; errors leave the original untouched.

    Supported operations: replace, effects, reframe, speed, duration, reorder.
    A duration edit borrows frames from the following shot, or an explicit donor.
    """
    from project_plan import validate_plan

    validate_plan(plan)
    if not isinstance(operations, list) or not operations:
        raise ValueError("revisions must be a non-empty list of operations")
    result = copy.deepcopy(plan)
    edits = result["edits"]
    fps = result["output"]["fps"]
    catalog = {str(c["id"]): c for c in result.get("clips", [])}
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Each revision must be an object")
        kind = operation.get("op")
        if kind == "reorder":
            order = operation.get("order", [])
            if len(order) != len(edits) or set(order) != {e["id"] for e in edits}:
                raise ValueError("reorder must contain every shot id exactly once")
            by_id = {e["id"]: e for e in edits}
            edits[:] = [by_id[i] for i in order]
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
                if clip["kind"] == "video" and not (clip["start"] <= start < end <= clip["end"] + 1e-6):
                    raise ValueError("Replacement source range must fit inside the selected clip")
                shot.update(asset_id=clip["asset_id"], clip_id=clip["id"], source=clip["source"],
                            kind=clip["kind"], source_start=start, source_end=end,
                            tags=copy.deepcopy(clip.get("tags", [])), shot_type=clip.get("shot_type", "unknown"))
                shot["speed_points"] = [{"at": 0, "speed": 1}, {"at": 1, "speed": 1}]
                shot.pop("action_anchor", None)
                shot["reframe"] = {"mode": "auto", "subject": clip.get("subject"), "subject_start": clip["start"]}
            elif kind == "effects":
                effects = operation.get("values")
                if not isinstance(effects, dict) or not effects:
                    raise ValueError("effects requires a non-empty values object")
                unknown = set(effects) - {"flash", "zoom", "shake", "grade"}
                if unknown:
                    raise ValueError(f"Unknown effects: {sorted(unknown)}")
                for shot in selected:
                    shot.setdefault("effects", {}).update(effects)
            elif kind == "reframe":
                mode = operation.get("mode", "manual")
                if mode not in ("auto", "center", "manual", "contain"):
                    raise ValueError("reframe mode must be auto, center, manual, or contain")
                if mode == "manual" and not operation.get("subject"):
                    raise ValueError("manual reframe requires normalized subject bbox [x,y,w,h]")
                for shot in selected:
                    shot["reframe"] = {"mode": mode, "subject": operation.get("subject"),
                                       "subject_start": operation.get("subject_start", shot["source_start"])}
            elif kind == "speed":
                points = operation.get("points")
                if not isinstance(points, list) or len(points) < 2:
                    raise ValueError("speed requires at least two {at, speed} points")
                for shot in selected:
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
            else:
                raise ValueError(f"Unknown revision operation: {kind!r}")
        _retime(result, update_sections=kind in ("duration", "reorder"))
    validate_plan(result)
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
    # Retain an immutable copy of the prior project before replacing it.
    digest = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()[:12]
    history = destination.parent / ".history" / f"{destination.stem}-{digest}.json"
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
<h1>Beat-Sync Edit · Review</h1><p class="muted">Select a shot to inspect it. Queue changes and download the revision file, or describe your changes to Codex.</p>
<main><section><video id="player" controls preload="metadata" src="VIDEO"></video><div id="shots"></div></section>
<section><label for="shot">Shot</label><select id="shot"></select><p id="details" class="muted"></p>
<label for="replacement">Replacement clip</label><select id="replacement"></select><button id="replace">Queue replacement</button>
<label for="seconds">Shot duration (seconds; borrow from adjacent shot)</label><input id="seconds" type="number" min="0.1" step="0.1"><button id="duration">Queue duration</button>
<p><button id="flash">Remove all flashes</button> <button id="download">Download revisions.json</button></p>
<label for="operations">Queued revisions</label><textarea id="operations" readonly>[]</textarea><p id="status" role="status"></p>
<p class="muted">Changes apply on the next render. Give revisions.json to Codex, or run:<br><code>edit_project.py revise project.json --operations revisions.json</code><br>Then render a new preview.</p></section></main>
<script>const data=DATA,player=document.getElementById('player'),shot=document.getElementById('shot'),queue=[];
const el=id=>document.getElementById(id),add=op=>{queue.push(op);el('operations').value=JSON.stringify(queue,null,2);el('status').textContent='Change queued. Download revisions to apply.'};
data.edits.forEach((e,i)=>{let o=new Option(`${i+1}. ${e.id} · ${e.section}`,e.id);shot.add(o);let b=document.createElement('button');b.textContent=`${i+1} · ${(e.duration_frames/data.fps).toFixed(2)}s`;b.onclick=()=>{shot.value=e.id;selectShot(true)};el('shots').append(b)});
data.clips.forEach(c=>el('replacement').add(new Option(`${c.id} · ${(c.tags||[]).join(', ')} · ${c.shot_type||''}`,c.id)));
function selectShot(seek){let e=data.edits.find(e=>e.id===shot.value);if(!e)return;el('seconds').value=(e.duration_frames/data.fps).toFixed(3);el('details').textContent=`${e.source} | source ${e.source_start.toFixed(2)}–${e.source_end.toFixed(2)}s`;if(seek)player.currentTime=e.timeline_start_frame/data.fps}
shot.onchange=()=>selectShot(true);selectShot(false);
el('replace').onclick=()=>{if(el('replacement').value)add({op:'replace',shot:shot.value,clip_id:el('replacement').value})};
el('duration').onclick=()=>{let seconds=Number(el('seconds').value);if(Number.isFinite(seconds)&&seconds>0)add({op:'duration',shot:shot.value,seconds});else el('status').textContent='Enter a positive duration.'};
el('flash').onclick=()=>add({op:'effects',all:true,values:{flash:0}});
el('download').onclick=()=>{if(!queue.length){el('status').textContent='Queue a change first.';return}let u=URL.createObjectURL(new Blob([JSON.stringify(queue,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=u;a.download='revisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};</script></html>'''
    # Substitute the JSON first so a filename containing DATA cannot become JS.
    # The distinct marker also avoids replacing user-controlled annotation text.
    page = page.replace("const data=DATA,", "const data=" + data + ",")
    page = page.replace('src="VIDEO"', 'src="' + html.escape(media_url, quote=True) + '"')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return str(out)

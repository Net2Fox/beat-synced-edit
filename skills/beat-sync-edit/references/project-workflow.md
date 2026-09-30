# Persistent editing projects

Use `scripts/edit_project.py` for exact-duration edits, mixed media, semantic
selection, music structure, tracked vertical framing, speed ramps and revisions.
Use the skill's Python interpreter with `-X utf8`; pass absolute paths. All files
below live in the user's project work directory, not the skill installation.

## Analyze and review

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" analyze $footageFolder $extraVideo $photosZip --work "$work/library"
& $editPython -X utf8 "$editScripts/edit_project.py" music $song --duration 25 -o "$work/beats.json"
```

Inputs may be files, folders, or ZIPs. ZIP contents are imported persistently
under `work/library/imports/`. Keep that directory with the project. Each asset
has a unique ID and absolute path, including files with identical basenames.
Images respect EXIF orientation; video dimensions, frame rate and rotation are
probed individually. The renderer normalizes them to the selected output format.

Open **every** returned contact sheet. Inspect extra frames around actions and
within long scenes when a single thumbnail is insufficient. Use visible evidence
to annotate objects, shot sizes, quality and action moments. Energy and image
fingerprints alone do not identify objects or understand a narrative.

Write annotations using actual clip IDs from `library.json`:

```json
{
  "clips": {
    "asset_0123456789ab:0000": {
      "tags": ["car", "drift"],
      "shot_type": "action",
      "action_time": 3.2,
      "subject": [0.35, 0.25, 0.3, 0.5],
      "quality": 0.9,
      "notes": "Car turns toward camera; strongest action at 3.2 seconds"
    }
  }
}
```

`action_time` is absolute source time inside that clip. `subject` is normalized
`[left, top, width, height]`, all within the image. Allowed shot types: `wide`,
`establishing`, `medium`, `closeup`, `close-up`, `detail`, `action`, `unknown`.
Use `exclude: true` for unusable footage. Do not infer unseen actions or label an
unreviewed clip as reviewed. Verify a supplied subject box on the initial frame
of the scene (`subject_thumb` at `subject_thumb_time`) before using it to
initialize tracking. The plan retains that tracking start even when it selects
a later source range from the scene.

Apply observations without decoding sources again:

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" annotate "$work/library/library.json" --annotations "$work/annotations.json"
```

You can also re-run `analyze` with `--annotations`. Keep the same input list when
re-running; otherwise omitted assets will leave the library.

## Plan

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" plan --library "$work/library/library.json" --beats "$work/beats.json" --duration 25 --preset car --size 1080x1920 --fps 30 -o "$work/project.json"
```

`--preset` accepts `cinematic`, `car`, `gaming`, `product`. Run `presets` to see
their actual pace, color, transition and speed settings. Choose from the user's
intent; a preset is a starting point and explicit requests take precedence.
Use `--section-stride drop=1 --min-shot 0.25` for faster cuts in the middle while
retaining longer intro/outro plans; repeat `--section-stride NAME=N` for other
sections. `--beat-stride N` changes every section. `--min-shot`/`--max-shot`
bound nominal shot lengths (a final section boundary or source shortage may
require a shorter remainder). `--grade none` preserves natural color;
`--tags car drift` prefers those reviewed labels; `--exclude CLIP_ID ...`
omits named clips. Speed limits use `--min-speed`/`--max-speed`.

The plan contains frame-based timing, intro/build/drop/outro sections, selected
source ranges and per-shot effects. Music structure is estimated from beats and
energy; it is editable, not a claim to recognize musical form perfectly. Inspect
the selected audio start and section boundaries. `--audio-start` sets a specific
start in seconds; `--sections` accepts a JSON array of `{name, start, end}`
records in output seconds (or `start_frame`, `end_frame`). Names are `intro`,
`build`, `drop`, `outro`; sections must cover the whole output contiguously.

```json
[
  {"name": "intro", "start": 0, "end": 4},
  {"name": "build", "start": 4, "end": 8},
  {"name": "drop", "start": 8, "end": 21},
  {"name": "outro", "start": 21, "end": 25}
]
```

Duration is rounded to the nearest output frame, and the renderer verifies the
frame count. A 25-second request at 30 fps yields 750 frames. Shortage policy:
`--shortage extend` may use unused source ranges and slower playback;
`--shortage error` fails when natural-speed material is insufficient;
`--shortage repeat --allow-repeats` explicitly permits reused footage. Preserve
the user's constraints: if material is still insufficient, request more footage
or a change to duration/repeat policy rather than silently ignoring them.

## Preview and revise

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" preview "$work/project.json" -o "$work/preview.mp4"
```

This renders a smaller video plus an offline HTML review page with a player,
shot navigation and a revision-file editor. Open the HTML or show the MP4.
Inspect representative frames, subject visibility, rhythm and audio alignment.
If the user already requested a final export, continue through verification;
preview generation itself does not require another approval.

Translate conversational revisions into JSON operations. Shot numbers start at
**1**; persistent IDs such as `shot-001` are preferable after reordering.

```json
[
  {"op": "replace", "shot": 3, "clip_id": "asset_0123456789ab:0000"},
  {"op": "effects", "all": true, "values": {"flash": 0}},
  {"op": "duration", "shot": 1, "seconds": 2.5, "borrow_from": 2}
]
```

Replacement preserves output duration. A duration revision borrows frames from
another shot, preserving the total; by default it uses the next shot (previous
for the final shot). It changes effective playback speed, so review the result.
Timing/reordering revisions also update the section spans; the original musical
sections remain in `original_sections`. Check the revised cuts against the beat
map, since an explicitly changed duration may move a cut off a beat.
Effects can target `shot`, `section`, or `all: true`. Supported values are
`flash`/`shake` from 0 to 1, `zoom` >= 1, and a supported `grade`.

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" revise "$work/project.json" --operations "$work/revisions.json"
& $editPython -X utf8 "$editScripts/edit_project.py" preview "$work/project.json" -o "$work/preview-v2.mp4"
```

Revisions are validated before writing; previous project JSON is saved under
`.history/`. Unchanged rendered shots are reused from the cache. Keep the saved
project, library, imports and original media to continue in another session.

## Tracking and smooth speed changes

`reframe.mode = auto` tracks a supplied subject box, or uses face/motion cues
when no box is given. Review tracking: occlusion and scene changes can break
visual tracking. `center` is a fixed central crop; `manual` locks a chosen subject
region; `contain` preserves the whole image with bars. For a moving target chosen
by the user, use `auto` with its initial bounding box.

```json
[
  {"op": "reframe", "shot": 3, "mode": "auto", "subject": [0.35, 0.25, 0.3, 0.5]},
  {"op": "speed", "shot": 3,
   "points": [{"at": 0, "speed": 2}, {"at": 0.5, "speed": 0.8}, {"at": 1, "speed": 2}],
   "anchor": {"source_time": 3.2, "output_fraction": 0.5}}
]
```

Speed points are **relative weights** along normalized output time, smoothly
interpolated and normalized to consume the selected source range. The source
span divided by output duration is the average speed. An action anchor fixes
the named source moment to an exact output fraction; choose that fraction from
the desired beat. Slow motion blends source frames; it is not generative or
optical-flow motion reconstruction. Preserve frame/time units when revising.
The planner's speed limits also apply to revisions, including the anchored
curve. If a curve exceeds them, choose gentler weights or an appropriate source
span; change the limits only when that matches the user's intended effect.

## Final render

```powershell
& $editPython -X utf8 "$editScripts/edit_project.py" render "$work/project.json" -o "$outputs/edit.mp4"
```

Output is H.264/AAC MP4 with square pixels. The verification JSON records actual
dimensions, video frames and audio presence. Use technical checks plus visual
and musical review; do not treat successful encoding as proof of editorial
quality. Keep preview and final paths distinct. Read the project's warnings and
report any tracking or playback aspects that remain unverified.

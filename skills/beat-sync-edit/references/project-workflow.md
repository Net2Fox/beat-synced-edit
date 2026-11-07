# Music montage projects

Read this when you build or change a music-driven edit, or need the complete
list of revision operations. Speech-first edits are in
[speech-workflow.md](speech-workflow.md), text, graphics and anchors in
[text-and-graphics.md](text-and-graphics.md), sound in
[audio-workflow.md](audio-workflow.md).

Contents: [Analyze and annotate](#analyze-and-annotate) ·
[Measure the music](#measure-the-music) · [Plan](#plan) · [Preview](#preview) ·
[Revise](#revise) · [Tracking and reframing](#tracking-and-reframing) ·
[Speed ramps](#speed-ramps) · [Requested slow motion](#requested-slow-motion) ·
[Final render](#final-render)

## Analyze and annotate

```sh
edit_project.py analyze <footage> <more-footage.mp4> <photos.zip> --work <work>/library
```

Inputs may be files, folders or ZIPs; ZIP contents are extracted to
`<work>/library/imports/`, which stays part of the project. Every asset gets a
unique ID and absolute path, even when basenames repeat; EXIF orientation and
each video's size, frame rate and rotation are normalised to the output format.
The command writes `<work>/library/library.json` and returns `contact_sheets`.
Each detected scene is one clip with ID `<asset_id>:<NNNN>`, source `start` and
`end` seconds, measured energy/motion with their sample times, a `thumb` and a
`subject_thumb` (the scene's first frame, at `subject_thumb_time`).

Open every contact sheet, plus extra frames around actions and in long scenes.
Energy and image fingerprints do not identify objects or follow a story, so
tags, shot types and actions come only from what you saw (the
report-only-what-you-observed rule in [SKILL.md](../SKILL.md#hard-rules)).
Write `<work>/annotations.json` keyed by clip IDs from `library.json`:

```json
{"clips": {"asset_0123456789ab:0000": {
  "tags": ["car", "drift"], "shot_type": "action", "action_time": 3.2,
  "subject": [0.35, 0.25, 0.3, 0.5], "quality": 0.9,
  "notes": "Car turns toward camera; strongest action at 3.2 seconds"}}}
```

| Field | Meaning |
|---|---|
| `tags` | non-empty strings; presets and `plan --tags` prefer matching clips |
| `shot_type` | `wide`, `medium`, `close`, `detail`, `action` or `unknown`; `establishing` (wide), `close-up`/`closeup` (close) and `extreme close-up`/`macro` (detail) are accepted and stored as the canonical name |
| `action_time` | absolute source seconds inside the clip; the planner tries to land it on a beat ([Speed ramps](#speed-ramps)) |
| `subject` | normalised `[left, top, width, height]` inside the image, measured on `subject_thumb`; tracking starts from that frame even when the plan uses a later part of the scene |
| `quality` | 0 to 1 |
| `exclude` | `true` keeps an unusable clip out of plans |
| `notes` | free text; `--query` matches it together with tags |
| `annotation_evidence` | optional: `reviewer`, `notes`, `frames` (source seconds you looked at, inside the clip), `confidence` 0 to 1 |

Apply the annotations without decoding the sources again:

```sh
edit_project.py annotate <work>/library/library.json --annotations <work>/annotations.json
```

It updates the library in place (`-o` writes a copy) and reports
`semantic_review: complete` once every clip has an annotation. `analyze` with
`--annotations <work>/annotations.json` does the same, but give it the same
input list: assets left out drop out of the library. Re-running is cheap
(measurements are cached by source content; annotations are applied fresh).

## Measure the music

```sh
edit_project.py music <song> --duration 25 -o <work>/beats.json
```

`--duration` (default 25) picks the most energetic window of that length as
`best_segment`; `plan` starts the audio there unless `--audio-start` is given,
so pass the same duration to both. The map also holds beats, energy, beat
confidence and phrase/event hypotheses; to judge or correct them, read
[music-editorial.md](music-editorial.md). To shorten or rearrange the song by
bars first, run `arrange-music` ([audio-workflow.md](audio-workflow.md)) and
plan with the `.beats.json` it writes next to the arranged WAV.

## Plan

```sh
edit_project.py plan --library <work>/library/library.json --beats <work>/beats.json --duration 25 --preset car --grade none --size 1080x1920 --fps 30 -o <work>/project.json
```

Defaults: `--duration 25`, `--preset cinematic`, `--size 1080x1920`,
`--fps 30`, `--pacing-mode auto`, `--reframe auto`, `--shortage extend`,
`--min-speed 1`, `--max-speed 3`, `--interpolation none`; without `--grade` the
preset's grade applies. Flags override the preset's values.

### Presets

| Preset | Character | Grade |
|---|---|---|
| `cinematic` (default) | patient establishing shots, gentle build, restrained accents | `cinematic` |
| `car` | wide/detail alternation, accelerating pace, punchy drop accents | `cool` |
| `gaming` | action-focused rapid cuts, timed impact accents | `vivid` |
| `product` | clean overview/detail sequences, gentle motion | `warm` |

A preset sets beats per cut for each section, minimum/maximum shot length,
target energy, preferred tags, a shot-type cycle, effects and a build/drop
speed ramp (`edit_project.py presets` prints the values). Preferred tags and
the shot cycle steer which clips are chosen, so pick by subject first and fall
back to `cinematic`. Every preset grades every shot, adds a slight zoom to
every shot and puts its flash/zoom/shake accents on drop cuts (none in phrase
flow). `--grade none` keeps natural colour (the natural-look rule in
[SKILL.md](../SKILL.md#hard-rules)); `neutral` is the same.

### Request to flag

| The user asks for | Use |
|---|---|
| natural colour, or names no look | `--grade none` |
| a colour look | `--grade cinematic`, `cool`, `vivid` or `warm` |
| punchier, more cuts in the drop | `--section-stride drop=1` with a lower `--min-shot`, or the `car`/`gaming` preset |
| calmer | a larger `--section-stride NAME=N` for the busy sections, a higher `--min-shot`, the `cinematic`/`product` preset, or `--pacing-mode phrase_flow` |
| the same cut spacing everywhere | `--beat-stride N`; it replaces every section's stride and can make a slow preset faster |
| a longest or shortest shot | `--max-shot` / `--min-shot` in seconds |
| vertical, square, landscape; a frame rate | `--size 1080x1920`, `1080x1080`, `1920x1080` (even numbers); `--fps N` (1 to 120) |
| a particular part of the song | `--audio-start SECONDS`, or `arrange-music` first to cut the song by bars |
| particular content first | `--tags TAG ...` for annotated tags; `--query "text"` and `--preferences` ([music-editorial.md](music-editorial.md)) |
| a clip left out | `--exclude CLIP_ID ...`, or `exclude: true` in the annotations |
| the camera to follow a subject | `subject` boxes in the annotations (per clip), or `--subject X Y W H` (one box for every shot, replacing the annotated ones), with `--reframe auto` |
| the whole frame kept; a fixed centre crop | `--reframe contain` (bars); `--reframe center` |
| repeated footage allowed | `--allow-repeats` (with `--shortage repeat`) |
| no flashes; a different shot order | revisions `{"op": "effects", "all": true, "values": {"flash": 0}}`; `reorder` ([Revise](#revise)) |
| slow motion, in their own words | [Requested slow motion](#requested-slow-motion) |

`--section-stride` takes `intro`, `build`, `drop` or `outro`, can be repeated
and wins over `--beat-stride` for its section. Strides apply to beat cuts only.
`--min-shot`/`--max-shot` bound the nominal shot length; the last shot of a
section or a source shortage can be shorter.

### Pacing, sections and shortage

`--pacing-mode auto` cuts on beats (`beat_cut`) when the pulse supports it,
otherwise `phrase_flow`: holds on phrase and event boundaries in one `flow`
section ([music-editorial.md](music-editorial.md)). After planning, read
`audio.start`, `sections`, `diagnostics` and each shot's `selection` in
`project.json`; `edit_project.py inspect <work>/project.json` prints duration,
sections and diagnostics.

To set the sections yourself, pass `--sections <work>/sections.json`: a JSON
array of `{name, start, end}` in output seconds (or `start_frame`,
`end_frame`), names `intro`, `build`, `drop`, `outro`, contiguous and covering
the whole output.

```json
[{"name": "intro", "start": 0, "end": 4}, {"name": "build", "start": 4, "end": 8},
 {"name": "drop", "start": 8, "end": 21}, {"name": "outro", "start": 21, "end": 25}]
```

Duration is rounded to the nearest output frame (25 s at 30 fps is 750 frames)
and the renderer checks the frame count; from the audio start it must fit
inside the song. When unused footage runs short (the exact-duration rule in
[SKILL.md](../SKILL.md#hard-rules)), `--shortage extend` (default) uses the
available ranges within the speed limits and can hold stills longer,
`--shortage error` fails instead and `--shortage repeat --allow-repeats` reuses
footage. If planning still fails, ask for more footage or a change of duration
or repeat policy. A `--min-speed` below 1 is rejected without the slow-motion
opt-in.

## Preview

```sh
edit_project.py preview <work>/project.json -o <work>/preview.mp4
```

This renders a smaller, fast-encoded video and `<work>/preview.html` (`--html`
sets another path), an offline review page with a player, shot buttons, a
replacement-clip picker, a duration field, a remove-flashes button and a
title/caption editor; show the user either one. The page only queues
operations and downloads `revisions.json`; apply that file with `revise`.
Preview runs the same export QA as render
([review-and-automation.md](review-and-automation.md)). Check cut placement
against `beat_frames` and `sections` in the project.

## Revise

```sh
edit_project.py revise <work>/project.json --operations <work>/revisions.json
edit_project.py preview <work>/project.json -o <work>/preview-v2.mp4
```

`revise` validates the whole list and writes nothing on error. On success it
saves the previous project in `<work>/.history/` and increments `revision`; to
undo, copy back the snapshot whose `revision` field you want (file names are
content hashes). `-o` writes a new file instead of overwriting the project. Operations apply in
order, and unchanged shots are reused from the render cache.

**Addressing.** `shot` is a 1-based position in the current order or a shot ID
such as `shot-003`; prefer IDs, because positions change after `reorder`.
`effects`, `reframe` and `speed` also accept `"section": "drop"` or
`"all": true`; `replace` and `duration` need exactly one shot. Shot IDs are in
`edits[].id` and on the preview page; the `--shot` flag of `tracking-report`,
`reframe-keyframes` and `speech-broll` takes an ID, not a number.

```json
[
  {"op": "replace", "shot": "shot-003", "clip_id": "asset_0123456789ab:0002"},
  {"op": "replace", "shot": "shot-005", "clip_id": "asset_0123456789ab:0000", "source_start": 3.0, "source_end": 4.6},
  {"op": "reorder", "order": ["shot-002", "shot-001", "shot-003", "shot-004", "shot-005"]},
  {"op": "duration", "shot": "shot-001", "seconds": 2.5, "borrow_from": "shot-002"},
  {"op": "replace", "shot": "shot-001", "clip_id": "asset_0123456789ab:0004"},
  {"op": "effects", "all": true, "values": {"flash": 0}},
  {"op": "effects", "section": "drop", "values": {"grade": "none", "zoom": 1.1}}
]
```

### Operations

| Op | Fields | Effect |
|---|---|---|
| `replace` | `shot`, `clip_id`; optional `source_start`, `source_end` (source seconds inside the clip) | New picture, same output length. Without a range it takes the first unused range long enough for 1x; with only `source_start` it plays at 1x from there if the clip is long enough. Resets the shot's speed curve, action anchor and reframe (`auto` with the clip's annotated subject). |
| `reorder` | `order`: every shot ID exactly once | New shot order. |
| `duration` | `shot`, `seconds`; optional `borrow_from` (a shot) | Sets one shot's length and takes the difference from the next shot (the previous one for the last shot) or from `borrow_from`; the total stays exact. Source ranges stay, so both shots change speed. |
| `effects` | selector, `values`: `flash` and `shake` 0 to 1, `zoom` 1 to 4, `grade` `none`/`neutral`/`cinematic`/`cool`/`vivid`/`warm` | Merges into each selected shot's effects. |
| `reframe` | selector, `mode`, `subject`, `subject_start`, `keyframes`, `sample_fps`, `confidence_threshold` | [Tracking and reframing](#tracking-and-reframing) |
| `speed` | selector, `points`, optional `anchor` | [Speed ramps](#speed-ramps) |
| `slow_motion_policy` | `prompt`, `interpolation`, `min_speed` | [Requested slow motion](#requested-slow-motion) |
| `title_add`, `title_update`, `title_remove`, `subtitle_add`, `subtitle_update`, `subtitle_remove`, `subtitles_replace`, `subtitles_shift`, `text_style`, `text_clear`, `anchor_set` | see [text-and-graphics.md](text-and-graphics.md) | titles, captions and named anchors |
| `qa_policy` | `values`: `intentional_black`, `intentional_silence` | intentional black or silent ranges: [review-and-automation.md](review-and-automation.md) |

Commands write the remaining operations; use the command rather than writing
them by hand: `style` (`style`), `graphics_set` (`graphics`, which replaces
every layer), `graphics_remove` (`graphics-remove`), `action_set` (`action`)
and the `speech_*` operations (the `speech-*` commands).

### Changing the picture

- **Music project.** Each shot's `selection.alternatives` lists up to three
  other clips with `clip_id`, `score`, `reason`, `available_source`
  (`[start, end]` of unused source) and `fits_slot`; prefer `fits_slot: true`.
  Any clip ID in the project's `clips` list (the library at planning time) is
  accepted, so new footage needs `analyze` with the full input list, `annotate`
  and a new `plan`.
- **Speech project.** `replace` also swaps the speech audio and that shot's
  source-bound captions for whatever the new range contains, and the preview
  page's replacement picker queues `replace` too. To change only the picture,
  use `speech-broll` ([speech-workflow.md](speech-workflow.md)).

### Timing rules

- A change that would play any shot below 1x is rejected unless slow motion is
  enabled; choose a longer unused source range (`replace` with
  `source_start`/`source_end`) or another clip. Lengthening a 1x shot with
  `duration` always needs this: in the same list, follow the `duration` op with
  a `replace` of that shot (its own or another `clip_id`).
- Ranges of the same source may not overlap unless repeats are allowed.
- `duration` and `reorder` rebuild `sections` from the shots, keep the planned
  ones in `original_sections` and set `timing_manually_revised`. Check moved
  cuts against `beat_frames`.
- Titles and graphics with an `anchor` move with it; other text keeps its
  output time ([text-and-graphics.md](text-and-graphics.md)).

Keep the project, library, `imports/` and original media to continue in
another session.

## Tracking and reframing

Each shot's `reframe.mode` decides the crop. `auto` (default) tracks the
`subject` box from `subject_start`, which must be at or before the shot's
`source_start`; without a box it follows faces, then frame-difference motion,
then the centre. For a moving subject the user chose, use `auto` with its box.
`manual` holds a fixed crop centred on the `subject` box, `center` a fixed
central crop, and `contain` keeps the whole image with bars.

```json
[{"op": "reframe", "shot": "shot-003", "mode": "auto", "subject": [0.35, 0.25, 0.3, 0.5],
  "subject_start": 12.0, "sample_fps": 8, "confidence_threshold": 0.6}]
```

`reframe` replaces the shot's whole reframe setting. `mode` defaults to
`manual`, which needs `subject` or `keyframes`. `subject_start` (source
seconds) defaults to the shot's `source_start`; the box must match that frame.
`sample_fps` is 0.1 to 60 (default 5), `confidence_threshold` 0 to 1 (default
0.55).

Check a tracked shot, then correct its path with explicit camera centres:

```sh
edit_project.py tracking-report <work>/project.json --shot shot-003 -o <work>/tracking-shot-003.json
edit_project.py reframe-keyframes <work>/project.json --shot shot-003 --keyframes <work>/camera.json
```

The report holds the source-time camera path (`keyframes` with `time`, `cx`,
`cy`, `method`, `confidence`), `low_confidence_intervals` in source seconds and
`review_required`. Motion is not object recognition, and confidence does not
verify that the right subject is followed (`identity_verified` is always
`false`): look at frames in the low-confidence intervals and around
occlusions, scene changes and people crossing or leaving the frame.

```json
[{"time": 2.0, "cx": 0.3, "cy": 0.5}, {"time": 3.5, "cx": 0.7, "cy": 0.48}]
```

In `camera.json`, `time` is absolute source seconds, non-negative, strictly
increasing and not past the shot's `source_end`; `cx`/`cy` are normalised
centres from 0 to 1. `reframe-keyframes` is a revision (`.history/` snapshot,
`-o` for a copy) that sets `auto` mode with these keyframes in place of the
subject box. The camera interpolates the centres along the same source
timeline as speed ramps; inspect frames where the direction or the subject
changes.

## Speed ramps

Every video shot has `speed_points` and may have an `action_anchor`. In build
and drop sections the planner gives video shots the preset's ramp (faster in,
1x at the beat nearest the middle, faster out) and, when the clip has an
`action_time` and the shot contains a beat, tries to put the action on that
beat. A ramp needs extra unused source; the planner keeps it only when enough
remains ([music-editorial.md](music-editorial.md)).

```json
[{"op": "speed", "shot": "shot-003",
  "points": [{"at": 0, "speed": 2}, {"at": 0.5, "speed": 1}, {"at": 1, "speed": 2}],
  "anchor": {"source_time": 3.2, "output_fraction": 0.5}}]
```

- `points` are relative weights along normalised output time: `at` runs from
  exactly 0 to exactly 1, strictly increasing; `speed` is above 0. The curve is
  smoothly interpolated and scaled to consume exactly the shot's source range,
  so `average_speed` is (`source_end` − `source_start`) / output duration. To
  change the overall speed, change the source range (`replace` with
  `source_start`/`source_end`) or the shot length (`duration`).
- Scaling and anchoring can put part of a shot below 1x even when every weight
  is 1 or more: a 2→1→2 curve needs about 1.5 source seconds per output second
  to keep its middle at 1x.
- `anchor` places `source_time` (strictly inside the shot's source range) at
  `output_fraction` of the shot (between 0 and 1); take the fraction from the
  target beat: (beat frame − shot start frame) / shot frames. A `speed` op
  without `anchor` removes an existing anchor.
- `plan`, `revise` and `render` reject a curve outside `policies.min_speed` and
  `policies.max_speed` (1 and 3 by default); use gentler weights, move the
  anchor or change the source span. `time`/`source_time` are source seconds;
  `at` and `output_fraction` are fractions of the output shot.

## Requested slow motion

Use this only as the playback-speed rule in [SKILL.md](../SKILL.md#hard-rules)
allows. Plan at 1x as usual. If the user actually said "Slow the impact down to
half speed with frame interpolation", enable it in the saved project and slow
only that shot in the same operation list (give it a source span half its
output length):

```json
[{"op": "slow_motion_policy", "prompt": "Slow the impact down to half speed with frame interpolation", "interpolation": "optical_flow", "min_speed": 0.5},
 {"op": "replace", "shot": "shot-009", "clip_id": "<that shot's clip_id>", "source_start": 3.5, "source_end": 3.75}]
```

`plan --slow-motion-prompt "<their words>" --interpolation optical_flow`
records the same permission at planning time but still plans every shot at 1x
or faster. Only when the user asked for slow motion across the whole edit, add
`--min-speed` (for example `0.5`): then shortage handling and speed ramps may
slow any shot down to that speed.

- The project records `policies.allow_slow_motion`, the exact quote in
  `policies.slow_motion_prompt`, `policies.interpolation: "optical_flow"` and
  `policies.min_speed`, which defaults to 0.5 once enabled (`plan` accepts
  0.01 to 1; passing it to `plan` also lets the planner slow any shot, so do
  that only for a whole-edit request). A prompt without `optical_flow`, or
  slowdown without a recorded prompt, fails validation in `plan`, `revise` and
  `render`.
- The quote authorizes; it does not choose shots or speeds. Slow only the
  requested moment: give that shot a source span shorter than its output length
  (`replace` with the same `clip_id` and `source_start`/`source_end`, then
  `speed` and `anchor` if needed) and check its `average_speed`.
- Only the shot a revision names can become slower than 1x: the `duration`
  target, a `speed` operation, or a `replace` with `source_start`/`source_end`.
  A `replace` without a range, or the donor of a `duration` change, never
  slows; `revise` refuses the change instead.
- A photo (`kind: image`) has no motion to slow: a source range on it is
  refused. Offer a longer hold with `duration` instead.
- The renderer interpolates every shot whose slowest speed is below 1x with
  optical flow; an interpolation error fails the render. Interpolation needs a
  following native frame. Only a plan made with slow motion enabled leaves one
  free at the end of each video, so for a hand-set range that reaches a
  video's last frame, trim `source_end` or choose a longer source. Check moving
  edges, motion blur and occlusions in the output, where optical flow can
  produce artifacts.
- To switch it off, first revise every slowed shot back to 1x or faster, then,
  in a later `revise`, apply `{"op": "slow_motion_policy", "prompt": ""}`;
  interpolation returns to `none` and the minimum to 1. The policy is checked
  before the other operations of the same list.

## Final render

```sh
edit_project.py render <work>/project.json -o <outputs>/final.mp4
```

The output is an H.264 (yuv420p, square pixels) and AAC MP4 at the project's
size and frame rate; cached shots in `<work>/cache` are reused (`--cache` sets
another folder). Render runs export QA, writes `final.verification.json`,
`final.qa.json`, `final.audio.json` and `final.review-NN.png` to `<work>/reports/`
(the output folder receives only the MP4) and
fails when a technical check fails
([review-and-automation.md](review-and-automation.md)). Keep preview and final
paths distinct. Read the project's `diagnostics`, and report tracking or speed
aspects you did not check.

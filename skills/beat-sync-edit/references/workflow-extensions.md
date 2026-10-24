# Styles, motion, tracking, QA and machine execution

`edit` is the launcher from SKILL.md; `edit COMMAND --help` shows exact flags.
All examples are local operations.
Supply absolute source paths in JSON. Keep source media separate from output,
cache, reports and execution plans. The `contract --json` command describes the
actual parser, including all command options and required arguments.

## Styles and local graphics

`style project.json --preset clean|editorial|energetic --config overrides.json`
creates a recoverable revision. Overrides can set `font` (absolute TTF/OTF),
`font_size`, `background`, `foreground`, `accent`, `animation`, and `safe_area`.
Safe areas are normalized inset fractions, e.g.
`{"left":0.06,"right":0.12,"top":0.07,"bottom":0.18}`. Presets are editable
starting points; they do not guarantee current platform UI placement. Inspect
the actual delivery context. Explicit cue style overrides take precedence.

`font-check project.json --json` checks the selected fonts' actual Unicode
character maps, including Cyrillic. Missing glyphs fail early during render.
Use one `.ttf`/`.otf` face, not a `.ttc` collection. A character existing in a
font does not prove correct complex-script shaping; inspect rendered pixels.

`graphic-template --kind hook-card --text "An opening idea" --end-frame 90 -o layers.json`
creates editable layers. Other templates: `lower-third`, `counter`, `progress-bar`.
Apply them with `graphics project.json --layers layers.json`; remove one with
`graphics-remove project.json --id hook-card-001`.

Layer example:

```json
[
  {"id":"label","kind":"card","text":"A clear opening","start_frame":0,"end_frame":90,
   "rect":[0.08,0.12,0.78,0.23],"animation":"slide"},
  {"id":"progress","kind":"bar","start_frame":0,"end_frame":300,
   "rect":[0.07,0.79,0.78,0.025],"value_from":0,"value_to":100,"animation":"none"}
]
```

Kinds: `card`, `rectangle`, `counter`, `bar`, `image`, `video`. Rectangles are
normalized `[x,y,width,height]`; frames are integer output frames with an
exclusive end. Optional colors, opacity, `fade_frames`, `font_size`, and
`font` override the project style. Animations: `none`, `fade`, `slide`, `pop`.
Image/video layers require an absolute `source`; video also accepts
`source_start`, `speed` (at least 1), `fit: contain|cover`. A video layer must
have enough source duration. Sound from a graphics video is not mixed
implicitly; add it explicitly to `audio_mix` if wanted.

`motion-project composition.json -o project.json` builds a standalone motion
project for the normal renderer. Composition fields: `width`, `height`, `fps`,
`duration` in seconds, `background`, `style`, `graphics`, optional `titles`,
`subtitles`, `audio` or `audio_mix`, and `qa`. With no audio specified it
creates intentional silence. Render and inspect this project as usual.

## Optional editable Remotion composition

`remotion-export composition.json --work react-composition` exports actual
React source, JSON props, a Node rendering entry point and pinned package
dependencies. It supports card, rectangle, counter and bar layers. Unsupported
image/video/audio/caption inputs fail explicitly; the native compositor handles
those. This adapter does not generate missing media.

Run `npm install` in that directory once, then either
`npm run render -- /absolute/output/motion.mp4` or repeat `remotion-export`
with `--render /absolute/output/motion.mp4`. Remotion needs a browser and may
download its local rendering browser. `BEAT_SYNC_BROWSER` can point to an
existing compatible browser executable. A render reports success only after
probing actual dimensions and decoded frame count. Inspect the pixels too.
Text waits for font loading and fits the actual DOM box before capture.

You can edit `index.jsx` or `composition.json`. Export refuses to overwrite
edited/unrelated source files; use a new directory when exporting a new
generated version. Rendering source manually through npm remains available.
Add the rendered MP4 to a project's graphics as `kind: video`, or analyze it
as normal media. Licensing/deployment decisions belong to Remotion's own
[documentation](https://www.remotion.dev/docs/renderer/render-media).

## Tracking diagnostics and explicit camera paths

`tracking-report project.json --shot shot-001 -o tracking.json` saves the
source-time camera centers, methods, confidence samples, and low-confidence
intervals. Tracking confidence is a review signal. It does not verify subject
identity, particularly when people cross or leave the frame.

`reframe-keyframes project.json --shot shot-001 --keyframes camera.json` applies
manual camera centers:

```json
[{"time":2.0,"cx":0.3,"cy":0.5},{"time":3.5,"cx":0.7,"cy":0.48}]
```

Times are absolute source seconds, strictly increasing; centers are normalized.
The camera interpolates centers along the same source timeline used by speed
ramps. A revised `reframe` operation also accepts `sample_fps` and
`confidence_threshold`. Inspect resulting frames at direction/identity changes.

## Export checks and honest review

`render` and `preview` run QA on the encoded output. `verify final.mp4
--project project.json --work review` repeats checks on an existing export.
Reports include decoded frame count, duration, dimensions, fps, H.264/yuv420p,
audio duration/sample rate, a full decode, detected black/silent intervals,
and contact sheets around cuts and caption/graphic times. Preview QA uses the
actual preview dimensions. Font and tracking reports accompany rendering.

`technical_pass` describes technical checks only. `visual_review`,
`editorial_review`, and `playback_review` remain `not_reviewed` until actual
observations are supplied. Detecting black/silent ranges is not proof of an
editing error. Mark intentional ranges using a revision:

```json
[{"op":"qa_policy","values":{"intentional_black":[[0,0.4]],"intentional_silence":[[0,0.6]]}}]
```

Inspect all contact sheets and play/listen to the relevant intervals whenever
playback is available. Use `review-export final.qa.json --observations review.json`
only after that work. Observation example:

```json
{"reviewer":"named reviewer","visual":{"status":"pass","evidence":"Inspected 0.0, 1.2 and 2.0 s: both caption lines and the face fit inside the safe area."}}
```

Omit unperformed categories. Status can be `pass`, `fail`, `not_reviewed`.
The command checks that the MP4 hash still matches its QA report and requires
evidence for completed reviews. It records supplied observations; it cannot
prove a human/agent actually watched. Do not invent those observations.

## Batch reuse and input-bound execution

`batch-analyze input-directory --work analysis` produces one library reusable
by multiple plans. Content-addressed analysis skips unchanged source decoding,
while annotations are reapplied. `batch-render jobs.json --work batch` reuses
a common shot cache, records each job and runs export QA. Optional
`--continue-on-error` attempts the remaining jobs; any failed job gives a failing
overall result. Job paths resolve beside the manifest:

```json
{"jobs":[{"project":"short.json","output":"short.mp4"},{"project":"long.json","output":"long.mp4","preview":true}]}
```

`--json` emits the `beat-sync.cli.v1` success/error envelope. `--json-brief`
uses compact JSON. Diagnostics go to stderr, so stdout remains parseable.
Without these flags existing commands retain their direct JSON result format.

`render project.json -o final.mp4 --dry-run --plan render-plan.json --json`
checks CLI syntax, saved-project validity, input existence and hashes without
decoding/rendering. It cannot predict model, codec or visual success. The plan
stores a parsed command, working directory, tool-source identity and content
fingerprints, including referenced media and directory membership.

`execute-plan render-plan.json --json` rechecks those fingerprints and executes
that one command. Changed media, project JSON, tool source or Python require a
new plan. This is reproducibility protection, not a cryptographic authorization
or permission system. Save plans outside any directory being analyzed. No shell
command string from the plan is executed. A normal `--dry-run` creates no files;
adding `--plan` intentionally writes just the execution plan.

For real-material evaluation manifests and calibration see
[music-editorial.md](music-editorial.md); for source-time word/shot/beat/
action anchors see [speech-workflow.md](speech-workflow.md).

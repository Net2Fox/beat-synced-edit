# Musical structure, selection and evaluation

`edit` is the skill launcher described in SKILL.md (call it by absolute path).
Use absolute media paths and keep intermediate files under the current
project's work directory.

## Music measurements and overrides

`music TRACK -o beats.json --duration 25` now stores `music_structure`: measured
onsets/density, RMS phases, quiet intervals below -50 dBFS, abrupt stops,
energy-change events, phrase hypotheses and beat confidence. Event/phrase IDs
are stable for one analyzed map. Eight-beat phrase candidates are explicitly
hypotheses; the analyzer does not identify semantic verses or actual bar lines.

`plan --pacing-mode auto` uses `beat_cut` when repeated onsets support the grid
and `phrase_flow` when they do not. Phrase flow uses event/phrase boundaries and
longer holds. With no detected beats, no artificial beat timestamps are created.
Old beat maps remain usable at lower stated confidence; reanalyze to get measured
onset evidence. Explicit `--pacing-mode beat_cut|phrase_flow` is available, but
beat cuts without any beats still fall back to phrase flow.

Listen to the chosen range. Correct an incorrect map with:

```json
{
  "reason": "Listened to the supplied track; the strong accents occur here",
  "beats": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
  "pacing_mode": "beat_cut",
  "events": [{"id": "impact", "type": "accent", "time": 2, "confidence": 0.9}],
  "phrases": [{"id": "opening", "start": 0, "end": 2}, {"id": "reveal", "start": 2, "end": 4}]
}
```

Fields besides `reason` are optional. Times are source music seconds, bounded by
its duration. Phrase ranges cannot overlap. `music-override beats.json --overrides
corrections.json -o corrected.json` retains the prior-map hash and changes in an
audit trail. Planning also accepts `--music-overrides corrections.json`.
`--sections` continues to accept contiguous **output** sections in seconds/frames.

Default build/drop ramps consume extra unused source: a 2→1→2 shape typically
needs 1.5 source seconds per output second. The planner reserves enough material
for the remaining output and falls back to constant speed if no surplus exists.
Effective rates, including action anchors, remain >=1 unless the exact user's
slow-motion request and optical-flow interpolation are recorded.

## Evidence and preferences

`candidates library.json --query "night drift" -o candidates.json` shows ranked
clips, measurement/annotation provenance, matched and missing query terms, score
contributions and exclusions. Query search matches reviewed tags/notes/transcript
text; it is not a visual-language detector. Do not infer unseen objects from it.

Every planned shot contains `selection`: score components, reasons, source range,
the top three available alternatives and the constraint order. Duration/unused
range feasibility takes priority over score. The optional preferences JSON is:

```json
{
  "tag_weights": {"drift": 3, "blurred": -4},
  "shot_weights": {"detail": 1},
  "asset_weights": {"asset-id": 0.5},
  "events": []
}
```

Use the profile in both `candidates --preferences profile.json` and
`plan --preferences profile.json --query "night drift"`. Do not invent preferences
the user has not requested; feedback is a separate reviewed observation.

```sh
edit feedback library.json --profile profile.json --clip CLIP_ID --decision reject --reason "The subject is occluded" --reviewer editor
edit feedback library.json --profile profile.json --clip CLIP_ID --decision clear --reason "Corrected framing reviewed" --reviewer editor
edit calibrate profile.json --holdout .25 -o model-report.json
edit plan --library library.json --beats beats.json --duration 25 --preferences profile.json --editorial-model model-report.json -o project.json
```

Accept boosts the exact candidate, reject excludes it, clear reverses a prior
decision. Records include content/range identity, features, reviewer, reason,
timestamp and previous event ID. Source content hashes prevent stale decisions
applying to replaced media. Feedback never edits the original media.

Calibration needs six decisions across at least three independent source files
and both classes. Source groups are split before training; vocabulary and model
fit use train groups only. The saved model is that evaluated model, not a refit
on all data. Report confusion counts, precision, recall, accuracy, Brier score,
baseline and sample counts. An insufficient dataset produces no model. Small
personal datasets do not establish artistic quality or likely popularity.

## Missed moments and false selections

Create labels after inspecting the material:

```json
{
  "labels": [
    {"id": "good-drift", "asset_id": "asset-id", "start": 4, "end": 5, "decision": "accept"},
    {"id": "blurred", "clip_id": "clip-id", "decision": "reject"}
  ]
}
```

`evaluate-selection project.json --labels labels.json -o evaluation.json` reports
chosen positive moments, missed positives, selected negatives, correct rejections
and unreviewed shots. A time range is considered selected at >=50% overlap by
default (`--minimum-overlap`). Unknown material is never counted as a negative.

## Reusable real-media review

```sh
edit review-manifest project.json --render export.mp4 --kind real --scenario multiple-people -o review.json
edit evaluate-manifest review.json -o report.json
edit record-case-review review.json --case case-001 --observations observations.json --reviewer editor --notes "Watched the export and sources" --labels labels.json
```

Available scenarios: musical-edit, multiple-people, fast-motion, quiet-speech,
names-and-languages, variable-frame-rate and ambiguous-rhythm. Each defines
explicit review checks. `observations.json` must provide every required check as
`pass`, `fail` or `not_reviewed`. Supply observations only after actual review.
For `multiple-people`, for example:

```json
{"crop_identity": "pass", "occlusion_recovery": "not_reviewed", "chosen_actions": "pass"}
```

The manifest binds project, source and rendered-video hashes. Repeat `--render`
in project order for multiple cases. Cases without an exported video cannot
become reviewed. Changed inputs are `stale`; absent
material is `missing_materials`; absent observations remain `not_reviewed`.
Distance of cuts to supplied beats is measured separately and does not verify
the beat map by listening. Synthetic cases stay labeled synthetic.

Media analysis uses a content-addressed cache including analyzer/dependency
identity and thumbnail hashes. Cached measurements are reused across batch
analysis; semantic annotations are freshly applied, never silently cached.

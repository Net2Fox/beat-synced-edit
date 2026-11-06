# Musical structure and selection

All commands below use `python -X utf8 scripts/edit_project.py` in an installed
skill, or `python -X utf8 edit_project.py` from the repository. Use absolute media
paths and keep intermediate files under the current project's work directory.

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
python edit_project.py feedback library.json --profile profile.json --clip CLIP_ID --decision reject --reason "The subject is occluded" --reviewer editor
python edit_project.py feedback library.json --profile profile.json --clip CLIP_ID --decision clear --reason "Corrected framing reviewed" --reviewer editor
python edit_project.py plan --library library.json --beats beats.json --duration 25 --preferences profile.json -o project.json
```

Accept boosts the exact candidate, reject excludes it, clear reverses a prior
decision. Records include content/range identity, features, reviewer, reason,
timestamp and previous event ID. Source content hashes prevent stale decisions
applying to replaced media. Feedback never edits the original media.

Media analysis uses a content-addressed cache including analyzer/dependency
identity and thumbnail hashes. Cached measurements are reused across `analyze`
runs; semantic annotations are freshly applied, never silently cached.

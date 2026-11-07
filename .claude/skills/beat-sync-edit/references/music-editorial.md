# Music analysis and clip selection

Read this to judge or correct the music map (beats, events, phrases, pacing mode)
or to steer which clips the planner picks with a query, preferences or feedback.
Planning flags, presets and revisions are in [project-workflow.md](project-workflow.md).

Contents: [Measurements](#music-measurements) · [Pacing](#pacing-modes) · [Corrections](#correcting-the-map) ·
[Ramps](#ramps-and-source-use) · [Candidates and feedback](#candidates-preferences-and-feedback) · [Cache](#analysis-cache)

## Music measurements

`edit_project.py music <song> --duration 25 -o <work>/beats.json` measures the whole
track. Its `music_structure` holds onsets and their density, 1 s energy phases,
`silence` (below -50 dBFS), `events` (`energy_rise`, `energy_fall`, `hard_stop`,
`silence_start`, `silence_end`, each with `id`, `time`, `confidence`), `phrases`,
`beat_confidence` (0-1) and a suggested `pacing`. Phrases are hypotheses (event
boundaries plus, with a strong pulse, every eighth beat); nothing detects bars,
verses or choruses. IDs are stable only within one map.

## Pacing modes

`plan --pacing-mode` takes `auto` (default), `beat_cut` or `phrase_flow`.

- `auto` picks `beat_cut` when `beat_confidence` >= 0.55, else `phrase_flow`, then
  switches to `phrase_flow` if the planned excerpt has fewer than 3 onsets or beats
  or local pulse confidence below 0.55. It keeps a `pacing_mode` from an override.
- `beat_cut` cuts on beats in intro/build/drop/outro sections. An `energy_rise`
  within 0.3 s of a beat moves the drop; a later `energy_fall` or `hard_stop` moves
  the outro. Chosen explicitly, it skips the `auto` checks but still falls back to
  `phrase_flow` when the selected range has no beats.
- `phrase_flow` uses one `flow` section (so no build/drop ramps) unless you pass
  `--sections`, cuts only at phrase starts and events, and holds each shot from
  max(2 s, `min_shot`) to max(4 s, 1.5 × `max_shot`).

Both modes ignore events below confidence 0.25. `project.json` gives the mode and
reason in `music_structure.pacing`. An older map with beats but no
`music_structure` plans as `beat_cut` at confidence 0.35; rerun `music`.

## Correcting the map

You cannot hear the track. Correct the map only from what the user tells you
(where the drop, accents or phrases fall) or from measured evidence (`beats`,
`music_structure` onsets, events and energy phases), then write
`<work>/music-overrides.json`:

```json
{"reason": "User: the drop is at 2 s and the accents fall every half second",
 "beats": [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5], "pacing_mode": "beat_cut",
 "events": [{"id": "impact", "type": "energy_rise", "time": 2, "confidence": 0.9}],
 "phrases": [{"id": "opening", "start": 0, "end": 2}, {"id": "reveal", "start": 2, "end": 4}]}
```

`reason` (required) names the source of the correction (the user's words or the
measured evidence), never a listening claim; the other four keys are optional and
no others are allowed. Times are source-music seconds within the track; beats
strictly increase; each event needs `time` and `type`; phrases must not overlap;
`id` is optional but unique; `confidence` defaults to 0.5. A supplied list
replaces the measured one (copy measured entries to keep them). When you correct
`beats`, set `pacing_mode` too: `auto` still checks them against the measured onsets.

```sh
edit_project.py music-override <work>/beats.json --overrides <work>/music-overrides.json -o <work>/beats-corrected.json
```

It records the previous map's hash and the changes in `music_structure.overrides`.
Plan with `--beats <work>/beats-corrected.json`, or pass `--music-overrides
<work>/music-overrides.json` to `plan` instead.

## Ramps and source use

Build/drop ramps read source faster than real time: the `car` preset's 2→1→2
`speed_ramp` (`edit_project.py presets` lists each) needs 1.5 source seconds per
output second. The planner keeps a ramp only while the unused source still covers
the rest of the edit, else plays the shot at constant speed. If a ramp or action
anchor would leave `--min-speed`..`--max-speed`, it drops the anchor, then the
ramp (the playback-speed rule in [SKILL.md](../SKILL.md)).

## Candidates, preferences and feedback

```sh
edit_project.py candidates <work>/library/library.json --query "night drift" --preferences <work>/preferences.json -o <work>/candidates.json
```

`candidates` is a context-free ranking (quality × 2 + measured energy + preference,
query and feedback terms) that lists each clip's score components, matched and
unmatched query terms and source evidence; rejected clips are `excluded` and come
last. The planner also weighs section energy, `--tags`, shot cycle, repetition and
similarity, so each shot's `selection` block in `project.json` shows how it ranked
clips for that slot: components, `reason`, `used_source_range`, up to three
`alternatives` and `constraint_order` (permitted source, enough unused duration,
then score). `--query` matches words in reviewed tags, notes and transcript text
only; it detects nothing visually.

```json
{"tag_weights": {"drift": 3, "blurred": -4}, "shot_weights": {"detail": 1},
 "asset_weights": {"<asset-id>": 0.5}, "events": []}
```

Preference weights (-20 to 20) add to the score per matching tag (lower-case
keys), annotated `shot_type` (canonical names; aliases such as `close-up` match
`close`; an unknown or repeated shot type is an error) or `asset_id`; `events` holds the records `feedback`
appends. Set weights only for what the user asked for, and pass the same file to
`candidates --preferences` and `plan --preferences <work>/preferences.json --query "..."`.

```sh
edit_project.py feedback <work>/library/library.json --profile <work>/preferences.json --clip <clip-id> --decision reject --reason "The subject is occluded" --reviewer editor
edit_project.py feedback <work>/library/library.json --profile <work>/preferences.json --clip <clip-id> --decision clear --reason "Corrected framing reviewed" --reviewer editor
```

`accept` adds 2 to that exact candidate's score, `reject` excludes it from plans,
`clear` cancels the earlier decision. `--reviewer` defaults to `user`; a missing
profile is created. Decisions are keyed to the source's content hash and range,
so they never apply to replaced media. Feedback never edits media or a saved
project: replan, or use a `replace` revision ([project-workflow.md](project-workflow.md)).

## Analysis cache

`analyze` caches measurements and thumbnails by source content in
`<work>/library/analysis-cache/`, but never annotations: after a rerun without
`--annotations`, run `annotate` again.

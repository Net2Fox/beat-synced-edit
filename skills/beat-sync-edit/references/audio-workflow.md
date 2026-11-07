# Audio: source sound, voice, music and effects

Read this when an edit needs sound beyond the planned song or recording: the clips' own
sound, a voice-over, a music bed under speech, sound effects on words, shots or beats,
ducking, loudness targets, or a song shortened or rearranged by bars before planning.

Contents: [Commands](#commands) · [Start from the current soundtrack](#start-from-the-current-soundtrack) · [The audio_mix object](#the-audio_mix-object)
· [Source sound](#source-sound) · [Tracks and anchors](#tracks-and-anchors) · [Ducking, loudness and reports](#ducking-loudness-and-reports)
· [Arrange music by bars](#arrange-music-by-bars)

## Commands

```sh
edit_project.py audio-config <work>/project.json --config <work>/audio.json
edit_project.py audio-mix <work>/project.json -o <work>/soundtrack.wav
edit_project.py audio-report <outputs>/final.mp4 -o <work>/qa/final-audio.json
```

- `audio-config` replaces the whole `project.audio_mix` with the `--config` object. It
  validates first (track files exist, have audio and cover their range; every placement
  resolves), keeps the previous project in `.history/` and increments `revision`; `-o`
  writes another file instead.
- `audio-mix` writes exactly the soundtrack `preview` and `render` use, as lossless 48 kHz
  stereo WAV (`-o` must end in `.wav`), plus `<name>.audio.json` beside it. The mix is
  cached in `<work>/cache` (`--cache` overrides), which `render` reuses after rechecking it.
- `audio-report` measures a file with an audio stream (it fails without one): `audio`
  (duration, sample rate, channels) and `measurements` (`integrated_lufs`, `true_peak_dbtp`,
  `lra_lu`, `measurable`).
- Apart from `audio-config` saving the project in place, an output that would overwrite an
  input (media, project, config, beat map, segments) is refused.

## Start from the current soundtrack

`plan` stores the song, and `speech-plan` the recording, in `project.audio` (`path`,
`start`, `duration`). Unless `audio_mix.replace_legacy` is `true`, the mixer adds
`project.audio` as a full-length `music` track with id `legacy-music`, read from
`project.audio.start`. Because `audio-config` replaces the whole `audio_mix`, extend the
current `audio_mix` from `project.json` rather than writing a new one:

- **Speech project.** `speech-plan` writes `replace_legacy: true`, `source_audio` enabled
  with role `speech`, and ducking; loudness normalization is on. Keep `replace_legacy`
  true whenever `source_audio` or `tracks` already carry that sound; otherwise the
  recording plays a second time, from its start, under the edit. No music track is needed.
- **Music project from `plan`.** There is no `audio_mix`: the song plays at its own level,
  unnormalized, and the clips' sound is off. Keep the song by leaving `replace_legacy` out,
  or set it `true` and add the song as a `music` track with `source_start` equal to
  `project.audio.start` so the cuts stay on its beats. For the clips' sound under the song,
  enable `source_audio` with role `ambient` (no ducking). Once `audio_mix` exists, loudness
  is normalized unless `"loudness": {"enabled": false}` keeps the song's previous level.
- **Motion project.** Without `audio`/`audio_mix`, `motion-project` writes a silent mix.

## The audio_mix object

A speech short with a music bed and one hit on a word:

```json
{
  "version": 1,
  "replace_legacy": true,
  "source_audio": {"enabled": true, "role": "speech", "gain_db": 0, "pitch_mode": "preserve"},
  "tracks": [
    {"id": "bed", "role": "music", "path": "<song>", "source_start": 12, "source_end": 42,
     "start": 0, "duration": 25, "gain_db": -9, "fade_in": 0.3, "fade_out": 0.8},
    {"id": "accent", "role": "sfx", "path": "<hit.wav>",
     "anchor": {"type": "word", "id": "<word-id>"}, "duration": 0.4, "gain_db": -6}
  ],
  "ducking": {"enabled": true, "threshold_db": -35, "reduction_db": 12, "attack": 0.03, "release": 0.3},
  "loudness": {"enabled": true, "integrated": -16, "true_peak": -1.5, "lra": 11}
}
```

`version` accepts only `1`. Set `allow_silence: true` to accept a mix with nothing audible
(no tracks, `source_audio` off). Times and fades are seconds, gains dB, paths absolute.

## Source sound

`source_audio` plays each video shot's own sound (photos have none) where the shot sits
in the timeline. It is off unless `"enabled": true` (`true`/`false` alone is shorthand).
Keys: `role` (default `speech`), `gain_db` (0; -96 to 36), `fade_in`/`fade_out` (0; applied
at every shot boundary), `pitch_mode` (`preserve` default, or `resample`). Roles `speech`
and `voice` duck the music; any other role (`ambient` for engine or crowd sound) goes to
the effects stem and triggers no ducking. A shot without an audio stream adds a report warning.

- Sound follows the picture: trims, reorders, `duration` changes and speed ramps apply to
  it. Shots at 1x are copied unchanged. At other speeds `preserve` keeps pitch but may
  smear short transients and `resample` changes pitch with speed; point the user to
  retimed speech and hits when they review.
- Per-shot override: a shot in `edits[]` may carry `"audio": {"gain_db", "fade_in",
  "fade_out", "pitch_mode", "role", "muted"}`, applied while `source_audio` is enabled
  (`"muted": true` silences that shot). No `revise` operation writes it: edit the shot in
  `project.json` directly; `audio-mix` validates it.
- `speech-broll` keeps the original recording under the new picture through the shot's
  `audio_source` ([speech-workflow.md](speech-workflow.md)).

## Tracks and anchors

| Track key | Default | Notes |
|---|---|---|
| `id` | `audio-<n>` | unique; `legacy-music` is taken while `replace_legacy` is false |
| `role` | `sfx` | `music` (ducked), `voice`/`speech` (duck the music), `sfx`, `ambient` |
| `path` | required | absolute |
| `source_start`, `source_end` | `0`, end of file | range read from the file |
| `start` | `0` | output time inside the project; ignored when `anchor` is set |
| `duration` | rest of the source range or of the project, whichever is shorter | must end by the project's end; without `loop`, at most the source range |
| `gain_db`, `fade_in`, `fade_out` | `0` | gain -96 to 36; linear fades |
| `loop` | `false` | `true` repeats the source range to fill `duration` |

Sound inside a graphics-layer video is never mixed; add it as a track.

Set `anchor` instead of `start` to place a track on a word, shot, beat, music event, action
or source moment; it resolves again at every mix, so the sound follows its target through
trims, reorders and retimes. Anchor types, IDs, `edge`, `offset_frames` and `shot_id`:
[text-and-graphics.md](text-and-graphics.md#semantic-anchors). For audio tracks:

- Track `offset` (seconds, may be negative) is added after the anchor's `offset_frames`.
- A target that appears in more than one shot fails unless the track sets `occurrence`
  (zero-based match index) or `"occurrences": "all"` (one placement per match), or the
  anchor sets `shot_id`.
- A missing, trimmed-away or ambiguous target, or one outside the project, fails
  validation in `audio-config`, `revise`, `preview` and `render`. Before a revision that
  cuts a track's target, re-anchor or remove that track with `audio-config`.

## Ducking, loudness and reports

`ducking` lowers `music` while voice is present, only when the mix holds both: `enabled`
(`true`), `threshold_db` (-35, voice level that triggers it; -96 to 0), `reduction_db`
(12; 0 to 60), `attack` (0.03 s), `release` (0.3 s; both 0.001 to 10).

`loudness` normalizes the master with measured two-pass FFmpeg `loudnorm`: `enabled`
(`true` once `audio_mix` exists), `integrated` (-16 LUFS; -70 to -5), `true_peak`
(-1.5 dBTP; -9 to 0), `lra` (11 LU; 1 to 50). Silence and signals too short to measure are
left unnormalized.

The report `<name>.audio.json` (beside the `audio-mix` WAV, and in `<work>/reports/` for every preview or render):

- `encoded_measurements`: `integrated_lufs`, `true_peak_dbtp`, `lra_lu` of the decoded
  output (the AAC track for an MP4).
- `loudness_within_tolerance`: `true` within ±1 LU of the integrated target and at most
  0.5 dB above the true-peak target; `false` needs inspection, never call it compliant;
  `null` (normalization off or unmeasurable) is not a pass.
- `ducking.applied`, `normalization.method` (`two_pass_loudnorm`, `skipped_unmeasurable`,
  `disabled`), `pre_normalization_peak`, `silent`, `warnings`, `sources` (file hashes)
  and `stems` (every placement with file, range and position).
- `grouped_stems`: WAVs of the `music` (already ducked), `voice` and `effects_ambient`
  groups before master normalization, to measure with `audio-report` or give the user.

With normalization on, `preview` and `render` also fail technical QA when the MP4 misses
these tolerances ([review-and-automation.md](review-and-automation.md)).

## Arrange music by bars

`arrange-music` shortens, reorders or repeats parts of a supplied song by bars, as listed
in a segments file (`<work>/arrangement.json` below):

```sh
edit_project.py music <song> -o <work>/beats.json
edit_project.py arrange-music <song> --beats <work>/beats.json --segments <work>/arrangement.json --beats-per-bar 4 --first-downbeat 0 -o <work>/arranged.wav
edit_project.py plan --library <work>/library/library.json --beats <work>/arranged.beats.json --audio-start 0 --duration <seconds> --grade none -o <work>/project.json
```

```json
[
  {"id": "intro", "start_bar": 1, "end_bar": 3},
  {"id": "chorus", "start_bar": 9, "end_bar": 13, "crossfade": 0.03},
  {"id": "ending", "start_bar": 17, "end_bar": 18, "gap_before": 0.2}
]
```

- Bars are **one-based and end-exclusive**: `[1, 3)` is the first two bars. Bar *n*
  starts at beat index `first_downbeat + (n - 1) * beats_per_bar` of the map's `beats`.
  For an irregular phrase use zero-based `start_beat` and exclusive `end_beat` instead.
- `music` detects neither meter nor where bars begin, so `--beats-per-bar` (default 4) and
  `--first-downbeat` (zero-based beat index, default 0) are assumptions. Use what the user
  says; otherwise report the values you assumed.
- The `--beats` map must belong to the same file. Only the boundary right after the last
  detected beat may lie past the grid (it is the recording end); no tempo extrapolation.
- `crossfade` (seconds) overlaps the previous segment and shortens the total; `gap_before`
  inserts silence. Never both on one segment, no `crossfade` on the first, and a crossfade
  must be shorter than both neighbours. `id` defaults to `segment-<n>`, unique.
- Output is lossless float WAV (`-o` must end in `.wav`). The command checks the exact
  sample count and that each segment's untouched PCM matches the source with zero shift,
  and fails otherwise; silent or constant windows are `unmeasurable`.
  `verification.timing_verified` covers audio placement, not the accuracy of the beats.
- The new map (`--beats-output`, default the output name with `.beats.json`) holds a fresh
  analysis of the arranged WAV (its `file`), `arranged_beats` (the source beats at their
  new positions) and `arrangement` (segments, hashes, verification). Plan with it, which
  also selects the arranged WAV, and `--audio-start 0` to start at the first bar; never
  reuse the old song's beat times.

# Source sound, speech, music and effects

Use `audio-config PROJECT --config AUDIO.json` to configure a persistent mix.
It validates the inputs before saving and keeps the previous project in `.history`.
Use `audio-mix PROJECT -o soundtrack.wav` to listen to exactly the project mix
before video encoding. `audio-report final.mp4` measures the actual decoded export.
All processing is local. Source media is never overwritten.

The configuration JSON is the value of `project.audio_mix`:

```json
{
  "version": 1,
  "replace_legacy": true,
  "source_audio": {
    "enabled": true,
    "role": "speech",
    "gain_db": 0,
    "pitch_mode": "preserve"
  },
  "tracks": [
    {
      "id": "bed",
      "role": "music",
      "path": "C:/media/music.wav",
      "source_start": 12,
      "source_end": 42,
      "start": 0,
      "duration": 25,
      "gain_db": -9,
      "fade_in": 0.3,
      "fade_out": 0.8
    },
    {
      "id": "accent",
      "role": "sfx",
      "path": "C:/media/hit.wav",
      "anchor": {"type": "word", "id": "word-0042"},
      "duration": 0.4,
      "gain_db": -6
    }
  ],
  "ducking": {
    "enabled": true,
    "threshold_db": -35,
    "reduction_db": 12,
    "attack": 0.03,
    "release": 0.3
  },
  "loudness": {"enabled": true, "integrated": -16, "true_peak": -1.5, "lra": 11}
}
```

Times and fades are seconds; gains are decibels. Paths must be absolute.
Tracks support `music`, `voice`, `speech`, `sfx`, and `ambient` roles. Only music
is ducked, and only voice/speech triggers ducking. A sound effect does not silence
the music. Explicit `loop:true` repeats the selected source range; unavailable
source material otherwise fails validation. A track must fit inside the output.
Empty soundtrack is accepted only with `allow_silence:true`.

Legacy `project.audio` becomes a music track unless `replace_legacy:true`.
Old projects retain their original gain and no loudness normalization is enabled
implicitly. New `audio_mix` configurations normalize by default; disable it with
`loudness.enabled:false` when required. Source speech projects need no music.

## Sound follows picture and speech revisions

Source sound is trimmed, reordered and retimed using the shared `timeline_map`
mapping, including nonlinear speed curves and action anchors. Natural-speed
audio is copied without time stretching. `pitch_mode:preserve` uses a variable
step phase vocoder for other mappings; it retains pitch but may smear short
transients. `pitch_mode:resample` follows the exact mapping by interpolation and
intentionally changes pitch with speed. Listen to retimed speech and action
sounds when reviewing real material. No algorithm guarantees transparent sound.

An edit can override source settings with `audio:{gain_db,fade_in,fade_out,
pitch_mode,role,muted}`. B-roll preserves speech through the edit's `audio_source`
mapping; the background picture does not replace the original recording.

Any standalone track can use an `anchor` instead of `start`:

* `{"type":"shot","id":"shot-1","edge":"end","offset_frames":-3}`
* `{"type":"source","source_id":"asset-1","time":2.5,"domain":"speech"}`
* `{"type":"word","id":"word-0042","edge":"start"}`
* `{"type":"beat","index":4}` (zero based)
* `{"type":"event","id":"event-1"}`
* `{"type":"action","id":"landing"}`

Anchors resolve at mix time, so edits and reorders move effects with their target.
`offset` shifts the resolved audio placement in seconds. Repeated source matches
must specify `occurrence:0`, `occurrences:"all"`, or `anchor.shot_id`. Missing,
trimmed, ambiguous or out-of-bounds targets fail with a repairable error instead
of placing effects at an arbitrary time.

## Verification and reusable stems

The mixer uses stereo 48 kHz float PCM, keeps sample-exact duration and caches
by source SHA-256, settings and resolved timeline. Cached mix and grouped stems
are checked for content changes before reuse. The report records every source,
range, placement and source hash; grouped music, voice and effects/ambient WAVs
are available for inspection. Music stems already include ducking, while stem
levels precede master normalization.

Loudness uses measured two-pass FFmpeg `loudnorm`. The rendered MP4 gets an
adjacent `.audio.json` containing fresh measurements of decoded AAC, including
integrated LUFS and true peak. `loudness_within_tolerance` tests +/-1 LU and at
most 0.5 dB above the requested true-peak target after encoding. A false result
requires inspection; do not describe it as compliant. Silence and very short
signals can be unmeasurable and are reported as such, never as a numeric pass.

## Arrange supplied music by bars

```
python edit_project.py arrange-music music.wav --beats music.beats.json --segments arrangement.json -o arranged.wav --beats-per-bar 4 --first-downbeat 0
```

Example `arrangement.json`:

```json
[
  {"id":"intro","start_bar":1,"end_bar":3},
  {"id":"chorus","start_bar":9,"end_bar":13,"crossfade":0.03},
  {"id":"ending","start_bar":17,"end_bar":18,"gap_before":0.2}
]
```

Bars are **one-based and end-exclusive**: `[1,3)` means the first two bars.
`first_downbeat` is a zero-based index in the input beat array. Confirm the meter
and first downbeat by listening; the analyzer does not prove where bars begin.
For an irregular phrase use zero-based `start_beat` / exclusive `end_beat`.
The boundary immediately after the final known beat is the recording end.
All other unknown boundaries fail; no tempo extrapolation invents missing beats.

`crossfade` overlaps with the preceding segment and shortens the total duration;
`gap_before` adds silence. They cannot both apply to the same join. Overlaps use
linear complementary gains to avoid boosting identical waveforms. Output is
lossless float WAV. The command verifies exact sample count, compares untouched
PCM regions and measures correlation shift. Silent/constant correlation windows
are explicitly unmeasurable. This verifies **audio placement**, not the accuracy
of detected musical beats.

The resulting `.beats.json` contains a fresh analysis of the arranged audio,
`arranged_beats` transformed from the chosen source ranges, the arrangement,
source/output hashes and the verification report. Use the new map and arranged
WAV when planning; do not reuse the old recording's beat times.

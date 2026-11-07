# Text and graphics

Read this for titles, burned-in captions, SRT/VTT files, captions from local
speech recognition, text and project styles, graphic cards, counters, bars and
overlays, motion-graphics-only videos, and semantic anchors
that tie text, graphics or sounds to a moment of a saved `<work>/project.json`.

Contents: [Basics](#basics) · [Titles](#titles) · [Caption files](#caption-files) · [Local speech recognition](#local-speech-recognition) ·
[Text styles](#text-styles) · [Project style presets](#project-style-presets) · [Fonts](#fonts) · [Revise text](#revise-text) ·
[Graphic layers](#graphic-layers) · [Motion-only projects](#motion-only-projects) ·
[Semantic anchors](#semantic-anchors)

## Basics

- Titles (`titles[]`), captions (`subtitles[]`) and graphics (`graphics[]`,
  drawn under text) are burned into preview and final MP4. Times are output
  seconds (start inclusive, end exclusive) stored as `start_frame`/`end_frame`;
  ranges outside the project are rejected.
- Text-only revisions reuse cached shots and keep the soundtrack and exact
  duration. Unanchored titles, graphics and output-timed captions keep their
  output time when shots are reordered or retimed: shift captions
  (`subtitles_shift`) when the soundtrack alignment changes. Anchored titles
  and graphics follow their target ([Semantic anchors](#semantic-anchors)).
- `inspect` shows no cues or styles: read them from `titles[]`, `subtitles[]`,
  `title_style`, `subtitle_style`, `graphics[]` and `style` in `project.json`.
- Speech projects already have source-bound captions. `subtitles-import`,
  `subtitles-transcribe`, `subtitles_shift`, `text_clear`, `subtitle_update`
  and `subtitle_remove` replace or detach them: read
  [speech-workflow.md](speech-workflow.md#captions-in-a-speech-project) first.

## Titles

```sh
edit_project.py title <work>/project.json --text 'Новый сезон' --start 0.2 --duration 2 --position top --animation fade
edit_project.py title <work>/project.json --text 'Watch the full story' --start 20 --end 25 --position center --animation slide --color '#FFE34D'
```

- `--start` (default 0) plus `--end` or `--duration` (one required). `--id`
  sets a stable ID; otherwise `title-001`, `title-002`, ...
- Style flags ([Text styles](#text-styles)) on `title` style that one title
  (cue style), not the track; `title` has no `--preset`. Titles may overlap
  each other; captions may not. `--anchor '<json>'` ties the title to a moment.

## Caption files

```sh
edit_project.py subtitles-import <work>/project.json <captions.srt> --preset boxed
edit_project.py subtitles-export <work>/project.json -o <outputs>/captions.srt
```

- Import reads UTF-8 SRT or WebVTT (BOM, Cyrillic and multiline cues are fine)
  and replaces the whole subtitle track with cues `sub-001`, `sub-002`, ...
  Formatting tags, WebVTT NOTE/STYLE/REGION blocks and cue settings are
  dropped; `X-TIMESTAMP-MAP` is rejected.
- `--timebase project` (default): times refer to the finished video;
  `soundtrack`: to the complete source song (the project's `audio.start` is
  subtracted). `--offset 0.2` delays cues by 0.2 s; negative advances them.
- Cues are rounded to output frames and clipped to the video; a file with no cue
  left is rejected. Overlapping cues are rejected: fix their times or merge the
  texts into one multiline cue.
- Imported cues have no word times, so `karaoke` shows them as plain captions.
- Export writes SRT or WebVTT by extension (`.srt`, `.vtt`; `--format srt|vtt`
  overrides): UTF-8 plain text and cue times, no animation, colour or word
  highlighting; a cue with a blank line cannot be exported. The MP4 itself has
  burned-in captions, not a switchable subtitle stream.

## Local speech recognition

`subtitles-transcribe` recognizes speech on this computer with faster-whisper
(nothing is uploaded) and replaces the subtitle track with word-timed captions.
Install the optional speech requirements first (Setup in SKILL.md).

```sh
edit_project.py subtitles-transcribe <work>/project.json --language ru --model small --preset karaoke --max-words 6 --max-chars 36 --max-duration 2.5
```

It recognizes the first that applies (`--offset` shifts the captions):

- `--audio <recording>` from `--audio-start` (default 0), aligned to the
  output; caption text only, not added as sound ([audio-workflow.md](audio-workflow.md));
- with `audio_mix` (every speech project): the whole mixed soundtrack from 0;
- otherwise the song from `audio.start`, looped if `audio.loop` is set.
  Audio of discarded source clips is never recognized.

| Flag | Default | Notes |
|---|---|---|
| `--model` | `small` | Whisper model name or a converted model folder; `tiny` is a quick multilingual check; `.en` models are English-only |
| `--language` | detected | e.g. `ru`, `en` |
| `--device`, `--compute-type` | `cpu`, `int8` | `--device` also takes `cuda`, `auto`; for GPU use `--device cuda --compute-type float16` with CUDA libraries installed |
| `--model-dir` | `<work>/models` | download/cache folder; the model downloads on first use |
| `--local-files-only` | off | never download |
| `--max-words`, `--max-chars`, `--max-duration` | 7, 42, 3 s | cue limits; cues also break at sentence punctuation and pauses over 0.6 s; words are never split |
| `--transcript` | `<work>/transcript.json` | raw result: source, extraction start, segments timed from the extracted audio |

- `karaoke` highlights each word at its recognized time; words sharing an
  output frame highlight together; segments without word times stay plain.
- Silence returns `status: no_speech` and leaves project and captions unchanged.
- Recognition mishears names, terms and sung lyrics, especially over loud music.
  Correct the text ([Revise text](#revise-text)) before delivering; it is not a
  verified transcript. Only English CPU recognition has been checked; other
  languages and GPU runs depend on the model and local runtime.

## Text styles

```sh
edit_project.py text-style <work>/project.json --track subtitles --position bottom --font-size 76 --max-lines 2 --margin 0.12 --background '#10151ECC'
```

Precedence per setting: renderer default < track style (`text-style`, `style`,
and `--preset`/style flags on `subtitles-import` and `subtitles-transcribe`;
the later call wins) < the cue's `style` (`title` flags, cue `style` in revisions).

| Flag | Values | Default: captions / titles |
|---|---|---|
| `--font` | absolute `.ttf`/`.otf` | a system font (Arial, Segoe UI, DejaVu Sans or Liberation Sans); pick one covering the script |
| `--font-size` | pixels at full output size (previews scale it) | 0.055 / 0.065 × min(width, height): about 59 / 70 px at 1080×1920 |
| `--color`, `--stroke-color`, `--highlight-color` | `#RRGGBB` or `#RRGGBBAA` | `#FFFFFF`, `#000000`, `#FFD633` |
| `--stroke-width` | pixels 0–100 | 0.0025 × min(width, height), at least 1 |
| `--background` | hex (translucent allowed) or `none` | `#00000099` / `none` |
| `--position` | `top`, `center`, `bottom` | `bottom` (centred near 82% of height) / `top` |
| `--align` | `left`, `center`, `right` | `center` |
| `--max-width`, `--margin` | frame fractions, 0.01–1 and 0–0.4 per side | 0.82, 0.09 |
| `--max-lines` | integer | 3 / 4 |
| `--opacity` | 0–1 | 1 |
| `--animation` | `none`, `fade`, `slide` | `none` |
| `--fade-frames` | entry/exit in output frames | about 0.15 s, at most half the cue |
| `--highlight`, `--no-highlight` | per-word highlight when words have times | off |

Text presets (`--preset` of `text-style`, `subtitles-import`,
`subtitles-transcribe`) change only the settings named here, before the flags of
the same call: `clean` white text, black outline, no box, no highlight; `boxed`
white on a `#10151ECC` box, no highlight; `karaoke` white on a `#10151ECC` box,
word highlight on in `#FFE34D`.

- Text wraps and shrinks until it fits `max_lines` and the safe area; words are
  never cut. A cue that fits at no size fails the render: shorten it, raise
  `max_lines` or reduce margins and stroke.
- Each side's inset is the larger of `margin` and the project `safe_area` side;
  the text width is the smaller of `max_width` and 1 minus both side insets.
- Bigger captions: read `subtitle_style.font_size` (absent means the default)
  and set about 1.2–1.4 times it. If text does not grow, shrink-to-fit limits
  it: raise `--max-lines`, or lower `--margin` and raise `--max-width` together.
- Defaults and presets do not guarantee clearance of platform buttons: check
  the caption and graphic frames in the contact sheets and adjust `--margin`,
  `--position` or the safe area.

## Project style presets

`style` sets project-wide typography, colours and safe areas, and the defaults
of graphic layers. Its presets are a separate namespace from the text presets,
although both have a `clean` (`plan --preset` is a third:
[project-workflow.md](project-workflow.md#presets)).

```sh
edit_project.py style <work>/project.json --preset editorial --config <work>/style.json
```

| Preset | background | foreground | accent | font_size | safe_area left, right, top, bottom | animation |
|---|---|---|---|---|---|---|
| `clean` | `#10151E` | `#FFFFFF` | `#FFD633` | 58 | .06, .10, .06, .16 | `fade` |
| `editorial` | `#F3EFE5` | `#122132` | `#185CE5` | 58 | .07, .07, .06, .14 | `slide` |
| `energetic` | `#12101E` | `#FFFFFF` | `#DDFF55` | 64 | .06, .12, .07, .18 | `pop` |

`--config` is a JSON file with any of `font` (absolute `.ttf`/`.otf`),
`font_size`, `background`, `foreground`, `accent`, `animation` (`none`, `fade`,
`slide`, `pop`; graphic layers only) and `safe_area` (e.g. `{"left": 0.06,
"right": 0.12, "top": 0.07, "bottom": 0.18}`; sides 0–0.49, left + right and
top + bottom below 0.9). Without `--preset` it merges into the current project
style (`clean` if none).

- Every `style` call, even `--config` alone, also overwrites in both
  `title_style` and `subtitle_style`: `color` (foreground), `highlight_color`
  (accent), `safe_area`, `font_size` and `font` (when set), replacing earlier
  `text-style` values; at 1080×1920 default titles shrink from about 70 to
  58 px. Background, stroke and per-cue styles stay. Run `style` first, then
  `text-style`, and repeat `text-style` after any later `style`.
- `editorial` puts dark `#122132` text on the dark caption box: follow it with
  `text-style --track subtitles --color '#FFFFFF'` or `--background '#F3EFE5CC'`.

## Fonts

```sh
edit_project.py font-check <work>/project.json
```

It checks the character map of every font used by text and graphics (counters
add digits and minus): each `fonts[]` entry has `status` `pass`, `fail` or
`unavailable` and its `missing` characters; `verified` is true when all pass,
and preview and render refuse to start otherwise. Use one `.ttf`/`.otf` face,
not a `.ttc`. Coverage does not prove shaping of complex scripts (Arabic,
Indic): inspect frames.

## Revise text

The preview page's text editor does not change the project: it downloads
title/caption updates and removals as `revisions.json` for `revise --operations`.
Or write the operations:

```json
[
  {"op": "title_update", "id": "title-001", "values": {"text": "A new beginning", "style": {"animation": "slide"}}},
  {"op": "subtitle_update", "id": "sub-001", "values": {"text": "Corrected wording", "start": 0.5, "end": 2.2}},
  {"op": "subtitles_shift", "seconds": 0.2},
  {"op": "text_style", "track": "subtitles", "preset": "boxed", "values": {"font_size": 76}}
]
```

| Op | Fields |
|---|---|
| `title_add`, `subtitle_add` | `values`: `text`, `start`/`end` seconds or `start_frame`/`end_frame`; optional `id`, `style`, `words`, `anchor` (titles) |
| `title_update`, `subtitle_update` | `id`, `values` (same keys; `style` merges into the cue style; the ID cannot change) |
| `title_remove`, `subtitle_remove` | `id` |
| `subtitles_replace` | `cues`: array of cue values |
| `subtitles_shift` | `seconds` (positive delays); clips cues to the video, drops cues fully outside |
| `text_style` | `track` (`titles`/`subtitles`), optional `preset`, `values` (the flags above in snake_case, plus `safe_area`; `"background": null` for no box) |
| `text_clear` | `track` |

- A cue has `id`, `text`, `start_frame`, `end_frame`, optional `style` and
  optional `words` (`text`, `start_frame`, `end_frame` on the output timeline;
  in order, non-overlapping, inside the cue, each found in the cue text).
- New `text` without new `words` drops the word timing. A times-only change
  rescales the words; ones shorter than a frame can vanish. For exact karaoke
  after rewriting a phrase, supply corrected `words` or rerun `subtitles-transcribe`.
- One operation file is validated and saved as a whole.

## Graphic layers

```sh
edit_project.py graphic-template --kind hook-card --text 'An opening idea' --end-frame 90 -o <work>/layers.json
edit_project.py graphics <work>/project.json --layers <work>/layers.json
edit_project.py graphics-remove <work>/project.json --id hook-card-001
```

- `graphics` replaces the entire layer list: to keep existing layers, copy
  `graphics[]` from `project.json` into the layers file with the new ones.
- `graphic-template` writes a one-layer array with ID `<kind>-001`
  (`--start-frame` default 0). Kinds: `hook-card`, `lower-third` (cards),
  `counter`, `progress-bar` (bar). Same-kind templates share an ID and duplicate
  IDs are rejected: rename one when merging.

```json
[
  {"id": "label", "kind": "card", "text": "A clear opening", "start_frame": 0, "end_frame": 90, "rect": [0.08, 0.12, 0.78, 0.23], "animation": "slide"},
  {"id": "progress", "kind": "bar", "start_frame": 0, "end_frame": 300, "rect": [0.07, 0.79, 0.78, 0.025], "value_from": 0, "value_to": 100, "animation": "none"}
]
```

| Field | Meaning |
|---|---|
| `id`, `start_frame`, `end_frame` | required: unique ID, integer output frames, end exclusive |
| `kind` | `card` (default), `rectangle`, `counter`, `bar`, `image`, `video` |
| `rect` | normalized `[x, y, width, height]` inside the frame; default `[0.08, 0.12, 0.78, 0.25]` |
| `text` | `card`, `counter`; shrinks to fit `rect`, error if it cannot |
| `value_from`, `value_to` | default 0 and 100, animated across the layer; a counter shows the rounded value at `{value}` in `text` (or after it), a bar fills that percentage |
| `color`, `background`, `accent`, `font`, `font_size`, `animation` | text colour, fill, bar fill, absolute font path, pixels, `none`/`fade`/`slide`/`pop`; default to the project style (else size 58, `fade`) |
| `opacity`, `fade_frames` | default 1 and 6 |
| `source`, `fit` | `image`/`video`: required absolute path; `contain` (default) or `cover` |
| `source_start`, `speed` | `video`: start second (0), speed 1–16 (1); the source must be long enough; its sound is not mixed (add an [audio track](audio-workflow.md#tracks-and-anchors)) |
| `anchor` | optional; moves the layer to an anchor, keeping its length ([Semantic anchors](#semantic-anchors)) |

## Motion-only projects

`motion-project` builds a project without footage (cards, counters, bars)
that previews and renders like any other:

```sh
edit_project.py motion-project <work>/composition.json -o <work>/project.json
```

Composition fields: `width` (1080) and `height` (1920), both even; `fps` (30);
`duration` seconds (10, at most 3600); `background` (default the style's, else
`#10151E`); `style` (the `style --config` keys); `graphics`; optional `titles`
and `subtitles` (cues with `id`, `text`, `start_frame`, `end_frame`); `audio`
(`{"path": "<song>", "start": 0}`) or `audio_mix`
([audio-workflow.md](audio-workflow.md)); `qa`. Without audio the result is
silent with the silence marked intentional. The background image goes to
`motion-assets/` beside the project.

## Semantic anchors

An anchor ties a title, graphic layer or audio track to a moment of the edit. It
is resolved again after every revision and before every preview and render, so
it follows trims, reorders and speed ramps exactly as rendered. The speed
operation's `anchor` (`source_time`, `output_fraction`) is unrelated:
[project-workflow.md](project-workflow.md#speed-ramps).

| Anchor | Points to |
|---|---|
| `{"type": "word", "id": "<word-id>", "edge": "start"}` | a speech-project transcript word (`speech.transcripts[].segments[].words[].id`), `edge` `start` (default) or `end`; follows the voice, also under B-roll |
| `{"type": "shot", "id": "shot-001", "edge": "end"}` | a shot (`edits[].id`), `edge` `start` or `end` |
| `{"type": "beat", "index": 4}` | an index into `beat_frames` |
| `{"type": "event", "id": "<event-id>"}` | a measured music event (`music_structure.events[].id`) |
| `{"type": "source", "source_id": "<asset-id>", "time": 2.75, "domain": "picture"}` | a second of a source video (`source_id`: `assets[].id` or the path); `domain` `picture` (default) or `speech` (where that source's speech plays) |
| `{"type": "action", "id": "landing"}` | a source moment saved with the `action` command (`--source-id` from `assets[]`; the same `--id` again replaces it) |

- `offset_frames` shifts the result by output frames. `source`, `word` and
  `action` take `shot_id` to pick one occurrence of repeated footage; `action`
  also takes `domain`. Photo shots never match them.

```sh
edit_project.py action <work>/project.json --id landing --source-id <asset-id> --time 2.75
edit_project.py title <work>/project.json --text 'Landing' --duration 0.6 --anchor '{"type": "action", "id": "landing"}'
```

- Titles take `anchor` from `title --anchor` or `title_add`/`title_update`
  values (a revision file avoids shell quoting), graphic layers from an
  `anchor` field. The anchor sets the start; the length is
  `anchor_duration_frames` (output frames, taken from the original length):
  update that field, not `end`, to change it, or set `"anchor": null` to detach.
- A title or graphic anchor must resolve to exactly one frame. If it matches
  nothing (the moment was cut) or several (repeated footage without `shot_id`),
  the revision or render fails: re-anchor or remove that item in the same
  operation list.
- The revision `{"op": "anchor_set", "value": {"id": "drop-hit", "anchor": {"type": "beat", "index": 4}}}`
  records a named anchor in `anchors[]` with `resolved_frames` and `status`
  (`resolved`/`unresolved`), refreshed after every revision; it places nothing.
- Audio tracks take the same anchors plus a track `offset` in seconds and
  occurrence selection: [audio-workflow.md](audio-workflow.md#tracks-and-anchors).

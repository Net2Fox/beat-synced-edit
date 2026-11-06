# Speech-first edits

Read this when the original speech drives the cut: an interview, lesson,
podcast or talking-head Short. It covers transcripts, choosing phrases,
`speech-plan`, source-bound captions, corrections, supplied translations,
B-roll over continuous speech and missed words. A speech project keeps the
recording's audio at natural speed and otherwise works like any project with
`preview`, `revise`, `render` and [review-and-automation.md](review-and-automation.md).
`speech-import`, `speech-correct`, `speech-translate`, `speech-captions`,
`speech-broll` and `speech-retry` change the project in place and save the
previous version in `<work>/.history/`; `-o` writes a new file instead.

Contents: [Transcripts](#transcripts) · [Analyze and choose phrases](#analyze-and-choose-phrases) ·
[Plan](#plan) · [Captions](#captions-in-a-speech-project) · [Correct words](#correct-words) ·
[Translate and export](#translate-and-export-captions) · [B-roll](#b-roll-over-continuous-speech) ·
[Change the selection](#add-drop-or-reorder-phrases) · [Missed words](#missed-words-gaps-and-retries) ·
[Several recordings](#several-recordings) · [Sound](#sound)

## Transcripts

Prefer a transcript the user supplied, passed with `--transcript`:

- SRT or VTT: cue times are source seconds; phrases and captions follow whole
  cues, with no word times and so no word highlighting.
- Word-timed JSON: `{"segments":[{"start":0.5,"end":2.5,"text":"...","words":[{"start":0.5,"end":1.0,"text":"..."}]}]}`
  or a top-level `"words"` array, in recording seconds, ordered,
  non-overlapping and within the recording, words inside their segment; `id`
  fields are kept.
- `analysis.json`, any JSON with a `transcript` object, or a speech project.

Without one, `speech-analyze`, `speech-plan`, `speech-batch` and `speech-retry`
(without `--file`) recognize speech locally with faster-whisper (default
`--model small`, `--device cpu`, `--compute-type int8`; nothing is uploaded).
The model downloads on first use into `models/` beside the output file or
project unless `--model-dir` is given; other flags and offline use are in
[Local speech recognition](text-and-graphics.md#local-speech-recognition).
Recognition mishears names, terms and speech over music: read the text and fix
it with `speech-correct`. Install the optional requirements once:

```sh
<python> -m pip install -r <skill>/requirements-transcription.txt
```

## Analyze and choose phrases

```sh
edit_project.py speech-analyze <recording> --transcript <transcript.srt> -o <work>/analysis.json
```

The recording must be a video with sound. `analysis.json` holds `asset` (its
`id` is the `source_id`), `transcript` with stable segment and word IDs,
`candidates` and `gap_report` ([gaps](#missed-words-gaps-and-retries)). Each
candidate has `id` (`phrase-<hash>`), `start`/`end` (source seconds), `text`,
`word_ids`, `segment_ids`, `complete_thought`, `reason` and `over_duration`.
Candidates end at sentence punctuation or before a pause of 0.8 s or more;
`complete_thought: true` only means the text ends with sentence punctuation,
and a thought over 45 s is flagged `over_duration`, never cut. Choose the
phrases for the piece, in playback order.

## Plan

Pass `analysis.json` as the transcript so recognition does not run again and
the IDs match:

```sh
edit_project.py speech-plan <recording> --transcript <work>/analysis.json --select <phrase-id> <phrase-id> <phrase-id> -o <work>/project.json
```

There is no duration flag: the length is the chosen phrases plus padding and
kept pauses, so reach a target (say 45 s) by adding up `end - start` of the
chosen candidates. The command prints `duration` and `shots`; if the length is
wrong, change `--select` and plan again. `-o` cannot be the recording or the
transcript.

| Flag | Default | Effect |
|---|---|---|
| `--select ID...` | every candidate | Phrases to use, in playback order; IDs must be known and unique. |
| `--pause-limit S` | 0.5 | After a phrase whose next selected phrase comes later in the source, keep at most S seconds of the source that follows it, stopping before any phrase you left out. |
| `--keep-pauses` | off | Keep the whole source span up to that next phrase, including any unselected speech in it; use it only for phrases that are consecutive in the source. Phrases played out of source order get no pause either way. |
| `--padding S` | 0.1 | Source context before and after each phrase, never reaching into a phrase you left out (unless `--keep-pauses`). Where neighbouring phrases would overlap in the source they meet halfway, so no footage repeats. |
| `--width`, `--height`, `--fps` | 1080, 1920, 30 | Output size and frame rate (not `--size`). |

Without `--select` it plans the whole recording with long pauses shortened to
`--pause-limit`: use that to tighten a full lesson or podcast, not for a Short.

```sh
edit_project.py speech-plan <recording> --transcript <work>/analysis.json -o <work>/project.json
```

Shot IDs are `speech-<candidate-id>`. The project keeps the transcripts,
`speech.candidates` and the chosen order in `speech.selected`.

## Captions in a speech project

`speech-plan` and `speech-import` already turn on source-bound captions
(original text), burned into preview and render; do not transcribe the edit
again. They follow trims, reorders, speed changes and B-roll. Original mode
groups word-timed speech into cues of at most 7 words, 42 characters and 3 s,
breaking at pauses over 0.6 s; SRT/VTT gives one cue per segment. Style them
with `text-style --track subtitles` ([Text styles](text-and-graphics.md#text-styles)),
fix words with `speech-correct` and switch the display with `speech-captions`.

These leave captions output-timed, so they stop following picture edits (as
titles without an anchor do):

- A `subtitle_update` revision detaches that cue (fixed output time);
  `subtitle_remove` hides it for good.
- `subtitles_shift` makes every caption output-timed and turns source captions off.
- `subtitles-import`, `subtitles-transcribe` (it recognizes the mixed output
  audio) and `text_clear` on `subtitles` replace or remove them and turn source
  captions off. Use import/transcribe here only when that is intended, for
  example captions for an added voiceover.

To undo, copy the earlier project back from `<work>/.history/`, or apply
`[{"op": "text_clear", "track": "subtitles"}]` with `revise`, then run
`speech-captions` on the project (cues detached earlier stay hidden).

## Correct words

```sh
edit_project.py speech-correct <work>/project.json --file <work>/corrections.json --glossary <work>/glossary.json
```

- `corrections.json` maps transcript IDs to text:
  `{"<word-id>": "Kubernetes", "<segment-id>": "The whole corrected sentence."}`.
  A word keeps its ID and timing. A segment correction drops that segment's
  word timing (kept as `superseded_words`), so its caption loses word
  highlighting; use it when a term was recognized as several words.
- `glossary.json` maps terms to replacements, e.g. `{"kubernetis": "Kubernetes"}`,
  case-insensitive and whole-term, matched inside each recognized word (or
  untimed segment): a term split across recognized words never matches, so
  correct that segment instead.
- Changes are logged before/after in the transcript's `corrections`; a changed
  segment's translations are marked stale. `--transcript-id` is needed only
  with several transcripts.

`speech-import` adds or replaces one asset's transcript (formats as for
`--transcript`), discarding that recording's earlier corrections and
translations, and turns source captions on. `--source-id` is the asset's `id`
in the project's `assets` (`speech-analyze` prints it as `source_id`):

```sh
edit_project.py speech-import <work>/project.json <transcript.json> --source-id <asset-id>
```

## Translate and export captions

`speech-translate` does not translate: the agent or the user supplies one text
per segment ID (not word ID), e.g. `{"<segment-id>": "Привет, друзья."}`.

```sh
edit_project.py speech-translate <work>/project.json <work>/translations-ru.json --language ru --mode bilingual
edit_project.py speech-captions <work>/project.json --mode translated --language ru
edit_project.py subtitles-export <work>/project.json -o <outputs>/captions.srt
```

- Every segment visible in the edit needs a translation, or the command fails
  and names the missing segment. `--mode` is `bilingual` (default; original
  line above the translation) or `translated`, and the captions switch to it.
- `speech-captions` switches the display (`--mode original|translated|bilingual`,
  `--language`); it sets the mode on every call (default `original`), and
  `--no-enabled` turns source captions off. `subtitles-export` writes the
  selected display as SRT or VTT (by extension, or `--format srt|vtt`).
- A translation takes its segment's time range, with no word times; describe
  that timing as hard rule 3 in SKILL.md requires. For long cues,
  supply shorter, genuinely timed segments with their translations, or set
  `--font-size` and `--max-lines` with `text-style --track subtitles`.
- A cue gets `translation_review_required: true` when its segment changed after
  translation or the edit shows only part of it.

## B-roll over continuous speech

```sh
edit_project.py speech-broll <work>/project.json --shot <shot-id> --media <broll.mp4> --offset 1 --duration 2
```

- Only the picture changes: the shot keeps the recording as its
  `audio_source`, so voice and captions continue; the B-roll's sound is unused.
- `--shot` is a shot ID from `edits[].id` (e.g. `speech-phrase-3f2a9c1d0b7e`),
  not a number. `--media` imports a local video or still (clip
  `<asset-id>-broll`); `--clip` reuses a clip from the project's `clips`.
- `--offset` (default 0) and `--duration` are seconds within the shot; without
  `--duration` the insert runs to the shot's end. A bounded insert splits the
  shot: the first piece keeps `<shot-id>`, later ones are `<shot-id>@<from>-<to>`
  (frames from the shot's start). It needs a constant-speed shot; over a speed
  ramp or action anchor, cover the whole shot or remove the retime first.
- `--source-start` (default 0) is where the insert starts in the B-roll video
  (inside the clip for `--clip`). The video must be long enough from there;
  otherwise shorten the insert or use a still. Reusing a video on another shot
  needs a range that does not overlap, because footage is not repeated.
- `--reframe auto|center|contain` (default `auto`). To swap a B-roll, run
  `speech-broll` again on its shot ID.

By contrast, `replace` (also queued by the preview page's replacement picker)
swaps picture and sound: on a shot that is not B-roll, the voice comes from the
replacement (or is silent) and the source captions disappear
([Changing the picture](project-workflow.md#changing-the-picture)). `reorder`,
`reframe`, `effects` and `speed` work as usual; voice and captions follow them.

## Add, drop or reorder phrases

Rebuild from the saved project with a new selection:

```sh
edit_project.py speech-plan <recording> --transcript <work>/project.json --select <phrase-id> <phrase-id> -o <work>/project-v2.json
```

- IDs are in the project's `speech.candidates`, the current order in
  `speech.selected`; IDs near corrected segments or recovered words can change.
  Without `--select` the whole transcript is replanned and the selection lost.
- `-o` cannot be the project passed to `--transcript`.
- Corrections, translations and recovered words carry over. Caption mode, text
  styles, titles, B-roll and audio settings do not: reapply them.
- To change only the order, a `reorder` revision keeps everything else.

## Missed words: gaps and retries

```sh
edit_project.py speech-gaps <work>/project.json -o <work>/gaps.json --min-gap 0.8 --threshold-db -40
edit_project.py speech-retry <work>/project.json --start 8.2 --end 11.4 --language ru
edit_project.py speech-retry <work>/project.json --start 8.2 --end 11.4 --file <work>/retry.json
```

- `speech-gaps` (defaults shown) lists intervals of at least `--min-gap`
  seconds without recognized words, with `rms_dbfs`. `review_required` means
  energy at or above `--threshold-db`: speech, music or noise. `quiet_gap` does
  not prove silence. `speech-analyze` writes the same report as `gap_report`.
- `speech-retry` takes a range inside the recording that overlaps no
  recognized word and recognizes only that range. Existing words and
  corrections stay, new words get their own IDs, and a segment spanning the
  gap is split (supply its translations again). `--file` imports human-aligned
  word-timed JSON in absolute source times inside the range instead. If
  nothing is recognized, the result says `no_speech_recognized` and the
  project is unchanged. `--source-id` is needed only with several transcripts.
- A retry changes the transcript and candidates, not the picture: rebuild
  ([above](#add-drop-or-reorder-phrases)) to use the recovered speech.

## Several recordings

```sh
edit_project.py speech-batch <work>/batch.json -o <work>/batch-analysis.json
```

```json
{"items": [{"id": "a", "source": "<recording-a>", "transcript": "<transcript-a.srt>"}, {"id": "b", "source": "<recording-b>"}]}
```

Relative paths resolve beside the manifest; IDs must be unique. Items without
a transcript share one loaded recognizer (ASR flags as for `speech-analyze`).
Each item is `analyzed` (`asset`, `transcript`, `candidates`, `gap_report`) or
`failed` with `error`; the report is always written, and the command exits with
an error if any item failed. `speech-plan` cannot read the report: save one
item's transcript as `{"transcript": {...}}` in its own file and pass that to
`--transcript`.

## Sound

The soundtrack is the recording (`audio_mix.source_audio`, role `speech`),
ducked and loudness-normalized. To add music, effects or a voiceover, extend
the current `audio_mix` with `audio-config`, which replaces all of it: keep
`source_audio` enabled and `replace_legacy: true`, or the edited voice is lost
or the recording plays again from its start underneath
([audio-workflow.md](audio-workflow.md#start-from-the-current-soundtrack)).

Word, source and action anchors for titles, graphics and sounds that follow the
speech are in [Semantic anchors](text-and-graphics.md#semantic-anchors).

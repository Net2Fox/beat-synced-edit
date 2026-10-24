# Speech, source captions and semantic anchors

Use speech mode for an interview, a lesson or a spoken short. Use music mode for
a musical montage. Both produce the same frame-exact version-2 project; speech
mode keeps the selected video's original audio, at natural speed by default.

## Analyze, review and plan

Prefer an existing SRT, VTT or word-timed JSON transcript. Local faster-whisper is
the fallback when `--transcript` is omitted. Recognition may download model
weights; it does not upload the recording. A local converted model plus
`--local-files-only` permits offline recognition. `speech-batch` reuses one loaded
recognizer for matching model/device/cache configurations.

```sh
edit speech-analyze interview.mp4 --transcript interview.srt -o analysis.json
edit speech-plan interview.mp4 --transcript analysis.json -o project.json --width 1080 --height 1920
edit render project.json -o short.mp4
```

`analysis.json` contains the source asset ID, stable segment/word IDs, candidate
IDs, their source ranges and reasons, and a gap report. Candidate punctuation and
pause rules are heuristics, not semantic understanding. Read/listen to candidates
before choosing them. `complete_thought` means sentence-ending punctuation was
observed. A long sentence is flagged rather than silently cut mid-thought.

Select and reorder reviewed candidates explicitly:

```sh
edit speech-plan interview.mp4 --transcript analysis.json --select phrase-ONE phrase-TWO -o project.json --pause-limit 0.7 --padding 0.1
```

Replace `phrase-ONE`/`phrase-TWO` with IDs in the report. `--pause-limit` retains
up to that many seconds of a chronological gap after each selected phrase.
`--keep-pauses` keeps the full gap. It does not insert missing pauses when a
different sentence order is requested. `--padding` adds source context around
cuts without reusing footage. A speech project derives its duration from selected
speech; it never speeds up or truncates words to fit an arbitrary target.

Word-timed JSON can contain `segments: [{start,end,text,words:[{start,end,text}]}]`
or a top-level `words` array. Times are seconds in the original source. Importing
SRT/VTT retains actual cue times but cannot provide genuine per-word highlights.

## Correct, translate and export

```sh
edit speech-import project.json transcript.json --source-id asset-ID
edit speech-correct project.json --file corrections.json --glossary terminology.json
edit speech-translate project.json translations.json --language ru --mode bilingual
edit subtitles-export project.json -o bilingual.srt
edit subtitles-export project.json -o bilingual.vtt
```

`corrections.json` maps stable word or segment IDs to corrected text. Word edits
retain their source timing and ID. A free segment rewrite archives its old words
and removes their stale highlighting. `terminology.json` maps terms to corrected
terms (case-insensitive whole-term matching), e.g. `{"net two fox":"Net2Fox"}`.
Multiword terminology may be corrected via a segment ID when recognizer tokens
split the phrase. The project retains an audit history of corrections.

`translations.json` maps **segment IDs** to supplied translated text. The command
does not produce translations. The editing agent/user supplies them. All visible
segments must have a translation before translated/bilingual mode is enabled.
Original word timings remain intact; translation text uses the source segment's
actual range, and word timings for a different language are never invented.
Source rewrites or trimmed translated segments are flagged for translation review.
For long translated paragraphs, supply shorter genuinely timed source segments
and their translations, or set an appropriate subtitle font size and `max-lines`.

`speech-captions --mode original|translated|bilingual [--language ru]` changes
display. `--no-enabled` removes generated captions. The original mode groups
word-timed speech into compact cues. Render burns the selected display into MP4;
SRT/VTT sidecars contain the same selected original/translated/bilingual text.

Source-aware captions follow source trim, reorder and nonlinear speed changes.
Existing output-timed imported captions are unchanged by picture revisions.
Editing a generated caption with `subtitle_update` detaches that occurrence from
its source timing; use `speech-correct` for changes that should follow the source.
`subtitles-transcribe` transcribes the actual mixed output audio when a mixer is
configured; these are output-timed captions, not source transcript metadata.

## B-roll with continuous speech

```sh
edit speech-broll project.json --shot speech-phrase-ID --media cutaway.mp4 --offset 1 --duration 2
```

The insert replaces picture only and saves the original `audio_source` mapping.
Subtitles and voice continue across the B-roll boundaries. Omit offset/duration
for a whole-shot replacement. `--clip` can select an existing project clip;
`--media` imports a new local video/still. The B-roll must be long enough, and
`--source-start` chooses its source interval. A bounded insert splits a
constant-speed speech shot; for an existing nonlinear retime use a whole-shot
insert or explicitly rebuild the retiming. No nonlinear curve is approximated.

## Gaps, targeted retries and batch work

```sh
edit speech-gaps project.json --min-gap 0.8 --threshold-db -40 -o gaps.json
edit speech-retry project.json --start 8.2 --end 11.4 --model small --language ru --model-dir work/models
edit speech-batch batch.json -o batch-analysis.json --model small --model-dir work/models
```

Gap analysis finds untranscribed intervals with measurable energy; that energy
may be speech, music or noise. Quiet intervals do not prove absence of speech.
Listen first, then retry the chosen **uncovered** source range. Retry refuses to
overwrite existing words, rebases real local word times into source time, gives
new words collision-free IDs and keeps prior corrections. `--file retry.json`
imports human-aligned replacement text for that gap, using absolute source times.
An empty recognizer result leaves the project unchanged and reports it honestly.

Retry updates transcript/candidates, not existing picture selections. To include
newly recovered speech in the montage, rebuild from the updated project:

```sh
edit speech-plan interview.mp4 --transcript project.json -o revised-plan.json
```

Batch format: `{"items":[{"id":"a","source":"a.mp4","transcript":"a.srt"},
{"id":"b","source":"b.mp4"}]}`. Paths resolve beside the manifest. Each item
reports analyzed/failed separately; absent real-media review stays `not_reviewed`.

## Semantic anchors

Anchor objects use one of:

```json
{"type":"word","id":"stable-word-id","edge":"start"}
{"type":"shot","id":"shot-001","edge":"end"}
{"type":"beat","index":4}
{"type":"event","id":"musical-event-id"}
{"type":"source","source_id":"asset-ID","time":2.75,"domain":"picture"}
{"type":"action","id":"landing"}
```

`offset_frames` applies after resolution. Source and word references may specify
`shot_id` to disambiguate repeats. Words use the speech mapping (including B-roll
voice); source anchors default to picture and accept `domain: "speech"`.
Source/output conversion uses the same raised-cosine integral/action warp as the
renderer, and its inverse, so speed ramps do not cause captions or SFX to drift.

Persist reusable action points and inspect anchor resolution:

```sh
edit action project.json --id landing --source-id asset-ID --time 2.75
edit anchor project.json --id highlight --spec '{"type":"action","id":"landing"}'
edit title project.json --text 'Landing' --duration 0.6 --anchor '{"type":"action","id":"landing"}'
```

Shell quoting differs across platforms; JSON revision/config files are the most
portable way to pass anchor objects. Titles/graphics accept `anchor`; audio
tracks accept `anchor`, plus explicit occurrence selection for repeated sources.
Saved anchor resolutions refresh after revisions. Removed source events remain
explicitly `unresolved`; a rendered title/graphic requiring an ambiguous or missing
anchor fails validation instead of silently appearing at the wrong time.

## Verification scope

`tests/test_speech_timeline.py` covers inverse nonlinear timing, trim/reorder,
stable corrections, translated sidecars, retries and anchors.
`tests/test_speech_workflow.py` drives the public CLI, generates local media,
renders real MP4, checks frame counts/pixels, and verifies original voice-band
audio rather than the B-roll's different tone. These deterministic tests do not
establish speech-recognition accuracy or the quality of real interview editing.

# Titles and subtitles

Use these commands with a saved version-2 project. The example PowerShell
variables `$editPython` and `$editScripts` come from SKILL.md. Pass absolute
paths for the project, media, fonts and outputs.

Text is a separate project layer. Titles and captions are burned into preview
and final MP4 after the picture is assembled. Text-only revisions reuse the
cached shots, preserve the soundtrack and keep the exact video duration.

## Titles

```powershell
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') title 'C:/edit/work/project.json' --text 'Новый сезон' --start 0.2 --duration 2 --position top --animation fade
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') title 'C:/edit/work/project.json' --text 'Watch the full story' --start 20 --end 25 --position center --animation slide --color '#FFE34D'
```

The project must be long enough for the requested range. Times are seconds in
the finished video; start is inclusive and end is exclusive. Titles can overlap
for intentional compositions. Check their positions visually.

## Import, style and export captions

```powershell
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') subtitles-import 'C:/edit/work/project.json' 'C:/edit/captions.srt' --preset boxed
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') text-style 'C:/edit/work/project.json' --track subtitles --position bottom --font-size 58 --max-lines 2 --margin 0.12 --background '#10151ECC'
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') subtitles-export 'C:/edit/work/project.json' -o 'C:/edit/outputs/captions.srt'
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') subtitles-export 'C:/edit/work/project.json' -o 'C:/edit/outputs/captions.vtt'
```

SRT and WebVTT are UTF-8, including BOM, Cyrillic and multiline text. Import
replaces the subtitle track in a recoverable revision. Known formatting tags
are removed; styling comes from the project. SRT/VTT sidecars carry plain text
and cue times, not the project's animations, colors or per-word highlighting.
The MP4 contains visible captions, not a switchable subtitle stream.

By default input timestamps refer to the finished video. For a caption file
timed against the complete source song, use `--timebase soundtrack`; the tool
subtracts the project's `audio.start`. Add `--offset 0.2` to delay captions by
0.2 seconds, or a negative offset to advance them. Cues are rounded to output
frames and clipped to the video. A file with no remaining cues is rejected.
Overlapping subtitle cues are rejected; resolve the overlap or combine their
text into one multiline cue. Titles are available as a separate overlay layer.

## Local speech recognition

Install the optional speech packages in the skill environment only when needed:

```powershell
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements-transcription.txt')
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') subtitles-transcribe 'C:/edit/work/project.json' --language ru --model small --preset karaoke --max-words 6 --max-chars 36 --max-duration 2.5
```

Recognition uses Faster Whisper locally, with CPU/int8 by default. Audio is
not uploaded. The selected model downloads on first use to `work/models`
(the project's directory plus `models`); `--model-dir` changes that cache.
`--model` accepts a model name or an existing converted model directory.
Use `--local-files-only` to prohibit downloading. `tiny` is a quick multilingual
check; `small` is the default. Models ending in `.en` are English-only.
GPU users can explicitly choose `--device cuda --compute-type float16` with
the required CUDA libraries already installed.

By default the tool transcribes only the soundtrack range used in the finished
video, beginning at `audio.start`. It does not transcribe discarded source-clip
audio. `--audio 'C:/edit/voice.wav' --audio-start 0` selects another aligned
recording; this supplies caption text and does not add or mix that recording
into the video. Use `--offset` for alignment with the final soundtrack.

Timed words are grouped at punctuation and the requested phrase limits. Very
long individual words remain intact. The `karaoke` preset highlights words
using their recognized times; plain SRT/VTT imports have no word alignment
and display ordinary captions even with that preset. Words shorter than an
output frame may share one highlight group. No approximate word times are
invented for imported text.

The raw result is saved as `work/transcript.json` (or `--transcript PATH`).
It records the source and extraction start; segment times are relative to the
extracted audio. Silence leaves the existing project and captions unchanged.
Recognition can mishear speech, names and sung lyrics, particularly over loud
music. Review and correct the text before delivering it; do not treat it as
a verified transcript. English CPU recognition and silence were tested with
Faster Whisper 1.2.1 and PyAV 18.1.0. PyAV 19 is excluded for an incompatible
decoder API. Other languages and GPU execution depend on the chosen model
and local runtime.

## Styles

`text-style` changes the whole `titles` or `subtitles` track. `title`, subtitle
import and transcription accept the same style flags. Individual cue styles
override the global style. Available presets: `clean`, `boxed`, `karaoke`.
Presets set colors/background/highlighting and retain other existing settings.

| Setting | Meaning |
|---|---|
| `--font` | Absolute TTF/OTF path. Defaults to an available system Unicode font. Choose a font covering the requested script. |
| `--font-size`, `--stroke-width` | Pixels at the final output size; automatically scaled in previews. |
| `--color`, `--stroke-color`, `--highlight-color` | `#RRGGBB` or `#RRGGBBAA`. |
| `--background` | Hex color or `none`; supports translucent boxes. |
| `--position` | `top`, `center`, `bottom`. |
| `--align` | `left`, `center`, `right` within the text block. |
| `--max-width`, `--margin` | Frame fractions; defaults .82 and .09. Adjust margins for the target platform's controls. |
| `--max-lines` | Wrap limit; text shrinks to fit without truncating words. Default titles 4, captions 3. |
| `--opacity` | 0–1. |
| `--animation`, `--fade-frames` | `none`, `fade`, `slide`; entry/exit length in output frames. |
| `--highlight`, `--no-highlight` | Enable/disable highlighting when word times exist. |

Defaults put titles near the top and captions at about 82% of frame height,
with white text, black outline and a translucent caption box. They are starting
points, not guarantees about every TikTok/Shorts UI overlay. Inspect the export
at representative times and shorten crowded captions when needed.

## Correct text and timing

The preview review page includes a text selector, text field and start/end
controls. It queues changes/removals and exports revision JSON. Apply that
file with `edit_project.py revise`; saving a file from the page does not modify
the project automatically. These operations also work through Codex:

```json
[
  {"op": "title_update", "id": "title-001", "values": {"text": "A new beginning", "style": {"animation": "slide"}}},
  {"op": "subtitle_update", "id": "sub-001", "values": {"text": "Corrected wording", "start": 0.5, "end": 2.2}},
  {"op": "subtitles_shift", "seconds": 0.2},
  {"op": "text_style", "track": "subtitles", "preset": "boxed", "values": {"font_size": 58}}
]
```

Inspect actual IDs in the project before revising. `title_add`/`subtitle_add`
accept `values` with text and start/end seconds or start_frame/end_frame.
`title_remove`/`subtitle_remove` take an `id`; `text_clear` takes a `track`;
`subtitles_replace` accepts a `cues` array. All changes are validated before
the project is saved, and previous versions remain in `.history`.

Cues store `id`, `text`, `start_frame`, `end_frame`, optional `style` and
optional `words` (`text`, `start_frame`, `end_frame` on the same output timeline).
Changing phrase text clears obsolete word alignment. Timing-only changes
rescale existing word ranges; subframe highlights can disappear. Provide
corrected `words` explicitly or transcribe again when exact karaoke timing is
needed after rewriting the phrase.

Titles and subtitles stay at absolute output times when shots are reordered
or retimed. Shift captions explicitly if the soundtrack alignment changes.
After edits, render and inspect the preview and then the final MP4:

```powershell
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') revise 'C:/edit/work/project.json' --operations 'C:/edit/work/text-changes.json'
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') preview 'C:/edit/work/project.json' -o 'C:/edit/work/preview.mp4'
& $editPython -X utf8 (Join-Path $editScripts 'edit_project.py') render 'C:/edit/work/project.json' -o 'C:/edit/outputs/final.mp4'
```

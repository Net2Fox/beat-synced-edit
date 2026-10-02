# Beat-Sync Edit for Codex

**English** · [Русский](README.ru.md) · [Full capabilities](docs/capabilities.md)

Create music-synced edits from your videos and photos by describing the result
to Codex. This **Net2Fox fork** adds a persistent editing project, exact output
duration, subject tracking, titles, subtitles and controlled slow motion to
[ZiadAbdelkarim's original project](https://github.com/ZiadAbdelkarim/beat-synced-edit).

Use it for TikTok, YouTube Shorts, Reels, travel montages, car edits, gaming
highlights and product videos. It edits existing media; it does not generate
new footage. The Python tools can also run directly without Codex.

## What you can make

| Capability | What it does |
|---|---|
| Music-synced montage | Cuts to detected beats, varies pacing across intro/build/drop/outro and accepts a chosen soundtrack start. |
| Mixed media | Combines videos and still images from files, folders or ZIP archives. |
| Content-aware selection | Uses visual observations supplied by Codex or the editor: subject tags, shot sizes, action moments and quality. |
| Framing | Vertical, square or horizontal output; subject tracking, fixed crops and letterboxing. |
| Looks and accents | Four editable presets, color grades, punch-ins, flashes, shake and photo motion. |
| Speed control | At least 1× playback by default. Explicitly requested slow motion uses optical-flow interpolation. |
| Text | Animated titles, styled captions, SRT/VTT import/export and optional local speech recognition with word highlighting. |
| Revisions | Save a project, preview it, replace or reorder shots, revise text and reuse unchanged shot caches. |
| Export | H.264/AAC MP4 with verified frame count, dimensions and audio; separate SRT/VTT files when requested. |

See the [complete capability guide](docs/capabilities.md) for every supported
workflow, preset differences, examples and practical limits, including the
specialized tools inherited from the original project.

## Requirements

- **Codex with local file and command access** for conversational editing.
  The CLI alone does not require Codex or an OpenAI API key.
- **Python 3.12 recommended.** This fork was tested on Windows with Python 3.12.
  macOS/Linux setup commands are included; they are not a claim of a tested
  platform matrix. Other Python versions need compatible dependency versions.
- **FFmpeg and ffprobe on PATH**, including H.264 (`libx264`) and AAC encoding.
  Obtain a build for your system from the [FFmpeg download page](https://ffmpeg.org/download.html).
- Local footage, a soundtrack and space for imported media, previews and caches.
  A Unicode font is needed for titles/captions; use an explicit TTF/OTF path if
  the system font does not cover the required characters.

The base environment uses librosa, PySceneDetect, OpenCV, NumPy and Pillow.
Speech recognition is optional and uses Faster Whisper. A GPU is not required;
speech defaults to CPU/int8 and rendering/interpolation run locally.

## Install the Codex skill

### Ask Codex to install it

Send this request to Codex:

```text
$skill-installer Install the skill from
https://github.com/Net2Fox/beat-synced-edit/tree/main/skills/beat-sync-edit
Create a .venv inside the installed skill directory, install its requirements.txt,
and check that ffmpeg and ffprobe are available. Tell me the installed path.
```

Install the **whole** `skills/beat-sync-edit` directory. Copying only `SKILL.md`
leaves out the scripts, references, dependencies and license. Codex should
discover the skill after installation; if it does not appear, restart Codex.
See [OpenAI's skill documentation](https://learn.chatgpt.com/docs/build-skills).

### Manual installation and environment setup

Clone this repository and copy `skills/beat-sync-edit` into a skill directory
recognized by your Codex installation. Current documented locations include
`~/.agents/skills/beat-sync-edit` for personal use and
`<project>/.agents/skills/beat-sync-edit` for one repository. Some bundled
installers use `$CODEX_HOME/skills` (usually `~/.codex/skills`); use the path
reported by your installer and avoid installing duplicate copies.
The [official skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
describe local discovery.

```sh
git clone https://github.com/Net2Fox/beat-synced-edit.git
```

Replace the example path below with the actual installed directory. Create
the environment once; for an existing installation reuse its `.venv`.

**Windows / PowerShell**

```powershell
$skillRoot = 'C:/path/to/installed/beat-sync-edit'
python -m venv (Join-Path $skillRoot '.venv')
$editPython = Join-Path $skillRoot '.venv/Scripts/python.exe'
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements.txt')
ffmpeg -version
ffprobe -version
& $editPython -X utf8 (Join-Path $skillRoot 'scripts/edit_project.py') --help
```

**macOS / Linux**

```sh
skillRoot='/path/to/installed/beat-sync-edit'
python3 -m venv "$skillRoot/.venv"
editPython="$skillRoot/.venv/bin/python"
"$editPython" -m pip install -r "$skillRoot/requirements.txt"
ffmpeg -version
ffprobe -version
"$editPython" -X utf8 "$skillRoot/scripts/edit_project.py" --help
```

Use `requirements.txt` for portable dependency resolution.
`requirements.lock.txt` records the tested Windows/Python 3.12 base environment;
it is not a universal lockfile and does not include the optional speech stack.

### Optional automatic subtitles

Ask Codex to install `requirements-transcription.txt` in the same environment,
or run:

```powershell
# PowerShell, using the variables above
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements-transcription.txt')
```

```sh
# macOS / Linux, using the variables above
"$editPython" -m pip install -r "$skillRoot/requirements-transcription.txt"
```

Whisper model weights download on first use. The default is multilingual
`small`; `tiny` is useful for a quick check and `.en` models are English-only.
Models are cached beside the project in `models/` unless `--model-dir` selects
another location. `--local-files-only` requires an already cached/local model.
Recognition processes audio locally; it does not upload it to a transcription
service. Codex itself follows its own model and tool data-handling settings.
Manual titles and SRT/VTT files do not need Whisper.

### Updating an existing installation

Back up the installed skill, then ask Codex to update its packaged files from
this fork while preserving `.venv` and your project/media folders. Install any
changed requirements afterward. A repository `git pull` alone does not update
a separately copied skill, and the installer may refuse an existing destination.

## Use it in Codex

Open a local working folder and give Codex the paths to your footage and music.
Specify duration, aspect ratio, desired style and any moments to include or
exclude. Keep working files in `work/` and final exports in `outputs/`, or
choose your own locations.

**A first edit**

> Use $beat-sync-edit. Create a 25-second edit from the videos in this folder
> set to this track: 9:16, 1080×1920, 30 FPS, cuts on the beat and quick zooms
> on the drop. Keep natural colors and do not repeat footage. Export MP4.

**Titles and captions**

> Use $beat-sync-edit. Add “A new beginning” for the first two seconds.
> Transcribe the Russian speech in the final soundtrack, use short captions
> with a dark background and yellow word highlighting, and export MP4 plus SRT.

**Revise an existing edit**

> Use $beat-sync-edit with this project.json. Replace the third shot with a
> close-up, remove flashes, correct the second caption and keep the total duration.

**Explicit slow motion**

> Use $beat-sync-edit. Slow the impact down to half speed with frame
> interpolation. Keep all other shots at normal speed or faster.

Slow motion is **off by default**, including presets and shortage handling.
It requires a direct request in your prompt and optical-flow interpolation.
Plain timestamp stretching, lowering playback FPS, duplicate-frame slowdown
and simple frame blending are forbidden. If interpolation fails, rendering
stops; it does not fall back to ordinary slowdown. Optical flow can still cause
artifacts around occlusions or fast motion, so inspect the result.

## How it works

1. **Index the media.** Probe files, detect scenes, measure motion/brightness,
   generate contact sheets and retain imported ZIP contents.
2. **Review the content.** Codex or the editor inspects source frames and adds
   subject tags, shot sizes and action timestamps. The image statistics alone
   do not identify objects or understand the story.
3. **Analyze the music.** Detect beats and energy changes, then estimate musical
   sections. Choose or override the audio start and section boundaries.
4. **Save a plan.** Build a contiguous timeline with source ranges, framing,
   effects and an exact output frame count in `project.json`.
5. **Preview and revise.** Render a smaller MP4 and an offline HTML review page.
   The page exports revision JSON; it does not directly save or render changes.
6. **Render and verify.** Process and cache individual shots, apply text layers,
   add the selected soundtrack and verify the final MP4 with ffprobe.

Keep `project.json`, the source media and persistent imports together. Projects
use absolute media paths: moving files requires updating those paths. Changes
retain snapshots in `.history/`; the main CLI caches shots in `cache/` beside
the project by default (usually `work/cache/`).
Text-only revisions reuse picture caches, though the final video still needs
text compositing and encoding.

## Command-line usage

Run these examples from the cloned repository root. Here `python` means an
interpreter with this repository's requirements installed: for example,
`& $editPython` in PowerShell or `"$editPython"` in a POSIX shell after setup
above. Replace input paths with your files. With only the installed skill,
replace `edit_project.py` with its absolute `scripts/edit_project.py` path.

```sh
python -X utf8 edit_project.py analyze /path/to/footage --work work/library
python -X utf8 edit_project.py music /path/to/song.wav --duration 25 -o work/beats.json
python -X utf8 edit_project.py plan --library work/library/library.json --beats work/beats.json --duration 25 --preset cinematic --grade none --size 1080x1920 --fps 30 -o work/project.json
python -X utf8 edit_project.py preview work/project.json -o work/preview.mp4
python -X utf8 edit_project.py render work/project.json -o outputs/edit.mp4
```

For content-aware selection, inspect the contact sheets and apply annotations
**before** `plan`; otherwise selection uses the available technical metadata.
The [project workflow](skills/beat-sync-edit/references/project-workflow.md)
includes annotation JSON, musical sections, speed authorization and revisions.

Text commands operate on the saved project. Choose **either** importing an
existing caption file **or** transcribing audio; each replaces the subtitle track
in a recoverable revision:

```sh
python -X utf8 edit_project.py title work/project.json --text "A new beginning" --start 0 --end 2 --animation fade
python -X utf8 edit_project.py subtitles-import work/project.json /path/to/captions.srt --preset boxed
# Alternative to import, after installing the optional speech requirements:
python -X utf8 edit_project.py subtitles-transcribe work/project.json --language ru --model small --preset karaoke
python -X utf8 edit_project.py subtitles-export work/project.json -o outputs/captions.vtt
python -X utf8 edit_project.py render work/project.json -o outputs/captioned.mp4
```

Use `edit_project.py --help` and `<command> --help` for available flags.
See the [text guide](skills/beat-sync-edit/references/text-and-subtitles.md)
for style settings, offsets, model caches and word timestamps.

## Output and limits

- Duration is rounded to one output frame: 25 seconds at 30 FPS is 750 frames.
  Insufficient footage produces an error or uses permitted alternatives; the
  planner does not introduce unrequested slow motion or repeats, or shorten
  the requested output to hide a shortage.
- The project renderer uses the selected soundtrack. It does not retain or
  mix source-clip audio; supplying a separate file for transcription does not
  add that audio to the edit.
- Captions are burned into MP4. SRT/VTT sidecars carry text and cue times, not
  animations or word highlighting; MP4 subtitles are not switchable tracks.
- Musical sections, tracking and transcripts need review. Recognition may
  mishear speech or lyrics, and low-quality source media is not automatically
  restored by a high output resolution or FPS setting.
- There is no automatic platform upload, generative video, voice synthesis or
  built-in caption translation. The review page is not a full timeline editor.

## Troubleshooting

| Problem | What to check |
|---|---|
| Skill is missing | Confirm the entire folder is installed in a discovered location; avoid duplicate copies; restart Codex if needed. |
| Import/dependency error | Use the skill's `.venv` interpreter and install the matching requirements there. |
| FFmpeg cannot run or encode | Check both executables on PATH and availability of `libx264`/AAC. |
| Not enough footage | Add unused clips/photos, shorten the requested edit or explicitly permit repeats. Slow motion needs its own direct request. |
| Captions are empty or mistimed | Check the audible soundtrack, its start, caption timebase/offset and selected language. |
| Text has missing glyphs | Supply an absolute `--font` path to a suitable Unicode TTF/OTF font. |
| Speech model unavailable offline | Download/cache the model first or pass an existing converted model path. |

## Documentation and development

- [All capabilities and limitations](docs/capabilities.md)
- [Codex skill instructions](skills/beat-sync-edit/SKILL.md)
- [Project workflow and revision format](skills/beat-sync-edit/references/project-workflow.md)
- [Titles, subtitles and speech recognition](skills/beat-sync-edit/references/text-and-subtitles.md)
- [Specialized legacy workflows](skills/beat-sync-edit/references/legacy-workflow.md)

Root Python files are the source of truth. After changing them, rebuild the
installable skill copy. Run checks with the dependency environment and FFmpeg:

```sh
python tools/build_codex_skill.py
python tools/build_codex_skill.py --check
python -X utf8 -m unittest discover -s tests -p "test_*.py"
python -X utf8 tests/smoke_test.py
python -X utf8 tests/project_smoke_test.py
python -X utf8 tests/text_smoke_test.py
```

Smoke tests create synthetic media in ignored `work/` folders. They do not need
personal footage or download speech models. The legacy smoke accepts
`--skill-dir`; project/text smokes accept `--scripts-dir` to verify an installed
copy. These are local checks, not a claim of CI coverage on every platform.

## Original project and license

This fork builds on [ZiadAbdelkarim/beat-synced-edit](https://github.com/ZiadAbdelkarim/beat-synced-edit).
The original README is preserved **unchanged** in [README.upstream.md](README.upstream.md),
from upstream commit
[`48c09c9`](https://github.com/ZiadAbdelkarim/beat-synced-edit/blob/48c09c92ee69c2d89b7e44b146bbd7b9c26fff08/README.md).
Its demonstrations describe the original project. The inherited CLI tools and
Claude Code skill remain in the repository; the Codex workflow described here
uses the fork's project editor. See [UPSTREAM.json](UPSTREAM.json) for provenance.

Released under the [MIT license](LICENSE), with the original attribution retained.

# Beat-Sync Edit for Claude Code and Codex

**English** · [Русский](README.ru.md) · [Full capabilities](docs/capabilities.md)

Create music-synced edits from your videos and photos by describing the result
to Claude Code or Codex. This **Net2Fox fork** adds a persistent editing project,
exact output duration, speech-led editing, audio mixing, local motion graphics,
subject tracking, captions and controlled slow motion to
[ZiadAbdelkarim's original project](https://github.com/ZiadAbdelkarim/beat-synced-edit).

Use it for TikTok, YouTube Shorts, Reels, travel montages, car edits, gaming
highlights and product videos. It edits existing media; it does not generate
new footage. The Python tools can also run directly without an agent.

## What you can make

| Capability | What it does |
|---|---|
| Music-synced montage | Measured beat confidence, phrase-flow fallback, editable musical events and source-budgeted acceleration ramps. |
| Speech shorts | Select complete phrases, preserve useful pauses and original speech under B-roll; correct stable words and import translations. |
| Audio | Source/voice/music/SFX tracks, fades, speech ducking, measured loudness and optional bar-based music arrangement. |
| Mixed media | Combines videos and still images from files, folders or ZIP archives. |
| Content-aware selection | Reviewed annotations, explained scores, alternatives, query/preferences and persistent accept/reject feedback. |
| Framing | Vertical, square or horizontal output; tracking diagnostics, manual camera keyframes, fixed crops and letterboxing. |
| Graphic compositions | Reusable styles/safe areas and local editable cards, counters and overlays, rendered to a reusable MP4. |
| Looks and accents | Seven editable presets (including phonk, anime and travel), eight color grades, cut transitions (flash, dip, whip, glitch, RGB, blur, zoom), punch-ins, shake, beat pulses, grain, vignette, glow, letterbox bars and photo motion. |
| Speed control | At least 1× playback by default. Explicitly requested slow motion uses optical-flow interpolation. |
| Text | Animated titles, styled captions, SRT/VTT import/export and optional local speech recognition with word highlighting. |
| Revisions | Save a project, preview it, replace or reorder shots, revise text and reuse unchanged shot caches. |
| Export and review | H.264/AAC MP4, decode/audio/black-frame QA, contact sheets and batch renders with a shared shot cache. |

See the [complete capability guide](docs/capabilities.md) for every supported
workflow, preset differences, examples and practical limits.

## Requirements

- **Claude Code or Codex with local file and command access** for conversational
  editing. The CLI alone needs neither an agent nor an API key.
- **Python 3.12 or newer.** Tested on Windows with Python 3.12 and on Linux with
  Python 3.13; macOS uses the same POSIX commands.
- **FFmpeg and ffprobe on PATH**, including H.264 (`libx264`) and AAC encoding.
  Obtain a build for your system from the [FFmpeg download page](https://ffmpeg.org/download.html).
- Local footage, a soundtrack and space for imported media, previews and caches.
  A Unicode font is needed for titles/captions; use an explicit TTF/OTF path if
  the system font does not cover the required characters.

The base environment uses librosa, PySceneDetect, OpenCV, NumPy, SciPy and
Pillow (about 0.7 GB). Speech recognition is optional and uses Faster Whisper.
A GPU is not required; speech defaults to CPU/int8 and rendering/interpolation
run locally.

## Install the skill

The skill is the whole [`skills/beat-sync-edit`](skills/beat-sync-edit) folder:
`SKILL.md`, `scripts/`, `references/`, the requirements files and the license.
Copying only `SKILL.md` leaves the skill without its tools.

### Claude Code

Copy the folder to `~/.claude/skills/beat-sync-edit` to use it in every project,
or to `<project>/.claude/skills/beat-sync-edit` for one project, then set up its
environment (below). Claude Code can do this for you:

```text
Install the skill from https://github.com/Net2Fox/beat-synced-edit
(folder skills/beat-sync-edit) into ~/.claude/skills/beat-sync-edit.
Create a .venv inside it, install its requirements.txt, and run
`scripts/edit_project.py doctor` with that interpreter to check the setup.
```

This repository also contains a synchronized copy in
`.claude/skills/beat-sync-edit`, so Claude Code sessions opened inside the
repository load the skill without installing it.

### Codex

Send this request to Codex:

```text
$skill-installer Install the skill from
https://github.com/Net2Fox/beat-synced-edit/tree/main/skills/beat-sync-edit
Create a .venv inside the installed skill directory, install its requirements.txt,
and run scripts/edit_project.py doctor with that interpreter to check the setup.
Tell me the installed path.
```

To install by hand, copy the folder to `~/.agents/skills/beat-sync-edit` (personal)
or `<project>/.agents/skills/beat-sync-edit` (one repository); some installers use
`$CODEX_HOME/skills` (usually `~/.codex/skills`). Avoid duplicate copies and
restart Codex if the skill does not appear. See
[OpenAI's skill documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

### Environment setup

Create the environment once inside the installed folder; reuse its `.venv`
afterwards. Replace the example path with the installed directory.

**Windows / PowerShell**

```powershell
$skillRoot = 'C:/path/to/installed/beat-sync-edit'
python -m venv (Join-Path $skillRoot '.venv')
$editPython = Join-Path $skillRoot '.venv/Scripts/python.exe'
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements.txt')
ffmpeg -version
ffprobe -version
& $editPython -X utf8 (Join-Path $skillRoot 'scripts/edit_project.py') doctor
```

**macOS / Linux**

```sh
skillRoot='/path/to/installed/beat-sync-edit'
python3 -m venv "$skillRoot/.venv"
editPython="$skillRoot/.venv/bin/python"
"$editPython" -m pip install -r "$skillRoot/requirements.txt"
ffmpeg -version
ffprobe -version
"$editPython" -X utf8 "$skillRoot/scripts/edit_project.py" doctor
```

`doctor` prints a JSON readiness report (Python, packages, FFmpeg encoders and
the caption font) with a fix for each problem, and exits with 0 when every
required component is ready and 4 otherwise. It works before the requirements
are installed, so run it first when something fails.

`requirements.txt` resolves current compatible versions.
`requirements.lock.txt` records the environment tested on Windows with
Python 3.12 (it does not cover the optional speech stack). To install those
versions, use it as a constraint:

```powershell
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements.txt') -c (Join-Path $skillRoot 'requirements.lock.txt')
```

```sh
"$editPython" -m pip install -r "$skillRoot/requirements.txt" -c "$skillRoot/requirements.lock.txt"
```

### Optional automatic subtitles

Ask the agent to install `requirements-transcription.txt` in the same
environment, or run it yourself with the interpreter from above:

```powershell
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements-transcription.txt')
```

```sh
"$editPython" -m pip install -r "$skillRoot/requirements-transcription.txt"
```

Whisper model weights download on first use. The default is multilingual
`small`; `tiny` is useful for a quick check and `.en` models are English-only.
Each model downloads once into a shared per-user cache
(`~/.cache/beat-sync-edit/models`; `%LOCALAPPDATA%\beat-sync-edit\models` on
Windows) and is reused by every project. Set `BEAT_SYNC_MODEL_DIR` or pass
`--model-dir` to choose another folder; if the cache is not writable, models
go to `models/` beside the project. `--local-files-only` requires an already cached/local model.
Recognition processes audio locally; it does not upload it to a transcription
service. The agent itself follows its own model and tool data-handling settings.
Manual titles and SRT/VTT files do not need Whisper.

### Updating an existing installation

Newer versions remove files that older ones shipped (for example
`references/legacy-workflow.md`, `scripts/render_edit.py` and `UPSTREAM.json`),
so copying the new folder over an old installation leaves stale files behind.
Back up the installed skill, delete everything in it except `.venv` and your
own folders, copy in the new `skills/beat-sync-edit`, then install any changed
requirements. A repository `git pull` alone does not update a separately
copied skill.

```sh
skillRoot='/path/to/installed/beat-sync-edit'
newSkill='/path/to/beat-synced-edit/skills/beat-sync-edit'
rm -rf "$skillRoot/SKILL.md" "$skillRoot/UPSTREAM.json" "$skillRoot/scripts" "$skillRoot/references"
cp -R "$newSkill/." "$skillRoot/"
"$skillRoot/.venv/bin/python" -m pip install -r "$skillRoot/requirements.txt"
```

```powershell
$skillRoot = 'C:/path/to/installed/beat-sync-edit'
$newSkill = 'C:/path/to/beat-synced-edit/skills/beat-sync-edit'
'SKILL.md','UPSTREAM.json','scripts','references' | ForEach-Object { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $skillRoot $_) }
Copy-Item -Recurse -Force (Join-Path $newSkill '*') $skillRoot
& (Join-Path $skillRoot '.venv/Scripts/python.exe') -m pip install -r (Join-Path $skillRoot 'requirements.txt')
```

## Use it

Open a local working folder and give the agent the paths to your footage and
music. Specify duration, aspect ratio, desired style and any moments to include
or exclude. Working files go to `work/` and final exports to `outputs/` unless
you choose other locations. Claude Code picks the skill up from the request (or
type `/beat-sync-edit`); in Codex start the request with `$beat-sync-edit`.

**A first edit**

> Create a 25-second edit from the videos in this folder set to this track:
> 9:16, 1080×1920, 30 FPS, cuts on the beat and quick zooms on the drop. Keep
> natural colors and do not repeat footage. Export MP4.

**A speech short**

> Turn this interview into a 45-second vertical short with the strongest
> complete answers and burned-in captions.

**Titles and captions**

> Add “A new beginning” for the first two seconds. Transcribe the Russian speech
> in the final soundtrack, use short captions with a dark background and yellow
> word highlighting, and export MP4 plus SRT.

**Revise an existing edit**

> Use this project.json. Replace the third shot with a close-up, remove flashes,
> correct the second caption and keep the total duration.

**Explicit slow motion**

> Slow the impact down to half speed with frame interpolation. Keep all other
> shots at normal speed or faster.

Slow motion is **off by default**, including presets and shortage handling.
It requires a direct request in your prompt and optical-flow interpolation.
Plain timestamp stretching, lowering playback FPS, duplicate-frame slowdown
and simple frame blending are forbidden. If interpolation fails, rendering
stops; it does not fall back to ordinary slowdown. Optical flow can still cause
artifacts around occlusions or fast motion, so inspect the result.

## How it works

1. **Index the media.** Probe files, detect scenes, measure motion/brightness,
   generate contact sheets and retain imported ZIP contents.
2. **Review the content.** The agent or editor inspects source frames and adds
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

The CLI works without an agent. As in `SKILL.md`, `edit_project.py` below means
`<python> -X utf8 <skill>/scripts/edit_project.py`, where `<skill>` is the
installed folder (or `skills/beat-sync-edit` in a clone) and `<python>` is its
`.venv` interpreter. Replace input paths with your files.

```sh
edit_project.py analyze /path/to/footage --work work/library
edit_project.py music /path/to/song.wav --duration 25 -o work/beats.json
edit_project.py plan --library work/library/library.json --beats work/beats.json --duration 25 --preset cinematic --grade none --size 1080x1920 --fps 30 -o work/project.json
edit_project.py preview work/project.json -o work/preview.mp4
edit_project.py render work/project.json -o outputs/edit.mp4
```

For content-aware selection, inspect the contact sheets and apply annotations
**before** `plan`; otherwise selection uses the available technical metadata.
Transitions, accents and looks are `revise` operations on the saved project;
`edit_project.py effects` prints the catalog and the
[effects guide](skills/beat-sync-edit/references/effects-and-looks.md) maps
requests such as "flash between clips" or "film look" to them.
The [project workflow](skills/beat-sync-edit/references/project-workflow.md)
includes annotation JSON, musical sections, speed authorization and revisions.

Text commands operate on the saved project. Choose **either** importing an
existing caption file **or** transcribing audio; each replaces the subtitle track
in a recoverable revision:

```sh
edit_project.py title work/project.json --text "A new beginning" --start 0 --end 2 --animation fade
edit_project.py subtitles-import work/project.json /path/to/captions.srt --preset boxed
# Alternative to import, after installing the optional speech requirements:
edit_project.py subtitles-transcribe work/project.json --language ru --model small --preset karaoke
edit_project.py subtitles-export work/project.json -o outputs/captions.vtt
edit_project.py render work/project.json -o outputs/captioned.mp4
```

Use `edit_project.py --help` and `edit_project.py <command> --help` for available
flags. See the [text and graphics guide](skills/beat-sync-edit/references/text-and-graphics.md)
for style settings, offsets, model caches and word timestamps.

## Output and limits

- Duration is rounded to one output frame: 25 seconds at 30 FPS is 750 frames.
  Insufficient footage produces an error or uses permitted alternatives; the
  planner does not introduce unrequested slow motion or repeats, or shorten
  the requested output to hide a shortage.
- Music projects play the selected soundtrack; source-clip audio is mixed in
  only when `audio-config` enables `source_audio` or adds tracks. Speech
  projects keep the original speech by default. An `--audio` file given to
  `subtitles-transcribe` is used only for recognition, not added to the mix.
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
| Skill is missing | Confirm the entire folder is installed in a discovered location; avoid duplicate copies; restart the agent if needed. |
| Import/dependency error | Run `edit_project.py doctor` with the skill's `.venv` interpreter; it lists what is missing and the command that installs it. |
| FFmpeg cannot run or encode | Check both executables on PATH and availability of `libx264`/AAC; `doctor` checks all of them. |
| Not enough footage | Add unused clips/photos, shorten the requested edit or explicitly permit repeats. Slow motion needs its own direct request. |
| Captions are empty or mistimed | Check the audible soundtrack, its start, caption timebase/offset and selected language. |
| Text has missing glyphs | Supply an absolute `--font` path to a suitable Unicode TTF/OTF font. |
| Speech model unavailable offline | Download/cache the model first or pass an existing converted model path. |

## Documentation and development

- [All capabilities and limitations](docs/capabilities.md)
- [Skill instructions (SKILL.md)](skills/beat-sync-edit/SKILL.md)
- [Music montage projects, revisions, tracking and speed](skills/beat-sync-edit/references/project-workflow.md)
- [Musical confidence and selection feedback](skills/beat-sync-edit/references/music-editorial.md)
- [Speech-first edits and source-bound captions](skills/beat-sync-edit/references/speech-workflow.md)
- [Titles, captions, speech recognition, styles and graphics](skills/beat-sync-edit/references/text-and-graphics.md)
- [Audio mixing and music arrangement](skills/beat-sync-edit/references/audio-workflow.md)
- [Export checks, batch rendering, CLI output and exit codes](skills/beat-sync-edit/references/review-and-automation.md)
- [Finishing tools: flash montage, over-under, custom FFmpeg looks](skills/beat-sync-edit/references/finishing-tools.md)

`skills/beat-sync-edit` is the only source of the skill: edit its `SKILL.md`,
`references/` and `scripts/` there. `.claude/skills/beat-sync-edit` is a
generated copy for Claude Code; refresh it after every change with
`tools/sync_skill.py` (the unit tests fail while it is out of date). Install
the development environment from `skills/beat-sync-edit/requirements.txt` and
run the checks with that interpreter and FFmpeg on PATH:

```sh
python tools/sync_skill.py
python -X utf8 -m unittest discover -s tests -p "test_*.py"
python -X utf8 tests/project_smoke_test.py
python -X utf8 tests/text_smoke_test.py
python -X utf8 tests/music_editorial_smoke.py
python -X utf8 tests/motion_smoke_test.py
python -X utf8 tests/finishing_tools_smoke_test.py
```

Smoke tests create synthetic media in ignored `work/` folders. They do not need
personal footage or download speech models. Each smoke test accepts
`--scripts-dir` to verify an installed copy. These are local checks, not a claim
of CI coverage on every platform. Synthetic fixtures do not establish real-world
ASR accuracy, subject identity, musical taste or editorial quality.

## Original project and license

This fork builds on [ZiadAbdelkarim/beat-synced-edit](https://github.com/ZiadAbdelkarim/beat-synced-edit).
The original README is preserved **unchanged** in [README.upstream.md](README.upstream.md),
from upstream commit
[`48c09c9`](https://github.com/ZiadAbdelkarim/beat-synced-edit/blob/48c09c92ee69c2d89b7e44b146bbd7b9c26fff08/README.md);
its demo videos remain in the upstream
[`examples/`](https://github.com/ZiadAbdelkarim/beat-synced-edit/tree/48c09c92ee69c2d89b7e44b146bbd7b9c26fff08/examples)
folder.
Its demonstrations describe the original project. This fork removed the original
JSON EDL pipeline (`clip_tag.py`, `plan_edit.py`, `render_edit.py`,
`vertical_style.py`); `flash_montage.py` and `overunder_stack.py` remain as
finishing tools, and `beat_map.py` is now the music-analysis library.
See [UPSTREAM.json](UPSTREAM.json) for provenance.

Released under the [MIT license](LICENSE), with the original attribution retained.

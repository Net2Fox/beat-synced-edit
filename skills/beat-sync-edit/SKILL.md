---
name: beat-sync-edit
description: Create and revise music-synced video edits from videos and photos for TikTok, YouTube Shorts and Reels, with titles and subtitles. Use for montage, beat-sync, эдит под музыку, монтаж в бит, титры, субтитры, captions, speech transcription, subject tracking, speed ramps and vertical export.
---

# Beat-Sync Edit

Turn the user's footage, music and creative directions into a saved editing
project, a reviewable preview and a finished MP4. Work from their actual media
and constraints; choose shots by content as well as musical energy.

## Setup and paths

Resolve `skillRoot` from this SKILL.md. Python tools are in `scripts/` and local
dependencies belong in `.venv/`. The environment is not shipped in Git.

```powershell
$skillRoot = Split-Path -Parent '<absolute path to this SKILL.md>'
$editPython = Join-Path $skillRoot '.venv/Scripts/python.exe'
$editScripts = Join-Path $skillRoot 'scripts'
# Only if the environment does not exist:
python -m venv (Join-Path $skillRoot '.venv')
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements.txt')
```

Use `-X utf8` for Python commands. On Linux/macOS create the environment with
`python3 -m venv` and use `.venv/bin/python`. FFmpeg and ffprobe must be on PATH.
`requirements.lock.txt` is the tested Windows/Python 3.12 snapshot;
`requirements.txt` is the portable dependency specification.

Keep analysis, persistent ZIP imports, project JSON, tracking/render caches and
previews in the current project's `work/`; final MP4s go to `outputs/` unless the
user chooses another location. Pass absolute paths. Do not put media in the
skill installation. Set `NUMBA_CACHE_DIR` under work if the skill is read-only.

## Choose the workflow

For new edits, use **edit_project.py**. Read
[project-workflow.md](references/project-workflow.md) for commands, semantic
annotations, preset settings, exact-duration policies, subject tracking, smooth
speed curves, preview review and targeted revisions.

1. Analyze mixed files/folders/ZIPs and the selected music.
2. View contact sheets and relevant source frames. Annotate objects, shot sizes,
   meaningful action times and subject boxes using observed evidence. Apply the
   annotations to the library before planning a content-aware edit.
3. Plan with the requested duration, format, pace and creative style. Inspect
   the musical sections and chosen source ranges. Presets are starting points;
   explicit user preferences override their effects and color settings.
4. Render a preview, inspect the framing and action/beat alignment, and apply
   targeted revisions to the saved project. Generate a final render when the
   requested result is ready; no extra approval is implied by the preview step.
5. Verify duration, frame count, dimensions and audio; inspect representative
   frames. Deliver the MP4 and summarize the actual result and anything not
   verified through playback.

For titles, captions, SRT/VTT files or automatic subtitles, read
[text-and-subtitles.md](references/text-and-subtitles.md). Add text to the saved
project, preview it and correct wording/timing before export. Use local speech
recognition only for audio that belongs in the requested edit; review its output.
The optional speech requirements and model are separate from the base install.
Text-only revisions preserve cached shots and the soundtrack.

Duration is exact to one output frame. Source footage is not repeated unless
allowed. Shortages must be resolved through available ranges, slower/longer
plans or an explicitly changed constraint. Do not silently truncate the edit.

Automatic beat/energy analysis estimates musical structure; check the drop.
Automatic tracking uses face/motion cues or a selected subject box; check that
it follows the intended object. Smooth slow motion blends source frames. These
features do not replace editorial inspection or synthesize unseen video.

## Existing projects and specialized effects

For a saved version-2 project, inspect it and use `revise`, `preview`, `render`;
preserve stable shot IDs and the recoverable history. Avoid regenerating the
entire plan for a local change such as replacing one shot or removing flashes.

For the original JSON EDL pipeline, square white-flash photo montages, custom
FFmpeg effects, or legacy command flags, read
[legacy-workflow.md](references/legacy-workflow.md). The original CLIs remain
available. Use the project workflow when exact duration and reusable revisions
are required.

For a reference video, match only the requested aspects (rhythm, color, framing,
effects). If the user's intended aspects are unclear, ask before applying a
whole look. Preserve proportions and natural color unless requested otherwise.

---
name: beat-sync-edit
description: Create and revise music edits, speech-first Shorts/Reels/TikToks and local motion graphics from supplied media. Use for beat-sync, эдиты, монтаж речи, B-roll, audio mixing, captions, tracking, speed ramps and video export in Codex or Claude Code.
---

# Beat-Sync Edit

Turn supplied footage, speech/music and creative directions into a saved editing
project, a reviewable preview and a finished MP4. This instruction is canonical
for both Codex and Claude Code. Use the same project CLI in either agent.

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
skill installation. An unset `NUMBA_CACHE_DIR` defaults to temporary storage;
set it under work when a persistent cache is useful.

## Choose the workflow

For new work, use **scripts/edit_project.py**. Select the planner from the task:

| Task | Read and use |
|---|---|
| Music montage or action edit | [project workflow](references/project-workflow.md): analyze, music, plan, preview, revise, render. |
| Interview, lesson, podcast or speech short | [speech workflow](references/speech-workflow.md): transcript-led selection, correctable words, preserved speech and B-roll. |
| Local animated titles/cards/charts or supplied Remotion composition | [workflow extensions](references/workflow-extensions.md): editable graphic layers, local motion assets and optional Remotion rendering. |
| Original sound + voice + music + SFX | [audio workflow](references/audio-workflow.md): gains, fades, ducking, measured normalization and music arrangement. |
| Improve selection, correct musical structure, evaluate edits | [music and editorial review](references/music-editorial.md): confidence, phrase flow, preferences, alternatives, feedback and held-out calibration. |
| Captions/titles in an existing edit | [text and subtitles](references/text-and-subtitles.md); use the speech reference for source-bound words/translations. |
| Tracking correction, style, export QA, dry run or batch work | [workflow extensions](references/workflow-extensions.md). |

A speech project should be planned around complete thoughts and audible original
speech. A music project should be planned around its measured pulse or phrases.
Graphic compositions use authored timing. Do not substitute one for the other.

1. Analyze the supplied media and, when relevant, selected music. For speech,
   start with transcript analysis; authored motion graphics need no soundtrack.
2. View contact sheets and relevant source frames. Annotate objects, shot sizes,
   meaningful action times and subject boxes using observed evidence. Apply the
   annotations to the library before planning a content-aware edit.
3. Plan with the requested duration, format, pace and creative style. Inspect
   explanations, alternatives, music hypotheses or transcript ranges. Presets are starting points;
   explicit user preferences override their effects and color settings.
4. Render a preview, inspect the framing and action/beat alignment, and apply
   targeted revisions to the saved project. Generate a final render when the
   requested result is ready; no extra approval is implied by the preview step.
5. Check the exported file with export QA, inspect representative frames and
   listen to speech/music transitions. Use tracking diagnostics to locate low
   confidence intervals. Deliver the MP4 and state anything not actually checked.

For titles, captions, SRT/VTT files or automatic subtitles, read
[text-and-subtitles.md](references/text-and-subtitles.md). Add text to the saved
project, preview it and correct wording/timing before export. Use local speech
recognition only for audio that belongs in the requested edit; review its output.
The optional speech requirements and model are separate from the base install.
Check for supplied transcripts before running ASR. Corrections and imported
translations preserve stable word IDs; do not present translation timing as
measured speech alignment. Text-only revisions preserve cached shots.

## Playback speed rule

Do not slow video by default. Keep the effective playback speed at least 1x
throughout every shot, including speed ramps, action anchors and revisions.
"Cinematic", "smooth", "on the beat", a preset, high-FPS footage or a shortage
of footage is not permission to slow it down.

Slow motion is allowed only when the user's prompt directly requests it, and
only with motion-compensated frame interpolation. Record the exact request in
`--slow-motion-prompt` and select `--interpolation optical_flow`; never invent
that quote or enable these settings proactively. Plain timestamp stretching,
lowering playback FPS, duplicated frames and simple frame blending are not
acceptable substitutes. If interpolation fails, stop that render and explain
the failure; do not fall back to ordinary slowdown. See
[project-workflow.md](references/project-workflow.md) for the explicit opt-in.

Duration is exact to one output frame. Source footage is not repeated unless
allowed. Resolve shortages using additional unused footage, permitted photo
holds, or an explicitly changed duration/repeat constraint. Do not silently
slow or truncate the edit to meet its duration. Existing projects receive the
same checks; an old slow-motion setting is not evidence of a user request.

Automatic beat/energy analysis estimates musical structure. A weak pulse uses
`phrase_flow`; do not fabricate a tempo grid and call it detected beat alignment.
Use manual music overrides after listening when the estimates are wrong.
Automatic tracking uses face/motion cues or a selected subject box; check that
it follows the intended object. Requested slow motion uses optical-flow frame
interpolation; inspect moving edges and occlusions for artifacts. These features
do not replace editorial inspection or create missing scenes. Use source-bound
word/action/shot/beat/event anchors for overlays and sounds that must survive
revisions. Record accepted/rejected source moments only after reviewing them;
never fabricate user feedback to improve a score.

For repeated evaluation use the real-media manifest workflow. Synthetic fixtures
verify mechanics, not real-world tracking identity, ASR accuracy or editorial
quality. A missing or unreviewed case remains unverified. Do not promise virality.

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

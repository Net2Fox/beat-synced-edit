---
name: beat-sync-edit
description: Edit the user's own footage, photos, speech and music into finished MP4s - beat-synced montages and fan edits (phonk, anime/AMV, car, gaming, travel, product), speech-first Shorts/Reels/TikToks with B-roll, captions and titles, audio mixing, subject tracking and reframing, speed ramps, transitions, flashes, glitch/RGB and color looks, previews, revisions and export QA. Use for "make an edit", "cut this to the beat", "add subtitles", эдит, монтаж под музыку/бит, нарезка, шортс/рилс, субтитры, переходы и эффекты - in Claude Code or Codex.
---

# Beat-Sync Edit

Turn supplied media and creative directions into a saved editing project, a
reviewable preview and a finished MP4. One project CLI serves Claude Code and
Codex on Windows, macOS and Linux. It edits existing media; it never generates
footage, music or voices.

## Setup (once per installation)

`skillRoot` is the folder containing this SKILL.md. Create or reuse its
environment with any Python 3.10+ (3.12 recommended):

```sh
python3 <skillRoot>/scripts/bootstrap.py            # Windows: python <skillRoot>\scripts\bootstrap.py
```

It reuses a healthy `.venv`, installs `requirements.txt` only when needed,
checks FFmpeg/ffprobe (libx264 + AAC), the default Unicode font and options,
and prints `READY` or what to fix. Add `--transcription` only when speech
recognition is needed; `--lock` installs the tested pinned versions. Never put
user media, renders or caches inside the skill folder.

## Calling the CLI

In this skill, **`edit` means the launcher by absolute path**:
`<skillRoot>/scripts/edit` on macOS/Linux, `<skillRoot>\scripts\edit.cmd` on
Windows. Agent shell calls do not keep functions or variables between calls,
so write the absolute path in every command (or set a variable inside the same
command). The launcher runs `scripts/edit_project.py` with `-X utf8` and the
skill's `.venv`.

```sh
/abs/skill/scripts/edit doctor                    # environment report
/abs/skill/scripts/edit plan --help               # exact flags of one command
/abs/skill/scripts/edit tool beat_map.py --help   # bundled legacy/helper scripts
```

`$work` and `$out` in the references stand for absolute `<project>/work` and
`<project>/outputs` folders; pass absolute paths everywhere. `edit contract
--json` describes every command; `--json` gives a parseable result envelope.
Set `NUMBA_CACHE_DIR` under `$work` when a persistent librosa cache helps.

## Choose the workflow

| Task | Read |
|---|---|
| Music montage, fan edit, action/car/gaming/travel edit | [project workflow](references/project-workflow.md): analyze, music, plan, preview, revise, render |
| Effects, transitions, grades, "make it look like …" | [effects and looks](references/effects-and-looks.md): catalog and request → operation recipes |
| Interview, lesson, podcast or speech short | [speech workflow](references/speech-workflow.md): transcript-led selection, correctable words, preserved speech, B-roll |
| Original sound + voice + music + SFX | [audio workflow](references/audio-workflow.md): gains, fades, ducking, loudness, bar-based arrangement |
| Captions, titles, SRT/VTT, automatic subtitles | [text and subtitles](references/text-and-subtitles.md) (source-bound words: speech workflow) |
| Better selection, wrong beats, evaluating edits | [music and editorial review](references/music-editorial.md) |
| Local animated cards/charts, Remotion, tracking fixes, style, QA, dry runs, batches | [workflow extensions](references/workflow-extensions.md) |
| White-flash photo montage, original EDL pipeline, custom FFmpeg filters | [legacy workflow](references/legacy-workflow.md) |

Plan speech around complete thoughts and audible original speech, music around
its measured pulse or phrases, and graphic compositions around authored timing.
Do not substitute one for another.

## Core loop

1. **Analyze** the supplied media (files, folders, ZIPs) and, for music edits,
   the chosen track. For speech start from a supplied transcript; check for one
   before running recognition.
2. **Look before planning.** Open every contact sheet (images can be read
   directly) and extra frames where needed. Annotate tags, shot types, action
   times and subject boxes from what is visible; apply them to the library.
3. **Plan** with the requested duration, format (9:16 `1080x1920`, 1:1
   `1080x1080`, 16:9 `1920x1080`), pace, preset and effects. Inspect the
   explanations, alternatives, section boundaries or transcript ranges.
4. **Preview** and inspect framing, beat/action alignment, effects at the cuts
   and captions. Translate feedback into targeted `revise` operations on the
   saved project instead of re-planning.
5. **Render** when the requested result is ready; a preview does not imply
   another approval step.
6. **Verify** with the export QA report and its contact sheets; listen to
   speech/music transitions when possible. Deliver the MP4 path, duration,
   format, shot count and effects, and state anything not actually checked.

## Translating requests

| User says (EN / RU) | Do |
|---|---|
| "15-second TikTok" / «на 15 секунд, вертикально» | `--duration 15 --size 1080x1920` |
| "faster, more cuts" / «динамичнее, больше склеек» | `--section-stride drop=1 --min-shot 0.2`, or preset `car`/`gaming`/`phonk` |
| "calmer, let shots breathe" / «спокойнее» | `--beat-stride 4 --min-shot 1.2`, or preset `cinematic`/`travel` |
| "start with the best moment" / «начни с самого яркого» | `revise` `replace` shot 1 with the strongest reviewed clip |
| flashes, glitch, whip, shake, pulse, film look, b&w / вспышки, глитч, переходы, тряска, ЧБ | [effects and looks](references/effects-and-looks.md) recipes |
| "keep the car/person in frame" / «держи объект в кадре» | `reframe` `auto` with the subject box; check the tracking report |
| "subtitles" / «субтитры», «караоке» | speech workflow, or `subtitles-transcribe` / `subtitles-import` |
| "like this reference" / «как в этом видео» | match only the named aspects; ask which ones when unclear |
| "slow motion" / «слоумо», «замедли» | only as an explicit request, through the playback-speed rule below |

Craft defaults when the user gives no direction: open on a strong, readable
shot within the first second; cut on beats or phrase starts; reserve hard
accents for the drop; one signature effect and one grade; keep text inside the
safe area; end on a clean frame. Explicit user preferences always win.

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

## Honest results

- Beat/energy analysis estimates musical structure. A weak pulse uses
  `phrase_flow`; never fabricate a tempo grid and call it detected beats.
  Correct wrong estimates with music overrides after listening.
- Tracking follows face/motion cues or a chosen subject box; check that it
  follows the intended object, especially when people cross. Optical-flow slow
  motion can smear moving edges; inspect them.
- Recognized speech can mishear names and lyrics; review it. Translations are
  supplied by the user or agent, never presented as measured alignment.
- Use source-bound word/action/shot/beat/event anchors for overlays and sounds
  that must survive revisions.
- Record accepted/rejected moments and review observations only after actually
  reviewing them; never fabricate feedback, review states or evidence.
  `technical_pass` covers technical checks only. Synthetic fixtures verify
  mechanics, not editorial quality. Do not promise virality.

## Existing projects and references

For a saved version-2 project, `inspect` it and use `revise`, `preview`,
`render`; preserve stable shot IDs and the recoverable `.history`. Avoid
re-planning for a local change such as replacing one shot, adding a transition
or removing flashes.

For a reference video, match only the requested aspects (rhythm, color,
framing, effects). If the intended aspects are unclear, ask before applying a
whole look. Preserve proportions and natural color unless asked otherwise.

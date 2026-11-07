---
name: beat-sync-edit
description: "Edits local video from supplied footage, photos, music and recordings: beat-synced music montages, speech-first Shorts/Reels/TikToks with B-roll, titles and captions (SRT/VTT, local speech recognition), voice/music/SFX mixing, vertical reframing with subject tracking, speed ramps, local motion graphics and MP4 export. Use when asked to cut, beat-sync, caption, reframe, mix or revise a video, including Russian requests (эдит, монтаж, нарезка, субтитры)."
---

# Beat-Sync Edit

Turn the user's footage, recordings and music into a saved editing project, a
preview and a finished MP4, all through one CLI, `edit_project.py`. These
instructions are the same for Claude Code and Codex.

## Setup

`<skill>` is the folder that contains this file. `<python>` is
`<skill>/.venv/bin/python` on Linux/macOS or `<skill>/.venv/Scripts/python.exe`
on Windows. If `<python>` does not exist yet, create it once:

```sh
python3 -m venv <skill>/.venv
<python> -m pip install -r <skill>/requirements.txt
ffmpeg -version
ffprobe -version
```

On Windows use `python -m venv <skill>/.venv`. FFmpeg and ffprobe must be on
PATH. Speech recognition is optional: install it only when there is speech to
transcribe and no transcript was supplied, with
`<python> -m pip install -r <skill>/requirements-transcription.txt`. Its first
run downloads model weights.

**Command notation.** In this skill, `edit_project.py CMD ARGS` means

```sh
<python> -X utf8 <skill>/scripts/edit_project.py CMD ARGS
```

and the same for `flash_montage.py` and `overunder_stack.py`. Shell variables
do not survive between tool calls, so write the full interpreter, script and
file paths (absolute) into every command. `edit_project.py --help` lists all
commands, `edit_project.py CMD --help` shows exact flags and
`edit_project.py presets` prints the preset settings; trust them over memory.

## Files

Keep everything in the user's project, never inside `<skill>`. `<work>` is a
work folder in the user's project (for example `work/`); `<outputs>` is where
finished files go (for example `outputs/`) unless the user picks another place.

| Path | Contents |
|---|---|
| `<work>/library/` | `analyze` output: `library.json`, contact sheets, imported ZIP contents |
| `<work>/annotations.json` | your visual observations about clips |
| `<work>/beats.json` | `music` output: tempo, beats, energy, beat confidence, phrase and event hypotheses |
| `<work>/project.json` | the editing project, with `.history/` snapshots and a `cache/` of rendered shots |
| `<work>/preview.mp4`, `.html` | fast review render and offline review page, with the same QA files as the final |
| `<work>/numba-cache/` | music-analysis cache; safe to delete |
| `<outputs>/final.mp4` | delivery, written with `final.qa.json`, `final.review-NN.png`, `final.verification.json` and `final.audio.json` beside it |

## Choose the workflow

| Request | Timing comes from | Start with | Read |
|---|---|---|---|
| Music montage: travel, car, gaming, product, action edit | measured beats or phrases of the song | `analyze`, `music`, `plan` | [project-workflow.md](references/project-workflow.md), [music-editorial.md](references/music-editorial.md) |
| Interview, lesson, podcast or talking-head short | complete spoken thoughts | `speech-analyze`, `speech-plan` | [speech-workflow.md](references/speech-workflow.md) |
| Titles, captions, SRT/VTT files, animated cards, counters, graphic overlays | authored times or anchors | `title`, `subtitles-*`, `graphics`, `motion-project` | [text-and-graphics.md](references/text-and-graphics.md) |
| Original sound, voice-over, music bed, sound effects, music arranged by bars | the saved timeline | `audio-config`, `arrange-music` | [audio-workflow.md](references/audio-workflow.md) |
| Change an existing project | the saved timeline | `inspect`, `revise` | [Revise an existing project](#revise-an-existing-project) |
| Check an export, record a review, render several projects | — | `verify`, `review-export`, `batch-render` | [review-and-automation.md](references/review-and-automation.md) |
| Square white-flash montage, over-under stack, custom FFmpeg look, matching a reference video | — | `flash_montage.py`, `overunder_stack.py`, `ffmpeg` | [finishing-tools.md](references/finishing-tools.md) |

Plan a music edit around its pulse or phrases and a speech edit around complete
thoughts; never substitute one for the other.

## Music montage

1. Index the media (files, folders or ZIPs):
   `edit_project.py analyze <footage...> --work <work>/library`
2. Open every contact sheet the command lists, plus extra frames where one
   thumbnail is not enough. Draw a clip's subject box on its `subject_thumb`
   (the scene's first frame, listed in `library.json`), because tracking
   starts there. Write `<work>/annotations.json` with tags, shot
   types, action times and subject boxes for the clips you actually saw (format
   in [project-workflow.md](references/project-workflow.md)), then apply it:
   `edit_project.py annotate <work>/library/library.json --annotations <work>/annotations.json`
3. Measure the music for the requested length:
   `edit_project.py music <song> --duration <seconds> -o <work>/beats.json`
4. Plan the exact duration:
   `edit_project.py plan --library <work>/library/library.json --beats <work>/beats.json --duration <seconds> --preset cinematic --grade none --size 1080x1920 --fps 30 -o <work>/project.json`.
   Presets are `cinematic` (default), `car`, `gaming` and `product`. Every
   preset also colour-grades every shot and adds zoom and flash accents.
   `--grade none` removes only the colour grade; keep it unless the user asked
   for a look, and remove flashes with an `effects` revision if asked. Map pacing and look requests
   to flags with the table in [project-workflow.md](references/project-workflow.md).
5. Preview: `edit_project.py preview <work>/project.json -o <work>/preview.mp4`.
   Look at framing, subject visibility, cut placement against the beats and
   very short shots (`duration_frames` in `edits[]`).
   If the user already asked for the final file, keep going; the preview needs
   no separate approval.
6. Fix what is wrong with targeted revisions (next section), preview again.
7. Render: `edit_project.py render <work>/project.json -o <outputs>/final.mp4`,
   then follow [Review and deliver](#review-and-deliver).

## Speech short

1. If the user supplied an SRT, VTT or word-timed JSON transcript, pass it with
   `--transcript`. Otherwise install the speech requirements (Setup).
2. `edit_project.py speech-analyze <recording> --transcript <transcript> -o <work>/analysis.json`
   (without `--transcript` it runs local speech recognition).
3. Read the candidates in `analysis.json` (IDs, text, source ranges, reasons)
   and choose and order the IDs that make a complete story at the requested length.
4. `edit_project.py speech-plan <recording> --transcript <work>/analysis.json --select <id> <id> ... --width 1080 --height 1920 -o <work>/project.json`.
   Without `--select` it plans the whole recording. The duration follows the
   chosen speech; check the reported `duration` and add or drop IDs.
5. The plan already burns in captions from the transcript. Style them with
   `text-style --track subtitles` and fix words with `speech-correct`.
   `subtitles-transcribe` and `subtitles-import` replace those captions, so use
   them in a speech project only when that is the intent.
6. Add B-roll with `speech-broll`, which keeps the voice and captions.
7. Preview and render as in the music montage.

Details: [speech-workflow.md](references/speech-workflow.md).

## Revise an existing project

- `edit_project.py inspect <work>/project.json` validates the project and
  summarises duration, preset and sections. Shot, title and caption IDs are in
  `edits[]`, `titles[]` and `subtitles[]` of `project.json`.
- Write the changes as JSON operations and apply them:
  `edit_project.py revise <work>/project.json --operations <work>/revisions.json`.
  The operations (`replace`, `reorder`, `duration`, `effects`, `reframe`,
  `speed`, text operations) are listed in
  [project-workflow.md](references/project-workflow.md).
- Music project: `replace` accepts any clip ID from the project's `clips`;
  the shot's `selection.alternatives` lists the best fits (prefer
  `fits_slot: true`). New footage needs `analyze` with the full input list,
  `annotate` and a new `plan`.
- Speech project: change the picture with `speech-broll`. `replace` swaps the
  picture and the speech together.
- Change only what was asked. Keep shot IDs and do not regenerate the whole plan
  for a local change. Every revision saves the previous project in `.history/`.
- Preview, then render again.

## Review and deliver

- `preview` and `render` run export QA themselves and fail when a technical
  check fails. Their printed result is long, so review from the report written
  beside the video, `<outputs>/final.qa.json` (`<work>/preview.qa.json` for a
  preview): open every PNG in its `contact_sheets` (cuts and caption/graphic
  midpoints), read `review_notes`, and check `black_intervals` and
  `silent_intervals`. Mark intended ones with the `qa_policy` revision
  ([review-and-automation.md](references/review-and-automation.md)), then
  `render` again (cached shots are reused) so the report reflects it.
- You cannot hear the result. Your audio evidence is the loudness and true-peak
  measurements, silent intervals, the beat map and the transcript; say that
  nobody listened unless the user did.
- Run `edit_project.py verify <file> --work <work>/qa` only on a file changed
  after `render`, for example by a finishing tool.
- Deliver the path, duration and size, what you checked, and what you did not.

## Hard rules

1. **Playback speed.** Never slow video down by default: effective speed stays
   at least 1x in every shot, ramp, anchor and revision. "Cinematic", "smooth",
   "on the beat", a preset, high-FPS footage or a shortage of footage is not
   permission. Slow motion is allowed only when the user's own words ask for
   it, and only for what they asked: plan at 1x, then `revise` with a
   `slow_motion_policy` operation holding their exact words and
   `optical_flow`, and slow only the requested shot
   ([project-workflow.md](references/project-workflow.md#requested-slow-motion));
   every other shot stays at 1x or faster. Never invent the quote or enable it
   yourself;
   an old project setting is not a request. Timestamp stretching, a lower
   playback FPS, duplicated frames and frame blending are never substitutes,
   in the CLI or in hand-written FFmpeg. If interpolation fails, stop and
   explain; never fall back to ordinary slowdown.
2. **Exact duration.** Output duration is exact to one frame and footage is not
   repeated unless allowed. Solve a shortage with unused footage, permitted
   photo holds or a duration/repeat change the user agrees to; never slow down
   or truncate silently.
3. **Report only what you observed.** Annotate from visible evidence and never
   label unseen objects or actions. When the pulse is weak, use phrase-based
   pacing instead of claiming beat alignment. Record feedback and review
   observations only after a real review. Imported translation timing is not
   measured speech alignment. Check that tracking follows the intended subject.
4. **Natural look.** Keep proportions and natural colour unless the user asks
   for a look.
5. **Reference videos.** Match only the aspects the user names (colour,
   contrast, pacing, effects); ask when it is unclear. Method in
   [finishing-tools.md](references/finishing-tools.md).
6. **No promises.** Do not promise virality or platform performance.

## References

- [project-workflow.md](references/project-workflow.md): annotations, planning
  flags and presets, revision operations, tracking and reframing, speed ramps
  and requested slow motion.
- [music-editorial.md](references/music-editorial.md): beat confidence and
  phrase pacing, music overrides, candidate ranking, preferences and feedback.
- [speech-workflow.md](references/speech-workflow.md): transcripts, candidate
  selection, speech planning, corrections and translations, B-roll, gaps.
- [text-and-graphics.md](references/text-and-graphics.md): titles, captions,
  speech recognition, text and project styles, graphics and motion cards,
  semantic anchors.
- [audio-workflow.md](references/audio-workflow.md): source sound, voice,
  music and effects tracks, ducking, loudness, arranging music by bars.
- [review-and-automation.md](references/review-and-automation.md): export QA,
  `verify`, `review-export`, batch renders, CLI output and exit codes.
- [finishing-tools.md](references/finishing-tools.md): white-flash montage,
  over-under stack, custom FFmpeg looks, matching a reference video.

# Beat-Synced Edit — Codex & Claude Code

This fork of [ZiadAbdelkarim/beat-synced-edit](https://github.com/ZiadAbdelkarim/beat-synced-edit)
adds a self-contained **Codex skill** and a persistent project editor for precise
music-synced edits, mixed media, subject tracking, speed ramps and targeted revisions.
The original CLI and Claude Code skill remain available.

## Install for Codex

Ask Codex:

```text
$skill-installer Install the skill from
https://github.com/Net2Fox/beat-synced-edit/tree/main/skills/beat-sync-edit
Then create its local Python environment and install requirements.txt.
```

Or copy `skills/beat-sync-edit` into your personal Codex skills directory.
Install the whole skill directory: it includes the Python tools, workflow references, requirements
and MIT license. The skill's `SKILL.md` describes the environment setup.
Python and FFmpeg/ffprobe are required; the `.venv` is created on the target machine.

Example request after installation:

> Use $beat-sync-edit. Create a 25-second edit from my footage set to this track:
> 9:16, 1080×1920, cuts on the beat, and quick zooms on the drop. Export as MP4.

### Project editor

| Capability | Behavior |
|---|---|
| Exact duration | Plans a contiguous frame-based timeline and verifies the rendered frame count. Shortages use unused ranges, longer/slower shots, or explicitly allowed repeats. |
| Mixed sources | Imports videos, photos, folders and ZIPs with persistent absolute source paths and unique IDs. Normalizes dimensions, frame rates and orientation during rendering. |
| Musical structure | Estimates intro, build, drop and outro from energy rises and beats. Accepts explicit section boundaries. |
| Content-aware selection | Uses Codex-reviewed object tags, shot sizes, action timestamps and quality labels, plus visual fingerprints to favor varied shots. |
| Subject-aware framing | Tracks an explicitly chosen region, or uses face/motion cues. Smooths the camera path; fixed crops and letterboxing are also available. |
| Smooth speed ramps | Interpolates a speed curve across each shot and can anchor a source action to a musical beat without changing output duration. |
| Style recipes | `cinematic`, `car`, `gaming` and `product` control pace, preferred shots, color, accents and retiming. Settings remain editable. |
| Preview and revisions | Creates a smaller MP4 and offline HTML review page. Replace a shot, change its length, remove effects, adjust framing/speed, or reorder; unchanged shots use the render cache. |
| Titles | Timed Unicode text with fonts, outline, translucent background, safe margins, wrapping and fade/slide animations. |
| Subtitles | Import/export SRT and WebVTT, edit phrases and timing, shift the track, and burn captions into previews and final MP4 without rebuilding cached shots. |
| Automatic captions | Optional local Faster Whisper transcription, phrase segmentation and word highlighting. Saves the raw transcript for review and correction. |

The project workflow is documented in
[the skill reference](skills/beat-sync-edit/references/project-workflow.md).
It includes the visual annotation step, section and revision JSON, and PowerShell
examples. A minimal CLI sequence, using the skill environment or an interpreter
with `requirements.txt` installed:

```sh
python -X utf8 edit_project.py analyze /path/to/footage --work work/library
python -X utf8 edit_project.py music /path/to/song.wav --duration 25 -o work/beats.json
# View the contact sheets; write observations using their actual clip IDs.
python -X utf8 edit_project.py annotate work/library/library.json --annotations work/annotations.json
python -X utf8 edit_project.py plan --library work/library/library.json --beats work/beats.json --duration 25 --preset car -o work/project.json
python -X utf8 edit_project.py preview work/project.json -o work/preview.mp4
python -X utf8 edit_project.py revise work/project.json --operations work/revisions.json
python -X utf8 edit_project.py render work/project.json -o outputs/edit.mp4
```

Save `project.json` and retain the source media/imports to resume later. Changes
keep recoverable project snapshots under `.history/`. Preview HTML is local and
uses no CDN; its controls export revisions for the CLI or Codex to apply.

Duration is quantized to the nearest output frame (25 seconds at 30 fps is exactly
750 frames). Automatic musical sections and tracking need review. Semantic tags
come from actual visual inspection/annotations, not from brightness heuristics.
Slow motion uses neighboring-frame blending, not optical-flow or generative
interpolation. The tool does not invent missing footage or silently repeat it.

### Titles and subtitles

Ask Codex, for example:

> Use $beat-sync-edit. Add an animated opening title, transcribe the Russian
> speech into short captions, highlight the spoken words in yellow, and export
> the video plus an SRT file. Keep the existing edit and music timing.

```sh
python -X utf8 edit_project.py title work/project.json --text "A new beginning" --start 0 --end 2 --animation fade
python -X utf8 edit_project.py subtitles-import work/project.json captions.srt --preset boxed
# Optional recognition packages; audio stays local, model downloads on first use.
python -m pip install -r requirements-transcription.txt
python -X utf8 edit_project.py subtitles-transcribe work/project.json --language ru --model small --preset karaoke
python -X utf8 edit_project.py subtitles-export work/project.json -o outputs/captions.vtt
python -X utf8 edit_project.py render work/project.json -o outputs/captioned.mp4
```

Import/transcription replaces the caption track in a recoverable project
revision. Recognition uses the audible soundtrack range by default; correct
misheard text before delivery. SRT/VTT sidecars preserve text and cue times;
styling and animations appear in the rendered MP4. Word highlighting requires
word timestamps from recognition or explicit annotations. The full
[text guide](skills/beat-sync-edit/references/text-and-subtitles.md) covers
alignment, local model caches, styles, the review page and targeted revisions.

### What changed in this fork

- A portable [Codex skill](skills/beat-sync-edit/SKILL.md), with UTF-8 PowerShell
  commands and an isolated environment instead of global Python packages.
- Thumbnail and contact-sheet output works with Cyrillic Windows paths.
- The edit plan and soundtrack start at the same selected beat, removing the
  original leading-offset mismatch between music and the concatenated picture.
- Pillow is an explicit dependency; OpenCV is installed explicitly without the
  removed `scenedetect[opencv]` extra.
- Vertical-only requests use `cover` and `grade none`; squeeze and color grades
  remain available when requested.

`requirements.lock.txt` is the tested Windows / Python 3.12 snapshot. Use
`requirements.txt` for dependency resolution on other platforms. The original
`plan_edit.py` retains its legacy behavior and may stop early when scenes run
out; use `edit_project.py` for the exact-duration project workflow.

### Development and verification

The root Python files are the source of truth. After changing them, rebuild the
installable copy and verify it:

```sh
python tools/build_codex_skill.py
python tools/build_codex_skill.py --check
python -X utf8 -m unittest discover -s tests -p "test_*.py"
python -X utf8 tests/smoke_test.py
python -X utf8 tests/project_smoke_test.py
python -X utf8 tests/text_smoke_test.py
```

Run the tests with an interpreter that has `requirements.txt` installed and
FFmpeg/ffprobe on PATH. The smoke test generates its own footage and rhythm in
ignored `work/smoke/`, including Cyrillic filenames. It exercises analysis,
contact sheets, planning, rendering, white-flash transitions and 1080×1920 export
with audio. It does not need personal videos. It also accepts `--skill-dir` to
check a separately installed copy and `--work-dir` for test outputs.
The project tests additionally cover mixed sources, annotations, safe persistent
ZIP imports, musical sections, source reuse policies, tracked subjects, ramps,
rotated full-HD output, revision history and cache invalidation. The project smoke
test exercises the complete CLI workflow with generated assets.
The text smoke test checks Cyrillic titles, SRT/VTT interchange, caption
revisions, rendering and shot cache reuse. It does not download speech models.

Original attribution and license are retained in [LICENSE](LICENSE).
The source revision and adaptation details are recorded in [UPSTREAM.json](UPSTREAM.json).

---

## Original project

Automatic beat-synced video editing.

Feed it a song and raw footage. It analyzes the beats, maps the energy, tags every scene, and cuts a ready-to-post edit — zero manual editing.

## Demos

<!-- EMBED STEP (once, in GitHub's web editor): click the pencil on this README,
     then for each cell below: select the PASTE-VIDEO-HERE line and drag the
     matching file from examples/ onto it. GitHub uploads the video and inserts
     a user-attachments URL that renders as an inline player. Keep the blank
     lines around each URL — without them the player won't render. -->

<table>
<tr>
<td width="55%" align="center">

https://github.com/user-attachments/assets/60be3f2a-6e7d-48ef-8455-f08f0387a8b2

<em>1:1 montage — white-flash transitions + punch-ins · <a href="#white-flash-montage-template">how to make one ↓</a></em>

</td>
<td width="45%" align="center">

https://github.com/user-attachments/assets/5959c81f-a305-446c-af12-92d15abade9d

<em>9:16 beat-synced edit — green-strong grade, stock footage + my own single</em>

</td>
</tr>
</table>

Full-quality versions of both demos live in [`examples/`](examples/).

---

## Two ways to use it

### 1. Pure CLI — deterministic, no AI

Run the four stages yourself. Same inputs, same edit, every time.

### 2. Claude Code skill — conversational

The repo ships a skill at `.claude/skills/beat-sync-edit/SKILL.md`. Open this folder in [Claude Code](https://claude.com/claude-code) and describe the edit you want:

> "cut my footage to the chorus, white flash on every drop, space the cuts out so the shots breathe, then make it 9:16"

Claude runs the same pipeline and layers ffmpeg effects at beat-accurate timestamps — white flashes, stretch punches, hue shifts, RGB split, speed ramps, shakes, color grades. The full effects cookbook lives in the skill file.

In conversation you can also dictate:

- **Aspect ratio** — 9:16 vertical, 1:1 square, stacked over-under, or leave it 16:9
- **Cut density** — "a cut on every beat" vs "spaced out, let the shots breathe"
- **Hue / tint by reference** — point Claude at any other video on your machine ("grade it like this one") and it will sample frames from the reference and build a matching color grade; with the Claude-in-Chrome extension it can even study a look from a video on the web

---


## How it works

```
song.mp3  ──►  beat_map.py    ──►  beats, energy curve, peaks/valleys (JSON)
clips.mp4 ──►  clip_tag.py    ──►  scenes tagged by motion/energy/brightness (JSON)
both      ──►  plan_edit.py   ──►  edit decision list: which clip hits which beat
EDL       ──►  render_edit.py ──►  final MP4 (extract → concat → mux audio)
```

| Stage | What it does |
|---|---|
| `beat_map.py` | librosa audio analysis — beat timestamps, tempo, energy over time, peaks/valleys, best highlight segments |
| `clip_tag.py` | PySceneDetect scene detection + per-clip motion/energy/brightness scoring; `--thumbs` exports a labeled contact sheet |
| `plan_edit.py` | the matcher — high-energy clips land on energy peaks, calm clips on valleys, with anti-repetition, source spacing, and black-frame filtering |
| `render_edit.py` | ffmpeg assembly; `--overunder` emits a stacked 960×1080 variant |
| `vertical_style.py` | fits 16:9 output into 9:16 with a stylized squeeze + grade for TikTok / Reels / Shorts |
| `flash_montage.py` | the white-flash montage template — 1:1 edits from stills and/or video clips with `fadewhite` transitions, punch-ins, and handheld sway (see below) |

---

## Quickstart

```bash
pip install -r requirements.txt   # ffmpeg must be on PATH (brew install ffmpeg)

python3 beat_map.py song.mp3
python3 clip_tag.py footage.mp4 --thumbs
python3 plan_edit.py song_beatmap.json footage_clips.json --html
python3 render_edit.py footage_edl.json -a song.mp3 -v footage.mp4
```

---

## Controlling the cut

All creative control lives in `plan_edit.py`:

| Flag | Effect |
|---|---|
| `--beat-stride N` | Cut density. `1` = a cut on every beat (default). `2`+ keeps every Nth beat — fewer, longer cuts that breathe, for slow or contemplative footage |
| `--full` | Edit the whole song instead of the best-scoring segment |
| `--segment 2` | Use the second (or third) best highlight segment |
| `--exclude '1,6,0-30'` | Drop clips by id or source time range |
| `--lead '2:18,5'` | Force the opening cuts, in order |
| `--pin '8=138,peak2=22'` | Pin a clip to a specific beat, peak, or valley |

A useful convention when comparing densities: render both and suffix them `_beat-full` and `_beat-thinned`.

---

## White-flash montage template

The square demo above is a montage: each scene holds for a couple of beats (about 2.8 seconds in the demo), then blooms into the next through a white flash. You make one by describing it.

Open this folder in [Claude Code](https://claude.com/claude-code), point it at your song and a folder of clips or photos, and say what you want:

> "make a white-flash montage from these six clips — punch in on each animal, flashes about a second long"

> "use still frames instead of the moving clips, and give them a little handheld shake"

> "quicker flashes, and end it on a fade to white"

Claude picks the moments from each clip, frames each subject, times the scenes to your song, and renders the finished 1:1 video. Scenes can be video clips or still photos — stills get a subtle handheld sway so they don't look frozen — and the flash length is whatever you ask for.

Prefer the command line? `python3 flash_montage.py --seq seq.json --audio song.wav --out montage.mp4` — the `seq.json` format is documented at the top of the script.

---

## Requirements

- Python 3.10+
- ffmpeg on PATH
- `pip install -r requirements.txt` — librosa, PySceneDetect, OpenCV, NumPy

---

## License

[MIT](LICENSE)

---
name: beat-sync-edit
description: Create music-synced video edits from footage for TikTok, YouTube Shorts and Reels. Use for montage, beat-sync, эдит под музыку, монтаж в бит, transitions, flashes, speed changes and vertical video export.
---

# Beat-Sync Edit

Drive the deterministic pipeline conversationally. The user describes the edit
they want ("cut my footage to the chorus, white flash on every drop, make it
9:16"); you run the stages, apply effects, and deliver the file.

## Codex setup and paths

This skill bundles the Python tools in `scripts/`. Dependencies are installed locally
in `.venv/`; the environment is not shipped in Git. Resolve `skillRoot` from the location of this SKILL.md, never from the
current project directory. Use that local interpreter after setup; no environment activation or global pip
installation is needed. On Windows/PowerShell:

```powershell
$skillRoot = Split-Path -Parent '<absolute path to this SKILL.md>'
$editPython = Join-Path $skillRoot '.venv/Scripts/python.exe'
$editScripts = Join-Path $skillRoot 'scripts'
# One-time setup after installation, if the environment is missing:
python -m venv (Join-Path $skillRoot '.venv')
& $editPython -m pip install -r (Join-Path $skillRoot 'requirements.txt')
```

Use `-X utf8` on every Python invocation to support Cyrillic paths and Unicode logs.
On Linux/macOS use `.venv/bin/python` if the environment was recreated there.
FFmpeg and ffprobe must be on PATH. Dependencies are in `requirements.txt`;
`requirements.lock.txt` records the tested Windows / Python 3.12 environment; it is
an optional reproducibility snapshot, not a cross-platform compatibility guarantee.
For Linux/macOS, create the environment with `python3 -m venv <skillRoot>/.venv`
and install `requirements.txt` using that environment's `bin/python -m pip`.

Keep analysis JSON, temporary media and preview sheets in the current project's
`work/` folder and final exports in its `outputs/` folder (or the user's requested
location). Pass explicit absolute input and output paths. Do not write media to the
skill folder. Set `NUMBA_CACHE_DIR` to a directory under project `work/` when
the skill installation is read-only. The following pipeline uses example variables
for absolute paths.

## The pipeline (run in order)

```powershell
& $editPython -X utf8 "$editScripts/beat_map.py" $song -o "$work/beatmap.json"
& $editPython -X utf8 "$editScripts/clip_tag.py" $footage --thumbs -o "$work/clips.json"
& $editPython -X utf8 "$editScripts/plan_edit.py" "$work/beatmap.json" "$work/clips.json" -o "$work/edit.json"
& $editPython -X utf8 "$editScripts/render_edit.py" "$work/edit.json" -a $song -v $footage -o "$work/cut.mp4"
& $editPython -X utf8 "$editScripts/vertical_style.py" "$work/cut.mp4" --fit cover --grade none --size 1080x1920 -o "$outputs/edit.mp4"
```

- `--fit cover --grade none` preserves proportions and color when only vertical
  framing is requested. Inspect the crop and use `contain` or custom reframing
  if the subject is outside the center. The upstream tool's bare defaults apply
  a squeeze and pink grade; use these only when they match the requested style.
- For multiple source files, inspect `clips.json` and resolve every EDL
  `clip_source` to its original absolute file path before rendering. The upstream
  multi-file analysis retains basenames; unresolved names otherwise fall back
  to the `-v` source. Extract ZIP inputs into project work first so source files
  remain available through rendering.
- The local planner starts the soundtrack at the first selected beat and rebases
  the EDL to zero, keeping the music and concatenated picture aligned.
- Inspect the EDL timing against the beat map. The planner can stop early when
  it runs out of unique scenes; `--full` does not guarantee the requested length.
  Resolve gaps/shortfalls before claiming that a requested duration was met.
- Optional `--html` creates analysis charts; beat-map HTML loads Chart.js from
  a public CDN. It is not required for editing or local JSON analysis.


- Read the beatmap's `peaks`/`valleys` and the EDL before adding effects —
  effects belong ON beat timestamps, not at arbitrary times.
- `plan_edit.py` overrides: `--exclude '1,6,0-30'`, `--lead '2:18,5'`,
  `--pin '8=138,peak2=22'` — use them when the user dislikes a cut.
- `plan_edit.py --beat-stride N` — cut density. 1 = a cut on every beat
  (default); N>1 keeps every Nth beat: fewer, longer cuts that breathe, for
  slow/contemplative footage. Naming convention for variants:
  `<name>_beat-full` (stride 1) vs `<name>_beat-thinned` (stride 2+).
- `plan_edit.py --full` uses the whole song instead of the best segment;
  `--segment 2|3` picks the second/third-best highlight segment.
- `render_edit.py --overunder` emits the stacked 960x1080 "3D" variant.

## The white-flash montage template (separate edit style)

When the user asks for a MONTAGE — a 1:1 sequence of held shots/stills with
white-flash transitions ("white flash between each clip", "photo narrative",
"meme montage") — use `flash_montage.py` instead of the beat pipeline:

```powershell
& $editPython -X utf8 "$editScripts/flash_montage.py" --seq "$work/seq.json" --audio $song --out "$outputs/montage.mp4" --flash 1.0
```

Author the seq.json yourself from the user's description: one item per shot,
`{"video": path, "start": t, "dur": d}` or `{"image": path, "dur": d}`, with
`zoom`/`cx`/`cy` to punch in on each subject (LOOK at a frame first to place
cx/cy), `stretch` for width hits, `motion: "sway"` for handheld feel (default
on stills, off for videos). Set `dur` to a beat-multiple of the song's tempo
(from beat_map.py) so flashes land musically — e.g. 4 beats per slot. Iterate
by editing the seq.json, not by rebuilding commands.

## What the user can ask for (translate words → workflow)

- "punchier / more cuts" → `--beat-stride 1` (default), or lower clip_tag
  `--threshold` for finer scenes
- "calmer / spaced out / longer scenes / let shots breathe" →
  `--beat-stride 2` (or 4 for very slow footage); when comparing, render both
  and suffix the outputs `_beat-full` / `_beat-thinned`
- "start on the best moment" → `--lead` with the highest-energy clip
- "make it vertical / TikTok-ready / 9:16" → vertical_style.py after render;
  "square / 1:1" → center-crop with ffmpeg (`crop=ih:ih,setsar=1` + scale);
  "stacked / over-under" → `render_edit.py --overunder`
- **Reference videos — take ONLY what the user asks for.** A reference is not
  a request to clone the whole look. Extract 3-5 frames
  (`ffmpeg -ss <t> -frames:v 1`), LOOK at them, then match just the named
  aspect(s): "this tint" → hue/cast only (`hue`, `colorbalance`); "this
  contrast" → `curves`/`eq` only; "how washed out it is" → saturation only;
  "the way it cuts" → cut rhythm/density, not color at all; "that flash
  effect" → just that effect from the cookbook. If they say "make it look
  like this" without naming an aspect, ASK which parts they mean (color?
  contrast? pacing? effects?) before matching more than one. Show a
  confirmation frame before final render. If the reference is on the web and
  Chrome tools are available, study it there the same way.

## Effects cookbook (apply with ffmpeg per segment, then re-concat)

Apply to individual extracted segments between the extract and concat steps
(re-encode the segment with `-vf "<filter>"`), or to the final file. Time
effects to beat timestamps from the beatmap.

| User says | ffmpeg filter |
|---|---|
| white flash (on the beat/drop) | `fade=t=in:st=0:d=0.07:color=white` on the segment starting at that beat |
| black dip | `fade=t=in:st=0:d=0.07:color=black` |
| stretch / punch-in | `scale=iw*1.15:ih*1.15,crop=iw/1.15:ih/1.15,setsar=1` (hold ~2 frames, then normal) |
| horizontal stretch hit | `scale=iw*1.25:ih,crop=iw/1.25:ih,setsar=1` |
| hue shift / psychedelic | static: `hue=h=60` · animated: `hue=h='mod(t*180,360)'` |
| RGB split / glitch | `rgbashift=rh=6:bh=-6` |
| speed ramp | `setpts=0.5*PTS` (2x) · `setpts=2*PTS` (half speed; add `minterpolate` for smoothness) |
| shake | `crop=iw-20:ih-20:'10+8*sin(t*40)':'10+8*cos(t*37)'` |
| strobe invert | `negate=enable='lt(mod(t,0.25),0.04)'` |
| dreamy glow | `gblur=sigma=8,blend=all_mode=screen,all_opacity=0.35` (via split) |
| grade: warm | `colorbalance=rm=.12:bm=-.08` · cool: `colorbalance=bm=.12:rm=-.06` |

Rules of thumb: flashes/punches on energy PEAKS only (over-flashing reads
amateur); one signature effect per edit + one grade; always `-pix_fmt yuv420p`
and `setsar=1` when re-encoding segments so concat stays valid.

## Workflow when the user asks for an edit

1. Run beat_map + clip_tag (with `--thumbs`; view the contact sheet to know
   the footage).
2. plan_edit → review the EDL against their description; apply overrides.
3. render_edit → if effects were requested, re-extract the affected segments
   with filters at the right beats, re-concat, re-mux audio.
4. Apply the requested format and effects, then verify the actual MP4 with
   ffprobe (duration, dimensions, video/audio streams), inspect representative
   frames and check the cut timing against the music. Deliver the file path,
   duration, cut count and effects used; state any unverified playback details.

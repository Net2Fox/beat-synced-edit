# Finishing tools and custom looks

Read this when a request needs something the project renderer does not do: a
square white-flash montage, an over-under stack, an FFmpeg look the project has
no effect for (its effects are in [effects-and-looks.md](effects-and-looks.md)),
or matching a reference video. Build every other edit with
`edit_project.py`: it keeps exact duration, revisions and export QA. Nothing
in these tools enforces the playback-speed rule in SKILL.md; follow it here
too.

Contents: [Square white-flash montage](#square-white-flash-montage) ·
[Over-under stack](#over-under-stack) ·
[Custom FFmpeg looks](#custom-ffmpeg-looks-on-a-finished-mp4) ·
[Matching a reference video](#matching-a-reference-video)

Check every file these tools produce with
`edit_project.py verify <file> --work <work>/qa` before delivering it. Add
`--project <work>/project.json` only for a custom look on a project render,
whose size and length match the project
([review-and-automation.md](review-and-automation.md)).

## Square white-flash montage

For a 1:1 sequence of held shots or stills joined by long white-flash
transitions ("white flash between each clip", "photo narrative", "meme
montage"), use `flash_montage.py`. For short flash accents inside an ordinary
beat edit, use the project presets/effects instead.

```sh
flash_montage.py --seq <work>/seq.json --audio <song> --out <outputs>/montage.mp4 --size 1080 --flash 0.5
```

Defaults: `--size 1080`, `--flash 0.5` (seconds), `--fps 30`. The first item
fades in from white unless you pass `--no-open-flash`; `--close-flash` fades
the last item out to white.

Write `seq.json` yourself, one item per shot, in order:

```json
{"items": [
  {"image": "/abs/a.jpg", "dur": 2.0, "zoom": 1.4, "cx": 0.5, "cy": 0.3, "motion": "sway"},
  {"video": "/abs/clip.mp4", "start": 7.0, "dur": 2.0, "zoom": 1.25}
]}
```

- `image` or `video`: absolute path. `start`: source time for videos
  (default 0); `start + dur` must stay inside the clip.
- `dur`: seconds on screen, including the flash overlap. Each `dur` must be
  longer than `--flash`.
- Output is always square (`--size` pixels per side): each source is
  cover-cropped to a centred square, so the sides of a landscape frame are
  lost. `zoom` with `cx`/`cy` (0-1 fractions of that square, default 0.5)
  punches in on a subject; open a frame first to place them. `stretch` > 1
  widens the subject while keeping 1:1; it distorts proportions, so follow
  the natural-look rule in SKILL.md.
- `motion`: `sway` (default for stills), `zoom` (slow push-in) or `none`
  (default for videos).
- Length = `sum(dur) - (N-1) * flash`. The song plays from its start and is
  trimmed to that length, so it must be at least that long; to start later in
  the song, cut it first (`ffmpeg -ss <t> -i <song> <work>/song-cut.wav`).
- The flash after item `i` (counting from 0) starts at
  `sum(dur[0..i]) - (i+1) * flash`. To land flashes on the music, put these
  times on `beats` from `edit_project.py music <song> -o <work>/beats.json`,
  measured on the file you pass to `--audio`; for a flash every k beats, use
  `dur = k * 60 / tempo + flash`. Keep `k * 60 / tempo` at 1/3 s or more
  (k = 2 or more above 180 BPM, and check for a doubled tempo): the script
  refuses more than three flashes in any second (SKILL.md rule 7).

Iterate by editing `seq.json` and re-running the command.

## Over-under stack

For the "3D over-under" look (the same view stacked top and bottom), process
a finished MP4:

```sh
overunder_stack.py <outputs>/final.mp4 -o <outputs>/final-overunder.mp4 --size 960x1080
```

`--size` is the whole frame (default `960x1080`; the height must be even) and
each half is W x H/2. A source with the half's aspect ratio (16:9 at the
default size) fills it uncropped; other ratios are scaled to cover and
centre-cropped, so a vertical source loses most of its height. Audio is
copied. Without `-o` the output is `<input>_overunder.mp4`.

## Custom FFmpeg looks on a finished MP4

First use what the project already does, because it is cached, revisable and
survives a re-render: grades, accents on a cut (flash, dip, invert, RGB split,
glitch, stretch, blur), whips, zoom, shake, beat pulse, vignette, grain, glow
and letterbox ([effects-and-looks.md](effects-and-looks.md)), faster playback
(the `speed` revision) and square or vertical output (`plan --size`, see
[project-workflow.md](project-workflow.md)).

Use FFmpeg only for what the renderer lacks: a hue shift, a strobe over a time
range, an accent in the middle of a shot (project accents start at a cut), or
a look on a `flash_montage.py` or `overunder_stack.py` output. Apply one
filter to the finished file and limit it to a time range with
`enable='between(t,A,B)'`, taking `A`/`B` from the output timeline: a cut is
at `timeline_start_frame / output.fps` of its shot in the `edits` of
`<work>/project.json`; a beat is at its time in `<work>/beats.json` minus
`audio.start` in `project.json`. Re-encode the picture only, so duration and
audio stay unchanged:

```sh
ffmpeg -i <outputs>/final.mp4 -vf "<filter>" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a copy <outputs>/final-look.mp4
```

| Request | Filter |
|---|---|
| hue shift | `hue=h=60:enable='between(t,A,B)'`; animated: `hue=h='mod(t*180,360)'` |
| strobe invert from A to B (2 per second) | `negate=enable='between(t,A,B)*lt(mod(t-A,0.5),0.04)'` |
| black dip at T inside a shot | `fade=t=in:st=T:d=0.07:color=black:enable='between(t,T,T+0.07)'` |
| RGB split inside a shot | `rgbashift=rh=6:bh=-6:enable='between(t,A,B)'` |
| horizontal stretch hit at T inside a shot | `-filter_complex "split[a][b];[b]scale=iw*1.25:ih,crop=iw/1.25:ih[s];[a][s]overlay=enable='between(t,T,T+0.1)'"` instead of `-vf` |
| black and white (montage or stack) | `hue=s=0` |
| teal-orange (montage or stack) | `colorbalance=rs=-0.15:bs=0.15:rh=0.15:bh=-0.15` |
| dreamy glow (montage or stack) | `-filter_complex "split[a][b];[b]gblur=sigma=8[g];[a][g]blend=all_mode=screen:all_opacity=0.35"` instead of `-vf` |

Without `enable`, `fade` darkens everything before T. `crop` and `scale`
reject `enable` (FFmpeg fails), so the stretch row goes through `overlay`.
Never change speed or duration here: no `setpts`, `minterpolate`, `fps`,
`tmix` or other blending of neighbouring frames. Keep full-frame flashes and
inverts at three per second or fewer, counting the project's own accents
([effects-and-looks.md](effects-and-looks.md#craft-and-safety)).

Put accents on energy peaks or drops (`peaks` and `music_structure` in the
beat map) and use one signature effect and one grade per edit. A later
`render` does not reapply the look: after each revision and re-render, run
the FFmpeg step again.

## Matching a reference video

The reference-video rule in SKILL.md decides which aspects to match. Extract
3-5 frames (`ffmpeg -ss <t> -i <reference> -frames:v 1 <work>/ref-<t>.png`),
or study a web reference in a browser if browser tools are available, then map
each named aspect to one adjustment:

- tint: the nearest project grade first (`effects` revision with `grade`),
  otherwise `hue`/`colorbalance`; contrast: `curves`/`eq`; washed-out look:
  saturation only;
- the way it cuts: pacing (`plan --beat-stride`, `--section-stride`,
  `--min-shot`), not colour;
- a specific effect: only that effect, from the project catalog when it has
  one ([effects-and-looks.md](effects-and-looks.md)).

Show a preview frame before the final render.

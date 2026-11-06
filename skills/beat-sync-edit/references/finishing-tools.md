# Finishing tools and custom looks

Use these after `render` only when the request needs something the project
renderer does not do. Build the edit itself with `edit_project.py`: it keeps
exact duration, revisions and export QA. The playback-speed rule in SKILL.md
applies here too, and nothing in these tools enforces it.

Check every file these tools produce with
`edit_project.py verify <file> --work <work>/qa` before delivering it.

## Square white-flash montage

For a 1:1 sequence of held shots or stills joined by long white-flash
transitions ("white flash between each clip", "photo narrative", "meme
montage"), use `flash_montage.py`. For short flash accents inside an ordinary
beat edit, use the project presets/effects instead.

```sh
flash_montage.py --seq <work>/seq.json --audio <song> --out <outputs>/montage.mp4 --size 1080 --flash 0.5
```

Write `seq.json` yourself, one item per shot, in order:

```json
{"items": [
  {"image": "/abs/a.jpg", "dur": 2.0, "zoom": 1.4, "cx": 0.5, "cy": 0.3, "motion": "sway"},
  {"video": "/abs/clip.mp4", "start": 7.0, "dur": 2.0, "zoom": 1.25}
]}
```

- `image` or `video`: absolute path. `start`: source time for videos.
- `dur`: seconds on screen, including the flash overlap. Each `dur` must be
  longer than `--flash`.
- `zoom` with `cx`/`cy` (0-1 fractions) punches in on a subject; open a frame
  first to place them. `stretch` > 1 widens the subject while keeping 1:1.
- `motion`: `sway` (default for stills), `zoom` (slow push-in) or `none`
  (default for videos).
- Length = `sum(dur) - (N-1) * flash`; the audio is trimmed to it and must be
  at least that long. Output is always square (`--size` pixels per side).
- To land flashes on the music, take `tempo` from `edit_project.py music` and
  make each `dur` a whole number of beats (for example `4 * 60 / tempo`).

Iterate by editing `seq.json` and re-running the command.

## Over-under stack

For the "3D over-under" look (the same view stacked top and bottom), process
a finished MP4:

```sh
overunder_stack.py <outputs>/final.mp4 -o <outputs>/final-overunder.mp4 --size 960x1080
```

16:9 sources fill each half without cropping; other ratios are scaled to
cover and centre-cropped. The height must be even. Audio is copied.

## Custom FFmpeg looks on a finished MP4

First use what the project already does: flash, zoom/punch-in, shake and the
grades `none`, `neutral`, `cinematic`, `cool`, `vivid`, `warm` (plan presets,
`--grade` and the `effects` revision), faster playback (the `speed` revision)
and square or vertical output (`plan --size`). See
[project-workflow.md](project-workflow.md).

For anything else, apply one filter to the rendered file and limit it to a
time range with `enable='between(t,A,B)'`, taking `A`/`B` from the output
timeline (for example beat times from the beat map shifted by the plan's
`audio.start`). Re-encode the picture only, so duration and audio stay
unchanged:

```sh
ffmpeg -i <outputs>/final.mp4 -vf "<filter>" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a copy <outputs>/final-look.mp4
```

| Request | Filter |
|---|---|
| black dip at time T | `fade=t=in:st=T:d=0.07:color=black:enable='between(t,T,T+0.07)'` |
| hue shift | `hue=h=60:enable='between(t,A,B)'`; animated: `hue=h='mod(t*180,360)'` |
| RGB split / glitch | `rgbashift=rh=6:bh=-6:enable='between(t,A,B)'` |
| strobe invert | `negate=enable='between(t,A,B)*lt(mod(t,0.25),0.04)'` |
| black and white | `hue=s=0` |
| teal-orange | `colorbalance=rs=-0.15:bs=0.15:rh=0.15:bh=-0.15` |
| dreamy glow (whole clip) | `-filter_complex "split[a][b];[b]gblur=sigma=8[g];[a][g]blend=all_mode=screen:all_opacity=0.35"` instead of `-vf` |

`crop`, `scale` and `setpts` ignore `enable`, so punch-ins and stretches
belong in the project `effects` revision. Never change speed or duration
here: no `setpts`, `minterpolate`, `fps`, `tmix` or frame blending.

Put accents on energy peaks or drops (`peaks` and `music_structure` in the
beat map), use one signature effect and one grade per edit, and keep
`-pix_fmt yuv420p`.

## Matching a reference video

A reference is not a request to copy the whole look. Extract 3-5 frames
(`ffmpeg -ss <t> -i <reference> -frames:v 1 <work>/ref-<t>.png`), look at
them, then match only the aspects the user named:

- tint: `hue`/`colorbalance`; contrast: `curves`/`eq`; washed-out look:
  saturation only;
- the way it cuts: pacing (`plan --section-stride`, `--min-shot`), not colour;
- a specific effect: only that effect.

If the user says "make it look like this" without naming aspects, ask which
ones (colour, contrast, pacing, effects) before matching more than one. Show
a preview frame before the final render.

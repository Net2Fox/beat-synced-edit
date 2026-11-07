# Effects, transitions and looks

Read this when the user asks for flashes, glitch, RGB split, whips or other
transitions, shake, zoom on the beat, film grain, vignette, letterbox bars,
a colour grade, or for removing effects. Effects live in each shot's `effects`
object of `<work>/project.json`. They are rendered into the cached shot,
changed with `revise`, and never overlap shots, change a frame count or change
playback speed. `edit_project.py effects` prints the live catalog (names,
ranges, grades and transitions); unknown names and out-of-range values are
rejected before a project is saved.

Contents: [Where effects come from](#where-effects-come-from) ·
[Catalog](#catalog) · [Grades](#grades) · [Transitions](#transitions) ·
[Requests to operations](#requests-to-operations) · [Craft and safety](#craft-and-safety)

## Where effects come from

1. **Preset.** `plan --preset NAME` copies the preset's effects to every shot.
   Accents (flash, dip, invert, rgb_split, glitch, stretch, blur_in) and shake
   stay only on accent shots: drop shots that start on a beat and are either
   the first shot of a drop section or every Nth shot of the edit (shots 1,
   5, 9, … with N = 4; shots 1, 3, 5, … with N = 2 for `phonk` and `anime`).
   Elsewhere they are zeroed and the punch-in zoom is reduced. Looks (grade,
   vignette, grain, glow, letterbox) stay on every shot; `pulse` stays only in
   build and drop. A `phrase_flow` plan has no drop, so it gets no accents.
   Naming a style preset (`phonk`, `anime`, `travel`) counts as asking for
   its look: plan it without `--grade none`.
2. **Plan flags.** `--grade NAME` replaces the preset's grade; `--grade none`
   (or `--effect grade=none`) means a natural look and also removes the
   preset's vignette, grain, glow and letterbox (`--grade neutral` drops only
   the colour grade). Repeatable
   `--effect NAME=VALUE` then overrides one effect of the preset (accents
   still land only on accent shots), so
   `--grade none --effect grain=0.15` gives natural colour with grain as the
   only look, and `--effect flash=0` turns flashes off everywhere.
3. **Revisions**, the normal way to change an existing edit. Each line below
   is a separate example. Operations in one list apply in order, so a
   transition placed after an `effects` operation clears the accents that
   operation set on the cut's incoming shot.

```json
{"op": "effects", "section": "drop", "values": {"rgb_split": 0.6, "shake": 0.3}}
{"op": "effects", "shot": 4, "reset": true, "values": {"grade": "mono"}}
{"op": "transition", "after": 3, "type": "whip", "strength": 0.8}
{"op": "transition", "section": "drop", "type": "flash", "strength": 0.6}
{"op": "transition", "all": true, "type": "cut"}
```

- `effects` targets `shot` (number from 1 or ID), `section` or `all: true` and
  merges `values`; `reset: true` clears the shot's effects first, grade
  included, and removes the transitions on its cuts, so both become hard cuts.
  `"grade": "none"` also removes looks not set in the same `values`.
- `transition` takes `type`, an optional `strength` (0–1, default 1) and
  exactly one of `after` (the outgoing shot), `section` (every cut into a shot
  of that section: `intro`, `build`, `drop`, `outro`; `flow` in a
  `phrase_flow` plan and `speech` in a speech project) or `all: true`.
- A transition owns its cut: setting one first clears the incoming shot's
  accents (the preset's too) and `whip_in`, the outgoing shot's `whip_out`, and
  any earlier transition there, restoring the shot's own zoom (or the zoom an
  `effects` revision set after the transition). `type: "cut"` stops there and
  leaves a hard cut. A `reorder` keeps a transition only while its two shots
  stay next to each other; a B-roll insert keeps it on the outer cuts only.
- `edit_project.py inspect <work>/project.json` lists the sections. Effect
  revisions re-render only the shots they change; text-only revisions none.

## Catalog

| Effect | Group | Range | What it does |
|---|---|---|---|
| `flash` | accent | 0–1 | White flash fading out over 80 ms from the cut |
| `dip` | accent | 0–1 | Fade up from black over 160 ms |
| `invert` | accent | 0–1 | Negative-image hit for about 70 ms |
| `rgb_split` | accent | 0–1 | Red/blue channel offset decaying over 200 ms |
| `glitch` | accent | 0–1 | Displaced slices and channel offset for about 130 ms |
| `stretch` | accent | 0–1 | Horizontal stretch hit settling over 150 ms |
| `blur_in` | accent | 0–1 | Defocus clearing over 250 ms |
| `whip_in` | transition | 0–1 | Motion-blurred slide into the shot (first 200 ms) |
| `whip_out` | transition | 0–1 | Motion-blurred slide out of the shot (last 200 ms) |
| `zoom` | motion | 1–4 | Punch-in settling over 180 ms; a slow push-in on stills |
| `shake` | motion | 0–1 | Camera shake for the whole shot |
| `pulse` | motion | 0–1 | Zoom bump on every measured beat inside the shot |
| `vignette` | look | 0–1 | Darkened frame edges |
| `grain` | look | 0–1 | Film grain |
| `glow` | look | 0–1 | Soft bloom around highlights |
| `letterbox` | look | 0–0.35 | Black bars; the height of **each** bar as a fraction of the frame |

Strength guide: subtle 0.2–0.4, clear 0.5–0.7, hard 0.8–1. `pulse` uses the
project's beat map (music projects only; speech and motion projects have no
beats).

Render cost: the `cinematic`, `vivid`, `moody`, `vintage` and `teal_orange`
grades make a render about 2.5–3.5 times slower than no grade, so
`cinematic` (the default), `gaming`, `phonk`, `anime` and `travel` take that
much longer than `car`, `product` or any plan with `--grade none`. Among the
looks, `grain` costs about as much as a grade and makes the exported file many
times larger; `glow` costs some, `vignette` and `letterbox` little. For a fast
draft, preview with `--grade none` or `--grade neutral --effect grain=0`.

Letterbox for a target aspect `A` on a `W×H` frame: `bar = (1 - W/(A·H)) / 2`.
On 16:9 output 2.39:1 is `0.128` and 2:1 is `0.056`. On 9:16 output thin bars
(0.06–0.10) are a stylistic choice, not an aspect conversion. Bars cover
picture: keep captions and graphics inside the remaining area (the text
`--margin` or the style's `safe_area`, see [text-and-graphics.md](text-and-graphics.md)).

## Grades

| Grade | Look |
|---|---|
| `none` | natural: no grade and no looks (see above) |
| `neutral` | no colour grade; looks stay |
| `cinematic` | soft contrast, warm highlights |
| `cool` / `warm` | colour temperature |
| `vivid` | saturated |
| `mono` | black and white |
| `teal_orange` | teal shadows, warm skin |
| `vintage` | faded blacks, warm, desaturated |
| `moody` | dark, desaturated, cool shadows |

## Transitions

| Type | Outgoing shot | Incoming shot |
|---|---|---|
| `cut` | clears `whip_out` | clears accents and `whip_in`, restores its zoom |
| `flash` / `dip` / `invert` | — | `flash` / `dip` / `invert` = strength |
| `whip` | `whip_out` = strength | `whip_in` = strength |
| `glitch` | — | `glitch` = strength, `rgb_split` = 0.6 × strength |
| `rgb` | — | `rgb_split` = strength, `stretch` = 0.4 × strength |
| `blur` | — | `blur_in` = strength |
| `zoom` | — | `zoom` = 1 + 0.3 × strength (not on a still photo, whose zoom is a slow push), `blur_in` = 0.4 × strength |

There are no cross-dissolves: shots never overlap, which keeps every cut
frame-exact on the beat and every shot cached on its own.

## Requests to operations

Translate the request into the smallest revision and keep the shot selection
unless the user asks for different footage. Re-planning with another preset
picks new shots; applying its effects with `revise` keeps the cut.

| Request (EN / RU) | Operation |
|---|---|
| "flash between clips" / «вспышки между клипами» | `{"op": "transition", "all": true, "type": "flash", "strength": 0.7}`; where cuts come faster than three a second, `revise` refuses it: flash every other cut (`after`) or use `rgb` / `whip` |
| "harder drop" / «жёстче дроп», «больше импакта» | `transition` `"section": "drop"` with `glitch` or `rgb` 0.7, plus `effects` `"section": "drop"` `{"shake": 0.3}` |
| "glitch, RGB" / «глитч», «RGB-сдвиг» | `transition` `glitch` (or `effects` `{"rgb_split": 0.6}`) on the named cuts |
| "smooth transitions" / «плавные переходы» | `transition` `whip` 0.6, or `blur` 0.7 (or `dip` 0.5 on slower cuts) for a softer feel |
| "zoom to the beat" / «пульс, зум под бит» | `effects` `"section": "drop"` `{"pulse": 0.6}` |
| "camera shake" / «тряска» | `effects` on accent shots `{"shake": 0.3}`; avoid it on speech close-ups |
| "film look" / «киношно», «как плёнка» | `effects` `all` `{"grade": "cinematic", "grain": 0.15, "vignette": 0.3, "letterbox": 0.1}` |
| "black and white" / «чёрно-белое» | `effects` `all` `{"grade": "mono"}` |
| "dark phonk vibe" / «мрачно, как фонк» | `effects` `all` `{"grade": "moody", "vignette": 0.45, "grain": 0.25}` plus glitch transitions on the drop, or plan with `--preset phonk` |
| "anime / AMV style" / «как AMV» | flash transitions on the drop (`rgb` where cuts are faster than three a second) and `{"pulse": 0.6, "glow": 0.35, "grade": "vivid"}`, or `--preset anime` |
| "warmer, colder" / «теплее», «холоднее» | `{"grade": "warm"}` / `{"grade": "cool"}` |
| "natural colours" / «без фильтров», «естественные цвета» | `effects` `all` `{"grade": "none"}` (removes looks too) |
| "fewer effects" / «поменьше эффектов» | halve strengths, or zero accents in intro and build |
| "remove all effects" / «убери все эффекты» | `{"op": "effects", "all": true, "reset": true}` |
| "remove the flashes" / «убери вспышки» | `{"op": "effects", "all": true, "values": {"flash": 0}}` |

Speed requests are not effects: "faster cuts" changes pacing
(`--section-stride`, shot durations), and slowing footage follows the
playback-speed rule in [SKILL.md](../SKILL.md#hard-rules), never an effect.

## Craft and safety

- One signature effect plus one grade reads as intentional; every accent on
  every cut reads as noise. Put accents on drops, downbeats and phrase starts,
  subtle in the build, full on the drop, little or none in intro and outro.
- Never exceed three full-frame flashes, dips or inverts in any one second:
  rapid flashing can trigger photosensitive seizures. `plan` drops the extra
  ones, `revise` refuses a revision that adds them, and export QA adds a
  review note when an older project still has them. On dense cuts use
  `whip`, `rgb` or `blur`.
- After an effect revision, preview and open the QA contact sheets
  ([review-and-automation.md](review-and-automation.md)): they sample frames
  on both sides of every cut, where accents and whips appear. Check that bars,
  vignette and glow do not hide captions or faces.
- Effects the renderer lacks (hue shift, a strobe over a time range, an
  accent in the middle of a shot, looks on a flash montage) are in
  [finishing-tools.md](finishing-tools.md).

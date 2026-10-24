# Effects, transitions and looks

Per-shot effects live in each shot's `effects` object of a saved project. They
are rendered into the cached shot, revised like any other operation, and never
overlap shots or change a frame count. `edit effects` prints the live catalog
(names, ranges, grades and transitions); unknown names and out-of-range values
are rejected before a project is saved.

## Where effects come from

1. **Preset.** `plan --preset NAME` copies the preset's effects to every shot,
   then keeps *accent* effects only on accent cuts: the first on-beat cut of
   the drop and every Nth on-beat drop cut (N = 4; 2 for `phonk` and `anime`).
   Elsewhere accents and shake are zeroed and punch-in zoom is reduced. Looks
   (grade, vignette, grain, glow, letterbox) stay on every shot; `pulse` stays
   only in build/drop.
2. **Plan overrides.** `--grade NAME` and repeatable `--effect NAME=VALUE`
   replace preset values before those rules apply. `--effect flash=0`
   disables flashes everywhere.
3. **Revisions** (the normal way to change an existing edit):

```json
[
  {"op": "effects", "section": "drop", "values": {"rgb_split": 0.6, "shake": 0.3}},
  {"op": "effects", "shot": 4, "reset": true, "values": {"grade": "mono"}},
  {"op": "transition", "after": 3, "type": "whip", "strength": 0.8},
  {"op": "transition", "section": "drop", "type": "flash", "strength": 0.6},
  {"op": "transition", "all": true, "type": "cut"}
]
```

`effects` targets `shot` (number from 1 or ID), `section` or `all: true` and
merges `values`; `reset: true` clears the shot's effects first (grade too).
`transition` edits both sides of a cut: `after` names the outgoing shot,
`section` selects every cut *into* that section, `all: true` every cut.
A `phrase_flow` project has a single `flow` section and no drop, so the planner
places no accents; target cuts with `after` or `all` instead (`edit inspect`
lists the sections).
Applying a transition first clears the previous transition at that cut;
`type: "cut"` returns it to a hard cut. Text-only revisions keep shot caches;
effect revisions re-render only the shots they change.

## Catalog

| Effect | Group | Range | What it does |
|---|---|---|---|
| `flash` | accent | 0–1 | White flash fading out over 80 ms from the cut |
| `dip` | accent | 0–1 | Fade up from black over 160 ms |
| `invert` | accent | 0–1 | Negative-image hit on the first two frames |
| `rgb_split` | accent | 0–1 | Chromatic red/blue offset decaying over 200 ms |
| `glitch` | accent | 0–1 | Displaced slices and channel offset for ~130 ms |
| `stretch` | accent | 0–1 | Horizontal stretch hit settling over 150 ms |
| `blur_in` | accent | 0–1 | Defocus clearing over 250 ms |
| `whip_in` | transition | 0–1 | Motion-blurred slide into the shot (first 200 ms) |
| `whip_out` | transition | 0–1 | Motion-blurred slide out of the shot (last 200 ms) |
| `zoom` | motion | 1–4 | Punch-in settling over 180 ms; slow push-in on stills |
| `shake` | motion | 0–1 | Camera shake for the whole shot |
| `pulse` | motion | 0–1 | Zoom bump on every measured beat inside the shot |
| `vignette` | look | 0–1 | Darkened frame edges |
| `grain` | look | 0–1 | Deterministic film grain |
| `glow` | look | 0–1 | Soft bloom around highlights |
| `letterbox` | look | 0–0.35 | Black bars; height of **each** bar as a fraction of frame height |

Strength guide: subtle 0.2–0.4, clear 0.5–0.7, hard 0.8–1. `pulse` uses the
project's `beat_frames` (music projects); speech and motion projects have none,
so it does nothing there. Beats are fixed when the project is planned; picture
revisions never move them, while a different `--audio-start` needs a new plan.

Letterbox for a target aspect `A` on a `W×H` frame: `bar = (1 - W/(A·H)) / 2`.
On 16:9 output 2.39:1 is `0.128`, 2:1 is `0.056`. On 9:16 output thin
"cinematic" bars (0.06–0.10) are a stylistic choice, not an aspect conversion.
Bars cover picture; keep captions and graphics inside the remaining area
(adjust `--margin` or the style's `safe_area`).

**Grades:** `none`/`neutral` (natural), `cinematic` (soft contrast, warm
highlights), `cool`, `warm`, `vivid` (saturated), `mono` (black and white),
`teal_orange` (teal shadows, warm skin), `vintage` (faded blacks, warm,
desaturated), `moody` (dark, desaturated, cool shadows). The user's "natural
color" or "no filter" request means `none`.

**Transitions** (`edit effects` lists the exact values each sets):

| Type | Outgoing shot | Incoming shot |
|---|---|---|
| `cut` | clears `whip_out` | clears all accents and `whip_in` |
| `flash` / `dip` / `invert` | — | `flash` / `dip` / `invert` = strength |
| `whip` | `whip_out` = strength | `whip_in` = strength |
| `glitch` | — | `glitch` = strength, `rgb_split` = 0.6·strength |
| `rgb` | — | `rgb_split` = strength, `stretch` = 0.4·strength |
| `blur` | — | `blur_in` = strength |
| `zoom` | — | `zoom` = 1 + 0.3·strength, `blur_in` = 0.4·strength |

There are no cross-dissolves: shots never overlap, which keeps every cut
frame-exact on the beat and every shot independently cached.

## Requests → operations

Translate the user's words into the smallest revision; keep shot selection
unless they ask for different footage. Re-planning with another preset
re-selects shots; applying its effects through `revise` keeps the cut.

| Request (EN / RU) | Operation |
|---|---|
| "flash between clips" / «вспышки между клипами» | `{"op":"transition","all":true,"type":"flash","strength":0.7}` |
| "harder drop" / «жёстче дроп», «больше импакта» | `transition` `section:"drop"` `glitch` or `rgb` 0.7, plus `effects` `section:"drop"` `{"shake":0.3}` |
| "glitch / RGB" / «глитч», «RGB-сдвиг» | `transition` `glitch` (or `effects` `{"rgb_split":0.6}`) on the named cuts |
| "smooth transitions" / «плавные переходы» | `transition` `whip` 0.6, or `dip` 0.5 / `blur` 0.7 for a softer feel |
| "zoom to the beat" / «пульс/зум под бит» | `effects` `section:"drop"` `{"pulse":0.6}` |
| "camera shake" / «тряска» | `effects` on accent shots `{"shake":0.3}`; avoid it on speech close-ups |
| "film look" / «киношно», «как плёнка» | `effects` `all` `{"grade":"cinematic","grain":0.15,"vignette":0.3,"letterbox":0.1}` |
| "black and white" / «чёрно-белое» | `effects` `all` `{"grade":"mono"}` |
| "dark phonk vibe" / «мрачно, как фонк» | `effects` `all` `{"grade":"moody","vignette":0.45,"grain":0.25}` + glitch transitions on the drop |
| "anime/AMV style" / «как AMV» | flash transitions on the drop, `{"pulse":0.6,"glow":0.35,"grade":"vivid"}` |
| "warm / cold" / «теплее», «холоднее» | `{"grade":"warm"}` / `{"grade":"cool"}` |
| "natural colors" / «без фильтров» | `effects` `all` `{"grade":"none"}` |
| "fewer effects" / «поменьше эффектов» | halve strengths, or zero accents on build/intro sections |
| "remove all effects" / «убери все эффекты» | `{"op":"effects","all":true,"reset":true}` |
| "remove the flashes" / «убери вспышки» | `{"op":"effects","all":true,"values":{"flash":0}}` |

Speed requests are not effects: "faster cuts" changes pacing (`--section-stride`
or shot durations), and slowing footage follows the playback-speed rule in
SKILL.md, never an effect.

## Craft and safety

- One signature effect plus one grade reads as intentional; stacking every
  accent on every cut reads as noise. Put accents on drops, downbeats and
  phrase starts.
- Accent strength should follow musical energy: subtle in the build, full on
  the drop, little or none in intro/outro.
- Do not exceed three full-frame flashes or inverts in any one second; rapid
  bright flashing can trigger photosensitive seizures. Prefer `dip`, `whip`
  or `rgb` for dense cuts.
- After an effect revision, preview and inspect the QA contact sheets: they
  sample frames on both sides of every cut, where accents and whips appear.
  Check that bars, vignette and glow do not hide captions or faces.

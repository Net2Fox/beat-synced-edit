# Capabilities

[English README](../README.md) · [Русский README](../README.ru.md) · [Русская версия](capabilities.ru.md)

This is the capability reference for **Net2Fox's fork** of `beat-synced-edit`.
The main workflow is a persistent editing project controlled through Codex, Claude Code or
`edit_project.py`. Separate legacy tools are described below; their effects are
not all switches in the project renderer.

## What you can make

| Edit | What the skill can do |
|---|---|
| TikTok, YouTube Shorts and Reels | Beat-synced vertical edits, normally 1080×1920, with selected shots, reframing, music, titles and captions. |
| Car and action edits | Alternate wide shots, details and action; increase cut density toward a drop; add short zoom punches, white flashes and shake. |
| Phonk and anime/AMV fan edits | Hard drop cuts with glitch/RGB hits, stretch and flash accents, zoom pulses on beats, whip transitions, moody or vivid looks with grain, glow and vignette. |
| Gaming highlights | Build a fast montage from supplied gameplay; prefer reviewed action/highlight labels and align a marked event with a beat. |
| Travel, nature and portrait films | Use a calmer pace, longer establishing shots, restrained accents and a cinematic or natural-color look. |
| Product, fashion and detail reels | Arrange overview/detail shots, use gentle motion on photos, add product names and closing calls to action. |
| Mixed video/photo montages | Combine clips and still images in one project, holding photos for the required time. |
| Captioned music or speech clips | Add manually written captions, import SRT/VTT, or recognize audible speech locally and highlight timed words. |
| Square and landscape edits | Choose an output such as 1080×1080 or 1920×1080 instead of the vertical default. |
| White-flash photo narratives | Use the separate square montage tool for held images/video and overlapping white-flash transitions. |

These are editing styles for existing material. They do not generate a missing
scene, an actor, a product shot or gameplay. The same tools can edit other
subjects when the source footage and directions are supplied.

## Inputs and media review

- Accept individual files, recursively scanned folders and ZIP archives, including
  mixed photos/videos and several inputs in one analysis.
- Recognized video extensions: MP4, MOV, MKV, WebM, AVI, M4V, WMV, MTS and M2TS.
  Recognized image extensions: JPG/JPEG, PNG, WebP, BMP and TIF/TIFF. Actual video
  decoding still depends on the local FFmpeg/OpenCV build and source codec.
- Use a separate local audio file as the soundtrack; common formats such as MP3,
  WAV and FLAC depend on the installed audio decoders. Audio-mix settings can
  preserve source sound and combine voice, music and effects; speech projects
  preserve their original speech by default.
- Detect scene boundaries, sample frames and produce paginated contact sheets,
  representative thumbnails and initial frames for subject selection.
- Measure motion, brightness and visual similarity; use stable asset/clip IDs
  and absolute paths so identical basenames in different folders remain distinct.
- Respect photo EXIF orientation, probe video rotation/dimensions/frame rate, and
  normalize selected media to the output format.
- Extract ZIP contents persistently under the project's analysis directory so
  later revisions can still access them. Keep those imports with the project.

**Content-aware selection requires visual review.** The agent looks at the
contact sheets and relevant source frames, then records tags, shot size, quality,
exclusions, a subject box and meaningful action times. The analysis scripts do
not identify cars, recognize kills, understand a story or label unseen actions
by themselves. Planning uses those observations together with measured energy,
shot variety and recent visual similarity; it is a scoring system, not a
guarantee that every selected shot tells the intended story.

## Music, pacing and duration

| Capability | How it works / control |
|---|---|
| Beat and tempo analysis | Beats, onset density, energy phases, silence/hard stops, phrase/event hypotheses, pulse confidence and energetic excerpts. |
| Soundtrack excerpt | Start from a suggested excerpt or set an exact `--audio-start` in seconds. |
| Musical structure | Estimate `intro`, `build`, `drop`, `outro` sections; provide explicit section ranges when the estimate misses the intended structure. |
| Cut density | Change every section with `--beat-stride`, or one section with repeated `--section-stride NAME=N` options. A stride of 1 targets every beat; larger values produce fewer cuts. |
| Shot length | Set nominal minimum/maximum shot duration. Section boundaries and available source ranges can require a shorter remainder. |
| Action alignment | Mark a source action time and anchor it to a chosen fraction of a shot, allowing an impact or reveal to meet a beat. The resulting speed still has to pass policy checks. |
| Exact final duration | Plan in output frames: 25 seconds at 30 fps is 750 frames. Other requested durations are rounded to the nearest output frame. |
| Footage shortages | Use unused source ranges or permitted photo holds; fail when constraints cannot be met. Reuse video only when explicitly allowed. No hidden slow motion or early finish to fill a shortage. |

Beat and section detection are estimates. `--pacing-mode auto` chooses beat cuts
when onset evidence supports them, otherwise longer phrase/event-driven holds.
No measured beats means no invented beat grid. `music-override` accepts bounded
manual beats/events/phrases plus a reason and retains an audit trail. Review the
actual music; successful analysis is not proof of musical alignment.

## Presets and built-in picture effects

Presets provide initial preferences and can be overridden by the request. They
do not authorize slow motion. The stride columns below are beats per planned
cut in **intro / build / drop / outro**; shot ranges are nominal seconds.

| Preset | Typical subject / shot order | Strides | Shot range | Grade | Drop accents and looks |
|---|---|---|---|---|---|
| `cinematic` | Travel, landscape, portrait; wide → medium → close | 8 / 4 / 2 / 8 | 0.8–6.0 | `cinematic` | flash 0.08, zoom 1.04× |
| `car` | Cars, wheels, driving; wide → detail → action → close | 4 / 2 / 1 / 4 | 0.2–3.0 | `cool` | flash 0.65, zoom 1.15×, shake 0.25 |
| `gaming` | Gameplay/action/highlights; wide → action → close → action | 4 / 2 / 1 / 2 | 0.15–2.0 | `vivid` | flash 0.45, zoom 1.12×, shake 0.15 |
| `product` | Product, fashion, packaging; wide → detail → close → medium | 4 / 4 / 2 / 4 | 0.6–4.0 | `warm` | flash 0.10, zoom 1.06× |
| `phonk` | Drift, night, street, fights; action → close → detail → action | 4 / 2 / 1 / 2 | 0.15–2.0 | `moody` | RGB split 0.7, glitch 0.5, flash 0.3, shake 0.35, beat pulse 0.5; vignette 0.45, grain 0.25 |
| `anime` | Anime/AMV, characters, fights; close → action → wide → close | 4 / 2 / 1 / 4 | 0.2–2.5 | `vivid` | flash 0.7, stretch 0.35, RGB split 0.4, beat pulse 0.6; glow 0.35 |
| `travel` | Travel, city, food, people; wide → medium → detail → wide | 8 / 4 / 2 / 8 | 0.9–6.0 | `vintage` | black dip 0.5, zoom 1.05×; vignette 0.25, grain 0.12 |

Accent effects (flash, dip, invert, RGB split, glitch, stretch, blur-in) and
shake appear only on accent cuts of the drop: its first on-beat cut and every
4th on-beat cut (every 2nd for `phonk` and `anime`). Elsewhere the planner turns
them off and reduces zoom accents; beat pulses stay in build/drop only. Looks
(grade, vignette, grain, glow, letterbox) apply to every shot. These shot-order
preferences depend on reviewed labels and available footage; they are not
mandatory sequences. `edit presets` shows the full current recipes and
`plan --effect NAME=VALUE` overrides any preset value.

The project renderer provides, as per-shot, cached and revisable effects that
never overlap shots or change the frame count:

- Cut accents: white flash, dip from black, invert hit, RGB split, glitch
  slices, horizontal stretch hit and blur-in.
- Transitions without overlap: motion-blurred whip out of one shot and into the
  next, plus flash/dip/glitch/RGB/blur/zoom transitions set with one
  `transition` revision on a cut, a section or every cut.
- Motion: quick zoom punches on video, gradual push-ins on photos, camera
  shake and zoom pulses on every measured beat inside a shot.
- Looks: vignette, deterministic film grain, highlight glow and letterbox bars.
- Ten grades: `none`/`neutral`, `cinematic`, `cool`, `warm`, `vivid`, `mono`,
  `teal_orange`, `vintage`, `moody`.
- Per-shot, per-section or whole-project revisions, including resetting all
  effects, removing flashes or preserving natural color.

Hue cycling, strobe sequences and custom curves remain in the separate custom
FFmpeg cookbook of the legacy workflow. See
[effects and looks](../skills/beat-sync-edit/references/effects-and-looks.md)
for ranges, transitions and request-to-operation recipes.

## Framing, tracking and playback speed

| Framing mode | Result |
|---|---|
| `auto` | Follow a selected initial subject box; without a box, use face/motion cues. Smooth the crop path. |
| `center` | Fixed central crop that fills the requested frame. |
| `manual` | Fixed subject framing or authored source-time camera keyframes. |
| `contain` | Keep the complete image within the output, adding bars as needed. |

Tracking is visual tracking, not identity recognition. Occlusion, cuts, fast
motion, camera motion or multiple subjects can cause errors. A selected box
must describe the correct initial frame; preview the result and use fixed
framing or containment when necessary. A crop cannot restore content outside
the original frame.

Speed ramps use smooth changes in source-time progression, optionally with an
action anchor. Point values are relative weights, not literal playback speeds;
the selected source span and output duration determine the actual speed.
Automatic build/drop ramps now reserve additional unused footage so their slowest
point remains 1×. Without a surplus, constant-speed shots preserve exact duration.

**Video is never slowed by default.** The effective speed must stay at least
1× throughout every shot, including ramps, anchored actions and revisions.
“Cinematic,” “smooth,” high-FPS footage and insufficient material are not
permission to slow down. Slow motion requires both:

1. A direct slow-motion request in the user's prompt, recorded verbatim in the
   project policy.
2. Motion-compensated `optical_flow` frame interpolation.

Plain timestamp stretching, lowering playback FPS, duplicated-frame slowdown
and simple blending are forbidden substitutes. Interpolation failure stops
the render; it does not trigger a basic-slowdown fallback. Inspect moving edges
and occlusions because optical flow can introduce artifacts. This policy does
not make already low-quality or low-FPS source footage perfect.

See [project workflow](../skills/beat-sync-edit/references/project-workflow.md)
for the exact opt-in flags, source-range requirements and revision operations.

## Titles and subtitles

| Capability | Details |
|---|---|
| Titles | Add opening/closing text, labels or calls to action at exact output times. Multiple titles may overlap intentionally. |
| Typography | Unicode/Cyrillic with a suitable font; custom TTF/OTF, size, color, outline, translucent background, opacity, alignment, wrapping, maximum lines and safe margins. |
| Placement and motion | Top, center or bottom; static, fade or slide animation with adjustable entry/exit length. |
| Track or cue styles | Global title/subtitle styles plus individual overrides; `clean`, `boxed`, `karaoke` presets. |
| SRT / WebVTT | Import UTF-8 files, including BOM and multiline cues; export plain-text SRT/VTT sidecars. |
| Timing | Use finished-video timestamps or timestamps relative to the original soundtrack; shift, clip to the project and round to output frames. |
| Manual corrections | Add, replace, edit or delete cues; correct phrase times, shift the entire subtitle track or clear a text track. |
| Word highlighting | Highlight words using existing word timestamps, normally supplied by local speech recognition. |
| Local speech recognition | Optional Faster Whisper recognizes speech and returns timestamped phrases/words; CPU/int8 by default, configurable model/language/device. |

Important behavior:

- Text is burned into the MP4. SRT/VTT files are separate outputs, not switchable
  subtitle streams inside the video. Sidecars do not preserve project styling,
  animation or word highlighting.
- Import replaces the subtitle track through a recoverable revision. Formatting
  tags from the file are removed. Overlapping subtitle cues must be combined or
  corrected before import; titles are a separate layer and may overlap.
- Plain SRT/VTT has no word alignment: selecting `karaoke` does not invent word
  timings. Changing a phrase's text clears its obsolete word alignment; changing
  only its times rescales existing word ranges.
- The optional recognizer downloads a model on first use, then processes audio
  locally. An existing local model and `--local-files-only` support operation
  without a model download. GPU use requires a compatible local CUDA runtime.
- Recognition uses the final soundtrack excerpt by default. A separate aligned
  recording can supply caption text, but selecting it does not mix that recording
  into the video. Silence leaves existing captions unchanged.
- Recognition is not verified transcription or reliable lyric alignment. Check
  names, language, timing and sung words, especially over music. It does not add
  translation, speaker diarization or synthesized voice-over.
- Output-timed titles/captions stay fixed during picture revisions. Speech-mode
  captions are bound to stable source words and remapped through trims, nonlinear
  speed and reorder. Word/shot/source/action/beat/event anchors can also bind
  graphics and audio to meaningful events.
- Text-only changes preserve the base-shot cache and soundtrack. The text layer
  is composited after picture assembly.

See [titles and subtitles](../skills/beat-sync-edit/references/text-and-subtitles.md)
for installation of optional recognition, commands, style flags and examples.

## Revisions, preview and delivery

- Save a version-2 JSON project containing media references, source ranges,
  frame-based shot timing, musical sections, effects, framing, speed policy and
  text tracks. Keep the library, imported assets and originals to resume later.
- Replace a shot, reorder shots, change framing/effects/speed, or redistribute
  duration between shots while preserving the total. Validation rejects changes
  that exceed source ranges, break speed policy or otherwise make the project
  invalid. Duration changes can move cuts off the beat and need review.
- Save prior project JSON under `.history/` and record the revision operations.
  Invalid revisions leave the original project unchanged.
- Reuse unchanged rendered shots from a local cache. Cache reuse reduces repeated
  work; different output sizes and changed shots require their own rendering.
- Generate a smaller preview and an offline HTML review page with a player,
  shot navigation and a revision-file editor, including text/timing changes.
  The page exports JSON changes; apply them with `revise`. It is not a live
  timeline editor and does not update the project or render by itself.
- Render H.264/AAC MP4 with square pixels and 48 kHz audio at the requested
  dimensions/frame rate. The standard CLI accepts even dimensions and integer
  frame rates up to 120 fps; higher output FPS alone does not improve source motion.
- Produce a verification JSON containing measured dimensions, duration, video
  frame count, audio presence and cache information. Technical verification is
  followed by representative-frame and musical review; it does not certify
  aesthetic quality or platform acceptance.

## Specialized tools retained from the earlier workflow

| Tool / workflow | Available use and boundary |
|---|---|
| `beat_map.py` | Standalone music analysis and optional HTML energy/beat charts. The chart page uses a public Chart.js CDN; JSON analysis does not need it. |
| `clip_tag.py` | Standalone scene detection, energy tagging and thumbnails for the original JSON EDL workflow. |
| `plan_edit.py` | Original EDL planning: alternate highlight excerpts, whole-song planning, beat stride, exclusions, lead shots and pins. It can finish early when unique scenes run out; use projects for exact-duration work. |
| `render_edit.py` / `overunder_stack.py` | Render the original EDL, or apply over-under stacking to an existing video with the standalone tool. Duplicates the same view above/below; accepts a custom size (default 960×1080) and keeps audio if present. It is not stereoscopic depth generation. |
| `vertical_style.py` | Cover/contain/square framing, explicitly requested squeeze styling and extra pink/blue strength variants, warm, teal-orange and black-and-white grades. Bare defaults apply squeeze and pink; specify the requested look. |
| `flash_montage.py` | Authored square photo/video sequence with real overlapping white-flash transitions, subject punch-ins, width stretch, sway or gentle zoom. Final duration accounts for transition overlaps. |
| Custom FFmpeg cookbook | Per-segment hue changes, strobe sequences, custom curves and other filters the project effects do not cover. These require deliberate filter work and separate verification. |

The slow-motion restriction applies to every workflow, including custom filters.
See [legacy workflow](../skills/beat-sync-edit/references/legacy-workflow.md).

## Example requests

> Use $beat-sync-edit. Make a 25-second car edit from this folder and music file,
> 1080×1920 at 30 fps. Keep natural color, alternate wide and detail shots, speed
> up the cuts at the drop and remove flashes. Add “Night drive” for the first
> two seconds. Export MP4.

> Use $beat-sync-edit. Combine these product photos and clips into a 15-second
> square reel. Keep the product fully visible, add its name and price, and end
> with “Available now.”

> Use $beat-sync-edit. Add subtitles from this SRT, move them 0.2 seconds later,
> use a dark translucent box and keep them above the bottom controls. Preserve
> the montage. Export MP4 and a corrected VTT.

> Use $beat-sync-edit. Transcribe the speech in the final soundtrack locally,
> use short phrases with yellow word highlighting, and keep the transcript for
> correction. Export the captioned MP4 and SRT.

> Use $beat-sync-edit. Slow only the impact down to half speed with optical-flow
> interpolation. Keep the rest at normal speed or faster and inspect the edges
> around the moving subject.

## Extended project workflows

- **Speech-first montage:** import existing SRT/VTT or word-timed JSON before
  optional ASR; select phrase candidates, preserve requested pauses and place
  B-roll over continuous original speech. Correct stable word/segment IDs, apply
  supplied terminology and import translated/bilingual captions. Energy-gap
  review flags suspicious omissions without pretending noise is recognized
  speech. Repeated recordings can share the same loaded model configuration.
- **Audio:** preserve or mute source sound, add voice/music/SFX, set gain/fades,
  duck music under speech, normalize and measure the encoded result. Optional
  beat-grid/bar arrangement verifies source/output placement and regenerates
  the map; grid accuracy still requires listening.
- **Selection:** per-shot score components, source evidence and alternatives;
  reviewed query terms and explicit preference weights affect planning. Audited
  accept/reject/clear decisions persist. Calibration splits independent sources
  before training and reports held-out metrics and a baseline. It produces no
  model for insufficient data and makes no virality claim.
- **Graphics:** reusable styles, safe text zones and character-coverage
  diagnostics; local animated cards, counters, progress bars and image/text
  layers. A motion specification can render a reusable MP4. The optional
  Remotion adapter exports editable React and uses locally installed dependencies
  when rendering is requested; no cloud media generation is included.
- **Tracking:** source-time path/confidence reports highlight intervals for
  inspection; manual camera keyframes correct errors. Confidence is a diagnostic,
  not recognition of a particular person or vehicle.
- **Execution and export:** structured JSON results/errors, dry runs, input-bound
  plans, provenance, batch analysis/render with shared caches. Export QA decodes
  media, measures audio and black/silent intervals, and writes review frames.
  Intentional black/silence ranges are explicit rather than silently ignored.
- **Real-media evaluation:** reusable source/project-hashed cases for multiple
  subjects, occlusions/fast motion, quiet speech, names/languages, variable FPS and
  ambiguous music. Missed and false selections are evaluated against supplied
  labels. Missing or unreviewed cases do not pass. Synthetic tests establish
  deterministic mechanics, not artistic quality or real ASR/tracking accuracy.

Commands and examples: [speech](../skills/beat-sync-edit/references/speech-workflow.md),
[audio](../skills/beat-sync-edit/references/audio-workflow.md),
[music/editorial](../skills/beat-sync-edit/references/music-editorial.md),
[graphics/QA/batch](../skills/beat-sync-edit/references/workflow-extensions.md).

## Boundaries

This repository does not include footage/music generation, automatic media
search/download, TTS, automatic translation,
speaker identification, a full nonlinear editor,
or automatic posting to social platforms. It does not export a native Premiere,
DaVinci Resolve or CapCut project. References can guide a requested aspect such
as pacing or color after inspection; there is no automatic one-click style clone.
Some additional effects can be authored with FFmpeg, but they are custom work,
not guarantees of the built-in planner.

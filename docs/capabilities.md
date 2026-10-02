# Capabilities

[English README](../README.md) · [Русский README](../README.ru.md) · [Русская версия](capabilities.ru.md)

This is the capability reference for **Net2Fox's Codex fork** of `beat-synced-edit`.
The main workflow is a persistent editing project controlled through Codex or
`edit_project.py`. Separate legacy tools are described below; their effects are
not all switches in the project renderer.

## What you can make

| Edit | What the skill can do |
|---|---|
| TikTok, YouTube Shorts and Reels | Beat-synced vertical edits, normally 1080×1920, with selected shots, reframing, music, titles and captions. |
| Car and action edits | Alternate wide shots, details and action; increase cut density toward a drop; add short zoom punches, white flashes and shake. |
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
  WAV and FLAC depend on the installed audio decoders. Clip audio is not mixed
  into the soundtrack by the project renderer.
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
| Beat and tempo analysis | Detect beats, estimate tempo, measure energy, locate energy peaks/valleys and suggest high-energy excerpts. |
| Soundtrack excerpt | Start from a suggested excerpt or set an exact `--audio-start` in seconds. |
| Musical structure | Estimate `intro`, `build`, `drop`, `outro` sections; provide explicit section ranges when the estimate misses the intended structure. |
| Cut density | Change every section with `--beat-stride`, or one section with repeated `--section-stride NAME=N` options. A stride of 1 targets every beat; larger values produce fewer cuts. |
| Shot length | Set nominal minimum/maximum shot duration. Section boundaries and available source ranges can require a shorter remainder. |
| Action alignment | Mark a source action time and anchor it to a chosen fraction of a shot, allowing an impact or reveal to meet a beat. The resulting speed still has to pass policy checks. |
| Exact final duration | Plan in output frames: 25 seconds at 30 fps is 750 frames. Other requested durations are rounded to the nearest output frame. |
| Footage shortages | Use unused source ranges or permitted photo holds; fail when constraints cannot be met. Reuse video only when explicitly allowed. No hidden slow motion or early finish to fill a shortage. |

Beat and section detection are estimates. In unmetered audio or a range without
detected beats, the planner may use a tempo-grid fallback and records that fact.
Review the actual drop and cut rhythm; a successful analysis is not proof of
musical alignment.

## Presets and built-in picture effects

Presets provide initial preferences and can be overridden by the request. They
do not authorize slow motion. The stride columns below are beats per planned
cut in **intro / build / drop / outro**; shot ranges are nominal seconds.

| Preset | Typical subject / shot order | Strides | Shot range | Grade | Drop accents: flash / zoom / shake |
|---|---|---|---|---|---|
| `cinematic` | Travel, landscape, portrait; wide → medium → close | 8 / 4 / 2 / 8 | 0.8–6.0 | `cinematic` | 0.08 / 1.04× / 0 |
| `car` | Cars, wheels, driving; wide → detail → action → close | 4 / 2 / 1 / 4 | 0.2–3.0 | `cool` | 0.65 / 1.15× / 0.25 |
| `gaming` | Gameplay/action/highlights; wide → action → close → action | 4 / 2 / 1 / 2 | 0.15–2.0 | `vivid` | 0.45 / 1.12× / 0.15 |
| `product` | Product, fashion, packaging; wide → detail → close → medium | 4 / 4 / 2 / 4 | 0.6–4.0 | `warm` | 0.10 / 1.06× / 0 |

Flash/shake values are strengths from 0 to 1. Outside the drop, the planner
turns off flash/shake and reduces zoom accents. These shot-order preferences
depend on reviewed labels and available footage; they are not mandatory
sequences. Run `edit_project.py presets` to inspect the full current recipes.

The project renderer provides:

- Short white accents at cuts without overlapping away the output duration.
- Quick zoom punches on video; gradual push-ins on still photos.
- Adjustable camera-shake styling.
- `none`/`neutral`, `cinematic`, `cool`, `vivid` and `warm` grades.
- Per-shot, per-section or whole-project effect revisions, including removing
  all flashes or preserving natural color.

Glitches, RGB splits, black dips, hue cycling and other cookbook effects belong
to a separate custom FFmpeg workflow. They are not built-in project effects or
automatic consequences of asking for a preset.

## Framing, tracking and playback speed

| Framing mode | Result |
|---|---|
| `auto` | Follow a selected initial subject box; without a box, use face/motion cues. Smooth the crop path. |
| `center` | Fixed central crop that fills the requested frame. |
| `manual` | Fixed framing around the selected subject region. |
| `contain` | Keep the complete image within the output, adding bars as needed. |

Tracking is visual tracking, not identity recognition. Occlusion, cuts, fast
motion, camera motion or multiple subjects can cause errors. A selected box
must describe the correct initial frame; preview the result and use fixed
framing or containment when necessary. A crop cannot restore content outside
the original frame.

Speed ramps use smooth changes in source-time progression, optionally with an
action anchor. Point values are relative weights, not literal playback speeds;
the selected source span and output duration determine the actual speed.

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
- Titles/captions stay at absolute output times when picture shots are reordered
  or retimed. Shift them explicitly if their relationship to the audio changes.
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
| Custom FFmpeg cookbook | Per-segment black dips, stretch hits, hue changes, RGB split, shake, strobe/inversion, glow and grades. These require deliberate filter work and separate verification. |

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

## Boundaries

This repository does not include footage/music generation, automatic media
search/download, TTS, automatic translation, source-audio/voice-over mixing,
speaker identification, a full nonlinear editor, arbitrary animated graphics,
or automatic posting to social platforms. It does not export a native Premiere,
DaVinci Resolve or CapCut project. References can guide a requested aspect such
as pacing or color after inspection; there is no automatic one-click style clone.
Some additional effects can be authored with FFmpeg, but they are custom work,
not guarantees of the built-in planner.

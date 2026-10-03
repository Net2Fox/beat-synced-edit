# Video workflow expansion

Scope: implement the recommendations from the 2026-10-03 audit of this fork.
External generative-media services are explicitly excluded. Existing frame-exact
projects, natural-speed defaults, recoverable revisions and source preservation
remain invariants. A feature is complete only after its public workflow works.

## Requirements and completion evidence

| ID | Requirement | Evidence required |
|---|---|---|
| R01 | One complete Codex/Claude skill with synchronized scripts and references | Both packages validate, execute CLI and pass bundle drift check |
| R02 | Acceleration-only preset ramps allocate enough unused source | Non-flat automatic curves, bounds >= 1, no repeated ranges, render smoke |
| R03 | Source/voice/music/SFX mix, gains, fades, ducking and measured loudness | Synthetic waveform assertions plus encoded-output measurements |
| R04 | Shared source/output time mapping and word/beat/shot/action anchors | Trim, reorder, nonlinear speed and revision mapping tests |
| R05 | Speech-first projects, phrase candidates, preserved pauses and B-roll | Transcript-driven CLI project renders with original audible speech |
| R06 | Correctable stable words, ASR fallback/gap review and model reuse | Import/correction/retry tests; real ASR run or explicit unavailable evidence |
| R07 | Source-aware captions and supplied translations/glossary | Captions follow revised sources; bilingual SRT/VTT export and burn-in |
| R08 | Musical events, phrases, confidence and beat/phrase pacing | Pulsed/ambient/silence analysis and manual-override tests |
| R09 | Explained choices, alternatives, review feedback and calibration | Persist decisions, rank with preferences, evaluate missed/false selections |
| R10 | Style data, safe zones, Unicode font diagnostics and graphic layers | Configurable dimensions, pixel checks, reviewed renders and font report |
| R11 | Local motion graphics / optional Remotion adapter | Editable composition generates an importable rendered asset; no cloud |
| R12 | Tracking diagnostics, low-confidence review and manual keyframes | Moving-object fixture, saved confidence report and keyframe correction |
| R13 | Structured CLI results/errors, dry-run, input-bound plans and provenance | JSON remains parseable, changed-input rejection and schema/CLI tests |
| R14 | Export QA beyond metadata and review of actual MP4 | Decode, audio, black/silent intervals, contact sheet, intentional exceptions |
| R15 | Reusable real-media evaluation and batch analysis/export | Manifest/evaluation CLI, shared work and honest unavailable-review states |
| R16 | Optional music arrangement by bars with timing verification | Exact-length splice, correlation test, regenerated music map |
| R17 | Updated documentation, compatibility and independent workflow review | Full unit/smoke suite, isolated packaged-skill execution and reviewer findings |

## Verification policy

Synthetic media exercises mechanics and known ground truth. It does not establish
editorial quality, real-world tracking identity or speech-recognition accuracy.
Real-media review has a separate manifest/report and remains `not_reviewed` until
the relevant material is supplied and inspected. Never turn absent evidence into
a passing result. Do not require user media for deterministic checks that can be
performed with generated patterns and waveforms.

## Work ownership

- Audio implementation: audio mixer, audio commands, renderer audio integration.
- Speech implementation: shared timing, transcript editing, captions and revisions.
- Music implementation: analysis, planning, ramps and editorial feedback.
- Integration: CLI contract, graphics/style, tracking diagnostics, QA, packaging,
  documentation and cross-feature tests.

Completion is tracked by current code and test reports, not by this checklist.
